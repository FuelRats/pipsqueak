#coding: utf8
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

#Sopel imports
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
log.startLogging(sys.stdout)

#ratlib imports
import ratlib.api.http
urljoin = ratlib.api.http.urljoin



import threading
import collections

## Start Config Section ##
class SocketSection(StaticSection):
    websocketurl = ValidatedAttribute('websocketurl', str, default='1234')
    websocketport = ValidatedAttribute('websocketurl', str, default='9000')

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



def callapi(bot, method, uri, data=None, _fn=ratlib.api.http.call):
    uri = urljoin(bot.config.ratbot.apiurl, uri)
    headers = {"Authorization":"Bearer "+bot.config.ratbot.apitoken}
    with bot.memory['ratbot']['apilock']:
        return _fn(method, uri, data, log=bot.memory['ratbot']['apilog'], headers=headers)


def removeTags(string):
    try:
        i = string.index('[')
    except ValueError:
        i = len(string)

    return string[0:i]

def getRatId(bot, ratname):
    """
    Gets the RatId for a given name from the API or 0 if it couldnt find anyone with that cmdrname
    Args:
        bot: the bot to pull the config from
        ratname: the cmdrname to look for

    Returns:

    """
    strippedname = removeTags(ratname)
    try:
        uri = '/rats?CMDRname=' + strippedname
        result = callapi(bot=bot,method = 'GET',uri=uri)
        # print(result)
        data = result['data']
        # print(data)
        firstmatch = data[0]
        id = firstmatch['_id']
        return {'id':id, 'name':strippedname}
    except IndexError as ex:
        try:
            #print('No rats with that CMDRname found. Trying nickname...')
            uri = '/rats?nickname=' + strippedname
            result = callapi(bot=bot, method='GET', uri=uri)
            # print(result)
            data = result['data']
            # print(data)
            firstmatch = data[0]
            id = firstmatch['_id']
            return {'id':id, 'name':strippedname}
        except IndexError:
            #print('no rats with that commandername or nickname found. trying gamertag...')
            try:
                uri = '/rats?gamertag=' + strippedname
                result = callapi(bot=bot, method='GET', uri=uri)
                # print(result)
                data = result['data']
                # print(data)
                firstmatch = data[0]
                id = firstmatch['_id']
                return {'id':id, 'name':strippedname}
            except IndexError:
                #print('no rats with that commandername or nickname or gamertag found.')
                return {'id':'0', 'name':strippedname, 'error':ex, 'description':'no rats with that commandername or nickname or gamertag found.'}
    except ratlib.api.http.APIError as ex:
        print('APIError: couldnt find RatId for '+strippedname)
        return {'id':'0', 'name':strippedname, 'error':ex, 'description':'API Error while trying to fetch Rat'}

def getRatName(bot, ratid):
    result = callapi(bot=bot, method='GET', uri='/rats/'+ratid)
    ret = 'unknown'
    try:
        data=result['data']
        try:
            ret = data['CMDRname']
        except:
            ret = data['nickname']
    except:
        ret = 'unknown'
    # print('returning '+ret+' as name for '+ratid)
    return ret

def getClientName(bot, resId):
    result = callapi(bot=bot, method='GET', uri='/rescues/' + resId)
    ret = 'unknown'
    try:
        data = result['data']
        ret = data['client']['nickname']
    except:
        ret = 'unknown'
    return ret

class Socket:
    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def __init__(self):
        self._lock = threading.RLock()
        print("Init for socket called!")


@commands('reconnect')
@ratlib.sopel.filter_output
def sockettest(bot, trigger):
    bot.say('Sorry Pal, but you need to restart the bot to attempt a Manual Reconnect!')

@commands('connectsocket','connect')
@ratlib.sopel.filter_output
def connectSocket(bot, trigger):
    bot.say('Gotcha, connecting to the API\'s Websocket!')
    MyClientProtocol.bot = bot
    factory = MyClientFactory(str(bot.config.socket.websocketurl) + ':' + bot.config.socket.websocketport)
    factory.protocol = MyClientProtocol
    # print('in connect')
    reactor.connectTCP(str(bot.config.socket.websocketurl).replace("ws://",''), int(bot.config.socket.websocketport), factory)
    # print('pls')
    thread = Thread(target = reactor.run, kwargs={'installSignalHandlers':0})
    thread.start()


    #reactor.run(installSignalHandlers=0)
    # print('Im in?')



