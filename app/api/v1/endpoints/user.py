import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.models import AuthToken, Region, User, UserRole
from app.schemas.schemas import MessageResponse, UserCreate, UserOut, UserUpdate

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


def _send_welcome_link(to: str, token: str, frontend_url: str) -> None:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from urllib.parse import quote
    from app.core.config import settings

    safe_token = quote(token, safe='')
    link = f"{frontend_url}/auth/verify?token={safe_token}"

    msg = MIMEMultipart('alternative')
    msg["Subject"] = "ЗЗК Реєстр — підтвердження акаунта"
    msg["From"] = settings.SMTP_USER
    msg["To"] = to

    plain_text = (
        f"Доброго дня!\n\n"
        f"Вас було додано до ЗЗК Реєстру. "
        f"Для першого входу перейдіть за посиланням:\n"
        f"<{link}>\n\n"
        f"Посилання дійсне 24 години."
    )

    html_text = f"""\
<!DOCTYPE html>
<html lang="uk">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;padding:40px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <tr><td style="padding-bottom:24px;">
          <h2 style="margin:0;color:#1a1a1a;font-size:22px;">ЗЗК Реєстр</h2>
        </td></tr>
        <tr><td style="color:#444;font-size:15px;line-height:1.6;padding-bottom:28px;">
          <p style="margin:0 0 12px 0;">Доброго дня!</p>
          <p style="margin:0;">Вас було додано до ЗЗК Реєстру.
          Для першого входу натисніть кнопку нижче.</p>
        </td></tr>
        <tr><td align="center" style="padding-bottom:28px;">
          <a href="{link}"
             style="display:inline-block;background:#4F46E5;color:#ffffff;text-decoration:none;
                    font-size:15px;font-weight:600;padding:14px 32px;border-radius:8px;">
            Підтвердити акаунт
          </a>
        </td></tr>
        <tr><td style="color:#888;font-size:13px;line-height:1.5;border-top:1px solid #eee;padding-top:20px;">
          <p style="margin:0 0 8px 0;">Якщо кнопка не працює, скопіюйте це посилання у браузер:</p>
          <p style="margin:0;word-break:break-all;color:#4F46E5;">{link}</p>
          <p style="margin:12px 0 0 0;">Посилання дійсне 24 години.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_text, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Помилка відправки welcome-листа: {e}")


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = await db.execute(select(User).where(User.email == body.email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email вже використовується")

    if body.region_id is not None:
        await _validate_region(body.region_id, db)

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

    from app.core.config import settings
    background_tasks.add_task(_send_welcome_link, body.email, token_value, settings.FRONTEND_URL)

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

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    data = body.model_dump(exclude_none=True)

    if "email" in data and data["email"] != user.email:
        dup = await db.execute(select(User).where(User.email == data["email"]))
        if dup.scalar_one_or_none():
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

    await db.delete(user)
    await db.commit()
    return MessageResponse(message="Користувача видалено")
