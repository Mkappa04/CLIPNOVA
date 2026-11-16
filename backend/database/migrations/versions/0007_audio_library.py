"""audio library: music tracks and sound effects with license and provenance (Editing Engine 2.0)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audio_assets',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('origin', sa.String(length=10), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('duration', sa.Float(), nullable=False),
    sa.Column('bpm', sa.Float(), nullable=True),
    sa.Column('beat_offset', sa.Float(), nullable=False),
    sa.Column('drop_time', sa.Float(), nullable=True),
    sa.Column('loop_start', sa.Float(), nullable=True),
    sa.Column('loop_end', sa.Float(), nullable=True),
    sa.Column('loudness_db', sa.Float(), nullable=True),
    sa.Column('energy', sa.Float(), nullable=True),
    sa.Column('gain_db', sa.Float(), nullable=False),
    sa.Column('license', sa.String(length=30), nullable=False),
    sa.Column('attribution', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audio_assets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audio_assets_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_audio_assets_category'), ['category'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('audio_assets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audio_assets_category'))
        batch_op.drop_index(batch_op.f('ix_audio_assets_kind'))
    op.drop_table('audio_assets')
