"""add_vector_rag_profiles_table

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-13 15:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('vector_rag_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('owner_user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('vector_embedding_provider', sa.String(length=64), nullable=True),
        sa.Column('vector_embedding_base_url', sa.String(length=2048), nullable=True),
        sa.Column('vector_embedding_model', sa.String(length=255), nullable=True),
        sa.Column('vector_embedding_api_key_ciphertext', sa.Text(), nullable=True),
        sa.Column('vector_embedding_api_key_masked', sa.String(length=64), nullable=True),
        sa.Column('vector_rerank_provider', sa.String(length=64), nullable=True),
        sa.Column('vector_rerank_base_url', sa.String(length=2048), nullable=True),
        sa.Column('vector_rerank_model', sa.String(length=255), nullable=True),
        sa.Column('vector_rerank_api_key_ciphertext', sa.Text(), nullable=True),
        sa.Column('vector_rerank_api_key_masked', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vector_rag_profiles_owner_user_id', 'vector_rag_profiles', ['owner_user_id'])


def downgrade() -> None:
    op.drop_index('ix_vector_rag_profiles_owner_user_id', table_name='vector_rag_profiles')
    op.drop_table('vector_rag_profiles')
