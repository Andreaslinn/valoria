"""Private evidence sanitization only; never modifies functional listing inputs."""
from __future__ import annotations
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup

POLICY_VERSION = 'evidence_safety_v1'
_DENIED = {'headers','requestheaders','responseheaders','cookies','cookie',
    'setcookie','authorization','proxyauthorization','password','passwd',
    'secret','apikey','accesskey','privatekey','token','accesstoken','refreshtoken',
    'idtoken','jwt','session','sessionid','sessionkey','csrf','csrftoken',
    'xsrf','signature','credential','xamzsignature','xamzcredential',
    'xamzsecuritytoken','policy','keypairid','auth','authentication',
    'tracking','track','telemetry','actions','action','email','phone','telephone',
    'mobile','contactphone','contactemail'}
def denied(key):
    key=re.sub(r'[^a-z0-9]', '', str(key).lower())
    return key in _DENIED or key.endswith(('token','secret','password','sessionid','apikey'))

def safe_text(text):
    text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[REDACTED_EMAIL]', text)
    text=re.sub(r'(?<!\w)\+56[\s().-]*[2-9](?:[\s().-]*\d){8}(?!\d)', '[REDACTED_PHONE]', text)
    text=re.sub(r'(?i)((?:tel[eé]fono|whatsapp|celular|fono|phone)\s*[:=]?\s*)[+\d][\d\s().-]{7,20}', r'\1[REDACTED_PHONE]', text)
    text=re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*', 'Bearer [REDACTED]', text)
    text=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED_JWT]', text)
    return text

def safe_url(value):
    try:
        p=urlsplit(value)
        if p.scheme not in {'http','https'}: return safe_text(value)
        # No userinfo, fragments or credential-bearing query keys.
        host=p.netloc.rsplit('@',1)[-1]
        query=urlencode([(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not denied(k)])
        return safe_text(urlunsplit((p.scheme,host,p.path,query,'')))
    except ValueError:
        return '[REDACTED_INVALID_URL]' if '?' in value or '@' in value else safe_text(value)

def sanitize(value):
    if isinstance(value,dict): return {k:sanitize(v) for k,v in value.items() if not denied(k)}
    if isinstance(value,list): return [sanitize(v) for v in value]
    if isinstance(value,tuple): return [sanitize(v) for v in value]
    if not isinstance(value,str): return value
    stripped=value.strip()
    if stripped.startswith(('http://','https://')): return safe_url(value)
    if stripped.startswith(('{','[')):
        try: return json.dumps(sanitize(json.loads(value)),ensure_ascii=False)
        except (ValueError,TypeError): pass
    if '<' in value and '>' in value:
        soup=BeautifulSoup(value,'html.parser')
        for el in soup.select('script,style,form,input,button,textarea'): el.decompose()
        allowed={'href','src','data-src','alt','title','class','id'}
        for el in soup.find_all(True):
            for key in list(el.attrs):
                if key not in allowed: del el.attrs[key]
                else: el.attrs[key]=sanitize(el.attrs[key])
        for node in list(soup.find_all(string=True)):
            node.replace_with(safe_text(str(node)))
        return str(soup)
    # Embedded URLs in descriptions must also lose credential-bearing queries.
    return safe_text(re.sub(r'https?://[^\s<>"\']+', lambda m:safe_url(m.group()), value))
