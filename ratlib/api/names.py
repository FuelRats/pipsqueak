import ratlib
import ratlib.api
import ratlib.api.http

urljoin = ratlib.api.http.urljoin
savedratids = {}
savedratnames = {}
savedclientnames = {}

def getRatId(bot, ratname):
    """
    Gets the RatId for a given name from the API or 0 if it couldnt find anyone with that cmdrname
    Args:
        bot: the bot to pull the config from
        ratname: the cmdrname to look for

    Returns:
        a dict with ['id'] which has the id it got, ['name'] the name it used to poll the api and
        if the api call returned an error or the rat wasn't found, ['error'] has the returned error object and
        ['description'] a description of the error.

    """
    strippedname = removeTags(ratname)
    if strippedname in savedratids.keys():
        return savedratids[strippedname]
    try:
        uri = '/rats?CMDRname=' + strippedname
        result = callapi(bot=bot, method='GET', uri=uri)
        # print(result)
        data = result['data']
        # print(data)
        firstmatch = data[0]
        id = firstmatch['_id']
        ret =  {'id': id, 'name': strippedname}
        savedratids.update({strippedname:ret})
        savedratnames.update({id:strippedname})
        return ret


    except IndexError as ex:
        try:
            # print('No rats with that CMDRname found. Trying nickname...')
            uri = '/rats?nickname=' + strippedname
            result = callapi(bot=bot, method='GET', uri=uri)
            # print(result)
            data = result['data']
            # print(data)
            firstmatch = data[0]
            id = firstmatch['_id']
            return {'id': id, 'name': strippedname}
        except IndexError:
            # print('no rats with that commandername or nickname found. trying gamertag...')
            try:
                uri = '/rats?gamertag=' + strippedname
                result = callapi(bot=bot, method='GET', uri=uri)
                # print(result)
                data = result['data']
                # print(data)
                firstmatch = data[0]
                id = firstmatch['_id']
                return {'id': id, 'name': strippedname}
            except IndexError:
                # print('no rats with that commandername or nickname or gamertag found.')
                return {'id': '0', 'name': strippedname, 'error': ex,
                        'description': 'no rats with that commandername or nickname or gamertag found.'}
    except ratlib.api.http.APIError as ex:
        print('APIError: couldnt find RatId for ' + strippedname)
        return {'id': '0', 'name': strippedname, 'error': ex, 'description': 'API Error while trying to fetch Rat'}


def getRatName(bot, ratid):
    """
    Returns the Name of a rat from its RatID by calling the API
    :param bot: the bot to pull config from and log errors to irc
    :param ratid: the id of the rat to find the name for
    :return: name of the rat
    """
    if ratid in savedratnames.keys():
        return savedratnames[ratid]
    try:
        result = callapi(bot=bot, method='GET', uri='/rats/' + ratid)
    except ratlib.api.http.APIError:
        print('got Api error during api call')
        return 'unknown'
    try:
        data = result['data']
        ret = data['CMDRname']

    except:
        ret = 'unknown'
    # print('returning '+ret+' as name for '+ratid)
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
        ret = data['client']['nickname']
    except:
        ret = 'unknown'
    savedclientnames.update({resId:ret})
    return ret
