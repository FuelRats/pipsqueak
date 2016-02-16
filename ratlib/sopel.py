"""
Sopel-specific ratlib constructs.

:author: Daniel Grace
"""
from sopel.config import StaticSection, types
from sopel.tools import SopelMemory
import os.path
import re
import ratlib.db
import ratlib.starsystem
__all__ = ['RatbotConfigurationSection', 'configure', 'setup', 'makepath']


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
    workdir = types.FilenameAttribute('workdir', directory=True, default='run')
    alembic = types.FilenameAttribute('alembic', directory=False, default='alembic.ini')
    debug_sql = BooleanAttribute('debug_sql', default=False)
    edsm_url = types.ValidatedAttribute('edsm_url', str, default="http://edsm.net/api-v1/systems?coords=1")
    edsm_maxage = types.ValidatedAttribute('edsm_maxage', int, default=60*60*12)
    edsm_db = types.ValidatedAttribute('edsm_db', str, default="systems.db")


def configure(config):
    """
    Handles common configuration for all rat-* modules.  Call in each module's configure() hook.

    :param config: Configuration to update.
    """
    if hasattr(config, 'ratbot'):
        return

    config.define_section('ratbot', RatbotConfigurationSection)
    config.ratbot.configure_setting('apiurl', "The URL of the API to talk to, or blank for offline mode.")
    config.ratbot.configure_setting('workdir', "Work directory for dynamically modified data.")
    config.ratbot.configure_setting('alembic', "Path to alembic.ini for database upgrades.")
    config.ratbot.configure_setting('debug_sql', "True if SQLAlchemy should echo query information.")
    config.ratbot.configure_setting('edsm_url', "URL for EDSM system data")
    config.ratbot.configure_setting('edsm_maxage', "Maximum age of EDSM system data in seconds")
    config.ratbot.configure_setting('edsm_db', "EDSM Database path (relative to workdir)")


def setup(bot):
    """
    Common setup for all rat-* modules.  Call in each module's setup() hook.

    :param bot: Sopel bot being setup.
    """
    if 'ratbot' not in bot.memory:
        bot.memory['ratbot'] = SopelMemory()
        ratlib.db.setup(bot)
        ratlib.starsystem.refresh_bloom(bot)


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
    def wrapper(bot, trigger):
        bot = OutputFilterWrapper(bot)
        return fn(bot, trigger)
    return wrapper
