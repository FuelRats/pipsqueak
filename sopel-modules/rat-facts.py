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
import os.path
import re
import glob
from sopel.module import commands, NOLIMIT, HALFOP, OP, rule
from sopel.config.types import StaticSection, ValidatedAttribute
from sopel.tools import SopelMemory, Identifier


class RatfactsSection(StaticSection):
    filename = ValidatedAttribute('filename', str, default='')


def configure(config):
    config.define_section('ratfacts', RatfactsSection)
    config.ratfacts.configure_setting('filename',
        "The name of the json file containing the fact list, or a directory of .json files that will all be examined.")


def getfacts(path, recurse=True):
    """
    Loads facts from the specified filename.

    If filename is a directory and recurse is True, loads all json files in that directory.
    """
    facts = {}
    if recurse and os.path.isdir(path):
        for filename in glob.glob(os.path.join(path, "*.json")):
            result = getfacts(filename, recurse=False)
            if result:
                facts.update(result)
        return facts

    with open(path) as f:
        facts = json.load(f)

    if not isinstance(facts, dict):
        # Something horribly wrong with the json
        raise RuntimeError("{}: json structure is not a dict.".format(path))
    return facts


def reload(bot):
    facts = getfacts(bot.config.ratfacts.filename)
    if 'ratbot' not in bot.memory:
        bot.memory['ratbot'] = SopelMemory()
    bot.memory['ratbot']['facts'] = facts


def setup(bot):
    reload(bot)


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
    """Lists the facts in the .JSON file, or reloads the facts database"""
    command = trigger.group(3)
    if command and command.strip().lower() == 'reload':
        nick = Identifier(trigger.nick)
        for channel in bot.privileges.values():
            access = channel.get(nick, 0)
            if access & (HALFOP|OP):
                reload(bot)
                return bot.reply("Facts reloaded.  {} known fact(s).".format(len(bot.memory['ratbot']['facts'])))

        return bot.reply("Not authorized.")

    facts = bot.memory['ratbot']['facts']
    if not facts:
        return bot.reply("Like Jon Snow, I know nothing.  (Or there's a problem with the fact list.)")
    return bot.reply("{} known fact(s): {}".format(len(facts), ", ".join(sorted(facts.keys()))))
