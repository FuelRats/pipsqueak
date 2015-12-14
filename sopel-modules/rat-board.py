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
from json import dumps
from datetime import datetime, date

#requests imports
import requests

#Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
from sopel.config.types import StaticSection, ValidatedAttribute

## Start setup section ###

class RatBoardSection(StaticSection):
    apiurl = ValidatedAttribute('apiurl', str, default='http://api.fuelrats.com/')

def configure(config):
    config.define_section('ratboard', RatBoardSection)
    config.ratboard.configure_setting('apiurl',
        "The URL of the API to talk to.")

def setup(bot):
    if 'ratbot' not in bot.memory:
        bot.memory['ratbot'] = SopelMemory()

    bot.memory['ratbot']['log'] = SopelMemory()
    bot.memory['ratbot']['cases'] = SopelMemory()
    bot.memory['ratbot']['caseIndex'] = 0

    # Grab cases from the API on module (re)load.
    syncList(bot)

# This regex gets pre-compiled, so we can easily re-use it later.
ratsignal = re.compile('ratsignal', re.IGNORECASE)

def syncList(bot):
    """
    Grab all open cases from the API so we can work with them.
    """

    # Prep link.
    link = bot.config.ratboard.apiurl
    if link.endswith('/'):
        link += 'api/search/rescues'
    else:
        link += '/api/search/rescues'

    # Execute search
    d = dict(open=True)
    ret = requests.get(link, data=d).json()['data']
    # Don't really care about the KeyError at this point.
    # If it's thrown the API behind the configured URL is
    # broken and this module should fail anyway.

    if len(ret) < 1:
        # No open cases.
        return

    for case in ret:
        c = dict(id=case['id'], index=bot.memory['ratbot']['caseIndex'])
        bot.memory['ratbot']['caseIndex'] += 1
        bot.memory['ratbot']['cases'][Identifier(case['client']['nickname'])] = c

### End setup section ###
### Start wrapper section ###

def callAPI(bot, method, URI, fields=dict()):
    """Wrapper function to contact the web API."""
    # Prepare the endpoint.
    link = bot.config.ratboard.apiurl
    if link.endswith('/'):
        link += URI
    else:
        link += '/'+URI

    # Determine method and execute.
    if method == 'GET':
        ret = requests.get(link, json=fields)
    elif method == 'PUT':
        ret = requests.put(link, json=fields)
    elif method == 'POST':
        ret = requests.post(link, json=fields)

    try:
        json=ret.json()

        if 'errors' in json:
            return json['errors'][0]
        else:
            return json
    except ValueError:
        return {'code': '2608', 'details': 'API didn\'t return valid JSON.'}

def openCase(bot, client, line):
    """Wrapper function to create a new case."""
    # Prepare API call.
    query = dict(client=dict(nickname=client, CMDRname=client), quotes=[line])

    # Tell the website about the new case.
    ans = callAPI(bot, 'POST', 'api/rescues/', query)
    try:
        ret = ans['data']
    except KeyError:
        return False, ans

    # Insert the Web ID and quotes in the bot's memory.
    i = bot.memory['ratbot']['caseIndex']
    bot.memory['ratbot']['caseIndex'] += 1
    bot.memory['ratbot']['cases'][client] = dict(id=ret['id'], index=i)
    return True, None

def addLine(bot, client, line):
    """
    Wrapper function for !grab and !inject
    """
    client, caseID = getID(bot, client)
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))

    # Add this line
    query = dict(quotes=ret['quotes']+[line])

    # And push it to the API.
    ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)

    if 'data' in ret:
        # Success
        return bot.say('Added "%s" to %s\'s case.' % (line, client))
    else:
        return bot.say('Error adding line to %s\'s case: [%s]%s' %
            (client, ret['code'],ret['details']))

def getID(bot, inp):
    """
    Get the Client name and Case ID from either a nickname or case index.
    """
    try:
        index = int(inp)
        # Integer, use index.
        for name, case in bot.memory['ratbot']['cases'].items():
            if case['index'] == index:
                return name, case['id']
    except ValueError:
        pass

    # Unknown index, string?
    try:
        client = Identifier(inp)
    except AttributeError:
        # It's not an integer or a string. Magic has happened.
        return None, None
    try:
        return client, bot.memory['ratbot']['cases'][client]['id']
    except KeyError:
        # Wasn't using a known nickname, return None.
        return None, None

### End wrapper section ###

@rule('.*')
@priority('low')
@require_chanmsg
def getLog(bot, trigger):
    """Remember the last thing somebody said."""

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
    """Light the rat signal, somebody needs fuel."""
    bot.say('Received R@SIGNAL from %s, Calling all available rats!' % trigger.nick)

    # Prepare values.
    line = ratsignal.sub('R@signal', trigger.group())
    client = Identifier(trigger.nick)

    # Open it up.
    success, error = openCase(bot, client, line)
    if not success:
        return bot.say('Error in opening new case: [%s]%s' % (error['code'], error['details']))

