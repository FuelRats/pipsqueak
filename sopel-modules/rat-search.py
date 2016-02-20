#coding: utf8
"""
rat-search.py - Elite Dangerous System Search module.
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports
import json
import os
import datetime

#Sopel imports
from sopel.module import commands, interval, example, NOLIMIT, HALFOP, OP
from sopel.tools import SopelMemory

from sqlalchemy import sql, orm

import ratlib
import ratlib.sopel
from ratlib import friendly_timedelta
from ratlib.db import with_session, Starsystem, StarsystemPrefix, get_status
from ratlib.starsystem import refresh_database, scan_for_systems, ConcurrentOperationError
from ratlib.autocorrect import correct
import re


def configure(config):
    ratlib.sopel.configure(config)


def setup(bot):
    ratlib.sopel.setup(bot)

    bot.memory['ratbot']['searches'] = SopelMemory()
    bot.memory['ratbot']['systemFile'] = ratlib.sopel.makepath(bot.config.ratbot.workdir, 'systems.json')

    frequency = int(bot.config.ratbot.edsm_autorefresh or 0)
    if frequency > 0:
        interval(frequency)(task_sysrefresh)


@commands('search')
@example('!search lave','')
@with_session
def search(bot, trigger, db=None):
    """
    Searches for system name matches.
    """

    system = trigger.group(2)
    if system:
        system = re.sub(r'\s\s+', ' ', system.strip())
    if not system:
        bot.reply("Usage: {} <name of system>".format(trigger.group(1)))

    if len(system) > 100:
        # Postgres has a hard limit of 255, but this is long enough.
        bot.reply("System name is too long.")

    # Try autocorrection first.
    result = correct(system)
    if result.fixed:
        system = result.output
    system_name = '"{}"'.format(system)
    if result.fixed:
        system_name += " (autocorrected)"

    system = system.lower()

    # Levenshtein expression
    max_distance = 10
    max_results = 4
    expr = sql.func.levenshtein_less_equal(Starsystem.name_lower, system, max_distance)

    # Query
    result = (
        db.query(Starsystem, expr.label("distance"))
        .filter(expr <= max_distance)
        .order_by(expr.asc())
    )[:max_results]


    if result:
        return bot.reply("Nearest matches for {system_name} are: {matches}".format(
            system_name=system_name,
            matches=", ".join('"{0.Starsystem.name}" [{0.distance}]'.format(row) for row in result)
        ))
    return bot.reply("No similar results for {system_name}".format(system_name=system_name))


def refresh_time_stats(bot):
    """
    Returns formatted stats on the last refresh.
    """
    stats = bot.memory['ratbot']['stats'].get('starsystem_refresh')
    if not stats:
        return "No starsystem refresh stats are available."
    return (
        "Refresh took {all:.2f} seconds.  (Fetch: {fetch:.2f}; Load: {load:.2f}; Stats: {stats:.2f}; Misc: {misc:.2f})"
        .format(**stats)
    )


@commands('sysstats')
@with_session
def cmd_sysstats(bot, trigger, db=None):
    """Diagnostics and statistics."""
    def ct(table, *filters):
        result = db.query(sql.func.count()).select_from(table)
        if filters:
            result = result.filter(*filters)
        return result.scalar()

    all_options = {'count', 'bloom', 'refresh', 'all'}
    options = (set((trigger.group(2) or '').lower().split(' ')) & all_options) or {'count'}
    if 'all' in options:
        options = all_options

    if 'count' in options:
        stats = {
            'excluded': (
                db.query(sql.func.count(Starsystem.id))
                .join(StarsystemPrefix, StarsystemPrefix.id == Starsystem.prefix_id)
                .filter(sql.or_(
                    StarsystemPrefix.cume_ratio < 0.05,
                    sql.and_(StarsystemPrefix.word_ct <= 1, sql.func.length(StarsystemPrefix.first_word) < 6)
                ))
                .scalar()
            ),
            'count': ct(Starsystem),
            'prefixes': ct(StarsystemPrefix),
            'one_word': ct(StarsystemPrefix, StarsystemPrefix.word_ct == 1)
        }
        stats['pct'] = 0 if not stats['count'] else stats['excluded'] / stats['count']

        num_systems = ct(Starsystem)
        bot.reply(
            "{count} starsystems under {prefixes} unique prefixes."
            " {one_word} single word systems. {excluded} ({pct:.0%}) systems excluded from system name detection."
            .format(**stats)
        )

    if 'refresh' in options:
        bot.reply(refresh_time_stats(bot))

    if 'bloom' in options:
        stats = bot.memory['ratbot']['stats'].get('starsystem_bloom')
        bloom = bot.memory['ratbot'].get('starsystem_bloom')

        if not stats or not bloom:
            bot.reply("Bloom filter stats are unavailable.")
        else:
            bot.reply(
                "Bloom filter generated in {time:.2f} seconds. k={k}, m={m}, n={entries}, {numset} bits set,"
                " {pct:.2%} false positive chance."
                .format(k=bloom.k, m=bloom.m, pct=bloom.false_positive_chance(), numset=bloom.setbits, **stats)
            )

def task_sysrefresh(bot):
    try:
        refresh_database(bot, background=True, callback=lambda: print("Starting background EDSM refresh."))
    except ConcurrentOperationError:
        pass


@commands('sysrefresh')
@with_session
def cmd_sysrefresh(bot, trigger, db=None):
    """
    Refreshes the starsystem database if you have halfop or better.  Reports the last refresh time otherwise.

    -f: Force refresh even if data is stale.  Requires op.
    """
    access = ratlib.sopel.best_channel_mode(bot, trigger.nick)
    privileged = access & (HALFOP | OP)
    msg = ""

    if privileged:
        try:
            refreshed = refresh_database(
                bot,
                force=access & OP and trigger.group(2) and trigger.group(2) == '-f',
                callback=lambda: bot.reply("Starting starsystem refresh...")
            )
            if refreshed:
                bot.reply(refresh_time_stats(bot))
                return
            msg = "Not yet.  "
        except ConcurrentOperationError:
            bot.reply("A starsystem refresh operation is already in progress.")
            return

    when = get_status(db).starsystem_refreshed
    if not when:
        msg += "The starsystem database appears to have never been initialized."
    else:
        when = when.astimezone(datetime.timezone.utc)
        msg += "The starsystem database was refreshed at {} ({})".format(
            ratlib.format_timestamp(when), ratlib.format_timedelta(when)
        )
    bot.reply(msg)

@commands('scan')
def cmd_scan(bot, trigger):
    """
    Used for system name detection testing.
    """
    if not trigger.group(2):
        bot.reply("Usage: {} <line of text>".format(trigger.group(1)))

    line = trigger.group(2).strip()
    results = scan_for_systems(bot, line)
    bot.reply("Scan results: {"
              "}".format(", ".join(results) if results else "no match found"))
