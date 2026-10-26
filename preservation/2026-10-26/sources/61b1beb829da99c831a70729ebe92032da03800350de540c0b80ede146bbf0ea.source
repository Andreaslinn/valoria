"""Authenticated Portal HTTP session; no password or browser runtime."""
from contextlib import asynccontextmanager
from http.cookiejar import Cookie
import json
import os
from pathlib import Path
import stat
import time
import httpx

ALLOWED_DOMAINS = {'.portalinmobiliario.com', 'www.portalinmobiliario.com', '.www.portalinmobiliario.com'}

def load_session(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('Portal session requires a private regular file')
    data = json.loads(path.read_text())
    jar = httpx.Cookies()
    for entry in data['cookies']:
        domain = entry['domain']
        if domain not in ALLOWED_DOMAINS:
            raise ValueError('Unexpected Portal session domain')
        expires = entry.get('expires')
        if expires is not None and expires <= time.time():
            continue
        jar.jar.set_cookie(Cookie(0, entry['name'], entry['value'], None, False,
            domain, True, domain.startswith('.'), entry.get('path', '/'), True,
            bool(entry.get('secure', True)), expires, expires is None, None, None, {}))
    if not any(c.name == 'ssid' for c in jar.jar):
        raise ValueError('Portal session expired; official verification required')
    return jar

def save_session(path, jar):
    entries = [{'domain':c.domain,'name':c.name,'value':c.value,'path':c.path,
                'secure':c.secure,'expires':c.expires}
               for c in jar.jar if c.domain in ALLOWED_DOMAINS and not c.is_expired()]
    path = Path(path)
    tmp = path.with_suffix('.new')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'cookies':entries, 'saved_at':int(time.time())}, stream)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()

@asynccontextmanager
async def portal_client(**kwargs):
    path = os.environ.get('PORTAL_SESSION_FILE')
    cookies = load_session(path) if path else None
    async with httpx.AsyncClient(cookies=cookies, **kwargs) as client:
        try:
            yield client
        finally:
            if path: save_session(path, client.cookies)
