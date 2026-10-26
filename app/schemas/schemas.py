from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, computed_field, model_validator

from app.models.models import (
    AssessmentType, CdComplicationType, DiagnosisType, DisabilityGroup,
    DrugType, HistologyStatus, LabType, PatientStatus, ResistantDrugType,
    SexType, SmokingStatus, UserRole,
)


# ── Auth ──────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Region ────────────────────────────────────────────────────────────────────

class RegionOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# ── User ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    role: UserRole
    first_name: str
    last_name: str
    patronymic: Optional[str] = None
    region_id: Optional[int] = None
    job_position: Optional[str] = None
    job_place: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    patronymic: Optional[str] = None
    region_id: Optional[int] = None
    job_position: Optional[str] = None
    job_place: Optional[str] = None


class DoctorBrief(BaseModel):
    id: int
    first_name: str
    last_name: str
    patronymic: Optional[str] = None
    region: Optional[RegionOut] = None

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    email: str
    role: UserRole
    first_name: str
    last_name: str
    patronymic: Optional[str]
    region: Optional[RegionOut] = None
    job_position: Optional[str]
    job_place: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Patient ───────────────────────────────────────────────────────────────────

def normalize_initials(value: str) -> str:
    """'тгк' / 'Т.Г.К.' / 'Т Г К' -> 'ТГК' (2-4 letters, no surname is collected)."""
    cleaned = "".join(ch for ch in value if not ch.isspace() and ch not in ".-'’ʼ").upper()
    if not (2 <= len(cleaned) <= 4) or not cleaned.isalpha():
        raise ValueError("Ініціали: 2–4 літери, наприклад ТГК (перша літера прізвища, імені та по батькові)")
    return cleaned


