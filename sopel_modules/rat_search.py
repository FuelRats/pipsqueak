#coding: utf8
"""
rat_search.py - Elite Dangerous System Search module.
Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

Copyright originally by Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl> (2015),
under the Eiffel Forum License, version 2

See LICENSE.md

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports
import json
import os
import datetime
import threading
import functools

#Sopel imports
from sopel.module import commands, interval, example, NOLIMIT, HALFOP, OP, rate
from sopel.tools import SopelMemory

from sqlalchemy import sql, orm
from sqlalchemy.orm.util import object_state

from ratlib import timeutil
import ratlib
import ratlib.sopel
from ratlib.db import with_session, Starsystem, StarsystemPrefix, Landmark, get_status
from ratlib.starsystem import refresh_database, scan_for_systems, ConcurrentOperationError
from ratlib.autocorrect import correct
import re
from ratlib.api.names import require_permission, Permissions
from ratlib.hastebin import post_to_hastebin
from ratlib.util import timed

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
@example('!search lave', '')
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
        return

    if len(system) > 100:
        # Postgres has a hard limit of 255, but this is long enough.
        bot.reply("System name is too long.")
        return

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
        return bot.say("Nearest matches for {system_name} are: {matches}".format(
            system_name=system_name,
            matches=", ".join('"{0.Starsystem.name}" [{0.distance}]'.format(row) for row in result)
        ))
    return bot.say("No similar results for {system_name}".format(system_name=system_name))


def refresh_time_stats(bot):
    """
    Returns formatted stats on the last refresh.
    """
    stats = bot.memory['ratbot']['stats'].get('starsystem_refresh')
    if not stats:
        return "No starsystem refresh stats are available."
    return (
        "Refresh took {total:.2f} seconds.  (Load: {load:.2f}, Prune: {prune:.2f}, Systems: {systems:.2f},"
        " Prefixes: {prefixes:.2f}, Stats: {stats:.2f}, Optimize: {optimize:.2f}, Bloom: {bloom:.2f}, Misc: {misc:.2f})"
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
                db.query(sql.func.count(Starsystem.name_lower))
                .join(StarsystemPrefix)
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
        bot.say(
            "{count} starsystems under {prefixes} unique prefixes."
            " {one_word} single word systems. {excluded} ({pct:.0%}) systems excluded from system name detection."
            .format(**stats)
        )

    if 'refresh' in options:
        bot.say(refresh_time_stats(bot))

    if 'bloom' in options:
        stats = bot.memory['ratbot']['stats'].get('starsystem_bloom')
        bloom = bot.memory['ratbot'].get('starsystem_bloom')

        if not stats or not bloom:
            bot.say("Bloom filter stats are unavailable.")
        else:
            bot.say(
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
        options = "" if not trigger.group(2) or trigger.group(2)[0] != '-' else trigger.group(2)[1:]
        force = 'f' in options and (access & OP)
        prune = not ('p' in options and (access & OP))


        try:
            refreshed = refresh_database(
                bot,
                force=force,
                prune=prune,
                callback=lambda: bot.say("Starting starsystem refresh...")
            )
            if refreshed:
                bot.say(refresh_time_stats(bot))
                return
            msg = "Not yet.  "
        except ConcurrentOperationError:
            bot.say("A starsystem refresh operation is already in progress.")
            return

    when = get_status(db).starsystem_refreshed
    if not when:
        msg += "The starsystem database appears to have never been initialized."
    else:
        when = when.astimezone(datetime.timezone.utc)
        msg += "The starsystem database was refreshed at {} ({}) or an update is still in progress. It is only allowed every {} seconds.".format(
            timeutil.format_timestamp(when), timeutil.format_timedelta(when), bot.config.ratbot.edsm_maxage or '<unknown>'
        )
    bot.say(msg)


@commands('scan')
def cmd_scan(bot, trigger):
    """
    Used for system name detection testing.
    """
    if not trigger.group(2):
        bot.reply("Usage: {} <line of text>".format(trigger.group(1)))

    line = trigger.group(2).strip()
    results = scan_for_systems(bot, line)
    bot.say("Scan results: {}".format(", ".join(results) if results else "no match found"))


@commands('plot')
@require_permission(Permissions.rat)
# @rate(60 * 30)
@with_session
def cmd_plot(bot, trigger, db=None):
    """
    Usage: !plot <sys1> to <sys2>
            This function has a limit of once per 30 minutes per person as it is a taxing calculation.
            Plots a route from sys1 to sys2 with waypoints every 1000 Lightyears. It only calculates these waypoints,
            so some waypoints MAY be unreachable, but it should be suitable for most of the Milky way, except when
            crossing outer limbs.
    """
    maxdistance = 990

    # if not trigger._is_privmsg:
    #     bot.say("This command is spammy, please use it in a private message.")
    #     return NOLIMIT
    locked = False
    try:
        locked = bot.memory['ratbot']['plots_available'].acquire(blocking=False)
        if not locked:
            bot.reply(
                "Sorry, but there are already {} plots running.  Please try again later."
                .format(bot.memory['ratbot']['maxplots'])
            )
            return NOLIMIT


        line = (trigger.group(2) or '').strip()
        if line.startswith('-b'):
            # Batched mode is no longer implemented, (all plots are batched) but discard it to not break parsing.
            line = line[2:].strip()
        names = list(x.strip() for x in line.split(' to '))
        if len(names) != 2:
            bot.reply('Usage: !plot <starting system> to <destination system>')
            return NOLIMIT

        systems = list(
            db.query(Starsystem).filter(Starsystem.name_lower == name.lower()).first()
            for name in names
        )
        for name, system in zip(names, systems):
            if system is None:
                bot.reply('Unable to plot; system "{}" is not in the database.'.format(name))
                return NOLIMIT
            if system.xz is None or system.y is None:
                bot.reply('Unable to plot; system "{}" has unknown coordinates.'.format(system.name))
                return NOLIMIT

        source, target = systems
        if source == target:
            bot.reply('Unable to plot from a system to itself.')
            return NOLIMIT

        distance = source.distance(target)
        if distance < maxdistance:
            bot.reply("Systems are less than {} LY apart".format(maxdistance))
            return NOLIMIT

        banner = (
            "Plotting waypoints from {source.name} ({source.x:.2f}, {source.y:.2f}, {source.z:.2f})"
            " to {target.name} ({target.x:.2f}, {target.y:.2f}, {target.z:.2f}) (Total distance: {ly:.2f} LY)"
            .format(source=source, target=target, ly=distance)
        )

        bot.reply(banner)

        def task():
            with timed() as t:
                db = ratlib.db.get_session(bot)
                stmt = sql.select([
                    sql.column('eddb_id'),
                    sql.column('distance'),
                    sql.column('remaining'),
                    sql.column('final'),
                ]).select_from(sql.func.find_route(source.eddb_id, target.eddb_id, maxdistance)).alias()
                query = (
                    db.query(Starsystem, stmt.c.distance, stmt.c.remaining, stmt.c.final)
                    .join(stmt, Starsystem.eddb_id == stmt.c.eddb_id)
                    .order_by(stmt.c.remaining.desc())
                )
                result = query.all()
                text = [banner, '']

                sysline_fmt = "{jump:5}: {sys.name:30}  ({sys.x:.2f}, {sys.y:.2f}, {sys.z:.2f})"
                travel_fmt = "       -> (jump {distance:.2f} LY; {remaining:.2f} LY remaining)"

                for jump, row in enumerate(result):
                    if not jump:
                        jump = "START"
                    else:
                        text.append(travel_fmt.format(distance=row.distance, remaining=row.remaining))
                        if row.final:
                            jump = "  END"
                    text.append(sysline_fmt.format(jump=jump, sys=row.Starsystem))
            success = result[-1].final
            elapsed = timeutil.format_timedelta(t.delta)
            text.append('')
            if success:
                text.append("Plot completed in {}.".format(elapsed))
            else:
                text.append("Could not complete plot.  Went {} jumps in {}.".format(len(result) - 1, elapsed))
            text = "\n".join(text) + "\n"
            url = post_to_hastebin(text, bot.config.ratbot.hastebin_url or "http://hastebin.com/") + ".txt"

            if success:
                return (
                    "Plot from {source.name} to {target.name} completed: {url}"
                    .format(source=source, target=target, url=url)
                )
            else:
                return (
                    "Plot from {source.name} to {target.name} failed, partial results at: {url}"
                    .format(source=source, target=target, url=url)
                )
        def task_done(future):
            try:
                try:
                    result = future.result()
                except Exception as ex:
                    result = str(ex)
                bot.reply(result)
            finally:
                bot.memory['ratbot']['plots_available'].release()

        try:
            locked = False
            future = bot.memory['ratbot']['executor'].submit(task)
            future.add_done_callback(task_done)
        except:
            locked = True
            raise

    finally:
        if locked:
            bot.memory['ratbot']['plots_available'].release()


@commands('landmark')
@require_permission(Permissions.rat)
@with_session
def cmd_landmark(bot, trigger, db=None):
    """
    Lists or modifies landmark starsystems.

    !landmark list - Lists all known landmarks in a PM.
    !landmark near <system> - Find the landmark closest to <system>
    !landmark add <system> - Adds the listed starsystem as a landmark system.  (Overseer Only)
    !landmark del <system> - Removes the listed starsystem from the landmark system lists.  (Overseer Only)
    !landmark refresh - Updates all landmarks to match their current listed EDDB coordinates.  (Overseer Only)
    """
    pm = functools.partial(bot.say, destination=trigger.nick)
    parts = re.split(r'\s+', trigger.group(2), maxsplit=1) if trigger.group(2) else None
    subcommand = parts.pop(0).lower() if parts else None
    system_name = parts.pop(0) if parts else None

    def lookup_system(name, model=Starsystem):
        return db.query(model).filter(model.name_lower == name.lower()).first()

    def get_system_or_none(name):
        if not system_name:
            bot.reply("A starsystem name must be specified")
            return None
        starsystem = lookup_system(system_name)
        if not starsystem:
            bot.reply("Starsystem '{}' is not in the database".format(system_name))
            return None
        if not starsystem.has_coordinates:
            bot.reply("Starsystem '{}' has unknown coordinates.".format(starsystem.name))
            return None
        return starsystem

    def subcommand_list(*unused_args, **unused_kwargs):
        if not trigger.is_privmsg:
            bot.reply("Messaging you the list of landmark systems.")

        ix = 0
        for ix, landmark in enumerate(db.query(Landmark).order_by(Landmark.name_lower), start=1):
            if landmark.xz is None or landmark.y is None:
                loc = "UNKNOWN LOCATION"
            else:
                loc = "({landmark.x:.2f}, {landmark.y:.2f}, {landmark.z:.2f})".format(landmark=landmark)

            pm("Landmark #{ix} - {landmark.name} @ {loc}".format(ix=ix, landmark=landmark, loc=loc))
        pm("{} landmark system(s) defined.".format(ix))

    def subcommand_near(*unused_args, **unused_kwargs):
        starsystem = get_system_or_none(system_name)
        if not starsystem:
            return
        landmark, distance = starsystem.nearest_landmark(db, True)
        if not landmark:
            bot.reply("Could not find a nearby landmark.  (Perhaps none are defined?)")
            return
        if not distance and starsystem.name_lower == landmark.name_lower:
            bot.reply("{} is a landmark!".format(starsystem.name))
            return
        bot.reply(
            "{starsystem.name} is {distance:.2f} LY from {landmark.name}"
            .format(starsystem=starsystem, landmark=landmark, distance=distance)
        )

    # @require_overseer(None)
    @require_permission(Permissions.overseer)
    def subcommand_add(*unused_args, **unused_kwargs):
        starsystem = get_system_or_none(system_name)
        if not starsystem:
            return
        landmark = Landmark(name=starsystem.name, name_lower=starsystem.name_lower, xz=starsystem.xz, y=starsystem.y)
        landmark = db.merge(landmark)
        persistent = object_state(landmark).persistent
        db.commit()

        if persistent:
            bot.reply("System '{}' was already a landmark.  Updated to current coordinates.".format(starsystem.name))
        else:
            bot.reply("Added system '{}' as a landmark.".format(starsystem.name))

    # @require_overseer(None)
    @require_permission(Permissions.overseer, message=None)
    def subcommand_del(*unused_args, **unused_kwargs):
        landmark = lookup_system(system_name, Landmark)
        if landmark is None:
            bot.reply("No such landmark '{}'".format(system_name))
            return
        db.delete(landmark)
        db.commit()
        bot.reply("Removed system '{}' from the list of landmarks.".format(landmark.name))
        pass

    @require_permission(Permissions.overseer, message=None)
    def subcommand_refresh(*unused_args, **unused_kwargs):
        ct = (
            db.query(Landmark)
            .filter(Landmark.name_lower == Starsystem.name_lower)
            .update({
                Landmark.name: Starsystem.name,
                Landmark.xz: Starsystem.xz,
                Landmark.y: Starsystem.y
            }, synchronize_session=False)
        )
        bot.reply("Synchronized {} landmark system(s).".format(ct))

    subcommands = {
        'list': subcommand_list,
        'near': subcommand_near,
        'add': subcommand_add,
        'del': subcommand_del,
        'refresh': subcommand_refresh,
    }

    if not subcommand:
        bot.reply("Missing subcommand.  See !help landmark")
    elif subcommand not in subcommands:
        bot.reply(
            "Unknown subcommand.  See !help landmark (or perhaps you meant !landmark near {})"
            .format(trigger.group(2))
        )
    else:
        return subcommands[subcommand](bot, trigger)
