"""Initial SQLite database creation script.

Revision ID: 196145ed4c8c
Revises: 
Create Date: 2016-02-12 15:41:08.452734

"""

# revision identifiers, used by Alembic.
revision = '196145ed4c8c'
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'ratbot_fact',
        sa.Column('name', sa.Text, primary_key=True),
        sa.Column('lang', sa.Text, primary_key=True),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('author', sa.Text, nullable=True)
    )


def downgrade():
    op.drop_table('ratbot_fact')
