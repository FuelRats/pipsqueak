#coding: utf8
"""
rat-twitter.py - Fuel Rats twitter module
Copyright 2017, Henrik "Tivec" Bergvin <henrik.bergvin@gmail.com>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports
import json
import os

#Sopel Imports
from sopel.config.types import ValidatedAttribute, StaticSection
from sopel.module import commands
from sopel.tools import SopelMemory

import ratlib.sopel
from ratlib.sopel import parameterize
import twitter

from ratlib.api.names import require_rat


class TwitterSection(StaticSection):
    consumer_key = ValidatedAttribute('consumer_key', str, default='consumer_key')
    consumer_secret = ValidatedAttribute('consumer_key', str, default='consumer_secret')
    access_token_key = ValidatedAttribute('access_token_key', str, default='access_token_key')
    access_token_secret = ValidatedAttribute('access_token_secret', str, default='access_token_secret')

def configure(config):
    ratlib.sopel.configure(config)
    config.define_section('twitter', TwitterSection)

def setup(bot):
    ratlib.sopel.setup(bot)

@commands('tweet')
@parameterize("t", usage="<text to tweet>")
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_tweet(bot, trigger, line):
    bot.say('trigger: ' + trigger)
    bot.say('line: ' + line)
    pass

