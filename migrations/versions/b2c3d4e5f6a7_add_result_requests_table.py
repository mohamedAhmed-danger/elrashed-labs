"""add result_requests table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-21 12:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'result_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_identity', sa.String(length=150), nullable=False),
        sa.Column('laboratory_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'REVIEWED', 'ATTENDED', 'NO_SHOW', name='status'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['laboratory_id'], ['laboratories.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_result_requests_user_identity', 'result_requests', ['user_identity'], unique=False)


def downgrade():
    op.drop_index('ix_result_requests_user_identity', table_name='result_requests')
    op.drop_table('result_requests')
