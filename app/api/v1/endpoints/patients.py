import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import false, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.endpoints.auth import can_issue_login_token, send_login_link
from app.core.deps import get_accessible_patient, get_current_user, require_any, require_doctor_or_admin
from app.core.mailer import build_link, send_action_mail
from app.core.security import decrypt_surname, encrypt_surname
from app.db.session import get_db
from app.models.models import (
    AuthToken, PatientLabResult, PatientProfile, PatientStatus, Region, User, UserRole,
)
from app.schemas.schemas import (
    ConfirmEmailChange, EmailChangeRequest, MessageResponse,
    PatientCreate, PatientLabResultCreate, PatientLabResultOut,
    PatientListItem, PatientOut, PatientRegister, PatientStatusUpdate, PatientUpdate,
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


async def _email_taken(email: str, db: AsyncSession, exclude_patient_id: Optional[int] = None) -> bool:
    """Case-insensitive uniqueness across patients AND staff (login resolves users first)."""
    q = select(PatientProfile.id).where(func.lower(PatientProfile.email) == email)
    if exclude_patient_id is not None:
        q = q.where(PatientProfile.id != exclude_patient_id)
    if (await db.execute(q)).first():
        return True
    return (await db.execute(select(User.id).where(func.lower(User.email) == email))).first() is not None


def _moderator_region_filter(region_id: Optional[int]):
    """Patients of the moderator's region: by the patient's own region or by their doctor's region."""
    if region_id is None:
        return false()
    return or_(
        PatientProfile.region_id == region_id,
        PatientProfile.doctor_id.in_(select(User.id).where(User.region_id == region_id)),
    )


def _doctor_pool(doctor: User):
    """Patients nobody has taken yet (self-registered or detached) — any doctor may pick them up.

    Not limited to the doctor's region: patients choose their region themselves and may
    pick a different one than the doctor who will actually treat them.
    """
    return PatientProfile.doctor_id.is_(None)


def _scope_to_user(q, current_user: User):
    """Restrict a patient query to what the current staff user may see."""
    if current_user.role == UserRole.DOCTOR:
        return q.where(PatientProfile.doctor_id == current_user.id)
    if current_user.role == UserRole.MODERATOR:
        return q.where(_moderator_region_filter(current_user.region_id))
    return q


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register_patient(
    body: PatientRegister,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Public self-registration. Creates a PENDING patient without a doctor; staff attach later.

    The response is identical whether or not the e-mail is already known (no account enumeration).
    """
    generic = {"message": "Якщо дані коректні — на вказаний email надіслано посилання для входу"}
    email = body.email.strip().lower()

    # Global flood guard: public endpoint, so cap self-registrations per hour
    recent = await db.execute(
        select(func.count(PatientProfile.id)).where(
            PatientProfile.doctor_id.is_(None),
            PatientProfile.created_at > datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    if recent.scalar_one() >= 100:
        raise HTTPException(status_code=429, detail="Забагато реєстрацій. Спробуйте пізніше")

    await _validate_region_id(body.region_id, db)

    existing = await db.execute(select(PatientProfile).where(func.lower(PatientProfile.email) == email))
    existing_patient = existing.scalars().first()

    if existing_patient is None and await _email_taken(email, db):
        return generic  # belongs to staff — do nothing, reveal nothing

    if existing_patient is None:
        patient = PatientProfile(
            initials=body.initials,
            sex=body.sex,
            region_id=body.region_id,
            email=email,
            birth_year=body.birth_year,
            weight=body.weight,
            height=body.height,
            disability=body.disability,
            diagnosis=body.diagnosis,
            histologically_confirmed=body.histologically_confirmed,
            diagnosis_year=body.diagnosis_year,
            status=PatientStatus.PENDING,
        )
        db.add(patient)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return generic
    else:
        patient = existing_patient

    if await can_issue_login_token(db, patient_id=patient.id):
        token_value = secrets.token_urlsafe(48)
        db.add(AuthToken(
            token=token_value,
            patient_id=patient.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            purpose="login",
        ))
        await db.commit()
        background_tasks.add_task(send_login_link, patient.email, token_value, valid_for="24 години")
    else:
        await db.commit()
    return generic


@router.get("", response_model=list[PatientListItem])
async def list_patients(
    status_filter: Optional[PatientStatus] = Query(None, alias="status"),
    diagnosis: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in (UserRole.DOCTOR, UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    q = _scope_to_user(select(PatientProfile).options(*_load_options()), current_user)

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
        # own pending patients + self-registered patients still waiting for a doctor
        q = q.where(or_(PatientProfile.doctor_id == current_user.id, _doctor_pool(current_user)))
    else:
        q = _scope_to_user(q, current_user)

    result = await db.execute(q.order_by(PatientProfile.created_at.desc()))
    return result.scalars().all()


@router.get("/attached", response_model=list[PatientListItem])
async def list_attached(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in (UserRole.DOCTOR, UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    q = _scope_to_user(
        select(PatientProfile).options(*_load_options()).where(
            PatientProfile.status == PatientStatus.ATTACHED
        ),
        current_user,
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
        # a detach clears doctor_id, so detached patients live in the shared pool
        q = q.where(or_(PatientProfile.doctor_id == current_user.id, _doctor_pool(current_user)))
    elif current_user.role == UserRole.MODERATOR:
        q = q.where(_moderator_region_filter(current_user.region_id))

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

    # A doctor may open a self-registered patient who still has no doctor, to decide on attaching
    unassigned_pending = (
        isinstance(current_user, User)
        and current_user.role == UserRole.DOCTOR
        and patient.doctor_id is None
        and patient.status in (PatientStatus.PENDING, PatientStatus.DETACHED)
    )
    if not unassigned_pending:
        await get_accessible_patient(patient_id, current_user, db)

    out = PatientOut.model_validate(patient)
    out.surname = _serialize_surname(patient, current_user)
    return out


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(
    body: PatientCreate,
    current_user: User = Depends(require_doctor_or_admin),
    db: AsyncSession = Depends(get_db),
):
    email = body.email.strip().lower()
    if await _email_taken(email, db):
        raise HTTPException(status_code=409, detail="Email вже використовується")

    # Validate FK references before inserting. A doctor can only create patients for themselves.
    doctor_id = body.doctor_id
    if current_user.role == UserRole.DOCTOR:
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
        email=email,
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

    # echoing the current value back is harmless; only a real change is restricted
    if "email" in data and data["email"].strip().lower() == patient.email.lower():
        data.pop("email")
    if "doctor_id" in data and data["doctor_id"] == patient.doctor_id:
        data.pop("doctor_id")

    if "email" in data:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Email пацієнта змінюється через підтвердження на новий email",
            )
        data["email"] = data["email"].strip().lower()
        if data["email"] != patient.email.lower() and await _email_taken(data["email"], db, patient_id):
            raise HTTPException(status_code=409, detail="Email вже використовується")

    if "doctor_id" in data:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Змінити лікаря може лише адміністратор")
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
            # Atomic claim: two doctors confirming the same pool patient must not both succeed
            claimed = await db.execute(
                update(PatientProfile)
                .where(
                    PatientProfile.id == patient_id,
                    or_(PatientProfile.doctor_id.is_(None), PatientProfile.doctor_id == current_user.id),
                )
                .values(doctor_id=current_user.id)
            )
            if claimed.rowcount != 1:
                await db.rollback()
                raise HTTPException(status_code=409, detail="Пацієнта щойно прикріпив інший лікар")
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
        if current_user.role == UserRole.MODERATOR:
            await get_accessible_patient(patient_id, current_user, db)
        if body.status == PatientStatus.ATTACHED:
            if not body.doctor_id:
                raise HTTPException(
                    status_code=400,
                    detail="doctor_id обов'язковий при статусі ATTACHED",
                )
            doctor = await _validate_doctor_id(body.doctor_id, db)
            if current_user.role == UserRole.MODERATOR and doctor.region_id != current_user.region_id:
                raise HTTPException(status_code=403, detail="Можна прикріплювати лише до лікарів свого регіону")
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
    await get_accessible_patient(patient_id, current_user, db)

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
    await get_accessible_patient(patient_id, current_user, db)

    if isinstance(current_user, PatientProfile):
        added_by_user_id = None
        added_by_role = "PATIENT"
    else:
        if current_user.role == UserRole.MODERATOR:
            raise HTTPException(status_code=403, detail="Модератор не може додавати результати")
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
    patient = await get_accessible_patient(patient_id, current_user, db)

    new_email = str(body.new_email).strip().lower()
    if await _email_taken(new_email, db, patient_id):
        raise HTTPException(status_code=409, detail="Email вже використовується")

    # Only the newest request may be confirmed: older pending links must not apply a different address
    now = datetime.now(timezone.utc)
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.patient_id == patient_id,
            AuthToken.purpose == "email_change",
            AuthToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    token_value = secrets.token_urlsafe(48)
    db.add(AuthToken(
        token=token_value,
        expires_at=now + timedelta(hours=24),
        patient_id=patient_id,
        purpose="email_change",
    ))
    patient.pending_email = new_email
    await db.commit()

    background_tasks.add_task(
        send_action_mail,
        new_email,
        "ЗЗК Реєстр — підтвердження зміни Email",
        "Для підтвердження зміни email натисніть кнопку нижче.",
        "Підтвердити email",
        build_link("/auth/confirm-email", token_value),
        "24 години",
    )

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
