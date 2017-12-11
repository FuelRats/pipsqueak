"""
Support for calling the WSS API and handling responses.

Copyright (c) 2017 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""

# import stuff from rat_socket (why am i doing it like this again?)

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
    raise NotImplementedError("start over.")

    def logger(message)->None:
        """
        Log helper method
        :param message: messsage to write
        :return:
        """
        if not log:
            print("[api.Websocket::call] {}".format(message))
        else:
            with log:
                log.write("[api.Websocket::call]: {}".format(message))
    if action not in Actions:
        logger("Unrecognized action {}".format(action))
        raise UnsupportedMethodError
    if not data:
        logger("No data given, using default...")
        data = {}
    if action is Actions.getRescues:
        if not API.my_instance:
            raise APIError("API not initialized")
        ret = API.my_instance.retrieve_cases()
        if ret == {}:
            bot.say("API returned empty data!", "#unkn0wndev")
            raise BadJSONError()
        else:
            print('[websocket::callapi]: got data from API:\n-------\t{}'.format(ret))
    else:
        raise UnsupportedMethodError()
