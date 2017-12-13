# coding: utf8
"""
rat_socket.py - Fuel Rats Rat Tracker and API websockets module.

Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.


This module is built on top of the Sopel system.
http://sopel.chat/
"""

# Python imports
import sys
from threading import Thread
import json
import time
import traceback
import logging
import asyncio

# Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
import ratlib.sopel
from sopel.config.types import StaticSection, ValidatedAttribute

import websockets.client
from ratlib.api.v2compatibility import convertV1RescueToV2, convertV2DataToV1


# ratlib imports
import ratlib.api.http
from ratlib.api.names import *

urljoin = ratlib.api.http.urljoin

import threading
import collections


## Start Config Section ##
class SocketSection(StaticSection):
    websocketurl = ValidatedAttribute('websocketurl', str, default='wss://')
    websockettoken = ValidatedAttribute('websockettoken', str, default='sekret')


def configure(config):
    ratlib.sopel.configure(config)
    config.define_section('socket', SocketSection)
    config.socket.configure_setting(
            'websocketurl',
            (
                "Websocket url"
            )
    )
    config.socket.configure_setting(
            'websockettoken',
            (
                "Web Socket token"
            )
    )


class Request:
    """
    Creates a request JSON object
    """
    def __init__(self, action, data, meta, status):
        self.action = action
        self.data = data
        self.meta = meta
        self.status = status

    def request(self):
        obj = {
            'action': self.action,
            'status': self.status,
            'data': self.data,
            'meta': self.meta
        }
        return json.dumps(obj)


class APIError(Exception):
    """Generic API error"""

    def __init__(self, code=None, details=None, json=None):
        """
        Creates a new APIError.
        :param code: Error code, if any
        :param details: Details, if any
        :param json: JSON response, if available.
        :return:
        """
        self.code = code
        self.details = details
        self.json = json

    def __repr__(self):
        return "<{0.__class__.__name__}({0.code}, {0.details!r})>".format(self)

    __str__ = __repr__


class BadResponseError(APIError):
    """Indicates a generic error with the API response."""
    pass


class BadJSONError(BadResponseError):
    """Indicates an error parsing JSON data."""

    def __init__(self, code='2608', details="API didn\'t return valid JSON."):
        super().__init__(code, details)


class UnsupportedMethodError(APIError):
    def __init__(self, code='9999', details="Invalid request method."):
        super().__init__(code, details)


class Actions(Enum):
    """
    Enum for valid API actions
    """
    getRescue  = 1
    setRescue  = 2
    getRescues = 3


class Api(threading.Thread):
    is_shutdown = False
    is_error = False

    @classmethod
    def get_instance(cls):
        """
        Find and return the running API thread
        :return: running Api thread
        """
        # loop through all the threads
        for thread in threading.enumerate():
            # find the thread with a specific name
            if thread.name == "ApiRunner":
                logging.getLogger("api").info("Found ApiRunner task, returning {}".format(thread))
                return thread


    def __init__(self, connection_string: str, connection_port: int = None, token=None, bot=None, logger=None):
        """
        Init for API container
        :param logger:
        :param connection_string: string to connect to, be WSS
        :param connection_port:  port to connect to (currently ignored)
        :param token:  API token
        :param bot:  SOPEL bot instance
        """
        # write to stdio since the logger isn't loaded yet (this way we know init gets called)
        print("[websocket]API: Init called")
        # fetch the logger
        self.logger = logger if logger is not None else logging.getLogger('api')
        super().__init__()

        # sanity check
        if connection_string.startswith("ws:"):
            connection_string.replace("ws:", "wss:")  # enforce wss, at least in the URI

        # init instance members
        self._connected = False
        self.url = connection_string
        self.port = connection_port
        self.__token = token
        self.bot = bot
        self.ws_client = None
        self.lock = self.bot.memory['ratbot']['lock'] = Socket()  # to prevent multiple calls getting jumbled up

        self.logger.debug("done with init.")

    def call(self, action:Actions, log=None, payload:dict=None)->dict:
        """
        Make an API call
        :param action: Actions object to exectue
        :param log: optional log fileobject to write to, if None writes to STDOUT
        :param payload: optional data to add to the API call
        :return: dict response from API
        """
        if action is not None and action not in Actions:
            return None
        if action is Actions.getRescues:
            return self.retrieve_cases()
    async def runner(self):
        """
        opens and maintains the socket connection
        :return:
        """
        # open the connection
        print(self.url)
        connection_string = self.url.format(token=self.__token)
        self.logger.info("connection string is {}".format(connection_string))
        async with websockets.connect('wss://dev.api.fuelrats.com')as socket:
            # get the on connect message
            msg = await socket.recv()
            self.ws_client = socket
            self.logger.warning("connection message is: {}".format(msg))
            while not self.is_error and not self.is_shutdown:
                # keep the connection alive
                asyncio.sleep(1)  # otherwise CPU usage gets crazy.
            self.ws_client = None
            self.logger.info("Connection closed.")

    def run(self):
        """
        Fetch and maintain a websocket connection to the API
        :return:
        """
        print("[Websockets]:Api run called.")
        # unless we want to shut down, keep the API up.
        while not self.is_shutdown and not self.is_error:
            print("[Websockets]Establishing WSS connection to API...")
            # let the games begin

            # create the websocket client object
            #
            # create the event loop for the thread
            asyncio.set_event_loop(asyncio.new_event_loop())
            loop = asyncio.get_event_loop()
            # open a websockets connection to the API
            print("[Websockets] Running connection...")
            loop.run_until_complete(self.runner())


