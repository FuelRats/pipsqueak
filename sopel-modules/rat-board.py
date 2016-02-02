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
import datetime
import collections
import itertools
import contextlib

#Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
import ratlib.sopel

import threading
import operator
import concurrent.futures

import ratlib
from ratlib.autocorrect import correct
from ratlib.api.props import *
import ratlib.api.http as api
call = api.call
urljoin = api.urljoin

target_case_max = 9  # Target highest boardindex to assign
HISTORY_MAX = 10000  # Max number of nicks we'll remember history for at once.


## Start setup section ###
def configure(config):
    ratlib.sopel.configure(config)

def setup(bot):
    ratlib.sopel.setup(bot)
    bot.memory['ratbot']['log'] = (threading.Lock(), collections.OrderedDict())
    bot.memory['ratbot']['board'] = RescueBoard()
    bot.memory['ratbot']['executor'] = concurrent.futures.ThreadPoolExecutor(max_workers = 1)
    refresh_cases(bot)

# This regex gets pre-compiled, so we can easily re-use it later.
ratsignal = re.compile('ratsignal', re.IGNORECASE)

import warnings


class RescueBoard:
    """
    Manages all attached cases, including API calls.
    """
    INDEX_TYPES = {
        'boardindex': operator.attrgetter('boardindex'),
        'id': operator.attrgetter('id'),
        'clientnick': lambda x: None if not x.client or not x.client['nickname'] else x.client['nickname'].lower(),
        'clientcmdr': lambda x: None if not x.client or not x.client['CMDRname'] else x.client['CMDRname'].lower(),
    }

    MAX_POOLED_CASES = 10

    def __init__(self):
        self._lock = threading.Lock()
        self.indexes = {k: {} for k in self.INDEX_TYPES.keys()}

        # Boardindex pool
        self.maxpool = self.MAX_POOLED_CASES
        self.counter = itertools.count(start = self.maxpool)
        self.pool = collections.deque(range(0, self.maxpool))

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def add(self, rescue):
        """
        Adds the selected case to our indexes.
        """
        with self:
            assert rescue.board is None, "Rescue is already assigned."
            assert rescue.boardindex is None, "Rescue already has a boardindex."
            # Assign an boardindex
            rescue.board = self
            try:
                rescue.boardindex = self.pool.popleft()
            except IndexError:
                rescue.boardindex = next(self.counter)

            # Add to indexes
            for index, fn in self.INDEX_TYPES.items():
                # FIXME: This will fail horribly if the function raises
                key = fn(rescue)
                if key is None:
                    continue
                if key in self.indexes[index]:
                    warnings.warn("Key {key!r} is already in index {index!r}".format(key=key, index=index))
                    continue
                self.indexes[index][key] = rescue

    def remove(self, rescue):
        """
        Removes the selected case from our indexes.
        """
        with self:
            # Remove from indexes
            assert rescue.board is self, "Rescue is not ours."
            assert rescue.boardindex is not None, "Rescue had no boardindex."
            for index, fn in self.INDEX_TYPES.items():
                key = fn(rescue)
                if key is None:
                    continue
                if self.indexes[index].get(key) != rescue:
                    warnings.warn("Key {key!r} in index {index!r} does not belong to this rescue.".format(key=key, index=index))
                    continue
                del self.indexes[index][key]

            # Reclaim numbers
            if rescue.boardindex < self.maxpool:
                self.pool.append(rescue.boardindex)
            if not self.indexes['boardindex']:  # Board is clear.
                self.counter = itertools.count(start = self.maxpool)

    @contextlib.contextmanager
    def change(self, rescue):
        """
        Returns a context manager that snapshots case attributes and updates the indexes with any relevant changes.

        Usage Example:
        ```
        with board.change(rescue):
            rescue.client['CMDRname'] = cmdrname
        """
        with self:
            assert rescue.board is self
            snapshot = dict({index: fn(self.rescue) for index, fn in self.INDEX_TYPES.items()})
            yield rescue
            assert rescue.board is self  # In case it was changed
            for index, fn in self.INDEX_TYPES.items():
                new = fn(rescue)
                old = snapshot[index]
                if old != new:
                    if old is not None:
                        if self.indexes[index].get(old) != rescue:
                            warnings.warn("Key {key!r} in index {index!r} does not belong to this rescue.".format(key=old, index=index))
                        else:
                            del self.indexes[index][old]
                    if new is not None:
                        if new in self.indexes[index]:
                            warnings.warn("Key {key!r} is already in index {index!r}".format(key=new, index=index))
                        else:
                            self.indexes[index][new] = rescue

    def create(self):
        """
        Creates a rescue attached to this board.
        """
        rescue = Rescue()
        self.add(rescue)
        return rescue

    def find(self, search, create=False):
        """
        Attempts to find a rescue attached to this board.  If it fails, possibly creates one instead.

        :param create: Whether to create a case that's not found.  Even if True, this only applies for certain types of
        searches.
        :return: The case (if found or created), or None if no case was found.

        If `int(search)` does not raise, `search` is treated as a boardindex.  This will never create a case.

        Otherwise, if `search` begins with `"@"`, it is treated as an ID from the API.  This will never create a case.

        Otherwise, `search` is treated as a client nickname or a commander name (in that order).  If this still does
        not have a result, a new case is returned (if `create` is True), otherwise returns None.
        """
        try:
            if search and isinstance(search, str) and search[0] == '#':
                index = int(search[1:])
            else:
                index = int(search)
        except ValueError:
            pass
        else:
            return self.indexes['boardindex'].get(index, None)

        if not search:
            return None

        if search[0] == '@':
            return self.indexes['id'].get(search[1:], None)

        result = self.indexes['clientnick'].get(search.lower()) or self.indexes['clientcmdr'].get(search.lower())
        if result or not create:
            return result

        rescue = Rescue()
        rescue.client['CMDRname'] = search
        rescue.client['nickname'] = search
        self.add(rescue)
        return rescue


