# coding: utf8
"""
rat_board.py - Fuel Rats Cases module.

Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

Copyright originally by Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl> (2015),
under the Eiffel Forum License, version 2

See LICENSE.md

This module is built on top of the Sopel system.
http://sopel.chat/
"""

# Python core imports
import re
import datetime
import collections
import itertools
import warnings

import sys
import contextlib
import traceback
import threading
from threading import Timer
import operator
import concurrent.futures
import dateutil.parser

# Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
from sopel.config.types import StaticSection, ValidatedAttribute
from sopel.module import require_privmsg, rate

import ratlib.sopel
from ratlib import timeutil
from ratlib.autocorrect import correct
from ratlib.starsystem import scan_for_systems
from ratlib.api.props import *
from ratlib.api.names import *
from ratlib.sopel import UsageError
import ratlib.api.http
import ratlib.db
from ratlib.db import with_session, Starsystem
from ratlib.api.v2compatibility import convertV2DataToV1, convertV1RescueToV2

urljoin = ratlib.api.http.urljoin

target_case_max = 9  # Target highest boardindex to assign
HISTORY_MAX = 10000  # Max number of nicks we'll remember history for at once.

defaultdata = {'IRCNick': 'unknown client name', 'langID': 'en',
               'markedForDeletion': {'marked': False, 'reason': 'None.', 'reporter': 'Noone.'}, "status": {},
               "boardIndex": None}
def dummymethod():
    pass
preptimer = Timer(0, dummymethod)

## Start setup section ###
class RatboardSection(StaticSection):
    signal = ValidatedAttribute('signal', str, default='ratsignal')


def configure(config):
    ratlib.sopel.configure(config)
    config.define_section('ratboard', RatboardSection)
    config.ratboard.configure_setting(
        'signal',
        (
            "When a message from a user contains this regex and does not begin with the command prefix, it will"
            " be treated as an incoming ratsignal."
        )
    )


def setup(bot):
    ratlib.sopel.setup(bot)
    bot.memory['ratbot']['log'] = (threading.Lock(), collections.OrderedDict())
    bot.memory['ratbot']['board'] = RescueBoard()
    bot.memory['ratbot']['board'].bot = bot
    bot.memory['ratbot']['lastsignal'] = None

    if not hasattr(bot.config, 'ratboard') or not bot.config.ratboard.signal:
        signal = 'ratsignal'
    else:
        signal = bot.config.ratboard.signal
        bot.memory['ratbot']['maxplots'] = int(bot.config.ratbot.maxplots) or 4

    bot.memory['ratbot']['plots_available'] = threading.Semaphore(value=bot.memory['ratbot']['maxplots'])

    # Build regular expression pattern.
    pattern = '(?!{prefix}).*{signal}.*'.format(prefix=bot.config.core.prefix, signal=signal)
    try:
        re.compile(pattern, re.IGNORECASE)  # Test the pattern, but we don't care about the result just the exception.
    except re.error:
        warnings.warn(
            "Failed to compile ratsignal regex; pattern was {!r}.  Falling back to old pattern."
                .format(pattern)
        )
        pattern = re.compile(r'\s*ratsignal.*')
    rule(pattern)(rule_ratsignal)

    # Handle log.
    if not hasattr(bot.config, 'ratbot') or not bot.config.ratbot.apidebug:
        bot.memory['ratbot']['apilog'] = None
        bot.memory['ratbot']['apilock'] = contextlib.ExitStack()  # Context manager that does nothing
    else:
        filename = bot.config.ratbot.apidebug
        if filename == 'stderr':
            f = sys.stderr
        elif filename == 'stdout':
            f = sys.stdout
        else:
            f = open(bot.config.ratbot.apidebug, 'w')
        bot.memory['ratbot']['apilog'] = f
        bot.memory['ratbot']['apilock'] = threading.Lock()
        print("[RatBoard] Logging API calls to " + bot.config.ratbot.apidebug)

    try:
        refresh_cases(bot)
        updateBoardIndexes(bot)
    except ratlib.api.http.BadResponseError as ex:
        warnings.warn("Failed to perform initial sync against the API")
        import traceback
        traceback.print_exc()


FindRescueResult = collections.namedtuple('FindRescueResult', ['rescue', 'created'])


