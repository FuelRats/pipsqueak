"""Adds EDSM starsystem data storage.

Revision ID: 46e931c30648
Revises: 196145ed4c8c
Create Date: 2016-02-12 21:46:27.137507

"""

# revision identifiers, used by Alembic.
revision = '46e931c30648'
down_revision = '196145ed4c8c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'status',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('starsystem_refreshed', sa.Integer, nullable=True)  # Time of last refresh
    )

    # Starsystem stats.
    op.create_table(
        'starsystem_prefix',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('first_word', sa.Text, nullable=False),  # First word of star system name, lowercased.
        sa.Column('word_ct', sa.Integer, nullable=False),  # Minimum number of words in system name.
        sa.Column('const_words', sa.Text, nullable=True),  # Constant words that always occur after the first word.
    )
    op.create_index(
        'starsystem_prefix__unique_words', 'starsystem_prefix',
        ['first_word', 'word_ct'],
        unique=True
    )

    op.create_table(
        'starsystem',
        sa.Column('id', sa.Integer, primary_key=True),  # Starsystem name, lowercased
        sa.Column('name_lower', sa.Text, nullable=False),  # Starsystem name, normalized
        sa.Column('name', sa.Text, nullable=False),  # Name with proper capitalization
        sa.Column('word_ct', sa.Integer, nullable=False),  # Number of words in name
        sa.Column('x', sa.Float),  # x-coordinate
        sa.Column('y', sa.Float),  # y-coordinate
        sa.Column('z', sa.Float),  # z-coordinate
        sa.Column(
            'prefix_id', sa.Integer,
            sa.ForeignKey("starsystem_prefix.id", ondelete='set null', onupdate='cascade'),
            nullable=True
        )
    )
    op.create_index('starsystem__name_lower', 'starsystem', ['name_lower'])
    op.create_index('starsystem__prefix_id', 'starsystem', ['prefix_id'])


def downgrade():
    op.drop_table('status')
    op.drop_table('starsystem')
    op.drop_table('starsystem_prefix')
