import socket
import logging
import logging.handlers
import time
import sys
import ssl
import signal
import os

from select import select

import botlib.processing
from botlib.systemsearch import Systemsearch
import botlib.systemsearch

sysloghandler = logging.handlers.SysLogHandler(address='/dev/log')
logging.basicConfig(format='moepbot %(levelname)s: %(message)s', level=logging.DEBUG, handlers=[sysloghandler])

sig_kill = False

def signal_handler(signum, frame):
  global sig_kill
  if signum == signal.SIGINT:
    if not sig_kill:
      sig_kill = True
    else:
      raise KeyBoardInterrupt("Killed by last-ditch killswitch. Please inform lerlacher.")

def chunks(l, n):
  """ Yield successive n-sized chunks from l.
  """
  for i in range(0, len(l), n):
    yield l[i:i+n]


class RatBotError(Exception):
  pass

class RatBotKilledError(RatBotError):
  pass

class RatBotResetError(RatBotError):
  pass

class Moepbot:
  STATE = {
       'idle':          0
       ,'connecting':   1
       ,'registered':  2
       ,'joining':      3
       ,'ready':        4
      }

  def __init__(self, connect = True):
    signal.signal(signal.SIGINT, signal_handler)
    self.working_dir = '/'
    self.host = "irc.freenode.net"
    self.port = 6667
    self.nick = "bmoep"
    self.ident = "moepbot"
    self.realname = "moepbot"
    self.channels = ["#moep80211"]
    self.serverpass = None
    self.cafile = None
    self.delay = 0.5
    self.lastmsgtime = None
    self.commandchar = "!"
    self.private_reply = False
    self.nick_timeout = 0
    self.debug = False

    self.version = 'PipSqueak 0.0'

    self.state = self.STATE['idle']
    logging.debug('transitioned to idle state')
    self.processes = {}
    self.processes_by_qout = {}
    self.queue_out = []
    self.select_on = []
    self.queue = ""

    self.cmd_handlers = {
        # bot management
        'die': [ 'Kills the bot.', [], self.cmd_die ],
        'reset': [ 'This command resets the bot', [], self.cmd_reset ],
        'join': [ 'Makes the bot join a channel', ['channel name'], self.cmd_join ],
        'part': [ 'Makes the bot part a channel', ['channel name (current channel if parameter not present and command issued from a channel)'], self.cmd_part ],
        'help': [ 'Prints help message listing commands', [], self.cmd_help ],
        # process control
#        'signal': [ 'Creates a new case', ['Client name', 'Client system', 'Client OX status (Empty for fine)'], self.cmd_signal],
        'search': [ 'Search for a simply-named system', ['-x Extended Search: Do not restrict search by system name length', '-f Fuzzy Search: Return just the three best-matching system names for search term', '-l / -ll / -lll Large radius: Search for close systems in 20 / 30 / 50Ly radius instead of 10', 'System'], self.cmd_search],
        'fact': [ 'Recites a fact', ['Name of fact, empty prints all available facts' ], self.cmd_fact ],
        }

  def handle_PRIVMSG(self, split_msg):
    sender_nick = split_msg[0].split('!')[0][1:]
    to = split_msg[2]
    ## TODO: Make channel detection more robust
    if to[0]=='#':
      from_channel = to
    else:
      from_channel = None

    text = split_msg[3:]
    # remove colon
    text[0] = text[0][1:]

    # detect cmd
    cmd = None
    if len(text[0]) > 0 and text[0][0] == self.commandchar:
      cmd = text[0][1:]
      params = text[1:]
    elif text[0] == self.currnick + ':':
      cmd = text[1]
      params = text[2:]
    elif from_channel == None:
      cmd = text[0]
      params = text[1:]

    if cmd in self.cmd_handlers:
      self.cmd_handlers[cmd][2](params, sender_nick, from_channel)
    elif cmd == '\x01VERSION\x01':
      self.reply(sender_nick, from_channel, self.version)
    elif cmd is not None:
      print("Unrecognized command '%s'" % (cmd, ))
      print(split_msg)

  def cmd_die(self, params, sender_nick, from_channel):
    logging.info("Killed by " + sender_nick)
    raise RatBotKilledError("Killed by die command");

  def cmd_reset(self, params, sender_nick, from_channel):
    logging.info("Reset by " + sender_nick)
    raise RatBotResetError("Killed by reset command, see you soon")

  def cmd_join(self, params, sender_nick, from_channel):
    if len(params) > 0:
      chan = params[0]
      self.send("JOIN :%s\r\n" % (chan))
    else:
      self.reply(sender_nick, from_channel, "Failed - Please specify a channel to join")

  def cmd_part(self, params, sender_nick, from_channel):
    chan = None
    if len(params) > 0:
      chan = params[0]
    elif from_channel != None:
      chan = from_channel
    else:
      self.reply(sender_nick, from_channel, "Failed - Where do you want me to part from?")
    if chan is not None:
      self.send("PART :%s\r\n" % (chan,))

  def cmd_cd(self, params, sender_nick, from_channel):
    if len(params) > 0:
      dir = " ".join(params)
      if os.path.exists(dir):
        os.chdir(dir)
        self.reply(sender_nick, from_channel, "Changed dir to %s" % (dir,))
      else:
        self.reply(sender_nick, from_channel, "No such dir %s" % (dir,))
    else:
      self.reply(sender_nick, from_channel, "No directory specified")

  def cmd_help(self, params, sender_nick, from_channel):
    self.reply(sender_nick, None, "Commands:")
    for cmd, attribs in self.cmd_handlers.items():
      self.reply(sender_nick, None, "  {0:10}: {1}; Params:".format(
        cmd,
        attribs[0],
        ))
      for switch in attribs[1]:
        self.reply(sender_nick, None, "    " + switch)


  def cmd_char(self, params, sender_nick, from_channel):
    if len(params) > 0 and len(params[0][0]) > 0:
      grp = params[0][0]
      self.commandchar = grp

    self.reply(sender_nick, from_channel, "Commandchar: %s" % (self.commandchar,))

  def cmd_replytoggle(self, params, sender_nick, from_channel):
    self.private_reply = not self.private_reply
    self.reply(sender_nick, from_channel, "Private reply is now %s." % (str(self.private_reply),))

  def cmd_popen(self, params, sender_nick, from_channel):
    try:
      proc = processing.ProcessManager(params, sender_nick=sender_nick, from_channel=from_channel)
      logging.info("Received command: "+" ".join(params))
      if proc.launch_result[0] == processing.Q_PID:
        self.processes[proc.pid]=proc
        self.processes_by_qout[proc.out_queue._reader]=proc
        self.select_on.append(proc.out_queue._reader)
        self.reply(sender_nick, from_channel, "Started %s with pid %d" % (params[0],proc.pid))
        return proc
      else:
        self.reply(sender_nick, from_channel, "Failed to start process: " + str(proc.launch_result[1][2]))
        return None
    except:
      self.reply(sender_nick, from_channel, "Failed to start process")
      return None

  def cmd_readout(self, params, sender_nick, from_channel):
    try:
      pid = int(params[0])
      proc = self.processes[pid]
      sender_nick = sender_nick or proc.sender_nick
      from_channel = from_channel or proc.from_channel
      while not proc.out_queue.empty():
        tp = proc.out_queue.get_nowait()
        if isinstance(tp, Exception):
          self.reply(sender_nick, from_channel,
              "\0034Unexpected Error\017: {}".format(tp))
        if isinstance(tp, Systemsearch):
          if tp.origin_systems:
            if '-f' in tp.args:
              plen = len(tp.origin_systems)
            else:
              plen = 1
            for rec in tp.origin_systems[:plen]:
              self.reply(sender_nick, from_channel,
                  "Found system \002%s\017 (\003%sMatching %d%%\017) at %s" % (
                    rec[0]['name'],
                    4 if rec[1] < 80 else 7 if rec[1] < 95 else 3,
                    rec[1],
                    "(no coordinates)" if not 'coords' in rec[0] else "[{0[x]:.0f} : {0[y]:.0f} : {0[z]:.0f}]".format(rec[0]['coords'])
                    ))
          if tp.closest_system:
            self.reply(sender_nick, from_channel,
                "Closest system is \002{}\017 for {:.1f}Ly".format(tp.closest_system['name'], tp.closest_system['real_distance']))
      return proc
    except (IndexError, ValueError, KeyError):
      self.reply(sender_nick, from_channel, "Failed - Please pass a valid pid instead of {}".format(params[0]))
    except:
      self.reply(sender_nick, from_channel, "Failed - Unhandled Error")
      raise

  def cmd_type(self, params, sender_nick, from_channel):
    try:
      pid = int(params[0])
      proc = self.processes[pid]
      line = " ".join(params[1:])
      proc.in_queue.put((processing.Q_SND,line+"\n"))
      self.reply(sender_nick, from_channel, "Sent")
    except (IndexError, ValueError, KeyError):
      self.reply(sender_nick, from_channel, "Failed - Please pass a valid pid")
    except:
      self.reply(sender_nick, from_channel, "Failed - Unhandled error")
      raise

  def cmd_eof(self, params, sender_nick, from_channel):
    try:
      pid = int(params[0])
      proc = self.processes[pid]
      proc.in_queue.put((processing.Q_EOF,None))
      self.reply(sender_nick, from_channel, "Closed")
    except (IndexError, ValueError, KeyError):
      self.reply(sender_nick, from_channel, "Failed - Please pass a valid pid")
    except:
      self.reply(sender_nick, from_channel, "Failed - Unhandled error")
      raise

  def cmd_kill(self, params, sender_nick, from_channel):
    try:
      pid = int(params[0])
      proc = self.processes[pid]
      sig = 15
      if len(params) > 1:
        try:
          sig = int(params[1])
        except:
          self.reply(sender_nick, from_channel, "Please pass a numeric signal or no signal to send SIGKILL")
          sig = -1

      if sig > 0:
        proc.in_queue.put((processing.Q_KIL,sig))
        self.reply(sender_nick, from_channel, "Sent Kill Signal")
    except (IndexError, ValueError, KeyError):
      self.reply(sender_nick, from_channel, "Failed - Please pass a valid pid (Use popen to kill a process not managed by the bot)")
    except:
      self.reply(sender_nick, from_channel, "Failed")
      raise

  def cmd_status(self, params, sender_nick, from_channel):
    try:
      pid = int(params[0])
      proc = self.processes[pid]
      retcode = proc.poll()
      if retcode == None:
        self.reply("%d is running\r\n" % (pid,))
      else:
        self.reply("%d terminated with retcode %d\r\n" % (pid, retcode))
    except (IndexError, ValueError, KeyError):
      self.reply(sender_nick, from_channel, "Failed - Please pass a valid pid")
    except:
      self.send("PRIVMSG %s :Failed\r\n" % (rcpt,))
      raise

  def cmd_signal(self, params, sender_nick, from_channel):
    self.reply(sender_nick, from_channel, "Not implemented yet, sorry")

  def cmd_search(self, params, sender_nick, from_channel):
    try:
      proc = processing.ProcessManager(params, sender_nick=sender_nick, from_channel=from_channel)
      logging.info("Received command: "+" ".join(params))
      self.processes[proc.pid]=proc
      self.processes_by_qout[proc.out_queue._reader]=proc
      self.select_on.append(proc.out_queue._reader)

      self.reply(sender_nick, from_channel, proc.start_result)
      return proc
    except:
      self.reply(sender_nick, from_channel, "Failed to start process")
      return None
  
  def cmd_fact(self, params, sender_nick, from_channel):
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
        self.reply(sender_nick, from_channel, facts[params[0]])
      else:
        self.reply(sender_nick, from_channel, 'No fact called ' + params[0])
    else:
      self.reply(sender_nick, None, 'Available facts:')
      for k in sorted(facts.keys()):
        self.reply(sender_nick, None, k + ' -> ' + facts[k])

  def handle_PING(self, msg):
    chunk = msg[5:]
    self.send("PONG %s" % chunk)

  def reply(self,nick,channel,msg):
    logging.debug("reply nick: %s, channel: %s, private reply: %s" % (nick, channel,str(self.private_reply)))
    if self.private_reply:
      to = nick
    else:
      to = channel if channel else nick
    if to == None:
      raise RatBotError('No recipient for privmsg')

    for chunk in chunks(msg, 400):
      self.send("PRIVMSG %s :%s\r\n" % (to, chunk))


  def send(self, msg):
    now = time.time()
    if self.lastmsgtime != None:
      elapsed = now - self.lastmsgtime
      if elapsed < self.delay:
        time.sleep(self.delay - elapsed)

    logging.debug(">> " + str(msg.replace("\r\n",'\\r\\n').encode()))
    self.socket.send(msg.encode())
    self.lastmsgtime = time.time()
