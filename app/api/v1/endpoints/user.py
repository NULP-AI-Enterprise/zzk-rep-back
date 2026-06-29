from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.models import User, UserRole
from app.schemas.schemas import MessageResponse, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(select(User).where(User.email == body.email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email вже використовується")

    user = User(
        email=body.email,
        role=body.role,
        first_name=body.first_name,
        last_name=body.last_name,
        patronymic=body.patronymic,
        region_id=body.region_id,
        job_position=body.job_position,
        job_place=body.job_place,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
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
    if current_user.id != user_id and current_user.role != UserRole.ADMIN:
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
    if current_user.id != user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ заборонено")

    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.region))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    await db.delete(user)
    await db.commit()
    return MessageResponse(message="Користувача видалено")