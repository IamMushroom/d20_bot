import logging
from collections.abc import Mapping
from ipaddress import ip_address, ip_network
from os import getenv


def trusted_proxy(remote_host: str | None) -> bool:
    if remote_host is None:
        return False
    try:
        address = ip_address(remote_host)
    except ValueError:
        return False
    for value in getenv('D20_BOT_WEB_TRUSTED_PROXIES', '').split(','):
        value = value.strip()
        if not value:
            continue
        try:
            if address in ip_network(value, strict=False):
                return True
        except ValueError:
            logging.warning('Invalid trusted proxy network', extra={'trusted_proxy_network': value})
    return False


def client_ip(headers: Mapping[str, str], remote_host: str | None) -> str:
    candidate = remote_host or 'unknown'
    if trusted_proxy(remote_host):
        candidate = headers.get('x-forwarded-for', '').split(',', 1)[0].strip() or candidate
    try:
        return str(ip_address(candidate))
    except ValueError:
        return remote_host or 'unknown'


def cookie(headers: Mapping[str, str], name: str) -> str | None:
    for item in headers.get('cookie', '').split(';'):
        key, separator, value = item.strip().partition('=')
        if separator and key == name:
            return value
    return None


def session_cookie(session_id: str, headers: Mapping[str, str], remote_host: str | None) -> str:
    value = f'd20_admin={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
    secure_mode = getenv('D20_BOT_WEB_SECURE_COOKIE', 'auto').lower()
    forwarded_protocol = (
        headers.get('x-forwarded-proto', 'http').split(',', 1)[0].strip().lower()
        if trusted_proxy(remote_host)
        else 'http'
    )
    if secure_mode == 'true' or (secure_mode == 'auto' and forwarded_protocol == 'https'):
        value += '; Secure'
    return value