@commands('quote')
def getQuote(bot, trigger):
    """
    Recite all case information
    required parameters: client name.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a client name to look up.')

    # Which client?
    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('No case with that name.')

    # Grab required web bits.
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))

    cmdr = ret['client']['CMDRname']
    rats = ret['rats']
    plat = ret['platform']
    quote = ret['quotes']

    # Prepare timestamps:

    # Created At
    opened = datetime.fromtimestamp(ret['createdAt'])
    try:
        # Turn into Galactic years
        opened = opened.replace(year = opened.year + 1286)
    except:
        # Feb 29th is a bit of a special case.
        opened = opened + (date(opened.year + 1286, 1, 1) - date(opened.year, 1, 1))

    # Last Modified
    updated = datetime.fromtimestamp(ret['lastModified'])
    try:
        # Turn into Galactic years
        updated = updated.replace(year = updated.year + 1286)
    except ValueError:
        # Feb 29th is a bit of a special case.
        updated = updated + (date(updated.year + 1286, 1, 1) - date(updated.year, 1, 1))

    # Turn both dates into human-readable strings.
    times = {
        'o': opened.strftime('%H:%M %d %b %Y'),
        'u': updated.strftime('%H:%M %d %b %Y')}

    # Printout

    bot.reply('%s\'s case (%s):' % (cmdr, plat))
    bot.say('Case opened: {0[o]}, last updated: {0[u]}'.format(times))
    if len(rats) > 0:
        bot.say('Assigned rats: '+', '.join(rats))
    for i in range(len(quote)):
        msg = quote[i]
        bot.say('[%s]%s' % (i, msg))

@commands('clear', 'close')
def clearCase(bot, trigger):
    """
    Mark a case as closed.
    required parameters: client name.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a name to clear cases.')

    # Which client?
    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    # Tell the website the case's closed.
    query = dict(active=False, open=False)
    ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)

    if 'data' in ret:
        del bot.memory['ratbot']['cases'][client]
        return bot.say('%s\'s case closed.' % (client,))
    else:
        return bot.say('Error closing %s\'s case: [%s]%s' %
            (client, ret['code'],ret['details']))

@commands('list')
def listCases(bot, trigger):
    """
    List the currently active cases.
    If -i parameter is specified, also show the inactive, but still open, cases.
    Otherwise, just show the amount of inactive, but still open cases.
    """
    if trigger.group(3) == '-i':
        showInactive = True
    else:
        showInactive = False

    # Ask the API for all open cases.
    query = dict(open=True)
    ans = callAPI(bot, 'GET', 'api/search/rescues', query)

    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching cases from API: [%s]%s' %
            (ret['code'], ret['details']))

    if len(ret) == 0:
        return bot.reply('No open cases.')

    # We have cases, sort them.
    actives = set()
    inactives = set()
    for case in ret:
        # Grab ID from the bot's memory
        index = bot.memory['ratbot']['cases'][Identifier(case['client']['nickname'])]['index']

        if case['codeRed']:
            name = color(case['client']['CMDRname'], colors.RED)
        else:
            name = case['client']['CMDRname']
        if case['active'] == True:
            actives.add('[%s]%s' % (index,name))
        else:
            inactives.add('[%s]%s' % (index,name))

    # Print to IRC.
    if showInactive:
        return bot.reply('%s active case(s): %s. %s inactive: %s.' %
            (len(actives), ', '.join(actives), len(inactives), ', '.join(inactives)))
    else:
        return bot.reply('%s active case(s): %s (+ %s inactive).' %
            (len(actives), ', '.join(actives), len(inactives)))

