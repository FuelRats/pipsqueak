from datatetime import datetime

LETTERS = ['a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p','q','r','s','t','u','w','x','y','z']

class FuelCase:
  def __init__(self, id, client, system, oxygen):
    self.id = id
    self.client = client
    self.system = system
    self.oxygen = oxygen
    self.cmdr = 'Unknown'
    self.nearsys = None
    if self.system.count(' ') > 1:
      self.nearsys = 'Unknown'

  def get_facts():
    oxstr = 'CASE RED' if self.oxygen else 'Oxygen ok'
    nearsysstr = '' if not self.nearsys else ' (' + self.nearsys + ')'

    return "Case {}: {} (CMDR {}), {}{}, oxstr".format(self.id, self.client, self.cmdr, self.system, nearsysstr, oxstr)


class FuelBoard:
  def __init__(se;f):
    self.board = {}
    self.idx = 0

  def ratsignal(self, client, system, oxygen):
    case = FuelCase(self.idx, client, system, oxygen)

    self.board[self.idx] = case
    self.idx = (self.idx + 1) % 26

    return case

  def query(self, id):
    return self.board.get(id)



