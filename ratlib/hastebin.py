"""
Copyright (c) 2017 The Fuel Rats Mischief, 
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
import requests
from urllib.parse import urljoin


def post_to_hastebin(data, url="http://hastebin.com/"):
    if isinstance(data, str):
        data = data.encode()
    response = requests.post(urljoin(url, "documents"), data)
    response.raise_for_status()
    result = response.json()
    return urljoin(url, result['key'])
