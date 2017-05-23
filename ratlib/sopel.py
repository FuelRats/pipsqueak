"""
Sopel-specific ratlib constructs.
Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

Copyright originally by Daniel "dewiniaid" Grace - https://github.com/dewiniaid (2016),
under the Eiffel Forum License, version 2

See LICENSE.md
"""
import datetime
import os.path
import re
import concurrent.futures
import functools

import ratlib.db
import ratlib.starsystem
from sopel.config import StaticSection, types
from sopel.tools import Identifier
from sopel.tools import SopelMemory
import inspect
import itertools


__all__ = [
    'BooleanAttribute', 'RatbotConfigurationSection', 'configure', 'setup',  # Sopel setup
    'best_channel_mode', 'OutputFilterWrapper', 'filter_output',  # IRC utility
    'makepath',  # General utility
    'cmd_version'
]


class BooleanAttribute(types.ChoiceAttribute):
    """
    Sopel somehow lacks a BooleanAttribute for configuration, so add our own.

    This is really just a bastardization of ChoiceAttribute with some coercion.
    """
    TRUTH = {
        '0': False, 'off': False, 'n': False, 'no': False, 'f': False, 'false': False,
        '1': True, 'on': True, 'y': True, 'yes': True, 't': True, 'true': True
    }

    def __init__(self, name, default=None):
        super().__init__(name, set(self.TRUTH.keys()), default=default)

    def parse(self, value):
        return self.TRUTH.get(super().parse(value.lower()), False)

    def serialize(self, value):
        return 'true' if value else 'false'


class RatbotConfigurationSection(StaticSection):
    apiurl = types.ValidatedAttribute('apiurl', str, default='')
    apitoken = types.ValidatedAttribute('apitoken', str, default='a')
    workdir = types.FilenameAttribute('workdir', directory=True, default='run')
    alembic = types.FilenameAttribute('alembic', directory=False, default='alembic.ini')
    debug_sql = BooleanAttribute('debug_sql', default=False)
    edsm_url = types.ValidatedAttribute('edsm_url', str, default="http://edsm.net/api-v1/systems?coords=1")
    edsm_maxage = types.ValidatedAttribute('edsm_maxage', int, default=12*60*60)
    edsm_autorefresh = types.ValidatedAttribute('edsm_autorefresh', int, default=4*60*60)
    edsm_db = types.ValidatedAttribute('edsm_db', str, default="systems.db")
    websocketurl = types.ValidatedAttribute('websocketurl', str, default='12')
    websocketport = types.ValidatedAttribute('websocketport', str, default='9000')
    shortenerurl = types.ValidatedAttribute('shortenerurl', str, default='')
    shortenertoken = types.ValidatedAttribute('shortenertoken', str, default='asdf')
    debug_channel = types.ValidatedAttribute('debug_channel', str, default='#mechadeploy')
    chunked_systems = BooleanAttribute('chunked_systems', default=True)  # Should be edsm_chunked_systems to fit others
    hastebin_url = types.ValidatedAttribute('hastebin_url', 'str', default="http://hastebin.com/")


