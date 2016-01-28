#coding: utf8
"""
rat-facts.py - Fact reciting module
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Licensed under the Eiffel Forum License 2.

These modules are built on top of the Sopel system.
http://sopel.chat/
"""

import json
import os
import re
from sopel.module import commands, NOLIMIT, rule
from sopel.config.types import StaticSection, ValidatedAttribute
from sopel.tools import SopelMemory


class RatfactsSection(StaticSection):
    filename = ValidatedAttribute('filename', str, default='')


def configure(config):
    config.define_section('ratfacts', RatfactsSection)
    config.ratfacts.configure_setting('filename',
        "The name of the json file containing the fact list.")


def setup(bot):
    with open(bot.config.ratfacts.filename) as f:
        facts = json.load(f)

    if not isinstance(facts, dict):
        # Something horribly wrong with the json
        raise RuntimeError("expects rat-facts json to be a dict")

    if 'ratbot' not in bot.memory:
        bot.memory['ratbot'] = SopelMemory()
    bot.memory['ratbot']['facts'] = facts


@commands(r'[^\s]+')
def reciteFact(bot, trigger):
    """Recite facts"""
    facts = bot.memory['ratbot']['facts']
    fact = trigger.group(1).lower()
    if fact not in facts:
        # Unknown fact
        return NOLIMIT

    rats = trigger.group(2)
    if rats:
        # Reorganize the rat list for consistent & proper separation
        # Split whitespace, comma, colon and semicolon (all common IRC multinick separators) then rejoin with commas
        rats = ", ".join(filter(None, re.split(r"[,\s+]", rats))) or None

    # reply_to automatically picks the sender's name if rats is None, no additional logic needed
    return bot.reply(facts[fact], reply_to=rats)


@commands('fact', 'facts')
def listFacts(bot, trigger):
    """Lists the facts in the .JSON file"""
    facts = bot.memory['ratbot']['facts']
    if not facts:
        return bot.reply("Like Jon Snow, I know nothing.  (Or there's a problem with the fact list.)")
    return bot.reply('Known facts: ' + ', '.join(sorted(facts.keys())))
