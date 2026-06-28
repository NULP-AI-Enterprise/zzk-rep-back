import enum
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime,
    Enum, ForeignKey, Integer, LargeBinary, Numeric,
    SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import relationship
from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"
    MODERATOR = "MODERATOR"
    ADMIN = "ADMIN"


class PatientStatus(str, enum.Enum):
    PENDING = "PENDING"
    ATTACHED = "ATTACHED"
    DETACHED = "DETACHED"


class SexType(str, enum.Enum):
    M = "M"
    F = "F"


class DisabilityGroup(str, enum.Enum):
    GROUP_1 = "GROUP_1"
    GROUP_2 = "GROUP_2"
    GROUP_3 = "GROUP_3"
    NONE = "NONE"


class DiagnosisType(str, enum.Enum):
    UC = "UC"
    CD = "CD"
    UNCLASSIFIED = "UNCLASSIFIED"


class HistologyStatus(str, enum.Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class SmokingStatus(str, enum.Enum):
    CURRENT = "CURRENT"
    NEVER = "NEVER"
    FORMER = "FORMER"


class LabType(str, enum.Enum):
    CRP = "CRP"
    CALPROTECTIN = "CALPROTECTIN"


class DrugType(str, enum.Enum):
    ASA_5 = "5ASA"
    BUDESONIDE = "BUDESONIDE"
    SYSTEMIC_STEROIDS = "SYSTEMIC_STEROIDS"
    THIOPURINES = "THIOPURINES"
    METHOTREXATE = "METHOTREXATE"
    ANTI_TNF = "ANTI_TNF"
    VEDOLIZUMAB = "VEDOLIZUMAB"
    USTEKINUMAB = "USTEKINUMAB"
    TOFACITINIB = "TOFACITINIB"
    UPADACITINIB = "UPADACITINIB"
    OTHER = "OTHER"


class ResistantDrugType(str, enum.Enum):
    INFLIXIMAB = "INFLIXIMAB"
    ADALIMUMAB = "ADALIMUMAB"
    VEDOLIZUMAB = "VEDOLIZUMAB"
    USTEKINUMAB = "USTEKINUMAB"
    TOFACITINIB = "TOFACITINIB"
    UPADACITINIB = "UPADACITINIB"
    OTHER = "OTHER"


class CdComplicationType(str, enum.Enum):
    ARTHRALGIA = "ARTHRALGIA"
    UVEITIS = "UVEITIS"
    ERYTHEMA_NODOSUM = "ERYTHEMA_NODOSUM"
    APHTHOUS_ULCERS = "APHTHOUS_ULCERS"
    PYODERMA = "PYODERMA"
    ANAL_FISSURE = "ANAL_FISSURE"
    NEW_FISTULA = "NEW_FISTULA"
    ABSCESS = "ABSCESS"


class AssessmentType(str, enum.Enum):
    CD = "CD"
    UC = "UC"


# ── Users & Auth ──────────────────────────────────────────────────────────────

class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    role = Column(Enum(UserRole, name="user_role"), nullable=False)  # Виправлено під назву в БД
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    patronymic = Column(String(100))
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="SET NULL"))
    job_position = Column(String(200))
    job_place = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    region = relationship("Region")
    patients = relationship("PatientProfile", foreign_keys="PatientProfile.doctor_id", back_populates="doctor")



class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id = Column(Integer, primary_key=True)
    token = Column(String(255), nullable=False, unique=True)

    # Зовнішні ключі (Foreign Keys) — тут все супер!
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=True)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="auth_tokens")

    patient = relationship("PatientProfile", backref="auth_tokens")


# ── Patient ───────────────────────────────────────────────────────────────────

class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    doctor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(Enum(PatientStatus, native_enum=False), nullable=False, default=PatientStatus.PENDING)
    surname_encrypted = Column(LargeBinary)
    initials = Column(String(10), nullable=False)
    sex = Column(Enum(SexType, native_enum=False), nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="SET NULL"))
    email = Column(String(255), nullable=False, unique=True)
    birth_year = Column(SmallInteger, nullable=False)
    weight = Column(Numeric(5, 1))
    height = Column(SmallInteger)
    disability = Column(Enum(DisabilityGroup, native_enum=False), nullable=False, default=DisabilityGroup.NONE)
    diagnosis = Column(Enum(DiagnosisType, native_enum=False), nullable=False)
    histologically_confirmed = Column(Enum(HistologyStatus, native_enum=False), nullable=False)
    diagnosis_year = Column(SmallInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("birth_year BETWEEN 1900 AND 2100", name="chk_birth_year"),
        CheckConstraint("weight > 0", name="chk_weight"),
        CheckConstraint("height > 0", name="chk_height"),
    )

    doctor = relationship("User", foreign_keys=[doctor_id], back_populates="patients")
    user = relationship("User", foreign_keys=[user_id])
    region = relationship("Region")

    cd_records = relationship("StateRecordCd", back_populates="patient", cascade="all, delete-orphan")
    uc_records = relationship("StateRecordUc", back_populates="patient", cascade="all, delete-orphan")
    clinical_records = relationship("StateRecordClinical", back_populates="patient", cascade="all, delete-orphan")
    self_assessments = relationship("PatientSelfAssessment", back_populates="patient", cascade="all, delete-orphan")
    tokens = relationship("SelfAssessmentToken", back_populates="patient", cascade="all, delete-orphan")

    @property
    def role(self):
        from app.models.models import UserRole
        return UserRole.PATIENT

# ── State Record: CD Anamnesis ────────────────────────────────────────────────

