"""
Utilities for handling starsystem names and the like.

This is specifically named 'starsystem' rather than 'system' for reasons that should be obvious.
"""
import io
import datetime
import re
import operator
import threading
from urllib.parse import urljoin
import csv
try:
    import collections.abc as collections_abc
except ImportError:
    import collections as collections_abc


import requests
import sqlalchemy as sa
from sqlalchemy import sql, orm, schema

from ratlib.db import get_status, get_session, with_session, Starsystem, StarsystemPrefix, SQLPoint, Point
from ratlib.bloom import BloomFilter
from ratlib import format_timestamp
from ratlib.util import timed, TimedResult

FLUSH_THRESHOLD = 25000  # Chunk size when refreshing starsystems


class ConcurrentOperationError(RuntimeError):
    pass


def refresh_database(
        bot,
        force=False, prune=True,
        limit_one=True, callback=None, background=False,
        _lock=threading.Lock()
):
    """
    Refreshes the database of starsystems.  Also rebuilds the bloom filter.
    :param bot: Bot instance
    :param force: True to force refresh regardless of age.
    :param prune: True to prune non-updated systems.  Keep True unless performance testing.
    :param limit_one: If True, prevents multiple concurrent refreshes.
    :param callback: Optional function that is called as soon as the system determines a refresh is needed.
        If running in the background, the function will be called immediately prior to the background task being
        scheduled.
    :param background: If True and a refresh is needed, it is submitted as a background task rather than running
        immediately.
    :param _lock: Internal lock against multiple calls.
    :returns: False if no refresh was needed.  Otherwise, a Future if background is True or True if a refresh occurred.
    :raises: ConcurrentOperationError if a refresh was already ongoing and limit_one is True.
    """
    release = False  # Whether to release the lock we did (not?) acquire.

    try:
        if limit_one:
            release = _lock.acquire(blocking=False)
            if not release:
                print('refresh_database call already in progress! Aborting.')
                return False
        result = _refresh_database(bot, force=force, prune=prune, callback=callback, background=background)
        if result and background and release:
            result.add_done_callback(lambda *a, **kw: _lock.release())
            release = False
        return result
    finally:
        if release:
            _lock.release()


