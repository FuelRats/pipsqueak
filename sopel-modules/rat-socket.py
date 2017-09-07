# coding: utf8
"""
rat-socket.py - Fuel Rats Rat Tracker module.

Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

Copyright originally by  Peter "Marenthyu" Fredebold <marenthyu@marenthyu.de> (2016),
under the Eiffel Forum License, version 2

This module is built on top of the Sopel system.
http://sopel.chat/
"""

# Python imports
import sys
from threading import Thread
import json
import time
import traceback

# Sopel imports
from sopel.formatting import bold, color, colors
from sopel.module import commands, NOLIMIT, priority, require_chanmsg, rule
from sopel.tools import Identifier, SopelMemory
import ratlib.sopel
from sopel.config.types import StaticSection, ValidatedAttribute

# Autobahn&Twisted imports
from twisted.python import log
from twisted.internet import reactor
from autobahn.twisted.websocket import WebSocketClientProtocol
from autobahn.twisted.websocket import WebSocketClientFactory
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.ssl import optionsForClientTLS
from twisted.internet import defer

log.startLogging(sys.stdout)
defer.setDebugging(True)

# ratlib imports
import ratlib.api.http
from ratlib.api.names import *

urljoin = ratlib.api.http.urljoin

import threading
import collections


## Start Config Section ##
class SocketSection(StaticSection):
    websocketurl = ValidatedAttribute('websocketurl', str, default='1234')
    websocketport = ValidatedAttribute('websocketport', str, default='9000')


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
        'websocketport',
        (
            "Web Socket Port"
        )
    )


def shutdown(bot=None):
    # Ignored by sopel?!?!?! - Sometimes.
    print('[Websocket] shutdown for socket')
    reactor.stop()



def setup(bot):
    ratlib.sopel.setup(bot)
    bot.memory['ratbot']['log'] = (threading.Lock(), collections.OrderedDict())
    bot.memory['ratbot']['socket'] = Socket()

    if not hasattr(bot.config, 'socket') or not bot.config.socket.websocketurl:
        websocketurl = '123'
        websocketport = '9000'
    else:
        websocketurl = bot.config.socket.websocketurl
        websocketport = bot.config.socket.websocketport
    debug_channel = bot.config.ratbot.debug_channel or '#mechadeploy'

        # ---> Does not work as te board is not nessesarily set up yet! func_connect(bot)


def func_connect(bot):
    if reactor._started:
        bot.say('[RatTracker] Reactor already running!')
        return
    bot.say('[RatTracker] Gotcha, connecting to RatTracker!')
    MyClientProtocol.bot = bot
    MyClientProtocol.debug_channel = bot.config.ratbot.debug_channel
    MyClientProtocol.board = bot.memory['ratbot']['board']
    factory = MyClientFactory(str(bot.config.socket.websocketurl) + ':' + bot.config.socket.websocketport + '?bearer=' + str(MyClientProtocol.bot.config.ratbot.apitoken))

    factory.protocol = MyClientProtocol
    # print('in connect')
    hostname = str(bot.config.socket.websocketurl).replace("ws://", '').replace("wss://", '')
    print('[Websocket] Hostname: ' + hostname)
    if (bot.config.socket.websocketurl.startswith('wss://')):

        reactor.connectSSL(hostname,
                           int(bot.config.socket.websocketport),
                           factory, contextFactory=optionsForClientTLS(hostname=hostname))
    else:

        reactor.connectTCP(hostname,
                           int(bot.config.socket.websocketport),
                           factory)

    # print('pls')
    thread = Thread(target=reactor.run, kwargs={'installSignalHandlers': 0})

    thread.start()


class Socket:
    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def __init__(self):
        self._lock = threading.RLock()
        # print("Init for socket called!")


@commands('reconnect')
@ratlib.sopel.filter_output
def sockettest(bot, trigger):
    """
    Just try it.
    """
    bot.say('Sorry Pal, but you need to restart the bot to attempt a Manual Reconnect! (Stupid, i know -_-)')


@commands('connectsocket', 'connect')
@require_techrat('I am sorry, but this command is restricted for TechRats and above.')
@ratlib.sopel.filter_output
def connectSocket(bot, trigger):
    """
    Connects the Bot to the API's websocket. This command may be removed Without notice and executed on bot startup.
    """
    func_connect(bot)


