"""Extend chunks with pgvector embeddings, FTS tsvector, ACLs, and provenance.

Revision ID: f4a7c2d81e53
Revises: e2b84f6c9a31
Create Date: 2026-11-18 20:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from rag_foundry.db.types import (
    DEFAULT_EMBEDDING_DIM,
    TSVectorType,
    VectorType,
)

# revision identifiers, used by Alembic.
revision: str = 'f4a7c2d81e53'
down_revision: Union[str, Sequence[str], None] = 'e2b84f6c9a31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add vector, full-text search, provenance, and ACL columns to chunks."""
    dialect_name = op.get_context().dialect.name
    if dialect_name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.add_column(
        'chunks',
        sa.Column(
            'chunk_index',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'chunks',
        sa.Column(
            'bounding_boxes',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        'chunks',
        sa.Column(
            'security_domain',
            sa.String(length=128),
            nullable=False,
            server_default='general',
        ),
    )
    op.add_column(
        'chunks',
        sa.Column(
            'chunk_metadata',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        'chunks',
        sa.Column(
            'embedding',
            VectorType(DEFAULT_EMBEDDING_DIM),
            nullable=True,
        ),
    )
    op.add_column(
        'chunks',
        sa.Column('embedding_model', sa.String(length=256), nullable=True),
    )
    op.add_column(
        'chunks',
        sa.Column('embedding_dim', sa.Integer(), nullable=True),
    )
    op.add_column(
        'chunks',
        sa.Column('search_vector', TSVectorType(), nullable=True),
    )

    op.create_index(
        op.f('ix_chunks_security_domain'),
        'chunks',
        ['security_domain'],
        unique=False,
    )
    op.create_index(
        'ix_chunks_workspace_security_domain',
        'chunks',
        ['workspace_id', 'security_domain'],
        unique=False,
    )
    op.create_index(
        'ix_chunks_search_vector_gin',
        'chunks',
        ['search_vector'],
        unique=False,
        postgresql_using='gin',
    )
    op.create_index(
        'ix_chunks_embedding_hnsw',
        'chunks',
        ['embedding'],
        unique=False,
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )


def downgrade() -> None:
    """Remove vector, full-text search, provenance, and ACL chunk columns."""
    op.drop_index('ix_chunks_embedding_hnsw', table_name='chunks')
    op.drop_index('ix_chunks_search_vector_gin', table_name='chunks')
    op.drop_index(
        'ix_chunks_workspace_security_domain', table_name='chunks'
    )
    op.drop_index(op.f('ix_chunks_security_domain'), table_name='chunks')

    with op.batch_alter_table('chunks') as batch_op:
        batch_op.drop_column('search_vector')
        batch_op.drop_column('embedding_dim')
        batch_op.drop_column('embedding_model')
        batch_op.drop_column('embedding')
        batch_op.drop_column('chunk_metadata')
        batch_op.drop_column('security_domain')
        batch_op.drop_column('bounding_boxes')
        batch_op.drop_column('chunk_index')