class RescueBoard:
    """
    Manages all attached cases, including API calls.
    """
    INDEX_TYPES = {
        'boardindex': operator.attrgetter('boardindex'),
        'id': operator.attrgetter('id'),
        'client': lambda x: str(x.client).lower(),
        'nick': lambda x: None if x.data is None or (not x.data.get('IRCNick')) else str(x.data['IRCNick']).lower(),
    }

    MAX_POOLED_CASES = 10
    bot = None

    def __init__(self):
        self._lock = threading.RLock()
        self.indexes = {k: {} for k in self.INDEX_TYPES.keys()}

        # Boardindex pool
        self.maxpool = self.MAX_POOLED_CASES
        self.counter = itertools.count(start=self.maxpool)
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
                    warnings.warn(
                        "Key {key!r} in index {index!r} does not belong to this rescue.".format(key=key, index=index))
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
            rescue.client = cmdrname
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
                            warnings.warn(
                                "Key {key!r} in index {index!r} does not belong to this rescue.".format(key=old,
                                                                                                        index=index))
                        else:
                            del self.indexes[index][old]
                    if new is not None:
                        if new in self.indexes[index]:
                            warnings.warn("Key {key!r} is already in index {index!r}".format(key=new, index=index))
                        else:
                            # print('Updating index '+str(index)+' with '+str(new))
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

        :param search: What to search for.
        :param create: Whether to create a case that's not found.  Even if True, this only applies for certain types of
        searches.
        :return: A FindRescueResult tuple of (rescue, created), both of which will be None if no case was found.

        If `int(search)` does not raise, `search` is treated as a boardindex.  This will never create a case.

        Otherwise, if `search` begins with `"@"`, it is treated as an ID from the API.  This will never create a case.

        Otherwise, `search` is treated as a client nickname or a commander name (in that order).  If this still does
        not have a result, a new case is returned (if `create` is True).
        """
        search = search.strip()
        try:
            if search and isinstance(search, str) and search[0] == '#':
                index = int(search[1:])
            else:
                index = int(search)
        except ValueError:
            pass
        else:
            rescue = self.indexes['boardindex'].get(index, None)
            return FindRescueResult(rescue, False if rescue else None)

        if not search:
            return FindRescueResult(None, None)

        if search[0] == '@':
            rescue = self.indexes['id'].get(search[1:], None),
            return FindRescueResult(rescue, False if rescue else None)

        # print('Indexes: '+str(self.indexes))
        searchterms = [search.lower()]
        searchterms.append(searchterms[0].replace('_', ' '))
        for index in 'client', 'nick':
            for term in searchterms:
                rescue = self.indexes[index].get(term)
                if rescue:
                    break
            else:
                continue
            break

        if rescue or not create:
            return FindRescueResult(rescue, False if rescue else None)

        rescue = Rescue()
        rescue.client = search
        self.add(rescue)
        return FindRescueResult(rescue, True)

    @property
    def rescues(self):
        """
        Read-only convenience property to list all known rescues.
        """
        return self.indexes['boardindex'].values()


class Rescue(TrackedBase):
    active = TrackedProperty(default=True)
    createdAt = DateTimeProperty(readonly=True)
    updatedAt = DateTimeProperty(readonly=True)
    id = TrackedProperty(remote_name='id', readonly=True)
    rats = SetProperty(default=lambda: set())
    unidentifiedRats = SetProperty(default=lambda: set())
    quotes = ListProperty(default=lambda: [])
    platform = TrackedProperty(default=None)
    open = TypeCoercedProperty(default=True, coerce=bool)
    epic = TypeCoercedProperty(default=False, coerce=bool)
    codeRed = TypeCoercedProperty(default=False, coerce=bool)
    client = TrackedProperty(default='<unknown client>')
    system = TrackedProperty(default=None)
    successful = TypeCoercedProperty(default=True, coerce=bool)
    title = TrackedProperty(default=None)
    firstLimpet = TrackedProperty(default='')
    data = TrackedProperty(
        default={'langID': 'unknown', 'IRCNick': '<unknown IRC Nickname>',
                 'markedForDeletion': {'marked': False, 'reason': 'None.', 'reporter': 'Noone.'}})

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.boardindex = None
        self.board = None

    def change(self):
        """
        Convenience shortcut for performing safe attribute changes (that also update indexes).

        ```
        with rescue.change():
            rescue.client = 'Foo'
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
        """Returns the Client CMDR name"""
        if self.client:
            return self.client
        return "<unknown client>"

    def touch(self, when=None):
        """
        Updates modification (and potentially creation time) of this case.  Should only be used when API-less
        :param when: Time to set.  Should be a UTC timestamp
        """
        if not when:
            when = datetime.datetime.now(tz=datetime.timezone.utc)
        if not self.createdAt:
            self.createdAt = when
        self.updatedAt = when
        return when


def refresh_cases(bot, rescue=None, force=False):
    """
    Grab all open cases from the API so we can work with them.
    :param bot: Sopel bot
    :param rescue: Individual rescue to refresh.
    :param force: True forcibly wipes the board and refreshes it clean.  False merges changes instead.
    """
    if not bot.config.ratbot.apiurl:
        warnings.warn("No API URL configured.  Operating in offline mode.")
        return  # API disabled.
    uri = '/rescues'
    if rescue is not None:
        if rescue.id is None:
            raise ValueError('Cannot refresh a non-persistent case.')
        uri += "/" + rescue.id

    else:
        uri += "?status.not=closed"

    # Exceptions here are the responsibility of the caller.
    result = callapi(bot, 'GET', uri)
    try:
        addNamesFromV2Response(result['included'])
    except:
        pass
    result['data'] = convertV2DataToV1(result['data'])
    # print('[RatBoard] refreshing returned '+str(result))
    if force:
        bot.memory['ratbot']['board'] = RescueBoard()
    board = bot.memory['ratbot']['board']

    if rescue:
        if len(result['data']) != 1:
            board.remove(rescue)
        else:
            with rescue.change():
                rescue.refresh(result['data'][0])
        return

    with board:
        # Cases we have but the refresh doesn't.  We'll assume these are closed after winnowing down the list.
        missing = set(board.indexes['id'].keys())
        # print("Result: " + str(result))
        for case in result['data']:
            id = case['id']
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

def updateBoardIndexes(bot):
    board = bot.memory['ratbot']['board']

    for rescue in board.rescues:
        with board.change(rescue):
            if rescue.data is None:
                rescue.data = {'boardIndex': rescue.boardindex}
            else:
                rescue.data.update({'boardIndex' : rescue.boardindex})
        save_case(bot, rescue, forceFull=True)

@commands('reindex', 'updateindex', 'index', 'ri')
@require_permission(Permissions.rat)
def cmd_reindex(bot, trigger):
    """
    Updates all Indexes with the API (/Dispatch Board)
    aliases: reindex, updateindex, index, ri
    """
    bot.say("Updating board indexes...")
    updateBoardIndexes(bot)
    bot.say("Done.")

def save_case(bot, rescue, forceFull=False):
    """
    Begins saving changes to a case.  Returns the future.

    :param bot: Bot instance
    :param rescue: Rescue to save.
    """

    with rescue.change():
        data = rescue.save(full=((rescue.id is None) or forceFull))
        rescue.commit()

    if not bot.config.ratbot.apiurl:
        return None  # API Disabled

    uri = '/rescues'
    if rescue.id:
        method = "PUT"
        uri += "/" + rescue.id
    else:
        method = "POST"

    def task():
        result = callapi(bot, method, uri, data=convertV1RescueToV2(data))
        rescue.commit()
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'], single=(method=="POST"))
        if 'data' not in result or not result['data']:
            raise RuntimeError("API response returned unusable data.")
        with rescue.change():
            rescue.refresh(result['data'][0])
        return rescue

    return bot.memory['ratbot']['executor'].submit(task)


def save_case_later(bot, rescue, message=None, timeout=10, forceFull=False):
    """
    Schedules a case to be saved and waits up to timeout seconds for a result.  Outputs message as a notice if the
    timeout expires.

    :param bot: Bot instance.
    :param rescue: Rescue to save
    :param message: Timeout message.  Determined automagically if None.
    :param timeout: Timeout.
    :return:
    """
    if not bot.config.ratbot.apiurl:
        rescue.touch()
    # Let's not. print('[RatBoard] Saving Case: '+str(json.dumps(rescue, default=lambda o: o.__dict__)))
    future = save_case(bot, rescue, forceFull)
    if not future:
        return None
    try:
        future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as ex:
        print('[RatBoard] Timeout Error: ' + str(ex))
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        if message is None:
            message = (
                "API is still not done updating case for {{name}}; continuing in background."
                    .format(name=rescue.data["IRCNick"])
            )
        bot.say(message)
        # return future


class AppendQuotesResult:
    """
    Result information from append_quotes
    """

    def __init__(self, rescue=None, created=False,
                 added_lines=None, autocorrected=False, detected_platform=None, detected_system=None
                 ):
        """
        Creates a new AppendQuotesResult

        :param rescue: The rescue that was found/created, or None if no such rescue.
        :param created: True if the rescue was freshly created.
        :param added_lines: Lines that were added to the new case after any relevant transformations.
        :param autocorrected: True if system name autocorrection triggered.
        :param detected_platform: Set to the detected platform, or False if no platform was detected.
        :param detected_system: Set to the detected system, or False if no system was detected.
        """
        self.rescue = rescue
        self.created = created
        self.added_lines = added_lines or []
        self.autocorrected = autocorrected
        self.detected_platform = detected_platform
        self.detected_system = detected_system

    def __bool__(self):
        return self.rescue is not None

    def tags(self):
        """Convenience method."""
        if not self:
            return []
        rv = ["Case " + str(self.rescue.boardindex)]
        if self.detected_platform:
            if self.detected_platform.upper() == 'PS':
                self.detected_platform = 'ps4'
            rv.append(self.detected_platform.upper())
        if self.detected_system:
            rv.append(self.detected_system)
        if self.autocorrected:
            rv.append("Autocorrected")
        return rv


def append_quotes(bot, search, lines, autocorrect=True, create=True, detect_platform=True, detect_system=True, author="Mecha"):
    """
    Appends lines to a (possibly newly created) case.  Returns a tuple of (Rescue, appended_lines).

    If autocorrect is True, performs system autocorrection first.  In this case, appended_lines may not match the input.
    :param bot: IRC bot handle.
    :param search: Client name, case ID, boardindex, a Rescue object, or a FindRescueResult.
    :param lines: Line(s) to append.  If this is a string it is coerced to a list of strings.
    :param autocorrect: Whether to perform system autocorrection.
    :param create: Whether this is allowed to create a new case.  Passed to `Board.find()`
    :param detect_platform: If True, attempts to parse a platform out of the first line.
    :param detect_system: If True, attempts system name autodetection.
    :return: A AppendQuotesResult representing the actions that happened.
    """
    rv = AppendQuotesResult()
    if isinstance(search, Rescue):
        rv.rescue = search
        rv.created = False
    elif isinstance(search, FindRescueResult):
        rv.rescue = search.rescue
        rv.created = search.created
    else:
        rv.rescue, rv.created = bot.memory['ratbot']['board'].find(search, create=create)
    if not rv:
        return rv

    if isinstance(lines, str):
        lines = [lines]
    if autocorrect:
        rv.added_lines = []
        for line in lines:
            result = correct(line)
            rv.added_lines.append(result.output)
            if result.fixed:
                rv.autocorrected = True
                originals = ", ".join('"...{name}"'.format(name=system) for system in result.corrections)
                if result.fixed > 1:
                    rv.added_lines.append("[Autocorrected system names, originals were {}]".format(originals))
                else:
                    rv.added_lines.append("[Autocorrected system name, original was {}]".format(originals))
    else:
        rv.added_lines = lines
    if rv.added_lines and detect_system and not rv.rescue.system:
        systems = scan_for_systems(bot, rv.added_lines[0])
        if len(systems) == 1:
            rv.detected_system = systems.pop()
            rv.added_lines.append("[Autodetected system: {}]".format(rv.detected_system))
            rv.rescue.system = rv.detected_system
    if detect_platform and rv.rescue.platform == None:
        platforms = set()
        for line in rv.added_lines:
            if re.search(
                    r"""
                    (?:[^\w-]|\A)  # Beginning of line, or non-hyphen word boundary
                    pc             # ... followed by "PC"
                    (?:[^\w-]|\Z)  # End of line, or non-hyphen word boundary
                    """, line, flags=re.IGNORECASE | re.VERBOSE
            ):
                platforms.add('pc')

            if re.search(
                    r"""
                    (?:[^\w-]|\A)  # Beginning of line, or non-hyphen word boundary
                    xb(?:ox)?      # ... followed by "XB" or "XBOX"
                    (?:-?(?:1|one))?  # ... maybe followed by 1/one, possibly w/ leading hyphen
                    (?:[^\w-]|\Z)  # End of line, or non-hyphen word boundary
                    """, line, flags=re.IGNORECASE | re.VERBOSE
            ):
                platforms.add('xb')
            if re.search(
                    r"""
                    (?:[^\w-]|\A)  # Beginning of line, or non-hyphen word boundary
                    [pP](?:lay)?(?:[- ])?[sS](?:tation)?      # ... followed by "ps" or "playstation" or "pstation" or "plays" or "Play Station" or ....
                    (?:[- ]?(?:4|four))?  # ... maybe followed by 4/four, possibly w/ leading hyphen/space
                    (?:[^\w-]|\Z)  # End of line, or non-hyphen word boundary
                    """, line, flags=re.IGNORECASE | re.VERBOSE
            ):
                if bot.config.ratboard.enable_ps_support == 'True' or False:
                    platforms.add('ps')
        if len(platforms) == 1:
            rv.rescue.platform = platforms.pop()
            rv.detected_platform = rv.rescue.platform

    json_lines = []
    for line in rv.added_lines:
        json_lines.append({"message":line, "updatedAt":datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
                           "createdAt":datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'), "author":author, "lastAuthor":author})
    rv.rescue.quotes.extend(json_lines)
    return rv


from ratlib.sopel import parameterize


# Convenience function
def requires_case(fn):
    return parameterize('r', "<client or case number>")(fn)


@rule('.*')
@priority('low')
@require_chanmsg
def rule_history(bot, trigger):
    """Remember the last thing somebody said."""
    if trigger.group().startswith("\x01ACTION"):  # /me
        line = trigger.group()[:-1]
    else:
        line = trigger.group()

    lock, log = bot.memory['ratbot']['log']
    nick = Identifier(trigger.nick)
    with lock:
        log[nick] = line
        log.move_to_end(nick)
        while len(log) > HISTORY_MAX:
            log.popitem(False)
    return NOLIMIT  # This should NOT trigger rate limit, EVER.


# @rule(r'\s*(ratsignal|testsignal)(.*)')
@priority('high')
@ratlib.sopel.filter_output
def rule_ratsignal(bot, trigger):
    """Light the rat signal, somebody needs fuel."""
    line = trigger.group()
    client = Identifier(trigger.nick)
    value = bot.memory['ratbot']['board'].find(client, create=False)
    if value[0]:
        bot.reply('You already sent a Signal! Please stand by, someone will help you soon!')
        return
    result = append_quotes(bot, trigger.nick, [line], create=True, author=trigger.nick)
    bot.say(
        "Received RATSIGNAL from {nick}.  Calling all available rats!  ({tags})"
            .format(nick=trigger.nick, tags=", ".join(result.tags()) if result else "<unknown>")
    )
    bot.reply('Are you on emergency oxygen? (Blue timer on the right of the front view)')
    with bot.memory['ratbot']['board'].change(result.rescue):
        result.rescue.data.update(defaultdata)
        result.rescue.data.update({'IRCNick': str(client), "boardIndex": int(result.rescue.boardindex)})
    save_case_later(
        bot, result.rescue,
        "API is still not done with ratsignal from {nick}; continuing in background.".format(nick=trigger.nick),
        forceFull=True
    )
    global preptimer
    try:
        preptimer.cancel()
    except:
        pass
    preptimer = Timer(180, prepexpired, args=[bot])
    preptimer.start()

@rule('!prep.*')
def prepsent(bot, trigger):
    global preptimer
    try:
        preptimer.cancel()
    except:
        pass

@commands('quote')
@ratlib.sopel.filter_output
@requires_case
@require_permission(Permissions.rat)
def cmd_quote(bot, trigger, rescue):
    """
    Recites all known information for the specified rescue
    Required parameters: client name or case number.
    """
    func_quote(bot, trigger, rescue)


def func_quote(bot, trigger, rescue, showboardindex=True):
    tags = ['unknown platform' if not rescue.platform or rescue.platform == 'unknown' else rescue.platform.upper()]
    if tags[0] == 'PS':
        tags[0] = 'PS4'
    if rescue.epic:
        tags.append("epic")
    if rescue.codeRed:
        tags.append(bold(color('CR', colors.RED)))

    fmt = (
              ("Rescue Operation {title}: " if rescue.title else "") +
              "{client}'s case " + (
                  "#{index}" if showboardindex else "") + " at {system} ({tags}) opened {opened} ({opened_ago}),"
                                                          " updated {updated} ({updated_ago})"
          ) + ("  @{id}" if bot.config.ratbot.apiurl else "")

    bot.say(fmt.format(
        client=rescue.client_name, index=rescue.boardindex, tags=", ".join(tags),
        opened=timeutil.format_timestamp(rescue.createdAt) if rescue.createdAt else '<unknown>',
        updated=timeutil.format_timestamp(rescue.updatedAt) if rescue.updatedAt else '<unknown>',
        opened_ago=timeutil.friendly_timedelta(rescue.createdAt) if rescue.createdAt else '???',
        updated_ago=timeutil.friendly_timedelta(rescue.updatedAt) if rescue.updatedAt else '???',
        id=rescue.id or 'pending',
        system=rescue.system or 'an unknown system',
        title=rescue.title
    ))

    if rescue.rats:
        ratnames = []
        for rat in rescue.rats:
            name = getRatName(bot, rat)[0]
            ratnames.append(name)
        bot.say("Assigned rats: " + ", ".join(ratnames))
    if rescue.unidentifiedRats:
        bot.say("Assigned unidentifiedRats: " + ", ".join(rescue.unidentifiedRats))
    for ix, quote in enumerate(rescue.quotes):
        pdate = "unknown" if quote["updatedAt"] is None else timeutil.friendly_timedelta(dateutil.parser.parse(quote['updatedAt']))
        if quote['lastAuthor'] is None:
            bot.say(
                '[{ix}][{quote[author]} {ago}] {quote[message]}'.format(ix=ix, quote=quote, ago=pdate))
        elif quote['lastAuthor'] == quote['author']:
            bot.say(
                '[{ix}][{quote[author]} {ago}] {quote[message]}'.format(ix=ix, quote=quote, ago=pdate))
        else:
            bot.say(
                '[{ix}][{quote[author]}, {quote[lastAuthor]} {ago}] {quote[message]}'.format(ix=ix, quote=quote,
                                                                                                    ago=pdate))


@commands('clear', 'close')
# @ratlib.sopel.filter_output
@parameterize('r*', '<client name or case number> [Rat that fired first limpet]')
@require_permission(Permissions.rat)
def cmd_clear(bot, trigger, rescue, *firstlimpet):
    """
    Mark a case as closed.
    Required parameters: client name or case number
    optional parameter: The rat that fired the first limpet
    aliases: clear, close
    """
    func_clear(bot, trigger, rescue, False, *firstlimpet)


def func_clear(bot, trigger, rescue, markingForDeletion=False, *firstlimpet):
    """
    Actual implementation for the clear
    """
    # print('[RatBoard] firstlimpet = ' + str(firstlimpet))
    if len(firstlimpet) > 1:
        raise UsageError()

    if not markingForDeletion and (not rescue.platform or rescue.platform == 'unknown'):
        bot.say('The case platform is unknown. Please set it with the corresponding command and try again.')
        return
    url = "https://fuelrats.com/paperwork/{rescue.id}/edit".format(
        rescue=rescue, apiurl=str(bot.config.ratbot.apiurl).strip('/'))
    try:
        url = bot.memory['ratbot']['shortener'].shorten(url)['shorturl']
    except:
        print('[RatBoard] Couldn\'t grab shortened URL for Paperwork. Ignoring, posting long link.')

    if len(firstlimpet) == 1:
        rat = getRatId(bot, firstlimpet[0], rescue.platform)['id']
        if rat != "0":
            rescue.firstLimpet = rat
            dt = datetime.date(2017, 4, 1)
            if datetime.date.today() == dt:
                bot.say(
                    'Your case got closed and you fired the First Limpet! Check if the paperwork is correct here: http://t.fuelr.at/a41',
                    firstlimpet[0])
            else:
                bot.say(
                'Your case got closed and you fired the First Limpet! Check if the paperwork is correct here: ' + url,
                firstlimpet[0])
            if rat not in rescue.rats:
                rescue.rats.update([rat])
        else:
            bot.reply('Couldn\'t find a Rat on ' + str(rescue.platform) + ' for ' + str(
                firstlimpet[0]) + ', sorry! Case not closed, try again!')
            return

    rescue.open = False
    rescue.active = False

    if (not markingForDeletion):
        bot.say(
            ("Case {rescue.client_name} cleared!" + ((" " + str(getRatName(bot, rescue.firstLimpet)[
                                                                    0]) + ", d") if rescue.firstLimpet else " D") + "o the Paperwork: {url}").format(
                rescue=rescue, url=url), '#ratchat')
    bot.say('Case {rescue.client_name} got cleared!'.format(rescue=rescue))
    rescue.board.remove(rescue)
    if not markingForDeletion:
        save_case_later(
            bot, rescue,
            "API is still not done with clearing case {!r}; continuing in background.".format(trigger.group(3))
        )


@commands('list')
@ratlib.sopel.filter_output
@parameterize('w*', usage="[-iru@] ['pc', 'ps', 'xb']")
@require_permission(Permissions.rat)
def cmd_list(bot, trigger, *remainder):
    """
    List the currently active, open cases.

    Supported parameters:
        -i: Also show inactive (but still open) cases.
        -r: Show assigned rats
        -u: Show only cases with no assigned rats
        -@: Show full case IDs.  (LONG)

    """
    count = 0
    plats = []
    params = ['']
    tmp = ''

    for word in remainder:
        for char in list(word):
            if char in ['@', 'i', 'r', 'u']:
                params[0] = '-'
                params.append(char)
            elif char == '-': None #ignore '-'
            else:
                plats.append(char)

    for i in range(1, len(list(params[0]))):
        if list(params[0])[i] == '-':
            list(params[0]).pop(i)
            i -= 1

    tmpStr = ''
    for element in plats:
        tmpStr += element

    offset = 0
    tmp = list(tmpStr)
    for x in range(0, len(tmpStr)):
        if (x + offset) % 3 != 0 or x == 0: continue
        if tmp[x + offset] != ' ':
            tmp.insert(x + offset - 1, ' ')
            offset += 1
    tmpStr = ''.join(tmp)
    plats = tmpStr.split(' ')
    
    for x in plats:
        if x not in ['pc', 'ps', 'xb', '',  '-']:
            raise UsageError()
    
    showpc = 'pc' in plats
    showps = 'ps' in plats
    showxb = 'xb' in plats
    showAllPlats = True if not (showpc or showps or showxb) else False

    showPlats = []
    if showpc: showPlats.append("pc")
    if showps: showPlats.append("ps")
    if showxb: showPlats.append("xb")

    if not params or params[0] != '-':
        params = '-'

    showids = '@' in params and bot.config.ratbot.apiurl is not None
    show_inactive = 'i' in params
    showassigned = 'r' in params
    unassigned = 'u' in params
    maxcount = 2 if showassigned else (3 if showids else 6)
    attr = 'client_name'

    board = bot.memory['ratbot']['board']

    def _keyfn(rescue):
        return not rescue.codeRed, rescue.boardindex

    with board:
        actives = list(filter(lambda x: x.active, board.rescues))
        actives.sort(key=_keyfn)
        inactives = list(filter(lambda x: not x.active, board.rescues))
        inactives.sort(key=_keyfn)

    output = []
    for name, cases, expand in (('active', actives, True), ('inactive', inactives, show_inactive)):
        if not cases:
            output.append("No {name} cases".format(name=name))
            continue
        num = len(cases)
        s = 's' if num != 1 else ''
        tmpOutput = []
        tmpOutput.append("{num} {name} case{s}".format(num=num, name=name, s=s))
        if expand:
            # list all rescues and replace rescues with IGNOREME if only unassigned rescues should be shown and the
            # rescues have more than 0 assigned rats
            # will also replace every rescue that should not be shown based on the supplied platform
            # FIXME: should be done easier to read, but it should work. I wanted to stick to the old way it was
            # implemented.
            templist = \
                (format_rescue(bot, rescue, attr, showassigned, showids, hideboardindexes=False, showmarkedfordeletionreason=False)
                 if (not unassigned or len(rescue.rats) == 0 and len(rescue.unidentifiedRats) == 0)
                    and (showAllPlats or rescue.platform in showPlats) else 'IGNOREME'
                 for rescue in cases)
            formatlist = []
            for formatted in templist:
                if formatted != 'IGNOREME':
                    formatlist.append(formatted)
                    tmpOutput.append(formatted)
            num = len(formatlist) if len(formatlist) != 0 else "No"
            s = 's' if num != 1 else ''
            tmpOutput[0] = "{num} {name} case{s}".format(num=num, name=name, s=s)
        else:
            tempcount = 0
            tempcount +=  (1 if (showAllPlats or rescue.platform in showPlats) else 0 for rescue in cases)
            num = tempcount if tempcount != 0 else "No"
            s = 's' if num != 1 else ''
            tmpOutput[0] = "{num} {name} case{s}".format(num=num, name=name, s=s)
        output.append(tmpOutput)
    for part in output:
        totalCount = 0
        length = len(part)
        currCount = 0
        currString = ""
        if part.__class__ is str:
            b = part
            part = []
            part.append(b)
            length = 1
        for case in part:
            if currCount == 0:
                currString = case
            else:
                currString = currString + ", "+case
            currCount += 1
            totalCount += 1
            if currCount == maxcount or totalCount == length:
                bot.say(currString)
                currCount = 0


def format_rescue(bot, rescue, attr='client_name', showassigned=False, showids=True, hideboardindexes=True,
                  showmarkedfordeletionreason=True):
    cr = color("(CR)", colors.RED) if rescue.codeRed else ''
    id = ""
    cl = (('Operation ' + rescue.title) if rescue.title else (getattr(rescue, attr)))
    platform = rescue.platform
    assignedratsstring = ''
    if platform == None:
        platform = ''
    if platform == 'xb':
        platform = color(' XB', colors.GREEN)
    if platform == 'pc':
        platform = ' PC'
    if platform == 'ps':
        platform = color(' PS4', colors.LIGHT_BLUE)
    if showassigned:
        assignedratsstring = ' Assigned Rats: '
        for rat in rescue.rats:
            assignedratsstring += getRatName(bot, rat)[0] + ', '
        for rat in rescue.unidentifiedRats:
            assignedratsstring += rat + ', '
        if len(rescue.rats) > 0 or len(rescue.rats) > 0:
            assignedratsstring = assignedratsstring.strip(', ')
            assignedratsstring = " " + assignedratsstring
    bi = rescue.boardindex if not hideboardindexes else ''
    if showids:
        id = "@" + (rescue.id if rescue.id is not None else "none")
    reason = ''
    reporter = ''
    if showmarkedfordeletionreason and rescue.data is not None:
        reason = ', Reason: ' + str(rescue.data['markedForDeletion']['reason'])
        reporter = ', reporter: ' + str(rescue.data['markedForDeletion']['reporter'])
    return "[{boardindex}{id}]{client}{cr}{platform}{assignedrats}{reason}{reporter}".format(
        boardindex=bi,
        id=id,
        client=cl,
        cr=cr,
        platform=platform,
        assignedrats=assignedratsstring,
        reason=reason,
        reporter=reporter
    )


@commands('grab')
@ratlib.sopel.filter_output
@parameterize('w', usage='<client name>')
@require_permission(Permissions.rat)
def cmd_grab(bot, trigger, client):
    """
    Grab the last line the client said and add it to the case.
    required parameters: client name.
    """
    client = Identifier(client)
    lock, log = bot.memory['ratbot']['log']
    with lock:
        line = log.get(client)

    if line is None:
        # If this were to happen, somebody is trying to break the system.
        # After all, why make a case with no information?
        return bot.reply(client + ' has not spoken recently.')

    result = append_quotes(bot, client, line, create=True, author=client)
    if not result:
        return bot.reply("Case was not found and could not be created.")

    if result.created:
        with bot.memory['ratbot']['board'].change(result.rescue):
            result.rescue.data.update(defaultdata)
            result.rescue.data.update({'IRCNick': result.rescue.client, "boardIndex": int(result.rescue.boardindex)})

    bot.say(
        "{rescue.client_name}'s case {verb} with: \"{line}\"  ({tags})"
            .format(
            rescue=result.rescue, verb='opened' if result.created else 'updated', tags=", ".join(result.tags()),
            line=result.added_lines[0]
        )
    )
    save_case_later(
        bot, result.rescue,
        "API is still not done with grab for {rescue.client_name}; continuing in background.".format(
            rescue=result.rescue), forceFull=True
    )


@commands('inject')
@parameterize("wT", usage="<client or case number> <text to add>")
@require_permission(Permissions.rat)
# Using this to prevent cases from created if they are not found, therefor created, but no line to add was specified.
def cmd_inject(bot, trigger, case, line):
    """
    Inject a custom line of text into the client's case.
    required parameters: Client name or case number, quote to add.
    """
    func_inject(bot, trigger)

@ratlib.sopel.filter_output
@parameterize('FT', usage='<client or case number> <text to add>')
def func_inject(bot, trigger, find_result, line):
    """
    Inject a custom line of text into the client's case.
    required parameters: Client name or case number, quote to add.
    """
    # Can probably be removed, keeping it with the above comment so s/o else later understands it.
    if not line:
        raise UsageError()
    result = append_quotes(bot, find_result, line, create=True, author=trigger.nick)
    if result.created:
        with bot.memory['ratbot']['board'].change(result.rescue):
            result.rescue.data.update(defaultdata)
            result.rescue.data.update({'IRCNick': result.rescue.client, "boardIndex": int(result.rescue.boardindex)})
        save_case_later(bot, result.rescue, forceFull=True)

    bot.say(
        "{rescue.client_name}'s case {verb} with: \"{line}\"  ({tags})"
            .format(
            rescue=result.rescue, verb='opened' if result.created else 'updated', tags=", ".join(result.tags()),
            line=result.added_lines[0]
        )
    )

    save_case_later(
        bot, result.rescue,
        "API is still not done with inject for {rescue.client_name}; continuing in background.".format(
            rescue=result.rescue)
    )


@commands('sub')
@ratlib.sopel.filter_output
@parameterize('rwT', usage='<client or case number> <line number> [<replacement text>]')
@require_permission(Permissions.rat)
def cmd_sub(bot, trigger, rescue, lineno, line=None):
    """
    Substitute or delete an existing line of text to the client's case.  Does not perform autocorrection/autodetection
    required parameters: client name or case number, line number
    optional parameter: replacement text
    """
    try:
        lineno = int(lineno)
    except ValueError:
        return bot.reply('Line number must be an integer.')
    if lineno < 0:
        return bot.reply('Line number cannot be negative.')
    if lineno >= len(rescue.quotes):
        return bot.reply('Case only has {} line(s)'.format(len(rescue.quotes)))
    if not line:
        rescue.quotes.pop(lineno)
        bot.say("Deleted line {}".format(lineno))
    else:
        rescue.quotes[lineno] = {"message":line, "updatedAt":datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
                                 "createdAt":rescue.quotes[lineno]["createdAt"],
                                 "author":rescue.quotes[lineno]["author"], "lastAuthor":trigger.nick}
        bot.say("Updated line {}".format(lineno))

    save_case_later(bot, rescue)


@commands('active', 'activate', 'inactive', 'deactivate')
@ratlib.sopel.filter_output
@requires_case
@require_permission(Permissions.rat)
def cmd_active(bot, trigger, rescue):
    """
    Toggle a case active/inactive
    required parameters: client name.
    aliases: active, activate, inactive, deactivate
    """
    rescue.active = not rescue.active
    bot.say(
        "{rescue.client_name}'s case is now {active}"
            .format(rescue=rescue, active=bold('active') if rescue.active else 'inactive')
    )
    save_case_later(bot, rescue)


@commands('epic')
@ratlib.sopel.filter_output
@requires_case
@require_permission(Permissions.rat)
def cmd_epic(bot, trigger, rescue):
    """
    Toggle a case epic/not epic
    CURRENTLY DISABLED
    required parameters: client name.
    """
    bot.say("Sorry, this command is currently disabled as the epic status is ignored by the API.")
    return
    rescue.epic = not rescue.epic
    bot.say(
        "{rescue.client_name}'s case is now {epic}"
            .format(rescue=rescue, epic=bold('epic') if rescue.epic else 'not as epic')
    )
    save_case_later(bot, rescue)


@commands('assign', 'add', 'go', 'gocr')
@ratlib.sopel.filter_output
@parameterize('r+', usage="<client or case number> <rats...>")
@require_permission(Permissions.rat)
def cmd_assign(bot, trigger, rescue, *rats):
    """
    Assign rats to a client's case.
    required parameters: client name, rat name(s).
    aliases: assign, add, go
    """
    ratlist = []
    ratids = []
    for rat in rats:
        if rescue.platform == None:
            i = getRatId(bot, rat)
        else:
            i = getRatId(bot, rat, platform=rescue.platform)
        # Check if id returned is an id, decide for unidentified rats or rats.
        # print("i is " + str(i))
        idstr = str(i['id'])
        # IRCNick may (but shouldn't be) be None - convert to string so it does not error out
        if rat.lower() == str(rescue.data['IRCNick']).lower():  # sanity check
            bot.reply("Unable to assign a client to their own case.")
            return
        elif idstr != '0' and idstr != 'None':
            # print('[RatBoard] id was not 0.')
            rescue.rats.update([i['id']])
            ratlist.append(i['name'])
            ratids.append(i['id'])
        else:
            # print('[RatBoard] id was 0')
            bot.reply('Be advised: ' + rat + ' does not have a registered Rat for the case\'s platform!')
            rescue.unidentifiedRats.update([rat])
            ratlist.append(removeTags(rat))
    # print("Trying to say: " + ("{client_name}: Please add the following rat(s) to your friends list: {rats}"
    #        .format(rescue=rescue, rats=", ".join(ratlist), client_name=rescue.client_name.replace(' ', '_'))))
    if rescue.codeRed:
        bot.say("{client_name}: Please REMAIN at the main menu and add the following rat(s) to your friends list: {rats}"
                .format(client_name=rescue.data["IRCNick"], rats = ", ".join(ratlist)))
    else:
        bot.say(
            "{client_name}: Please add the following rat(s) to your friends list: {rats}"
                .format(rescue=rescue, rats=", ".join(ratlist), client_name=rescue.data["IRCNick"])
        )
    if len(ratids) > 0:
        callapi(bot, 'PUT', '/rescues/assign/' + str(rescue.id), data={'data':ratids}, triggernick=str(trigger.nick))
    save_case_later(bot, rescue)


@commands('ratid', 'id')
@ratlib.sopel.filter_output
@parameterize('w', usage='<ratname>')
@require_permission(Permissions.rat)
def cmd_ratid(bot, trigger, rat, platform=None):
    """
    Get a rats' id from the api
    required parameters: rat name
    aliases: ratid, id
    """
    if platform:
        bot.say("searching for rat '{}' on {}".format(rat,platform))
    else:
        bot.say("searching for rat {}".format(rat))
    id = getRatId(bot=bot, ratname=rat, platform=platform)
    bot.say('Rat id for ' + str(id['name']) + ' is ' + str(id['id']))


@commands('unassign', 'deassign', 'rm', 'remove', 'standdown')
@ratlib.sopel.filter_output
@parameterize('r+', usage="<client or case number> <rats...>")
@require_permission(Permissions.rat)
def cmd_unassign(bot, trigger, rescue, *rats):
    """
    Remove rats from a client's case.
    required parameters: client name or board index and the rats to unassign
    aliases: unassign, deassign, rm, remove, standdown
    """
    rescue.unidentifiedRats -= set(rats)
    ratids = []
    for rat in rats:
        rat = str(getRatId(bot, rat)['id'])

        if rat != '0':
            ratids.append(rat)
            rescue.rats -= {rat}

    callapi(bot, 'PUT', '/rescues/unassign/' + str(rescue.id), data={'data':ratids}, triggernick=str(trigger.nick))

    bot.say(
        "Removed from {name}'s case: {rats}"
            .format(name=rescue.data["IRCNick"], rats=", ".join(rats))
    )
    save_case_later(bot, rescue)


@commands('codered', 'casered', 'cr')
@ratlib.sopel.filter_output
@requires_case
@require_permission(Permissions.rat)
def cmd_codered(bot, trigger, rescue):
    """
    Toggles the code red status of a case.
    A code red is when the client is so low on fuel that their life support
    system has failed, indicated by the infamous blue timer on their HUD.
    aliases: codered, casered, cr
    """
    rescue.codeRed = not rescue.codeRed
    if rescue.codeRed:
        bot.say('CODE RED! {name} is on emergency oxygen.'.format(name=rescue.data["IRCNick"]), transform=False)
        if rescue.rats:
            ratnames = []
            for rat in rescue.rats:
                ratnames.append(getRatName(bot, rat)[0])
            bot.say(", ".join(ratnames) + ": This is your case!")
    else:
        bot.say('{name}\'s case is no longer CR'.format(name=rescue.data["IRCNick"]))

    save_case_later(bot, rescue)


@requires_case
@require_permission(Permissions.rat)
def cmd_platform(bot, trigger, rescue, platform=None):
    """
    Sets a case platform to PC or xbox.
    """
    rescue.platform = platform
    bot.say(
        "{name}'s platform set to {platform}".format(name=rescue.data["IRCNick"], platform=('PS4' if rescue.platform.upper() == 'PS' else rescue.platform.upper()))
    )
    save_case_later(
        bot, rescue,
        (
            "API is still not done updating platform for {name}; continuing in background."
                .format(name=rescue.data["IRCNick"])
        )
    )


# For some reason, this can't be tricked with functools.partial.
@commands('pc')
@require_permission(Permissions.rat)
def cmd_platform_pc(bot, trigger):
    """Sets a case's platform to PC"""
    return cmd_platform(bot, trigger, platform='pc')


@commands('xb(?:ox)?(?:-?(?:1|one))?')
@require_permission(Permissions.rat)
def cmd_platform_xb(bot, trigger):
    """Sets a case's platform to XB"""
    return cmd_platform(bot, trigger, platform='xb')

@commands('ps(?:4)?')
@require_permission(Permissions.rat)
def cmd_plaform_ps(bot, trigger):
    """Sets a case's platform to PlayStation"""
    if bot.config.ratboard.enable_ps_support == 'True' or False:
        return cmd_platform(bot, trigger, platform='ps')
    else:
        bot.say("PlayStation Support not yet enabled.")

@commands('sys', 'system', 'loc', 'location')
@ratlib.sopel.filter_output
@parameterize('rT', usage='<client or case number> <system name>')
@ratlib.db.with_session
@require_permission(Permissions.rat)
def cmd_system(bot, trigger, rescue, system, db=None):
    """
    Sets a case's system.
    required parameters: Client name or case number, system location
    aliases: sys, system, loc, location
    """
    if not system:
        raise UsageError()

    # Try to find the system in EDDB.
    fmt = "Location of {name} set to {rescue.system}"

    result = db.query(Starsystem).filter(Starsystem.name_lower == system.lower()).first()
    if result:
        system = result.name
    else:
        fmt += "  (not in EDDB)"
    rescue.system = system
    bot.say(fmt.format(rescue=rescue, name=rescue.data["IRCNick"]))
    save_case_later(
        bot, rescue,
        (
            "API is still not done updating system for {name}; continuing in background."
                .format(name=rescue.data["IRCNick"])
        )
    )


@commands('cmdr', 'commander')
@ratlib.sopel.filter_output
@parameterize('rT', usage='<client or case number> <commander namename>')
@ratlib.db.with_session
@require_permission(Permissions.rat)
def cmd_commander(bot, trigger, rescue, commander, db=None):
    """
    Sets a client's in-game commander name.
    required parameters: Client name or case number, commander name
    aliases: cmdr, commander
    """
    if not commander:
        raise UsageError()

    with rescue.change():
        rescue.client = commander

    bot.say("Client for case {rescue.boardindex} is now CMDR {commander}".format(rescue=rescue, commander=commander))
    save_case_later(
        bot, rescue,
        (
            "API is still not done updating system for {name}; continuing in background."
                .format(name=rescue.data["IRCNick"])
        )
    )

_ratmama_regex = re.compile(r"""
    (?x)
    # The above makes whitespace and comments in the pattern ignored.
    # Saved at https://regex101.com/r/jhKtQD/1
    \s*                                  # Handle any possible leading whitespace
    Incoming\s+Client:\s*   # Match "Incoming Client" prefix
    # Wrap the entirety of rest of the pattern in a group to make it easier to echo the entire thing
    (?P<all>
    (?P<cmdr>[^@#\d\s].*?)               # Match CDMR name.  Don't allow leading digits or @/#, as it breaks things
                                         # (and probably isn't a legal name anyways).  Dispatch can manually handle
                                         # those cases if it turns out to be a thing, or someone can fix Ratmama too.
    \s+-\s+                              #  -
    System:\s*(?P<system>.*?)            # Match system name
    (?:\s[sS][yY][sS][tT][eE][mM]|)      # Strip " system" from end, if present (case insensitive)
    \s+-\s+                              #  -
    Platform:\s*(?P<platform>\w+)        # Match platform (currently can't contain spaces)
    \s+-\s+                              #  -
    O2:\s*(?P<o2>.+?)                    # Match oxygen status
    \s+-\s+                              #  -
    Language:\s*
    (?P<full_language>                   # Match full language text (for regenerating the line)
    (?P<language>.+?)\s*                 # Match language name. (currently unused)
    \(                                   # The "(" of "(en-US)"
    (?P<language_code>.+?)               # "en"
    (?:                                  # Optional group
        -(?P<language_country>.+)        # "-", "US" (currently unused)
    )?                                   # Actually make the group optional.
    \)                                   # The ")" of "(en-US)"
    )                                    # End of full language text
    (?:                                  # Possibly match IRC nickname
    \s+-\s+                              #  -
    IRC\s+Nickname:\s*(?P<nick>[^\s]+)   # IRC nickname
    )?                                   # ... emphasis on "Possibly"
    )                                    # End of the main capture group
    \s*                                  # Handle any possible trailing whitespace
    $                                    # End of pattern
""")

@rule('Incoming Client:.* - O2:.*')
@require_chanmsg
@with_session
def ratmama_parse(bot, trigger, db):
    """
    Parse Incoming KiwiIRC clients that are announced by RatMama

    :param trigger: line that triggered this
    """
    # print('[RatBoard] triggered ratmama_parse')
    # print('[RatBoard] line: ' + line)

    if Identifier(trigger.nick) in ('Ratmama[BOT]', 'Dewin'):
        match = _ratmama_regex.fullmatch(trigger.group())
        if not match:
            return

        # Save time of new Ratsignal
        bot.memory['ratbot']['lastsignal'] = datetime.datetime.utcnow()

        # Parse results
        fields = match.groupdict()
        fields["ratsignal"] = bot.config.ratboard.signal.upper()

        # Create format string
        fmt = (
            "{ratsignal} - CMDR {cmdr} - Reported System: {system} - Platform: {platform} - O2: {o2}"
            " - Language: {full_language}"
        )
        if fields["nick"]:
            fmt += " - IRC Nickname: {nick}"

        # Create plaintext versions of newline
        newline = fmt.format(**fields)
        result = append_quotes(bot, fields["cmdr"], fmt.format(**fields), create=True, author="Mecha")
        case = result.rescue  # Reduce typing later.

        # Update the case
        if not case.system:
            case.system = fields["system"]
        # using lower() as systems may be saved in different capitalisation than the client entered it
        if case.system.lower() != fields["system"].lower():
            bot.say("Caution - Reported and autodetected System do not match! Dispatch, check it is set to the correct one! (" + case.system + " vs " + fields["system"] + ")")
        case.codeRed = (fields["o2"] != "OK")
        if fields["platform"] == "PS4":
            case.platform = "ps"
        else:
            case.platform = fields["platform"].lower()
        if not fields["nick"]:
            fields["nick"] = fields["cmdr"]
        with bot.memory['ratbot']['board'].change(case):
            case.data.update(defaultdata)
            case.data.update({
                'langID': fields["language_code"],
                'IRCNick': fields["nick"],
                "boardIndex": int(case.boardindex)
            })



        save_case_later(bot, case, forceFull=True)
        if result.created:
            # Add IRC formatting to fields, then substitute them into to output to the channel
            # (But only if this is a new case, because we aren't using it otherwise)
            system = db.query(Starsystem).filter(Starsystem.name_lower == fields["system"].lower()).first()

            if case.codeRed:
                fields["o2"] = bold(color(fields["o2"], colors.RED))

            if case.platform == 'xb':
                fields["platform"] = color(fields["platform"], colors.GREEN)
            elif case.platform == 'ps':
                fields["platform"] = color("PS4", colors.LIGHT_BLUE)
            fields["platform"] = bold(fields["platform"])
            fields["system"] = bold(fields["system"])
            fields["cmdr"] = bold(fields["cmdr"])

            if system:
                nearest, distance = system.nearest_landmark(db, with_distance=True)
                if nearest and nearest.name_lower != system.name_lower:
                    fields["system"] += " ({:.2f} LY from {})".format(distance, nearest.name)
            else:
                fields["system"] += " (not in EDDB)"

            bot.say((fmt + " (Case #{boardindex})").format(boardindex=case.boardindex, **fields))
            if case.codeRed:
                prepcrstring = getFact(bot, factname='prepcr', lang=fields["language_code"])
                bot.say(
                    fields["nick"] + " " + prepcrstring)
            bot.memory['ratbot']['lastsignal'] = datetime.datetime.utcnow()
            global preptimer
            try:
                preptimer.cancel()
            except:
                pass
            if not case.codeRed:
                preptimer = Timer(180, prepexpired, args=[bot])
                preptimer.start()
        else:
            bot.say("{0.client} has reconnected to the IRC! (Case #{0.boardindex})".format(case))


@commands('closed', 'recent')
@require_permission(Permissions.rat)
def cmd_closed(bot, trigger):
    '''
    Lists the 5 last closed rescues to give the ability to reopen them
    aliases: closed, recent
    '''
    try:
        result = callapi(bot=bot, uri='/rescues?status=closed&limit=5&order=-updatedAt', method='GET',
                         triggernick=str(trigger.nick))
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'])
        data = result['data']
        rescue0 = getDummyRescue()
        rescue1 = getDummyRescue()
        rescue2 = getDummyRescue()
        rescue3 = getDummyRescue()
        rescue4 = getDummyRescue()

        try:
            rescue0 = data[0]
            rescue1 = data[1]
            rescue2 = data[2]
            rescue3 = data[3]
            rescue4 = data[4]
        except:
            bot.say('Couldn\'t grab 5 cases. The output might look weird.')
        bot.say(
            "These are the newest closed rescues: 1: Client {0[client]} at {0[system]} - id: {0[id]} 2: Client {1[client]} at {1[system]} - id: {1[id]}".format(rescue0, rescue1))
        bot.say(
            "3: Client {0[client]} at {0[system]} - id: {0[id]} 4: Client {1[client]} at {1[system]} - id: {1[id]}".format(
                rescue2, rescue3))
        bot.say(
            "5: Client {0[client]} at {0[system]} - id: {0[id]}".format(rescue4))

    except ratlib.api.http.APIError:
        bot.reply('Got an APIError, sorry. Try again later!')


def getDummyRescue():
    return {'attributes':{'client': 'dummy', 'system': 'dummy'}, 'id': 'dummy'}


@commands('reopen')
@parameterize('+', usage="<id>")
@require_permission(Permissions.overseer)
def cmd_reopen(bot, trigger, id):
    """
    Reopens a case by its full database ID
    """
    try:
        result = callapi(bot, 'PUT', data={'status': 'open'}, uri='/rescues/' + str(id), triggernick=str(trigger.nick))
        refresh_cases(bot, force=True)
        updateBoardIndexes(bot)
        bot.say('Reopened case. Cases refreshed, care for your case numbers!')
    except ratlib.api.http.APIError:
        # print('[RatBoard] apierror.')
        bot.reply('id ' + str(id) + ' does not exist or other API Error.')


@commands('delete')
@require_permission(Permissions.overseer)
@parameterize('+', usage='<id/list>')
def cmd_delete(bot, trigger, id):
    """
    Parameters:
        id - Delete a rescue by its full database ID
        list - Shows the Marked for Deletion List™
    """
    func_delete(bot, trigger, id)


def func_delete(bot, trigger, id):
    if 'list' != id:
        try:
            result = callapi(bot, 'DELETE', uri='/rescues/' + str(id), triggernick=str(trigger.nick))
            # print('[RatBoard] ' + str(result))
        except ratlib.api.http.APIError as ex:
            bot.reply('Case with id ' + str(id) + ' does not exist or other APIError.')
            print('[RatBoard] ' + str(ex))
            return
        bot.say('Deleted case with id ' + str(id) + ' - THIS IS NOT REVERTIBLE!')
    else:
        result = callapi(bot, 'GET', uri='/rescues?data={"markedForDeletion":{"marked":true}}',
                         triggernick=str(trigger.nick))
        caselist = []
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'])
        for case in result['data']:
            rescue = Rescue.load(case)
            caselist.append(format_rescue(bot, rescue))
        if (len(caselist) == 0):
            bot.say('No Cases marked for deletion!')
        else:
            bot.say('Cases marked for deletion:')
        for case in caselist:
            bot.say(str(case))


@commands('mdlist')
@require_permission(Permissions.overseer)
def cmd_mdlist(bot, trigger):
    """
    Shows the Marked for Deletion List™
    """
    func_delete(bot, trigger, 'list')


@commands('quoteid')
@ratlib.sopel.filter_output
@parameterize('+', usage='<id>')
@require_permission(Permissions.overseer)
def cmd_quoteid(bot, trigger, id):
    """
    Quotes a case by its database id
    """
    try:
        result = callapi(bot, method='GET', uri='/rescues/' + str(id), triggernick=str(trigger.nick))
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'])
        rescue = Rescue.load(result['data'][0])
        func_quote(bot, trigger, rescue, showboardindex=False)
    except:
        bot.reply('Couldn\'t find a case with id ' + str(id) + ' or other APIError')


@commands('title')
@parameterize('rw*', '<case # or client name> <title to set>')
@require_permission(Permissions.rat)
def cmd_title(bot, trigger, rescue, *title):
    """
    Sets the Operation Title of a rescue.
    required parameters: boardindex or clientname and Title to set
    """
    comptitle = ""
    for s in title:
        comptitle = comptitle + s
    rescue.title = comptitle
    bot.say('Set ' + rescue.data["IRCNick"] + '\'s case Title to "' + comptitle + '"')
    save_case_later(bot, rescue)


@commands('pwl', 'pwlink', 'paperwork', 'paperworklink')
@parameterize(params='r', usage='<client name or case number>')
# @require_permission(Permissions.rat)
@require_permission(Permissions.rat)
def cmd_pwl(bot, trigger, case):
    """
    Creates the link for the paperwork of any currently open rescue and shortens it (if the shortener module is active)
    required parameters: client name or board index
    aliases: pwl, pwlink, paperwork, paperworklink
    """
    url = "https://fuelrats.com/paperwork/{rescue.id}/edit".format(
        rescue=case, apiurl=str(bot.config.ratbot.apiurl).strip('/'))
    shortened = url
    if bot.memory['ratbot']['shortener']:
        shortened = bot.memory['ratbot']['shortener'].shorten(url)['shorturl']
    bot.reply('Here you go: ' + str(shortened))


# This should go elsewhere, but here for now.
@commands('version', 'uptime')
def cmd_version(bot, trigger):
    """
    Shows the bot's current version and Uptime
    aliases: version, uptime
    """
    started = bot.memory['ratbot']['stats']['started']
    bot.say(
        "Version {version}, up {delta} since {time}"
            .format(
            version=bot.memory['ratbot']['version'],
            delta=timeutil.format_timedelta(datetime.datetime.now(tz=started.tzinfo) - started),
            time=timeutil.format_timestamp(started)
        )
    )


@commands('flush', 'resetnames', 'rn', 'flushnames', 'fn')
# @require_permission(Permissions.rat)
@require_permission(Permissions.rat)
def cmd_flush(bot, trigger):
    """
    Resets the cached RatNames. Helps with Bugged rat names on !assign
    aliases: flush, resetnames, rn, flushnames, fn
    """
    flushNames()
    bot.say('Cached names flushed!')


@commands('host')
def cmd_host(bot, trigger):
    """
    Shows you your current host to verify priviliges
    """
    bot.reply('Your Host is: ' + str(trigger.host))


@commands('refreshboard', 'resetboard', 'forceresetboard', 'forcerefreshboard', 'frb', 'fbr', 'boardrefresh')
# @require_overseer()
@require_permission(Permissions.overseer)
def cmd_forceRefreshBoard(bot, trigger):
    """
    Forcefully resets the Board. This removes all "Ghost" Cases as they are grabbed from the API. Boardindexes will get changed by , but updated on the Dispatch Board afterwards.
    aliases: refreshboard, resetboard, forceresetboard, forcerefreshboard, br, fbr, boardrefresh (kinda went overBOARD with that. hah. puns.)
    """
    bot.say(
        'Force refreshing the Board. This removes all cases and grabs them from the API.')
    refresh_cases(bot, force=True)
    bot.say('Reload done, trying to update indexes...')
    updateBoardIndexes(bot)
    bot.say("All Indexes updated, force refresh complete!")


def getFact(bot, factname, lang='en'):
    try:
        return ratlib.db.Fact.find(db=bot.memory['ratbot']['db'](), name=factname, lang=lang).message
    except AttributeError:
        return ratlib.db.Fact.find(db=bot.memory['ratbot']['db'](), name=factname, lang='en').message


def rescueMarkedForDeletion(rescue):
    return rescue.data.get('markedForDeletion').get('marked')


def getDeletionReason(rescue):
    return rescue.data.get('markedForDeletion').get('reason')


def getDeletionReporter(rescue):
    return rescue.data.get('markedForDeletion').get('reporter')


def setRescueMarkedForDeletion(bot, rescue, marked, reason='None.', reporter='Noone.'):
    rescue.data.update({'markedForDeletion': {'marked': marked, 'reason': str(reason), 'reporter': str(reporter)}})
    save_case_later(bot, rescue, forceFull=True)


@commands('md', 'mdadd', 'markfordeletion', 'markfordelete')
@parameterize('rt', '<client/board #> <reason>')
# @require_permission(Permissions.rat)
@require_permission(Permissions.rat)
def cmd_md(bot, trigger, case, reason):
    """
    Closes a rescue and adds it to the Marked for Deletion List™
    required parameters: client name or board index and the reason it should be deleted
    aliases: md, mdadd, markfordeletion, markfordelete
    """
    bot.say('Closing case of ' + str(case.data["IRCNick"]) + ' (Case #' + str(
        case.id) + ') and adding it to the Marked for Deletion List™.')
    func_clear(bot, trigger, case, markingForDeletion=True)
    setRescueMarkedForDeletion(bot=bot, rescue=case, marked=True, reason=reason, reporter=trigger.nick)
    try:
        preptimer.cancel()
    except:
        pass

@commands('mdremove', 'mdr', 'mdd', 'mddeny')
@parameterize('w', '<id>')
# @require_overseer()
@require_permission(Permissions.overseer)
def cmd_mdremove(bot, trigger, caseid):
    """
    Remove a case from the Marked for Deletion List™ (Does NOT reopen the case!)
    required parameter: database id
    aliases: mdremove, mdr, mdd, mddeny
    """
    try:
        result = callapi(bot, method='GET', uri='/rescues/' + str(caseid), triggernick=str(trigger.nick))
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'])
        rescue = Rescue.load(result['data'][0])
        setRescueMarkedForDeletion(bot, rescue, marked=False)
        bot.say('Successfully removed ' + str(rescue.data["IRCNick"]) + '\'s case from the Marked for Deletion List™.')
    except:
        bot.reply('Couldn\'t find a case with id ' + str(caseid) + ' or other APIError')


@commands('ircnick', 'nick', 'nickname')
@parameterize('rt')
# @require_permission(Permissions.rat)
@require_permission(Permissions.rat)
def cmd_nick(bot, trigger, case, newnick):
    """
    Sets a new nickname for this case.
    """
    with bot.memory['ratbot']['board'].change(case):
        case.data.update({'IRCNick': newnick})
    save_case_later(bot, case, forceFull=True)
    bot.say('Set Nick to ' + str(newnick))

@commands('quiet', 'lastsignal', 'last')
# @require_permission(Permissions.rat)
@require_permission(Permissions.rat)
def cmd_quiet(bot, trigger):
    """
    Tells the time since the last Signal
    """
    if bot.memory['ratbot']['lastsignal'] is None:
        bot.say("Sadly, I don't remember when we had the last signal. Maybe it was 42 seconds ago?")
        return
    tdelta = datetime.datetime.utcnow() - bot.memory['ratbot']['lastsignal']
    seconds = tdelta.seconds % 60
    minutes = int(tdelta.seconds / 60)
    hashours = False
    hours = 0
    if minutes >= 60:
        hours = int(minutes/60)
        minutes = minutes % 60
        hashours = True
    ret = str(minutes) + " minutes and " + str(seconds) + " seconds"
    if hashours:
        ret = str(hours) + " hours, " + ret

    if hours > 12:
        bot.say("Wow, the last signal was so long ago... " + ret + " ago to be exact! Orangey approves!")
        return
    bot.say("It has been quiet for " + ret + "! Time to summon a case?")




def pretty_date(time=False):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc
    SOURCE: https://stackoverflow.com/questions/1551382/user-friendly-time-format-in-python
    """
    from datetime import datetime
    now = datetime.utcnow()
    if type(time) is int:
        diff = now - datetime.fromtimestamp(time)
    elif isinstance(time,datetime):
        diff = now - time
    else:
        diff = now - now
    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ''

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return str(int(second_diff)) + " seconds ago"
        if second_diff < 120:
            return "a minute ago"
        if second_diff < 3600:
            return str(int(second_diff / 60)) + " minutes ago"
        if second_diff < 7200:
            return "an hour ago"
        if second_diff < 86400:
            return str(int(second_diff / 3600)) + " hours ago"
    if day_diff == 1:
        return "Yesterday"
    if day_diff < 7:
        return str(int(day_diff)) + " days ago"
    if day_diff < 31:
        return str(int(day_diff / 7)) + " weeks ago"
    if day_diff < 365:
        return str(int(day_diff / 30)) + " months ago"
    return str(int(day_diff / 365)) + " years ago"

def prepexpired(bot):
    bot.say("Caution: The most recent client has NOT been !prep-ed!")

@commands('paperworkneeded', 'needspaperwork', 'npw', 'pwn')
# @require_permission(Permissions.rat)
@require_permission(Permissions.rat)
def cmd_pwn(bot, trigger):
    '''
    Lists all cases with incomplete paperwork
    aliases: paperworkneeded, needspaperwork, npw, pwn
    '''
    try:
        result = callapi(bot=bot, uri='/rescues?outcome=null&order=-updatedAt', method='GET',
                         triggernick=str(trigger.nick))
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'])
        data = result['data']
        if len(data) > 0:
            bot.say("Incomplete Paperwork Cases:")
        else:
            bot.say("All Paperwork done!")
        for case in data:
            url = "https://fuelrats.com/paperwork/{id}/edit".format(id=case['id'])
            try:
                url = bot.memory['ratbot']['shortener'].shorten(url)['shorturl']
            except:
                print('[RatBoard] Couldn\'t grab shortened URL for Paperwork. Ignoring, posting long link.')
            ratname = getRatName(bot, ratid=case['firstLimpet'])[0]
            bot.say("Rescue of {case[client]} at {case[system]} by {ratname} - link: {url}".format(case=case, ratname=ratname, url=url))

    except ratlib.api.http.APIError:
        bot.reply('Got an APIError, sorry. Try again later!')


@commands('invalid', 'invalidate')
@parameterize('w', '<id>')
# @require_overseer()
@require_permission(Permissions.overseer)
def cmd_invalid(bot, trigger, caseid):
    """
    Remove a case from the Marked for Deletion List™ (Does NOT reopen the case!)
    required parameter: database id
    aliases: mdremove, mdr, mdd, mddeny
    """
    try:
        result = callapi(bot, method='GET', uri='/rescues/' + str(caseid), triggernick=str(trigger.nick))
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        case = result["data"][0]
        findresult = bot.memory['ratbot']['board'].find(case["attributes"]["client"], create=False)
        if findresult != (None, None):
            bot.reply("A Case for that rescues client is still on the board. Please !close or !md it first")
            return

        case["attributes"]["data"]["markedForDeletion"]["marked"] = False
        case["attributes"]["outcome"] = "invalid"
        result = callapi(bot, method='PUT', uri='/rescues/' + str(caseid), triggernick=str(trigger.nick), data=case["attributes"])
        bot.reply("Set Case to invalid outcome and removed it from the Marked For Deletion List™")

    except:
        bot.reply('Couldn\'t find a case with id ' + str(caseid) + ' or other APIError')
