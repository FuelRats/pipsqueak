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
from time import time

#Fuzzywuzzy import
from fuzzywuzzy import fuzz

#Sopel imports
from sopel import web
from sopel.formatting import bold
from sopel.module import commands, example, NOLIMIT
from sopel.tools import SopelMemory

from sqlalchemy import sql, orm

import ratlib.sopel
from ratlib.db import with_session, Starsystem, StarsystemPrefix
from ratlib.starsystem import refresh_database
from ratlib.autocorrect import correct
import re

def configure(config):
    ratlib.sopel.configure(config)

def setup(bot):
    ratlib.sopel.setup(bot)

    bot.memory['ratbot']['searches'] = SopelMemory()
    bot.memory['ratbot']['systemFile'] = ratlib.sopel.makepath(bot.config.ratbot.workdir, 'systems.json')


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


@commands('sysstats')
@with_session
def cmd_sysstats(bot, trigger, db=None):
    ct = lambda t: db.query(sql.func.count()).select_from(t)
    bot.reply(
        "{num_systems} starsystems under {num_prefixes} unique prefixes."
        "  {one_word} single word systems.  {mixed} mixed-length prefixes."
        .format(
            num_systems=ct(Starsystem).scalar(),
            num_prefixes=ct(StarsystemPrefix).scalar(),
            one_word=ct(StarsystemPrefix).filter(StarsystemPrefix.word_ct == 1).scalar(),
            mixed='unknown'


        )
    )

@commands('sysrefresh')
def cmd_sysrefresh(bot, trigger, db=None):
    result = refresh_database(bot, trigger.group(2) and trigger.group(2) == '-f')
    if result:
        bot.reply("System database refreshed.")
    else:
        bot.reply("System is already up to date.")

