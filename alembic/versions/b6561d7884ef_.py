"""Starsystem Storage Improvements

Revision ID: b6561d7884ef
Revises: aad7f336662f
Create Date: 2016-11-17 19:05:01.898722

"""

# revision identifiers, used by Alembic.
revision = 'b6561d7884ef'
down_revision = 'aad7f336662f'
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
    # These columns are used for starsystem prefix matching.  Used in various operations throughout this migration
    fk_cols = ['first_word', 'word_ct']

    # Starsystem stats - force a refresh.
    op.execute("UPDATE status SET starsystem_refreshed=NULL")

    # Starsystem updates:
    # It's not possible to migrate existing data due to structural changes... so wipe it prior to running the script.
    op.execute("TRUNCATE TABLE starsystem, starsystem_prefix")
    # op.execute("TRUNCATE TABLE starsystem_prefix CASCADE")

    # - Starsystem changes
    with op.batch_alter_table('starsystem') as batch:
        batch.add_column(sa.Column('first_word', sa.Text(collation="C"), nullable=False))  # New method of prefixes.
        batch.drop_column('x')
        batch.drop_column('z')
        batch.add_column(sa.Column('xz', SQLPoint))
        batch.drop_column('id')  # id
        batch.drop_column('prefix_id')  # Remove old method
        batch.alter_column('first_word', nullable=False)
        batch.add_column(sa.Column('eddb_id', sa.Integer, autoincrement=False))
        batch.create_index('starsystem__xz', ['xz'], postgresql_using='spgist')
        batch.create_index('starsystem__y', ['y'])
        batch.create_index('starsystem__prefix', fk_cols)
    op.create_primary_key('starsystem__pkey', 'starsystem', ['eddb_id'])

    # Alembic can't do this AFAIK
    op.execute(
        "ALTER TABLE starsystem ALTER COLUMN xz SET STATISTICS 10000, ALTER COLUMN y SET STATISTICS 10000"
    )

    # Starsystem_prefix updates:
    # - Get rid of artificial primary key - use (first word, word_ct) as new PK.
    # - Dispose of some fields we never used before
    with op.batch_alter_table('starsystem_prefix') as batch:
        batch.drop_column('id')
        batch.drop_column('const_words')  # Was never used for anything
        batch.drop_index('starsystem_prefix__unique_words')  # soon-to-be-created PK obsoletes this
    op.create_primary_key('starsystem__prefix__pkey', 'starsystem_prefix', fk_cols)

    # Recreate foreign key, now that we can.
    op.create_foreign_key('starsystem__prefix_fkey', 'starsystem', 'starsystem_prefix', fk_cols, fk_cols)

    # PostgreSQL stored procedures for plotting.
    op.execute("""
        CREATE OR REPLACE FUNCTION starsystem_distance(IN POINT, IN DOUBLE PRECISION, IN POINT, IN DOUBLE PRECISION)
        RETURNS DOUBLE PRECISION
        LANGUAGE SQL SECURITY INVOKER IMMUTABLE
        AS $$SELECT SQRT(($1[0]-$3[0])^2 + ($1[1]-$3[1])^2 + ($2-$4)^2)$$;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION find_route(
            IN source_id INT, IN target_id INT, IN maxdistance DOUBLE PRECISION,
            OUT eddb_id INT, OUT location DOUBLE PRECISION[], OUT distance DOUBLE PRECISION,
            OUT remaining DOUBLE PRECISION, OUT final BOOLEAN
        )
        RETURNS SETOF RECORD
        LANGUAGE PLPGSQL
        STRICT
        STABLE
        AS $PROC$
        DECLARE
            unit_box BOX DEFAULT '(-0.5,-0.5),(0.5,0.5)';
            -- Target coordinates
            target_xz POINT;
            target_y DOUBLE PRECISION;
            -- Current coordinates
            cur_xz POINT;
            cur_y DOUBLE PRECISION;
            -- Origin of search zone
            aim_xz POINT;
            aim_y DOUBLE PRECISION;
            -- Search zone
            search_xz BOX;
            search_ymin DOUBLE PRECISION;
            search_ymax DOUBLE PRECISION;
            -- Search "radius"
            search_min_radius NUMERIC DEFAULT LEAST(maxdistance, GREATEST(20, maxdistance/16));
            search_max_radius NUMERIC DEFAULT 2*maxdistance;
            search_radius NUMERIC;
        BEGIN
            SELECT xz, y INTO cur_xz, cur_y FROM starsystem AS s WHERE s.eddb_id=source_id;
            SELECT xz, y INTO target_xz, target_y FROM starsystem AS s WHERE s.eddb_id=target_id;
            IF cur_xz IS NULL OR cur_y IS NULL OR target_xz IS NULL OR target_y IS NULL THEN
                RETURN;
            END IF;
            eddb_id := source_id;
            distance := 0;
            remaining := starsystem_distance(cur_xz, cur_y, target_xz, target_y);
            <<outer>>

            WHILE TRUE LOOP
                RAISE NOTICE 'In loop';
                final := (eddb_id = target_id);
                location := ARRAY[cur_xz[0], cur_y, cur_xz[1]];
                RETURN NEXT;
                IF final THEN
                    RETURN;
                ELSIF remaining <= maxdistance THEN
                    distance := remaining;
                    remaining := 0;
                    location := ARRAY[target_xz[0], target_y, target_xz[1]];
                    eddb_id := target_id;
                    final := TRUE;
                    RETURN NEXT;
                    RETURN;
                END IF;

                -- Determine place to aim for
                aim_xz := (cur_xz + (target_xz - cur_xz)*POINT(maxdistance/remaining,0));
                aim_y :=  cur_y + (target_y - cur_y)*(maxdistance/remaining);

                -- Begin searching
                search_radius := search_min_radius;
                WHILE search_radius <= search_max_radius LOOP
                    search_xz := unit_box*POINT(search_radius,0) + aim_xz;
                    search_ymin := aim_y - search_radius;
                    search_ymax := aim_y + search_radius;
                    -- Uncomment for debugging
                    -- RAISE NOTICE 'cur_xz=%, cur_y=%, target_xz=%, target_y=%, aim_xz=%, aim_y=%, radius=%, remaining=%', cur_xz, cur_y, target_xz, target_y, aim_xz, aim_y, search_radius, remaining;
                    search_radius := search_radius*2;
                    BEGIN
                        SELECT
                            s.eddb_id, starsystem_distance(s.xz, s.y, cur_xz, cur_y) AS distance_from_here, starsystem_distance(s.xz, s.y, target_xz, target_y) AS distance_to_target, s.xz, s.y
                            INTO STRICT eddb_id, distance, remaining, cur_xz, cur_y
                        FROM
                            starsystem AS s
                        WHERE
                            -- Search parameters
                            s.xz <@ search_xz
                            AND s.y BETWEEN search_ymin AND search_ymax
                            -- Ensure it's within maximum jump range
                            AND starsystem_distance(s.xz, s.y, cur_xz, cur_y) <= maxdistance
                            -- Ensure it's not further than we are; that's counterproductive
                            AND starsystem_distance(s.xz, s.y, target_xz, target_y) < remaining
                            -- We want the system with the least distance remaining
                            ORDER BY starsystem_distance(s.xz, s.y, target_xz, target_y)
                            LIMIT 1
                        ;
                    EXCEPTION
                        WHEN NO_DATA_FOUND THEN CONTINUE;
                    END;
                    search_radius := NULL;  -- Force loop to terminate if we found a system.
                END LOOP;
            END LOOP;
        END
        $PROC$;
    """)


