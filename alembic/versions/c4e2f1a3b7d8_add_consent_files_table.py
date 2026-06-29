"""add consent_files table

Revision ID: c4e2f1a3b7d8
Revises: b3f1a2e4d5c6
Create Date: 2026-06-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e2f1a3b7d8'
down_revision = 'b3f1a2e4d5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'consent_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('uploaded_by', sa.Integer(), nullable=False),
        sa.Column('s3_key', sa.String(length=500), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['patient_id'], ['patient_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_consent_files_patient_id', 'consent_files', ['patient_id'])


def downgrade() -> None:
    op.drop_index('ix_consent_files_patient_id', table_name='consent_files')
    op.drop_table('consent_files')
