"""surgery name/description, standalone lab results, pending email, auth token purpose

Revision ID: d1e2f3a4b5c6
Revises: c4e2f1a3b7d8
Create Date: 2026-07-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c4e2f1a3b7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Task 3: surgery name + description
    op.add_column('clinical_surgeries', sa.Column('operation_name', sa.String(length=200), nullable=True))
    op.add_column('clinical_surgeries', sa.Column('description', sa.Text(), nullable=True))

    # Task 5: pending email + auth token purpose
    op.add_column('patient_profiles', sa.Column('pending_email', sa.String(length=255), nullable=True))
    op.add_column('auth_tokens', sa.Column('purpose', sa.String(length=20), nullable=False, server_default='login'))

    # Task 6: standalone patient lab results
    op.create_table(
        'patient_lab_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('lab_type', sa.String(length=20), nullable=False),
        sa.Column('value', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('result_date', sa.Date(), nullable=False),
        sa.Column('added_by_user_id', sa.Integer(), nullable=True),
        sa.Column('added_by_role', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['patient_id'], ['patient_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['added_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_patient_lab_results_patient_id', 'patient_lab_results', ['patient_id'])


def downgrade() -> None:
    op.drop_index('ix_patient_lab_results_patient_id', table_name='patient_lab_results')
    op.drop_table('patient_lab_results')

    op.drop_column('auth_tokens', 'purpose')
    op.drop_column('patient_profiles', 'pending_email')

    op.drop_column('clinical_surgeries', 'description')
    op.drop_column('clinical_surgeries', 'operation_name')
