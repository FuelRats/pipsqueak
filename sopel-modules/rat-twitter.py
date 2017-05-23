#coding: utf8
"""
rat-twitter.py - Fuel Rats twitter module
Copyright 2017, Henrik "Tivec" Bergvin <henrik.bergvin@gmail.com>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports

import warnings

import twitter
# Sopel Imports
from sopel.config.types import ValidatedAttribute, StaticSection
from sopel.module import commands
from twitter import TwitterError

import ratlib.sopel
from ratlib.api.names import require_rat
from ratlib.db import with_session
from ratlib.sopel import parameterize


class TwitterSection(StaticSection):
    consumer_key = ValidatedAttribute('consumer_key', str, default='undefined')
    consumer_secret = ValidatedAttribute('consumer_secret', str, default='undefined')
    access_token_key = ValidatedAttribute('access_token_key', str, default='undefined')
    access_token_secret = ValidatedAttribute('access_token_secret', str, default='undefined')

def configure(config):
    ratlib.sopel.configure(config)
    config.define_section('twitter', TwitterSection)
    config.twitter.configure_setting(
        'consumer_key',
        (
            "Consumer key for the twitter application."
        )
    )
    config.twitter.configure_setting(
        'consumer_secret',
        (
            "Consumer secret for the twitter application."
        )
    )
    config.twitter.configure_setting(
        'access_token_key',
        (
            "Access token key for the twitter application."
        )
    )
    config.twitter.configure_setting(
        'access_token_secret',
        (
            "Access token secret for the twitter application."
        )
    )

def setup(bot):
    ratlib.sopel.setup(bot)
    if not hasattr(bot.config, 'twitter'):
        warnings.warn("Twitter module configuration failed.")
        return

    api = twitter.Api(
        consumer_key=bot.config.twitter.consumer_key,
        consumer_secret=bot.config.twitter.consumer_secret,
        access_token_key=bot.config.twitter.access_token_key,
        access_token_secret=bot.config.twitter.access_token_secret
    )

    try:
        api.VerifyCredentials()
    except TwitterError:
        warnings.warn('Twitter API verification failed.')
        return

    bot.memory['ratbot']['twitterapi'] = api


# Convenience function
def requires_case(fn):
    return parameterize('r', "<client or case number>")(fn)

@commands('tweet')
@parameterize("t", usage="<text to tweet>")
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_tweet(bot, trigger, line):

    api = bot.memory['ratbot']['twitterapi']
    if not api:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    if len(line) > 140:
        bot.reply("Unable to send a tweet that is more than 140 characters long. You need to shave off " + str((len(line)-140)) + " characters.")
        return


    board = bot.memory['ratbot']['board']

    for rescue in board.rescues:
        with board.change(rescue):
            if(rescue.client_name.lower() in line.lower() or rescue.system.lower() in line.lower()):
                bot.say('Tweet not sent: do not give out client information in tweets. Try again.')
                return
            pass

    try:
        api.PostUpdate(line)
    except TwitterError:
        bot.say("Tweet failed. Please speak to your friendly neighborhood techies.")
        return

    bot.say('Tweet sent!')
    pass




@commands('tweetc')
@requires_case
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
@with_session
def cmd_tweetc(bot, trigger, rescue, db):

    api = bot.memory['ratbot']['twitterapi']

    if not api:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    bot.say("Ok, you picked rescue #" + rescue.boardindex)
