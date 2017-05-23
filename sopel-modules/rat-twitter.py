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
from ratlib.api.names import require_rat
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


# Convenience function
def requires_case(fn):
    return parameterize('r', "<client or case number>")(fn)

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

    try:
        api.PostUpdate(line)
    except TwitterError:
        bot.say('Tweet failed. Please try again in a moment and speak to your friendly rat technicians.')
        return

    bot.say('Tweet "{}" sent!'.format(line))
    pass




@commands('tweetc','tweetcase')
@parameterize('r', usage='<client or case number>')
@with_session
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_tweetc(bot, trigger, rescue, db = None):
    """
    Send a tweet based on a case, using generic terms (in bubble, near landmark).
    Required parameter: Client name or board index.
    """
    api = bot.memory['ratbot']['twitterapi']

    if not api:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    def lookup_system(name, model=Starsystem):
        if name is not None:
            return db.query(model).filter(model.name_lower == name.lower()).first()
        return None


    platform = rescue.platform

    if not platform or platform == 'unknown':
        bot.say('The case platform is unknown. Please set it with the corresponding command and try again.')
        return

    platform = platform.upper()
    starsystem = lookup_system(rescue.system)
    cr = "CR " if rescue.codeRed else ""

    message = "[{platform}] Rats needed for {cr}rescue!".format(platform=platform, cr=cr)

    if starsystem:
        landmark, distance = starsystem.nearest_landmark(db, True)

        # is it in the bubble?
        if (landmark.name_lower == "sol" or landmark.name_lower == "fuelum") and distance < 500:
            message = "[{platform}] Rats needed for {cr}rescue in the bubble!".format(platform=platform, cr=cr, system=starsystem.name)

        # is it near or at a landmark?
        elif (starsystem.name_lower == landmark.name_lower) or distance < 500:
            message = "[{platform}] Rats needed for {cr}rescue near {system}!".format(platform=platform, cr=cr, system=landmark.name)

        # ok, just give us the distance
        else:
            if distance < 1000:
                dist = '{dist}ly'.format(dist=math.ceil(distance / 100) * 100)
            else:
                dist = '{dist}kly'.format(dist=math.ceil(distance / 1000))
            message = "[{platform}] Rats needed for {cr}rescue {distance} from {system}!".format(platform=platform, cr=cr, distance=dist, system=landmark.name)

    if not message:
        bot.say('An unknown error occurred. Speak with your local Tech Rats')
        return

    if len(message) < 115:
        message = "{msg} Call your jumps, Rats!".format(msg=message)
    elif len(message) > 140:
        bot.say('Tweet failed! Message is too long ({} characters). Please report this to your local Tech Rats'.format(len(message)))

    try:
        api.PostUpdate(message)
    except TwitterError:
        bot.say('Tweet failed. Please try again in a moment and speak to your friendly rat technicians.')
        return

    bot.say('Tweet sent: "' + message + '"')