def setup(bot):
    # setup logging stuff
    logging.basicConfig(format="%(levelname)s :%(message)s")
    logger = logging.getLogger('api')
    logger.addHandler(logging.FileHandler("logs/api.log", 'w'))
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)

    logging.info("[websockets] setup called.")
    logging.basicConfig(level=logging.DEBUG)  # write all the things

    ratlib.sopel.setup(bot)
    bot.memory['ratbot']['log'] = (threading.Lock(), collections.OrderedDict())
    bot.memory['ratbot']['lock'] = Socket()

    if not hasattr(bot.config, 'lock') or not bot.config.socket.websocketurl:
        websocketurl = 'dev.api.fuelrats.com/?bearer={token}'
        __token = '9000'
    else:
        websocketurl = bot.config.socket.websocketurl
        __token= bot.config.socket.websockettoken
    debug_channel = bot.config.ratbot.debug_channel or '#mechadeploy'
    # init a new instance of the API and store it in memory
    logger.info("===========\ncreating new API instance")
    thread = Api(websocketurl, token=__token, bot=bot, logger=logger)
    logger.info("1. api instance created: {}".format(thread))
    logger.info("2. name thread.")
    thread.name = "ApiRunner"
    logger.info('3. run thread.')
    thread.start()
    # api_instance.run()
    logger.info('done. thread= {}'.format(thread))
    logger.info('4. profit??')

    # bot.say('[RatTracker] Gotcha, connecting to RatTracker!', "#unkn0wndev")
    # # thread = Thread(target=api_instance.run)
    # bot.memory['ratbot']['api'] = api_instance
    # print("in ratbot memory:"+bot.memory['ratbot']['api'])
    # print("thread: {}".format(thread))
    logger.info("-------------------")
    # NOTE: this does not actually create an API connection, just the Api handler instance
#
# @commands('connect')
# def func_connect(bot, trigger=None):
#     if Api.my_instance is not None and Api.my_instance._connected:
#         bot.say('[RatTracker] API instance already running!', "#unkn0wnDev")
#         return
#     bot.say('[RatTracker] Gotcha, connecting to RatTracker!', "#unkn0wndev")
#     thread = Thread(target=Api.my_instance.run)
#     thread.start()


class Socket:
    """
    Read/write lock (i presume)
    """
    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def __init__(self):
        self._lock = threading.RLock()
        # print("Init for lock called!")


@commands('reconnect')
@ratlib.sopel.filter_output
def sockettest(bot, trigger):
    """
    Just try it.
    """
    bot.say('Sorry Pal, but you need to restart the bot to attempt a Manual Reconnect! (Stupid, i know -_-)')

