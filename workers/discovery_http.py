"""Count source HTTP responses without logging URLs or credentials."""
from contextlib import contextmanager


@contextmanager
def source_http_counters(client, counters, *, hosts=None):
    keys = ('http_requests', 'http_302', 'http_403', 'http_429')
    for key in keys:
        counters.setdefault(key, 0)
    async def observe(response):
        if hosts and response.url.host not in hosts:
            return
        counters['http_requests'] += 1
        if response.status_code in (302, 403, 429):
            counters['http_' + str(response.status_code)] += 1
    hooks = getattr(client, 'event_hooks', None)
    if hooks is not None:
        hooks.setdefault('response', []).append(observe)
    try:
        yield
    finally:
        if hooks is not None and observe in hooks['response']:
            hooks['response'].remove(observe)
