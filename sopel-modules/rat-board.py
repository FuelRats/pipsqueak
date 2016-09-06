# coding: utf8
"""
rat-board.py - Fuel Rats Cases module.
Copyright 2015, Dimitri "Tyrope" Molenaars <tyrope@tyrope.nl>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

# Python core imports
import re
import datetime
import collections
import itertools
import warnings
import functools
import json

import sys
import contextlib

# Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
import ratlib.sopel

import threading
import operator
import concurrent.futures

from ratlib import friendly_timedelta, format_timestamp

from ratlib.autocorrect import correct
from ratlib.starsystem import scan_for_systems
from ratlib.api.props import *
from ratlib.api.names import *
from ratlib.sopel import UsageError
from sopel.config.types import StaticSection, ValidatedAttribute
import ratlib.api.http
import ratlib.db

urljoin = ratlib.api.http.urljoin

target_case_max = 9  # Target highest boardindex to assign
HISTORY_MAX = 10000  # Max number of nicks we'll remember history for at once.


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
    if not hasattr(bot.config, 'ratboard') or not bot.config.ratboard.signal:
        signal = 'ratsignal'
    else:
        signal = bot.config.ratboard.signal

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
        print("Logging API calls to " + bot.config.ratbot.apidebug)

    try:
        refresh_cases(bot)
    except ratlib.api.http.BadResponseError as ex:
        warnings.warn("Failed to perform initial sync against the API")
        import traceback
        traceback.print_exc()


def callapi(bot, method, uri, data=None, _fn=ratlib.api.http.call, statuses=None):
    '''
    Calls the API with the given method endpoint and data.
    :param bot: bot to pull config from and log error messages to irc
    :param method: GET PUT POST etc.
    :param uri: the endpoint to use, ex /rats
    :param data: body for request
    :param _fn: http call function to use
    :return: the data dict the api call returned.
    '''
    uri = urljoin(bot.config.ratbot.apiurl, uri)
    # print('will call uri '+uri)
    headers = {"Authorization": "Bearer " + bot.config.ratbot.apitoken}
    print('Calling api with data: ' + str(data))
    with bot.memory['ratbot']['apilock']:
        return _fn(method, uri, data, log=bot.memory['ratbot']['apilog'], headers=headers, statuses=statuses)


FindRescueResult = collections.namedtuple('FindRescueResult', ['rescue', 'created'])


class RescueBoard:
    """
    Manages all attached cases, including API calls.
    """
    INDEX_TYPES = {
        'boardindex': operator.attrgetter('boardindex'),
        'id': operator.attrgetter('id'),
        'client': lambda x: None if not x.client else x.client.lower(),

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
                    self.bot.say(
                        'WARNING! A CASE HAS BEEN ASSIGNED AN INDEX THAT WAS ALREADY USED! REPORT THIS TO MARENTHYU AND ASK AN OVERSEER (OR HIGHER) TO DO !fbr - THANK YOU! (affected case #: ' + str(
                            key) + ')')
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
            return None, None

        if search[0] == '@':
            rescue = self.indexes['id'].get(search[1:], None),
            return FindRescueResult(rescue, False if rescue else None)

        rescue = self.indexes['client'].get(search.lower())
        if not rescue:
            spacesearch = search.replace('_', ' ')
            rescue = self.indexes['client'].get(spacesearch.lower())

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
    platform = TrackedProperty(default='unknown')
    open = TypeCoercedProperty(default=True, coerce=bool)
    epic = TypeCoercedProperty(default=False, coerce=bool)
    codeRed = TypeCoercedProperty(default=False, coerce=bool)
    client = TrackedProperty(default='<unknown client>')
    system = TrackedProperty(default=None)
    successful = TypeCoercedProperty(default=True, coerce=bool)
    title = TrackedProperty(default=None)
    firstLimpet = TrackedProperty(default='')
    data = TrackedProperty(
        default={'langID': 'unknown', 'markedForDeletion': {'marked': False, 'reason': 'None.', 'reporter': 'Noone.'}})

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
        uri += "?open=true"

    # Exceptions here are the responsibility of the caller.
    result = callapi(bot, 'GET', uri)
    # print('refreshing returned '+str(result))
    if force:
        bot.memory['ratbot']['board'] = RescueBoard()
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
        result = callapi(bot, method, uri, data=data)
        rescue.commit()
        if 'data' not in result or not result['data']:
            raise RuntimeError("API response returned unusable data.")
        with rescue.change():
            rescue.refresh(result['data'])
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
    # Let's not. print('Saving Case: '+str(json.dumps(rescue, default=lambda o: o.__dict__)))
    future = save_case(bot, rescue, forceFull)
    if not future:
        return None
    try:
        future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as ex:
        print('Timeout Error: ' + str(ex))
        if message is None:
            message = (
                "API is still not done updating case for {{rescue.client_name}}; continuing in background."
                    .format(rescue=rescue)
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
            rv.append(self.detected_platform.upper())
        if self.detected_system:
            rv.append(self.detected_system)
        if self.autocorrected:
            rv.append("Autocorrected")
        return rv


def append_quotes(bot, search, lines, autocorrect=True, create=True, detect_platform=True, detect_system=True):
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
    if detect_platform and rv.rescue.platform == 'unknown':
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
        if len(platforms) == 1:
            rv.rescue.platform = platforms.pop()
            rv.detected_platform = rv.rescue.platform

    rv.rescue.quotes.extend(rv.added_lines)
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
    result = append_quotes(bot, trigger.nick, [line], create=True)
    bot.say(
        "Received RATSIGNAL from {nick}.  Calling all available rats!  ({tags})"
            .format(nick=trigger.nick, tags=", ".join(result.tags()) if result else "<unknown>")
    )
    bot.reply('Are you on emergency oxygen? (Blue timer on the right of the front view)')
    save_case_later(
        bot, result.rescue,
        "API is still not done with ratsignal from {nick}; continuing in background.".format(nick=trigger.nick)
    )


@commands('quote')
@ratlib.sopel.filter_output
@requires_case
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_quote(bot, trigger, rescue):
    """
    Recites all known information for the specified rescue
    Required parameters: client name or case number.
    """
    func_quote(bot, trigger, rescue)

def func_quote(bot, trigger, rescue, showboardindex=True):
    tags = ['unknown platform' if not rescue.platform or rescue.platform == 'unknown' else rescue.platform.upper()]

    if rescue.epic:
        tags.append("epic")
    if rescue.codeRed:
        tags.append(bold(color('CR', colors.RED)))

    fmt = (
              ("Rescue Operation {title}: " if rescue.title else "") +
              "{client}'s case "+"#{index}" if showboardindex else ""+" at {system} ({tags}) opened {opened} ({opened_ago}),"
              " updated {updated} ({updated_ago})"
          ) + ("  @{id}" if bot.config.ratbot.apiurl else "")

    bot.say(fmt.format(
        client=rescue.client_name, index=rescue.boardindex, tags=", ".join(tags),
        opened=format_timestamp(rescue.createdAt) if rescue.createdAt else '<unknown>',
        updated=format_timestamp(rescue.updatedAt) if rescue.updatedAt else '<unknown>',
        opened_ago=friendly_timedelta(rescue.createdAt) if rescue.createdAt else '???',
        updated_ago=friendly_timedelta(rescue.updatedAt) if rescue.updatedAt else '???',
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
        bot.say('[{ix}]{quote}'.format(ix=ix, quote=quote))


@commands('clear', 'close')
# @ratlib.sopel.filter_output
@parameterize('r*', '<client name or case number> [Rat that fired first limpet]')
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_clear(bot, trigger, rescue, *firstlimpet):
    """
    Mark a case as closed.
    Required parameters: client name or case number and optionally a rat who fired the first limpet.
    """
    func_clear(bot, trigger, rescue, False, *firstlimpet)


def func_clear(bot, trigger, rescue, markingForDeletion=False, *firstlimpet):
    """
    Actual implementation for the clear
    """
    print('firstlimpet = ' + str(firstlimpet))
    if len(firstlimpet) > 1:
        raise UsageError()

    url = "{apiurl}/rescues/edit/{rescue.id}".format(
        rescue=rescue, apiurl=str(bot.config.ratbot.apiurl).strip('/'))
    try:
        url = bot.memory['ratbot']['shortener'].shortenUrl(bot, url)['shorturl']
    except:
        print('Couldn\'t grab shortened URL for Paperwork. Ignoring, posting long link.')

    if len(firstlimpet) == 1:
        rat = getRatId(bot, firstlimpet[0], rescue.platform)['id']
        if rat != "0":
            rescue.firstLimpet = rat
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

    bot.say(
        ("Case {rescue.client_name} cleared!" + ((" " + str(getRatName(bot, rescue.firstLimpet)[
                                                                0]) + ", d") if rescue.firstLimpet else " D") + "o the Paperwork: {url}").format(
            rescue=rescue, url=url), '#ratchat')
    bot.reply('Case {rescue.client_name} got cleared!'.format(rescue=rescue))
    rescue.board.remove(rescue)
    if not markingForDeletion:
        save_case_later(
            bot, rescue,
            "API is still not done with clearing case {!r}; continuing in background.".format(trigger.group(3))
        )


@commands('list')
@ratlib.sopel.filter_output
@parameterize('w', usage="[-iru@]")
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_list(bot, trigger, params=''):
    """
    List the currently active, open cases.

    Supported parameters:
        -i: Also show inactive (but still open) cases.
        -r: Show assigned rats
        -u: Show only cases with no assigned rats
        -@: Show full case IDs.  (LONG)

    """
    if not params or params[0] != '-':
        params = '-'

    showids = '@' in params and bot.config.ratbot.apiurl is not None
    show_inactive = 'i' in params
    showassigned = 'r' in params
    unassigned = 'u' in params
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
        t = "{num} {name} case{s}".format(num=num, name=name, s=s)
        if expand:
            # list all rescues and replace rescues with IGNOREME if only unassigned rescues should be shown and the rescues have more than 0 assigned rats
            # FIXME: should be done easier to read, but it should work. I wanted to stick to the old way it was implemented.
            templist = (format_rescue(bot, rescue, attr, showassigned, showids, hideboardindexes=False, showmarkedfordeletionreason=False) if (
                (not unassigned) or (len(rescue.rats) == 0 and len(rescue.unidentifiedRats) == 0)) else 'IGNOREME' for
                        rescue in cases)
            formatlist = []
            for formatted in templist:
                if formatted != 'IGNOREME':
                    formatlist.append(formatted)
            if len(formatlist) > 0:
                t += ": " + ", ".join(formatlist)
        output.append(t)
    bot.say("; ".join(output))


def format_rescue(bot, rescue, attr='client_name', showassigned=False, showids=True, hideboardindexes=True, showmarkedfordeletionreason=True):
    cr = color("(CR)", colors.RED) if rescue.codeRed else ''
    id = ""
    cl = (('Operation ' + rescue.title) if rescue.title else (getattr(rescue, attr)))
    platform = rescue.platform
    assignedratsstring = ''
    if platform == 'unknown':
        platform = ''
    if platform == 'xb':
        platform = color(' XB', colors.GREEN)
    if platform == 'pc':
        platform = ' PC'
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
        reason = ', Reason: '+str(rescue.data['markedForDeletion']['reason'])
        reporter = ', reporter: '+str(rescue.data['markedForDeletion']['reporter'])
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
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
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

    result = append_quotes(bot, client, line, create=True)
    if not result:
        return bot.reply("Case was not found and could not be created.")

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
            rescue=result.rescue)
    )


@commands('inject')
@ratlib.sopel.filter_output
@parameterize('FT', usage='<client or case number> <text to add>')
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_inject(bot, trigger, find_result, line):
    """
    Inject a custom line of text into the client's case.
    required parameters: Client name or case number, quote to add.
    """
    if not line:
        raise UsageError()
    result = append_quotes(bot, find_result, line, create=True)

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
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
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
        rescue.quotes[lineno] = line
        bot.say("Updated line {}".format(lineno))

    save_case_later(bot, rescue)


@commands('active', 'activate', 'inactive', 'deactivate')
@ratlib.sopel.filter_output
@requires_case
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_active(bot, trigger, rescue):
    """
    Toggle a case active/inactive
    required parameters: client name.
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
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_epic(bot, trigger, rescue):
    """
    Toggle a case epic/not epic
    required parameters: client name.
    """
    rescue.epic = not rescue.epic
    bot.say(
        "{rescue.client_name}'s case is now {epic}"
            .format(rescue=rescue, epic=bold('epic') if rescue.epic else 'not as epic')
    )
    save_case_later(bot, rescue)