#
# class MyClientProtocol(WebSocketClientProtocol):
#     bot = None
#     board = None
#     debug_channel = ''
#
#     def onOpen(self):
#         WebSocketClientProtocol.onOpen(self)
#         MyClientProtocol.bot.say('[Websocket] Successfully openend connection to Websocket!', MyClientProtocol.debug_channel)
#         #print(
#         #    '[Websocket] Authenticating with message: ' + '{ "action": "authorization", "bearer": "' + MyClientProtocol.bot.config.ratbot.apitoken + '"}')
#         #self.sendMessage(
#             #str('{ "action": "authorization", "bearer": "' + MyClientProtocol.bot.config.ratbot.apitoken + '"}').encode(
#             #    'utf-8'))
#         print("[Websocket] onOpen received, sending rattracker sub")
#         self.sendMessage(str('{ "action":["stream","subscribe"], "id":"0xDEADBEEF" }').encode('utf-8'))
#
#     def onMessage(self, payload, isBinary):
#         if isBinary:
#             print("[Websocket] Binary message received: {0} bytes".format(len(payload)))
#
#
#         else:
#             # print("[Websocket] Text message received: {0}".format(payload.decode('utf8')))
#             handleWSMessage(payload, self)
#
#     def onClose(self, wasClean, code, reason):
#         # print('onclose')
#         MyClientProtocol.bot.say('[RatTracker] Lost connection to RatTracker! Trying to reconnect...')
#         MyClientProtocol.bot.say('[Websocket] Closed connection with Websocket. Reason: ' + str(reason), MyClientProtocol.debug_channel)
#         WebSocketClientProtocol.onClose(self, wasClean, code, reason)
#
#
# def handleWSMessage(payload, senderinstance):
#     response = json.loads(payload.decode('utf8'))
#     say = MyClientProtocol.bot.say
#     bot = MyClientProtocol.bot
#     board = MyClientProtocol.board
#     debug_channel = MyClientProtocol.debug_channel
#
#     try:
#         # print("[Websocket] Response: " + str(response))
#         data = response['data']
#         if 'action' in response.keys():
#             action = response['action'][0]
#         elif 'meta' in response.keys():
#             action = response['meta']['event']
#         else:
#             data = data['attributes']
#             action = data['event']
#     except:
#         print("[Websocket] Message: " + str(response))
#         print("[Websocket] Couldn't get data or action - Ignoring Websocket Event.")
#         return
#
#
#     def filterClient(bot, data):
#         resId = data.get('RescueID') or data.get('rescueID') or data.get('RescueId') or data.get(
#             'rescueId') or data.get('rescueid')
#         return getClientName(bot=bot, resId=resId)
#
#     def filterRat(bot, data):
#         ratId = data.get('RatID') or data.get('ratID') or data.get('RatId') or data.get('ratId') or data.get('ratid')
#
#         return getRatName(bot=bot, ratid=ratId)[0]
#
#     def getRescue(bot, data):
#         id = "@" + str(data.get("RescueID"))
#         board = bot.memory['ratbot']['board']
#         result = board.find(id, create=False)
#         rescue = result.rescue[0]
#         return rescue
#
#     def getRatId(bot, data):
#         ratId = data.get('RatID') or data.get('ratID') or data.get('RatId') or data.get('ratId') or data.get('ratid')
#
#         return ratId
#
#     def onduty(data):
#         # print('in function onduty!!!!!!!!')
#         if data['OnDuty'] == 'True':
#             say(str(filterRat(bot, data)) + ' is now on Duty! (Current Location: ' + data[
#                 'currentSystem'] + ') [Reported by RatTracker]')
#         else:
#             say(str(filterRat(bot, data)) + ' is now off Duty! [Reported by RatTracker]')
#
#     def welcome(data):
#         print('debug channel is '+debug_channel)
#         say('[Websocket] Successfully welcomed to Websocket!', str(MyClientProtocol.debug_channel))
#
#     def fr(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         rescue = getRescue(bot, data)
#         ratid = getRatId(bot, data)
#         if data['FriendRequest'] == 'true':
#             say(rat + ': fr+ [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": True, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"FriendRequest": True})
#         else:
#             say(rat + ': fr- [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"FriendRequest": False})
#         save_case(bot, rescue, forceFull=True)
#
#     def wr(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         rescue = getRescue(bot, data)
#         ratid = getRatId(bot, data)
#         if data['WingRequest'] == 'true':
#             say(rat + ': wr+ [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": True,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"WingRequest": True})
#         else:
#             say(rat + ': wr- [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"WingRequest": False})
#         save_case(bot, rescue, forceFull=True)
#
#     def system(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         rescue = getRescue(bot, data)
#         ratid = getRatId(bot, data)
#         if data['ArrivedSystem'] == 'true':
#             say(rat + ': sys+ [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": True, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"ArrivedSystem": True})
#         else:
#             say(rat + ': sys- [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"ArrivedSystem": False})
#         save_case(bot, rescue, forceFull=True)
#
#     def bc(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         rescue = getRescue(bot, data)
#         ratid = getRatId(bot, data)
#         if data['BeaconSpotted'] == 'true':
#             say(rat + ': bc+ [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": True, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"BeaconSpotted": True})
#         else:
#             say(rat + ': bc- [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"BeaconSpotted": False})
#         save_case(bot, rescue, forceFull=True)
#
#     def inst(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         rescue = getRescue(bot, data)
#         ratid = getRatId(bot, data)
#         if data['InstanceSuccessful'] == 'true':
#             say(rat + ': inst+ [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": True}})
#                 else:
#                     status.get(ratid).update({"InstanceSuccessful": True})
#         else:
#             say(rat + ': inst- [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"InstanceSuccessful": False})
#         save_case(bot, rescue, forceFull=True)
#
#     def fueled(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         rescue = getRescue(bot, data)
#         ratid = getRatId(bot, data)
#         if data['Fueled'] == 'true':
#             say(rat + ': Client Fueled! [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": True, "ArrivedSystem": False, "WingRequest": False,
#                                            "BeaconSpotted": False, "FriendRequest": False,
#                                            "InstanceSuccessful": False}})
#                 else:
#                     status.get(ratid).update({"Fueled": True})
#         else:
#             say(rat + ': Client not Fueled! [Case ' + client + ', RatTracker]')
#             with bot.memory['ratbot']['board'].change(rescue):
#                 status = rescue.data.get("status")
#                 if not ratid in status.keys():
#                     status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
#                                        "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
#                 else:
#                  status.get(ratid).update({"Fueled": False})
#         save_case(bot, rescue, forceFull=True)
#
#     def calljumps(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         lystr = str(data['Lightyears'])
#         try:
#             ind = lystr.index(',')
#             lyintstr = lystr
#         except:
#             ind = len(lystr)
#             lyintstr = lystr
#         try:
#             lyintstr = str(int(lystr[0:ind]))
#         except:
#             try:
#                 ind = lyintstr.index('.')
#             except:
#                 ind = len(lyintstr)
#         lyintstr = str(int(lyintstr[0:ind]))
#         if data['SourceCertainty'] == 'Fuelum':
#             bot.say(str(rat) + ': ' + str(data['CallJumps']) + 'j from Fuelum. [Case ' + str(
#                 client) + ', Unknown Rat Location, RatTracker]')
#             return
#         if data['SourceCertainty'] != 'Exact' or data['DestinationCertainty'] != 'Exact':
#             bot.say(str(rat) + ': ' + str(data[
#                                               'CallJumps']) + 'j - Estimate, no exact System. ' + str(
#                 lyintstr) + 'LY [Case ' + str(client) + ', RatTracker]')
#         else:
#             bot.say(str(rat) + ': ' + str(data['CallJumps']) + 'j, ' + str(lyintstr) + 'LY [Case ' + str(
#                 client) + ', RatTracker]')
#
#     def clientupdate(data):
#         client = filterClient(bot, data)
#         rat = filterRat(bot, data)
#         for res in board.rescues:
#             if res.id == data['RescueID'] and res.system != data['SystemName']:
#                 res.system = data['SystemName']
#                 bot.say(rat + ': ' + client + '\'s System is ' + res.system + '! Case updated. [RatTracker]')
#                 save_case(bot, res)
#                 # bot.say('Client name: ' + client + ', Ratname: ' + rat)
#
#
#     wsevents = {"OnDuty": onduty, 'welcome': welcome, 'FriendRequest': fr, 'WingRequest': wr,
#                 'SysArrived': system, 'BeaconSpotted': bc, 'InstanceSuccessful': inst,
#                 'Fueled': fueled, 'CallJumps': calljumps, 'ClientSystem': clientupdate}
#     # print('keys of wsevents: '+str(wsevents.keys()))
#     print("[Websocket] Action was: " + str(action))
#     print("[Websocket] message was: " + str(response))
#
#     if action in wsevents.keys():
#         # print('Action is in wskeys!!')
#         try:
#             wsevents[action](data=data)
#         except:
#             bot.say(
#                 '[RatTracker] Got an error while handling WebSocket Event. Please report this to Marenthyu including the time this happened. Thank you!')
#             bot.say('Unhandled Websocket event. Check console output.', debug_channel)
#             exc_type, exc_value, exc_traceback = sys.exc_info()
#             traceback.print_exception(exc_type, exc_value, exc_traceback)


def save_case(bot, rescue, forceFull=False):
    """
    Begins saving changes to a case.  Returns the future.

    :param bot: Bot instance
    :param rescue: Rescue to save.
    """

    with rescue.change():
        data = rescue.save(full=((rescue.id is None) or forceFull))
        rescue.commit()

    if not bot.config.ratbot.apiurl:
        return None  # API Disabled

    uri = '/rescues'
    if rescue.id:
        method = "PUT"
        uri += "/" + rescue.id
    else:
        method = "POST"

    def task():
        result = callapi(bot, method, uri, data=convertV1RescueToV2(data))
        rescue.commit()
        try:
            addNamesFromV2Response(result['included'])
        except:
            pass
        result['data'] = convertV2DataToV1(result['data'], single=(method=="POST"))
        if 'data' not in result or not result['data']:
            raise RuntimeError("API response returned unusable data.")
        with rescue.change():
            rescue.refresh(result['data'][0])
        return rescue

    return bot.memory['ratbot']['executor'].submit(task)

def shutdown(bot=None):
    # Ignored by sopel?!?!?! - Sometimes.
    print('[Websocket] shutdown for lock called.')
    Api.is_shutdown = True
