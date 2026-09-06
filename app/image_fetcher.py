import ipaddress
import socket
import uuid
from urllib.parse import urlparse

import requests

from app import config
from app.errors import ApiError


def _is_public_host(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ApiError(400, "INVALID_REQUEST", f"Unsupported image_url scheme: {parsed.scheme}")
    if not parsed.hostname or not _is_public_host(parsed.hostname):
        raise ApiError(400, "INVALID_REQUEST", "image_url resolves to a private/loopback/reserved address")


def fetch_image(url: str, task_id: str, suffix: str) -> str:
    """Downloads url into ComfyUI's input dir with SSRF guards; returns the filename
    (as ComfyUI expects it in a LoadImage node's `image` input)."""
    current_url = url
    for _ in range(config.MAX_IMAGE_REDIRECTS + 1):
        _validate_url(current_url)
        try:
            resp = requests.get(
                current_url,
                stream=True,
                timeout=config.IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            raise ApiError(400, "INVALID_REQUEST", f"Failed to fetch image_url: {e}")

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise ApiError(400, "INVALID_REQUEST", "Redirect response missing Location header")
            current_url = location
            continue

        if resp.status_code != 200:
            raise ApiError(400, "INVALID_REQUEST", f"image_url returned HTTP {resp.status_code}")

        content_length = resp.headers.get("Content-Length")
        max_bytes = config.MAX_INPUT_IMAGE_MB * 1024 * 1024
        if content_length and int(content_length) > max_bytes:
            raise ApiError(400, "INVALID_REQUEST", "image exceeds MAX_INPUT_IMAGE_MB")

        filename = f"{task_id}_{suffix}.png"
        dest = config.COMFY_INPUT_DIR / filename
        total = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise ApiError(400, "INVALID_REQUEST", "image exceeds MAX_INPUT_IMAGE_MB")
                f.write(chunk)
        return filename

    raise ApiError(400, "INVALID_REQUEST", "Too many redirects fetching image_url")
