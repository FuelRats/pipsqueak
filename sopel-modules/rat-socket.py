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
    bot.memory['ratbot']['board'] = Socket()

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


class Socket:
    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._lock.__exit__(exc_type, exc_val, exc_tb)

    def __init__(self):
        print("Init for socket called!")


@commands('sockettest','test','socket')
@ratlib.sopel.filter_output
def sockettest(bot, trigger):
    bot.say('Gotcha! - Testvalue is: ' + bot.config.socket.websocketurl)

@commands('connectsocket','connect')
@ratlib.sopel.filter_output
def connectSocket(bot, trigger):
    bot.say('gotcha, connecting.')
    factory = MyClientFactory(str(bot.config.socket.websocketurl) + ':' + bot.config.socket.websocketport)
    factory.protocol = MyClientProtocol
    print('in connect')
    reactor.connectTCP(str(bot.config.socket.websocketurl).replace("ws://",''), int(bot.config.socket.websocketport), factory)
    print('pls')
    thread = Thread(target = reactor.run, kwargs={'installSignalHandlers':0})
    thread.start()
    MyClientProtocol.bot = bot
   # thread.join()


    #reactor.run(installSignalHandlers=0)
    print('Im in?')



class MyClientProtocol(WebSocketClientProtocol):
    bot = None

    def onOpen(self):
        print('onOpen')
        self.sendMessage(str('{ "action":"stream:subscribe", "applicationId":"0xDEADBEEF" }').encode('utf-8'))

    def onMessage(self, payload, isBinary):
      if isBinary:
         print("Binary message received: {0} bytes".format(len(payload)))

      else:
         print("Text message received: {0}".format(payload.decode('utf8')))
         MyClientProtocol.bot.say(payload.decode('utf8'))

    def onClose(self, wasClean, code, reason):
        print('onclose')
        MyClientProtocol.bot.say('Closed')




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


