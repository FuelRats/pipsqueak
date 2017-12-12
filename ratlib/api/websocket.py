"""
Support for calling the WSS API and handling responses.

Copyright (c) 2017 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
# core python imports
import logging


# import stuff from rat_socket (why am i doing it like this again?)
from sopelModules.rat_socket import Actions
from sopelModules.rat_socket import UnsupportedMethodError
from sopelModules.rat_socket import APIError
from sopelModules.rat_socket import BadJSONError
from sopelModules.rat_socket import Api as API


def call(action:Actions, bot=None, data=None, log=None, **kwargs):
    """
    Wrapper function to call the Websockets API
    :param action: Action to execute against the API
    :param bot: optional SOPEL bot to send replies
    :param data:  JSON data to send
    :param log: File object to write logs to, assumes STDOUT if None
    :param kwargs:
    :return:
    """
    logger = logging.getLogger("api")
    api = API.get_instance()
    if action not in Actions:
        logger.error("Unrecognized action {}".format(action))
        raise UnsupportedMethodError
    elif not data:
        logger.warning("No data given, using default...")
        data = {}
    if action is Actions.getRescues:
        if not api:
            raise APIError("API not initialized")
        ret = api.retrieve_cases()
        if ret == {}:
            bot.say("API returned empty data!", "#unkn0wndev")
            raise BadJSONError()
        else:
            print('[websocket::callapi]: got data from API:\n-------\t{}'.format(ret))
    else:
        raise UnsupportedMethodError()