@commands('assign', 'add', 'go')
@ratlib.sopel.filter_output
@parameterize('r+', usage="<client or case number> <rats...>")
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_assign(bot, trigger, rescue, *rats):
    """
    Assign rats to a client's case.
    required parameters: client name, rat name(s).
    """
    ratlist = []
    for rat in rats:
        if rescue.platform == 'unknown':
            i = getRatId(bot, rat)
        else:
            i = getRatId(bot, rat, platform=rescue.platform)
        # Check if id returned is an id, decide for unidentified rats or rats.
        idstr = str(i['id'])
        if idstr != '0':
            # print('id was not 0.')
            rescue.rats.update([i['id']])
            ratlist.append(getRatName(bot, i['id'])[0])
        else:
            # print('id was 0')
            bot.reply('Be advised: ' + rat + ' does not have a registered Rat for the case\'s platform!')
            rescue.unidentifiedRats.update([rat])
            ratlist.append(removeTags(rat))

    bot.say(
        "{client_name}: Please add the following rat(s) to your friends list: {rats}"
            .format(rescue=rescue, rats=", ".join(ratlist), client_name=rescue.client_name.replace(' ', '_'))
    )
    save_case_later(bot, rescue)


@commands('ratid', 'id')
@ratlib.sopel.filter_output
@parameterize('w', usage='<ratname>')
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_ratid(bot, trigger, rat):
    """
    Get a rats' id from the api
    required parameters: rat name
    """
    id = getRatId(bot=bot, ratname=rat)
    bot.say('Rat id for ' + str(id['name']) + ' is ' + str(id['id']))


