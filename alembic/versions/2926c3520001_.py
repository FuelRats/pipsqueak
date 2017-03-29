"""Database support for Landmarks.

Revision ID: 2926c3520001
Revises: b6561d7884ef
Create Date: 2016-12-07 20:42:00.001800

"""

# revision identifiers, used by Alembic.
revision = '2926c3520001'
down_revision = 'b6561d7884ef'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy import types


# This is a dummy just for Alembic -- an actual implementation is elsewhere but is not needed here.
# version of it here just for importing
class SQLPoint(types.UserDefinedType):
    def get_col_spec(self):
        return "POINT"


def upgrade():
    op.create_table(
        'landmark',
        sa.Column('name_lower', sa.Text, primary_key=True),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('xz', SQLPoint, nullable=True),
        sa.Column('y', sa.Float, nullable=True)
    )


def downgrade():
    op.drop_table('landmark')
    pass