class MyClientProtocol(WebSocketClientProtocol):
    bot = None

    def onOpen(self):
        MyClientProtocol.bot.say('Successfully openend connection to Websocket!')
        self.sendMessage(str('{ "action":"stream:subscribe", "applicationId":"0xDEADBEEF" }').encode('utf-8'))

    def onMessage(self, payload, isBinary):
      if isBinary:
         print("Binary message received: {0} bytes".format(len(payload)))

      else:
         print("Text message received: {0}".format(payload.decode('utf8')))
         handleWSMessage(payload)


    def onClose(self, wasClean, code, reason):
        # print('onclose')
        MyClientProtocol.bot.say('Closed connection with Websocket. Reason: '+str(reason))


def handleWSMessage(payload):
    response = json.loads(payload.decode('utf8'))
    action = response['meta']['action']
    data = response['data']
    say = MyClientProtocol.bot.say
    bot = MyClientProtocol.bot

    def onduty(data):
        #print('in function onduty!!!!!!!!')
        if data['OnDuty'] == 'True':
            say(str(getRatName(bot, data['RatID'])) + ' is now on Duty! (Current Location: '+data['currentSystem']+') [Reported by RatTracker]')
        else:
            say(str(getRatName(bot, data['RatID'])) + ' is now off Duty! [Reported by RatTracker]')

    def welcome(data):
        say('Successfully welcomed to Websocket!')

    def fr(data):
        client = getClientName(bot=bot, resId=data['RescueID'])
        rat = getRatName(bot=bot, ratid=data['ratID'])
        if data['FriendRequest'] == 'true':
            say(rat + ': fr+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': fr- [Case ' + client + ', RatTracker]')

    def wr(data):
        client = getClientName(bot=bot, resId=data['RescueID'])
        rat = getRatName(bot=bot, ratid=data['ratID'])
        if data['WingRequest'] == 'true':
            say(rat + ': wr+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': wr- [Case ' + client + ', RatTracker]')

    def system(data):
        client = getClientName(bot=bot, resId=data['RescueID'])
        rat = getRatName(bot=bot, ratid=data['ratID'])
        if data['ArrivedSystem'] == 'true':
            say(rat + ': sys+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': sys- [Case ' + client + ', RatTracker]')

    def bc(data):
        client = getClientName(bot=bot, resId=data['RescueID'])
        rat = getRatName(bot=bot, ratid=data['ratID'])
        if data['BeaconSpotted'] == 'true':
            say(rat + ': bc+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': bc- [Case ' + client + ', RatTracker]')

    def inst(data):
        client = getClientName(bot=bot, resId=data['RescueID'])
        rat = getRatName(bot=bot, ratid=data['ratID'])
        if data['InstanceSuccessful'] == 'true':
            say(rat + ': inst+ [Case ' + client + ', RatTracker]')
        else:
            say(rat + ': inst- [Case ' + client + ', RatTracker]')

    wsevents = {"OnDuty:update":onduty,'welcome':welcome,'FriendRequest:update':fr,'WingRequest:update':wr,'SysArrived:update':system,'BeaconSpotted:update':bc,'InstanceSuccessful:update':inst}
    #print('keys of wsevents: '+str(wsevents.keys()))
    #print(action)

    if action in wsevents.keys():
        #print('Action is in wskeys!!')
        wsevents[action](data=data)


class MyClientFactory(ReconnectingClientFactory, WebSocketClientFactory):

    protocol = MyClientProtocol

    def startedConnecting(self, connector):
        print('Started to connect.')

    def clientConnectionLost(self, connector, reason):
        print('Lost connection. Reason: {}'.format(reason))
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        print('Connection failed. Reason: {}'.format(reason))
        MyClientProtocol.bot.say('Connection to Websocket refused. reason:'+str(reason))
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)

    def retry(self, connector=None):
        MyClientProtocol.bot.say('Reconnecting to API Websocket in '+str(self.delay)+' seconds...')
        ReconnectingClientFactory.retry(self)


