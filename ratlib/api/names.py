"""
This is specifically named 'starsystem' rather than 'system' for reasons that should be obvious.

Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
import ratlib
import ratlib.api
import ratlib.api.http
import functools
from sopel.module import NOLIMIT
from enum import Enum

class Permissions(Enum):
    recruit = (0, None)
    rat = (1, "Sorry, but you need to be a registered and drilled Rat with an identified IRC nickname to use "
                        "this command.")
    dispatch = (2,"Sorry, but you need to be a dispatch or higher to use this command")
    overseer = (3, 'Sorry pal, you\'re not an overseer or higher!')
    op = (4, "This command is restricted for Ops and above only.")
    techrat = (5,'I am sorry, but this command is restricted for TechRats and above only.')
    netadmin = (6, "Hey Buddy, you know you need to be an identified NetAdmin to use this command, right?")


urljoin = ratlib.api.http.urljoin
savedratids = {}
savedratnames = {}
savedclientnames = {}
def getRatId(bot, ratname, platform=None):

    if ratname in savedratids.keys():
        element = savedratids.get(ratname)
        strippedname = removeTags(ratname)
        if (platform is None) and ((str(element['name']).lower()==str(ratname).lower()) or str(element['name']).lower()==str(strippedname).lower() or str(element['name']).lower()==str(strippedname.replace('_',' ')).lower()):
            # print('platform was None and '+ratname+' was in keys and the name matched. returning '+str(element))
            return element
        elif (platform == element['platform']) and ((str(element['name']).lower()==str(ratname).lower()) or str(element['name']).lower()==str(strippedname).lower() or str(element['name']).lower()==str(strippedname.replace('_',' ')).lower()):
            # print('platform was on the gotten name and names matched. Returning '+str(element))
            return element


    try:
        uri = '/nicknames/' + ratname
        # print('looking for name '+ratname)
        # print('uri: '+str(uri))
        result = callapi(bot=bot, method='GET', uri=uri)
        data = result['data']['attributes']['rows']
        # print(result)
        # print(data)
        returnlist = []
        strippedname = removeTags(ratname)
        if platform is None:
            if len(data) == 0:
                raise Exception
            firstmatch = data[0]
            retlist = []
            tempnam = 'unknown name'
            tempplat = 'unknown platform'
            nicknames = firstmatch['nicknames']
            tempAlias = [name.lower() for name in nicknames]

            # print("looping over firstmatch['rats']...")

            for ratobject in firstmatch['rats']:
                id = ratobject['id']
                tempnam = ratobject['name']
                tempplat = ratobject['platform']

                # print("tempnam = {}\ntempplat={}\n--------\nid={}".format(tempnam,tempplat, id))
                if (str(tempnam).lower()==str(ratname).lower()
                    or str(tempnam).lower()==str(strippedname).lower()
                    or str(tempnam).lower()==str(strippedname.replace('_', ' ')).lower()
                    or strippedname.lower() in tempAlias):
                        # print("appending rat!")
                        retlist.append({'id': id, 'name':tempnam , 'platform':tempplat})
            if len(retlist) == 0:
                ratnam = tempnam
                ratplat = tempplat
                # print("======\n setting ID to zero... because FIRETRUCK this")
                id = 0
            else:
                id = retlist[0]['id']
                ratnam = retlist[0]['name']
                ratplat = retlist[0]['platform']

            ret = {'id': id, 'name':ratnam , 'platform':ratplat}

        else:
            ret = {'id':None, 'name':None, 'platform':None}
            id = None
            ratnam = None
            if len(data) == 0:
                # print('data length 0')
                raise Exception
            for user in data:
                for ratobject in user['rats']:
                    ratnam = ratobject['name']
                    ratplat = ratobject['platform']
                    cmdr = ratobject['id']
                    rat = {'id':cmdr, 'platform':ratplat, 'name':ratnam}
                    # print("checking " + str(rat))
                    # print("platform is " + platform)
                    if rat['platform'] == platform:
                        # print("It matched!")
                        id = rat['id']
                        ret = {'id':cmdr, 'name': ratnam, 'platform':platform}
                        returnlist.append(ret)
            strippedname = removeTags(ratname)
            for retelement in returnlist:
                 if (str(retelement['name']).lower()==str(ratname).lower()) or (str(retelement['name']).lower()==str(strippedname).lower()) or (str(retelement['name']).lower()==str(strippedname.replace('_', ' ')).lower()):
                    # print("setting ret to " + str(retelement))
                    ret = retelement
        if ret != {'id':None, 'name':None, 'platform':None}:
            savedratids.update({ratname: ret})
            savedratnames.update({id: {'name': ratnam, 'platform': ret['platform'], 'id':ret['id']}})
        # print("returning " + str(ret))
        return ret
    except Exception as ex:
            # raise ex  # burn baby burn
            # print('Calling fallback on ratID search as no rat with registered nickname '+strippedname+' or '+ratname+' was found.')

            return idFallback(bot, ratname, platform=platform)


def idFallback(bot, ratname, platform=None):
    """
    Fallback to searching the commander Name instead of the linked account nickname.
    Args:
        bot: the bot to pull the config from
        ratname: the cmdrname to look for

    Returns:
        a dict with ['id'] which has the id it got, ['name'] the name it used to poll the api and
        if the api call returned an error or the rat wasn't found, ['error'] has the returned error object and
        ['description'] a description of the error.

    """
    strippedname = removeTags(ratname)
    # print('[NamesAPI] Had to call idFallback for '+str(ratname))
    print('[NamesAPI] had to call idFallback for {ratname} (strippedName = {strippedName})'.format(
            ratname=ratname, strippedName=strippedname))
    try:
        uri = '/rats?name=' + strippedname + (('&platform='+platform) if platform is not None else '')
        result = callapi(bot=bot, method='GET', uri=uri)
        # print(result)
        data = result['data']
        # print(data)
        firstmatch = data[0]
        id = firstmatch['id']
        ret =  {'id': id, 'name': strippedname, 'platform':firstmatch['attributes']['platform']}
        savedratids.update({ratname:ret})
        savedratnames.update({id:{'name':strippedname, 'platform':firstmatch['platform']}})
        return ret

    except (IndexError, KeyError) as ex:
                # print('no rats with that commandername or nickname or gamertag found.')
                return {'id': '0', 'name': ratname, 'error': ex, 'platform':'unknown',
                        'description': 'no rats with that commandername or nickname or gamertag found.'}
    except ratlib.api.http.APIError as ex:
        print('[NamesAPI] APIError: couldnt find RatId for ' + ratname)
        return {'id': '0', 'name': ratname, 'platform':'unknown', 'error': ex, 'description': 'API Error while trying to fetch Rat'}


def getRatName(bot, ratid):
    """
    Returns the Name of a rat from its RatID by calling the API
    :param bot: the bot to pull config from and log errors to irc
    :param ratid: the id of the rat to find the name for
    :return: name of the rat
    """
    if (str(ratid) is not '0') and str(ratid) in savedratnames.keys():
        return savedratnames.get(ratid)['name'], savedratnames.get(ratid)['platform']
    if str(ratid) == 'None':
        return 'unknown', 'unknown'
    try:
        result = callapi(bot=bot, method='GET', uri='/rats/' + str(ratid))
    except ratlib.api.http.APIError:
        print('got Api error during api call')
        return 'unknown', 'unknown'
    try:
        data = result['data'][0]['attributes']
        name = data['name']
        platform = data['platform']
        ret = name, platform
    except:
        print('Couldn\'t parse Ratname from api response for ratid' + str(ratid))
        ret = 'unknown', 'unknown'
    # print('returning '+str(ret)+' as name for '+ratid)
    return ret

def removeTags(string):
    """
       Removes tags that are used on irc; ex: Marenthyu[PC] becomes Marenthyu
       :param string: the untruncated string
       :return: the string with everything start at an [ removed.
    """
    try:
        i = string.index('[')
    except ValueError:
        i = len(string)

    return string[0:i]

def callapi(bot, method, uri, triggernick=None, data=None, _fn=ratlib.api.http.call):
    '''
    Calls the API with the gived method endpoint and data.
    :param bot: bot to pull config from and log error messages to irc
    :param method: GET PUT POST etc.
    :param uri: the endpoint to use, ex /rats
    :param data: body for request
    :param _fn: http call function to use
    :return: the data dict the api call returned.
    '''
    uri = urljoin(bot.config.ratbot.apiurl, uri)
    headers = {"Authorization": "Bearer " + bot.config.ratbot.apitoken}
    if triggernick is not None:
        headers.update({"X-Command-By":str(triggernick)})
    with bot.memory['ratbot']['apilock']:
        return _fn(method, uri, data, log=bot.memory['ratbot']['apilog'], headers=headers)

def getClientName(bot, resId):
    """
    Gets a client name from a rescueid
    :param bot: used to send messages and log errors to irc
    :param resId: the rescueid to look for the client's name
    :return: Client nickname of resId
    """

    if resId in savedclientnames.keys():
        return savedclientnames[resId]

    try:
        result = callapi(bot=bot, method='GET', uri='/rescues/' + resId)
        data = result['data'][0]['attributes']
        ret = data['client']
    except:
        ret = 'unknown'
    savedclientnames.update({resId:ret})
    return ret

def flushNames():
    savedratids.clear()
    savedratnames.clear()
    savedclientnames.clear()


def require_permission(privilage:Permissions, message =''):
    """
    Requires the invoking user to have a specified privilege level
    :param privilage: Permission level
    :param msg: (optional) overwrite message
    :return:
    """
    if message == '': message = privilage.value[1]
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):

            if getPrivLevel(trigger)<privilage.value[0]:
                if message and not callable(message):
                    bot.say(message)
                    return NOLIMIT
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator


privlevels = {'recruit.fuelrats.com':0, 'rat.fuelrats.com':1, 'dispatch.fuelrats.com':2, 'overseer.fuelrats.com':3, 'op.fuelrats.com':4, 'techrat.fuelrats.com':5, 'netadmin.fuelrats.com':6, 'admin.fuelrats.com':6}

def getPrivLevel(trigger):
    if trigger.owner:
        return 9
    if trigger.admin:
        return 8
    elif str(trigger.host).endswith('techrat.fuelrats.com'):
        return privlevels.get('techrat.fuelrats.com')
    else:
        for key in privlevels.keys():
            if str(trigger.host).endswith(key):
                return privlevels.get(key)
        return -1

def addNamesFromV2Response(ratdata):
    for rat in ratdata:
        if rat['type'] != "rats":
            continue
        r = {'id':rat['id'], 'name':rat['attributes']['name'], 'platform':rat['attributes']['platform']}
        savedratids.update({rat['attributes']['name']: r})
        savedratnames.update({rat['id']: {'name': rat['attributes']['name'], 'platform': rat['attributes']['platform']}})