class Rescue(TrackedBase):
    active = TrackedProperty()
    createdAt = DateTimeProperty()
    id = TrackedProperty(remote_name='_id')
    rats = SetProperty()
    tempRats = SetProperty(default=lambda: set())
    quotes = ListProperty(default=lambda: [])
    platform = TrackedProperty()
    open = TypeCoercedProperty(default=True, coerce=bool)
    epic = TypeCoercedProperty(default=False, coerce=bool)
    codeRed = TypeCoercedProperty(default=False, coerce=bool)
    client = DictProperty(default=lambda: {})

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.boardindex = None
        self.board = None

    def change(self):
        """
        Convenience shortcut for performing safe attribute changes (that also update indexes).

        ```
        with rescue.change():
            rescue.client['CMDRname'] = 'Foo'
        ```

        If the rescue is not attached to the board, this returns a dummy context manager that does nothing.
        """
        if self.board:
            return self.board.change(self)
        @contextlib.contextmanager
        def _dummy():
            yield self
        return _dummy()

    def refresh(self, json):
        for prop in self._props:
            prop.read(self, json)

    @classmethod
    def load(cls, json, inst=None):
        """
        Creates a case from a JSON dict.
        """
        if inst is None:
            inst = cls()
        inst.refresh(json)
        return inst

    @property
    def client_name(self):
        t = self.client.get('CMDRname')
        if t:
            return "CMDR " + t
        t = self.client.get('nickname')
        if t:
            return t
        return "<unknown client>"



def refresh_cases(bot):
    """
    Grab all open cases from the API so we can work with them.
    """
    try:
        result = call('GET', urljoin(bot.config.ratbot.apiurl, '/api/search/rescues'), data={'open': True})
    except api.APIError as ex:
        # TODO: Rework this to try again later.
        raise

    board = bot.memory['ratbot']['board']

    with board:
        # Cases we have but the refresh doesn't.  We'll assume these are closed after winnowing down the list.
        missing = set(board.indexes['id'].keys())
        for case in result['data']:
            id = case['_id']
            missing.discard(id)  # Case still exists.
            existing = board.indexes['id'].get(id)

            if existing:
                # TODO: This should refresh the existing case if it can safely do so.
                continue

            board.add(Rescue.load(case))

        for id in missing:
            # TODO: Remove these cases if we can safely do so.
            pass


def append_quotes(bot, search, lines, autocorrect=True, create=True):
    """
    Appends lines to a (possibly newly created) case.  Returns a tuple of (Rescue, appended_lines).

    If autocorect is True, performs system autocorrection first.  In this case, appended_lines may not match the input.
    :param bot: IRC bot handle.
    :param search: Client name, case ID, boardindex, or a Rescue object.
    :param lines: Line(s) to append.  If this is a string it is coerced to a list of strings.
    :param autocorrect: Whether to perform system autocorrection.
    :param create: Whether this is allowed to create a new case.  Passed to `Board.find()`
    :return:
    """
    if isinstance(lines, str):
        lines = [lines]
    if autocorrect:
        newlines = []
        for line in lines:
            result = correct(line)
            newlines.append(result.output)
            if result.fixed:
                originals = ", ".join('"...{name}"'.format(name=system) for system in result.corrections)
                if result.fixed > 1:
                    newlines.append("[Autocorrected system names, originals were {}]".format(originals))
                else:
                    newlines.append("[Autocorrected system name, original was {}]".format(originals))
    else:
        newlines = lines  # No alterations

    if isinstance(search, Rescue):
        rescue = search
    else:
        rescue = bot.memory['ratbot']['board'].find(search, create=create)
    if not rescue:
        return None
    rescue.quotes.extend(newlines)
    return rescue, newlines


