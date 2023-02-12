import contextlib

import requests
from requests.exceptions import ProxyError

import proxy


@contextlib.contextmanager
def handle_proxy_error():
    try:
        yield
    except ProxyError:
        print("Got proxy error, switching proxy.")
        proxy.next_proxy()
        raise


class SessionWithProxy(requests.Session):
    def get(self, *args, **kwargs):
        with handle_proxy_error():
            return super(SessionWithProxy, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        with handle_proxy_error():
            return super(SessionWithProxy, self).post(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with handle_proxy_error():
            return super(SessionWithProxy, self).delete(*args, **kwargs)

    def put(self, *args, **kwargs):
        with handle_proxy_error():
            return super(SessionWithProxy, self).put(*args, **kwargs)

    def options(self, *args, **kwargs):
        with handle_proxy_error():
            return super(SessionWithProxy, self).options(*args, **kwargs)

    def patch(self, *args, **kwargs):
        with handle_proxy_error():
            return super(SessionWithProxy, self).patch(*args, **kwargs)


session = SessionWithProxy()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36'
})
