# coding: utf8
"""
rat-socket.py - Fuel Rats Rat Tracker module.
Copyright 2016, Peter "Marenthyu" Fredebold <marenthyu@marenthyu.de>
Licensed under the Eiffel Forum License 2.

This module is built on top of the Sopel system.
http://sopel.chat/
"""

# Python imports
import sys
from threading import Thread
import json
import time

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
    # Ignored by sopel?!?!?!
    print('shutdown for socket')
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
    bot.say('Sorry Pal, but you need to restart the bot to attempt a Manual Reconnect!')


@commands('connectsocket', 'connect')
@ratlib.sopel.filter_output
def connectSocket(bot, trigger):
    """
    Connects the Bot to the API's websocket. This command may be removed Without notice and executed on bot startup.
    """
    if reactor._started:
        bot.say('Already connected!')
        return
    bot.say('Gotcha, connecting to the API\'s Websocket!')
    MyClientProtocol.bot = bot
    MyClientProtocol.board = bot.memory['ratbot']['board']
    factory = MyClientFactory(str(bot.config.socket.websocketurl) + ':' + bot.config.socket.websocketport)

    factory.protocol = MyClientProtocol
    # print('in connect')
    hostname = str(bot.config.socket.websocketurl).replace("ws://", '').replace("wss://", '')
    print('Hostname: '+hostname)
    if (bot.config.socket.websocketurl.startswith('wss://')):

        reactor.connectSSL(hostname,
                           int(bot.config.socket.websocketport),
                           factory, contextFactory=optionsForClientTLS(hostname = hostname))
    else:

        reactor.connectTCP(hostname,
                           int(bot.config.socket.websocketport),
                           factory)

    # print('pls')
    thread = Thread(target=reactor.run, kwargs={'installSignalHandlers': 0})

    thread.start()


    # reactor.run(installSignalHandlers=0)
    # print('Im in?')


class MyClientProtocol(WebSocketClientProtocol):
    bot = None
    board = None
    authed = False


    def onOpen(self):
        WebSocketClientProtocol.onOpen(self)
        MyClientProtocol.bot.say('Successfully openend connection to Websocket!')
        print('Authenticating with message: '+'{ "action": "authorization", "bearer": "'+MyClientProtocol.bot.config.ratbot.apitoken+'"}')
        self.sendMessage(str('{ "action": "authorization", "bearer": "'+MyClientProtocol.bot.config.ratbot.apitoken+'"}').encode('utf-8'))


    def onMessage(self, payload, isBinary):
        if isBinary:
            print("Binary message received: {0} bytes".format(len(payload)))


        else:
            print("Text message received: {0}".format(payload.decode('utf8')))
            handleWSMessage(payload, self)

    def onClose(self, wasClean, code, reason):
        # print('onclose')
        MyClientProtocol.bot.say('Closed connection with Websocket. Reason: ' + str(reason))
        WebSocketClientProtocol.onClose(self, wasClean, code, reason)


def handleWSMessage(payload, senderinstance):
    response = json.loads(payload.decode('utf8'))
    action = response['meta']['action']
    try:
        data = response['data']
    except KeyError as ex:
        MyClientProtocol.bot.say('Couldn\'t grab Data field. Here\'s the Error field: '+str(response['errors']))
        return
    say = MyClientProtocol.bot.say
    bot = MyClientProtocol.bot
    board = MyClientProtocol.board

    def filterClient(bot, data):
        resId = data.get('RescueID') or data.get('rescueID') or data.get('RescueId') or data.get('rescueId') or data.get('rescueid')
        return getClientName(bot=bot, resId=resId)
    def filterRat(bot, data):
        ratId = data.get('RatID') or data.get('ratID') or data.get('RatId') or data.get('ratId') or data.get('ratid')

        return getRatName(bot=bot, ratid=ratId)

    def onduty(data):
        # print('in function onduty!!!!!!!!')
        if data['OnDuty'] == 'True':
            say(str(filterRat(bot, data)) + ' is now on Duty! (Current Location: ' + data[
                'currentSystem'] + ') [Reported by RatTracker]')
        else:
            say(str(filterRat(bot, data)) + ' is now off Duty! [Reported by RatTracker]')

    def welcome(data):
        say('Successfully welcomed to Websocket!')

    def fr(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        if data['FriendRequest'] == 'true':
            say(rat + ': fr+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': fr- [Case ' + client + ', RatTracker]')

    def wr(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        if data['WingRequest'] == 'true':
            say(rat + ': wr+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': wr- [Case ' + client + ', RatTracker]')

    def system(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        if data['ArrivedSystem'] == 'true':
            say(rat + ': sys+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': sys- [Case ' + client + ', RatTracker]')

    def bc(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        if data['BeaconSpotted'] == 'true':
            say(rat + ': bc+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': bc- [Case ' + client + ', RatTracker]')

    def inst(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        if data['InstanceSuccessful'] == 'true':
            say(rat + ': inst+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': inst- [Case ' + client + ', RatTracker]')

    def fueled(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        if data['Fueled'] == 'true':
            say(rat + ': Client Fueled! [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': Client not Fueled! [Case ' + client + ', RatTracker]')

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
            bot.say(rat + ': '+str(data['CallJumps'])+'j from Fuelum. [Case '+ client+', Unknown Rat Location, RatTracker]')
            return
        if data['SourceCertainty'] != 'Exact' or data['DestinationCertainty'] != 'Exact':
            bot.say(rat + ': ' + str(data[
                                         'CallJumps']) + 'j - Estimate, no exact System. ' + lyintstr + 'LY [Case ' + client + ', RatTracker]')
        else:
            bot.say(rat + ': ' + str(data['CallJumps']) + 'j, ' + lyintstr + 'LY [Case ' + client + ', RatTracker]')

    def clientupdate(data):
        client = filterClient(bot, data)
        rat = filterRat(bot, data)
        for res in board.rescues:
            if res.id == data['RescueID'] and res.system != data['SystemName']:
                res.system = data['SystemName']
                bot.say(rat + ': ' + client + '\'s System is ' + res.system + '! Case updated. [RatTracker]')
                save_case(bot, res)
        # bot.say('Client name: ' + client + ', Ratname: ' + rat)
    def authorize(data):
        MyClientProtocol.authed = True
        bot.say('Authenticated with the API!')
        print(
            'Authed! Subscribing to RT with message: ' + '{ "action":"stream:subscribe", "applicationId":"0xDEADBEEF" }')
        senderinstance.sendMessage(MyClientProtocol, str('{ "action":"stream:subscribe", "applicationId":"0xDEADBEEF" }').encode('utf-8'))

    wsevents = {"OnDuty:update": onduty, 'welcome': welcome, 'FriendRequest:update': fr, 'WingRequest:update': wr,
                'SysArrived:update': system, 'BeaconSpotted:update': bc, 'InstanceSuccessful:update': inst,
                'Fueled:update': fueled, 'CallJumps:update': calljumps, 'ClientSystem:update':clientupdate, 'authorization':authorize}
    # print('keys of wsevents: '+str(wsevents.keys()))
    # print(action)

    if action in wsevents.keys():
        # print('Action is in wskeys!!')
        wsevents[action](data=data)

def save_case(bot, rescue):
    """
    Begins saving changes to a case.  Returns the future.

    :param bot: Bot instance
    :param rescue: Rescue to save.
    """

    with rescue.change():
        data = rescue.save(full=(rescue.id is None))
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
            raise RuntimeError("API response returned unusable data.")
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
        MyClientProtocol.bot.say('Reconnecting to API Websocket in ' + str(self.delay) + ' seconds...')
        ReconnectingClientFactory.retry(self)
