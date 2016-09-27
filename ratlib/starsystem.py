"""
Utilities for handling starsystem names and the like.

This is specifically named 'starsystem' rather than 'system' for reasons that should be obvious.
"""

from time import time
import datetime
import itertools
import re
import operator
import threading


try:
    import collections.abc as collections_abc
except ImportError:
    import collections as collections_abc

import requests
import sqlalchemy as sa
from sqlalchemy import sql, orm, schema
from ratlib.db import get_status, get_session, with_session, Starsystem, StarsystemPrefix
from ratlib.bloom import BloomFilter


def chunkify(it, size):
    if not isinstance(it, collections_abc.Iterator):
        it = iter(it)
    go = True
    def _gen():
        nonlocal go
        try:
            remaining = size
            while remaining:
                remaining -= 1
                yield next(it)
        except StopIteration:
            go = False
            raise
    while go:
        yield _gen()


class ConcurrentOperationError(RuntimeError):
    pass


def refresh_database(bot, force=False, limit_one=True, callback=None, background=False, _lock=threading.Lock()):
    """
    Refreshes the database of starsystems.  Also rebuilds the bloom filter.
    :param bot: Bot instance
    :param force: True to force refresh regardless of age.
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
        result = _refresh_database(bot, force, callback, background)
        if result and background and release:
            result.add_done_callback(lambda *a, **kw: _lock.release())
            release = False
        return result
    finally:
        if release:
            _lock.release()


@with_session
def _refresh_database(bot, force=False, callback=None, background=False, db=None):
    """
    Actual implementation of refresh_database.

    Refreshes the database of starsystems.  Also rebuilds the bloom filter.
    :param bot: Bot instance
    :param force: True to force refresh
    :param callback: Optional function that is called as soon as the system determines a refresh is needed.
    :param background: If True and a refresh is needed, it is submitted as a background task rather than running
        immediately.
    :param db: Database handle
    """
    start = time()
    print('Starting refresh at '+str(start))
    edsm_url = bot.config.ratbot.edsm_url or "http://edsm.net/api-v1/systems?coords=1"
    chunked = bot.config.ratbot.chunked_systems == 'True'
    status = get_status(db)
    edsm_maxage = float(bot.config.ratbot.edsm_maxage) or 60*12*12
    if not (
        force or
        not status.starsystem_refreshed or
        (datetime.datetime.now(tz=datetime.timezone.utc) - status.starsystem_refreshed).total_seconds() > edsm_maxage
    ):
        # No refresh needed.
        print('not force and no refresh needed')
        return False

    if callback:
        callback()

    if background:
        print('Sending edsm refresh to background!')
        return bot.memory['ratbot']['executor'].submit(
            _refresh_database, bot, force=True, callback=None, background=False
        )

    fetch_start = time()
    print('Started Database refresh......')
    req = requests.get(edsm_url)
    if req.status_code != 200:
        print('ERROR When calling EDSM - Status code was '+str(req.status_code))
        return
    if chunked:
        data = []
        response = req.json()
        for part in response.keys():
            print('requesting from: '+edsm_url[0:edsm_url.rfind('/')+1] + str(part))
            partreq = requests.get(edsm_url[0:edsm_url.rfind('/')+1] + str(part))
            partdata = partreq.json()
            data.extend(partdata)
    else:
        data = req.json()
    print('Fetch done, Code was 200, data loaded into var!')
    fetch_end = time()
    # with open('run/systems.json') as f:
    #     import json
    #     data = json.load(f)

    print('Wiping old data')
    db.query(Starsystem).delete()  # Wipe all old data
    db.query(StarsystemPrefix).delete()  # Wipe all old data
    print('done wiping, moving along...')
    # Pass 1: Load JSON data into stats table.
    systems = []
    ct = 0

    def _format_system(s):
        nonlocal ct
        ct += 1
        name, word_ct = re.subn(r'\s+', ' ', s['name'].strip())
        word_ct += 1
        return {
            'name_lower': name.lower(),
            'name': name,
            'x': s.get('x'), 'y': s.get('y'), 'z': s.get('z'),
            'word_ct': word_ct
        }

    print('loading data into db....')
    load_start = time()
    for chunk in chunkify(data, 5000):
        db.bulk_insert_mappings(Starsystem, [_format_system(s) for s in chunk])
    print('Done with chunkified stuff, deleting data var to free up mem. Analyzing stuff.')
    del data
    db.connection().execute("ANALYZE " + Starsystem.__tablename__)
    print('Done loading!')
    load_end = time()

    stats_start = time()
    # Pass 2: Calculate statistics.
    # 2A: Quick insert of prefixes for single-name systems
    print('Executing against Database...')
    db.connection().execute(
        sql.insert(StarsystemPrefix).from_select(
            (StarsystemPrefix.first_word, StarsystemPrefix.word_ct),
            db.query(Starsystem.name_lower, Starsystem.word_ct).filter(Starsystem.word_ct == 1).distinct()
        )
    )
    def _gen():
        for s in (
            db.query(Starsystem)
            .order_by(Starsystem.word_ct, Starsystem.name_lower)
            .filter(Starsystem.word_ct > 1)
        ):
            first_word, *words = s.name_lower.split(" ")
            yield (first_word, s.word_ct), words, s

    ct = 0
    print('Adding Prefixes to db...')
    for chunk in chunkify(itertools.groupby(_gen(), operator.itemgetter(0)), 100):
        for (first_word, word_ct), group in chunk:
            ct += 1
            const_words = None
            for _, words, system in group:
                if const_words is None:
                    const_words = words.copy()
                else:
                    for ix, (common, word) in enumerate(zip(const_words, words)):
                        if const_words[ix] != words[ix]:
                            const_words = const_words[:ix]
                            break
            prefix = StarsystemPrefix(
                first_word=first_word, word_ct=word_ct, const_words=" ".join(const_words)
            )
            # print('prefix: '+str(prefix))
            db.add(prefix)
        # print(ct)
        # print('db.flush for ct '+str(ct))
        db.flush()
    print('Prefixes added and database flushed. Executing more stuff against database...')
    db.connection().execute(
        sql.update(
            Starsystem, values={
                Starsystem.prefix_id: db.query(StarsystemPrefix.id).filter(
                    StarsystemPrefix.first_word == sql.func.split_part(Starsystem.name_lower, ' ', 1),
                    StarsystemPrefix.word_ct == Starsystem.word_ct
                ).as_scalar()
            }
        )
    )
    exestring = """
        UPDATE {sp} SET ratio=t.ratio, cume_ratio=t.cume_ratio
        FROM (
            SELECT t.id, ct/SUM(ct) OVER w AS ratio, SUM(ct) OVER p/SUM(ct) OVER w AS cume_ratio
            FROM (
                SELECT sp.*, COUNT(*) AS ct
                FROM
                    {sp} AS sp
                    INNER JOIN {s} AS s ON s.prefix_id=sp.id
                GROUP BY sp.id
                HAVING COUNT(*) > 0
            ) AS t
            WINDOW
            w AS (PARTITION BY t.first_word ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING),
            p AS (PARTITION BY t.first_word ORDER BY t.word_ct ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        ) AS t
        WHERE t.id=starsystem_prefix.id
        """.format(sp=StarsystemPrefix.__tablename__, s=Starsystem.__tablename__)
    print('Executing yet more stuff...')

    db.connection().execute(
        exestring
    )
    stats_end = time()

    # Update refresh time
    status = get_status(db)
    status.starsystem_refreshed = sql.func.clock_timestamp()
    db.add(status)
    db.commit()
    print('calc bloom...')
    bloom_start = time()
    refresh_bloom(bot)
    bloom_end = time()
    end = time()
    print('Done with all!, collecting stats.')
    stats = {
        'stats': stats_end - stats_start, 'load': load_end - load_start, 'fetch': fetch_end - fetch_start,
        'bloom': bloom_end - bloom_start
    }
    stats['misc'] = (end - start) - sum(stats.values())
    stats['all'] = end - start
    bot.memory['ratbot']['stats']['starsystem_refresh'] = stats
    print('Database Refresh Done.')
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
    start = time()
    bloom.update(x[0] for x in db.query(StarsystemPrefix.first_word).distinct())
    end = time()
    # print(
    #     "Recomputing bloom filter took {} seconds.  {}/{} bits, {} hashes, {} false positive chance"
    #     .format(end-start, bloom.setbits, bloom.bits, hashes, bloom.false_positive_chance())
    # )
    bot.memory['ratbot']['starsystem_bloom'] = bloom
    bot.memory['ratbot']['stats']['starsystem_bloom'] = {'entries': count, 'time': end - start}
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
