"""
Support for calling the HTTP/HTTPS API and handling responses.

Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
import requests
import requests.exceptions as exc
import requests.status_codes
import datetime
import json
import functools

# Exceptions
"""Generic API Error class."""
class APIError(Exception):
    def __init__(self, code=None, details=None, json=None):
        """
        Creates a new APIError.
        :param code: Error code, if any
        :param details: Details, if any
        :param json: JSON response, if available.
        :return:
        """
        self.code = code
        self.details = details
        self.json = json

    def __repr__(self):
        return "<{0.__class__.__name__}({0.code}, {0.details!r})>".format(self)
    __str__ = __repr__


"""Indicates a generic error with the API response."""
class BadResponseError(APIError):
    pass


"""Indicates an error parsing JSON data."""
class BadJSONError(BadResponseError):
    def __init__(self, code='2608', details="API didn\'t return valid JSON."):
        super().__init__(code, details)


class UnsupportedMethodError(APIError):
    def __init__(self, code='9999', details="Invalid request method."):
        super().__init__(code, details)


class HTTPError(APIError):
    pass


# Actual API calling
# For known request methods, we call request.<method> directly since it does some preprocessing for us
# All other requests just use requests.request(method, ...)
request_methods = {attr: getattr(requests, attr.lower()) for attr in "GET PUT POST".split(" ")}

def urljoin(*parts):
    """
    Join chunks of a URL together.

    The main thing this does is ensure each chunk is separated by exactly one /.

    :param parts: URL components.
    :return: Unified URL string
    """
    def _gen(parts):
        prev = None
        for part in parts:
            if not part:
                continue
            if not prev:
                prev = part
            elif (prev[-1] == '/') != (part[0] == '/'):  # Exactly one slash was present
                prev = part
            # At this point, either zero or two slashes are present.  Which is it?
            elif part[0] == '/':  # Two slashes.
                prev = part[1:]
            else:  # No slashes.
                yield '/'
                prev = part
            yield prev

    return "".join(part for part in _gen(parts))


def call(method, uri, data=None, statuses=None, log=None, headers=None, **kwargs):
    """
    Wrapper function to contact the web API.

    :param method: Request method
    :param uri: URI.  If this is anything other than a string, it is passed to urljoin() first.
    :param data: Data for JSON request body.
    :param log: File-like object to log request data to.
    :param headers: Additional header to send; Used to Send authorization.
    :param **kwargs: Passed to requests.
    :param statuses: If present, a set of acceptable HTTP response codes (including 200).  If not present, the default
        behavior of requests.raise_for_status() is used.
    """
    if not isinstance(uri, str):
        uri = urljoin(uri)

    #dump data as a String if it is a dict element to allow for both json objects and Json-formatted strings
    if type(data) == type({}):
        data = json.dumps(data)

    data = json.loads(data or '{}')
    # print('statuses: '+str(statuses))
    # print('will send '+str(data))
    if log:
        logprint = functools.partial(print, file=log, flush=True)
    else:
        logprint = lambda *a, **kw: None

    timestamp = datetime.datetime.now()
    when = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

    logprint(
        "[{when}] {method} {uri}\n{header}\n{data}\n".format(
            header=headers, when=when, method=method.upper(), uri=uri, data=json.dumps(data, sort_keys=True, indent=" "*4)
        )
    )

    response = None
    try:
        if method in request_methods:
            response = request_methods[method](uri, json=data, headers=headers)
            # print('response full: '+str(response.text))
        else:
            response = requests.request(method.upper(), uri, json=data, headers=headers)
            # print('response full: ' + str(response.text))
        if not statuses:
            if response.status_code != 400:
                response.raise_for_status()
        elif response.status_code not in statuses:
            raise HTTPError(code=response.status_code, details="Unexpected Status Code {}".format(response.status_code))
    except exc.HTTPError as ex:
        print(str(ex))
        print(
            "[{when}] {method} {uri}\n{header}\n{data}\n".format(
                header=headers, when=when, method=method.upper(), uri=uri,
                data=json.dumps(data, sort_keys=True, indent=" " * 4)
            )
        )
        if response is not None:
            print("Response:")
            print(response.text)
        raise HTTPError(code=ex.response.status_code, details=str(ex)) from ex
    except exc.RequestException as ex:
        try:
            logprint(str(ex.args[0]))
        except (AttributeError, IndexError):
            logprint(str(ex))
        raise BadResponseError() from ex
    finally:
        if response is not None:
            delta = (datetime.datetime.now() - timestamp).total_seconds()
            try:
                body = response.text
            except:
                body = '(unable to decode body)'
            logprint(
                "[{when}] status={response.status_code} in {delta} sec.\n{body}\n{d}".format(
                    when=when, response=response, body=body, delta=delta, d='-'*10
                ),
            )
    if response.status_code == 204:
        result = {'data':[]}
    else:
        try:
            result = response.json()
        except ValueError as ex:
            raise BadJSONError() from ex

    if 'errors' in result:
        err = result['errors'][0]
        print('Error while calling API. result: '+str(result))
        print(
            "[{when}] {method} {uri}\n{header}\n{data}\n".format(
                header=headers, when=when, method=method.upper(), uri=uri,
                data=json.dumps(data, sort_keys=True, indent=" " * 4)
            )
        )
        raise APIError(err.get('name'), err.get('message'), json=result)
    if 'data' not in result:
        raise BadResponseError(details="Did not receive a data field in a non-error response.", json=result)

    return result


class ShortenerError(ValueError):
    """Shortner API errors"""
    def __init__(self, status, message, code):
        self.status = status
        self.message = message
        self.code = code
        super().__init__(status, message, code)

    def __repr__(self):
        return "{c.__name__}({o.status!r}, {o.message!r}, {o.code!r})".format(
            c = type(self), o=self
        )


class Shortener:
    def __init__(self, url, token):
        self.url = url
        self.token = token

    def shorten(self, url, keyword=None):
        params = {
            'action': 'shorturl',
            'format': 'json',
            'url': url,
        }
        if self.token:
            params['signature'] = self.token
        if keyword:
            params['keyword'] = keyword

        response = requests.get(self.url, params=params)
        response.raise_for_status()
        data = response.json()

        if data and (data['status'] != 'success' and 'shorturl' not in data):
            raise ShortenerError(data['status'], data['message'], data['statusCode'])
        return data