@with_session
def _refresh_database(bot, force=False, prune=True, callback=None, background=False, db=None):
    """
    Actual implementation of refresh_database.

    Refreshes the database of starsystems.  Also rebuilds the bloom filter.
    :param bot: Bot instance
    :param force: True to force refresh
    :param prune: True to prune non-updated systems.  Keep True unless performance testing.
    :param callback: Optional function that is called as soon as the system determines a refresh is needed.
    :param background: If True and a refresh is needed, it is submitted as a background task rather than running
        immediately.
    :param db: Database handle

    Note that this function executes some raw SQL queries (among other voodoo).  This is for performance reasons
    concerning the insanely large dataset being handled, and should NOT serve as an example for implementation
    elsewhere.
    """
    eddb_url = bot.config.ratbot.edsm_url or "https://eddb.io/archive/v5/systems.csv"
    chunked = bot.config.ratbot.chunked_systems

    # Should really implement this, but until then
    if chunked:
        raise NotImplementedError("Chunked system loading is not implemented yet.")

    status = get_status(db)
    eddb_maxage = float(bot.config.ratbot.edsm_maxage or (7*86400))  # Once per week = 604800 seconds
    if not (
        force or
        not status.starsystem_refreshed or
        (datetime.datetime.now(tz=datetime.timezone.utc) - status.starsystem_refreshed).total_seconds() > eddb_maxage
    ):
        # No refresh needed.
        # print('not force and no refresh needed')
        return False

    if callback:
        callback()

    if background:
        print('Scheduling background refresh of starsystem data')
        return bot.memory['ratbot']['executor'].submit(
            _refresh_database, bot, force=True, callback=None, background=False
        )

    conn = db.connection()
    # Now in actual implementation beyond background scheduling

    # Counters for stats
    # All times in seconds
    stats = {
        'load': 0,      # Time spent retrieving the CSV file(s) and dumping it into a temptable in the db.
        'prune': 0,     # Time spent removing non-update updates.
        'systems': 0,   # Time spent merging starsystems into the db.
        'prefixes': 0,  # Time spent merging starsystem prefixes into the db.
        'stats': 0,     # Time spent (re)computing system statistics
        'bloom': 0,     # Time spent (re)building the system prefix bloom filter.
        'optimize': 0,  # Time spent optimizing/analyzing tables.
        'misc': 0,      # Miscellaneous tasks (total time - all other stats)
        'total': 0,     # Total time spent.
    }

    def log(fmt, *args, **kwargs):
        print("[{}] ".format(datetime.datetime.now()) + fmt.format(*args, **kwargs))

    overall_timer = TimedResult()
    log("Starsystem refresh started")
    if chunked:
        # FIXME: Needs to be reimplemented.
        log("Retrieving starsystem index at {}", eddb_url)
        with timed() as t:
            response = requests.get(eddb_url)
            response.raise_for_status()
            urls = list(urljoin(eddb_url, chunk["SectorName"]) for chunk in response.json())
        stats['index'] += t.seconds
        log("{} file(s) queued for starsystem refresh.  (Took {}}", len(urls), format_timestamp(t.delta))
    else:
        urls = [eddb_url]

    temptable = sa.Table(
        '_temp_new_starsystem', sa.MetaData(),
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('eddb_id', sa.Integer),
        sa.Column('name_lower', sa.Text(collation="C")),
        sa.Column('name', sa.Text(collation="C")),
        sa.Column('first_word', sa.Text(collation="C")),
        sa.Column('word_ct', sa.Integer),
        sa.Column('xz', SQLPoint),
        sa.Column('y', sa.Numeric),
        # sa.Index('_temp_id_ix', 'eddb_id'),
        prefixes=['TEMPORARY'], postgresql_on_commit='DROP'
    )
    temptable.create(conn)

    sql_args = {
        'sp': StarsystemPrefix.__tablename__,
        's': Starsystem.__tablename__,
        'ts': temptable.name,
        'tsp': '_temp_new_prefixes'
    }

    buffer = io.StringIO()  # Temporary IO buffer for COPY FROM
    columns = ['eddb_id', 'name_lower', 'name', 'first_word', 'word_ct', 'xz', 'y']  # Columns to copy to temptable
    getter = operator.itemgetter(*columns)
    total_flushed = 0  # Total number of flushed items so far
    pending_flush = 0  # Number of items waiting to flush

    def exec(sql, *args, **kwargs):
        try:
            conn.execute(sql.format(*args, **kwargs, **sql_args))
        except Exception as ex:
            log("Query failed.")
            import traceback
            traceback.print_exc()
            raise

    def flush():
        nonlocal buffer, total_flushed, pending_flush
        if not pending_flush:
            return
        log("Flushing system(s) {}-{}", total_flushed + 1, total_flushed + pending_flush)
        buffer.seek(0)
        cursor = conn.connection.cursor()
        cursor.copy_from(buffer, temptable.name, sep='\t', null='', columns=columns)
        buffer = io.StringIO()
        # systems = []
        total_flushed += pending_flush
        pending_flush = 0


    with timed() as t:
        for url in urls:
            log("Retrieving starsystem data at {}", url)
            try:
                response = requests.get(url, stream=True)
                reader = csv.DictReader(io.TextIOWrapper(response.raw))

                for row in reader:
                    # Parse and reformat system info from CSV
                    name, word_ct = re.subn(r'\s+', ' ', row['name'].strip())
                    name_lower = name.lower()
                    first_word, *unused = name_lower.split(" ", 1)
                    word_ct += 1
                    if all((row['x'], row['y'], row['z'])):
                        xz = "({x},{z})".format(**row)
                        y = row['y']
                    else:
                        xz = y = ''
                    system_raw = {
                        'eddb_id': str(row['id']),
                        'name_lower': name_lower,
                        'name': name,
                        'first_word': first_word,
                        'xz': xz,
                        'y': y,
                        'word_ct': str(word_ct)
                    }
                    pending_flush += 1
                    buffer.write("\t".join(getter(system_raw)))
                    buffer.write("\n")

                    if pending_flush >= FLUSH_THRESHOLD:
                        flush()
            except ValueError:
                pass
            except Exception as ex:
                log("Failed to retrieve data")
                import traceback
                traceback.print_exc()
            flush()
        log("Creating index")
        exec("CREATE INDEX ON {ts}(eddb_id)")
    stats['load'] += t.seconds

    with timed() as t:
        log("Removing possible duplicates")
        exec("DELETE FROM {ts} WHERE eddb_id NOT IN(SELECT MAX(id) AS id FROM {ts} GROUP BY eddb_id)")

        # No need for the temporary 'id' column at this point.
        exec("ALTER TABLE {ts} DROP id CASCADE");
        # Making this a primary key (or even just a unique key) apparently affects query planner performance vs the
        # non-existing unique key.
        exec("ALTER TABLE {ts} ADD PRIMARY KEY(eddb_id)");

        if prune:
            log("Removing non-updates to existing systems")
            # If a starsystem has been updated, at least one of 'name', 'xz' or 'y' are guaranteed to have changed.
            # (A change that effects word_ct would effect name as well, for instance.)
            # Delete any temporary systems that exist in the real table with matching attributes.
            exec("""
                DELETE FROM {ts} AS t USING {s} AS s
                WHERE s.eddb_id=t.eddb_id
                AND ROW(s.name, s.y) IS NOT DISTINCT FROM ROW(t.name, t.y)
                AND ((s.xz IS NULL)=(t.xz IS NULL)) AND (s.xz~=t.xz OR s.xz IS NULL)
            """)
        else:
            log("Skipping non-update removal phase")
    stats['prune'] += t.seconds

    with timed() as t:
        log("Building list of distinct prefixes")
        # Create list of unique prefixes in this batch
        exec("""
            CREATE TEMPORARY TABLE {tsp} ON COMMIT DROP
            AS SELECT DISTINCT first_word, word_ct FROM {ts}
        """)

        # Insert new prefixes
        exec("""
            INSERT INTO {sp} (first_word, word_ct)
            SELECT t.first_word, t.word_ct
            FROM
                {tsp} AS t
                LEFT JOIN {sp} AS sp ON sp.first_word=t.first_word AND sp.word_ct=t.word_ct
            WHERE sp.first_word IS NULL
        """)
    stats['prefixes'] += t.seconds

    with timed() as t:
        log("Updating existing systems.")
        exec("""
            UPDATE {s} AS s
            SET name_lower=t.name_lower, name=t.name, first_word=t.first_word, word_ct=t.word_ct, xz=t.xz, y=t.y
            FROM {ts} AS t
            WHERE s.eddb_id=t.eddb_id
        """)

        log("Inserting new systems.")
        exec("""
            INSERT INTO {s} (eddb_id, name_lower, name, first_word, word_ct, xz, y)
            SELECT t.eddb_id, t.name_lower, t.name, t.first_word, t.word_ct, t.xz, t.y
            FROM {ts} AS t
            LEFT JOIN {s} AS s ON s.eddb_id=t.eddb_id
            WHERE s.eddb_id IS NULL
        """)

    stats['systems'] += t.seconds

    with timed() as t:
        log('Computing prefix statistics')
        exec("""
            UPDATE {sp} SET ratio=t.ratio, cume_ratio=t.cume_ratio
            FROM (
                SELECT
                    t.first_word, t.word_ct, ct/(SUM(ct) OVER w) AS ratio,
                    (SUM(ct) OVER p)/(SUM(ct) OVER w) AS cume_ratio
                FROM (
                    SELECT sp.*, COUNT(s.eddb_id) AS ct
                    FROM
                        {sp} AS sp
                        LEFT JOIN {s} AS s USING (first_word, word_ct)
                    WHERE sp.first_word IN(SELECT first_word FROM {tsp})
                    GROUP BY sp.first_word, sp.word_ct
                    HAVING COUNT(*) > 0
                ) AS t
                WINDOW
                w AS (PARTITION BY t.first_word ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING),
                p AS (PARTITION BY t.first_word ORDER BY t.word_ct ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            ) AS t
            WHERE {sp}.first_word=t.first_word AND {sp}.word_ct=t.word_ct
        """)
    stats['stats'] += t.seconds
    with timed() as t:
        log("Analyzing tables")
        exec("ANALYZE {sp}")
        exec("ANALYZE {s}")
    stats['optimize'] += t.seconds

    log("Starsystem database update complete")
    # Update refresh time
    try:
        status = get_status(db)
        status.starsystem_refreshed = sql.func.clock_timestamp()
        db.add(status)
        db.commit()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        raise
    log("Starsystem database update committed")

    with timed() as t:
        log("Rebuilding bloom filter")
        refresh_bloom(bot)
    stats['bloom'] += t.seconds

    overall_timer.stop()
    stats['misc'] = overall_timer.seconds - sum(stats.values())
    stats['total'] = overall_timer.seconds
    bot.memory['ratbot']['stats']['starsystem_refresh'] = stats
    log("Starsystem refresh finished")
    return True