class MyClientProtocol(WebSocketClientProtocol):
    bot = None
    board = None
    debug_channel = ''

    def onOpen(self):
        WebSocketClientProtocol.onOpen(self)
        MyClientProtocol.bot.say('[Websocket] Successfully openend connection to Websocket!', MyClientProtocol.debug_channel)
        #print(
        #    '[Websocket] Authenticating with message: ' + '{ "action": "authorization", "bearer": "' + MyClientProtocol.bot.config.ratbot.apitoken + '"}')
        #self.sendMessage(
            #str('{ "action": "authorization", "bearer": "' + MyClientProtocol.bot.config.ratbot.apitoken + '"}').encode(
            #    'utf-8'))
        print("[Websocket] onOpen received, sending rattracker sub")
        self.sendMessage(str('{ "action":["stream","subscribe"], "id":"0xDEADBEEF" }').encode('utf-8'))

    def onMessage(self, payload, isBinary):
        if isBinary:
            print("[Websocket] Binary message received: {0} bytes".format(len(payload)))


        else:
            # print("[Websocket] Text message received: {0}".format(payload.decode('utf8')))
            handleWSMessage(payload, self)

    def onClose(self, wasClean, code, reason):
        # print('onclose')
        MyClientProtocol.bot.say('[RatTracker] Lost connection to RatTracker! Trying to reconnect...')
        MyClientProtocol.bot.say('[Websocket] Closed connection with Websocket. Reason: ' + str(reason), MyClientProtocol.debug_channel)
        WebSocketClientProtocol.onClose(self, wasClean, code, reason)


