"""Assertion validation reports pinned to ontology releases (ADR-0014).

Revision ID: a7c19e4b2d10
Revises: b5d25670ed6d
Create Date: 2026-11-06 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c19e4b2d10'
down_revision: Union[str, Sequence[str], None] = 'b5d25670ed6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the assertion validation table."""
    op.create_table(
        'assertion_validations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('assertion_id', sa.Uuid(), nullable=False),
        sa.Column('ontology_release_id', sa.Uuid(), nullable=False),
        sa.Column('ontology_version', sa.String(length=64), nullable=False),
        sa.Column('policy_id', sa.String(length=128), nullable=False),
        sa.Column('policy_version', sa.String(length=64), nullable=False),
        sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('findings', sa.JSON(), nullable=False),
        sa.Column('actor_id', sa.String(length=256), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['assertion_id'], ['semantic_assertions.id']
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_assertion_validations_assertion_id'),
        'assertion_validations',
        ['assertion_id'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the assertion validation table."""
    op.drop_index(
        op.f('ix_assertion_validations_assertion_id'),
        table_name='assertion_validations',
    )
    op.drop_table('assertion_validations')
