#coding: utf8
"""
rat-board.py - Fuel Rats Cases module.
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports
import json
import os

#Sopel Imports
from sopel.module import commands
from sopel.tools import SopelMemory

import ratlib.sopel

def configure(config):
    ratlib.sopel.configure(config)

def setup(bot):
    ratlib.sopel.setup(bot)

    bot.memory['ratbot']['drilllist'] = ratlib.sopel.makepath(bot.config.ratbot.workdir, 'drills.json')

@commands('drill')
def listDrills(bot, trigger):
    """Lists all current rats waiting for a drill, and their drill type."""

    #Argument parsing
    if trigger.group(3) is not None:
        arg = trigger.group(3).lower()
    else:
        arg = ''

    if arg == '-r':
        patchdrills = False
        ratdrills = True
    elif arg in ('-p', '-d'):
        patchdrills = True
        ratdrills = False
    else:
        patchdrills = True
        ratdrills = True

    # Load the list
    try:
        with open(bot.memory['ratbot']['drilllist']) as f:
            ls = json.load(f)
    except IOError as e:
        return bot.say('I can\'t seem to open the list.')

    # Parse the list
    pdrill = set()
    rdrill = set()
    for name, types in ls.items():
        if types['patchdrill']:
            pdrill.add(name)
        if types['ratdrill']:
            rdrill.add(name)

    # Print the list
    msg = ''
    if ratdrills and len(rdrill) > 0:
        msg += 'Ratting drills: '+', '.join(rdrill)
        if patchdrills and len(pdrill) > 0:
            msg += '. '

    if patchdrills and len(pdrill) > 0:
        msg += 'Dispatch drills: '+', '.join(pdrill)

    if len(msg) == 0:
        return bot.reply('That list is empty.')
    else:
        return bot.reply(msg)

@commands('drilladd')
def addDrill(bot, trigger):
    """Adds a rat to the list of awaiting drills.
    Arguments:
    -r = [r]atting drill only
    -d / -p = [d]is[p]atch drill only
    -b = [b]oth types of drills."""

    #Argument parsing
    if trigger.group(3) is None:
        return bot.reply('Missing 2 arguments.')

    if trigger.group(4) is None:
        return bot.reply('Missing 1 argument.')

    arg = trigger.group(3).lower()

    if arg == '-r':
        pdrill = False
        rdrill = True
    elif arg in ('-p', '-d'):
        pdrill = True
        rdrill = False
    elif arg == '-b':
        pdrill = True
        rdrill = True
    else:
        return bot.reply('invalid drill type, use -r, -d, -p or -b.')

    # Prepare new rat
    drill = {trigger.group(4): {'patchdrill':pdrill,'ratdrill':rdrill}}

    # Fetch list
    try:
        with open(bot.memory['ratbot']['drilllist']) as f:
            ls = json.load(f)
    except IOError:
        # File doesn't exist.
        ls = dict()

    # Add rat
    ls.update(drill)

    with open(bot.memory['ratbot']['drilllist'], 'w') as f:
        json.dump(ls, f)

    return bot.reply('CMDR %s added to drill list.' % (trigger.group(4),))


@commands('drilldel', 'drillrem')
def removeDrill(bot, trigger):
    """Removes a rat from the list of awaiting drills.
    NOTE: to only remove the rat from 1 type, use !drilladd instead"""

    #Argument parsing
    if trigger.group(3) is None:
        return bot.reply('I need a rat to remove...')
    else:
        CMDR = trigger.group(3)

    # Load list
    with open(bot.memory['ratbot']['drilllist']) as f:
        ls = json.load(f)

    # Check if in the list
    if CMDR not in ls:
        return bot.reply('CMDR %s not in the drill list.' % (CMDR,))


    # Remove from and upload list.
    del ls[CMDR]
    with open(bot.memory['ratbot']['drilllist'], 'w') as f:
        json.dump(ls, f)

    return bot.reply('CMDR %s removed from the list.' % (CMDR,))

