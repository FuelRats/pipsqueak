"""
Sopel-specific ratlib constructs.

:author: Daniel Grace
"""
from sopel.config import StaticSection, types
from sopel.tools import SopelMemory
import os.path

__all__ = ['RatbotConfigurationSection', 'configure', 'setup', 'makepath']

class RatbotConfigurationSection(StaticSection):
    apiurl = types.ValidatedAttribute('apiurl', str, default='http://api.fuelrats.com/')
    workdir = types.FilenameAttribute('workdir', directory=True, default='run')

def configure(config):
    """
    Handles common configuration for all rat-* modules.  Call in each module's configure() hook.

    :param config: Configuration to update.
    """
    if hasattr(config, 'ratbot'):
        return

    config.define_section('ratbot', RatbotConfigurationSection)
    config.ratbot.configure_setting('apiurl', "The URL of the API to talk to.")
    config.ratbot.configure_setting('workdir', "Work directory for dynamically modified data.")

def setup(bot):
    """
    Common setup for all rat-* modules.  Call in each module's setup() hook.

    :param bot: Sopel bot being setup.
    """
    if 'ratbot' not in bot.memory:
        bot.memory['ratbot'] = SopelMemory()

def makepath(dir, filename):
    """
    If filename is an absolute path, returns it unmodified.

    Otherwise, returns os.path.join(dir, file)

    :param dir: Directory
    :param filename: Filename
    """
    return filename if os.path.isabs(filename) else os.path.join(dir, filename)
