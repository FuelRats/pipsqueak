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

    api = bot.memory['ratbot']['twitterapi']
    if not api:
        bot.reply("The Twitter interface is not correctly configured. Unable to continue.")
        return

    if len(line) > 140:
        bot.reply("Unable to send a tweet that is more than 140 characters long. You need to shave off " + str((len(line)-140)) + " characters.")
        return

    if len(line) < 5:
        bot.reply("Tweet not sent because it is very short. Did you mean to use !tweetcase?")
        return

    board = bot.memory['ratbot']['board']

    for rescue in board.rescues:
        with board.change(rescue):
            if(rescue.client_name.lower() in line.lower() or (rescue.system and rescue.system.lower() in line.lower())):
                bot.say('Tweet not sent: do not give out client information in tweets. Try again.')
                return
            pass

    try:
        api.PostUpdate(line)
    except TwitterError:
        bot.say('Tweet failed. Please speak to your friendly rat technicians.')
        return

    bot.say('Tweet sent!')
    pass




@commands('tweetc','tweetcase')
@parameterize('r', usage='<client or case number>')
@with_session
@require_rat('Sorry, you need to be a registered and drilled Rat to use this command.')
def cmd_tweetc(bot, trigger, rescue, db = None):

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

    message = "{platform} rats needed for {cr}rescue.".format(platform=platform, cr=cr)

    if starsystem:
        landmark, distance = starsystem.nearest_landmark(db, True)

        # is it in the bubble?
        if (landmark.name_lower == "sol" or landmark.name_lower == "fuelum") and distance < 1000:
            message = "{platform} rats needed for {cr}rescue in the bubble.".format(platform=platform, cr=cr, system=starsystem.name)

        # is it near or at a landmark?
        elif (starsystem.name_lower == landmark.name_lower) or distance < 250:
            message = "{platform} rats needed for {cr}rescue near {system}.".format(platform=platform, cr=cr, system=landmark.name)

        # ok, just give us the distance
        else:
            dist = math.ceil(distance / 1000)
            message = "{platform} rats needed for {cr}rescue {distance}kly from {system}.".format(platform=platform, cr=cr, distance=dist, system=landmark.name)

    if not message:
        bot.say('An unknown error occurred. Speak with your local techies')
        return

    try:
        api.PostUpdate(message)
    except TwitterError:
        bot.say('Tweet failed. Please speak to your friendly rat technicians.')
        return

    bot.say('Tweet sent: ' + message)
