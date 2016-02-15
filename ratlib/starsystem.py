"""
Utilities for handling starsystem names and the like.

This is specifically named 'starsystem' rather than 'system' for reasons that should be obvious.
"""

from time import time
import itertools
import re
import operator
import os
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


@with_session
def refresh_database(bot, refresh=False, db=None):
    """
    Refreshes the database of starsystems.  Also rebuilds the bloom filter.
    :param bot: Bot instance
    :param refresh: True to force refresh
    :param db: Database handle
    """
    edsm_url = bot.config.ratbot.edsm_url or "http://edsm.net/api-v1/systems?coords=1"
    status = get_status(db)

    edsm_maxage = bot.config.ratbot.maxage or 60*12*12
    if not (refresh or not status.starsystem_refreshed or time() - status.starsystem_refreshed > edsm_maxage):
        # No refresh needed.
        return False

    data = requests.get(edsm_url).json()
    # with open('run/systems.json') as f:
    #     import json
    #     data = json.load(f)

    db.query(Starsystem).delete()  # Wipe all old data
    db.query(StarsystemPrefix).delete()  # Wipe all old data
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

    for chunk in chunkify(data, 5000):
        db.bulk_insert_mappings(Starsystem, [_format_system(s) for s in chunk])
        print(ct)
    del data
    db.connection().execute("ANALYZE " + Starsystem.__tablename__)

    # Pass 2: Calculate statistics.
    # 2A: Quick insert of prefixes for single-name systems
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
    for chunk in chunkify(itertools.groupby(_gen(), operator.itemgetter(0)), 100):
        pending = {}
        for (first_word, word_ct), group in chunk:
            ct += 1
            systems = []
            const_words = None
            for _, words, system in group:
                systems.append(system.id)
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
            db.add(prefix)
            pending[prefix] = systems
        print(ct)
        db.flush()
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

    # Update refresh time
    status = get_status(db)
    status.starsystem_refreshed = time()
    db.add(status)
    db.commit()
    refresh_bloom(bot)
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
    count = db.query(sql.func.count(sql.distinct(StarsystemPrefix.first_word))).scalar()
    bits, hashes = BloomFilter.suggest_size_and_hashes(rate=0.01, count=count, max_hashes=10)
    bloom = BloomFilter(bits, BloomFilter.extend_hashes(hashes))
    start = time()
    bloom.update(x[0] for x in db.query(StarsystemPrefix.first_word).distinct())
    end = time()
    print(
        "Recomputing bloom filter took {} seconds.  {}/{} bits, {} hashes, {} false positive chance"
        .format(end-start, bloom.setbits, bloom.bits, hashes, bloom.false_positive_chance())
    )
    bot.memory['ratbot']['starsystem_bloom'] = bloom
    return bloom

