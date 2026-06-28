"""fix auth_tokens datetime timezone

Revision ID: b3f1a2e4d5c6
Revises: 0c847fe2969a
Create Date: 2026-06-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3f1a2e4d5c6'
down_revision = '0c847fe2969a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'auth_tokens', 'expires_at',
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        postgresql_using='expires_at AT TIME ZONE \'UTC\'',
    )
    op.alter_column(
        'auth_tokens', 'used_at',
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=True,
        postgresql_using='used_at AT TIME ZONE \'UTC\'',
    )


def downgrade() -> None:
    op.alter_column(
        'auth_tokens', 'expires_at',
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        postgresql_using='expires_at AT TIME ZONE \'UTC\'',
    )
    op.alter_column(
        'auth_tokens', 'used_at',
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using='used_at AT TIME ZONE \'UTC\'',
    )
