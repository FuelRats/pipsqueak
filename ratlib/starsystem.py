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


def get_generation(bot=None, db=None):
    if db is None:
        db = get_session(bot)
    status = get_status(db)
    return status.starsystem_generation


def prune_database(bot=None, db=None):
    if db is None:
        db = get_session(bot)
    generation = get_generation(db=db)
    db.query(Starsystem).filter(Starsystem.generation != generation).delete()
    db.query(StarsystemPrefix).filter(StarsystemPrefix.generation != generation).delete()
    db.commit()
    db.close()
    return generation


@with_session
def refresh_database(bot, refresh=False, db=None):
    def _count(table):
        return (
            db.query(sql.func.count()).select_from(table).filter(table.generation == generation).scalar()
        )

    edsm_url = bot.config.ratbot.edsm_url or "http://edsm.net/api-v1/systems?coords=1"
    # kvp = bot.memory['ratbot']['sqldict']
    #
    # updated = kvp.get('starsystems_updated')
    # if updated is None:
    #     refresh = True
    # else:
    #     edsm_maxage = bot.config.ratbot.maxage
    #     if edsm_maxage is None:
    #         edsm_maxage = 60*12*12
    #     age = time() - int(updated)
    #     if age > edsm_maxage:
    #         refresh = True
    #
    # if not refresh:
    #     return

    bot.notice("[starsystems] Starting refresh")

    # data = requests.get(edsm_url).json()
    with open('run/systems.json') as f:
        import json
        data = json.load(f)

    bot.notice("[starsystems] ... beginning initial load")

    # Clean out old remnants and increment generation
    generation = prune_database(db=db) + 1

    # Pass 1: Load JSON data into stats table.
    systems = []
    ct = 0
    for chunk in chunkify(data, 5000):
        systems = []
        for system in chunk:
            ct += 1
            words = re.split(r'\s+', system['name'].strip())
            name = " ".join(words)
            systems.append({
                'generation': generation,
                'name_lower': name.lower(),
                'name': name,
                'x': system.get('x'), 'y': system.get('y'), 'z': system.get('z'),
                'word_ct': len(words)
            })
        print(ct)
        db.bulk_insert_mappings(Starsystem, systems)
        db.commit()
        print(' OK')

    db.connection().execute("ANALYZE " + Starsystem.__tablename__)
    db.commit()
    print("Added {} starsystems.".format(_count(Starsystem)))

    # Reclaim memory
    del systems
    del data

    # Pass 2: Calculate statistics.
    # 2A: Quick insert of prefixes for single-name systems
    db.connection().execute(
        sql.insert(StarsystemPrefix).from_select(
            (StarsystemPrefix.generation, StarsystemPrefix.first_word, StarsystemPrefix.word_ct),
            db.query(
                sql.column(str(generation)).label("generation"),
                Starsystem.name_lower,
                sql.column("1").label("word_ct")
            )
        )
    )
    ct = db.query(sql.func.count()).select_from(StarsystemPrefix).scalar()
    print("Fast-added {} single-word system prefixes.".format(_count(StarsystemPrefix)))
    db.commit()

    def _gen():
        for system in (
            db.query(Starsystem)
            .order_by(Starsystem.word_ct, Starsystem.name_lower)
            .filter(Starsystem.generation == generation, Starsystem.word_ct > 1)
        ):
            first_word, *words = system.name_lower.split(" ")
            yield (first_word, system.word_ct), words, system

    ct = 0
    for chunk in chunkify(itertools.groupby(_gen(), operator.itemgetter(0)), 50):
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
                generation=generation, first_word=first_word, word_ct=word_ct, const_words=" ".join(const_words)
            )
            db.add(prefix)
            pending[prefix] = systems
        print(ct)
        db.flush()
        for prefix, systems in pending.items():
            for chunk in chunkify(systems, 500):
                (
                    db.query(Starsystem).filter(Starsystem.id.in_(chunk))
                    .update({Starsystem.prefix_id: prefix.id}, synchronize_session=False)
                )
        db.commit()
        print(" OK")
    print("Analyzed {} system prefixes.".format(_count(StarsystemPrefix)))

    # Update generation
    status = get_status(db)
    status.starsystem_generation = generation
    db.add(status)
    db.commit()
    prune_database(db=db)
