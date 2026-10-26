"""
Тести для /api/v1/users
ADMIN — повний CRUD
DOCTOR / PATIENT — тільки свій профіль
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import UserRole
from tests.conftest import create_user, get_token_for_user


@pytest.mark.asyncio
async def test_admin_create_user(client: AsyncClient, db: AsyncSession):
    admin = await create_user(db, "admin_create@test.com", UserRole.ADMIN)
    token = get_token_for_user(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "new_doctor@test.com",
            "role": "DOCTOR",
            "first_name": "Іван",
            "last_name": "Петренко",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new_doctor@test.com"
    assert data["role"] == "DOCTOR"


@pytest.mark.asyncio
async def test_doctor_cannot_create_user(client: AsyncClient, db: AsyncSession):
    doctor = await create_user(db, "doc_no_create@test.com", UserRole.DOCTOR)
    token = get_token_for_user(doctor)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "x@test.com", "role": "DOCTOR", "first_name": "A", "last_name": "B"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient, db: AsyncSession):
    admin = await create_user(db, "admin_list@test.com", UserRole.ADMIN)
    await create_user(db, "doc_listed@test.com", UserRole.DOCTOR)
    token = get_token_for_user(admin)

    resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "doc_listed@test.com" in emails


@pytest.mark.asyncio
async def test_doctor_cannot_list_users(client: AsyncClient, db: AsyncSession):
    doctor = await create_user(db, "doc_no_list@test.com", UserRole.DOCTOR)
    token = get_token_for_user(doctor)

    resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_search_users(client: AsyncClient, db: AsyncSession):
    admin = await create_user(db, "admin_search@test.com", UserRole.ADMIN)
    await create_user(db, "searchable@test.com", UserRole.DOCTOR, first_name="Уніквас")
    token = get_token_for_user(admin)

    resp = await client.get(
        "/api/v1/users/search?name=Уніквас",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert any(u["first_name"] == "Уніквас" for u in resp.json())


@pytest.mark.asyncio
async def test_get_own_profile(client: AsyncClient, db: AsyncSession):
    user = await create_user(db, "own_profile@test.com", UserRole.DOCTOR)
    token = get_token_for_user(user)

    resp = await client.get(
        f"/api/v1/users/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "own_profile@test.com"


@pytest.mark.asyncio
async def test_doctor_cannot_get_other_profile(client: AsyncClient, db: AsyncSession):
    doc1 = await create_user(db, "doc_other1@test.com", UserRole.DOCTOR)
    doc2 = await create_user(db, "doc_other2@test.com", UserRole.DOCTOR)
    token = get_token_for_user(doc1)

    resp = await client.get(
        f"/api/v1/users/{doc2.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_own_profile(client: AsyncClient, db: AsyncSession):
    user = await create_user(db, "update_profile@test.com", UserRole.DOCTOR)
    token = get_token_for_user(user)

    resp = await client.patch(
        f"/api/v1/users/{user.id}",
        json={"job_position": "Гастроентеролог"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["job_position"] == "Гастроентеролог"


@pytest.mark.asyncio
async def test_admin_delete_user(client: AsyncClient, db: AsyncSession):
    admin = await create_user(db, "admin_del@test.com", UserRole.ADMIN)
    target = await create_user(db, "to_delete@test.com", UserRole.DOCTOR)
    token = get_token_for_user(admin)

    resp = await client.delete(
        f"/api/v1/users/{target.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Перевірити що видалено
    resp = await client.get(
        f"/api/v1/users/{target.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_email(client: AsyncClient, db: AsyncSession):
    admin = await create_user(db, "admin_dup@test.com", UserRole.ADMIN)
    await create_user(db, "dup_email@test.com", UserRole.DOCTOR)
    token = get_token_for_user(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "dup_email@test.com", "role": "DOCTOR", "first_name": "A", "last_name": "B"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409