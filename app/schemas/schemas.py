from __future__ import annotations
from datetime import date, datetime
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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    patronymic: Optional[str] = None
    region_id: Optional[int] = None
    job_position: Optional[str] = None
    job_place: Optional[str] = None


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

class PatientCreate(BaseModel):
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

    @field_validator("birth_year")
    @classmethod
    def validate_birth_year(cls, v: int) -> int:
        if not (1900 <= v <= 2100):
            raise ValueError("birth_year має бути між 1900 та 2100")
        return v


class PatientUpdate(BaseModel):
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
    localization: Optional[str] = None
    perianal_lesions: Optional[bool] = None
    behavior: Optional[str] = None
    general_wellbeing: Optional[int] = Field(None, ge=0, le=4)
    abdominal_pain: Optional[int] = Field(None, ge=0, le=3)
    stool_count: Optional[int] = Field(None, ge=0)
    abdominal_mass: Optional[int] = Field(None, ge=0, le=3)
    ses_cd: Optional[str] = None
    ses_cd_other: Optional[str] = None
    complications: List[CdComplicationType] = []
    comments: Optional[str] = None


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
    extent: Optional[str] = None
    stool_frequency: Optional[int] = Field(None, ge=0, le=3)
    rectal_bleeding: Optional[int] = Field(None, ge=0, le=3)
    physician_assessment: Optional[int] = Field(None, ge=0, le=3)
    endoscopic_mayo: Optional[int] = Field(None, ge=0, le=3)
    endoscopic_mayo_other: Optional[str] = None
    comments: Optional[str] = None


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

class LabResultCreate(BaseModel):
    lab_type: LabType
    value: float = Field(gt=0)
    result_date: date


class SurgeryCreate(BaseModel):
    operation_date: date
    operation_name: Optional[str] = None
    description: Optional[str] = None


class TreatmentCreate(BaseModel):
    drug: DrugType
    other_drug_name: Optional[str] = None


class ResistantDrugCreate(BaseModel):
    drug: ResistantDrugType
    other_drug_name: Optional[str] = None


class ClinicalRecordCreate(BaseModel):
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
    cd_stool_count: Optional[int] = Field(None, ge=0)
    uc_rectal_bleeding: Optional[int] = Field(None, ge=0, le=3)
    uc_defecation_freq: Optional[int] = Field(None, ge=0, le=3)
    first_symptoms_date: Optional[date] = None
    first_symptoms_desc: Optional[str] = None
    possible_factors: Optional[str] = None
    constipation_on_flare: Optional[bool] = None
    constipation_stool_freq: Optional[str] = None

    @model_validator(mode="after")
    def check_fields_match_type(self) -> "SelfAssessmentCreate":
        if self.assessment_type == AssessmentType.CD:
            if self.uc_rectal_bleeding is not None or self.uc_defecation_freq is not None:
                raise ValueError("UC fields must be None for CD assessment")
        elif self.assessment_type == AssessmentType.UC:
            if self.cd_abdominal_pain is not None or self.cd_stool_count is not None:
                raise ValueError("CD fields must be None for UC assessment")
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
    s3_key: str
    original_filename: Optional[str] = None


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
    value: float = Field(gt=0)
    result_date: date


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