def downgrade():
    # We lose const_words in the upgrade process, so the only clean downgrade requires reloading the entire db.
    # That simplifies the downgrade SQL, at least -- we just drop and recreate the tables and mark starsystem db
    # outdated.

    # Starsystem stats - force a refresh.
    op.execute("UPDATE status SET starsystem_refreshed=NULL")

    op.drop_table("starsystem")
    op.drop_table("starsystem_prefix")
    op.execute("DROP FUNCTION IF EXISTS starsystem__tproc()")
    op.execute("DROP FUNCTION IF EXISTS starsystem_distance()")
    op.execute("DROP FUNCTION IF EXISTS find_route()")

    op.create_table(
        'starsystem_prefix',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('first_word', sa.Text(collation="C"), nullable=False),  # First word of star system name, lowercased.
        sa.Column('word_ct', sa.Integer, nullable=False),  # Minimum number of words in system name.
        sa.Column('const_words', sa.Text(collation="C"), nullable=True),  # Constant words that always occur after the first word.
        sa.Column('ratio', sa.Float()),
        sa.Column('cume_ratio', sa.Float())
    )
    op.create_index(
        'starsystem_prefix__unique_words', 'starsystem_prefix',
        ['first_word', 'word_ct'],
        unique=True
    )

    op.create_table(
        'starsystem',
        sa.Column('id', sa.Integer, primary_key=True),  # Starsystem name, lowercased
        sa.Column('name_lower', sa.Text(collation="C"), nullable=False),  # Starsystem name, normalized
        sa.Column('name', sa.Text(collation="C"), nullable=False),  # Name with proper capitalization
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
