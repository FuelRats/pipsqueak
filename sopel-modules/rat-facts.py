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
from sopel.module import commands, NOLIMIT, rule
from sopel.config.types import StaticSection, ValidatedAttribute

class RatfactsSection(StaticSection):
    filename = ValidatedAttribute('filename', str, default='')

def configure(config):
    config.define_section('ratfacts', RatfactsSection)
    config.ratfacts.configure_setting('filename',
        "The name of the json file containing the fact list.")

@rule('.*')
def reciteFact(bot, trigger):
    msgParts = trigger.group().split(' ')
    cmd = msgParts[0]
    if cmd.startswith('!'): #TODO use bot.config's command prefix
        # Remove the !
        cmd = cmd[1:]
    else:
        # We don't care about this message.
        return NOLIMIT

    try:
        with open(bot.config.ratfacts.filename) as f:
            facts = json.load(f)
    except IOError:
        # We couldn't open facts.json, so act as if you're disabled.
        return NOLIMIT

    if cmd in facts:
        if len(msgParts) > 1:
            # This command was directed at somebody.
            return bot.say('%s: %s' % (msgParts[1], facts[cmd.lower()]))
        else:
            return bot.reply(facts[cmd.lower()])
    else:
        # Not one of our commands.
        return NOLIMIT

@commands('fact', 'facts')
def listFacts(bot, trigger):
    """Lists the facts in the .JSON file"""
    try:
        with open(bot.config.ratfacts.filename) as f:
            facts = json.load(f)
    except IOError:
        # We couldn't open facts.json...
        return bot.reply('There appears to be a problem with the fact list.')
    return bot.reply('Known facts: '+', '.join(facts.keys()))

