# coding: utf-8
# Python imports
import sys
from threading import Thread
import threading
import json
from ratlib.api.http import callshortener


# Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
import ratlib.sopel
from sopel.config.types import StaticSection, ValidatedAttribute

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
    bot.memory['ratbot']['shortener'] = Shortener()

    if not hasattr(bot.config, 'socket') or not bot.config.socket.websocketurl:
        shortenerurl = '123'
        shortenertoken = 'asdf'
    else:
        shortenerurl = bot.config.socket.shortenerurl
        shortenertoken = bot.config.socket.shortenertoken

class Shortener:
    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def __init__(self):
        self._lock = threading.RLock()
        # print("Init for shortener called!")

    def shortenUrl(self, bot, url, keyword=None):
        result = callshortener(method='GET', uri=(
        bot.config.shortener.shortenerurl + "?signature=" + bot.config.shortener.shortenertoken + "&action=shorturl&format=json"+(('&keyword='+keyword) if keyword is not None else '')+"&url=" + url))
        return result


def shortenUrl(bot, url, keyword=None):
    result = callshortener(method='GET', uri=(
        bot.config.shortener.shortenerurl + "?signature=" + bot.config.shortener.shortenertoken + "&action=shorturl&format=json" + (
        ('&keyword=' + keyword) if keyword is not None else '') + "&url=" + url))
    return result

@commands('short','shortener','shorten')
@parameterize("w*","<url to shorten> [keyword]")
def shorten_cmd(bot, trigger, url, *keywords):
    if len(keywords) > 0:
        keyword = keywords[0]
    else:
        keyword=None
    shortened = shortenUrl(bot, url, keyword)
    try:
        if keyword != None and shortened['code']=='error:keyword':
            bot.reply('That keyword is already taken, sorry. Please try again with another one.')
            return
    except:
        pass

    if shortened['statusCode'] != 200:
        bot.reply('That didnt work. Error '+str(shortened['statusCode'])+' - message: '+str(shortened['message']))
    else:
        bot.reply('Your short URL is: '+str(shortened['shorturl']))
