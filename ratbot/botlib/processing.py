import select
import sys
from multiprocessing import Process, Queue
import random

from botlib.systemsearch import Systemsearch

import logging
botlogger = logging.getLogger('RatBotLogger')

def argfilter(args):
  switches = []
  sys = []
  for arg in args:
    if arg[0] == '-':
      switches.append(arg)
    else:
      sys.append(arg)
  return switches, " ".join(sys)

class ProcessManager:
  def __init__(self, args, run=True, sender_nick=None, from_channel=None):
    self.sender_nick = sender_nick
    self.from_channel = from_channel
    self.args, self.system = argfilter(args)
    self.in_queue = Queue()
    self.out_queue = Queue()
    self.process = None
    self.pid = None
    if run:
      self.start_result = self.start_process()

  def start_process(self):
    if self.process == None:
      self.process=Process(target=self.runner,args=((self.args, self.system), self.in_queue,self.out_queue))
      self.process.start()
      print("process started")
      self.pid = random.randint(0,99999)
      if '-d' in self.args:
        if self.system == "":
          if '-r' in self.args:
            return "Reloading system list."
          else:
            return "This is going to do nothing."
        else:
          return "Searching closest simple-named system for '%s', %s, %s" % (
              self.system,
              '20 Ly radius' if '-l' in self.args else '10Ly radius',
              'full matching' if '-x' not in self.args else 'matching against similar-length system names'
              )
      else:
        if self.system == "":
          if '-r' in self.args:
            return "Reloading system list."
          else:
            return "This is going to do nothing."
        return "Fuzzy searching for '%s' against system list, %s" % (
            self.system,
            'full matching' if '-x' not in self.args else 'matching against similar-length system names'
            )

  def join_process(self):
    self.process.join()

  def runner(self, args,q_in, q_out):
    switches, system = args[0], args[1]

    search = Systemsearch(switches, system)
    try:
      search.do_search()
    except Exception as e:
      q_out.put(e)
      logging.exception(e)
    finally:
      q_out.put(search)
      logging.debug(search)
