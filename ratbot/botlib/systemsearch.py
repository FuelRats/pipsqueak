import requests
import json
import math
import os
from datetime import datetime, timedelta
from functools import reduce
from fuzzywuzzy import fuzz

DEBUG = False

SYSTEMS_URL = "http://www.edsm.net/api-v1/systems"
SPHERE_URL = "http://www.edsm.net/api-v1/sphere-systems"

"""
  Load system names from file or directly from EDSM
"""
sysnames = []
if os.path.isfile('systems.json'):
  sysnames = json.load(open('systems.json'))
else:
  sysnames = requests.get(SYSTEMS_URL,{'coords':1}).json()
  with open('systems.json', 'w') as f:
    json.dump(sysnames, f)

"""
  multifind compares the search term against all names in the system name list and returns the three best matches according to levenshtein distance
"""
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

"""
  Squared distance (sqrt missing as optimisation)
"""
def dist_square(a,b):

  x = a['x'] - b['x']
  y = a['y'] - b['y']
  z = a['z'] - b['z']

  return x*x + y*y + z*z

"""
  Reduce kernel to find closest simple-named system (simple-named == at most one space in name)
"""
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
    self.reloaded = None

  def __str__(self):
    return "Systemsearch for {}, options {}, found origin systems {}, found close systems {}".format(self.sysname, self.args, self.origin_systems, self.close_systems)

  def do_search(self):
    """
      Searches the system list for the system name given in self.sysname, with self.args
        * If '-r' is given, reload system name list
        * find three closest-matching system names using multifind
        * if '-d' is given, find a simple-named system close to the system with the best name match. The search radius for this is adjustable using the -l/-ll/-lll argument.
    """
    if '-r' in self.args:
      """
        Only reload if current list is older than 12 hours
      """
      is_old = datetime.now() - datetime.fromtimestamp(os.path.getmtime('systems.json')) > timedelta(hours=12)
      if is_old:
        if DEBUG:
          print('requesting new system list')
        sysnames = requests.get(SYSTEMS_URL,{'coords':1}).json()
        with open('systems.json', 'w') as f:
          json.dump(sysnames, f)
        if DEBUG:
          print('Done with system reload')
        self.reloaded = "Reloaded system list."
      else:
        self.reloaded = "System list too young."

    """
      If we don't have a system name to search for, just return
    """
    if self.sysname is None or len(self.sysname) == 0:
      return

    """
      Run multifind
    """
    self.origin_systems = multifind(self.sysname, '-x' not in self.args)
    if DEBUG:
      print('SSearch DEBUG Origin systems found: ', self.origin_systems)
    """
      Return if no -d or no systems found
    """
    if '-d' not in self.args or len(self.origin_systems) < 1:
      return

    """
      adjust search radius
    """
    radius = 10
    if '-l' in self.args:
      radius = 20
    elif '-ll' in self.args:
      radius = 30
    elif '-lll' in self.args:
      radius = 50

    """
      Can't do sphere search if we don't have coordinates for the system
    """
    if not 'coords' in self.origin_systems[0]:
      return

    """
      Sphere search request to EDSM API, because this is faster if off-loaded
    """
    sphereparams = {'sysname': self.origin_systems[0]['name'], 'radius': radius, 'coords': 1}
    sphererq = requests.get(SPHERE_URL, sphereparams)
    sphererq.raise_for_status()

    try:
     self.close_systems = sphererq.json()
    except:
      raise Exception("Failed to parse EDSM sphere result searching for %s: %s " % (self.origin_systems[0][0]['name'], (sphererq.text if sphererq.text != '' else '(Empty)')))

    """
      Now calculate distance between origin system and systems in the sphere
    """
    origin_name = self.origin_systems[0]['name'].lower()
    origin_coords = self.origin_systems[0]['coords']
    for system in self.close_systems:
      if system['name'].lower() == origin_name:
        """
          But penalise the origin system itself
        """
        system['distance'] = 999
      else:
        system['distance'] = dist_square(origin_coords, system['coords'])

    if DEBUG:
      print('SSearch DEBUG Close systems: ', self.close_systems)

    """
      Reduce list to smallest distance and calculate real distance
    """
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
