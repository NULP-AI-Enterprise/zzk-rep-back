import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, require_doctor_or_admin
from app.db.session import get_db
from app.models.models import ConsentFile, PatientProfile, User, UserRole
from app.schemas.schemas import (
    ConsentFileOut, ConsentFileRegister, ConsentUploadUrlResponse,
)

router = APIRouter(prefix="/patients/{patient_id}/consent", tags=["Consent"])


def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


async def _get_patient_or_403(patient_id: int, current_user: User, db: AsyncSession) -> PatientProfile:
    result = await db.execute(select(PatientProfile).where(PatientProfile.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")
    if current_user.role == UserRole.DOCTOR and patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    return patient


@router.post("/upload-url", response_model=ConsentUploadUrlResponse)
async def get_upload_url(
    patient_id: int,
    current_user: User = Depends(require_doctor_or_admin),
    db: AsyncSession = Depends(get_db),
):
    if not settings.S3_BUCKET:
        raise HTTPException(status_code=503, detail="S3 не налаштовано")
    await _get_patient_or_403(patient_id, current_user, db)

    s3_key = f"consent/{patient_id}/{uuid.uuid4()}.pdf"
    url = _s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": s3_key, "ContentType": "application/pdf"},
        ExpiresIn=900,
    )
    return ConsentUploadUrlResponse(upload_url=url, s3_key=s3_key)


@router.post("", response_model=ConsentFileOut, status_code=201)
async def register_consent_file(
    patient_id: int,
    body: ConsentFileRegister,
    current_user: User = Depends(require_doctor_or_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)

    record = ConsentFile(
        patient_id=patient_id,
        uploaded_by=current_user.id,
        s3_key=body.s3_key,
        original_filename=body.original_filename,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.get("", response_model=list[ConsentFileOut])
async def list_consent_files(
    patient_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(ConsentFile)
        .where(ConsentFile.patient_id == patient_id)
        .order_by(ConsentFile.uploaded_at.desc())
    )
    return result.scalars().all()


@router.get("/{file_id}/download-url")
async def get_download_url(
    patient_id: int,
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.S3_BUCKET:
        raise HTTPException(status_code=503, detail="S3 не налаштовано")
    await _get_patient_or_403(patient_id, current_user, db)

    result = await db.execute(
        select(ConsentFile).where(ConsentFile.id == file_id, ConsentFile.patient_id == patient_id)
    )
    cf = result.scalar_one_or_none()
    if not cf:
        raise HTTPException(status_code=404, detail="Файл не знайдено")

    url = _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": cf.s3_key},
        ExpiresIn=300,
    )
    return {"download_url": url}