@commands('unassign', 'deassign', 'rm', 'remove', 'standdown')
@ratlib.sopel.filter_output
@parameterize('r+', usage="<client or case number> <rats...>")
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_unassign(bot, trigger, rescue, *rats):
    """
    Remove rats from a client's case.
    """
    rescue.unidentifiedRats -= set(rats)
    for rat in rats:
        rat = str(getRatId(bot, rat)['id'])
        if rat != '0':
            rescue.rats -= {rat}
            callapi(bot, 'PUT', '/rescues/' + str(rescue.id) + '/unassign/' + rat)

    bot.say(
        "Removed from {rescue.client_name}'s case: {rats}"
            .format(rescue=rescue, rats=", ".join(rats))
    )
    save_case_later(bot, rescue)


@commands('codered', 'casered', 'cr')
@ratlib.sopel.filter_output
@requires_case
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_codered(bot, trigger, rescue):
    """
    Toggles the code red status of a case.
    A code red is when the client is so low on fuel that their life support
    system has failed, indicated by the infamous blue timer on their HUD.
    """
    rescue.codeRed = not rescue.codeRed
    if rescue.codeRed:
        bot.say('CODE RED! {rescue.client_name} is on emergency oxygen.'.format(rescue=rescue), transform=False)
        if rescue.rats:
            ratnames = []
            for rat in rescue.rats:
                ratnames.append(getRatName(bot, rat)[0])
            bot.say(", ".join(ratnames) + ": This is your case!")
    else:
        bot.say('{rescue.client_name}\'s case is no longer CR.'.format(rescue=rescue))

    save_case_later(bot, rescue)


