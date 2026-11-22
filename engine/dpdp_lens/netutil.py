"""Shared network checks."""
import ipaddress
from urllib.parse import urlparse


def is_local(url: str) -> bool:
    """Threat T3: only touch http(s) URLs on localhost or a private address."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private
