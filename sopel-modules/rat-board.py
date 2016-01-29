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
import datetime
# from iso8601 import parse_date as parse_datetime  # parse_date is a misnomer, as documented it produces a datetime.

#requests imports
import requests

#Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
from sopel.config.types import StaticSection, ValidatedAttribute

from ratlib import friendly_timedelta
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
        c = dict(id=case['_id'], index=bot.memory['ratbot']['caseIndex'])
        bot.memory['ratbot']['caseIndex'] += 1
        bot.memory['ratbot']['cases'][Identifier(case['client']['nickname'])] = c

### End setup section ###
### Start wrapper section ###
class APIError(Exception):
    def __init__(self, code, details, json=None):
        self.code = code
        self.details = details
        self.json = json

    def __repr__(self):
        return "<{0.__class__.__name__({0.code}, {0.details!r})>".format(self)
    __str__ = __repr__

class APIJSONError(APIError):
    def __init__(self, code='2608', details="API didn\'t return valid JSON."):
        super().__init__(code, details)

class APIMissingDataError(APIError):
    def __init__(self, code='????', details="API response had no 'data' section.", json=None):
        super().__init__(code, details, json=json)


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
        json = ret.json()
        if 'errors' in json:
            err = json['errors'][0]
            raise APIError(err.get('code'), err.get('details'), json=json)
        if 'data' not in json:
            raise APIMissingDataError(json=json)
        else:
            return json
    except ValueError:
        raise APIJSONError()


def openCase(bot, client, line):
    """Wrapper function to create a new case."""
    # Prepare API call.
    query = dict(client=dict(nickname=client, CMDRname=client), quotes=[line])

    # Tell the website about the new case.  No try-except here since we want it to propogate out.
    ans = callAPI(bot, 'POST', 'api/rescues/', query)
    ret = ans['data']

    # Insert the Web ID and quotes in the bot's memory.
    i = bot.memory['ratbot']['caseIndex']
    bot.memory['ratbot']['caseIndex'] += 1
    bot.memory['ratbot']['cases'][client] = dict(id=ret['_id'], index=i)
    return i

