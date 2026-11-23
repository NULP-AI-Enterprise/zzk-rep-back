from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.db.session import get_db
from app.models.models import User, UserRole, PatientProfile

bearer_scheme = HTTPBearer()


async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: AsyncSession = Depends(get_db),
) -> User | PatientProfile:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        sub: str = payload.get("sub")

        if not sub or ":" not in sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалідний токен структури")

        entity_type, entity_id_raw = sub.split(":", 1)
        entity_id = int(entity_id_raw)

    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалідний токен")

    if entity_type == "user":
        result = await db.execute(
            select(User)
            .where(User.id == entity_id)
            .options(selectinload(User.region))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Користувача не знайдено")
        return user

    elif entity_type == "patient":
        # ВИПРАВЛЕНО: додано selectinload для регіону, щоб уникнути MissingGreenlet
        result = await db.execute(
            select(PatientProfile)
            .where(PatientProfile.id == entity_id)
            .options(selectinload(PatientProfile.region))
        )
        patient = result.scalar_one_or_none()
        if patient is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Профіль пацієнта не знайдено")
        return patient

    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невідомий тип авторизації")


def require_roles(*roles: UserRole):
    """Фабрика залежностей для перевірки ролі."""

    async def _check(
            current_user: User | PatientProfile = Depends(get_current_user)
    ) -> User | PatientProfile:
        # У пацієнтів немає поля .role в БД, але є @property,
        # тому перевіряємо, чи це пацієнт, чи користувач з роллю

        # Якщо це PatientProfile, ми знаємо, що він завжди має роль PATIENT
        user_role = getattr(current_user, "role", None)

        # Для пацієнтів, якщо у них немає явно `role` в об'єкті, задаємо її
        if isinstance(current_user, PatientProfile):
            user_role = UserRole.PATIENT

        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Доступ заборонено. Потрібна роль: {[r.value for r in roles]}",
            )
        return current_user

    return _check


require_admin = require_roles(UserRole.ADMIN)
require_doctor_or_admin = require_roles(UserRole.DOCTOR, UserRole.ADMIN)
require_moderator_or_admin = require_roles(UserRole.MODERATOR, UserRole.ADMIN)
require_any = require_roles(UserRole.DOCTOR, UserRole.PATIENT, UserRole.MODERATOR, UserRole.ADMIN)


async def _load_patient(patient_id: int, db: AsyncSession) -> PatientProfile:
    result = await db.execute(select(PatientProfile).where(PatientProfile.id == patient_id))
    patient = result.scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")
    return patient


async def _in_moderator_region(patient: PatientProfile, user: User, db: AsyncSession) -> bool:
    rid = user.region_id
    if rid is None:
        return False
    if patient.region_id == rid:
        return True
    if patient.doctor_id is not None:
        doc = await db.execute(select(User.region_id).where(User.id == patient.doctor_id))
        return doc.scalar_one_or_none() == rid
    return False


async def get_accessible_patient(
        patient_id: int,
        current_user: User | PatientProfile,
        db: AsyncSession,
        write: bool = False,
) -> PatientProfile:
    """Доступ до медичних даних.
    PATIENT   — лише свої
    DOCTOR    — лише своїх пацієнтів
    ADMIN     — усі (власник)
    MODERATOR — знеособлені дані пацієнтів СВОГО регіону, лише читання (write=True -> 403)
    """
    patient = await _load_patient(patient_id, db)

    if isinstance(current_user, PatientProfile):
        if patient.id == current_user.id:
            return patient
    elif current_user.role == UserRole.ADMIN:
        return patient
    elif current_user.role == UserRole.DOCTOR:
        if patient.doctor_id == current_user.id:
            return patient
    elif current_user.role == UserRole.MODERATOR and not write:
        if await _in_moderator_region(patient, current_user, db):
            return patient

    raise HTTPException(status_code=403, detail="Доступ заборонено")


async def get_patient_for_management(
        patient_id: int,
        current_user: User | PatientProfile,
        db: AsyncSession,
) -> PatientProfile:
    if isinstance(current_user, User) and current_user.role in (UserRole.ADMIN, UserRole.MODERATOR):
        patient = await _load_patient(patient_id, db)
        if current_user.role == UserRole.ADMIN or await _in_moderator_region(patient, current_user, db):
            return patient
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    return await get_accessible_patient(patient_id, current_user, db)