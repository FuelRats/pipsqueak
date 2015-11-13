#coding: utf8
"""
rat-board.py - Fuel Rats Cases module.
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports
import re
from time import time

#urllib3 imports
import urllib3

#Sopel imports
from sopel.formatting import bold
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
from sopel.config.types import StaticSection, ValidatedAttribute

class RatBoardSection(StaticSection):
    apiURL = ValidatedAttribute('apiURL', str, default='')

def configure(config):
    config.define_section('ratboard', RatBoardSection)
    config.ratboard.configure_setting('apiURL',
        "The URL of the API to talk to.")

def setup(bot):
    bot.memory['ratbot'] = SopelMemory()
    bot.memory['ratbot']['log'] = SopelMemory()
    bot.memory['ratbot']['cases'] = SopelMemory()

# This regex gets pre-compiled, so we can easily re-use it later.
ratsignal = re.compile('ratsignal', re.IGNORECASE)

# urllib3 things.
conn = None


def openCase(bot, client, line):
    """
    Wrapper function to create a new case.
    """
    # Prepare API call.
    query = dict(nickname=client, CMDRname=client, codeRed=False)

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    # Tell the website about the new case.
    ret = conn.request_encode_body('POST', '/api/rescues/', fields=query)

    # Insert the Web ID and quotes in the bot's memory.
    bot.memory['ratbot']['cases'][client] = dict(id=ret['id'], quote=[line])

@rule('.*')
@priority('low')
@require_chanmsg
def getLog(bot, trigger):
    """
    Remember the last thing somebody said.
    """

    if trigger.group().startswith("\x01ACTION"): # /me
        line = trigger.group()[:-1]
    else:
        line = trigger.group()

    # Make sure we don't accidentally signal again.
    ratsignal.sub('R@signal', line)

    bot.memory['ratbot']['log'][Identifier(trigger.nick)] = line

    return NOLIMIT #This should NOT trigger rate limit, EVER.

@rule('(ratsignal)(.*)')
@priority('high')
def lightSignal(bot, trigger):
    """
    Light the rat signal, somebody needs fuel.
    """
    bot.say('Received R@SIGNAL from %s, Calling all available rats!' % trigger.nick)

    # Prepare values.
    line = ratsignal.sub('R@signal', trigger.group())
    client = Identifier(trigger.nick)

    # Open it up.
    openCase(bot, client, line)

@commands('quote')
def getQuote(bot, trigger):
    """
    Recite all case information
    """
    if trigger.group(3) == None:
        return bot.reply('I need a client name to look up.')

    client = Identifier(trigger.group(3))

    # Grab required memory bits.
    caseID = bot.memory['ratbot']['cases'][client]['id']
    quote = bot.memory['ratbot']['cases'][client]['quote']

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    # Grab required web bits.
    ret = conn.request('GET', '/api/rescues/'+caseID)
    rats = ret['rats']
    plat = ret['platform']

    bot.reply('%s\'s case (%s):' % (client, plat))
    if len(rats) > 0:
        bot.say('Assigned rats: '+', '.join(rats))
    for i in range(len(quote)):
        msg = quote[i]
        bot.say('[%s]%s' % (i, msg))

@commands('clear', 'close')
def clearCase(bot, trigger):
    """
    Mark a case as closed.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a name to clear cases.')

    client = Identifier(trigger.group(3))

    # Remove the memory bits.
    try:
        caseID = bot.memory['ratbot']['cases'][client]['id']
        del bot.memory['ratbot']['cases'][client]
    except KeyError:
        return bot.reply('Case not found.')

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    # Tell the website the case's closed.
    query = dict(active=False, open=False)
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    return bot.say('%s\'s case closed.' % (client,))

@commands('list')
def listCases(bot, trigger):
    """
    List the currently active cases.
    If -i parameter is specified, also show the inactive, but still open, cases.
    """
    if trigger.group(3) == '-i':
        showInactive = True
    else:
        showInactive = False

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    # Ask the API for all open cases.
    query = dict(open=True)
    ret = conn.request_encode_body('GET', '/api/search/rescues',fields=query)

    if len(ret) == 0:
        return bot.reply('No open cases.')

    # We have cases, sort them.
    actives = set()
    inactives = set()
    for case in ret:
        if case['active'] == True:
            actives.add(case['CMDRname'])
        else:
            inactives.add(case['CMDRname'])

    # Print to IRC.
    if showInactive:
        return bot.reply('%s active case(s): %s. %s inactive: %s' %
            (len(actives), ', '.join(actives), len(inactives), ', '.join(inactives)))
    else:
        return bot.reply('%s active case(s): %s (+ %s inactive).' %
            (len(actives), ', '.join(actives), len(inactives)))

