from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_accessible_patient, get_current_user
from app.db.session import get_db
from app.models.models import (
    AssessmentType, PatientProfile, UserRole, PatientSelfAssessment, User,
)
from app.schemas.schemas import SelfAssessmentCreate, SelfAssessmentOut

router = APIRouter(tags=["Self Assessments"])


def _calc_pro2(body: SelfAssessmentCreate) -> int | None:
    if body.assessment_type == AssessmentType.CD:
        if body.cd_abdominal_pain is not None and body.cd_stool_count is not None:
            return (body.cd_abdominal_pain * 5) + (body.cd_stool_count * 2)
    elif body.assessment_type == AssessmentType.UC:
        if body.uc_rectal_bleeding is not None and body.uc_defecation_freq is not None:
            return body.uc_rectal_bleeding + body.uc_defecation_freq
    return None


async def _get_patient_accessible(patient_id: int, current_user: User | PatientProfile, db: AsyncSession):
    return await get_accessible_patient(patient_id, current_user, db)


# ── Єдиний універсальний ендпоінт для створення ──────────────────────────────

@router.post("/patients/{patient_id}/self-assessments", response_model=SelfAssessmentOut, status_code=201)
async def create_self_assessment(
        patient_id: int, body: SelfAssessmentCreate,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    if not isinstance(current_user, PatientProfile) and current_user.role == UserRole.MODERATOR:
        raise HTTPException(status_code=403, detail="Модератор не може створювати самооцінки")
    await _get_patient_accessible(patient_id, current_user, db)

    is_patient = current_user.role == UserRole.PATIENT

    # Визначаємо ID автора
    # Якщо пацієнт - ставимо None, щоб уникнути помилки FK
    author_id = None if is_patient else current_user.id

    assessment = PatientSelfAssessment(
        patient_id=patient_id,
        created_by=author_id,  # Тепер тут буде None, якщо заповнив пацієнт
        filled_by_patient=is_patient,
        pro2_score=_calc_pro2(body),
        **body.model_dump(),
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    return assessment


# ── Читання історії ──────────────────────────────────────────────────────────

@router.get("/patients/{patient_id}/self-assessments", response_model=list[SelfAssessmentOut])
async def list_self_assessments(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_accessible(patient_id, current_user, db)
    result = await db.execute(
        select(PatientSelfAssessment)
        .where(PatientSelfAssessment.patient_id == patient_id)
        .order_by(PatientSelfAssessment.id.desc())
    )
    return result.scalars().all()


@router.get("/patients/{patient_id}/self-assessments/latest", response_model=SelfAssessmentOut)
async def latest_self_assessment(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_accessible(patient_id, current_user, db)
    result = await db.execute(
        select(PatientSelfAssessment)
        .where(PatientSelfAssessment.patient_id == patient_id)
        .order_by(PatientSelfAssessment.id.desc()).limit(1)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Самооцінок немає")
    return assessment