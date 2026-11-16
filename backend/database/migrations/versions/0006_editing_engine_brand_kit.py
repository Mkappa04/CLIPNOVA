"""editing engine: AI editing plan per clip, Brand Kit assets

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('brand_assets',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('owner', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('stored_name', sa.String(length=80), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('has_alpha', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('brand_assets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_brand_assets_owner'), ['owner'], unique=False)
    with op.batch_alter_table('clips', schema=None) as batch_op:
        batch_op.add_column(sa.Column('edit_plan', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clips', schema=None) as batch_op:
        batch_op.drop_column('edit_plan')
    with op.batch_alter_table('brand_assets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_brand_assets_owner'))
    op.drop_table('brand_assets')
