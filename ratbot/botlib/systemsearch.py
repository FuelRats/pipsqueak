import requests
import json
import math
import os
from functools import reduce
from fuzzywuzzy import fuzz

DEBUG = False

SYSTEMS_URL = "http://www.edsm.net/api-v1/systems"
SPHERE_URL = "http://www.edsm.net/api-v1/sphere-systems"

sysnames = []
if os.path.isfile('systems.json'):
  sysnames = json.load(open('systems.json'))
else:
  sysnames = requests.get(SYSTEMS_URL,{'coords':1}).json()

def multifind(name, full_length=False):
  name = name.lower()
  if DEBUG:
    print('SSearch DEBUG multifind ', name)
  l = len(name)
  best = [None,None,None]
  for candidate in sysnames:
    cname = candidate['name'].lower()
    cl = len(cname)
    if full_length or (cl > 0.85*l and cl < 1.15*l):
      candidate['ratio'] = fuzz.ratio(name, cname)
      if best[0] is None or candidate['ratio'] > best[0]['ratio']:
        best[2] = best[1]
        best[1] = best[0]
        best[0] = candidate
      elif best[1] is None or candidate['ratio'] > best[1]['ratio']:
        best[2] = best[1]
        best[1] = candidate
      elif best[2] is None or candidate['ratio'] > best[2]['ratio']:
        best[2] = candidate
  return list(filter(lambda x: x is not None, best))

def dist_square(a,b):
  x = a['x'] - b['x']
  y = a['y'] - b['y']
  z = a['z'] - b['z']

  return x*x + y*y + z*z

def smallest(x,y):
  try:
    if not x:
      return y
    if y['distance'] < x['distance'] and y['name'].count(' ') <= 1:
      return y
    else:
      return x
  except:
    print('x: ', x)
    print('y: ', y)
    raise

class Systemsearch:
  def __init__(self, args, sysname):
    self.args = args
    self.sysname = sysname
    self.origin_systems = None
    self.close_systems = None

  def __str__(self):
    return "Systemsearch for {}, options {}, found origin systems {}, found close systems {}".format(self.sysname, self.args, self.origin_systems, self.close_systems)

  def do_search(self):
    if '-r' in self.args:
      sysnames = requests.get(SYSTEMS_URL,{'coords':1}).json()
      with open('systems.json', 'w') as f:
        json.dump(sysnames, f)

    if self.sysname is None:
      return

    self.origin_systems = multifind(self.sysname, '-x' in self.args)
    if DEBUG:
      print('SSearch DEBUG Origin systems found: ', self.origin_systems)
    if '-f' in self.args or len(self.origin_systems) < 1:
      return

    radius = 10
    if '-l' in self.args:
      radius = 20
    elif '-ll' in self.args:
      radius = 30
    elif '-lll' in self.args:
      radius = 50

    if not 'coords' in self.origin_systems[0]:
      return

    sphereparams = {'sysname': self.origin_systems[0]['name'], 'radius': radius, 'coords': 1}
    sphererq = requests.get(SPHERE_URL, sphereparams)
    sphererq.raise_for_status()

    try:
     self.close_systems = sphererq.json()
    except:
      raise Exception("Failed to parse EDSM sphere result searching for %s: %s " % (self.origin_systems[0][0]['name'], (sphererq.text if sphererq.text != '' else '(Empty)')))

    origin_name = self.origin_systems[0]['name'].lower()
    origin_coords = self.origin_systems[0]['coords']
    for system in self.close_systems:
      if system['name'].lower() == origin_name:
        system['distance'] = 999
      else:
        system['distance'] = dist_square(origin_coords, system['coords'])

    if DEBUG:
      print('SSearch DEBUG Close systems: ', self.close_systems)

    closest = reduce(smallest, self.close_systems, None)
    closest['real_distance'] = math.sqrt(closest['distance']) if closest['distance'] != 999 else 0

    if DEBUG:
      print('SSearch DEBUG Closest system: ', closest)

    self.origin_systems[0]['closest'] = closest

if __name__ == '__main__':
  DEBUG = True
  import sys
  print('Switches: ',sys.argv[1:-1],' System: ', sys.argv[-1])
  search = Systemsearch(sys.argv[1:-1],sys.argv[-1])
  search.do_search()