@requires_case
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_platform(bot, trigger, rescue, platform=None):
    """
    Sets a case platform to PC or xbox.
    """
    rescue.platform = platform
    bot.reply(
        "{rescue.client_name}'s platform set to {platform}".format(rescue=rescue, platform=rescue.platform.upper())
    )
    save_case_later(
        bot, rescue,
        (
            "API is still not done updating platform for {rescue.client_name}; continuing in background."
                .format(rescue=rescue)
        )
    )


# For some reason, this can't be tricked with functools.partial.
@commands('pc')
def cmd_platform_pc(bot, trigger):
    """Sets a case's platform to PC"""
    return cmd_platform(bot, trigger, platform='pc')


@commands('xb(?:ox)?(?:-?(?:1|one))?')
def cmd_platform_xb(bot, trigger):
    """Sets a case's platform to XB"""
    return cmd_platform(bot, trigger, platform='xb')


@commands('sys', 'system', 'loc', 'location')
@ratlib.sopel.filter_output
@parameterize('rT', usage='<client or case number> <system name>')
@ratlib.db.with_session
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_system(bot, trigger, rescue, system, db=None):
    """
    Sets a case's system.
    required parameters: Client name or case number, system location
    """
    if not system:
        raise UsageError()

    # Try to find the system in EDSM.
    fmt = "Location of {rescue.client_name} set to {rescue.system}"

    result = db.query(ratlib.db.Starsystem).filter(ratlib.db.Starsystem.name_lower == system.lower()).first()
    if result:
        system = result.name
    else:
        fmt += "  (not in EDSM)"
    rescue.system = system
    bot.reply(fmt.format(rescue=rescue))
    save_case_later(
        bot, rescue,
        (
            "API is still not done updating system for {rescue.client_name}; continuing in background."
                .format(rescue=rescue)
        )
    )