class _PatientFieldChecks(BaseModel):
    """Shared range checks so bad input gives a 422, not a DB constraint 409/500."""

    @field_validator("initials", check_fields=False)
    @classmethod
    def _check_initials(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else normalize_initials(v)

    @field_validator("birth_year", check_fields=False)
    @classmethod
    def _check_birth_year(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1900 <= v <= date.today().year):
            raise ValueError(f"Рік народження має бути між 1900 та {date.today().year}")
        return v

    @field_validator("weight", check_fields=False)
    @classmethod
    def _check_weight(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 < v < 500):
            raise ValueError("Вага має бути від 0 до 500 кг")
        return v

    @field_validator("height", check_fields=False)
    @classmethod
    def _check_height(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 < v < 300):
            raise ValueError("Зріст має бути від 0 до 300 см")
        return v

    @field_validator("diagnosis_year", check_fields=False)
    @classmethod
    def _check_diagnosis_year(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1900 <= v <= date.today().year):
            raise ValueError(f"Рік діагнозу має бути між 1900 та {date.today().year}")
        return v


class PatientRegister(_PatientFieldChecks):
    """Public self-registration: general data the patient enters about themselves."""
    initials: str
    sex: SexType
    region_id: int
    email: EmailStr
    birth_year: int
    weight: Optional[float] = None
    height: Optional[int] = None
    disability: DisabilityGroup = DisabilityGroup.NONE
    diagnosis: DiagnosisType = DiagnosisType.UNCLASSIFIED
    histologically_confirmed: HistologyStatus = HistologyStatus.UNKNOWN
    diagnosis_year: Optional[int] = None
    consent: bool

    @field_validator("consent")
    @classmethod
    def _check_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Необхідна згода на обробку даних")
        return v


class PatientCreate(_PatientFieldChecks):
    surname: Optional[str] = None
    initials: str
    sex: SexType
    region_id: Optional[int] = None
    email: EmailStr
    birth_year: int
    weight: Optional[float] = None
    height: Optional[int] = None
    disability: DisabilityGroup = DisabilityGroup.NONE
    diagnosis: DiagnosisType
    histologically_confirmed: HistologyStatus
    diagnosis_year: Optional[int] = None
    doctor_id: Optional[int] = None


class PatientUpdate(_PatientFieldChecks):
    surname: Optional[str] = None
    initials: Optional[str] = None
    sex: Optional[SexType] = None
    region_id: Optional[int] = None
    email: Optional[EmailStr] = None
    birth_year: Optional[int] = None
    weight: Optional[float] = None
    height: Optional[int] = None
    disability: Optional[DisabilityGroup] = None
    diagnosis: Optional[DiagnosisType] = None
    histologically_confirmed: Optional[HistologyStatus] = None
    diagnosis_year: Optional[int] = None
    doctor_id: Optional[int] = None


class PatientStatusUpdate(BaseModel):
    status: PatientStatus
    doctor_id: Optional[int] = None


class PatientListItem(BaseModel):
    id: int
    initials: str
    sex: SexType
    diagnosis: DiagnosisType
    status: PatientStatus
    birth_year: int
    disability: DisabilityGroup
    doctor: Optional[UserOut] = None
    region: Optional[RegionOut] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PatientOut(PatientListItem):
    surname: Optional[str] = None
    email: str
    weight: Optional[float]
    height: Optional[int]
    histologically_confirmed: HistologyStatus
    diagnosis_year: Optional[int]
    updated_at: datetime


class PatientMeOut(BaseModel):
    id: int
    email: EmailStr
    initials: str
    sex: SexType
    birth_year: int
    weight: Optional[float] = None
    height: Optional[int] = None
    disability: DisabilityGroup
    diagnosis: DiagnosisType
    status: PatientStatus
    histologically_confirmed: HistologyStatus
    diagnosis_year: Optional[int] = None
    region: Optional[RegionOut] = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def role(self) -> UserRole:
        return UserRole.PATIENT

    model_config = {"from_attributes": True}


# ── CD Record (Хвороба Крона) ─────────────────────────────────────────────────

class CdRecordCreate(BaseModel):
    localization: Optional[str] = Field(None, max_length=2)
    perianal_lesions: Optional[bool] = None
    behavior: Optional[str] = Field(None, max_length=2)
    general_wellbeing: Optional[int] = Field(None, ge=0, le=4)
    abdominal_pain: Optional[int] = Field(None, ge=0, le=3)
    stool_count: Optional[int] = Field(None, ge=0, le=100)
    abdominal_mass: Optional[int] = Field(None, ge=0, le=3)
    ses_cd: Optional[str] = Field(None, max_length=10)
    ses_cd_other: Optional[str] = Field(None, max_length=200)
    complications: List[CdComplicationType] = []
    comments: Optional[str] = Field(None, max_length=5000)

    @field_validator("complications")
    @classmethod
    def _dedupe_complications(cls, v: List[CdComplicationType]) -> List[CdComplicationType]:
        # (record_id, complication) is unique in the DB; duplicates would 500 and inflate the HBI score
        return list(dict.fromkeys(v))


class CdComplicationOut(BaseModel):
    complication: CdComplicationType

    model_config = {"from_attributes": True}


class CdRecordOut(BaseModel):
    id: int
    patient_id: int
    created_by: int
    created_at: datetime
    localization: Optional[str]
    perianal_lesions: Optional[bool]
    behavior: Optional[str]
    general_wellbeing: Optional[int]
    abdominal_pain: Optional[int]
    stool_count: Optional[int]
    abdominal_mass: Optional[int]
    ses_cd: Optional[str]
    ses_cd_other: Optional[str]
    harvey_bradshaw: Optional[int]
    comments: Optional[str]
    complications: List[CdComplicationOut] = []

    model_config = {"from_attributes": True}


# ── UC Record (Виразковий коліт) ──────────────────────────────────────────────

class UcRecordCreate(BaseModel):
    extent: Optional[str] = Field(None, max_length=2)
    stool_frequency: Optional[int] = Field(None, ge=0, le=3)
    rectal_bleeding: Optional[int] = Field(None, ge=0, le=3)
    physician_assessment: Optional[int] = Field(None, ge=0, le=3)
    endoscopic_mayo: Optional[int] = Field(None, ge=0, le=3)
    endoscopic_mayo_other: Optional[str] = Field(None, max_length=200)
    comments: Optional[str] = Field(None, max_length=5000)


class UcRecordOut(BaseModel):
    id: int
    patient_id: int
    created_by: int
    created_at: datetime
    extent: Optional[str]
    stool_frequency: Optional[int]
    rectal_bleeding: Optional[int]
    physician_assessment: Optional[int]
    endoscopic_mayo: Optional[int]
    endoscopic_mayo_other: Optional[str]
    partial_mayo: Optional[int]
    comments: Optional[str]

    model_config = {"from_attributes": True}


# ── Clinical Record ───────────────────────────────────────────────────────────

def _not_future(v: Optional[date]) -> Optional[date]:
    # +1 day: the server runs on UTC, users in Ukraine are ahead of it for a few hours
    if v is not None and v > date.today() + timedelta(days=1):
        raise ValueError("Дата не може бути в майбутньому")
    return v


class LabResultCreate(BaseModel):
    lab_type: LabType
    value: float = Field(ge=0, le=99999999, allow_inf_nan=False)
    result_date: date

    _check_date = field_validator("result_date")(_not_future)


class SurgeryCreate(BaseModel):
    operation_date: date
    operation_name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)

    _check_date = field_validator("operation_date")(_not_future)


