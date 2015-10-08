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
import json
from datetime import datetime, timedelta
# 3Plib imports
import irc.bot
import irc.strings
from irc.client import ip_numstr_to_quad, ip_quad_to_numstr, Connection
# custom imports
from botlib import processing
from botlib.systemsearch import Systemsearch
import botlib.systemsearch

FACTS = json.load(open('facts.json'))

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
    self.chanlog = {}
    self.grabbed = {}
    self.processes = {}
    self.processes_by_qout = {}
    self.cooldown = {}
    self.cmd_handlers = {
        # bot management
        'die': [ 'Kills the bot.', [], self.cmd_die, True ],
        'reset': [ 'This command resets the bot', [], self.cmd_reset, False ],
        'join': [ 'Makes the bot join a channel', ['channel name'],
          self.cmd_join, True ],
        'part': [ 'Makes the bot part a channel',
          ['channel name (current channel if parameter not present and command issued from a channel)'], self.cmd_part, True ],
        'help': [ 'Prints help message listing commands', [], self.cmd_help, False ],
        # process control
#        'signal': [ 'Creates a new case', ['Client name', 'Client system', 'Client OX status (Empty for fine)'], self.cmd_signal],
        'search': [ 'Search for a simply-named system',
          ['-x Extended Search: Do not restrict search by system name length',
           '-f Fuzzy Search: Return just the three best-matching system names for search term',
           '-l / -ll / -lll Large radius: Search for close systems in 20 / 30 / 50Ly radius instead of 10', 'System'],
          self.cmd_search, False],
        'fact': [ 'Recites a fact',
          ['Name of fact, empty prints all available facts' ],
          self.cmd_fact, False ],
        'grab': [ 'Grabs last message from nick',
          ['Nick to grab'],
          self.cmd_grab, False ],
        'quote': [ 'Recites grabbed messages from a nick',
          ['Previously grabbed nick'],
          self.cmd_quote, False ],
        'clear': [ 'Clears grab list completely',
          [],
          self.cmd_clear, False ],
        'inject': [ 'Injects custom text into grab list',
          ['Nick to inject for', 'Message'],
          self.cmd_inject, False ],
        'masters': ['Lists masters', [], self.cmd_masters, False ]
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
    if not e.target in self.chanlog:
      self.chanlog[e.target] = {}
    self.chanlog[e.target][e.source.nick] = e.arguments[0]

    self.botlogger.debug('Pubmsg arguments: {}'.format(e.arguments))
    if e.arguments[0].startswith('!'):
      self.botlogger.debug('detected command {}'.format(e.arguments[0][1:]))
      self.do_command(c, e, e.arguments[0][1:])
    a = e.arguments[0].split(":", 1)
    self.botlogger.debug("Split up: %s" % a)
    if len(a) > 1 and len(a[0]) > 0 and irc.strings.lower(a[0]) == irc.strings.lower(self.connection.get_nickname()):
      self.do_command(c, e, a[1].strip())

  def do_command(self, c, e, cmd):
    nick = irc.strings.IRCFoldedCase(e.source.nick)
    c = self.connection

    split = cmd.split()
    cmd = split[0]
    args = split[1:]

    if cmd in self.cmd_handlers:
      chan = self.channels[e.target] if e.target in self.channels else None
      privers = list(chan.opers()) + list(chan.voiced()) + list(chan.owners()) + list(chan.halfops()) if chan is not None else []
      self.botlogger.debug("Privers: {}".format(", ".join(privers)))
      self.botlogger.debug("{} is {}in privers".format(nick, "" if nick in privers else "not "))

      if ((self.cmd_handlers[cmd][3]) == False) or (nick in privers):
        self.cmd_handlers[cmd][2](c, args, nick, e.target)
      else:
        self.reply(c, nick, e.target, "Privileged operation - can only be called from a channel by someone having ~@%+ flag")
  
  def cmd_die(self, c, params, sender_nick, from_channel):
    self.botlogger.info("Killed by " + sender_nick)
    if len(params) > 0:
      raise RatBotKilledError(" ".join(params))
    else:
      raise RatBotKilledError("Killed by !die")

  def cmd_grab(self, c, params, sender_nick, from_channel):
    if from_channel is None:
      self.reply(c, sender_nick, from_channel, "This command only works in a channel")
    elif len(params) < 1:
      self.reply(c, sender_nick, from_channel, "Sorry, I need a nick to grab")
    else:
      grabnick = params[0]
      line = self.chanlog.get(from_channel, {}).get(grabnick, None)
      if line is None:
        self.reply(c, sender_nick, from_channel, "Sorry, couldn't find a grabbable line, did you misspell the nick?")
      else:
        if not grabnick in self.grabbed:
          self.grabbed[grabnick] = [line]
        else:
          self.grabbed[grabnick].append(line)
        self.reply(c, sender_nick, from_channel, "Grabbed '{}' from {} ({} grabbed lines now)".format(line, grabnick, len(self.grabbed[grabnick])))

  def cmd_quote(self, c, params, sender_nick, from_channel):
    if len(params) < 1:
      self.reply(c, sender_nick, from_channel, "Sorry, I need a nick to grab")
    else:
      grabnick = params[0]
      lines = self.grabbed.get(grabnick, None)
      if lines is None:
        self.reply(c, sender_nick, from_channel, "Sorry, couldn't find grabbed lines, did you misspell the nick?")
      else:
        for line in lines:
          self.reply(c, sender_nick, from_channel, "<{}> {}".format(grabnick, line))

  def cmd_clear(self, c, params, sender_nick, from_channel):
    self.grabbed = {}

  def cmd_inject(self, c, params, sender_nick, from_channel):
    if len(params) < 2:
      self.reply(c, sender_nick, from_channel, "Sorry, I need a nick and some text.")
    else:
      grabnick = params[0]
      grabtext = " ".join(params[1:])
      if not grabnick in self.grabbed:
        self.grabbed[grabnick] = []
      self.grabbed[grabnick].append("{} [INJECTED BY {}]".format(grabtext, sender_nick))

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
      self.reply(c,sender_nick, None, "  {0:10}: {1}{2}".format(
        cmd,
        attribs[0],
        " (Privileged)" if attribs[3] else ""
        ))
      for switch in attribs[1]:
        self.reply(c,sender_nick, None, "    " + switch)

  def cmd_masters(self, c, params, sender_nick, from_channel):
# list(self.channels[e.target].opers()) + list(self.channels[e.target].voiced()) + list(self.channels[e.target].owners()) + list(self.channels[e.target].halfops()))
    if from_channel is None:
      self.reply(c, sender_nick, None, "Call this from a channel")
    else:
      self.reply(c,sender_nick, None, "Current masters in {}:".format(from_channel))
      chan = self.channels[from_channel]
      for t,l in [('Owners', chan.owners()), ('Opers', chan.opers()), ('Hops', chan.halfops()), ('Voicers', chan.voiced())]:
        self.reply(c, sender_nick, None, "{}: {}".format(t, ", ".join(l)))

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
          if len(tp.origin_systems) > 0:
            if '-f' in tp.args:
              plen = len(tp.origin_systems)
            else:
              plen = 1
            for rec in tp.origin_systems[:plen]:
              self.reply(c,sender_nick, from_channel,
                  "Found system \002%s\017 (\003%sMatching %d%%\017) at %s, %s" % (
                    rec['name'],
                    4 if rec['ratio'] < 80 else 7 if rec['ratio'] < 95 else 3,
                    rec['ratio'],
                    "(no coordinates)" if not 'coords' in rec else "[{0[x]:.0f} : {0[y]:.0f} : {0[z]:.0f}]".format(rec['coords']),
                    "(no close system searched)" if '-f' in tp.args else ("(no close system)" if not 'closest' in rec else "{:.1f}Ly from \002{}\017".format(rec['closest']['real_distance'], rec['closest']['name']))
                    ))
          else:
            self.reply(c, sender_nick, from_channel, "No systems found")
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
    if len(params) > 0:
      if params[0] in FACTS.keys():
        self.reply(c,sender_nick, from_channel, FACTS[params[0]])
      else:
        self.reply(c,sender_nick, from_channel, 'No fact called ' + params[0])
    else:
      self.reply(c, sender_nick, None, 'Available FACTS:')
      for k in sorted(FACTS.keys()):
        self.reply(c, sender_nick, None, k + ' -> ' + FACTS[k])

  def handle_PING(self, msg):
    chunk = msg[5:]
    self.send("PONG %s" % chunk)

  def reply(self, c, nick,channel,msg):
    self.botlogger.debug("reply nick: %s, channel: %s" % (nick, channel))
    to = channel if channel else nick
    if to is None:
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

  bot = None
  while True:
    try:
      bot = TestBot(channels, nickname, server, port, debug)
      bot.start()
    except (RatBotKilledError, KeyboardInterrupt) as e:
      bot.disconnect("".join(e.args))
      raise
    except:
      logging.exception("Thrown")
      bot.disconnect("Thrown")
      continue

if __name__ == "__main__":
  main()
