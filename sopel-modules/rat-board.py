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
import warnings
import functools

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
    bot.memory['ratbot']['queue'] = concurrent.futures.ThreadPoolExecutor(max_workers=10)  # Immediate tasks
    refresh_cases(bot)


# This regex gets pre-compiled, so we can easily re-use it later.
ratsignal = re.compile('ratsignal', re.IGNORECASE)


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
        self._lock = threading.RLock()
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
                self.counter = itertools.count(start=self.maxpool)

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
            snapshot = dict({index: fn(rescue) for index, fn in self.INDEX_TYPES.items()})
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

    @property
    def rescues(self):
        """
        Read-only convenience property to list all known rescues.
        """
        return self.indexes['boardindex'].values()


class Rescue(TrackedBase):
    active = TrackedProperty(default=True)
    createdAt = DateTimeProperty(readonly=True)
    lastModified = DateTimeProperty(readonly=True)
    id = TrackedProperty(remote_name='_id', readonly=True)
    rats = SetProperty(default=lambda: set())
    unidentifiedRats = SetProperty(default=lambda: set())
    quotes = ListProperty(default=lambda: [])
    platform = TrackedProperty(default='pc')
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

    def refresh(self, json, merge=True):
        for prop in self._props:
            if isinstance(prop, InstrumentedProperty):
                prop.read(self, json, merge=merge)
                continue
            if merge and prop in self._changed:
                continue  # Ignore incoming data that conflicts with our pending changes.
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

    def save(self, full=False, props=None):
        result = {}
        props = self._props if full else self._changed
        for prop in props:
            prop.write(self, result)
        return result

    @property
    def client_name(self):
        """Returns the first logical name for a client."""
        t = self.client.get('nickname')
        if t:
            return t
        t = self.client.get('CMDRname')
        if t:
            return "CMDR " + t
        return "<unknown client>"

    @property
    def client_names(self):
        """Returns all known names for a client."""
        nickname = self.client.get('nickname')
        cmdrname = self.client.get('CMDRname')
        if nickname:
            if cmdrname and nickname.lower() != cmdrname.lower():
                return "{nickname} (CMDR {cmdrname})".format(nickname, cmdrname)
            return nickname
        elif cmdrname:
            return "CMDR {cmdrname}".format(cmdrname)
        else:
            return "<unknown client>"

def refresh_cases(bot, rescue=None):
    """
    Grab all open cases from the API so we can work with them.
    :param bot: Sopel bot
    :param rescue: Individual rescue to refresh.
    """
    uri = urljoin(bot.config.ratbot.apiurl, '/api/search/rescues')
    if rescue is not None:
        if rescue.id is None:
            raise ValueError('Cannot refresh a non-persistent case.')
        uri += "/" + rescue.id
        data = {}
    else:
        data = {'open': True}

    # Exceptions here are the responsibility of the caller.
    result = call('GET', uri, data=data)
    board = bot.memory['ratbot']['board']

    if rescue:
        if not result['data']:
            board.remove(rescue)
        else:
            with rescue.change():
                rescue.refresh(result['data'])
        return

    with board:
        # Cases we have but the refresh doesn't.  We'll assume these are closed after winnowing down the list.
        missing = set(board.indexes['id'].keys())
        for case in result['data']:
            id = case['_id']
            missing.discard(id)  # Case still exists.
            existing = board.indexes['id'].get(id)

            if existing:
                with existing.change():
                    existing.refresh(case)
                continue
            board.add(Rescue.load(case))

        for id in missing:
            case = board.indexes['id'].get(id)
            if case:
                board.remove(case)

def save_case(bot, rescue):
    """
    Begins saving changes to a case.  Returns the future.
    """
    with rescue.change():
        data = rescue.save(full=(rescue.id is None))
        rescue.commit()
    uri = urljoin(bot.config.ratbot.apiurl, '/api/rescues')
    if rescue.id:
        method = "PUT"
        uri += "/" + rescue.id
    else:
        method = "POST"

    def task():
        result = call(method, uri, data=data)
        rescue.commit()
        if 'data' not in result or not result['data']:
            raise RuntimeError("API response returned unusable data.")
        with rescue.change():
            rescue.refresh(result['data'])
        return rescue

    return bot.memory['ratbot']['queue'].submit(task)

