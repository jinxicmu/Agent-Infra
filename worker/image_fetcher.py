"""Bounded image downloads with DNS pinning and validation on every redirect."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin
import urllib3
import requests
from PIL import Image


class InputError(Exception):
    pass


def fetch_image(url, task_id, role, directory, check=lambda: None):
    deadline = time.monotonic() + 60
    dest = directory / f'{task_id}_{role}.png'
    temporary = dest.with_suffix('.download')
    try:
        for _ in range(4):
            check()
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise InputError('Invalid image URL')
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            if port not in (80, 443):
                raise InputError('Unsupported image port')
            addresses = [item[4][0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)]
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise InputError('Image host must resolve only to public addresses')
            if parsed.scheme == 'https':
                pool = urllib3.HTTPSConnectionPool(addresses[0], port, server_hostname=parsed.hostname,
                    assert_hostname=parsed.hostname, cert_reqs='CERT_REQUIRED', ca_certs=requests.certs.where())
            else:
                pool = urllib3.HTTPConnectionPool(addresses[0], port)
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            response = None
            try:
                response = pool.urlopen('GET', path, headers={'Host': parsed.netloc},
                    redirect=False, retries=False, preload_content=False,
                    timeout=urllib3.Timeout(connect=5, read=10))
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    if not location:
                        raise InputError('Missing redirect location')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise InputError('Image download failed')
                total = 0
                with temporary.open('wb') as stream:
                    while True:
                        check()
                        if time.monotonic() > deadline:
                            raise InputError('Image download deadline exceeded')
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 20 * 1024**2:
                            raise InputError('Image exceeds 20 MiB')
                        stream.write(chunk)
                with Image.open(temporary) as picture:
                    if picture.width * picture.height > 32_000_000:
                        raise InputError('Image dimensions too large')
                    picture.load()
                    picture.convert('RGB').save(dest, 'PNG')
                return dest.name
            finally:
                if response:
                    response.close()
                pool.close()
        raise InputError('Too many image redirects')
    finally:
        temporary.unlink(missing_ok=True)
