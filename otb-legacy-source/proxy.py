import os
import random
import re
import threading
import time

import requests

from log import log
from session import session
from settings import settings

try:
    with open("proxies.txt", "r") as f:
        lines = f.readlines()
except IOError:
    with open("proxies.txt", "w") as f:
        f.write("""# Put a list of proxies here on each line
# You can leave out username and password if it's not needed
# Every proxy should support both http and https
""")
        lines = []


class Proxy(object):
    def __init__(self, host, port, username=None, password=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    def format(self):
        if self.username or self.password:
            return ("%s:%s@%s:%s" % (self.username, self.password, self.host, self.port))
        else:
            return ("%s:%s" % (self.host, self.port))


def parse_proxy(line):
    match = re.match(r'([\d\w.]+):([\d\w.]+)@([\d\w.]+):([\d\w.]+)', line)
    if match:
        groups = match.groups()
        return Proxy(groups[2], groups[3], groups[0], groups[1])

    match = re.match(r'([\d\w.]+):([\d\w.]+)(?::([\d\w.]+):([\d\w.]+))?', line)
    if match:
        groups = match.groups()
        return Proxy(*groups)

    raise ValueError("Invalid proxy format.")


proxies = []

for line in lines:
    if not line.startswith("#") and line.strip() != "":
        try:
            proxies.append(parse_proxy(line.strip()))
        except ValueError:
            pass


random.shuffle(proxies)


def infinite_loop_proxies():
    while True:
        for proxy in proxies:
            yield proxy


switch_proxy_every_minutes = int(settings['General']['switch_proxy_every_minutes'])


def test_proxy():
    response = requests.get("http://ifconfig.me")
    print("Without session:", response.text)

    response = session.get("https://ifconfig.me")
    print("With session:", response.text)


proxies_loop = infinite_loop_proxies()


def next_proxy():
    next_proxy = next(proxies_loop)

    http_proxy = "http://" + next_proxy.format()
    https_proxy = "https://" + next_proxy.format()

    os.environ['HTTP_PROXY'] = os.environ['http_proxy'] = http_proxy
    os.environ['HTTPS_PROXY'] = os.environ['https_proxy'] = https_proxy
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,.local'

    session.proxies = {
        "http": http_proxy,
        "https": https_proxy
    }

    # test_proxy()


def proxy_updater():
    if not proxies:
        return

    while True:
        next_proxy()

        time.sleep(switch_proxy_every_minutes * 60)


proxy_updater_loop = None


def start_proxy_loop():
    global proxy_updater_loop
    proxy_updater_loop = threading.Thread(target=proxy_updater)
    proxy_updater_loop.daemon = True
    proxy_updater_loop.start()

    log("Number of proxies loaded: %i" % len(proxies))