class TreatmentCreate(BaseModel):
    drug: DrugType
    other_drug_name: Optional[str] = Field(None, max_length=200)


class ResistantDrugCreate(BaseModel):
    drug: ResistantDrugType
    other_drug_name: Optional[str] = Field(None, max_length=200)


class ClinicalRecordCreate(BaseModel):
    strictures: Optional[bool] = None
    penetrations_fistulas: Optional[bool] = None
    fecal_incontinence: Optional[str] = Field(None, max_length=10)
    infectious_complications: Optional[str] = Field(None, max_length=5000)
    abdominal_surgeries: Optional[bool] = None
    steroid_dependence: Optional[bool] = None
    steroid_resistance: Optional[bool] = None
    advanced_therapy_resistance: Optional[bool] = None
    smoking_status: Optional[SmokingStatus] = None
    side_effects: Optional[str] = Field(None, max_length=5000)
    resistant_drugs_other: Optional[str] = Field(None, max_length=5000)
    lab_results: List[LabResultCreate] = []
    surgeries: List[SurgeryCreate] = []
    treatments: List[TreatmentCreate] = []
    resistant_drugs: List[ResistantDrugCreate] = []


class LabResultOut(BaseModel):
    id: int
    lab_type: LabType
    value: float
    result_date: date

    model_config = {"from_attributes": True}


class SurgeryOut(BaseModel):
    id: int
    operation_date: date
    operation_name: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class TreatmentOut(BaseModel):
    id: int
    drug: DrugType
    other_drug_name: Optional[str] = None

    model_config = {"from_attributes": True}


class ResistantDrugOut(BaseModel):
    id: int
    drug: ResistantDrugType
    other_drug_name: Optional[str] = None

    model_config = {"from_attributes": True}


class ClinicalRecordOut(BaseModel):
    id: int
    patient_id: int
    created_by: int
    created_at: datetime
    strictures: Optional[bool] = None
    penetrations_fistulas: Optional[bool] = None
    fecal_incontinence: Optional[str] = None
    infectious_complications: Optional[str] = None
    abdominal_surgeries: Optional[bool] = None
    steroid_dependence: Optional[bool] = None
    steroid_resistance: Optional[bool] = None
    advanced_therapy_resistance: Optional[bool] = None
    smoking_status: Optional[SmokingStatus] = None
    side_effects: Optional[str] = None
    resistant_drugs_other: Optional[str] = None
    lab_results: List[LabResultOut] = []
    surgeries: List[SurgeryOut] = []
    treatments: List[TreatmentOut] = []
    resistant_drugs: List[ResistantDrugOut] = []

    model_config = {"from_attributes": True}


