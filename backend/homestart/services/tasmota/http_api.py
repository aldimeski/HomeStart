"""Tasmota HTTP command interface (http://<ip>/cm?cmnd=...), used for scanning and as a fallback to MQTT."""

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Any

import httpx

from .parsing import decode_json, parse_console

HTTP_TIMEOUT = 3.0
SCAN_TIMEOUT = 2.0
SCAN_CONCURRENCY = 64

# httpx logs full request URLs at INFO level and Tasmota passes credentials in the URL.
logging.getLogger("httpx").setLevel(logging.WARNING)


class DeviceUnreachable(Exception):
    pass


class AuthRequired(Exception):
    pass


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


def _is_auth_warning(data: dict[str, Any] | None) -> bool:
    return bool(data) and "Need user=" in str(data.get("WARNING", ""))


async def command(
    host: str,
    port: int,
    cmnd: str,
    credentials: Credentials | None,
    timeout: float = HTTP_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    params = {"cmnd": cmnd}
    if credentials:
        params = {"user": credentials.username, "password": credentials.password, **params}
    url = _url(host, port, "/cm")

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=timeout) as own_client:
                response = await own_client.get(url, params=params)
        else:
            response = await client.get(url, params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        raise DeviceUnreachable(str(host)) from exc

    data = decode_json(response.content)
    if response.status_code == 401 or _is_auth_warning(data):
        raise AuthRequired(str(host))
    if data is None:
        raise DeviceUnreachable(f"{host} did not answer like a Tasmota device")
    return data


def _url(host: str, port: int, path: str) -> str:
    return f"http://{host}:{port}{path}" if port != 80 else f"http://{host}{path}"


async def console_log(
    host: str, port: int, index: int, credentials: Credentials | None, client: httpx.AsyncClient
) -> tuple[int, list[str]]:
    """Web log lines after `index` (0 = everything the device still holds) and the new index."""
    # /cs only accepts HTTP Basic auth, which also keeps the password out of the URL.
    auth = (credentials.username, credentials.password) if credentials else None
    try:
        response = await client.get(_url(host, port, "/cs"), params={"c2": index}, auth=auth)
    except httpx.HTTPError as exc:
        raise DeviceUnreachable(str(host)) from exc
    if response.status_code == 401:
        raise AuthRequired(str(host))
    parsed = parse_console(response.text) if response.status_code == 200 else None
    if parsed is None:
        raise DeviceUnreachable(f"{host} did not answer like a Tasmota console")
    return parsed


def default_scan_subnet() -> ipaddress.IPv4Network:
    """The /24 network of the server's LAN address (no packets are sent by the UDP connect)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))  # TEST-NET address, only used to pick the outgoing interface
        address = sock.getsockname()[0]
    return ipaddress.IPv4Network(f"{address}/24", strict=False)


@dataclass
class ScanHit:
    host: str
    status: dict[str, Any] | None  # None when the device requires a login we do not have


async def scan(subnet: ipaddress.IPv4Network, credentials: Credentials | None) -> list[ScanHit]:
    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
    hits: list[ScanHit] = []

    async with httpx.AsyncClient(timeout=SCAN_TIMEOUT) as client:

        async def probe(host: str) -> None:
            async with semaphore:
                try:
                    data = await command(host, 80, "Status 0", credentials, SCAN_TIMEOUT, client)
                except AuthRequired:
                    hits.append(ScanHit(host, None))
                    return
                except DeviceUnreachable:
                    return
                if isinstance(data.get("Status"), dict):
                    hits.append(ScanHit(host, data))

        await asyncio.gather(*(probe(str(ip)) for ip in subnet.hosts()))
    return hits


def is_local_address(host: str) -> bool:
    """Only private LAN addresses may be contacted, so the server cannot be used to reach other networks."""
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_INET)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.IPv4Address(info[4][0])
        if not ip.is_private or ip.is_loopback or ip.is_unspecified:
            return False
    return bool(infos)
