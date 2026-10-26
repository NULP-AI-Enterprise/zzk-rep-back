import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import Base, get_db
from main import app
from app.models.models import AuthToken, User, UserRole
from app.core.security import create_access_token

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSession = async_sessionmaker(engine_test, expire_on_commit=False)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSession() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSession() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Seed helpers ──────────────────────────────────────────────────────────────

async def create_user(db: AsyncSession, email: str, role: UserRole, **kwargs) -> User:
    user = User(
        email=email,
        role=role,
        first_name=kwargs.get("first_name", "Тест"),
        last_name=kwargs.get("last_name", "Тестовий"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def get_token_for_user(user: User) -> str:
    """Генеруємо JWT напряму для тестів — без email round-trip."""
    return create_access_token({"sub": f"user:{user.id}", "role": user.role.value})


def get_token_for_patient(patient) -> str:
    return create_access_token({"sub": f"patient:{patient.id}", "role": "PATIENT"})