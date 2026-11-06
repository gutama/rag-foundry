"""Append-only entity lineage for merges and splits (ADR-0012).

Revision ID: c3d54973f560
Revises: d5faa98d8261
Create Date: 2026-11-06 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d54973f560'
down_revision: Union[str, Sequence[str], None] = 'd5faa98d8261'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXED = ('event_id', 'predecessor_id', 'successor_id', 'workspace_id')


def upgrade() -> None:
    """Create the entity lineage table."""
    op.create_table(
        'entity_lineage',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('event_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=16), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('predecessor_id', sa.Uuid(), nullable=False),
        sa.Column('successor_id', sa.Uuid(), nullable=False),
        sa.Column('actor_id', sa.String(length=256), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(['predecessor_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['successor_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in _INDEXED:
        op.create_index(
            op.f(f'ix_entity_lineage_{column}'),
            'entity_lineage',
            [column],
            unique=False,
        )


def downgrade() -> None:
    """Drop the entity lineage table."""
    for column in reversed(_INDEXED):
        op.drop_index(
            op.f(f'ix_entity_lineage_{column}'), table_name='entity_lineage'
        )
    op.drop_table('entity_lineage')
