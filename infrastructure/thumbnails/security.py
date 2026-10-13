"""Bounded fetch with exact CDN allowlist, DNS validation and connection pinning."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urljoin

HOSTS = frozenset({'photos.encuentra24.com', 'http2.mlstatic.com'})
MIMES = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP', 'image/avif': 'AVIF'}
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 8192
MAX_REDIRECTS = 2
TOTAL_TIMEOUT = 12.0
IO_TIMEOUT = 3.0


class Rejected(Exception):
    """Only stable codes are persisted; exception text never includes the URL."""


def source_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise Rejected('url_invalid')
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in HOSTS:
            raise Rejected('url_host_or_scheme')
        if parsed.username or parsed.password or parsed.port not in (None, 443):
            raise Rejected('url_credentials_or_port')
        # Observed CDN refs are unsigned. Reject rather than persist secrets.
        if parsed.query or parsed.fragment or '\\' in url:
            raise Rejected('url_query_or_fragment')
        return parsed.hostname, parsed.path or '/'
    except ValueError as exc:
        raise Rejected('url_invalid') from exc


def public_addresses(host: str, resolver=socket.getaddrinfo) -> list[str]:
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(r[4][0] for r in records))
        if not addresses:
            raise Rejected('dns_empty')
        for address in addresses:
            ip = ipaddress.ip_address(address)
            mapped = getattr(ip, 'ipv4_mapped', None)
            if not ip.is_global or (mapped and not mapped.is_global):
                raise Rejected('dns_forbidden')
        return addresses
    except (socket.gaierror, ValueError) as exc:
        raise Rejected('dns_invalid') from exc


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect only to the validated numeric IP; retain hostname for TLS SNI
        # and certificate verification. No proxy env, cookies or auth headers.
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


@dataclass(frozen=True)
class Download:
    body: bytes
    mime: str
    elapsed_ms: float
    source_hash: str


def fetch(url: str, *, resolver=socket.getaddrinfo, connection=PinnedHTTPS) -> Download:
    original = url
    started = time.perf_counter()
    deadline = started + TOTAL_TIMEOUT
    for redirect in range(MAX_REDIRECTS + 1):
        host, path = source_url(url)
        addresses = public_addresses(host, resolver)
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise Rejected('timeout')
        conn = connection(host, addresses[0], min(IO_TIMEOUT, remaining))
        try:
            conn.request('GET', path, headers={'Accept': 'image/webp,image/jpeg,image/png',
                                             'User-Agent': 'Valoria-thumbnail-sandbox/1',
                                             'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if redirect == MAX_REDIRECTS or not location:
                    raise Rejected('redirect_limit')
                url = urljoin(url, location)
                source_url(url)
                continue
            if response.status != 200:
                raise Rejected('http_' + str(response.status))
            mime = (response.getheader('Content-Type') or '').split(';')[0].strip().lower()
            if mime not in MIMES or response.getheader('Content-Encoding') not in (None, 'identity'):
                raise Rejected('mime_or_encoding')
            declared = response.getheader('Content-Length')
            if declared:
                try:
                    length = int(declared)
                except ValueError as exc:
                    raise Rejected('length_invalid') from exc
                if not 0 <= length <= MAX_BYTES:
                    raise Rejected('download_too_large')
            chunks, count = [], 0
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise Rejected('timeout')
                if getattr(conn, 'sock', None):
                    conn.sock.settimeout(min(IO_TIMEOUT, remaining))
                # read1 avoids waiting for a full chunk under a slow trickle.
                chunk = response.read1(min(65536, MAX_BYTES + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_BYTES:
                    raise Rejected('download_too_large')
                chunks.append(chunk)
            if declared and count != int(declared):
                raise Rejected('length_mismatch')
            return Download(b''.join(chunks), mime,
                            (time.perf_counter()-started)*1000,
                            hashlib.sha256(original.encode()).hexdigest())
        except Rejected:
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise Rejected('timeout') from exc
        except (OSError, http.client.HTTPException) as exc:
            raise Rejected('network_failure') from exc
        finally:
            conn.close()
    raise Rejected('redirect_limit')
