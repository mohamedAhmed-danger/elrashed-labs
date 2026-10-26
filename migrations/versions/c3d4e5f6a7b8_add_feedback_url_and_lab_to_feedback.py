"""add feedback_url to laboratories and laboratory_id to feedbacks

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-26 18:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add feedback_url to laboratories
    with op.batch_alter_table('laboratories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('feedback_url', sa.String(length=255), nullable=True))

    # 2. Add laboratory_id and make reference_id nullable in feedbacks
    with op.batch_alter_table('feedbacks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('laboratory_id', sa.Integer(), nullable=True))
        batch_op.alter_column('reference_id', existing_type=sa.String(length=50), nullable=True)
        batch_op.create_foreign_key('fk_feedbacks_laboratory', 'laboratories', ['laboratory_id'], ['id'])
        batch_op.create_index('ix_feedbacks_laboratory_id', ['laboratory_id'], unique=False)

    # 3. Best-effort backfill laboratory_id from matching bookings
    try:
        conn = op.get_bind()
        conn.execute(sa.text(
            "UPDATE feedbacks SET laboratory_id = ("
            "  SELECT bookings.laboratory_id FROM bookings "
            "  WHERE bookings.reference_id = feedbacks.reference_id LIMIT 1"
            ") WHERE feedbacks.laboratory_id IS NULL AND feedbacks.reference_id IS NOT NULL"
        ))
    except Exception:
        pass


def downgrade():
    with op.batch_alter_table('feedbacks', schema=None) as batch_op:
        batch_op.drop_index('ix_feedbacks_laboratory_id')
        batch_op.drop_constraint('fk_feedbacks_laboratory', type_='foreignkey')
        batch_op.alter_column('reference_id', existing_type=sa.String(length=50), nullable=False)
        batch_op.drop_column('laboratory_id')

    with op.batch_alter_table('laboratories', schema=None) as batch_op:
        batch_op.drop_column('feedback_url')