def append_quotes(bot, search, lines, autocorrect=True, create=True, detect_platform=True):
    """
    Appends lines to a (possibly newly created) case.  Returns a tuple of (Rescue, appended_lines).

    If autocorrect is True, performs system autocorrection first.  In this case, appended_lines may not match the input.
    :param bot: IRC bot handle.
    :param search: Client name, case ID, boardindex, or a Rescue object.
    :param lines: Line(s) to append.  If this is a string it is coerced to a list of strings.
    :param autocorrect: Whether to perform system autocorrection.
    :param create: Whether this is allowed to create a new case.  Passed to `Board.find()`
    :param detect_platform: If True, attempts to parse a platform out of the first line.
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
    if detect_platform and not rescue.quotes:
        platforms = set()
        for line in lines:
            if re.search(r'\bpc\b', line, flags=re.IGNORECASE):
                platforms.add('pc')
            if re.search(r'\bxb(ox|one|1)?\b', line, flags=re.IGNORECASE):
                platforms.add('xb')
        if len(platforms) == 1:
            rescue.platform = platforms.pop()

    rescue.quotes.extend(newlines)
    return rescue, newlines

# Maintain a log of the last thing anyone in channel said.
@rule('.*')
@priority('low')
@require_chanmsg
def rule_history(bot, trigger):
    """Remember the last thing somebody said."""
    if trigger.group().startswith("\x01ACTION"): # /me
        line = trigger.group()[:-1]
    else:
        line = trigger.group()

    ## Make sure we don't accidentally signal again.
    ## This is now replaced by filtering our output to not include ratsignal, rather than filtering input.
    # ratsignal.sub('R@signal', line)

    lock, log = bot.memory['ratbot']['log']
    nick = Identifier(trigger.nick)
    with lock:
        log[nick] = line
        log.move_to_end(nick)
        while len(log) > HISTORY_MAX:
            log.popitem(False)
    return NOLIMIT  #This should NOT trigger rate limit, EVER.


@rule(r'\s*(testsignal)(.*)')
@priority('high')
@ratlib.sopel.filter_output
def rule_ratsignal(bot, trigger):
    """Light the rat signal, somebody needs fuel."""
    line = trigger.group()
    client = Identifier(trigger.nick)
    rescue, lines = append_quotes(bot, trigger.nick, [line], create=True)
    bot.say(
        "Received RATSIGNAL from {nick}.  Calling all available rats!  (Case {index})"
        .format(nick=trigger.nick, index=rescue.boardindex if rescue else "<unknown>")
    )
    bot.reply('Are you on emergency oxygen? (Blue timer on the right of the front view)')
    future = save_case(bot, rescue)
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done with ratsignal from {nick}; continuing in background.".format(nick=trigger.nick)
        )

@commands('quote')
@ratlib.sopel.filter_output
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

    tags = [rescue.platform.upper() if rescue.platform else 'unknown platform']
    if rescue.epic:
        tags.append("epic")
    if rescue.codeRed:
        tags.append(bold(color('CR', colors.RED)))

    bot.reply(
        "{client}'s case #{index} ({tags}) opened {opened} ({opened_ago}), last updated {updated} ({updated_ago})  @{id}"
        .format(
            client=rescue.client_name, index=rescue.boardindex, tags=", ".join(tags), id=rescue.id or 'pending',
            opened=rescue.createdAt.strftime(datefmt) if rescue.createdAt else '<unknown>',
            updated=rescue.lastModified.strftime(datefmt) if rescue.lastModified else '<unknown>',
            opened_ago=ratlib.friendly_timedelta(rescue.createdAt) if rescue.createdAt else '???',
            updated_ago=ratlib.friendly_timedelta(rescue.lastModified) if rescue.lastModified else '???',
        )
    )

    # FIXME: Rats/temprats/etc isn't really handled yet.
    if rescue.rats:
        bot.say("Assigned rats: " + ", ".join(rescue.rats))
    if rescue.unidentifiedRats:
        bot.say("Assigned unidentifiedRats: " + ", ".join(rescue.unidentifiedRats))
    for ix, quote in enumerate(rescue.quotes):
        bot.say('[{ix}]{quote}'.format(ix=ix, quote=quote))

@commands('clear', 'close')
@ratlib.sopel.filter_output
def cmd_clear(bot, trigger):
    """
    Mark a case as closed.
    required parameters: client name.
    """
    if trigger.group(3) is None:
        return bot.reply('Usage: {} <client or case number>'.format(trigger.group(1)))

    board = bot.memory['ratbot']['board']
    # TODO: Start attempted case refresh here.
    # ans = callAPI(bot, 'GET', 'api/rescues/'+caseID)
    rescue = board.find(trigger.group(3), create=False)
    if not rescue:
        return bot.reply('Could not find a case with that name or number.')

    rescue.open = False
    rescue.active = False
    future = save_case(bot, rescue)
    with board:
        board.remove(rescue)
    bot.reply("Cleared case {0.boardindex} ({0.client_names}).".format(rescue))

    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice("API is still not done with clearing case {!r}; continuing in background.".format(trigger.group(3)))


@commands('list')
@ratlib.sopel.filter_output
def cmd_list(bot, trigger):
    """
    List the currently active, open cases.

    Supported parameters:
        -i: Also show inactive (but still open) cases.
        -@: Show full case IDs.  (LONG)
    """
    params = trigger.group(3)
    if not params or params[0] != '-':
        params = '-'

    show_ids = '@' in params
    show_inactive = 'i' in params

    board = bot.memory['ratbot']['board']
    pool = bot.memory['ratbot']['queue']

    def _keyfn(rescue):
        return not rescue.codeRed, rescue.boardindex

    with board:
        actives = list(filter(lambda x: x.active, board.rescues))
        actives.sort(key=_keyfn)
        inactives = list(filter(lambda x: not x.active, board.rescues))
        inactives.sort(key=_keyfn)

    def format_rescue(rescue):
        cr = color("(CR)", colors.RED) if rescue.codeRed else ''
        id = ""
        if show_ids:
            id = "@" + (rescue.id if rescue.id is not None else "none")
        return "[{boardindex}{id}]{client}{cr}".format(
            boardindex=rescue.boardindex,
            id=id,
            client=rescue.client.get('nickname') or rescue.client.get('CMDRname') or '<unknown>',
            cr=cr
        )

    output = []
    for name, cases, expand in (('active', actives, True), ('inactive', inactives, show_inactive)):
        if not cases:
            output.append("No {name} cases".format(name=name))
            continue
        num = len(cases)
        s = 's' if num != 1 else ''
        t = "{num} {name} case{s}".format(num=num, name=name, s=s)
        if expand:
            t += ": " + ", ".join(format_rescue(rescue) for rescue in cases)
        output.append(t)
    bot.reply("; ".join(output))


@commands('grab')
@ratlib.sopel.filter_output
def cmd_grab(bot, trigger):
    """
    Grab the last line the client said and add it to the case.
    required parameters: client name.
    """
    if trigger.group(3) is None:
        return bot.reply('I need a case name to grab to.')

    client = Identifier(trigger.group(3))

    lock, log = bot.memory['ratbot']['log']
    with lock:
        line = log.get(client)

    if line is None:
        # If this were to happen, somebody is trying to break the system.
        # After all, why make a case with no information?
        return bot.reply(client + ' has not spoken recently.')

    rescue, lines = append_quotes(bot, client, line, create=True)
    created = len(lines) == len(rescue.quotes)  # Dirty hack for now
    future = save_case(bot, rescue)

    if created:
        fmt = "{rescue.client_name}'s case opened with: \"{line}\"  (Case {rescue.boardindex})"
    else:
        fmt = "{rescue.client_name}'s case updated with: \"{line}\"  (Case {rescue.boardindex})"
    bot.say(fmt.format(rescue=rescue, line=lines[0]))
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done with grab for {rescue.client_name}}; continuing in background.".format(rescue=rescue)
        )


@commands('inject')
def cmd_inject(bot, trigger):
    """
    Inject a custom line of text into the client's case.
    required parameters: client name, text to inject.
    """
    parts = re.split(r'\s+', trigger.group(2) or '', 1)
    if len(parts) != 2:
        return bot.reply('Usage: {} <client or case number> <text of message>'.format(trigger.group(1)))
    client, line = parts
    rescue, lines = append_quotes(bot, client, line, create=True)

    created = len(lines) == len(rescue.quotes)  # Dirty hack for now
    future = save_case(bot, rescue)

    if created:
        fmt = "Created case for {rescue.client_name}.  (Case {rescue.boardindex})"
    else:
        fmt = "Added line to {rescue.client_name}.  (Case {rescue.boardindex})"
    bot.reply(fmt.format(rescue=rescue))
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done with inject for {rescue.client_name}}; continuing in background.".format(rescue=rescue)
        )


@commands('sub')
def cmd_sub(bot, trigger):
    """
    Substitute or delete an existing line of text to the client's case.
    required parameters: client name, line number.
    optional parameter: new text
    """
    parts = re.split(r'\s+', trigger.group(2) or '', 2)
    if len(parts) < 2:
        return bot.reply('Usage: {} <client or case number> <line> [<replacement>]'.format(trigger.group(1)))
    line = None
    if len(parts) == 3:
        line = parts.pop()
    client, lineno = parts
    try:
        lineno = int(lineno)
    except ValueError:
        return bot.reply('Line number must be an integer.')
    if lineno < 0:
        return bot.reply('Line number cannot be negative.')

    board = bot.memory['ratbot']['board']
    rescue = board.find(client, create=False)
    if not rescue:
        return bot.reply("No such case.")
    if lineno >= len(rescue.quotes):
        return bot.reply('Case only has {} line(s)'.format(len(rescue.quotes)))

    if not line:
        rescue.quotes.pop(lineno)
        bot.reply("Deleted line {}".format(lineno))
    else:
        rescue.quotes[lineno] = line
        bot.reply("Updated line {}".format(lineno))

    future = save_case(bot, rescue)
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done updating case for ({rescue.client_name}}; continuing in background.".format(rescue=rescue)
        )


@commands('active', 'activate', 'inactive', 'deactivate')
def cmd_active(bot, trigger):
    """
    Toggle a case active/inactive
    required parameters: client name.
    """
    if trigger.group(3) is None:
        return bot.reply('I need a case name to set (in)active.')
    board = bot.memory['ratbot']['board']
    rescue = board.find(trigger.group(3), create=False)
    if rescue is None:
        return bot.reply('No such case.')
    rescue.active = not rescue.active

    future = save_case(bot, rescue)
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done updating case for ({rescue.client_name}}; continuing in background.".format(rescue=rescue)
        )
    return bot.say(
        "{rescue.client_name}'s case is now {active}".format(rescue=rescue, active=bold('active' if a else 'inactive'))
    )

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


@commands('codered', 'casered', 'cr')
def cmd_codered(bot, trigger):
    """
    Toggles the code red status of a case.
    A code red is when the client is so low on fuel that their life support
    system has failed, indicated by the infamous blue timer on their HUD.
    """
    if trigger.group(3) is None:
        return bot.reply('I need a case name to set (in)active.')
    board = bot.memory['ratbot']['board']
    rescue = board.find(trigger.group(3), create=False)
    if rescue is None:
        return bot.reply('No such case.')
    rescue.codeRed = not rescue.codeRed
    future = save_case(bot, rescue)
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done updating case for ({rescue.client_name}}; continuing in background.".format(rescue=rescue)
        )
    if rescue.codeRed:
        bot.say('CODE RED! {rescue.client_name} is on emergency oxygen.'.format(rescue=rescue))
        if rescue.rats:
            bot.say(", ".join(rats) + ": This is your case!")
    else:
        bot.say('{rescue.client_name}\'s case is no longer CR.'.format(rescue=rescue))


def cmd_platform(bot, trigger, platform=None):
    """
    Sets a case platform to PC or xbox.
    """
    if trigger.group(3) is None:
        return bot.reply('I need a case name to set (in)active.')
    board = bot.memory['ratbot']['board']
    rescue = board.find(trigger.group(3), create=False)
    if rescue is None:
        return bot.reply('No such case.')

    rescue.platform = platform
    future = save_case(bot, rescue)
    try:
        result = future.result(timeout=10)
    except concurrent.futures.TimeoutError:
        bot.notice(
            "API is still not done updating platform for ({rescue.client_name}}; continuing in background.".format(rescue=rescue)
        )
    return bot.say(
        "{rescue.client_name}'s platform set to {platform}".format(rescue=rescue, platform=rescue.platform.upper())
    )

# For some reason, this can't be tricked with functools.partial.
@commands('pc')
def cmd_platform_pc(bot, trigger):
    return cmd_platform(bot, trigger, 'pc')

@commands('xbox', 'xb', 'xb1', 'xbone')
def cmd_platform_xb(bot, trigger):
    return cmd_platform(bot, trigger, 'xb')
