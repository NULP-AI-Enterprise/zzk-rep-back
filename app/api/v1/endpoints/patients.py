import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_any, require_doctor_or_admin
from app.core.security import decrypt_surname, encrypt_surname
from app.core.config import settings
from app.db.session import get_db
from app.models.models import (
    AuthToken, PatientLabResult, PatientProfile, PatientStatus, Region, User, UserRole,
)
from app.schemas.schemas import (
    ConfirmEmailChange, EmailChangeRequest, MessageResponse,
    PatientCreate, PatientLabResultCreate, PatientLabResultOut,
    PatientListItem, PatientOut, PatientStatusUpdate, PatientUpdate,
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


@router.get("/{patient_id}/lab-results", response_model=list[PatientLabResultOut])
async def list_patient_lab_results(
    patient_id: int,
    current_user: User | PatientProfile = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    patient = await _fetch_patient(patient_id, db)
    # Patients can only view their own results
    if isinstance(current_user, PatientProfile) and current_user.id != patient_id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    result = await db.execute(
        select(PatientLabResult)
        .options(selectinload(PatientLabResult.added_by_user))
        .where(PatientLabResult.patient_id == patient_id)
        .order_by(PatientLabResult.result_date)
    )
    rows = result.scalars().all()
    out = []
    for r in rows:
        added_by_name = None
        if r.added_by_user:
            added_by_name = f"{r.added_by_user.last_name} {r.added_by_user.first_name}"
        out.append(PatientLabResultOut(
            id=r.id,
            lab_type=r.lab_type,
            value=float(r.value),
            result_date=r.result_date,
            added_by_role=r.added_by_role,
            added_by_name=added_by_name,
            created_at=r.created_at,
        ))
    return out


@router.post("/{patient_id}/lab-results", response_model=PatientLabResultOut, status_code=201)
async def add_patient_lab_result(
    patient_id: int,
    body: PatientLabResultCreate,
    current_user: User | PatientProfile = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    patient = await _fetch_patient(patient_id, db)

    if isinstance(current_user, PatientProfile):
        if current_user.id != patient_id:
            raise HTTPException(status_code=403, detail="Доступ заборонено")
        added_by_user_id = None
        added_by_role = "PATIENT"
    else:
        if current_user.role == UserRole.DOCTOR and patient.doctor_id != current_user.id:
            raise HTTPException(status_code=403, detail="Доступ заборонено")
        added_by_user_id = current_user.id
        added_by_role = current_user.role.value

    lab = PatientLabResult(
        patient_id=patient_id,
        lab_type=body.lab_type,
        value=body.value,
        result_date=body.result_date,
        added_by_user_id=added_by_user_id,
        added_by_role=added_by_role,
    )
    db.add(lab)
    await db.commit()
    await db.refresh(lab)

    added_by_name = None
    if added_by_user_id:
        user_res = await db.execute(select(User).where(User.id == added_by_user_id))
        u = user_res.scalar_one_or_none()
        if u:
            added_by_name = f"{u.last_name} {u.first_name}"

    return PatientLabResultOut(
        id=lab.id,
        lab_type=lab.lab_type,
        value=float(lab.value),
        result_date=lab.result_date,
        added_by_role=lab.added_by_role,
        added_by_name=added_by_name,
        created_at=lab.created_at,
    )


@router.post("/{patient_id}/request-email-change", response_model=MessageResponse)
async def request_email_change(
    patient_id: int,
    body: EmailChangeRequest,
    background_tasks: BackgroundTasks,
    current_user: User | PatientProfile = Depends(require_doctor_or_admin),
    db: AsyncSession = Depends(get_db),
):
    import smtplib
    from email.mime.text import MIMEText

    patient = await _fetch_patient(patient_id, db)
    if current_user.role == UserRole.DOCTOR and patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    # Check new email not already taken
    dup = await db.execute(
        select(PatientProfile).where(PatientProfile.email == str(body.new_email))
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email вже використовується")

    token_value = secrets.token_urlsafe(48)
    auth_token = AuthToken(
        token=token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        patient_id=patient_id,
        purpose='email_change',
    )

    # Fetch patient row to update pending_email
    pat_res = await db.execute(select(PatientProfile).where(PatientProfile.id == patient_id))
    pat = pat_res.scalar_one()
    pat.pending_email = str(body.new_email)

    db.add(auth_token)
    await db.commit()

    def _send(to: str, token: str) -> None:
        link = f"{settings.FRONTEND_URL}/auth/confirm-email?token={token}"
        msg = MIMEText(
            f"Доброго дня!\n\nДля підтвердження зміни email перейдіть за посиланням:\n{link}\n\n"
            f"Посилання дійсне 24 години.",
            "plain",
            "utf-8",
        )
        msg["Subject"] = "ЗЗК Реєстр — підтвердження зміни Email"
        msg["From"] = settings.SMTP_USER
        msg["To"] = to
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        except Exception as e:
            print(f"Помилка відправки листа: {e}")

    background_tasks.add_task(_send, str(body.new_email), token_value)

    return MessageResponse(message="Листа з підтвердженням надіслано на новий email")


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
