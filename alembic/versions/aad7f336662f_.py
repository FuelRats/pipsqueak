"""Update starsystem_refreshed data type to a proper timestamp.

Revision ID: aad7f336662f
Revises: 6a5e9a3c5e18
Create Date: 2016-02-17 20:25:39.749744

"""

# revision identifiers, used by Alembic.
revision = 'aad7f336662f'
down_revision = '6a5e9a3c5e18'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.execute("""
        ALTER TABLE status ALTER starsystem_refreshed TYPE TIMESTAMP WITH TIME ZONE
        USING CASE
            WHEN starsystem_refreshed IS NULL THEN NULL
            ELSE (TIMESTAMP WITH TIME ZONE 'epoch' + starsystem_refreshed * INTERVAL '1 second')
        END
    """)
    pass


def downgrade():
    op.execute("""
        ALTER TABLE status ALTER starsystem_refreshed TYPE INT
        USING CASE
            WHEN starsystem_refreshed IS NULL THEN NULL
            ELSE EXTRACT(EPOCH FROM starsystem_refreshed)
        END
    """)
    pass