class StateRecordCd(Base):
    __tablename__ = "state_records_cd"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    localization = Column(String(2))
    perianal_lesions = Column(Boolean)
    behavior = Column(String(2))
    general_wellbeing = Column(SmallInteger)
    abdominal_pain = Column(SmallInteger)
    stool_count = Column(SmallInteger)
    abdominal_mass = Column(SmallInteger)
    ses_cd = Column(String(10))
    ses_cd_other = Column(String(200))
    harvey_bradshaw = Column(SmallInteger)  # тільки сервер
    comments = Column(Text)

    patient = relationship("PatientProfile", back_populates="cd_records")
    creator = relationship("User")
    complications = relationship("CdComplication", back_populates="record", cascade="all, delete-orphan")


class CdComplication(Base):
    __tablename__ = "cd_complications"

    id = Column(Integer, primary_key=True)
    record_id = Column(Integer, ForeignKey("state_records_cd.id", ondelete="CASCADE"), nullable=False)
    complication = Column(Enum(CdComplicationType, native_enum=False), nullable=False)

    __table_args__ = (UniqueConstraint("record_id", "complication"),)

    record = relationship("StateRecordCd", back_populates="complications")


# ── State Record: UC Anamnesis ────────────────────────────────────────────────

class StateRecordUc(Base):
    __tablename__ = "state_records_uc"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    extent = Column(String(2))
    stool_frequency = Column(SmallInteger)
    rectal_bleeding = Column(SmallInteger)
    physician_assessment = Column(SmallInteger)
    endoscopic_mayo = Column(SmallInteger)
    endoscopic_mayo_other = Column(String(200))
    partial_mayo = Column(SmallInteger)  # тільки сервер
    comments = Column(Text)

    patient = relationship("PatientProfile", back_populates="uc_records")
    creator = relationship("User")


# ── State Record: Clinical ────────────────────────────────────────────────────

class StateRecordClinical(Base):
    __tablename__ = "state_records_clinical"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    strictures = Column(Boolean)
    penetrations_fistulas = Column(Boolean)
    fecal_incontinence = Column(String(10))  # "NONE","1-4","5-8","≥9"
    infectious_complications = Column(Text)
    abdominal_surgeries = Column(Boolean)
    steroid_dependence = Column(Boolean)
    steroid_resistance = Column(Boolean)
    advanced_therapy_resistance = Column(Boolean)
    smoking_status = Column(Enum(SmokingStatus, native_enum=False))
    side_effects = Column(Text)
    resistant_drugs_other = Column(Text)

    patient = relationship("PatientProfile", back_populates="clinical_records")
    creator = relationship("User")
    lab_results = relationship("ClinicalLabResult", back_populates="record", cascade="all, delete-orphan")
    surgeries = relationship("ClinicalSurgery", back_populates="record", cascade="all, delete-orphan")
    treatments = relationship("ClinicalTreatment", back_populates="record", cascade="all, delete-orphan")
    resistant_drugs = relationship("ClinicalResistantDrug", back_populates="record", cascade="all, delete-orphan")


class ClinicalLabResult(Base):
    __tablename__ = "clinical_lab_results"

    id = Column(Integer, primary_key=True)
    record_id = Column(Integer, ForeignKey("state_records_clinical.id", ondelete="CASCADE"), nullable=False)
    lab_type = Column(Enum(LabType, native_enum=False), nullable=False)
    value = Column(Numeric(10, 2), nullable=False)
    result_date = Column(Date, nullable=False)

    record = relationship("StateRecordClinical", back_populates="lab_results")


class ClinicalSurgery(Base):
    __tablename__ = "clinical_surgeries"

    id = Column(Integer, primary_key=True)
    record_id = Column(Integer, ForeignKey("state_records_clinical.id", ondelete="CASCADE"), nullable=False)
    operation_date = Column(Date, nullable=False)

    record = relationship("StateRecordClinical", back_populates="surgeries")


class ClinicalTreatment(Base):
    __tablename__ = "clinical_treatments"

    id = Column(Integer, primary_key=True)
    record_id = Column(Integer, ForeignKey("state_records_clinical.id", ondelete="CASCADE"), nullable=False)
    drug = Column(Enum(DrugType, native_enum=False), nullable=False)
    other_drug_name = Column(String(200))

    record = relationship("StateRecordClinical", back_populates="treatments")


class ClinicalResistantDrug(Base):
    __tablename__ = "clinical_resistant_drugs"

    id = Column(Integer, primary_key=True)
    record_id = Column(Integer, ForeignKey("state_records_clinical.id", ondelete="CASCADE"), nullable=False)
    drug = Column(Enum(ResistantDrugType, native_enum=False), nullable=False)
    other_drug_name = Column(String(200))

    __table_args__ = (UniqueConstraint("record_id", "drug"),)

    record = relationship("StateRecordClinical", back_populates="resistant_drugs")


# ── Self Assessment (CD + UC в одній таблиці) ─────────────────────────────────

class PatientSelfAssessment(Base):
    __tablename__ = "patient_self_assessments"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    assessment_type = Column(Enum(AssessmentType, native_enum=False), nullable=False)

    # ХК
    cd_abdominal_pain = Column(SmallInteger)
    cd_stool_count = Column(SmallInteger)

    # ВК
    uc_rectal_bleeding = Column(SmallInteger)
    uc_defecation_freq = Column(SmallInteger)

    # Спільні
    pro2_score = Column(SmallInteger)  # тільки сервер
    first_symptoms_date = Column(Date)
    first_symptoms_desc = Column(Text)
    possible_factors = Column(Text)
    constipation_on_flare = Column(Boolean)
    constipation_stool_freq = Column(Text)
    filled_by_patient = Column(Boolean, default=True, nullable=False)

    patient = relationship("PatientProfile", back_populates="self_assessments")
    creator = relationship("User")


class SelfAssessmentToken(Base):
    __tablename__ = "self_assessment_tokens"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))

    patient = relationship("PatientProfile", back_populates="tokens")