#coding: utf8
"""
rat-autocorrect.py - System name autocorrection.
Copyright 2016, Daniel "dewin" Grace

Licensed under the Eiffel Forum License 2.

These modules are built on top of the Sopel system.
http://sopel.chat/

This is currently a very rudimentary implementation, lacking any sort of configuration.
"""
from sopel.module import rule, NOLIMIT
import ratlib.autocorrect

@rule(".+")
def correct_system(bot, trigger):
    line = trigger.group(0)
    result = ratlib.autocorrect.correct(line)
    if result.fixed:
        names = ", ".join(
            '"...{old}" is probably "...{new}"'
                .format(old=old, new=new) for old, new in result.corrections.items()
        )
        bot.say("{names} (corrected for {nick})".format(names=names, nick=trigger.nick))
    return NOLIMIT

