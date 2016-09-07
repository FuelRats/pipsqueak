import ratlib
import ratlib.api
import ratlib.api.http
import functools

urljoin = ratlib.api.http.urljoin
savedratids = {}
savedratnames = {}
savedclientnames = {}

def getRatId(bot, ratname, platform=None):

    if ratname in savedratids.keys():
        element = savedratids.get(ratname)
        strippedname = removeTags(ratname)
        if (platform == None) and ((element['name']==ratname) or element['name']==strippedname or element['name']==strippedname.replace('_',' ')):
            print('platform was None and '+ratname+' was in keys and the name matched. returning '+str(element))
            return element
        elif (platform == element['platform']) and ((element['name']==ratname) or element['name']==strippedname or element['name']==strippedname.replace('_',' ')):
            print('platform was on the gotten name and names matched. Returning '+str(element))
            return element


    try:
        uri = '/users?nicknames=' + ratname
        # print('looking for name '+ratname)
        # print('uri: '+str(uri))
        result = callapi(bot=bot, method='GET', uri=uri)
        # print(result)
        data = result['data']
        # print(data)
        returnlist = []
        if platform == None:
            if len(data) == 0:
                raise Exception
            firstmatch = data[0]
            strippedname = removeTags(ratname)
            retlist = []
            cmdr = 0

            for cmdr in firstmatch['CMDRs']:
                id = cmdr
                tempnam, tempplat = getRatName(bot, cmdr)
                if (tempnam==ratname or tempnam==strippedname or tempnam==strippedname.replace('_', ' ')):
                    retlist.append({'id': cmdr, 'name':tempnam , 'platform':tempplat})
            if len(retlist) == 0:
                ratnam = tempnam
                ratplat = tempplat
                id = cmdr
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
                print('data length 0')
                raise Exception
            for user in data:
                for cmdr in user['CMDRs']:
                    ratnam, ratplat = getRatName(bot, cmdr)
                    rat = {'id':cmdr, 'platform':ratplat, 'name':ratnam}
                    if rat['platform'] == platform:
                        id = rat['id']
                        ret = {'id':id, 'name': ratnam, 'platform':platform}
                        returnlist.append(ret)
            strippedname = removeTags(ratname)
            for retelement in returnlist:
                print('Is '+retelement['name'] + ' == ' + ratname+'? '+str(retelement['name']==ratname))
                print('Is ' + retelement['name'] + ' == ' + strippedname+'? ' + str(retelement['name']==strippedname))
                print('Is ' + retelement['name'] + ' == ' + strippedname.replace('_', ' ') + '? ' + str(retelement['name'] == strippedname.replace('_', ' ')))
                if (retelement['name']==ratname) or (retelement['name']==strippedname) or (retelement['name']==strippedname.replace('_', ' ')):
                    ret = retelement
        savedratids.update({ratname: ret})
        savedratnames.update({id: {'name': ratnam, 'platform': ret['platform'], 'id':ret['id']}})
        return ret
    except:
        # print('didnt find with tags, trying without')
        try:
            strippedname = removeTags(ratname)
            if strippedname in savedratids.keys() and (platform == savedratids.get(strippedname)['platform'] or platform == None):
                return savedratids[strippedname]
            uri = '/users?nicknames=' + strippedname
            result = callapi(bot=bot, method='GET', uri=uri)
            # print(result)
            data = result['data']
            # print(data)
            returnlist = []
            if platform == None:
                firstmatch = data[0]
                id = firstmatch['CMDRs'][0]
                ratnam, ratplat = getRatName(bot, id)
                ret = {'id': id, 'name': ratnam, 'platform': ratplat}

            else:
                ret = {'id': None, 'name': None, 'platform': None}
                id = None
                if len(data) == 0:
                    # print('data length 0, calling fallback.')
                    return idFallback(bot, ratname, platform=platform)
                for user in data:
                    for cmdr in user['CMDRs']:
                        ratnam, ratplat = getRatName(bot, cmdr)
                        rat = {'id': cmdr, 'platform': ratplat}
                        if rat['platform'] == platform:
                            id = rat['id']
                            ret = {'id': rat['id'], 'name': ratnam, 'platform': rat['platform']}
                            returnlist.append(ret)
                strippedname = removeTags(ratname)
                for retelement in returnlist:
                    if (retelement['name'] == ratname) or (retelement['name'] == str(strippedname)) or (retelement['name']==str(strippedname).replace('_', ' ')):
                        ret = retelement
            savedratids.update({strippedname: ret})
            savedratnames.update({id: {'name':ret['name'], 'platform':ret['platform'], 'id':ret['id']}})
            return ret
        except:
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
    print('[NamesAPI] Had to call idFallback for '+str(ratname))
    try:
        uri = '/rats?CMDRname=' + strippedname + (('&platform='+platform) if platform is not None else '')
        result = callapi(bot=bot, method='GET', uri=uri)
        # print(result)
        data = result['data']
        # print(data)
        firstmatch = data[0]
        id = firstmatch['id']
        ret =  {'id': id, 'name': strippedname, 'platform':firstmatch['platform']}
        savedratids.update({ratname:ret})
        savedratnames.update({id:{'name':strippedname, 'platform':firstmatch['platform']}})
        return ret


    except IndexError as ex:
                # print('no rats with that commandername or nickname or gamertag found.')
                return {'id': '0', 'name': ratname, 'error': ex, 'platform':'unknown',
                        'description': 'no rats with that commandername or nickname or gamertag found.'}
    except ratlib.api.http.APIError as ex:
        print('APIError: couldnt find RatId for ' + ratname)
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
    try:
        result = callapi(bot=bot, method='GET', uri='/rats/' + str(ratid))
    except ratlib.api.http.APIError:
        print('got Api error during api call')
        return 'unknown', 'unknown'
    try:
        data = result['data']
        name = data['CMDRname']
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

