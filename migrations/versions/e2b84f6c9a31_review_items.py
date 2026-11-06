"""Curator review queue items (ADR-0022).

Revision ID: e2b84f6c9a31
Revises: a7c19e4b2d10
Create Date: 2026-11-06 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b84f6c9a31'
down_revision: Union[str, Sequence[str], None] = 'a7c19e4b2d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXED = ('status', 'target_id', 'workspace_id')


def upgrade() -> None:
    """Create the review item table."""
    op.create_table(
        'review_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('semantic_profile_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column('decided_by', sa.String(length=256), nullable=True),
        sa.Column(
            'decided_at', sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in _INDEXED:
        op.create_index(
            op.f(f'ix_review_items_{column}'), 'review_items', [column],
            unique=False,
        )


def downgrade() -> None:
    """Drop the review item table."""
    for column in reversed(_INDEXED):
        op.drop_index(
            op.f(f'ix_review_items_{column}'), table_name='review_items'
        )
    op.drop_table('review_items')
