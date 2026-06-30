import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from typing import Union
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.models import AuthToken, User, PatientProfile
from app.schemas.schemas import TokenResponse, UserOut, PatientMeOut

router = APIRouter(prefix="/auth", tags=["Auth"])


class SendLinkRequest(BaseModel):
    email: EmailStr


class VerifyTokenRequest(BaseModel):
    token: str


def _send_magic_link(to: str, token: str) -> None:
    link = f"{settings.FRONTEND_URL}/auth/verify?token={token}"
    msg = MIMEText(
        f"Доброго дня!\n\nДля входу в ЗЗК Реєстр перейдіть за посиланням:\n{link}\n\n"
        f"Посилання дійсне 15 хвилин.",
        "plain",
        "utf-8",
    )
    msg["Subject"] = "ЗЗК Реєстр — вхід в систему"
    msg["From"] = settings.SMTP_USER
    msg["To"] = to

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Помилка відправки листа: {e}")


@router.post("/send-link", status_code=status.HTTP_200_OK)
async def send_magic_link(
        body: SendLinkRequest,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db),
):
    user_res = await db.execute(select(User).where(User.email == body.email))
    user = user_res.scalar_one_or_none()

    patient = None
    if not user:
        pat_res = await db.execute(select(PatientProfile).where(PatientProfile.email == body.email))
        patient = pat_res.scalar_one_or_none()

    if user or patient:
        token_value = secrets.token_urlsafe(48)
        auth_token = AuthToken(
            token=token_value,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            user_id=user.id if user else None,
            patient_id=patient.id if patient else None
        )
        db.add(auth_token)
        await db.commit()
        background_tasks.add_task(_send_magic_link, body.email, token_value)

    return {"message": "Якщо цей email зареєстрований — лист відправлено"}


@router.post("/verify", response_model=TokenResponse)
async def verify_magic_link(
        body: VerifyTokenRequest,
        db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AuthToken)
        .options(selectinload(AuthToken.user))
        .where(AuthToken.token == body.token)
    )
    auth_token = result.scalar_one_or_none()

    if not auth_token or auth_token.used_at is not None or auth_token.expires_at < now:
        raise HTTPException(status_code=400, detail="Невалідний або протермінований токен")

    # Build identity BEFORE marking the token used — if something goes wrong here
    # the token stays valid and the user can retry.
    if auth_token.user_id:
        if auth_token.user is None:
            raise HTTPException(status_code=400, detail="Невалідний або протермінований токен")
        sub_identity = f"user:{auth_token.user_id}"
        role_value = auth_token.user.role.value
    elif auth_token.patient_id:
        sub_identity = f"patient:{auth_token.patient_id}"
        role_value = "PATIENT"
    else:
        raise HTTPException(status_code=400, detail="Невалідний або протермінований токен")

    auth_token.used_at = datetime.now(timezone.utc)
    await db.commit()

    return TokenResponse(access_token=create_access_token({"sub": sub_identity, "role": role_value}))


@router.get("/me", response_model=Union[UserOut, PatientMeOut])
async def me(
        current_user: Union[User, PatientProfile] = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    # Довантажуємо регіон жадібно, щоб уникнути MissingGreenlet
    if isinstance(current_user, User):
        result = await db.execute(
            select(User).options(selectinload(User.region)).where(User.id == current_user.id)
        )
        user = result.scalar_one()
        return UserOut.model_validate(user, from_attributes=True)

    if isinstance(current_user, PatientProfile):
        result = await db.execute(
            select(PatientProfile).options(selectinload(PatientProfile.region)).where(
                PatientProfile.id == current_user.id)
        )
        patient = result.scalar_one()
        return PatientMeOut.model_validate(patient, from_attributes=True)

    raise HTTPException(status_code=400, detail="Невідомий тип користувача")