"""Entity identity schema: entities, identifiers and mentions (ADR-0012).

Revision ID: bd8685ecd2ef
Revises: c1949d0ff61b
Create Date: 2026-11-06 09:55:16.376781

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd8685ecd2ef'
down_revision: Union[str, Sequence[str], None] = 'c1949d0ff61b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the entity, entity identifier and mention tables."""
    op.create_table(
        'entities',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('semantic_profile_id', sa.Uuid(), nullable=False),
        sa.Column('canonical_uri', sa.String(length=512), nullable=False),
        sa.Column(
            'ontology_class_uri', sa.String(length=512), nullable=False
        ),
        sa.Column('preferred_labels', sa.JSON(), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('merged_into_id', sa.Uuid(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(['merged_into_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'workspace_id', 'canonical_uri', name='uq_entity_canonical_uri'
        ),
    )
    for column in ('ontology_class_uri', 'semantic_profile_id',
                   'workspace_id'):
        op.create_index(
            op.f(f'ix_entities_{column}'), 'entities', [column],
            unique=False,
        )

    op.create_table(
        'entity_identifiers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('scheme', sa.String(length=64), nullable=False),
        sa.Column('value', sa.String(length=256), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['entity_id'], ['entities.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'entity_id', 'scheme', name='uq_entity_identifier_scheme'
        ),
        sa.UniqueConstraint(
            'workspace_id', 'scheme', 'value',
            name='uq_entity_identifier_value',
        ),
    )
    op.create_index(
        op.f('ix_entity_identifiers_entity_id'),
        'entity_identifiers',
        ['entity_id'],
        unique=False,
    )

    op.create_table(
        'entity_mentions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('semantic_profile_id', sa.Uuid(), nullable=False),
        sa.Column('chunk_id', sa.Uuid(), nullable=False),
        sa.Column('start_offset', sa.Integer(), nullable=False),
        sa.Column('end_offset', sa.Integer(), nullable=False),
        sa.Column('surface_text', sa.Text(), nullable=False),
        sa.Column(
            'ontology_class_uri', sa.String(length=512), nullable=True
        ),
        sa.Column('identifiers', sa.JSON(), nullable=False),
        sa.Column('resolution_status', sa.String(length=32), nullable=False),
        sa.Column('resolved_entity_id', sa.Uuid(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(['resolved_entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in ('chunk_id', 'resolved_entity_id', 'workspace_id'):
        op.create_index(
            op.f(f'ix_entity_mentions_{column}'), 'entity_mentions',
            [column], unique=False,
        )


def downgrade() -> None:
    """Drop the entity, entity identifier and mention tables."""
    for column in ('workspace_id', 'resolved_entity_id', 'chunk_id'):
        op.drop_index(
            op.f(f'ix_entity_mentions_{column}'),
            table_name='entity_mentions',
        )
    op.drop_table('entity_mentions')
    op.drop_index(
        op.f('ix_entity_identifiers_entity_id'),
        table_name='entity_identifiers',
    )
    op.drop_table('entity_identifiers')
    for column in ('workspace_id', 'semantic_profile_id',
                   'ontology_class_uri'):
        op.drop_index(op.f(f'ix_entities_{column}'), table_name='entities')
    op.drop_table('entities')
