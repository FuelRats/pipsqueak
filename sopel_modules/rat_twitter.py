#coding: utf8
"""
rat_twitter.py - Fuel Rats Twitter module

Copyright (c) 2017 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

#Python core imports

import warnings

import twitter
import math
# Sopel Imports
from sopel.config.types import ValidatedAttribute, StaticSection
from sopel.module import commands
from twitter import TwitterError

import ratlib.sopel
from ratlib import starsystem
from ratlib.api.names import Permissions, require_permission
from ratlib.sopel import parameterize


class TwitterSection(StaticSection):
    debug = ValidatedAttribute('debug', bool, default=False)
    consumer_key = ValidatedAttribute('consumer_key', str, default='undefined')
    consumer_secret = ValidatedAttribute('consumer_secret', str, default='undefined')
    access_token_key = ValidatedAttribute('access_token_key', str, default='undefined')
    access_token_secret = ValidatedAttribute('access_token_secret', str, default='undefined')

def configure(config):
    ratlib.sopel.configure(config)
    config.define_section('twitter', TwitterSection)
    config.twitter.configure_setting(
        'debug',
        (
            "Sets if debug mode is active by default."
        )
    )
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

    bot.memory['ratbot']['twitterapi'] = None
    bot.memory['ratbot']['twitterdebug'] = bot.config.twitter.debug

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

@commands('tweetdebug')
@require_permission(Permissions.techrat, None)
def cmd_tweetdebug(bot, trigger):
    """
    Toggles debug mode on and off. Does not save when the bot is reloaded.
    In debug mode, tweets are not sent. Debug mode defaults to False.
    """
    api = bot.memory['ratbot']['twitterapi']
    debug = bot.memory['ratbot']['twitterdebug']

    if api is None and debug:
        bot.reply('Cannot disable debug mode when Twitter API is not configured.')
        return

    debug = not debug
    bot.memory['ratbot']['twitterdebug'] = debug
    bot.reply('Done. Twitter module is now {}in debug mode.'.format('not ' if not debug else ''))


@commands('tweet')
@parameterize("t", usage="<text to tweet>")
@require_permission(Permissions.rat)
def cmd_tweet(bot, trigger, line):
    """
    Tweet your heart out! (Serious messages though!)
    Will filter out if you try to give away details about our clients in the message.
    Required parameter: The message you want to send, max 140 characters.
    """
    api = bot.memory['ratbot']['twitterapi']
    debug = bot.memory['ratbot']['twitterdebug']

    if api is None or not debug:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    if len(line) > 140:
        bot.reply("Unable to send a tweet that is more than 140 characters long. You need to shave off " + str((len(line)-140)) + " characters.")
        return

    if len(line) < 5:
        bot.reply("Tweets need to be at least 5 characters long. Did you mean to use !tweetcase?")
        return

    board = bot.memory['ratbot']['board']

    lowerline = line.lower()

    for rescue in board.rescues:
        with board.change(rescue):
            if(rescue.client_name.lower() in lowerline or (rescue.system and rescue.system.lower() in lowerline)):
                bot.say('Tweet not sent - do not give out client information in tweets. Try again.')
                return
            pass

    if debug:
        bot.say('Tweet debug: "{}"'.format(line))
        return

    try:
        api.PostUpdate(line)
    except TwitterError as twitterError:
        if 'code' in twitterError.message[0]:
            if twitterError.message[0]['code'] == 187:
                bot.say(
                    "Tweet failed! The tweet is considered a duplicate! Try a different message.")
        else:
            bot.say('Tweet failed. Please try again in a moment and speak to your friendly rat technicians.')

        import traceback
        traceback.print_exc()
        return

    bot.say('Tweet "{}" sent!'.format(line))
    pass


def get_tweet_for_case(rescue):
    platform = rescue.platform.upper()
    cr = "CR " if rescue.codeRed else ""
    nearSystem = ""


    validatedSystem = starsystem.validate(rescue.system)
    if validatedSystem:
        nearestLandmark = starsystem.get_nearest_landmark(validatedSystem)

        if nearestLandmark:
            name, distance = nearestLandmark
            if (name.casefold() == validatedSystem.casefold()) or distance < 50:
                nearSystem = " near {system}".format(platform=platform, cr=cr, system=name)

            if distance < 500:
                nearSystem = ' ~{dist}LY from {system}'.format(dist=math.ceil(distance / 10) * 10, system=name)
            elif distance < 2000:
                nearSystem = ' ~{dist}LY from {system}'.format(dist=math.ceil(distance / 100) * 100, system=name)
            else:
                nearSystem = ' ~{dist}kLY from {system}'.format(dist=math.ceil(distance / 1000), system=name)

    return "[{platform}] Rats needed for a {cr}rescue{nearSystem}!".format(
        platform=platform,
        cr=cr,
        nearSystem=nearSystem
    )


@commands('tweetcase','tweetc')
@parameterize('r', usage='<client or case number>')
@require_permission(Permissions.rat)
def cmd_tweetc(bot, trigger, rescue):
    """
    Send a tweet based on a case, using generic terms (in bubble, near landmark).
    Required parameter: Client name or board index.

    Aliases: tweetcase, tweetc
    """
    api = bot.memory['ratbot']['twitterapi']
    debug = bot.memory['ratbot']['twitterdebug']

    if api is None or not debug:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    platform = rescue.platform

    if not platform or platform == 'unknown':
        bot.say('The case platform is unknown. Please set it with the corresponding command and try again.')
        return

    if rescue.system is None:
        bot.say('The case has no assigned system. Please do this before sending a tweet.')
        return

    message = get_tweet_for_case(rescue)

    if not message:
        bot.say('An unknown error occurred. Speak with your local Tech Rats')
        return

    if len(message) < 100:
        message = "{msg} Call your jumps, Rats!".format(msg=message)

    if rescue.id is not None:
        message = '{msg} -case {id}'.format(msg=message, id=rescue.id[-6:])

    if len(message) > 140:
        bot.say('Tweet failed! Message is too long ({} characters). Please report this to your local Tech Rats'.format(len(message)))

    if debug:
        bot.say('Tweet debug: "' + message + '"')
        return

    try:
        api.PostUpdate(message)
    except TwitterError as twitterError:
        if 'code' in twitterError.message[0]:
            if twitterError.message[0]['code'] == 187:
                bot.say("Tweet failed! The tweet is considered a duplicate! Either you have already sent one, or something went wrong. Contact your nearest Tech Rat.")
        else:
            bot.say('Tweet failed. Please try again in a moment and speak to your friendly rat technicians.')

        bot.say('Failed tweet: "' + message + '"')
        import traceback
        traceback.print_exc()
        return

    bot.say('Tweet sent: "' + message + '"')
