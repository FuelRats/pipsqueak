#coding: utf8
"""
rat-twitter.py - Fuel Rats Twitter module

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
from ratlib.api.names import require_rat, require_techrat
from ratlib.db import with_session, Starsystem
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
    bot.memory['ratbot']['twitterdebug'] = False

# Convenience function
def requires_case(fn):
    return parameterize('r', "<client or case number>")(fn)

@commands('tweetdebug')
@require_techrat
def cmd_tweetdebug(bot, trigger):
    """
    Toggles debug mode on and off. Does not save when the bot is reloaded.
    In debug mode, tweets are not sent. Debug mode defaults to False.    
    """
    debug = bot.memory['ratbot']['twitterdebug']
    debug = not debug
    bot.memory['ratbot']['twitterdebug'] = debug
    bot.reply('Done. Twitter module is now {}in debug mode.'.format('not ' if not debug else ''))


@commands('tweet')
@parameterize("t", usage="<text to tweet>")
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_tweet(bot, trigger, line):
    """ 
    Tweet your heart out! (Serious messages though!) 
    Will filter out if you try to give away details about our clients in the message.
    Required parameter: The message you want to send, max 140 characters.
    """
    api = bot.memory['ratbot']['twitterapi']
    debug = bot.memory['ratbot']['twitterdebug']

    if not api:
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


def get_tweet_for_case(rescue, db):

    def lookup_system(name, model=Starsystem):
        if name is not None:
            return db.query(model).filter(model.name_lower == name.lower()).first()
        return None

    platform = rescue.platform.upper()
    cr = "CR " if rescue.codeRed else ""

    # this is the base message
    message = "[{platform}] Rats needed for {cr}rescue!".format(platform=platform, cr=cr)

    if db is None:
        return message

    starsystem = lookup_system(rescue.system)
    if starsystem:
        landmark, distance = starsystem.nearest_landmark(db, True)

        # we couldn't calculate a distance (system not in eddb, probably)
        if distance is None:
            return message

        if (starsystem.name_lower == landmark.name_lower) or distance < 50:
            return "[{platform}] Rats needed for {cr}rescue near {system}!".format(platform=platform, cr=cr, system=landmark.name)

        # let's work on distances
        if distance < 250:
            dist = '{dist}ly'.format(dist=math.ceil(distance / 10) * 10)
        elif distance < 1000:
            dist = '{dist}ly'.format(dist=math.ceil(distance / 100) * 100)
        else:
            dist = '{dist}kly'.format(dist=math.ceil(distance / 1000))

        return "[{platform}] Rats needed for {cr}rescue {distance} from {system}!".format(platform=platform, cr=cr, distance=dist, system=landmark.name)

    return message

@commands('tweetcase','tweetc')
@parameterize('r', usage='<client or case number>')
@with_session
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_tweetc(bot, trigger, rescue, db = None):
    """
    Send a tweet based on a case, using generic terms (in bubble, near landmark).
    Required parameter: Client name or board index.
    
    Aliases: tweetcase, tweetc
    """
    api = bot.memory['ratbot']['twitterapi']
    debug = bot.memory['ratbot']['twitterdebug']

    if not api:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    platform = rescue.platform

    if not platform or platform == 'unknown':
        bot.say('The case platform is unknown. Please set it with the corresponding command and try again.')
        return

    if rescue.system is None:
        bot.say('The case has no assigned system. Please do this before sending a tweet.')
        return

    message = get_tweet_for_case(rescue, db)

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