@commands('grab')
def grabLine(bot, trigger):
    """
    Grab the last line the client said and add it to the case.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name to grab to.')

    client = Identifier(trigger.group(3))

    if client not in bot.memory['ratbot']['log']:
        # If this were to happen, somebody is trying to break the system.
        # After all, why make a case with no information?
        return bot.reply('%s has never spoken before.' % (client,))

    line = bot.memory['ratbot']['log'][client]

    if client not in bot.memory['ratbot']['cases']:
        # Create a new case.
        openCase(bot, client, line)
        return bot.say('%s\'s case opened with: %s' % (client, line))
    else:
        # Add line to case.
        bot.memory['ratbot']['cases'][client]['quote'] += (line,)
        return bot.say('Added "%s" to %s\'s case.' % (line, client))

@commands('inject')
def injectLine(bot, trigger):
    """
    Inject a custom line of text into the client's case.
    """

    # I need at least 2 parameters.
    if trigger.group(4) == None:
        return bot.reply('I need a case and some text to do this.')

    # Prepare the inject
    client = Identifier(trigger.group(3))
    line = trigger.group(2)[len(client)+1:] + ' [INJECT by %s]' % (trigger.nick,)

    # Does this client exist?
    if client not in bot.memory['ratbot']['cases']:
        # Create a new case.
        openCase(bot, client, line)
        return bot.say('%s\'s case opened with: %s' % (client, line))
    else:
        # Add line to case.
        bot.memory['ratbot']['cases'][client]['quote'] += (line,)
        return bot.say('Added "%s" to %s\'s case.' % (line, client))

@commands('sub')
def subLine(bot, trigger):
    """
    Substitute or delete an existing line of text to the client's case.
    """
    # I need at least 2 parameters
    if trigger.group(4) == None:
        return bot.reply('I need a case and a line number.')

    # Does this client exist?
    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')

    # Do we have enough lines?
    lines = bot.memory['ratbot']['cases'][client]['quote']
    if int(number) > len(lines):
        return bot.reply('I can\'t replace line %s if there\'s only %s lines.' %
            (number, len(lines)))

    # Ok, now we can sub the line.
    data = trigger.group(2)[len(client)+1:]
    try:
        number, subtext = data.split(' ', 1)
    except ValueError:
        # Or delete it.
        number = data
        subtext = None

    newquote = tuple()
    for i in range(len(lines)):
        if i != int(number):
            # Not our line, continue.
            newquote += (lines[i],)
        elif subtext == None:
            # Delete, don't sub.
            continue
        else:
            # Sub
            newquote += (subtext + '[SUB by %s]' % (trigger.nick,),)

    bot.memory['ratbot']['cases'][client]['quote'] = newquote

    if subtext == None:
        return bot.say('Line %s in %s\'s case deleted.' %
            (number, client))
    else:
        return bot.say('Line %s in %s\'s case replaced with: %s' %
            (number, client, subtext))

@commands('active')
def toggleCaseActive(bot, trigger):
    """
    Toggle a case active/inactive
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name to grab to.')

    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')

    caseID = bot.memory['ratbot']['cases'][client]['ID']

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    # Ask the API what it is, then reverse the result.
    a = not conn.request('GET', '/api/search/rescues/'+caseID)['active']

    # Upload the new result.
    query = dict(active=a)
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    if a:
        return bot.say('%s\'s case is now ' % (client,)+bold('active'))
    else:
        return bot.say('%s\'s case is now ' % (client,)+bold('inactive'))

@commands('assign')
def addRats(bot, trigger):
    """
    Assign rats to a client's case.
    """
    # I need at least 2 parameters
    if trigger.group(4) == None:
        return bot.reply('I need a case and at least 1 rat name.')

    # Does this client exist?
    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')
    caseID = bot.memory['ratbot']['cases'][client]['ID']

    rats = trigger.group(2)[len(client)+1:].split(' ')
    newrats = rats

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    webrats = conn.request('GET', 'api/rescues/'+caseID)['rats']

    for rat in webrats:
        rats.add(rat)

    query = dict(rats=rats)
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    return bot.say('Added rats to %s\'s case: %s' % (client, ', '.join(newrats)))

@commands('unassign')
def addRats(bot, trigger):
    """
    Remove rats from a client's case.
    """
    # I need at least 2 parameters
    if trigger.group(4) == None:
        return bot.reply('I need a case and at least 1 rat name.')

    # Does this client exist?
    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')
    caseID = bot.memory['ratbot']['cases'][client]['ID']

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    removedRats = trigger.group(2)[len(client)+1:].split(' ')
    rats = conn.request('GET', 'api/rescues/'+caseID)['rats']

    for rat in removedRats:
        try:
            rats.remove(rat)
        except ValueError:
            # This rat wasn't assigned here in the first place!
            continue

    query = dict(rats=rats)
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    return bot.say('Removed rats from %s\'s case: %s' % (
        client, ', '.join(removedRats)))

@commands('codered', 'cr')
def codeRed(bot, trigger):
    """
    Toggles the code red status of a case.
    A code red is when the client is so low on fuel that their life support
    system has failed, indicated by the infamous blue timer on their HUD.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name.')

    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')
    caseID = bot.memory['ratbot']['cases'][client]['ID']

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    # Ask the API what it is, then reverse the result.
    ret = conn.request('GET', '/api/search/rescues/'+caseID)
    CR = not ret['codeRed']

    # Upload the new result.
    query = dict(codeRed=CR)
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    rats = ', '.join(ret['rats'])

    if CR:
        bot.say('CODE RED! %s is on emegency oxygen.' % (client,))
        if len(rats) > 0:
            bot.say('%s: This is your case!' % (rats,))
    else:
        bot.say('%s\'s case demoted from code red.' % (client,))

@commands('pc')
def setCasePC(bot, trigger):
    """
    Sets a case platform to PC.
    To set a client's case to Xbox One, use the 'xbox' command or it's aliases.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name.')

    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')
    caseID = bot.memory['ratbot']['cases'][client]['ID']

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    query = dict(platform='PC')
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    return bot.say('%s\'s case set to PC.' % (client,))

@commands('xbox','xb','xb1','xbone')
def setCaseXbox(bot, trigger):
    """
    Sets a case platform to Xbox One.
    To set a client's case to PC, use the 'pc' command
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name.')

    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')
    caseID = bot.memory['ratbot']['cases'][client]['ID']

    if conn == None:
        # Make a connection
        conn = urllib3.connection_from_url(bot.config.ratboard.apiURL)

    query = dict(platform='Xbox One')
    conn.request_encode_body('PUT', 'api/rescues/'+caseID, fields=query)

    return bot.say('%s\'s case set to Xbox One.' % (client,))

