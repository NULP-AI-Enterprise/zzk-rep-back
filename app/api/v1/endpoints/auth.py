import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.core.mailer import build_link, send_action_mail
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.models import AuthToken, SelfAssessmentToken, User, PatientProfile
from app.schemas.schemas import MessageResponse, TokenResponse, UserOut, PatientMeOut

router = APIRouter(prefix="/auth", tags=["Auth"])

LOGIN_TOKEN_TTL = timedelta(minutes=15)
# Max simultaneously valid (unused, unexpired) tokens per account — stops e-mail bombing
MAX_ACTIVE_TOKENS = 5


class SendLinkRequest(BaseModel):
    email: EmailStr


class VerifyTokenRequest(BaseModel):
    token: str


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def can_issue_login_token(
        db: AsyncSession, *, user_id: Optional[int] = None, patient_id: Optional[int] = None,
) -> bool:
    """False when the account already has MAX_ACTIVE_TOKENS valid login links (mail-bomb guard)."""
    owner = (AuthToken.user_id == user_id) if user_id is not None else (AuthToken.patient_id == patient_id)
    active = await db.execute(
        select(func.count(AuthToken.id)).where(
            owner,
            AuthToken.purpose == "login",
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > datetime.now(timezone.utc),
        )
    )
    return active.scalar_one() < MAX_ACTIVE_TOKENS


def send_login_link(to: str, token: str, *, welcome: bool = False, valid_for: str = "15 хвилин") -> None:
    link = build_link("/auth/verify", token)
    if welcome:
        intro = "Вас було додано до ЗЗК Реєстру. Для першого входу натисніть кнопку нижче."
        subject, button = "ЗЗК Реєстр — підтвердження акаунта", "Підтвердити акаунт"
    else:
        intro = "Для входу в ЗЗК Реєстр натисніть кнопку нижче."
        subject, button = "ЗЗК Реєстр — вхід в систему", "Увійти"
    send_action_mail(to, subject, intro, button, link, valid_for)


@router.post("/send-link", status_code=status.HTTP_200_OK)
async def send_magic_link(
        body: SendLinkRequest,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db),
):
    email = body.email.strip().lower()

    # .first(): legacy rows may differ only by e-mail case — never 500 on that
    user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalars().first()

    patient = None
    if not user:
        patient = (await db.execute(
            select(PatientProfile).where(func.lower(PatientProfile.email) == email)
        )).scalars().first()

    if user or patient:
        now = datetime.now(timezone.utc)
        if await can_issue_login_token(db, user_id=user.id if user else None,
                                       patient_id=patient.id if patient else None):
            token_value = secrets.token_urlsafe(48)
            db.add(AuthToken(
                token=token_value,
                expires_at=now + LOGIN_TOKEN_TTL,
                user_id=user.id if user else None,
                patient_id=patient.id if patient else None,
                purpose="login",
            ))
            await db.commit()
            # send to the address stored in DB (not the case the visitor typed)
            background_tasks.add_task(send_login_link, (user or patient).email, token_value)

    return {"message": "Якщо цей email зареєстрований — лист відправлено"}


_INVALID = "Невалідне посилання"
_USED = "Це посилання вже використано. Запросіть нове на сторінці входу."
_EXPIRED = "Термін дії посилання минув. Запросіть нове на сторінці входу."


@router.post("/verify", response_model=TokenResponse)
async def verify_magic_link(
        body: VerifyTokenRequest,
        db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    token_value = body.token.strip()

    result = await db.execute(
        select(AuthToken)
        .options(selectinload(AuthToken.user))
        .where(AuthToken.token == token_value)
    )
    auth_token = result.scalar_one_or_none()

    if auth_token is not None:
        # email_change tokens are sent to a NEW, not yet verified address — never a login credential
        if auth_token.purpose != "login":
            raise HTTPException(status_code=400, detail=_INVALID)
        if auth_token.used_at is not None:
            raise HTTPException(status_code=400, detail=_USED)
        if _aware(auth_token.expires_at) < now:
            raise HTTPException(status_code=400, detail=_EXPIRED)

        if auth_token.user_id and auth_token.user is not None:
            sub_identity = f"user:{auth_token.user_id}"
            role_value = auth_token.user.role.value
        elif auth_token.patient_id:
            sub_identity = f"patient:{auth_token.patient_id}"
            role_value = "PATIENT"
        else:
            raise HTTPException(status_code=400, detail=_INVALID)

        # Atomic single-use: only one concurrent request can flip used_at from NULL
        consumed = await db.execute(
            update(AuthToken)
            .where(AuthToken.id == auth_token.id, AuthToken.used_at.is_(None))
            .values(used_at=now)
        )
        await db.commit()
        if consumed.rowcount != 1:
            raise HTTPException(status_code=400, detail=_USED)

        return TokenResponse(access_token=create_access_token({"sub": sub_identity, "role": role_value}))

    # Self-assessment reminder links (/self-assessment?token=...) log the patient in too
    sa_res = await db.execute(select(SelfAssessmentToken).where(SelfAssessmentToken.token == token_value))
    sa_token: Optional[SelfAssessmentToken] = sa_res.scalar_one_or_none()
    if sa_token is None:
        raise HTTPException(status_code=400, detail=_INVALID)
    if sa_token.used_at is not None:
        raise HTTPException(status_code=400, detail=_USED)
    if _aware(sa_token.expires_at) < now:
        raise HTTPException(status_code=400, detail=_EXPIRED)

    consumed = await db.execute(
        update(SelfAssessmentToken)
        .where(SelfAssessmentToken.id == sa_token.id, SelfAssessmentToken.used_at.is_(None))
        .values(used_at=now)
    )
    await db.commit()
    if consumed.rowcount != 1:
        raise HTTPException(status_code=400, detail=_USED)

    return TokenResponse(access_token=create_access_token(
        {"sub": f"patient:{sa_token.patient_id}", "role": "PATIENT"}
    ))


@router.post("/confirm-email-change", response_model=MessageResponse)
async def confirm_email_change(
        body: VerifyTokenRequest,
        db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AuthToken)
        .options(selectinload(AuthToken.patient))
        .where(AuthToken.token == body.token.strip())
    )
    auth_token = result.scalar_one_or_none()

    if (
        not auth_token
        or auth_token.used_at is not None
        or _aware(auth_token.expires_at) < now
        or auth_token.purpose != 'email_change'
    ):
        raise HTTPException(status_code=400, detail="Невалідний або протермінований токен")

    patient = auth_token.patient
    if not patient or not patient.pending_email:
        raise HTTPException(status_code=400, detail="Зміна email не знайдена")

    new_email = patient.pending_email.strip().lower()
    taken = await db.execute(
        select(PatientProfile.id).where(
            func.lower(PatientProfile.email) == new_email, PatientProfile.id != patient.id
        )
    )
    taken_by_user = await db.execute(select(User.id).where(func.lower(User.email) == new_email))
    if taken.first() or taken_by_user.first():
        raise HTTPException(status_code=409, detail="Цей email вже використовується")

    patient.email = new_email
    patient.pending_email = None
    auth_token.used_at = now
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Цей email вже використовується")

    return MessageResponse(message="Email успішно змінено")


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