"""Resolution candidates with scores, versions and decisions (ADR-0012).

Revision ID: d5faa98d8261
Revises: bd8685ecd2ef
Create Date: 2026-11-06 10:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5faa98d8261'
down_revision: Union[str, Sequence[str], None] = 'bd8685ecd2ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXED = ('decision', 'entity_id', 'mention_id', 'workspace_id')


def upgrade() -> None:
    """Create the resolution candidate table."""
    op.create_table(
        'resolution_candidates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('mention_id', sa.Uuid(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('method', sa.String(length=32), nullable=False),
        sa.Column('score_breakdown', sa.JSON(), nullable=False),
        sa.Column('matched_text', sa.Text(), nullable=True),
        sa.Column('policy_id', sa.String(length=128), nullable=False),
        sa.Column('policy_version', sa.String(length=64), nullable=False),
        sa.Column(
            'normalizer_version', sa.String(length=32), nullable=False
        ),
        sa.Column('ontology_release_id', sa.Uuid(), nullable=True),
        sa.Column('decision', sa.String(length=32), nullable=False),
        sa.Column('decided_by', sa.String(length=256), nullable=True),
        sa.Column(
            'decided_at', sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(
            ['mention_id'], ['entity_mentions.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'mention_id', 'run_number', 'rank',
            name='uq_resolution_candidate_rank',
        ),
    )
    for column in _INDEXED:
        op.create_index(
            op.f(f'ix_resolution_candidates_{column}'),
            'resolution_candidates',
            [column],
            unique=False,
        )


def downgrade() -> None:
    """Drop the resolution candidate table."""
    for column in reversed(_INDEXED):
        op.drop_index(
            op.f(f'ix_resolution_candidates_{column}'),
            table_name='resolution_candidates',
        )
    op.drop_table('resolution_candidates')