@commands('cmdr', 'commander')
@ratlib.sopel.filter_output
@parameterize('rT', usage='<client or case number> <commander namename>')
@ratlib.db.with_session
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_commander(bot, trigger, rescue, commander, db=None):
    """
    Sets a client's in-game commander name.
    required parameters: Client name or case number, commander name
    """
    if not commander:
        raise UsageError()

    with rescue.change():
        rescue.client = commander

    bot.say("Client for case {rescue.boardindex} is now CMDR {commander}".format(rescue=rescue, commander=commander))
    save_case_later(
        bot, rescue,
        (
            "API is still not done updating system for {rescue.client_name}; continuing in background."
                .format(rescue=rescue)
        )
    )


@rule('Incoming Client:.* - O2:.*')
def ratmama_parse(bot, trigger):
    '''
    Parse Incoming Kiwiirc clients (gets announced by ratmama)
    :param trigger: line that triggered this
    '''
    print('triggered ratmama_parse')
    line = trigger.group()
    print('line: ' + line)
    if Identifier(trigger.nick) == 'Ratmama[BOT]':
        import re
        newline = line.replace("Incoming Client:", bot.config.ratboard.signal.upper() + " - CMDR")
        cmdr = re.search('(?<=CMDR ).*?(?= - )', newline).group()
        system = re.search('(?<=System: ).*?(?= - )', newline).group()
        platform = re.search('(?<=Platform: ).*?(?= - )', newline).group()
        crstring = re.search('(?<=O2: ).*?(?= -)', newline).group()
        langID = re.search('Language: .* \((.*)\)', newline).group(1)
        try:
            langID = langID[0:langID.index('-')]
        except ValueError:
            pass
        result = append_quotes(bot, cmdr, [newline], create=True)
        cr = False
        if crstring != "OK":
            cr = True
            newline = newline.replace(crstring, color('\u0002' + crstring + '\u000F', colors.RED))
        if platform == 'XB':
            newline = newline.replace(platform, color(platform, colors.GREEN))
        if not result.rescue.system:
            result.rescue.system = system
        newline = newline.replace(cmdr, '\u0002' + cmdr + '\u000F').replace(system,
                                                                            '\u0002' + result.rescue.system + '\u000F').replace(
            platform, '\u0002' + platform + '\u000F')
        result.rescue.codeRed = cr
        result.rescue.platform = platform.lower()
        result.rescue.data.update({'langID': langID})
        save_case_later(bot, result.rescue)
        if result.created:
            bot.say(newline + ' (Case #' + str(result.rescue.boardindex) + ')')
            if cr:
                prepcrstring = getFact(bot, factname='prepcr', lang=langID)
                bot.say(
                    result.rescue.client + " " + prepcrstring)
        else:
            bot.say('Client ' + result.rescue.client + ' has reconnected to the IRC!')