def parameterize(params=None, usage=None, split=re.compile(r'\s+').split):
    """
    Returns a decorator that wraps a function into a structure that's easier to work with in commands.
    Works around some issues with Sopel's argument parsing and makes things much more convenient.

    :param params: Sequence of parameter types to parse.
    :param usage: Usage instructions displayed on error.  Automatically prepended by "Usage: <command name>"
    :param split: Function accepting (string, maxsplit) and returning the split string.

    The first two arguments to the wrapped function will be 'bot' and 'trigger' as normal.  Additional arguments will
    be added on based on splitting the trigger text into words and mapping them against the characters appearing in
    'params', as follows:

    'r': Parameter will be the case found by board.find(..., create=False).  Outputs an error message instead of
    calling the wrapped function if the case is not found.
    'R': As above, but the case can be created.
    'f': Like 'r', but the parameter will be the entire find() result tuple (rescue, created)
    'F': Like 'R', but the parameter will be the entire find() result tuple (rescue, created)
    'w': Parameter will be a single word.

    The following must be the final parameter if they are present:
    '*': Produces one parameter for each word remaining in the line.
    '+': Produces one parameter for each word remaining in the line, which must be at least one word.
    't': Parameter will be the entire remainder of the line.
    'T': Same as 't'.  Backwards compatibility.

    Any remaining 'words' in the argument will be passed to the wrapped function as additional parameters, as params
    contained enough 'w's to pad to the end of the argument list.

    If the resulting call does not match the function signature, usage instructions are displayed instead.  These usage
    instructions can also be displayed by raising UsageError() from the wrapped function.

    Optional parameters can be specified by making them optional on the function call itself (e.g. by assigning
    default values)
    """

    # Input validation
    maxsplit = 0
    if len(params):
        result = re.search(r'[tT*+]', params[:-1])
        if result:
            raise ValueError("{!r} must be the last parameter if it is present.", result.group(0))
        if params[-1] in 'tT':
            maxsplit = len(params) - 1
            if not maxsplit:
                # Only accepts one parameter and it's t/T?
                # We can't use the normal split mechanics, because they treat maxsplit=0 as unlimited splits.  So
                # replace the split function with a dummy instead.
                split = lambda x, maxsplit: [x] if x else []
        result = re.search(r'[^rRfFwtT*+]', params)
        if result:
            raise ValueError("{!r} is an unknown parameter type.".format(result.group(0)))

    def decorator(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(bot, trigger, *args, **kwargs):
            args = list(args)
            try:
                line = (trigger.group(2) or '').strip()
                if line:
                    for param, value in itertools.zip_longest(params, split(line, maxsplit), fillvalue=None):
                        if param == '+' and value is None:
                            raise UsageError()
                        if value is None:
                            break
                        if param and param in 'rRfF':
                            if value == bot.config.ratboard.signal:
                                return bot.reply('No, i am NOT adding a rescue to save '+value+'! Come on, this is dispatch rule #97 !')
                            value = bot.memory['ratbot']['board'].find(value, create=param in 'RF')
                            if not value[0]:
                                return bot.reply('Could not find a case with that name or number.')
                            if param in 'rR':
                                value = value[0]
                        # 'w' and 't'/'T' don't require any special handling, the split takes care of them.
                        # '*' doesn't require any special handling, it's just syntactic sugar.
                        # '+' already had its special handling done.
                        args.append(value)
                try:
                    bound = sig.bind(bot, trigger, *args, **kwargs)
                except TypeError:
                    raise UsageError()
                else:
                    return fn(*bound.args, **bound.kwargs)
            except UsageError:
                if usage is None:
                    return bot.reply("Incorrect format for command {}".format(trigger.group(1)))
                else:
                    return bot.reply("Usage: {} {}".format(trigger.group(1), usage))

        return wrapper

    return decorator


class UsageError(ValueError):
    pass

def best_channel_mode(bot, nickname):
    """
    Returns a combination of all channel privileges the given nickname has across all channel modes.
    :param bot:
    :param nickname:
    :return:
    """
    access = 0
    nickname = Identifier(nickname)
    for channel in bot.privileges.values():
        access |= channel.get(nickname, 0)
    return access


def configure(config):
    """
    Handles common configuration for all rat-* modules.  Call in each module's configure() hook.

    :param config: Configuration to update.
    """
    if hasattr(config, 'ratbot'):
        return

    config.define_section('ratbot', RatbotConfigurationSection)
    config.ratbot.configure_setting('apiurl', "The URL of the API to talk to, or blank for offline mode.")
    config.ratbot.configure_setting('apitoken', "The Oauth2 Token to authorize with the RatAPI.")
    config.ratbot.configure_setting('workdir', "Work directory for dynamically modified data.")
    config.ratbot.configure_setting('alembic', "Path to alembic.ini for database upgrades.")
    config.ratbot.configure_setting('debug_sql', "True if SQLAlchemy should echo query information.")
    config.ratbot.configure_setting('edsm_url', "URL for EDSM system data")
    config.ratbot.configure_setting('edsm_maxage', "Maximum age of EDSM system data in seconds")
    config.ratbot.configure_setting('edsm_autorefresh', "EDSM autorefresh frequency in seconds (0=disable)")
    config.ratbot.configure_setting('edsm_db', "EDSM Database path (relative to workdir)")
    config.ratbot.configure_setting('websocketurl', "The url for the Websocket to listen on")
    config.ratbot.configure_setting('websocketport', "The port for the Websocket to listen on")
    config.ratbot.configure_setting('shortenerurl', "The url for the shortener to listen on")
    config.ratbot.configure_setting('shortenertoken', "The Auth token the shortener should use")
    config.ratbot.configure_setting('debug_channel', "Channel for debug output")
    config.ratbot.configure_setting('hastebin_url', "Hastebin base URL")


def setup(bot):
    """
    Common setup for all rat-* modules.  Call in each module's setup() hook.

    :param bot: Sopel bot being setup.
    """
    if 'ratbot' in bot.memory:
        return

    # Attempt to determine some semblance of a version number.
    version = None
    try:
        if bot.config.ratbot.version_string:
            version = bot.config.ratbot.version_string
        elif bot.config.ratbot.version_file:
            with open(bot.config.ratbot.version_file, 'r') as f:
                version = f.readline().strip()
        else:
            import shlex
            import os.path
            import inspect
            import subprocess

            path = os.path.abspath(os.path.dirname(inspect.getframeinfo(inspect.currentframe()).filename))

            if bot.config.ratbot.version_cmd:
                cmd = bot.config.ratbot.version_cmd
            else:
                cmd = shlex.quote(bot.config.ratbot.version_git or 'git') + " describe --tags --long --always"
            output = subprocess.check_output(cmd, cwd=path, shell=True, universal_newlines=True)
            version = output.strip().split('\n')[0].strip()
    except Exception as ex:
        print("Failed to determine version: " + str(ex))
    if not version:
        version = '<unknown>'

    print("Starting Ratbot version " + version)

    bot.memory['ratbot'] = SopelMemory()
    bot.memory['ratbot']['executor'] = concurrent.futures.ThreadPoolExecutor(max_workers=10)  # Queue
    bot.memory['ratbot']['version'] = version
    bot.memory['ratbot']['stats'] = SopelMemory()
    bot.memory['ratbot']['stats']['started'] = datetime.datetime.now(tz=datetime.timezone.utc)
    ratlib.db.setup(bot)
    ratlib.starsystem.refresh_bloom(bot)
    ratlib.starsystem.refresh_database(
        bot,
        callback=lambda: print("EDSM database is out of date.  Starting background refresh."),
        background=True
    )

def shutdown(bot):
    print('shutting down?')

def makepath(dir, filename):
    """
    If filename is an absolute path, returns it unmodified.

    Otherwise, returns os.path.join(dir, file)

    :param dir: Directory
    :param filename: Filename
    """
    return filename if os.path.isabs(filename) else os.path.join(dir, filename)


class OutputFilterWrapper:
    """
    Wraps a SopelBot or SopelWrapper
    """
    # List of regex replacements to perform on output.
    replacements = [
        (re.compile(r'(r)at(signal)', re.IGNORECASE), r'\g<1>@\g<2>'),
        (re.compile('(cod|cas)e (r)e(d)', re.IGNORECASE), r'\g<1>3 \g<2>3\g<3>')
    ]
    _bot = None

    def __init__(self, bot):
        super().__setattr__('_bot', bot)

    def transform(self, message):
        for pattern, repl in self.replacements:
            message = pattern.sub(repl, message)
        return message

    def say(self, message, *args, transform=True, **kwargs):
        if transform:
            message = self.transform(message)
        self._bot.say(message, *args, **kwargs)

    def action(self, message, *args, transform=True, **kwargs):
        if transform:
            message = self.transform(message)
        self._bot.action(message, *args, **kwargs)

    def notice(self, message, *args, transform=True, **kwargs):
        if transform:
            message = self.transform(message)
        self._bot.notice(message, *args, **kwargs)

    def reply(self, message, *args, transform=True, **kwargs):
        if transform:
            message = self.transform(message)
        self._bot.reply(message, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._bot, name)

    def __setattr__(self, name, value):
        return setattr(self._bot, name, value)

    def __delattr__(self, name):
        return delattr(self._bot, name)

    def __dir__(self):
        return dir(self._bot) + ['transform', 'replacements']


def filter_output(fn):
    """
    Decorator: Wraps the passed Bot instance with a wrapper that filters output.

    In actuality, the wrapped function is normally invoked with a SopelWrapper, so we're wrapping the wrapper.  It's
    a wrap battle.

    :param fn: Function to wrap
    :return: Wrapped function
    """
    @functools.wraps(fn)
    def wrapper(bot, trigger):
        bot = OutputFilterWrapper(bot)
        return fn(bot, trigger)
    return wrapper