def callapi(bot, method, uri, data=None, _fn=ratlib.api.http.call):
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
        data = result['data']
        ret = data['client']
    except:
        ret = 'unknown'
    savedclientnames.update({resId:ret})
    return ret

def flushNames():
    savedratids.clear()
    savedratnames.clear()
    savedclientnames.clear()

def require_netadmin(message=None):
    """Decorate a function to require the triggering user to be a FuelRats netadmin (as in, a highly ranked admin.).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<6:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

def require_techrat(message=None):
    """Decorate a function to require the triggering user to be a FuelRats TechRat (as in, a rat that's part of the RatTech team.).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<5:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

def require_op(message=None):
    """Decorate a function to require the triggering user to be a FuelRats op (as in, an operator.).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<4:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

def require_overseer(message=None):
    """Decorate a function to require the triggering user to be a FuelRats overseer (as in, a highly experienced and trustworthy person).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<3:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

def require_dispatch(message=None):
    """Decorate a function to require the triggering user to be a FuelRats dispatch (as in, the currently active dispatch).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<2:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

def require_rat(message=None):
    """Decorate a function to require the triggering user to be a FuelRats rat (as in, registered with the API and drilled).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<1:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

def require_recruit(message=None):
    """Decorate a function to require the triggering user to be a FuelRats recruit (as in, a user registered with the API but undrilled).
    If they are not, `message` will be said if given."""
    def actual_decorator(function):
        @functools.wraps(function)
        def guarded(bot, trigger, *args, **kwargs):
            if getPrivLevel(trigger)<0:
                if message and not callable(message):
                    bot.say(message)
            else:
                return function(bot, trigger, *args, **kwargs)
        return guarded
    # Hack to allow decorator without parens
    if callable(message):
        return actual_decorator(message)
    return actual_decorator

privlevels = {'recruit.fuelrats.com':0, 'rat.fuelrats.com':1, 'dispatch.fuelrats.com':2, 'overseer.fuelrats.com':3, 'op.fuelrats.com':4, 'techrat.fuelrats.com':5, 'netadmin.fuelrats.com':6}

def getPrivLevel(trigger):
    if trigger.owner:
        return 9
    if trigger.admin:
        return 8
    else:
        for key in privlevels.keys():
            if str(trigger.host).endswith(key):
                return privlevels.get(key)
        return -1