@commands('closed', 'recent')
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_closed(bot, trigger):
    '''
    Lists the 5 last closed rescues to give the ability to reopen them
    '''
    try:
        result = callapi(bot=bot, uri='/rescues?open=false&limit=5&order=updatedAt&direction=DESC', method='GET')
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
            bot.reply('Couldn\'t grab 5 cases. The output might look weird.')
        bot.reply(
            "These are the newest closed rescues: 1: Client " + str(rescue0['client']) + " at " + str(
                rescue0['system']) + " - id: " + str(rescue0['id']) + " 2: Client " + str(
                rescue1['client']) + " at " + str(rescue1['system']) + " - id: " + str(rescue1['id']))
        bot.reply("3: Client " + str(rescue2['client']) + " at " + str(rescue2['system']) + " - id: " + str(
            rescue2['id']) + " 4: Client " + str(rescue3['client']) + " at " + str(rescue3['system']) + " - id: " + str(
            rescue3['id']))
        bot.reply(
            "5: Client " + str(rescue4['client']) + " at " + str(rescue4['system']) + " - id: " + str(rescue4['id']))

    except ratlib.api.http.APIError:
        bot.reply('Got an APIError, sorry. Try again later!')


def getDummyRescue():
    return {'client': 'dummy', 'system': 'dummy', 'id': 'dummy'}


@commands('reopen')
@parameterize('+', usage="<id>")
@require_overseer('Sorry pal, you\'re not an overseer or higher!')
def cmd_reopen(bot, trigger, id):
    access = ratlib.sopel.best_channel_mode(bot, trigger.nick)
    print('access: ' + str(access))
    if access:
        print('got access - id: ' + str(id))
        bot.reply('got access - id: ' + str(id))
        try:
            result = callapi(bot, 'PUT', data={'open': True}, uri='/rescues/' + str(id))
            refresh_cases(bot, force=True)
            bot.reply('Reopened case. Cases refreshed, care for your case numbers!')
        except ratlib.api.http.APIError:
            # print('apierror.')
            bot.reply('id ' + str(id) + ' does not exist or other API Error.')
    else:
        print('no access')
        bot.reply('Not authorized.')


@commands('delete')
@require_overseer(message='Sorry pal, you\'re not an overseer or higher!')
@parameterize('+', usage='<id/list>')
def cmd_delete(bot, trigger, id):
    if 'list'!=id:
        try:
           result = callapi(bot, 'DELETE', uri='/rescues/' + str(id))
            # print(result)
        except ratlib.api.http.APIError as ex:
            bot.reply('case with id ' + str(id) + ' does not exist or other APIError.')
            print(ex)
            return
        bot.reply('deleted case with id ' + str(id) + ' - THIS IS NOT REVERTABLE!')
    else:
        result = callapi(bot, 'GET', uri='/rescues?data={"markedForDeletion":{"marked":true}}')
        caselist = []
        for case in result['data']:
            rescue = Rescue.load(case)
            caselist.append(format_rescue(bot, rescue))
        if (len(caselist)==0):
            bot.reply('No Cases marked for deletion!')
        else:
            bot.reply('Cases marked for deletion:')
        for case in caselist:
            bot.reply(str(case))

