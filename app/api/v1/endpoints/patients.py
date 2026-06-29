from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_doctor_or_admin
from app.core.security import decrypt_surname, encrypt_surname
from app.db.session import get_db
from app.models.models import (
    PatientProfile, PatientStatus, User, UserRole,
)
from app.schemas.schemas import (
    MessageResponse, PatientCreate, PatientListItem,
    PatientOut, PatientStatusUpdate, PatientUpdate,
)

router = APIRouter(prefix="/patients", tags=["Patients"])


def _load_options():
    return [
        selectinload(PatientProfile.doctor).selectinload(User.region),
        selectinload(PatientProfile.region),
    ]


def _serialize_patient(patient: PatientProfile, current_user: User) -> dict:
    """
    Прізвище дешифрується ТІЛЬКИ якщо current_user є лікарем цього пацієнта.
    ADMIN, MODERATOR, інші лікарі — бачать None.
    """
    surname = None
    if (
        current_user.role == UserRole.DOCTOR
        and current_user.id == patient.doctor_id
        and patient.surname_encrypted
    ):
        surname = decrypt_surname(patient.surname_encrypted)
    return surname


@router.get("", response_model=list[PatientListItem])
async def list_patients(
    status_filter: Optional[PatientStatus] = Query(None, alias="status"),
    diagnosis: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in (UserRole.DOCTOR, UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    q = select(PatientProfile).options(*_load_options())

    if current_user.role == UserRole.DOCTOR:
        q = q.where(PatientProfile.doctor_id == current_user.id)

    elif current_user.role == UserRole.MODERATOR:
        q = q.where(PatientProfile.region_id == current_user.region_id)

    if status_filter:
        q = q.where(PatientProfile.status == status_filter)
    if diagnosis:
        q = q.where(PatientProfile.diagnosis == diagnosis)

    result = await db.execute(q.order_by(PatientProfile.created_at.desc()))
    return result.scalars().all()


@router.get("/pending", response_model=list[PatientListItem])
async def list_pending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in (UserRole.DOCTOR, UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    q = select(PatientProfile).options(*_load_options()).where(
        PatientProfile.status == PatientStatus.PENDING
    )

    if current_user.role == UserRole.DOCTOR:
        q = q.where(PatientProfile.doctor_id == current_user.id)

    elif current_user.role == UserRole.MODERATOR:
        q = q.where(PatientProfile.region_id == current_user.region_id)

    result = await db.execute(q.order_by(PatientProfile.created_at.desc()))
    return result.scalars().all()


@router.get("/attached", response_model=list[PatientListItem])
async def list_attached(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in (UserRole.DOCTOR, UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    q = select(PatientProfile).options(*_load_options()).where(
        PatientProfile.status == PatientStatus.ATTACHED
    )
    if current_user.role == UserRole.DOCTOR:
        q = q.where(PatientProfile.doctor_id == current_user.id)

    elif current_user.role == UserRole.MODERATOR:
        q = q.where(PatientProfile.region_id == current_user.region_id)

    result = await db.execute(q.order_by(PatientProfile.created_at.desc()))
    return result.scalars().all()


@router.get("/detached", response_model=list[PatientListItem])
async def list_detached(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in (UserRole.DOCTOR, UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    q = select(PatientProfile).options(*_load_options()).where(
        PatientProfile.status == PatientStatus.DETACHED
    )
    if current_user.role == UserRole.DOCTOR:
        q = q.where(PatientProfile.doctor_id == current_user.id)

    elif current_user.role == UserRole.MODERATOR:
        q = q.where(PatientProfile.region_id == current_user.region_id)

    result = await db.execute(q.order_by(PatientProfile.created_at.desc()))
    return result.scalars().all()


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(
    patient_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PatientProfile).options(*_load_options()).where(PatientProfile.id == patient_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")

    if current_user.role == UserRole.PATIENT and patient.id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    if current_user.role in (UserRole.DOCTOR, UserRole.ADMIN, UserRole.MODERATOR) \
            and patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    out = PatientOut.model_validate(patient)
    out.surname = _serialize_patient(patient, current_user)
    return out


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(
    body: PatientCreate,
    current_user: User = Depends(require_doctor_or_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(
        select(PatientProfile).where(PatientProfile.email == body.email)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email вже використовується")

    encrypted = encrypt_surname(body.surname) if body.surname else None

    patient = PatientProfile(
        doctor_id=body.doctor_id,
        surname_encrypted=encrypted,
        initials=body.initials,
        sex=body.sex,
        region_id=body.region_id,
        email=body.email,
        birth_year=body.birth_year,
        weight=body.weight,
        height=body.height,
        disability=body.disability,
        diagnosis=body.diagnosis,
        histologically_confirmed=body.histologically_confirmed,
        diagnosis_year=body.diagnosis_year,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    out = PatientOut.model_validate(patient)
    out.surname = _serialize_patient(patient, current_user)
    return out


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: int,
    body: PatientUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PatientProfile).where(PatientProfile.id == patient_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")

    if current_user.role not in (UserRole.DOCTOR, UserRole.ADMIN, UserRole.MODERATOR):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    if patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    data = body.model_dump(exclude_none=True)

    if "surname" in data:
        patient.surname_encrypted = encrypt_surname(data.pop("surname"))

    for field, value in data.items():
        setattr(patient, field, value)

    await db.commit()
    await db.refresh(patient)

    out = PatientOut.model_validate(patient)
    out.surname = _serialize_patient(patient, current_user)
    return out


@router.patch("/{patient_id}/status", response_model=PatientOut)
async def update_status(
    patient_id: int,
    body: PatientStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Правила зміни статусу:

    DOCTOR:
      - може тільки ATTACHED → DETACHED (відкріпити свого пацієнта)
      - doctor_id пацієнта стає NULL автоматично
      - інші переходи заборонені

    MODERATOR / ADMIN:
      - будь-який перехід
      - при ATTACHED або PENDING — doctor_id обов'язковий
      - при DETACHED — doctor_id автоматично стає NULL
    """
    result = await db.execute(
        select(PatientProfile).options(*_load_options()).where(PatientProfile.id == patient_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")

    is_moderator_or_admin = current_user.role in (UserRole.MODERATOR, UserRole.ADMIN)
    is_doctor = current_user.role == UserRole.DOCTOR

    if is_doctor:
        if patient.doctor_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ заборонено")
        if body.status != PatientStatus.DETACHED:
            raise HTTPException(
                status_code=403,
                detail="Лікар може лише відкріпити пацієнта (DETACHED)",
            )

    elif not is_moderator_or_admin:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    if body.status in (PatientStatus.ATTACHED, PatientStatus.PENDING):
        if not is_doctor and not body.doctor_id:
            raise HTTPException(
                status_code=400,
                detail="doctor_id обов'язковий при статусі ATTACHED або PENDING",
            )

    patient.status = body.status

    if body.status == PatientStatus.DETACHED:
        patient.doctor_id = None
    elif is_moderator_or_admin and body.doctor_id:
        patient.doctor_id = body.doctor_id
    elif is_doctor and body.status == PatientStatus.DETACHED:
        patient.doctor_id = None

    await db.commit()
    await db.refresh(patient)

    out = PatientOut.model_validate(patient)
    out.surname = _serialize_patient(patient, current_user)
    return out


@router.delete("/{patient_id}", response_model=MessageResponse)
async def delete_patient(
    patient_id: int,
    current_user: User = Depends(require_doctor_or_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PatientProfile).where(PatientProfile.id == patient_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")

    if current_user.role == UserRole.DOCTOR and patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    await db.delete(patient)
    await db.commit()
    return MessageResponse(message="Пацієнта видалено")