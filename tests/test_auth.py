import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AuthToken, UserRole
from tests.conftest import create_user, get_token_for_user


@pytest.mark.asyncio
async def test_send_link_known_email(client: AsyncClient, db: AsyncSession):
    await create_user(db, "magic_known@test.com", UserRole.DOCTOR)
    resp = await client.post("/api/v1/auth/send-link", json={"email": "magic_known@test.com"})
    # Завжди 200 незалежно від існування email
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_send_link_unknown_email(client: AsyncClient):
    # Невідомий email — теж 200 (не розкриваємо існування акаунту)
    resp = await client.post("/api/v1/auth/send-link", json={"email": "nobody@test.com"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_verify_valid_token(client: AsyncClient, db: AsyncSession):
    user = await create_user(db, "magic_verify@test.com", UserRole.DOCTOR)

    token_value = secrets.token_urlsafe(48)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(auth_token)
    await db.commit()

    resp = await client.post("/api/v1/auth/verify", json={"token": token_value})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_verify_token_used_twice(client: AsyncClient, db: AsyncSession):
    user = await create_user(db, "magic_twice@test.com", UserRole.DOCTOR)

    token_value = secrets.token_urlsafe(48)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(auth_token)
    await db.commit()

    await client.post("/api/v1/auth/verify", json={"token": token_value})
    # Другий раз — має повернути 400
    resp = await client.post("/api/v1/auth/verify", json={"token": token_value})
    assert resp.status_code == 400
    assert "вже використано" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_verify_expired_token(client: AsyncClient, db: AsyncSession):
    user = await create_user(db, "magic_expired@test.com", UserRole.DOCTOR)

    token_value = secrets.token_urlsafe(48)
    auth_token = AuthToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # вже протермінований
    )
    db.add(auth_token)
    await db.commit()

    resp = await client.post("/api/v1/auth/verify", json={"token": token_value})
    assert resp.status_code == 400
    assert "минув" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_verify_invalid_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/verify", json={"token": "nonexistent-token"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_me(client: AsyncClient, db: AsyncSession):
    user = await create_user(db, "magic_me@test.com", UserRole.DOCTOR)
    token = get_token_for_user(user)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "magic_me@test.com"


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)  # HTTPBearer — залежить від версії FastAPI