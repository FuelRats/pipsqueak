import requests
from urllib.parse import urljoin


def post_to_hastebin(data, url="http://hastebin.com/"):
    if isinstance(data, str):
        data = data.encode()
    response = requests.post(urljoin(url, "documents"), data)
    response.raise_for_status()
    result = response.json()
    return urljoin(url, result['key'])
