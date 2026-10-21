"""multi lab isolation: lab identity, user roles, booking/complaint lab FK, usage table

Revision ID: a1b2c3d4e5f6
Revises: 5845382105e1
Create Date: 2026-10-19 12:00:00

Existing rows are attached to the first laboratory (lowest id) and every
existing user becomes an admin, so nothing changes for the running lab.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '5845382105e1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ---- laboratories: identity + billing link -------------------------------
    with op.batch_alter_table('laboratories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('logo_path', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('support_phone', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('notification_email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('billing_laboratory_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_laboratories_billing', 'laboratories', ['billing_laboratory_id'], ['id'])

    first_lab_id = conn.execute(sa.text("SELECT MIN(id) FROM laboratories")).scalar()

    # ---- users: lab + role (existing users stay admins) ----------------------
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('laboratory_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=False, server_default='admin'))
        batch_op.create_index('ix_users_laboratory_id', ['laboratory_id'], unique=False)
        batch_op.create_foreign_key('fk_users_laboratory', 'laboratories', ['laboratory_id'], ['id'])
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('role', existing_type=sa.String(length=20), server_default=None, existing_nullable=False)

    # ---- bookings / complaints: add nullable, backfill, then NOT NULL --------
    for table in ('bookings', 'complaints'):
        existing = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar()
        if existing and first_lab_id is None:
            raise RuntimeError(
                f"Table '{table}' has rows but there is no laboratory to attach them to. "
                "Create a laboratory first, then run the migration again."
            )

        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('laboratory_id', sa.Integer(), nullable=True))

        if first_lab_id is not None:
            conn.execute(
                sa.text(f"UPDATE {table} SET laboratory_id = :lab WHERE laboratory_id IS NULL"),
                {"lab": first_lab_id},
            )

        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('laboratory_id', existing_type=sa.Integer(), nullable=False)
            batch_op.create_index(f'ix_{table}_laboratory_id', ['laboratory_id'], unique=False)
            batch_op.create_foreign_key(f'fk_{table}_laboratory', 'laboratories', ['laboratory_id'], ['id'])

    # ---- per-lab usage ledger -------------------------------------------------
    op.create_table(
        'lab_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('laboratory_id', sa.Integer(), nullable=False),
        sa.Column('usage_date', sa.Date(), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['laboratory_id'], ['laboratories.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('laboratory_id', 'usage_date', name='uq_lab_usage_lab_date'),
    )
    op.create_index('ix_lab_usage_laboratory_id', 'lab_usage', ['laboratory_id'], unique=False)


def downgrade():
    op.drop_index('ix_lab_usage_laboratory_id', table_name='lab_usage')
    op.drop_table('lab_usage')

    for table in ('complaints', 'bookings'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'fk_{table}_laboratory', type_='foreignkey')
            batch_op.drop_index(f'ix_{table}_laboratory_id')
            batch_op.drop_column('laboratory_id')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_laboratory', type_='foreignkey')
        batch_op.drop_index('ix_users_laboratory_id')
        batch_op.drop_column('role')
        batch_op.drop_column('laboratory_id')

    with op.batch_alter_table('laboratories', schema=None) as batch_op:
        batch_op.drop_constraint('fk_laboratories_billing', type_='foreignkey')
        batch_op.drop_column('billing_laboratory_id')
        batch_op.drop_column('notification_email')
        batch_op.drop_column('support_phone')
        batch_op.drop_column('logo_path')
