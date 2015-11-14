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

#Sopel imports
from sopel.formatting import bold
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory

def setup(bot):
    bot.memory['ratbot'] = SopelMemory()
    bot.memory['ratbot']['log'] = SopelMemory()
    bot.memory['ratbot']['cases'] = SopelMemory()

# This regex gets pre-compiled, so we can easily re-use it later.
ratsignal = re.compile('ratsignal', re.IGNORECASE)

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
def lightSignal(bot, trigger):
    """
    Light the rat signal, somebody needs fuel.
    """
    bot.say('Received R@SIGNAL from %s, Calling all available rats!' % trigger.nick)

    # Prepare a new case.
    line = ratsignal.sub('R@signal', trigger.group())

    #TODO call POST http://api.fuelrats.com/api/rescues/

    signal = dict(active=True, codeRed=False, platform='', rats=[], quote=(line,))

    # Inject it in the bot's memory.
    bot.memory['ratbot']['cases'][Identifier(trigger.nick)] = signal

@commands('quote')
def getQuote(bot, trigger):
    """
    Recite all case information
    """
    if trigger.group(3) == None:
        return bot.reply('I need a client name to look up.')

    client = Identifier(trigger.group(3))
    case = bot.memory['ratbot']['cases'][client]

    bot.reply('%s\'s case:' % client)
    if len(case['rats']) > 0:
        bot.say('Assigned rats: '+', '.join(case['rats']))
    for i in range(len(case['quote'])):
        msg = case['quote'][i]
        bot.say('[%s]%s' % (i, msg))

@commands('clear', 'close')
def clearCase(bot, trigger):
    """
    Mark a case as closed.
    """
    if trigger.group(3) == None:
        return bot.reply('I need a name to clear cases.')

    client = Identifier(trigger.group(3))
    try:
        del bot.memory['ratbot']['cases'][client]
    except:
        return bot.reply('Case not found.')
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

    actives = set()
    inactives = set()
    for k,v in bot.memory['ratbot']['cases'].items():
        if v['active']:
            actives.add(k)
        else:
            inactives.add(k)

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
        # This shouldn't ever happen,
        # because the RATSIGNAL line should be in the log.
        return bot.reply('%s has never spoken before.' % (client,))

    if client not in bot.memory['ratbot']['cases']:
        # Create a new case.
        signal = dict(active=True, codeRed=False, platform='', rats=[], quote=tuple())
        bot.memory['ratbot']['cases'][client] = signal
        newCase = True
    else:
        newCase = False

    line = bot.memory['ratbot']['log'][client]

    bot.memory['ratbot']['cases'][client]['quote'] += (line,)

    if newCase:
        return bot.say('%s\'s case opened with: %s' % (client, line))
    else:
        return bot.say('Added "%s" to %s\'s case.' % (line, client))

@commands('inject')
def injectLine(bot, trigger):
    """
    Inject a custom line of text into the client's case.
    """

    # I need at least 2 parameters.
    if trigger.group(4) == None:
        return bot.reply('I need a case and some text to do this.')

    # Does this client exist?
    client = Identifier(trigger.group(3))
    if client not in bot.memory['ratbot']['cases']:
        return bot.reply('Case not found.')

    # Good. Inject.
    inject = trigger.group(2)[len(client)+1:] + ' [INJECT by %s]' % (trigger.nick,)

    bot.memory['ratbot']['cases'][client]['quote'] += (inject,)
    return bot.say('Added "%s" to %s\'s case.' % (inject, client))

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

    data = trigger.group(2)[len(client)+1:]
    try:
        number, subtext = data.split(' ', 1)
    except ValueError:
        number = data
        subtext = None

    lines = bot.memory['ratbot']['cases'][client]['quote']

    if int(number) > len(lines):
        return bot.reply('I can\'t replace line %s if there\'s only %s lines.' %
            (number, len(lines)))
    newquote = tuple()

    for i in range(len(lines)):
        if i != int(number):
            # Not our line, continue.
            newquote += (lines[i],)
        elif subtext == None:
            # Delete, don't sub.
            continue
        else:
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

    # Reverse the polarity.
    active = not bot.memory['ratbot']['cases'][client]['active']
    bot.memory['ratbot']['cases'][client]['active'] = active

    if active:
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

    rats = trigger.group(2)[len(client)+1:].split(' ')

    for rat in rats:
        bot.memory['ratbot']['cases'][client]['rats'].append(rat)

    return bot.say('Added rats to %s\'s case: %s' % (client, ', '.join(rats)))

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

    # Reverse the polarity.
    CR = not bot.memory['ratbot']['cases'][client]['codeRed']
    bot.memory['ratbot']['cases'][client]['codeRed'] = CR

    rats = bot.memory['ratbot']['cases'][client]['rats']

    if CR:
        bot.say('CODE RED! %s is on emegency oxygen.' % (client,))
        if len(rats) > 0:
            bot.say('%s: This is your case!' % (', '.join(rats),))
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

    #Check the current platform.
    p = bot.memory['ratbot']['cases'][client]['platform']
    if p == 'PC':
        return bot.say('%s\'s case is already PC.' % (client,))
    else:
        bot.memory['ratbot']['cases'][client]['platform'] = 'PC'
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

    #Check the current platform.
    p = bot.memory['ratbot']['cases'][client]['platform']
    if p == 'Xbox One':
        return bot.say('%s\'s case is already Xbox One.' % (client,))
    else:
        bot.memory['ratbot']['cases'][client]['platform'] = 'Xbox One'
        return bot.say('%s\'s case set to Xbox One.' % (client,))

