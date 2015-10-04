#! /usr/bin/env python
#
# Example program using irc.bot.
#
# Joel Rosdahl <joel@rosdahl.net>

"""A simple example bot.

"""

# stdlib imports
import logging
import logging.handlers
from datetime import datetime, timedelta
# 3Plib imports
import irc.bot
import irc.strings
from irc.client import ip_numstr_to_quad, ip_quad_to_numstr, Connection
# custom imports
from botlib import processing
from botlib.systemsearch import Systemsearch
import botlib.systemsearch

class QConnection(Connection):
  socket = None

  def __init__(self, c, bot, proc):
    Connection.__init__(self, bot.reactor)
    self.c = c
    self.bot = bot
    self.proc = proc
    self.socket = proc.out_queue._reader

  def process_data(self):
    self.bot.cmd_readout(self.c, [self.proc.pid], None, None)

class RatBotError(Exception):
  pass

class RatBotKilledError(RatBotError):
  pass

class RatBotResetError(RatBotError):
  pass

class TestBot(irc.bot.SingleServerIRCBot):
  def __init__(self, channels, nickname, server, port=6667, debug=False):
    irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
    self.debug = debug

    self.botlogger = logging.getLogger('RatBotLogger')
    sysloghandler = logging.handlers.SysLogHandler('/dev/log')
    sysloghandler.setFormatter(logging.Formatter('ratbot %(levelname)s: %(message)s'))
    self.botlogger.addHandler(sysloghandler)

    if debug:
      self.botlogger.setLevel(logging.DEBUG)
      stderrhandler = logging.StreamHandler()
      stderrhandler.setFormatter(logging.Formatter('ratbot %(levelname)s: %(message)s'))
      self.botlogger.addHandler(stderrhandler)
    else:
      self.botlogger.setLevel(logging.INFO)

    self.botlogger.info('Ratbot started')
    self._channels = channels
    self.processes = {}
    self.processes_by_qout = {}
    self.cooldown = {}
    self.cmd_handlers = {
        # bot management
        'die': [ 'Kills the bot.', [], self.cmd_die ],
        'reset': [ 'This command resets the bot', [], self.cmd_reset ],
        'join': [ 'Makes the bot join a channel', ['channel name'],
          self.cmd_join ],
        'part': [ 'Makes the bot part a channel',
          ['channel name (current channel if parameter not present and command issued from a channel)'], self.cmd_part ],
        'help': [ 'Prints help message listing commands', [], self.cmd_help ],
        # process control
#        'signal': [ 'Creates a new case', ['Client name', 'Client system', 'Client OX status (Empty for fine)'], self.cmd_signal],
        'search': [ 'Search for a simply-named system',
          ['-x Extended Search: Do not restrict search by system name length',
           '-f Fuzzy Search: Return just the three best-matching system names for search term',
           '-l / -ll / -lll Large radius: Search for close systems in 20 / 30 / 50Ly radius instead of 10', 'System'],
          self.cmd_search],
        'fact': [ 'Recites a fact',
          ['Name of fact, empty prints all available facts' ],
          self.cmd_fact ],
        }

  def on_nicknameinuse(self, c, e):
    c.nick(c.get_nickname() + "_")

  def on_welcome(self, c, e):
    for channel in self._channels:
      self.botlogger.debug('Joining %s' % channel)
      c.join(channel)

  def on_privmsg(self, c, e):
    self.do_command(c, e, e.arguments[0])

  def on_pubmsg(self, c, e):
    self.botlogger.debug('Pubmsg arguments: {}'.format(e.arguments))
    if e.arguments[0].startswith('!'):
      self.botlogger.debug('detected command {}'.format(e.arguments[0][1:]))
      self.do_command(c, e, e.arguments[0][1:])
    a = e.arguments[0].split(":", 1)
    if len(a) > 1 and irc.strings.lower(a[0]) == irc.strings.lower(self.connection.get_nickname()):
      self.do_command(c, e, a[1].strip())

  def do_command(self, c, e, cmd):
    nick = e.source.nick
    c = self.connection

    split = cmd.split()
    cmd = split[0]
    args = split[1:]

    if cmd == "disconnect":
      self.disconnect()
    elif cmd in self.cmd_handlers:
      self.cmd_handlers[cmd][2](c, args, nick, e.target)
  
  def cmd_die(self, c, params, sender_nick, from_channel):
    self.botlogger.info("Killed by " + sender_nick)
    if len(params) > 0:
      self.die(" ".join(params))
    else:
      self.die("Killed by !die")

  def cmd_reset(self, c, params, sender_nick, from_channel):
    self.botlogger.info("Reset by " + sender_nick)
    raise RatBotResetError("Killed by reset command, see you soon")

  def cmd_join(self, c, params, sender_nick, from_channel):
    if len(params) > 0:
      c.join(params[0])
    else:
      self.reply(c, sender_nick, from_channel, "Failed - Please specify a channel to join")

  def cmd_part(self, c, params, sender_nick, from_channel):
    chan = None
    if len(params) > 0:
      chan = params[0]
    elif from_channel != None:
      chan = from_channel
    else:
      self.reply(c,sender_nick, from_channel, "Failed - Where do you want me to part from?")
    if chan is not None:
      c.part(chan)

  def cmd_help(self, c, params, sender_nick, from_channel):
    self.reply(c,sender_nick, None, "Commands:")
    for cmd, attribs in self.cmd_handlers.items():
      self.reply(c,sender_nick, None, "  {0:10}: {1}; Params:".format(
        cmd,
        attribs[0],
        ))
      for switch in attribs[1]:
        self.reply(c,sender_nick, None, "    " + switch)

  def cmd_readout(self, c, params, sender_nick, from_channel):
    try:
      pid = int(params[0])
      proc = self.processes[pid]
      sender_nick = sender_nick or proc.sender_nick
      from_channel = from_channel or proc.from_channel
      while not proc.out_queue.empty():
        tp = proc.out_queue.get_nowait()
        if isinstance(tp, Exception):
          self.reply(c,sender_nick, from_channel,
              "\0034Unexpected Error\017: {}".format(tp))
        if isinstance(tp, Systemsearch):
          if tp.origin_systems:
            if '-f' in tp.args:
              plen = len(tp.origin_systems)
            else:
              plen = 1
            for rec in tp.origin_systems[:plen]:
              self.reply(c,sender_nick, from_channel,
                  "Found system \002%s\017 (\003%sMatching %d%%\017) at %s, %s" % (
                    rec[0]['name'],
                    4 if rec[1] < 80 else 7 if rec[1] < 95 else 3,
                    rec[1],
                    "(no coordinates)" if not 'coords' in rec[0] else "[{0[x]:.0f} : {0[y]:.0f} : {0[z]:.0f}]".format(rec[0]['coords']),
                    "(no close system searched)" if '-f' in tp.args else ("(no close system)" if not 'closest' in rec[0] else "{:.1f}Ly from \002{}\017".format(rec[0]['closest']['real_distance'], rec[0]['closest']['name']))
                    ))
      return proc
    except (IndexError, ValueError, KeyError):
      self.reply(c,sender_nick, from_channel, "Failed - Please pass a valid pid instead of {}".format(params[0]))
    except:
      self.reply(c,sender_nick, from_channel, "Failed - Unhandled Error")
      raise


  def cmd_signal(self, c, params, sender_nick, from_channel):
    self.reply(c,sender_nick, from_channel, "Not implemented yet, sorry")

  def cmd_search(self, c, params, sender_nick, from_channel):
    self.botlogger.debug('Calling search')
    try:
      jp = " ".join(params)
      if jp in self.cooldown:
        delta = datetime.now() - self.cooldown[jp]
        if delta < timedelta(seconds=180):
          self.reply(c, sender_nick, from_channel, "I'm afraid I can't do that Dave. This search was just started {}s ago".format(delta.seconds))
      else:
        self.cooldown[jp] = datetime.now()
        proc = processing.ProcessManager(params, sender_nick=sender_nick, from_channel=from_channel)
        self.botlogger.info("Received command: "+" ".join(params))
        self.processes[proc.pid]=proc
        self.processes_by_qout[proc.out_queue._reader]=proc
        #self.select_on.append(proc.out_queue._reader)
        qconn = QConnection(c, self, proc)
        self.reactor.connections.append(qconn)

        self.reply(c,sender_nick, from_channel, proc.start_result)
        return proc
    except:
      self.reply(c,sender_nick, from_channel, "Failed to start process")
      self.botlogger.exception("Failed to start process")
      return None
  
  def cmd_fact(self, c, params, sender_nick, from_channel):
    facts = {
        'pcfr': 'To send a friend request, go to the menu (\002Hit ESC\017), click \002friends and private groups\017, and click \002ADD FRIEND\017',
        'pcwing': 'To send a wing request, go to the comms panel (\002Default key 2\017), \002hit ESC\017 to get out of the chat box, and move to the second panel (\002Default key E\017). Then select the CMDR you want to invite to your wing and select \002Invite to wing\017.',
        'pcbeacon': 'To drop a wing beacon, go to the right-side panel (\002Default key 4\017), navigate to the functions screen (\002Default key Q\017), select \002BEACON\017 and set it to \002WING\017',
        'xfr': 'To add the rats to your friends list press the XBOX button once, then press the RB button once, select the friends tile and press A to enter your friends list. Now press Y and search for the rat\'s name.',
        'xwing': 'To add the rats to your wing hold the X button and press up on the D-pad, press RB once, then select the name of a rat and select [Invite to wing]',
        'xbeacon': 'To light your wing beacon hold X and press RIGHT on the D-pad. Press the LB button once then select beacon and set it from OFF to WING',
        }
    if len(params) > 0:
      if params[0] in facts.keys():
        self.reply(c,sender_nick, from_channel, facts[params[0]])
      else:
        self.reply(c,sender_nick, from_channel, 'No fact called ' + params[0])
    else:
      self.reply(c, sender_nick, None, 'Available facts:')
      for k in sorted(facts.keys()):
        self.reply(c, sender_nick, None, k + ' -> ' + facts[k])

  def handle_PING(self, msg):
    chunk = msg[5:]
    self.send("PONG %s" % chunk)

  def reply(self, c, nick,channel,msg):
    self.botlogger.debug("reply nick: %s, channel: %s" % (nick, channel))
    to = channel if channel else nick
    if to == None:
      raise RatBotError('No recipient for privmsg')

    c.privmsg(to, msg)


  def send(self, msg):
    now = time.time()
    if self.lastmsgtime != None:
      elapsed = now - self.lastmsgtime
      if elapsed < self.delay:
        time.sleep(self.delay - elapsed)

    self.botlogger.debug(">> " + str(msg.replace("\r\n",'\\r\\n').encode()))
    self.socket.send(msg.encode())
    self.lastmsgtime = time.time()

def main():
  import sys
  if len(sys.argv) < 4:
    print("Usage: testbot <server[:port]> <channel> <nickname> [debug]")
    sys.exit(1)

  s = sys.argv[1].split(":", 1)
  server = s[0]
  if len(s) == 2:
    try:
      port = int(s[1])
    except ValueError:
      print("Error: Erroneous port.")
      sys.exit(1)
  else:
    port = 6667
  channels = sys.argv[2].split(",")
  nickname = sys.argv[3]
  debug = len(sys.argv) >= 5

  bot = TestBot(channels, nickname, server, port, debug)
  bot.start()

if __name__ == "__main__":
  main()
