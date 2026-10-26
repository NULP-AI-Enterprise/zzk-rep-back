import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.endpoints.auth import send_login_link
from app.core.deps import get_current_user, require_admin, require_moderator_or_admin
from app.db.session import get_db
from app.models.models import AuthToken, PatientProfile, PatientStatus, Region, User, UserRole
from app.schemas.schemas import DoctorBrief, MessageResponse, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


async def _validate_region(region_id: int, db: AsyncSession) -> None:
    res = await db.execute(select(Region).where(Region.id == region_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=422, detail=f"Регіон з id={region_id} не існує")


async def _fetch_user_with_region(user_id: int, db: AsyncSession) -> User:
    result = await db.execute(
        select(User).options(selectinload(User.region)).where(User.id == user_id)
    )
    return result.scalar_one()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    email = body.email.strip().lower()
    exists = await db.execute(select(User).where(func.lower(User.email) == email))
    patient_exists = await db.execute(
        select(PatientProfile.id).where(func.lower(PatientProfile.email) == email)
    )
    if exists.scalar_one_or_none() or patient_exists.first():
        raise HTTPException(status_code=409, detail="Email вже використовується")

    if body.region_id is not None:
        await _validate_region(body.region_id, db)

    user = User(
        email=email,
        role=body.role,
        first_name=body.first_name,
        last_name=body.last_name,
        patronymic=body.patronymic,
        region_id=body.region_id,
        job_position=body.job_position,
        job_place=body.job_place,
    )
    db.add(user)
    await db.flush()  # get user.id before creating token

    token_value = secrets.token_urlsafe(48)
    db.add(AuthToken(
        token=token_value,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ))

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email вже використовується")

    user = await _fetch_user_with_region(user.id, db)

    background_tasks.add_task(send_login_link, email, token_value, welcome=True, valid_for="24 години")

    return user


@router.get("", response_model=list[UserOut])
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).options(selectinload(User.region)).order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.get("/doctors", response_model=list[DoctorBrief])
async def list_doctors(
    current_user: User = Depends(require_moderator_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Doctors a patient can be attached to. Moderators only see doctors of their own region."""
    q = select(User).options(selectinload(User.region)).where(User.role == UserRole.DOCTOR)
    if current_user.role == UserRole.MODERATOR:
        q = q.where(User.region_id == current_user.region_id) if current_user.region_id is not None else q.where(False)
    result = await db.execute(q.order_by(User.last_name, User.first_name))
    return result.scalars().all()


@router.get("/search", response_model=list[UserOut])
async def search_users(
    name: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    pattern = f"%{name}%"
    result = await db.execute(
        select(User)
        .options(selectinload(User.region))
        .where(
            User.first_name.ilike(pattern)
            | User.last_name.ilike(pattern)
            | User.patronymic.ilike(pattern)
        )
    )
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # a PatientProfile id is unrelated to a User id — never compare them
    if not isinstance(current_user, User) or (
        current_user.id != user_id and current_user.role != UserRole.ADMIN
    ):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    result = await db.execute(
        select(User).options(selectinload(User.region)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not isinstance(current_user, User) or (
        current_user.id != user_id and current_user.role != UserRole.ADMIN
    ):
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    data = body.model_dump(exclude_none=True)

    # Only admins may change e-mail (login identity) or region (controls moderator data scope)
    # echoing the current values back (whole-object forms) is not a change
    for key, current in (("email", user.email), ("region_id", user.region_id), ("role", user.role)):
        if key in data and data[key] == current:
            data.pop(key)

    if current_user.role != UserRole.ADMIN and ({"email", "region_id", "role"} & data.keys()):
        raise HTTPException(status_code=403, detail="Email, регіон та роль може змінювати лише адміністратор")
    if "role" in data and user.id == current_user.id and data["role"] != user.role:
        raise HTTPException(status_code=400, detail="Не можна змінити власну роль")

    if "email" in data:
        data["email"] = data["email"].strip().lower()
        dup = await db.execute(
            select(User.id).where(func.lower(User.email) == data["email"], User.id != user_id)
        )
        dup_patient = await db.execute(
            select(PatientProfile.id).where(func.lower(PatientProfile.email) == data["email"])
        )
        if dup.first() or dup_patient.first():
            raise HTTPException(status_code=409, detail="Email вже використовується")

    if "region_id" in data:
        await _validate_region(data["region_id"], db)

    for field, value in data.items():
        setattr(user, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Конфлікт даних при оновленні")

    return await _fetch_user_with_region(user_id, db)


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Не можна видалити власний акаунт")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    # Their patients lose the doctor (FK SET NULL): put them back into the shared pool
    await db.execute(
        update(PatientProfile)
        .where(PatientProfile.doctor_id == user_id, PatientProfile.status == PatientStatus.ATTACHED)
        .values(status=PatientStatus.DETACHED)
    )
    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Користувач має пов'язані клінічні записи — видалення неможливе",
        )
    return MessageResponse(message="Користувача видалено")