@commands('quoteid')
@require_overseer(message='Sorry pal, you\'re not an overseer or higher!')
@parameterize('+', usage='<id>')
def cmd_quoteid(bot, trigger, id):
    try:
        result = callapi(bot, method='GET', uri='/rescues/'+str(id))
        rescue = Rescue.load(result['data'])
        func_quote(bot, trigger, rescue, showboardindex=False)
    except:
        bot.reply('Couldn\'t find a case with id '+str(id)+' or other APIError')


@commands('title')
@parameterize('rw*', '<case # or client name> <title to set>')
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_title(bot, trigger, rescue, *title):
    comptitle = ""
    for s in title:
        comptitle = comptitle + s
    rescue.title = comptitle
    bot.reply('Set ' + rescue.client + '\'s case Title to "' + comptitle + '"')
    save_case_later(bot, rescue)


@commands('pwl', 'pwlink', 'paperwork', 'paperworklink')
@parameterize(params='r', usage='<client name or case number>')
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_pwl(bot, trigger, case):
    url = "{apiurl}/rescues/edit/{rescue.id}".format(
        rescue=case, apiurl=str(bot.config.ratbot.apiurl).strip('/'))
    shortened = url
    if bot.memory['ratbot']['shortener']:
        shortened = bot.memory['ratbot']['shortener'].shortenUrl(bot, url)['shorturl']
    bot.reply('Here you go: ' + str(shortened))


# This should go elsewhere, but here for now.
@commands('version', 'uptime')
def cmd_version(bot, trigger):
    from ratlib import format_timedelta, format_timestamp
    started = bot.memory['ratbot']['stats']['started']
    bot.say(
        "Version {version}, up {delta} since {time}"
            .format(
            version=bot.memory['ratbot']['version'],
            delta=format_timedelta(datetime.datetime.now(tz=started.tzinfo) - started),
            time=format_timestamp(started)
        )
    )


@commands('flush', 'resetnames', 'rn', 'flushnames', 'fn')
@require_rat('Sorry, you need to be a registered and drilled rat to access this command.')
def cmd_flush(bot, trigger):
    flushNames()
    bot.reply('Cached names flushed!')


@commands('host')
def cmd_host(bot, trigger):
    bot.reply('Your Host is: ' + str(trigger.host))


@commands('refreshboard', 'resetboard', 'forceresetboard', 'forcerefreshboard', 'frb', 'fbr', 'boardrefresh')
@require_overseer('Sorry, but you need to be a registered Overseer or higher to access this command.')
def cmd_forceRefreshBoard(bot, trigger):
    bot.reply(
        'Force refreshing the Board. This removes all cases and grabs them from the API. DISPATCH, be advised: Case numbers may be changed!')
    refresh_cases(bot, force=True)
    bot.reply('Force refresh done.')


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


@commands('md','mdadd')
@parameterize('rt', '<client/board #> <reason>')
@require_rat('Sorry, but you need to be a registered and drilled Rat to use this command.')
def cmd_md(bot, trigger, case, reason):
    bot.reply('Closing case of ' + str(case.client) + ' (Case #' + str(case.id) + ') and marking it for deletion.')
    func_clear(bot, trigger, case, markingForDeletion=True)
    setRescueMarkedForDeletion(bot=bot, rescue=case, marked=True, reason=reason, reporter=trigger.nick)

@commands('mdremove','mdr','mdd','mddeny')
@parameterize('w', '<id>')
@require_overseer('Sorry, but you need to be an overseer or higher to use this command!')
def cmd_mdremove(bot, trigger, caseid):
    try:
        result = callapi(bot, method='GET', uri='/rescues/'+str(id))
        rescue = Rescue.load(result['data'])
        setRescueMarkedForDeletion(bot, rescue, marked=False)
        bot.reply('Successfully removed '+str(rescue.client)+'\'s case from the marked for deletion list.')
    except:
        bot.reply('Couldn\'t find a case with id '+str(id)+' or other APIError')