@with_session
def refresh_bloom(bot, db):
    """
    Refreshes the bloom filter.

    :param bot: Bot storing the bloom filter
    :param db: Database handle
    :return: New bloom filter.
    """
    # Get filter planning statistics
    count = db.query(sql.func.count(sql.distinct(StarsystemPrefix.first_word))).scalar() or 0
    bits, hashes = BloomFilter.suggest_size_and_hashes(rate=0.01, count=max(32, count), max_hashes=10)
    bloom = BloomFilter(bits, BloomFilter.extend_hashes(hashes))
    with timed() as t:
        bloom.update(x[0] for x in db.query(StarsystemPrefix.first_word).distinct())
    # print(
    #     "Recomputing bloom filter took {} seconds.  {}/{} bits, {} hashes, {} false positive chance"
    #     .format(end-start, bloom.setbits, bloom.bits, hashes, bloom.false_positive_chance())
    # )
    bot.memory['ratbot']['starsystem_bloom'] = bloom
    bot.memory['ratbot']['stats']['starsystem_bloom'] = {'entries': count, 'time': t.seconds}
    return bloom


def scan_for_systems(bot, line, min_ratio=0.05, min_length=6):
    """
    Scans for system names that might occur in the line of text.

    :param bot: Bot
    :param line: Line of text
    :param min_ratio: Minimum cumulative ratio to consider an acceptable match.
    :param min_length: Minimum length of the word matched on a single-word match.
    :return: Set of matched systems.

    min_ratio explained:

    There's one StarsystemPrefix for each distinct combination of (first word, word count).  Each prefix has a
    'ratio': the % of starsystems belonging to it as related the total number of starsystems owned by all other
    prefixes sharing the same first_word.  That is:
        count(systems with the same first word and word count) / count(systems with the same first word, any word count)

    Additionally, there's a 'cume_ratio' (Cumulative Ratio) that is: The sum of this prefix's ratio and all other
    related prefixes with a lower word count.

    min_ratio excludes prefixes with a cume_ratio below min_ratio.  The main reason for this is to exclude certain
    matches that might be made as a result of a typo -- e.g. matching a sector name rather than sector+coords because
    the coordinates were mistyped or the system in question isn't in EDSM yet.
    """
    # Split line into words.
    #
    # Rather than use a complicated regex (which we end up needing to filter anyways), we split on any combination of:
    # 0+ non-word characters, followed by 1+ spaces, followed by 0+ non-word characters.
    # This filters out grammar like periods at ends of sentences and commas between words, without filtering out things
    # like a hyphen in a system name (since there won't be a space in the right place.)
    words = list(filter(None, re.split(r'\W*\s+\W*', ' ' + line.lower() + ' ')))

    # Check for words that are in the bloom filter.  Make a note of their location in the word list.
    bloom = bot.memory['ratbot']['starsystem_bloom']
    candidates = {}
    for ix, word in enumerate(words):
        if word in candidates:
            candidates[word].append(ix)
        elif word in bloom:
            candidates[word] = [ix]

    # No candidates; bail.
    if not candidates:
        return set()

    # Still here, so find prefixes in the database
    db = get_session(bot)
    results = {}
    try:
        # Find matching prefixes
        for prefix in db.query(StarsystemPrefix).filter(
                StarsystemPrefix.first_word.in_(candidates.keys()),
                StarsystemPrefix.cume_ratio >= min_ratio,
                sql.or_(StarsystemPrefix.word_ct > 1, sql.func.length(StarsystemPrefix.first_word) >= min_length)
        ):
            # Look through matching words.
            for ix in candidates[prefix.first_word]:
                # Bail if there's not enough room for the rest of this prefix.
                # (e.g. last word of the line was "MCC", with no room for a possible "811")
                endix = ix + prefix.word_ct
                if endix > len(words):
                    break
                # Try to find the actual system.
                check = " ".join(words[ix:endix])
                system = db.query(Starsystem).filter(Starsystem.name_lower == check).first()
                if not system or (prefix.first_word in results and len(results[prefix.first_word]) > len(system.name)):
                    continue
                results[prefix.first_word] = system.name
        return set(results.values())
    finally:
        db.rollback()