# Maintain a log of the last thing anyone in channel said.
@rule('.*')
@priority('low')
@require_chanmsg
def maintain_history(bot, trigger):
    """Remember the last thing somebody said."""
    if trigger.group().startswith("\x01ACTION"): # /me
        line = trigger.group()[:-1]
    else:
        line = trigger.group()

    # Make sure we don't accidentally signal again.
    # TODO: This should probably happen on quote/etc instead -- we should store the client's words verbatim.
    ratsignal.sub('R@signal', line)

    lock, log = bot.memory['ratbot']['log']
    nick = Identifier(trigger.nick)
    with lock:
        log[nick] = line
        log.move_to_end(nick)
        while len(log) > HISTORY_MAX:
            log.popitem(False)
    return NOLIMIT  #This should NOT trigger rate limit, EVER.


@rule(r'\s*(ratsignal)(.*)')
@priority('high')
def rule_ratsignal(bot, trigger):
    """Light the rat signal, somebody needs fuel."""
    line = ratsignal.sub('R@signal', trigger.group())
    client = Identifier(trigger.nick)
    rescue, lines = append_quotes(bot, trigger.nick, [line], create=True)
    bot.say(
        "Received R@SIGNAL from {nick}.  Calling all available rats!  (Case {index})"
        .format(nick=trigger.nick, index=rescue.boardindex if rescue else "<unknown>")
    )
    bot.reply('Are you on emergency oxygen? (Blue timer on the right of the front view)')


@commands('quote')
def cmd_quote(bot, trigger):
    """
    Recite all case information
    required parameters: client name.
    """
    if trigger.group(3) is None:
        return bot.reply('Usage: {} <client or case number>'.format(trigger.group(1)))

    # TODO: Start attempted case refresh here.
    # ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    rescue = bot.memory['ratbot']['board'].find(trigger.group(3), create=False)
    if not rescue:
        return bot.reply('Could not find a case with that name or number.')

    datefmt = "%b %d %H:%M:%S UTC"

    tags = [rescue.platform if rescue.platform else '(unknown platform)']
    if rescue.epic:
        tags.append("epic")
    if rescue.codeRed:
        tags.append(bold(color('CR', colors.RED)))

    bot.reply(
        "{client}'s case #{index} ({tags})  @{id}"
        .format(client=rescue.client_name, index=rescue.boardindex, tags=", ".join(tags))
    )
    bot.say(
        "Case opened: {opened} ({opened_ago}), updated: {updated} ({updated_ago})"
        .format(
            opened=rescue.createdAt.strftime(datefmt) if rescue.createdAt else '<unknown>',
            updated=rescue.lastModified.strftime(datefmt) if rescue.lastModified else '<unknown>',
            opened_ago=ratlib.friendly_timedelta(rescue.createdAt) if rescue.createdAt else '???',
            updated_ago=ratlib.friendly_timedelta(rescue.lastModified) if rescue.lastModified else '???',
        )
    )

    # FIXME: Rats/temprats/etc isn't really handled yet.
    if rescue.rats:
        bot.say("Assigned rats: " + ", ".join(rescue.rats))
    if rescue.tempRats:
        bot.say("Assigned tempRats: " + ", ".join(rescue.tempRats))
    for ix, quote in enumerate(rescue.quotes):
        bot.say('[{ix}]{quote}'.format(ix=ix, quote=quote))

@commands('clear', 'close')
def cmd_clear(bot, trigger):
    """
    Mark a case as closed.
    required parameters: client name.
    """
    if trigger.group(3) is None:
        return bot.reply('Usage: {} <client or case number>'.format(trigger.group(1)))

    # TODO: Start attempted case refresh here.
    # ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    rescue = bot.memory['ratbot']['board'].find(trigger.group(3), create=False)
    if not rescue:
        return bot.reply('Could not find a case with that name or number.')

    rescue.open = False
    rescue.active = False
    # Stats are fun!
    if rescue.createdAt:
        delta = ratlib.format_timedelta(datetime.datetime.now(tz=datetime.timezone.utc) - rescue.createdAt)
        return bot.reply("{client}'s case closed.  (Time: {time}".format(client=rescue.client_name, time=delta))
    return bot.reply("{client}'s case closed.".format(client=rescue.client_name))

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
    except api.APIError as ex:
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
        try:
            index = openCase(bot, client, line)
        except APIError as ex:
            return bot.reply(str(ex))
        return bot.say(
            "{client}'s case opened with: {line}  (Case {index})".format(client=client, line=line, index=index)
        )
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

