import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import UserRole
from tests.conftest import create_user, get_token_for_user

PATIENT_PAYLOAD = {
    "surname": "Тестовий",
    "initials": "Т.Т.",
    "sex": "M",
    "email": "patient_unique@test.com",
    "birth_year": 1985,
    "disability": "NONE",
    "diagnosis": "CD",
    "histologically_confirmed": "YES",
    "doctor_id": None,
}


@pytest.mark.asyncio
async def test_create_patient_by_doctor(client: AsyncClient, db: AsyncSession):
    doctor = await create_user(db, "doc_create@test.com", UserRole.DOCTOR)
    token = get_token_for_user(doctor)

    payload = {**PATIENT_PAYLOAD, "email": "pat1@test.com", "doctor_id": doctor.id}
    resp = await client.post(
        "/api/v1/patients",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["initials"] == "ТТ"
    assert data["diagnosis"] == "CD"
    assert data["status"] == "PENDING"
    assert data["surname"] == "Тестовий"


@pytest.mark.asyncio
async def test_create_patient_patient_role_forbidden(client: AsyncClient, db: AsyncSession):
    patient_user = await create_user(db, "pat_role@test.com", UserRole.PATIENT)
    token = get_token_for_user(patient_user)

    payload = {**PATIENT_PAYLOAD, "email": "pat2@test.com", "doctor_id": 1}
    resp = await client.post(
        "/api/v1/patients",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_patients_doctor_sees_only_own(client: AsyncClient, db: AsyncSession):
    doc1 = await create_user(db, "doc_list1@test.com", UserRole.DOCTOR)
    doc2 = await create_user(db, "doc_list2@test.com", UserRole.DOCTOR)
    token1 = get_token_for_user(doc1)
    token2 = get_token_for_user(doc2)

    await client.post(
        "/api/v1/patients",
        json={**PATIENT_PAYLOAD, "email": "pat_doc1@test.com", "doctor_id": doc1.id},
        headers={"Authorization": f"Bearer {token1}"},
    )

    resp = await client.get("/api/v1/patients", headers={"Authorization": f"Bearer {token2}"})
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    # Лікар 2 не бачить пацієнтів лікаря 1
    resp1 = await client.get("/api/v1/patients", headers={"Authorization": f"Bearer {token1}"})
    pat_ids_doc1 = [p["id"] for p in resp1.json()]
    for pid in pat_ids_doc1:
        assert pid not in ids


@pytest.mark.asyncio
async def test_admin_sees_all_patients(client: AsyncClient, db: AsyncSession):
    doc = await create_user(db, "doc_admin_test@test.com", UserRole.DOCTOR)
    admin = await create_user(db, "admin_patients@test.com", UserRole.ADMIN)
    doc_token = get_token_for_user(doc)
    admin_token = get_token_for_user(admin)

    create_pat = await client.post(
        "/api/v1/patients",
        json={**PATIENT_PAYLOAD, "email": "pat_for_admin@test.com", "doctor_id": doc.id},
        headers={"Authorization": f"Bearer {doc_token}"},
    )
    pat_id = create_pat.json()["id"]

    resp = await client.get("/api/v1/patients", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert pat_id in ids


@pytest.mark.asyncio
async def test_admin_cannot_see_surname(client: AsyncClient, db: AsyncSession):
    doc = await create_user(db, "doc_surname@test.com", UserRole.DOCTOR)
    admin = await create_user(db, "admin_surname@test.com", UserRole.ADMIN)
    doc_token = get_token_for_user(doc)
    admin_token = get_token_for_user(admin)

    create_resp = await client.post(
        "/api/v1/patients",
        json={**PATIENT_PAYLOAD, "email": "pat_surname@test.com", "doctor_id": doc.id},
        headers={"Authorization": f"Bearer {doc_token}"},
    )
    patient_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/patients/{patient_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["surname"] is None


@pytest.mark.asyncio
async def test_update_patient_status(client: AsyncClient, db: AsyncSession):
    doc = await create_user(db, "doc_status@test.com", UserRole.DOCTOR)
    token = get_token_for_user(doc)

    create_resp = await client.post(
        "/api/v1/patients",
        json={**PATIENT_PAYLOAD, "email": "pat_status@test.com", "doctor_id": doc.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    patient_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "PENDING"

    resp = await client.patch(
        f"/api/v1/patients/{patient_id}/status",
        json={"status": "ATTACHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ATTACHED"

    resp = await client.patch(
        f"/api/v1/patients/{patient_id}/status",
        json={"status": "DETACHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "DETACHED"


@pytest.mark.asyncio
async def test_list_by_status_filters(client: AsyncClient, db: AsyncSession):
    doc = await create_user(db, "doc_filter@test.com", UserRole.DOCTOR)
    token = get_token_for_user(doc)

    create_resp = await client.post(
        "/api/v1/patients",
        json={**PATIENT_PAYLOAD, "email": "pat_pending@test.com", "doctor_id": doc.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    patient_id = create_resp.json()["id"]

    resp = await client.get("/api/v1/patients/pending", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert patient_id in ids

    await client.patch(
        f"/api/v1/patients/{patient_id}/status",
        json={"status": "ATTACHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get("/api/v1/patients/attached", headers={"Authorization": f"Bearer {token}"})
    ids = [p["id"] for p in resp.json()]
    assert patient_id in ids

    await client.patch(
        f"/api/v1/patients/{patient_id}/status",
        json={"status": "DETACHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get("/api/v1/patients/detached", headers={"Authorization": f"Bearer {token}"})
    ids = [p["id"] for p in resp.json()]
    assert patient_id in ids