def addLine(bot, client, line):
    """
    Wrapper function for !grab and !inject
    """
    client, caseID = getID(bot, client)
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

    # Add this line
    query = dict(quotes=ret['quotes']+[line])

    # And push it to the API.
    try:
        ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        # Success
        return bot.say('Added "{0}" to {1}\'s case.'.format(lines[0], client))
    except APIError as ex:
        return bot.reply(str(ex))

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
    line = ratsignal.sub('R@signal', trigger.group())
    client = Identifier(trigger.nick)

    """Light the rat signal, somebody needs fuel."""
    index = None
    try:
        index = openCase(bot, client, line)
    except APIError as ex:
        bot.say(str(ex))

    msg = "Received R@SIGNAL from {nick}, Calling all available rats!"
    if index is not None:
        msg += "  (Case {index})"
    bot.say(msg.format(nick=trigger.nick, index=index))
    bot.reply('Are you on emergency oxygen? (Blue timer on the right of the front view)')

    # Prepare values.

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
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

    cmdr = ret['client']['CMDRname']
    rats = ret['rats']
    plat = ret['platform']
    quote = ret['quotes']

    #opened = parse_datetime(ret['createdAt'])
    #updated = parse_datetime(ret['lastModified'])
    opened = datetime.datetime.fromtimestamp(ret['createdAt'] / 1000, tz=datetime.timezone.utc)
    updated = datetime.datetime.fromtimestamp(ret['lastModified'] / 1000, tz=datetime.timezone.utc)
    datefmt = "%Y-%m-%d %H:%M:%S %Z"

    if ret['codeRed']:
        bot.reply('{0}\'s case ({1}, {2}):'.format(cmdr, plat, bold(color('CR', colors.RED))))
    else:
        bot.reply('{0}\'s case ({1}):'.format(cmdr, plat))

    bot.say(
        "Case opened: {opened} ({opened_ago}), last updated: {updated} ({updated_ago})"
        .format(
            opened=opened.strftime(datefmt), updated=updated.strftime(datefmt),
            opened_ago=friendly_timedelta(opened), updated_ago=friendly_timedelta(opened)
        )
    )

    if len(rats) > 0:
        bot.say('Assigned rats: '+', '.join(rats))
    for i in range(len(quote)):
        msg = quote[i]
        bot.say('[{0}]{1}'.format(i, msg))

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
    try:
        ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        del bot.memory['ratbot']['cases'][client]
    except APIError as ex:
        return bot.reply(str(ex))
    return bot.say(client+'\'s case closed.')

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
    try:
        ans = callAPI(bot, 'GET', 'api/search/rescues', query)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

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
            actives.add('[{0}]{1}'.format(index,name))
        else:
            inactives.add('[{0}]{1}'.format(index,name))

    # Print to IRC.
    if showInactive:
        return bot.reply('{0} active case(s): {1}. {2} inactive: {3}.'.format(
            len(actives), ', '.join(actives), len(inactives), ', '.join(inactives)))
    else:
        return bot.reply('{0} active case(s): {1} (+ {2} inactive).'.format(
            len(actives), ', '.join(actives), len(inactives)))

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
        return bot.reply(client+' has never spoken before.')

    line = bot.memory['ratbot']['log'][client]

    if client not in bot.memory['ratbot']['cases']:
        # Create a new case.
        success, error = openCase(bot, client, line)
        if success:
            return bot.say('{0}\'s case opened with: {1}'.format(client, line))
        else:
            return bot.reply('Error pushing data: [{0[code]}]{0[details]}'.format(error))
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
    line = trigger.group(2)[len(trigger.group(3))+1:] + ' [INJECT by {0}]'.format(trigger.nick)

    if caseID == None:
        # Create a new case.
        success, error = openCase(bot, client, line)
        if success:
            return bot.say('{0}\'s case opened with: {1}'.format(client, line))
        else:
            return bot.reply('Error pushing data: [{0[code]}]{0[details]}'.format(error))
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
    client, caseID = getID(bot, trigger.group(3))
    if caseID == None:
        return bot.reply('Case not found.')

    # Is the line number even a number?
    try:
        int(trigger.group(4))
    except ValueError:
        return bot.reply('Line number is not a valid number.')

    number = trigger.group(4)

    # Grab lines
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))
    lines = ret['quotes']

    # Do we have enough lines?
    if int(number)+1 > len(lines):
        return bot.reply(
            'I can\'t replace line {0} if there\'s only {1} lines.'.format(
                number, len(lines)))

    # Ok, now we can sub the line.
    data = trigger.group(2)[len(trigger.group(3))+1:]
    try:
        number, subtext = data.split(' ', 1)
    except ValueError:
        # Or delete it.
        number = data
        subtext = None

    newquote = list()
    for i in range(len(lines)):
        if i != int(number):
            # Not our line, continue.
            newquote += (lines[i],)
        elif subtext == None:
            # Delete, don't sub.
            continue
        else:
            # Sub
            newquote += [subtext + '[SUB by {0}]'.format(trigger.nick)]

    query = {'quotes': newquote}
    # And push it to the API.
    try:
        ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)

        if subtext == None:
            return bot.say('Line {0} in {1}\'s case deleted.'.format(number, client))
        else:
            return bot.say(
                'Line {0} in {1}\'s case replaced with: {2}'.format(
                    number, client, subtext))
    except APIError as ex:
        return bot.reply(str(ex))

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
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

    a = not ret['active']
    # Upload the new result.
    query = dict(active=a)
    try:
        ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
    except APIError as ex:
        return bot.reply(str(ex))
    return bot.say("{client}'s case is now {active}".format(client=client, active=bold('active' if a else 'inactive')))

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
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))
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
    try:
        ret = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        # Success
        bot.say('Added "{0}" to {1}\'s case.'.format(line, client))
    except APIError as ex:
        bot.reply(str(ex))
    return bot.say(client+', Please add the following rat(s) to your friends list: '+', '.join(newrats))

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
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

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
    try:
        ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

    return bot.say(
        'Removed rats from {0}\'s case: {1}'.format(
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
    try:
        ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))
    CR = not ret['codeRed']

    # Upload the new result.
    query = dict(codeRed=CR)
    try:
        ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        ret = ans['data']
    except ValueError as ex:
        return bot.reply(str(ex))

    rats = ', '.join(ret['rats'])

    if CR:
        bot.say('CODE RED! {0} is on emergency oxygen.'.format(client))
        if len(rats) > 0:
            bot.say(rats+': This is your case!')
    else:
        bot.say(client+'\'s case demoted from code red.')

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
    try:
        ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))
    return bot.say(client+'\'s case set to PC.')

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
    try:
        ans = callAPI(bot, 'PUT', 'api/rescues/'+caseID, query)
        ret = ans['data']
    except APIError as ex:
        return bot.reply(str(ex))

    return bot.say(client+'\'s case set to Xbox One.')

