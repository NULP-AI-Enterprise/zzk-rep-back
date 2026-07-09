from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_doctor_or_admin
from app.core.security import decrypt_surname, encrypt_surname
from app.db.session import get_db
from app.models.models import (
    PatientProfile, PatientStatus, Region, User, UserRole,
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


async def _fetch_patient(patient_id: int, db: AsyncSession) -> PatientProfile:
    result = await db.execute(
        select(PatientProfile).options(*_load_options()).where(PatientProfile.id == patient_id)
    )
    return result.scalar_one()


def _serialize_surname(patient: PatientProfile, current_user: User) -> Optional[str]:
    if (
        current_user.role == UserRole.DOCTOR
        and current_user.id == patient.doctor_id
        and patient.surname_encrypted
    ):
        return decrypt_surname(patient.surname_encrypted)
    return None


async def _validate_doctor_id(doctor_id: int, db: AsyncSession) -> User:
    res = await db.execute(select(User).where(User.id == doctor_id))
    doctor = res.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=422, detail=f"Лікаря з id={doctor_id} не знайдено")
    if doctor.role != UserRole.DOCTOR:
        raise HTTPException(status_code=422, detail="Вказаний користувач не є лікарем")
    return doctor


async def _validate_region_id(region_id: int, db: AsyncSession) -> None:
    res = await db.execute(select(Region).where(Region.id == region_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=422, detail=f"Регіон з id={region_id} не існує")


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
        q = q.join(User, PatientProfile.doctor_id == User.id).where(
            User.region_id == current_user.region_id
        )

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
        q = q.join(User, PatientProfile.doctor_id == User.id).where(
            User.region_id == current_user.region_id
        )

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
        q = q.join(User, PatientProfile.doctor_id == User.id).where(
            User.region_id == current_user.region_id
        )

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

    if current_user.role == UserRole.DOCTOR and patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    out = PatientOut.model_validate(patient)
    out.surname = _serialize_surname(patient, current_user)
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
        raise HTTPException(status_code=409, detail="Email вже використовується")

    # Validate FK references before inserting
    doctor_id = body.doctor_id
    if doctor_id is None and current_user.role == UserRole.DOCTOR:
        doctor_id = current_user.id
    if doctor_id is not None:
        await _validate_doctor_id(doctor_id, db)

    if body.region_id is not None:
        await _validate_region_id(body.region_id, db)

    encrypted = encrypt_surname(body.surname) if body.surname else None

    patient = PatientProfile(
        doctor_id=doctor_id,
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

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email вже використовується")

    patient = await _fetch_patient(patient.id, db)
    out = PatientOut.model_validate(patient)
    out.surname = _serialize_surname(patient, current_user)
    return out


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: int,
    body: PatientUpdate,
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

    data = body.model_dump(exclude_none=True)

    if "email" in data and data["email"] != patient.email:
        dup = await db.execute(
            select(PatientProfile).where(PatientProfile.email == data["email"])
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email вже використовується")

    if "doctor_id" in data:
        await _validate_doctor_id(data["doctor_id"], db)

    if "region_id" in data:
        await _validate_region_id(data["region_id"], db)

    if "surname" in data:
        patient.surname_encrypted = encrypt_surname(data.pop("surname"))

    for field, value in data.items():
        setattr(patient, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Конфлікт даних при оновленні")

    patient = await _fetch_patient(patient_id, db)
    out = PatientOut.model_validate(patient)
    out.surname = _serialize_surname(patient, current_user)
    return out


@router.patch("/{patient_id}/status", response_model=PatientOut)
async def update_status(
    patient_id: int,
    body: PatientStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DOCTOR:
      - PENDING/DETACHED → ATTACHED: дозволено якщо пацієнт без лікаря або вже цього лікаря;
        doctor_id автоматично встановлюється на current_user.id
      - ATTACHED → DETACHED: дозволено тільки для свого пацієнта
      - Будь-який інший перехід: 403
    MODERATOR/ADMIN: будь-який перехід; при ATTACHED — doctor_id обов'язковий
    """
    result = await db.execute(
        select(PatientProfile).where(PatientProfile.id == patient_id)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")

    is_moderator_or_admin = current_user.role in (UserRole.MODERATOR, UserRole.ADMIN)
    is_doctor = current_user.role == UserRole.DOCTOR

    if is_doctor:
        if body.status == PatientStatus.ATTACHED:
            # Лікар може підтвердити/прикріпити пацієнта якщо той ще без лікаря
            # або вже прикріплений до цього ж лікаря
            if patient.doctor_id is not None and patient.doctor_id != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Пацієнт вже прикріплений до іншого лікаря",
                )
            patient.doctor_id = current_user.id
        elif body.status == PatientStatus.DETACHED:
            if patient.doctor_id != current_user.id:
                raise HTTPException(status_code=403, detail="Доступ заборонено")
            patient.doctor_id = None
        else:
            raise HTTPException(
                status_code=403,
                detail="Лікар може лише підтвердити (ATTACHED) або відкріпити (DETACHED) пацієнта",
            )
    elif is_moderator_or_admin:
        if body.status == PatientStatus.ATTACHED:
            if not body.doctor_id:
                raise HTTPException(
                    status_code=400,
                    detail="doctor_id обов'язковий при статусі ATTACHED",
                )
            await _validate_doctor_id(body.doctor_id, db)
            patient.doctor_id = body.doctor_id
        elif body.status == PatientStatus.DETACHED:
            patient.doctor_id = None
        # PENDING — лише скидання без зміни doctor_id
    else:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    patient.status = body.status
    await db.commit()

    patient = await _fetch_patient(patient_id, db)
    out = PatientOut.model_validate(patient)
    out.surname = _serialize_surname(patient, current_user)
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
