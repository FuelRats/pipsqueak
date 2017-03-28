"""Adding additional starsystem statistics.

Revision ID: 6a5e9a3c5e18
Revises: 7e30cf9b2d8b
Create Date: 2016-02-15 19:28:01.359937

"""

# revision identifiers, used by Alembic.
revision = '6a5e9a3c5e18'
down_revision = '7e30cf9b2d8b'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table("starsystem_prefix") as batch:
        batch.add_column(sa.Column('ratio', sa.Float()))
        batch.add_column(sa.Column('cume_ratio', sa.Float()))
    op.execute(
        """
        UPDATE starsystem_prefix SET ratio=t.ratio, cume_ratio=t.cume_ratio
        FROM (
            SELECT t.id, ct/SUM(ct) OVER w AS ratio, SUM(ct) OVER p/SUM(ct) OVER w AS cume_ratio
            FROM (
                SELECT sp.*, COUNT(*) AS ct
                FROM
                    starsystem_prefix AS sp
                    INNER JOIN starsystem AS s ON s.prefix_id=sp.id
                GROUP BY sp.id
                HAVING COUNT(*) > 0
            ) AS t
            WINDOW
            w AS (PARTITION BY t.first_word ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING),
            p AS (PARTITION BY t.first_word ORDER BY t.word_ct ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        ) AS t
        WHERE t.id=starsystem_prefix.id
        """
    )


def downgrade():
    with op.batch_alter_table("starsystem_prefix") as batch:
        batch.drop_column('ratio')
        batch.drop_column('cume_ratio')
