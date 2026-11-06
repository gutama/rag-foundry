"""Semantic assertions and their append-only status log (ADR-0014).

Revision ID: b5d25670ed6d
Revises: c3d54973f560
Create Date: 2026-11-06 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d25670ed6d'
down_revision: Union[str, Sequence[str], None] = 'c3d54973f560'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ASSERTION_INDEXES = (
    'object_entity_id',
    'property_uri',
    'status',
    'subject_entity_id',
    'workspace_id',
)


def upgrade() -> None:
    """Create the assertion and assertion transition tables."""
    op.create_table(
        'semantic_assertions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('semantic_profile_id', sa.Uuid(), nullable=False),
        sa.Column('subject_entity_id', sa.Uuid(), nullable=False),
        sa.Column('property_uri', sa.String(length=512), nullable=False),
        sa.Column('object_entity_id', sa.Uuid(), nullable=True),
        sa.Column(
            'literal_value', sa.JSON(none_as_null=True), nullable=True
        ),
        sa.Column('source_chunk_ids', sa.JSON(), nullable=False),
        sa.Column('origin', sa.String(length=16), nullable=False),
        sa.Column(
            'extraction_method', sa.String(length=128), nullable=False
        ),
        sa.Column(
            'extraction_model', sa.String(length=256), nullable=True
        ),
        sa.Column(
            'extraction_prompt_version', sa.String(length=64),
            nullable=True,
        ),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('ontology_release_id', sa.Uuid(), nullable=True),
        sa.Column('requires_review', sa.Boolean(), nullable=False),
        sa.Column('review_reason', sa.Text(), nullable=True),
        sa.Column('superseded_by_id', sa.Uuid(), nullable=True),
        sa.Column(
            'valid_from', sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(['object_entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['subject_entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(
            ['superseded_by_id'], ['semantic_assertions.id']
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in _ASSERTION_INDEXES:
        op.create_index(
            op.f(f'ix_semantic_assertions_{column}'),
            'semantic_assertions',
            [column],
            unique=False,
        )

    op.create_table(
        'assertion_transitions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('assertion_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=32), nullable=True),
        sa.Column('to_status', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.String(length=256), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['assertion_id'], ['semantic_assertions.id']
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'assertion_id', 'sequence', name='uq_assertion_transition_seq'
        ),
    )
    op.create_index(
        op.f('ix_assertion_transitions_assertion_id'),
        'assertion_transitions',
        ['assertion_id'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the assertion and assertion transition tables."""
    op.drop_index(
        op.f('ix_assertion_transitions_assertion_id'),
        table_name='assertion_transitions',
    )
    op.drop_table('assertion_transitions')
    for column in reversed(_ASSERTION_INDEXES):
        op.drop_index(
            op.f(f'ix_semantic_assertions_{column}'),
            table_name='semantic_assertions',
        )
    op.drop_table('semantic_assertions')