# ── Self Assessment ───────────────────────────────────────────────────────────

class SelfAssessmentCreate(BaseModel):
    assessment_type: AssessmentType
    cd_abdominal_pain: Optional[int] = Field(None, ge=0, le=3)
    cd_stool_count: Optional[int] = Field(None, ge=0, le=100)
    uc_rectal_bleeding: Optional[int] = Field(None, ge=0, le=3)
    uc_defecation_freq: Optional[int] = Field(None, ge=0, le=3)
    first_symptoms_date: Optional[date] = None
    first_symptoms_desc: Optional[str] = Field(None, max_length=5000)
    possible_factors: Optional[str] = Field(None, max_length=5000)
    constipation_on_flare: Optional[bool] = None
    constipation_stool_freq: Optional[str] = Field(None, max_length=5000)

    _check_first_symptoms = field_validator("first_symptoms_date")(_not_future)

    @model_validator(mode="after")
    def check_fields_match_type(self) -> "SelfAssessmentCreate":
        if self.assessment_type == AssessmentType.CD:
            if self.uc_rectal_bleeding is not None or self.uc_defecation_freq is not None:
                raise ValueError("UC fields must be None for CD assessment")
        elif self.assessment_type == AssessmentType.UC:
            if self.cd_abdominal_pain is not None or self.cd_stool_count is not None:
                raise ValueError("CD fields must be None for UC assessment")

        scores = (
            [self.cd_abdominal_pain, self.cd_stool_count]
            if self.assessment_type == AssessmentType.CD
            else [self.uc_rectal_bleeding, self.uc_defecation_freq]
        )
        if all(sc is None for sc in scores):
            raise ValueError("Вкажіть хоча б один показник самооцінки")
        return self


class SelfAssessmentOut(BaseModel):
    id: int
    patient_id: int
    created_by: Optional[int]
    created_at: datetime
    assessment_type: AssessmentType
    cd_abdominal_pain: Optional[int]
    cd_stool_count: Optional[int]
    uc_rectal_bleeding: Optional[int]
    uc_defecation_freq: Optional[int]
    pro2_score: Optional[int]
    first_symptoms_date: Optional[date]
    first_symptoms_desc: Optional[str]
    possible_factors: Optional[str]
    constipation_on_flare: Optional[bool]
    constipation_stool_freq: Optional[str]

    model_config = {"from_attributes": True}


# ── Consent File ──────────────────────────────────────────────────────────────

class ConsentUploadUrlResponse(BaseModel):
    upload_url: str
    s3_key: str


class ConsentFileRegister(BaseModel):
    s3_key: str = Field(..., min_length=1, max_length=500)
    original_filename: Optional[str] = Field(None, max_length=255)


class ConsentFileOut(BaseModel):
    id: int
    patient_id: int
    uploaded_by: int
    s3_key: str
    original_filename: Optional[str]
    uploaded_at: datetime

    model_config = {"from_attributes": True}


# ── Standalone Patient Lab Results ────────────────────────────────────────────

class PatientLabResultCreate(BaseModel):
    lab_type: LabType
    value: float = Field(ge=0, le=99999999, allow_inf_nan=False)
    result_date: date

    _check_date = field_validator("result_date")(_not_future)


class PatientLabResultOut(BaseModel):
    id: int
    lab_type: LabType
    value: float
    result_date: date
    added_by_role: str
    added_by_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Email Change ──────────────────────────────────────────────────────────────

class EmailChangeRequest(BaseModel):
    new_email: EmailStr


class ConfirmEmailChange(BaseModel):
    token: str


# ── Misc ──────────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
