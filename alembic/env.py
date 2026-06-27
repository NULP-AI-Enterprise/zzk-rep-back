import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

# Імпортуйте ваші моделі та конфіг
from app.models.models import Base
from app.core.config import settings

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    # Створюємо асинхронний двигун
    connectable = create_async_engine(
        settings.DATABASE_URL.split("?")[0],
        connect_args={"ssl": "require"} if settings.DB_SSL else {},
        poolclass=pool.NullPool,
    )

    # Використовуємо connect() для асинхронного з'єднання
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    # Запускаємо асинхронну функцію через asyncio
    asyncio.run(run_migrations_online())