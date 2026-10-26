import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    AuthToken, DiagnosisType, HistologyStatus, PatientProfile, PatientStatus,
    Region, SexType, UserRole,
)
from tests.conftest import create_user, get_token_for_patient, get_token_for_user

REG = {
    "initials": "т.г.к.",
    "sex": "M",
    "email": "Self.Reg@Test.com",
    "birth_year": 1990,
    "diagnosis": "UC",
    "consent": True,
}


@pytest.fixture(autouse=True)
def _no_smtp(monkeypatch):
    monkeypatch.setattr("app.core.mailer.send_mail", lambda *a, **k: True)


async def _region(db: AsyncSession) -> int:
    r = (await db.execute(select(Region).where(Region.name == "Тест-регіон"))).scalar_one_or_none()
    if not r:
        r = Region(name="Тест-регіон")
        db.add(r)
        await db.commit()
        await db.refresh(r)
    return r.id


async def _patient(db: AsyncSession, email: str, **kw) -> PatientProfile:
    p = PatientProfile(
        email=email, initials="АБВ", sex=SexType.M, birth_year=1990,
        diagnosis=DiagnosisType.UC, histologically_confirmed=HistologyStatus.UNKNOWN,
        status=kw.pop("status", PatientStatus.PENDING), **kw,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest.mark.asyncio
async def test_self_registration_creates_pending_patient_without_surname(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    resp = await client.post("/api/v1/patients/register", json={**REG, "region_id": rid})
    assert resp.status_code == 202
    p = (await db.execute(select(PatientProfile).where(PatientProfile.email == "self.reg@test.com"))).scalar_one()
    assert p.initials == "ТГК"
    assert p.status == PatientStatus.PENDING and p.doctor_id is None
    assert p.surname_encrypted is None

    # same generic answer for a known e-mail (no enumeration), no duplicate row
    again = await client.post("/api/v1/patients/register", json={**REG, "region_id": rid})
    assert again.status_code == 202 and again.json() == resp.json()


@pytest.mark.asyncio
async def test_registration_requires_consent_and_valid_initials(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    base = {**REG, "email": "bad@test.com", "region_id": rid}
    assert (await client.post("/api/v1/patients/register", json={**base, "consent": False})).status_code == 422
    assert (await client.post("/api/v1/patients/register", json={**base, "initials": "А"})).status_code == 422
    assert (await client.post("/api/v1/patients/register", json={**base, "initials": "АБ1"})).status_code == 422
    assert (await client.post("/api/v1/patients/register", json={**base, "birth_year": 2999})).status_code == 422


@pytest.mark.asyncio
async def test_doctor_sees_unassigned_pending_and_can_attach(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    doctor = await create_user(db, "pool_doc@test.com", UserRole.DOCTOR)
    other = await create_user(db, "pool_doc2@test.com", UserRole.DOCTOR)
    p = await _patient(db, "pool_pat@test.com", region_id=rid)
    h = {"Authorization": f"Bearer {get_token_for_user(doctor)}"}

    pending = (await client.get("/api/v1/patients/pending", headers=h)).json()
    assert p.id in [x["id"] for x in pending]
    assert (await client.get(f"/api/v1/patients/{p.id}", headers=h)).status_code == 200

    att = await client.patch(f"/api/v1/patients/{p.id}/status", headers=h, json={"status": "ATTACHED"})
    assert att.status_code == 200

    # now it belongs to `doctor`: gone from the pool and closed for others
    h2 = {"Authorization": f"Bearer {get_token_for_user(other)}"}
    assert p.id not in [x["id"] for x in (await client.get("/api/v1/patients/pending", headers=h2)).json()]
    assert (await client.get(f"/api/v1/patients/{p.id}", headers=h2)).status_code == 403


@pytest.mark.asyncio
async def test_email_change_token_is_not_a_login_credential(client: AsyncClient, db: AsyncSession):
    p = await _patient(db, "emailchg@test.com")
    tok = secrets.token_urlsafe(48)
    db.add(AuthToken(token=tok, patient_id=p.id, purpose="email_change",
                     expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    await db.commit()
    resp = await client.post("/api/v1/auth/verify", json={"token": tok})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_verify_reports_used_vs_expired(client: AsyncClient, db: AsyncSession):
    u = await create_user(db, "usedexp@test.com", UserRole.DOCTOR)
    ok, old = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    db.add(AuthToken(token=ok, user_id=u.id, expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    db.add(AuthToken(token=old, user_id=u.id, expires_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    await db.commit()
    assert (await client.post("/api/v1/auth/verify", json={"token": ok})).status_code == 200
    used = await client.post("/api/v1/auth/verify", json={"token": ok})
    assert used.status_code == 400 and "використано" in used.json()["detail"]
    exp = await client.post("/api/v1/auth/verify", json={"token": old})
    assert exp.status_code == 400 and "минув" in exp.json()["detail"]


@pytest.mark.asyncio
async def test_send_link_is_case_insensitive(client: AsyncClient, db: AsyncSession):
    u = await create_user(db, "mixedcase@test.com", UserRole.DOCTOR)
    await client.post("/api/v1/auth/send-link", json={"email": "MixedCase@Test.com"})
    n = (await db.execute(select(AuthToken).where(AuthToken.user_id == u.id))).scalars().all()
    assert len(n) == 1


@pytest.mark.asyncio
async def test_patient_cannot_read_other_patients_consent_or_user_profile(client: AsyncClient, db: AsyncSession):
    a = await _patient(db, "idor_a@test.com")
    b = await _patient(db, "idor_b@test.com")
    h = {"Authorization": f"Bearer {get_token_for_patient(a)}"}
    assert (await client.get(f"/api/v1/patients/{b.id}/consent", headers=h)).status_code == 403
    assert (await client.get(f"/api/v1/patients/{b.id}/records/cd", headers=h)).status_code == 403
    assert (await client.get(f"/api/v1/patients/{b.id}/self-assessments", headers=h)).status_code == 403
    # patient id must never be matched against a User id
    assert (await client.get(f"/api/v1/users/{a.id}", headers=h)).status_code == 403
    assert (await client.patch(f"/api/v1/users/{a.id}", headers=h, json={"first_name": "X"})).status_code == 403


@pytest.mark.asyncio
async def test_moderator_scoped_to_region(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    other = Region(name="Інший-регіон")
    db.add(other)
    await db.commit()
    mod = await create_user(db, "mod_scope@test.com", UserRole.MODERATOR)
    mod.region_id = rid
    await db.commit()
    mine = await _patient(db, "mod_mine@test.com", region_id=rid)
    theirs = await _patient(db, "mod_theirs@test.com", region_id=other.id)
    h = {"Authorization": f"Bearer {get_token_for_user(mod)}"}
    ids = [x["id"] for x in (await client.get("/api/v1/patients", headers=h)).json()]
    assert mine.id in ids and theirs.id not in ids
    assert (await client.get(f"/api/v1/patients/{theirs.id}", headers=h)).status_code == 403
    assert (await client.get(f"/api/v1/patients/{theirs.id}/consent", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_doctor_cannot_change_patient_email_or_doctor_directly(client: AsyncClient, db: AsyncSession):
    doc = await create_user(db, "patch_doc@test.com", UserRole.DOCTOR)
    p = await _patient(db, "patch_pat@test.com", doctor_id=doc.id, status=PatientStatus.ATTACHED)
    h = {"Authorization": f"Bearer {get_token_for_user(doc)}"}
    assert (await client.patch(f"/api/v1/patients/{p.id}", headers=h, json={"email": "new@test.com"})).status_code == 403
    colleague = await create_user(db, "patch_doc2@test.com", UserRole.DOCTOR)
    assert (await client.patch(f"/api/v1/patients/{p.id}", headers=h, json={"doctor_id": colleague.id})).status_code == 403
    # echoing unchanged values is fine
    assert (await client.patch(f"/api/v1/patients/{p.id}", headers=h, json={"email": p.email, "doctor_id": doc.id})).status_code == 200
    assert (await client.patch(f"/api/v1/patients/{p.id}", headers=h, json={"initials": "xyz"})).json()["initials"] == "XYZ"
    assert (await client.patch(f"/api/v1/patients/{p.id}", headers=h, json={"birth_year": 1})).status_code == 422


@pytest.mark.asyncio
async def test_doctors_list_scoped_and_role_update_admin_only(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    admin = await create_user(db, "adm_roles@test.com", UserRole.ADMIN)
    mod = await create_user(db, "mod_roles@test.com", UserRole.MODERATOR)
    mod.region_id = rid
    d_in = await create_user(db, "doc_in@test.com", UserRole.DOCTOR)
    d_in.region_id = rid
    d_out = await create_user(db, "doc_out@test.com", UserRole.DOCTOR)
    await db.commit()

    hm = {"Authorization": f"Bearer {get_token_for_user(mod)}"}
    ids = [d["id"] for d in (await client.get("/api/v1/users/doctors", headers=hm)).json()]
    assert d_in.id in ids and d_out.id not in ids

    hd = {"Authorization": f"Bearer {get_token_for_user(d_in)}"}
    assert (await client.get("/api/v1/users/doctors", headers=hd)).status_code == 403
    # a user can't promote themselves or move their own region
    assert (await client.patch(f"/api/v1/users/{d_in.id}", headers=hd, json={"role": "ADMIN"})).status_code == 403
    assert (await client.patch(f"/api/v1/users/{mod.id}", headers=hm, json={"region_id": rid + 1000})).status_code == 403

    ha = {"Authorization": f"Bearer {get_token_for_user(admin)}"}
    ok = await client.patch(f"/api/v1/users/{d_out.id}", headers=ha, json={"role": "MODERATOR"})
    assert ok.status_code == 200 and ok.json()["role"] == "MODERATOR"
    assert (await client.patch(f"/api/v1/users/{admin.id}", headers=ha, json={"role": "DOCTOR"})).status_code == 400


@pytest.mark.asyncio
async def test_register_known_email_is_throttled(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    body = {**REG, "email": "bomb@test.com", "region_id": rid}
    for _ in range(12):
        assert (await client.post("/api/v1/patients/register", json=body)).status_code == 202
    n = (await db.execute(select(AuthToken).join(PatientProfile, AuthToken.patient_id == PatientProfile.id)
                          .where(PatientProfile.email == "bomb@test.com"))).scalars().all()
    assert len(n) == 5


@pytest.mark.asyncio
async def test_case_variant_duplicate_emails_do_not_500(client: AsyncClient, db: AsyncSession):
    await _patient(db, "Dup@Case.com")
    await _patient(db, "dup@case.com")
    assert (await client.post("/api/v1/auth/send-link", json={"email": "dup@case.com"})).status_code == 200


@pytest.mark.asyncio
async def test_detached_pool_patient_openable_and_claim_is_exclusive(client: AsyncClient, db: AsyncSession):
    d1 = await create_user(db, "claim1@test.com", UserRole.DOCTOR)
    d2 = await create_user(db, "claim2@test.com", UserRole.DOCTOR)
    p = await _patient(db, "claim_pat@test.com", status=PatientStatus.DETACHED)
    h1 = {"Authorization": f"Bearer {get_token_for_user(d1)}"}
    h2 = {"Authorization": f"Bearer {get_token_for_user(d2)}"}
    assert (await client.get(f"/api/v1/patients/{p.id}", headers=h1)).status_code == 200
    assert (await client.patch(f"/api/v1/patients/{p.id}/status", headers=h1, json={"status": "ATTACHED"})).status_code == 200
    assert (await client.patch(f"/api/v1/patients/{p.id}/status", headers=h2, json={"status": "ATTACHED"})).status_code == 403


@pytest.mark.asyncio
async def test_deleting_doctor_detaches_patients_and_echo_patch_is_ok(client: AsyncClient, db: AsyncSession):
    admin = await create_user(db, "adm_del@test.com", UserRole.ADMIN)
    doc = await create_user(db, "doc_del@test.com", UserRole.DOCTOR)
    p = await _patient(db, "del_pat@test.com", doctor_id=doc.id, status=PatientStatus.ATTACHED)
    hd = {"Authorization": f"Bearer {get_token_for_user(doc)}"}
    # unchanged email in the body is not an email change
    assert (await client.patch(f"/api/v1/users/{doc.id}", headers=hd,
                               json={"email": doc.email, "first_name": "Нове"})).status_code == 200
    ha = {"Authorization": f"Bearer {get_token_for_user(admin)}"}
    assert (await client.delete(f"/api/v1/users/{doc.id}", headers=ha)).status_code == 200
    await db.refresh(p)
    assert p.doctor_id is None and p.status == PatientStatus.DETACHED


@pytest.mark.asyncio
async def test_moderator_cannot_attach_to_foreign_region_doctor(client: AsyncClient, db: AsyncSession):
    rid = await _region(db)
    other = Region(name="Чужий-регіон")
    db.add(other)
    await db.commit()
    mod = await create_user(db, "mod_att@test.com", UserRole.MODERATOR)
    mod.region_id = rid
    foreign = await create_user(db, "foreign_doc@test.com", UserRole.DOCTOR)
    foreign.region_id = other.id
    own = await create_user(db, "own_doc@test.com", UserRole.DOCTOR)
    own.region_id = rid
    await db.commit()
    p = await _patient(db, "mod_att_pat@test.com", region_id=rid)
    h = {"Authorization": f"Bearer {get_token_for_user(mod)}"}
    bad = await client.patch(f"/api/v1/patients/{p.id}/status", headers=h, json={"status": "ATTACHED", "doctor_id": foreign.id})
    assert bad.status_code == 403
    ok = await client.patch(f"/api/v1/patients/{p.id}/status", headers=h, json={"status": "ATTACHED", "doctor_id": own.id})
    assert ok.status_code == 200
