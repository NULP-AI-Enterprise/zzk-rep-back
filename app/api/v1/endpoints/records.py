from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_doctor_or_admin
from app.db.session import get_db
from app.models.models import (
    CdComplication, ClinicalLabResult, ClinicalResistantDrug,
    ClinicalSurgery, ClinicalTreatment,
    PatientProfile, StateRecordCd, StateRecordClinical, StateRecordUc,
    User, UserRole,
)
from app.schemas.schemas import (
    CdRecordCreate, CdRecordOut,
    ClinicalRecordCreate, ClinicalRecordOut,
    UcRecordCreate, UcRecordOut,
)

router = APIRouter(prefix="/patients/{patient_id}/records", tags=["Records"])


async def _get_patient_or_403(patient_id: int, current_user: User, db: AsyncSession) -> PatientProfile:
    result = await db.execute(select(PatientProfile).where(PatientProfile.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Пацієнта не знайдено")
    if current_user.role == UserRole.DOCTOR and patient.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    if isinstance(current_user, PatientProfile) and patient.id != current_user.id:
        raise HTTPException(status_code=403, detail="Доступ заборонено")
    return patient


def _calc_harvey_bradshaw(body: CdRecordCreate) -> int | None:
    fields = [body.general_wellbeing, body.abdominal_pain, body.stool_count, body.abdominal_mass]
    if all(f is None for f in fields):
        return None
    return sum(f or 0 for f in fields) + len(body.complications)


def _calc_partial_mayo(body: UcRecordCreate) -> int | None:
    fields = [body.stool_frequency, body.rectal_bleeding, body.physician_assessment]
    if all(f is None for f in fields):
        return None
    return sum(f or 0 for f in fields)


# ═══════════════════════════════════════════════════════════════
# CD ANAMNESIS (Хвороба Крона)
# ═══════════════════════════════════════════════════════════════

def _cd_opts():
    return [selectinload(StateRecordCd.complications)]


@router.post("/cd", response_model=CdRecordOut, status_code=201)
async def create_cd(
        patient_id: int, body: CdRecordCreate,
        current_user: User = Depends(require_doctor_or_admin),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)

    record = StateRecordCd(
        patient_id=patient_id, created_by=current_user.id,
        localization=body.localization, perianal_lesions=body.perianal_lesions,
        behavior=body.behavior, general_wellbeing=body.general_wellbeing,
        abdominal_pain=body.abdominal_pain, stool_count=body.stool_count,
        abdominal_mass=body.abdominal_mass, ses_cd=body.ses_cd,
        ses_cd_other=body.ses_cd_other, comments=body.comments,
        harvey_bradshaw=_calc_harvey_bradshaw(body),
    )
    db.add(record)
    await db.flush()

    for comp in body.complications:
        db.add(CdComplication(record_id=record.id, complication=comp))

    await db.commit()

    result = await db.execute(select(StateRecordCd).options(*_cd_opts()).where(StateRecordCd.id == record.id))
    return result.scalar_one()


@router.get("/cd", response_model=list[CdRecordOut])
async def list_cd(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordCd).options(*_cd_opts())
        .where(StateRecordCd.patient_id == patient_id)
        .order_by(StateRecordCd.id.desc())
    )
    return result.scalars().all()


@router.get("/cd/latest", response_model=CdRecordOut)
async def latest_cd(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordCd).options(*_cd_opts())
        .where(StateRecordCd.patient_id == patient_id)
        .order_by(StateRecordCd.id.desc()).limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Записів ХК немає")
    return record


@router.get("/cd/{record_id}", response_model=CdRecordOut)
async def get_cd(
        patient_id: int, record_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordCd).options(*_cd_opts())
        .where(StateRecordCd.id == record_id, StateRecordCd.patient_id == patient_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Запис не знайдено")
    return record


# ═══════════════════════════════════════════════════════════════
# UC ANAMNESIS (Виразковий коліт)
# ═══════════════════════════════════════════════════════════════

@router.post("/uc", response_model=UcRecordOut, status_code=201)
async def create_uc(
        patient_id: int, body: UcRecordCreate,
        current_user: User = Depends(require_doctor_or_admin),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)

    record = StateRecordUc(
        patient_id=patient_id, created_by=current_user.id,
        extent=body.extent, stool_frequency=body.stool_frequency,
        rectal_bleeding=body.rectal_bleeding, physician_assessment=body.physician_assessment,
        endoscopic_mayo=body.endoscopic_mayo, endoscopic_mayo_other=body.endoscopic_mayo_other,
        comments=body.comments, partial_mayo=_calc_partial_mayo(body),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.get("/uc", response_model=list[UcRecordOut])
async def list_uc(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordUc)
        .where(StateRecordUc.patient_id == patient_id)
        .order_by(StateRecordUc.id.desc())
    )
    return result.scalars().all()


@router.get("/uc/latest", response_model=UcRecordOut)
async def latest_uc(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordUc)
        .where(StateRecordUc.patient_id == patient_id)
        .order_by(StateRecordUc.id.desc()).limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Записів ВК немає")
    return record


@router.get("/uc/{record_id}", response_model=UcRecordOut)
async def get_uc(
        patient_id: int, record_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordUc)
        .where(StateRecordUc.id == record_id, StateRecordUc.patient_id == patient_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Запис не знайдено")
    return record


# ═══════════════════════════════════════════════════════════════
# CLINICAL (Загальна клінічна частина)
# ═══════════════════════════════════════════════════════════════

def _clin_opts():
    return [
        selectinload(StateRecordClinical.lab_results),
        selectinload(StateRecordClinical.surgeries),
        selectinload(StateRecordClinical.treatments),
        selectinload(StateRecordClinical.resistant_drugs),
    ]


@router.post("/clinical", response_model=ClinicalRecordOut, status_code=201)
async def create_clinical(
        patient_id: int, body: ClinicalRecordCreate,
        current_user: User = Depends(require_doctor_or_admin),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)

    record = StateRecordClinical(
        patient_id=patient_id, created_by=current_user.id,
        strictures=body.strictures, penetrations_fistulas=body.penetrations_fistulas,
        fecal_incontinence=body.fecal_incontinence,
        infectious_complications=body.infectious_complications,
        abdominal_surgeries=body.abdominal_surgeries,
        steroid_dependence=body.steroid_dependence, steroid_resistance=body.steroid_resistance,
        advanced_therapy_resistance=body.advanced_therapy_resistance,
        smoking_status=body.smoking_status, side_effects=body.side_effects,
        resistant_drugs_other=body.resistant_drugs_other,
    )
    db.add(record)
    await db.flush()

    for lr in body.lab_results:
        db.add(ClinicalLabResult(record_id=record.id, lab_type=lr.lab_type, value=lr.value, result_date=lr.result_date))

    if body.abdominal_surgeries:
        for s in body.surgeries:
            db.add(ClinicalSurgery(
                record_id=record.id,
                operation_date=s.operation_date,
                operation_name=s.operation_name,
                description=s.description,
            ))

    for t in body.treatments:
        db.add(ClinicalTreatment(record_id=record.id, drug=t.drug, other_drug_name=t.other_drug_name))

    for rd in body.resistant_drugs:
        db.add(ClinicalResistantDrug(record_id=record.id, drug=rd.drug, other_drug_name=rd.other_drug_name))

    await db.commit()

    result = await db.execute(
        select(StateRecordClinical).options(*_clin_opts()).where(StateRecordClinical.id == record.id))
    return result.scalar_one()


@router.get("/clinical", response_model=list[ClinicalRecordOut])
async def list_clinical(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordClinical).options(*_clin_opts())
        .where(StateRecordClinical.patient_id == patient_id)
        .order_by(StateRecordClinical.id.desc())
    )
    return result.scalars().all()


@router.get("/clinical/latest", response_model=ClinicalRecordOut)
async def latest_clinical(
        patient_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordClinical).options(*_clin_opts())
        .where(StateRecordClinical.patient_id == patient_id)
        .order_by(StateRecordClinical.id.desc()).limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Клінічних записів немає")
    return record


@router.get("/clinical/{record_id}", response_model=ClinicalRecordOut)
async def get_clinical(
        patient_id: int, record_id: int,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _get_patient_or_403(patient_id, current_user, db)
    result = await db.execute(
        select(StateRecordClinical).options(*_clin_opts())
        .where(StateRecordClinical.id == record_id, StateRecordClinical.patient_id == patient_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Запис не знайдено")
    return record