@commands('grab')
def grabLine(bot, trigger):
    """
    Grab the last line the client said and add it to the case.
    required parameters: client name.
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
        success, error = openCase(bot, client, line)
        if success:
            return bot.say('%s\'s case opened with: %s' % (client, line))
        else:
            return bot.reply('Error in opening new case: [%s]%s' %
                (error['code'], error['details']))
    else:
        return addLine(bot, client, line)

@commands('inject')
def injectLine(bot, trigger):
    """
    Inject a custom line of text into the client's case.
    required parameters: client name, text to inject.
    """

    # I need at least 2 parameters.
    if trigger.group(4) == None:
        return bot.reply('I need a case and some text to do this.')

    # Does this client exist?
    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        client = Identifier(trigger.group(3))

    # Prepare the inject
    line = trigger.group(2)[len(trigger.group(3))+1:] + ' [INJECT by %s]' % (trigger.nick,)

    if caseID == None:
        # Create a new case.
        success, error = openCase(bot, client, line)
        if success:
            return bot.say('%s\'s case opened with: %s' % (client, line))
        else:
            return bot.reply('Error in opening new case: [%s]%s' %
                (error['code'], error['details']))
    else:
        return addLine(bot, client, line)

@commands('sub')
def subLine(bot, trigger):
    """
    Substitute or delete an existing line of text to the client's case.
    required parameters: client name, line number.
    optional parameter: new text
    """
    # I need at least 2 parameters
    if trigger.group(4) == None:
        return bot.reply('I need a case and a line number.')

    # Does this client exist?
    caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    number = trigger.group(4)

    # Grab lines
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))
    lines = ret['quotes']

    # Do we have enough lines?
    if int(number) > len(lines):
        return bot.reply('I can\'t replace line %s if there\'s only %s lines.' %
            (number, len(lines)))

    # Ok, now we can sub the line.
    data = trigger.group(2)[len(trigger.group(3))+1:]
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

        # And push it to the API.
        ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)

        if 'data' not in ret:
            # Oops.
            return bot.say('Error changing line %s in %s\'s case: [%s]%s' %
                (number, client, ret['code'],ret['details']))

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
    required parameters: client name.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name to set (in)active.')

    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    # Ask the API what it is, then reverse the result.
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))
    a = not ret['active']

    # Upload the new result.
    query = dict(active=a)
    ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)

    if 'data' not in ans:
        return bot.reply('Error pushing data: [%s]%s' %
            (ans['code'], ans['details']))

    if a:
        return bot.say('%s\'s case is now ' % (client,)+bold('active'))
    else:
        return bot.say('%s\'s case is now ' % (client,)+bold('inactive'))

@commands('assign', 'add', 'go')
def addRats(bot, trigger):
    """
    Assign rats to a client's case.
    required parameters: client name, rat name(s).
    """
    # I need at least 2 parameters
    if trigger.group(4) == None:
        return bot.reply('I need a case and at least 1 rat name.')

    # Does this client exist?
    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    # List of rats
    rats = trigger.group(2)[len(trigger.group(3))+1:].split(' ')
    newrats = rats[:]

    # Grab the current rats
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))
    webrats = ret['rats']

    # Add the current rats to the list of new rats.
    for rat in webrats:
        # Don't allow empty names.
        if len(rat.strip()) < 1:
            continue
        # Don't allow duplicates.
        if rat not in rats:
            rats.append(rat)

    # Upload new list.
    query = dict(rats=rats)
    ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
    if 'data' not in ans:
        return bot.reply('Error pushing data: [%s]%s' %
            (ans['code'], ans['details']))

    return bot.say('%s, Please add the following rat(s): %s' % (client, ', '.join(newrats)))

@commands('unassign', 'rm', 'remove', 'stdn', 'standdown')
def rmRats(bot, trigger):
    """
    Remove rats from a client's case.
    """
    # I need at least 2 parameters
    if trigger.group(4) == None:
        return bot.reply('I need a case and at least 1 rat name.')

    # Does this client exist?
    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    removedRats = trigger.group(2)[len(trigger.group(3))+1:].split(' ')
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))

    rats = ret['rats']

    for rat in removedRats:
        if len(rat.strip()) < 1:
            # Empty rats
            removedRats.remove(rat)
            continue
        try:
            rats.remove(rat)
        except ValueError:
            # This rat wasn't assigned here in the first place!
            continue

    query = dict(rats=rats)
    ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error pushing data: [%s]%s' %
            (ans['code'], ans['details']))

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

    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    # Ask the API what it is, then reverse the result.
    ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error fetching data: [%s]%s' %
            (ans['code'], ans['details']))
    CR = not ret['codeRed']

    # Upload the new result.
    query = dict(codeRed=CR)
    ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error pushing data: [%s]%s' %
            (ans['code'], ans['details']))

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

    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    query = dict(platform='PC')
    ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error pushing data: [%s]%s' %
            (ans['code'], ans['details']))

    return bot.say('%s\'s case set to PC.' % (client,))

@commands('xbox','xb','xb1','xbone')
def setCaseXbox(bot, trigger):
    """
    Sets a case platform to Xbox One.
    To set a client's case to PC, use the 'pc' command
    """
    if trigger.group(3) == None:
        return bot.reply('I need a case name.')

    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')


    query = dict(platform='Xbox One')
    ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
    try:
        ret = ans['data']
    except KeyError:
        return bot.reply('Error pushing data: [%s]%s' %
            (ans['code'], ans['details']))

    return bot.say('%s\'s case set to Xbox One.' % (client,))

