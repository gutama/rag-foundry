"""Ontology registry schema: releases, classes and properties (ADR-0011).

Revision ID: c1949d0ff61b
Revises: a545ddc30037
Create Date: 2026-11-06 09:22:41.230982

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1949d0ff61b'
down_revision: Union[str, Sequence[str], None] = 'a545ddc30037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ontology release, class and property tables."""
    op.create_table(
        'ontology_releases',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('ontology_uri', sa.String(length=512), nullable=False),
        sa.Column('version', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('previous_release_id', sa.Uuid(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            'published_at', sa.DateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ['previous_release_id'], ['ontology_releases.id']
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ontology_uri', 'version', name='uq_ontology_release_version'
        ),
    )
    op.create_index(
        op.f('ix_ontology_releases_ontology_uri'),
        'ontology_releases',
        ['ontology_uri'],
        unique=False,
    )

    op.create_table(
        'ontology_classes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('uri', sa.String(length=512), nullable=False),
        sa.Column('preferred_labels', sa.JSON(), nullable=False),
        sa.Column('parent_class_uris', sa.JSON(), nullable=False),
        sa.Column('description', sa.JSON(), nullable=False),
        sa.Column('identity_rules', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ['release_id'], ['ontology_releases.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'release_id', 'uri', name='uq_ontology_class_uri'
        ),
    )
    op.create_index(
        op.f('ix_ontology_classes_release_id'),
        'ontology_classes',
        ['release_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ontology_classes_uri'),
        'ontology_classes',
        ['uri'],
        unique=False,
    )

    op.create_table(
        'ontology_properties',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('uri', sa.String(length=512), nullable=False),
        sa.Column('preferred_labels', sa.JSON(), nullable=False),
        sa.Column('description', sa.JSON(), nullable=False),
        sa.Column('property_type', sa.String(length=16), nullable=False),
        sa.Column('domain_class_uris', sa.JSON(), nullable=False),
        sa.Column('range_class_uris', sa.JSON(), nullable=False),
        sa.Column('datatype', sa.String(length=512), nullable=True),
        sa.Column(
            'inverse_property_uri', sa.String(length=512), nullable=True
        ),
        sa.Column('temporal', sa.Boolean(), nullable=False),
        sa.Column('provenance_required', sa.Boolean(), nullable=False),
        sa.Column('constraints', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ['release_id'], ['ontology_releases.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'release_id', 'uri', name='uq_ontology_property_uri'
        ),
    )
    op.create_index(
        op.f('ix_ontology_properties_release_id'),
        'ontology_properties',
        ['release_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ontology_properties_uri'),
        'ontology_properties',
        ['uri'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ontology tables."""
    op.drop_index(
        op.f('ix_ontology_properties_uri'), table_name='ontology_properties'
    )
    op.drop_index(
        op.f('ix_ontology_properties_release_id'),
        table_name='ontology_properties',
    )
    op.drop_table('ontology_properties')
    op.drop_index(
        op.f('ix_ontology_classes_uri'), table_name='ontology_classes'
    )
    op.drop_index(
        op.f('ix_ontology_classes_release_id'), table_name='ontology_classes'
    )
    op.drop_table('ontology_classes')
    op.drop_index(
        op.f('ix_ontology_releases_ontology_uri'),
        table_name='ontology_releases',
    )
    op.drop_table('ontology_releases')