def handleWSMessage(payload, senderinstance):
    response = json.loads(payload.decode('utf8'))
    say = MyClientProtocol.bot.say
    bot = MyClientProtocol.bot
    board = MyClientProtocol.board
    debug_channel = MyClientProtocol.debug_channel

    try:
        # print("[Websocket] Response: " + str(response))
        data = response['data']
        if 'action' in response.keys():
            action = response['action'][0]
        else:
            action = response['meta']['event']
    except KeyError:
        print("[Websocket] Message: " + str(response))
        print("[Websocket] Couldn't get data or action - Ignoring Websocket Event.")
        return


    def filterClient(bot, data):
        resId = data.get('RescueID') or data.get('rescueID') or data.get('RescueId') or data.get(
            'rescueId') or data.get('rescueid')
        return getClientName(bot=bot, resId=resId)

    def filterRat(bot, data):
        ratId = data.get('RatID') or data.get('ratID') or data.get('RatId') or data.get('ratId') or data.get('ratid')

        return getRatName(bot=bot, ratid=ratId)[0]

    def getRescue(bot, data):
        id = "@" + str(data.get("RescueID"))
        board = bot.memory['ratbot']['board']
        result = board.find(id, create=False)
        rescue = result.rescue[0]
        return rescue

    def getRatId(bot, data):
        ratId = data.get('RatID') or data.get('ratID') or data.get('RatId') or data.get('ratId') or data.get('ratid')

        return ratId

    def onduty(data):
        # print('in function onduty!!!!!!!!')
        if data['OnDuty'] == 'True':
            say(str(filterRat(bot, data)) + ' is now on Duty! (Current Location: ' + data[
                'currentSystem'] + ') [Reported by RatTracker]')
        else:
            say(str(filterRat(bot, data)) + ' is now off Duty! [Reported by RatTracker]')

    def welcome(data):
        print('debug channel is '+debug_channel)
        say('[Websocket] Successfully welcomed to Websocket!', str(MyClientProtocol.debug_channel))

    def fr(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        rescue = getRescue(bot, data)
        ratid = getRatId(bot, data)
        if data['FriendRequest'] == 'true':
            say(rat + ': fr+ [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": True, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"FriendRequest": True})
        else:
            say(rat + ': fr- [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"FriendRequest": False})
        save_case(bot, rescue, forceFull=True)

    def wr(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        rescue = getRescue(bot, data)
        ratid = getRatId(bot, data)
        if data['WingRequest'] == 'true':
            say(rat + ': wr+ [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": True,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"WingRequest": True})
        else:
            say(rat + ': wr- [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"WingRequest": False})
        save_case(bot, rescue, forceFull=True)

    def system(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        rescue = getRescue(bot, data)
        ratid = getRatId(bot, data)
        if data['ArrivedSystem'] == 'true':
            say(rat + ': sys+ [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": True, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"ArrivedSystem": True})
        else:
            say(rat + ': sys- [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"ArrivedSystem": False})
        save_case(bot, rescue, forceFull=True)

    def bc(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        rescue = getRescue(bot, data)
        ratid = getRatId(bot, data)
        if data['BeaconSpotted'] == 'true':
            say(rat + ': bc+ [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": True, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"BeaconSpotted": True})
        else:
            say(rat + ': bc- [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"BeaconSpotted": False})
        save_case(bot, rescue, forceFull=True)

    def inst(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        rescue = getRescue(bot, data)
        ratid = getRatId(bot, data)
        if data['InstanceSuccessful'] == 'true':
            say(rat + ': inst+ [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": True}})
                else:
                    status.get(ratid).update({"InstanceSuccessful": True})
        else:
            say(rat + ': inst- [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"InstanceSuccessful": False})
        save_case(bot, rescue, forceFull=True)

    def fueled(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        rescue = getRescue(bot, data)
        ratid = getRatId(bot, data)
        if data['Fueled'] == 'true':
            say(rat + ': Client Fueled! [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": True, "ArrivedSystem": False, "WingRequest": False,
                                           "BeaconSpotted": False, "FriendRequest": False,
                                           "InstanceSuccessful": False}})
                else:
                    status.get(ratid).update({"Fueled": True})
        else:
            say(rat + ': Client not Fueled! [Case ' + client + ', RatTracker]')
            with bot.memory['ratbot']['board'].change(rescue):
                status = rescue.data.get("status")
                if not ratid in status.keys():
                    status.update({ratid: {"Fueled": False, "ArrivedSystem": False, "WingRequest": False,
                                       "BeaconSpotted": False, "FriendRequest": False, "InstanceSuccessful": False}})
                else:
                 status.get(ratid).update({"Fueled": False})
        save_case(bot, rescue, forceFull=True)

    def calljumps(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        lystr = str(data['Lightyears'])
        try:
            ind = lystr.index(',')
            lyintstr = lystr
        except:
            ind = len(lystr)
            lyintstr = lystr
        try:
            lyintstr = str(int(lystr[0:ind]))
        except:
            try:
                ind = lyintstr.index('.')
            except:
                ind = len(lyintstr)
        lyintstr = str(int(lyintstr[0:ind]))
        if data['SourceCertainty'] == 'Fuelum':
            bot.say(str(rat) + ': ' + str(data['CallJumps']) + 'j from Fuelum. [Case ' + str(
                client) + ', Unknown Rat Location, RatTracker]')
            return
        if data['SourceCertainty'] != 'Exact' or data['DestinationCertainty'] != 'Exact':
            bot.say(str(rat) + ': ' + str(data[
                                              'CallJumps']) + 'j - Estimate, no exact System. ' + str(
                lyintstr) + 'LY [Case ' + str(client) + ', RatTracker]')
        else:
            bot.say(str(rat) + ': ' + str(data['CallJumps']) + 'j, ' + str(lyintstr) + 'LY [Case ' + str(
                client) + ', RatTracker]')

    def clientupdate(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        for res in board.rescues:
            if res.id == data['RescueID'] and res.system != data['SystemName']:
                res.system = data['SystemName']
                bot.say(rat + ': ' + client + '\'s System is ' + res.system + '! Case updated. [RatTracker]')
                save_case(bot, res)
                # bot.say('Client name: ' + client + ', Ratname: ' + rat)


    wsevents = {"OnDuty": onduty, 'welcome': welcome, 'FriendRequest': fr, 'WingRequest': wr,
                'SysArrived': system, 'BeaconSpotted': bc, 'InstanceSuccessful': inst,
                'Fueled': fueled, 'CallJumps': calljumps, 'ClientSystem': clientupdate}
    # print('keys of wsevents: '+str(wsevents.keys()))
    # print(action)

    if action in wsevents.keys():
        # print('Action is in wskeys!!')
        try:
            wsevents[action](data=data)
        except:
            bot.say(
                '[RatTracker] Got an error while handling WebSocket Event. Please report this to Marenthyu including the time this happened. Thank you!')
            bot.say('Unhandled Websocket event. Check console output.', debug_channel)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_traceback)


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

    uri = '/api/rescues'
    if rescue.id:
        method = "PUT"
        uri += "/" + rescue.id
    else:
        method = "POST"

    def task():
        result = callapi(bot, method, uri, data=data)
        rescue.commit()
        if 'data' not in result or not result['data']:
            raise RuntimeError("[Websocket] API response returned unusable data.")
        with rescue.change():
            rescue.refresh(result['data'])
        return rescue

    return bot.memory['ratbot']['executor'].submit(task)


class MyClientFactory(ReconnectingClientFactory, WebSocketClientFactory):
    protocol = MyClientProtocol

    def startedConnecting(self, connector):
        print('[Websocket] Started to connect.')
        ReconnectingClientFactory.startedConnecting(self, connector)

    def clientConnectionLost(self, connector, reason):
        print('[Websocket]  Lost connection. Reason: {}'.format(reason))
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        print('[Websocket]  Connection failed. Reason: {}'.format(reason))
        MyClientProtocol.bot.say('Connection to Websocket refused. reason:' + str(reason))
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)

    def retry(self, connector=None):
        MyClientProtocol.bot.say('[Websocket] Reconnecting to API Websocket in ' + str(int(self.delay)) + ' seconds...')
        ReconnectingClientFactory.retry(self)
