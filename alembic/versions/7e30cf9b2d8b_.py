"""Use C collation by default for starsystem tables.

Revision ID: 7e30cf9b2d8b
Revises: 46e931c30648
Create Date: 2016-02-15 15:19:49.306682

"""

# revision identifiers, used by Alembic.
revision = '7e30cf9b2d8b'
down_revision = '46e931c30648'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.alter_column("starsystem", "name", type_=sa.Text(collation="C"))
    op.alter_column("starsystem", "name_lower", type_=sa.Text(collation="C"))
    op.alter_column("starsystem_prefix", "first_word", type_=sa.Text(collation="C"))
    op.alter_column("starsystem_prefix", "const_words", type_=sa.Text(collation="C"))
    op.execute("UPDATE status SET starsystem_refreshed = NULL")
pass


def downgrade():
    pass
