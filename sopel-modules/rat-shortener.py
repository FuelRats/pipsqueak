# coding: utf-8
"""
Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
import requests
from sopel.config.types import StaticSection, ValidatedAttribute
from sopel.module import commands

import ratlib.sopel
from ratlib.api.http import ShortenerError, Shortener
from ratlib.sopel import parameterize


## Start Config Section ##
class ShortenerSection(StaticSection):
    shortenerurl = ValidatedAttribute('shortenerurl', str, default='1234')
    shortenertoken = ValidatedAttribute('shortenertoken', str, default='asdf')

def configure(config):
    ratlib.sopel.configure(config)
    config.define_section('shortener', ShortenerSection)
    config.socket.configure_setting(
        'shortenerurl',
        (
            "Shortener url"
        )
    )
    config.socket.configure_setting(
        'shortenertoken',
        (
            "Shortener Token"
        )
    )


def setup(bot):
    ratlib.sopel.setup(bot)
    if not hasattr(bot.config, 'shortener') or not bot.config.shortener.shortenerurl:
        bot.memory['ratbot']['shortener'] = None
    else:
        bot.memory['ratbot']['shortener'] = Shortener(
            url=bot.config.shortener.shortenerurl,
            token=bot.config.shortener.shortenertoken
        )


@commands('short','shortener','shorten')
@parameterize("ww","<url to shorten> [keyword]")
def shorten_cmd(bot, trigger, url, keyword=None):
    """
    Shortens a given URL
    required parameter: url to shorten
    optional parameter: keyword to append to the link (if it is not used already)
    aliases: short, shortener, shorten
    """
    shortener = bot.memory['ratbot']['shortener']
    if not shortener:
        bot.reply("The URL Shortener is not configured.  Unable to continue.")
        return

    try:
        result = shortener.shorten(url, keyword)
    except ShortenerError as ex:
        if ex.status == 'error:keyword':

            bot.reply('That keyword is already taken, sorry. Please try again with another one.')
        else:
            bot.reply(ex.message)
        return
    except (requests.HTTPError, ValueError) as ex:
        bot.reply(str(ex))
        return

    bot.reply("Your short URL is: {}".format(result['shorturl']))
