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

import ratlib.sopel
from ratlib.db import with_session, Starsystem, StarsystemPrefix
from ratlib.starsystem import refresh_database, get_generation
from sqlalchemy import sql, orm

def configure(config):
    ratlib.sopel.configure(config)

def setup(bot):
    ratlib.sopel.setup(bot)

    bot.memory['ratbot']['searches'] = SopelMemory()
    bot.memory['ratbot']['systemFile'] = ratlib.sopel.makepath(bot.config.ratbot.workdir, 'systems.json')

def findSystems(systemfile, refresh, system):
    """ EDSM interfacing and system list fuzzy searches. """
    # Refresh the systems list
    if refresh:
        # Determine list age.
        try:
            age = time() - os.path.getmtime(systemfile)
        except:
            # 404 - File not Found.. probably.
            age = 99999 # So make it too old for us to care.

        if age < 12*3600: #12 hours
            refreshResult = (False, 'List too young.')
        else:
            # Old enough, contact EDSM
            try:
                query_url = "http://edsm.net/api-v1/systems?coords=1"
                answer = json.loads(web.get(query_url, timeout=300))
                # All good, apply new list.
                try:
                    with open(systemfile, 'w') as f:
                        json.dump(answer, f)
                    refreshResult = (True, '')
                except IOError as e:
                    refreshResult = (False, 'File error.'+e)
            except:
                refreshResult = (False, 'API error.')
    else:
        refreshResult = (False, 'refresh not requested.')

    #Execute search
    name = system.lower()
    l = len(system)
    best = [None, None, None]
    # Load the system list.
    try:
        with open(systemfile) as f:
            candidates = json.load(f)
    except IOError as e:
        if not refreshResult[0]:
            return ('I can\'t read the systems list, try again with -r.',
                ), refreshResult
        else:
            return ('Something went wrong with the systems list, please try again.',
                ), refreshresult
    for candidate in candidates:
        #Grab some info on this candidate
        cname = candidate['name'].lower()
        cl = len(cname)

        # How similar?
        candidate['ratio'] = fuzz.ratio(name, cname)

        # Put it in the top3, if applicable.
        if best[0] is None or candidate['ratio'] > best[0]['ratio']:
            best[2] = best[1]
            best[1] = best[0]
            best[0] = candidate
        elif best[1] is None or candidate['ratio'] > best[1]['ratio']:
            best[2] = best[1]
            best[1] = candidate
        elif best[2] is None or candidate['ratio'] > best[2]['ratio']:
            best[2] = candidate

    searchResults = ['Fuzzy searching \'%s\' for against system list, full matching:' % (system, ), None, None, None]
    resultTemplate = 'Found system %s (Matching %s percent.) %s'
    for i in range(3):
        try:
            location = 'at [%s:%s:%s].' % (int(best[i]['coords']['x']),
                int(best[i]['coords']['y']), int(best[i]['coords']['z']))
        except KeyError as e:
            location = ', location unknown.'
        searchResults[i+1] = resultTemplate % (bold(best[i]['name']),
                best[i]['ratio'], location)

    # Return results.
    return searchResults, refreshResult

@commands('search')
@example('!search lave','')
def search(bot, trigger):
    """
    Searches for system name matches.
    -r to refresh the local System List (12 hour cooldown)
    """
    # Argument parsing
    if trigger.group(3) == '-r':
        search = trigger.group(2)[3:]
        refresh = True
    else:
        search = trigger.group(2)
        refresh = False

    # Empty search
    if search == None or len(search) == 0:
        # Returning NOLIMIT makes the rate-limiter ignore this command.
        return NOLIMIT

    # Search cooldown.
    if search.lower() in bot.memory['ratbot']['searches']:
        if time() - bot.memory['ratbot']['searches'][search.lower()] < 1800:
            return bot.say('I''m sorry %s, I\'m afraid I can\'t let you search there again so soon.' % (trigger.nick,))
    bot.memory['ratbot']['searches'][search.lower()] = time()

    #Do the search
    searchResults, refreshResult = findSystems(
        bot.memory['ratbot']['systemFile'], refresh, search)

    # Refresh results
    if refresh:
        if refreshResult[0]:
            bot.reply('System list updated successfully.')
        else:
            bot.reply('System list '+bold('not')+' updated: '+refreshResult[1])

    # Search results
    for res in searchResults:
        if res != None:
            bot.say(res.replace(' percent.', '%'))

@commands('sysstats')
@with_session
def cmd_sysstats(bot, trigger, db=None):
    generation = get_generation(db=db)
    ct = lambda t: db.query(sql.func.count()).select_from(t).filter(t.generation == generation)
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
    refresh_database(bot)
