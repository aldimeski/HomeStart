"""Who may use the Radiopanel and the openHAB pass-through without a HomeStart login."""

import ipaddress

from fastapi import HTTPException, Request, status

from .config import Settings
from .db import SessionLocal
from .security import client_ip, current_session_token, user_for_token


def is_local(settings: Settings, ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(address in network for network in settings.radio_allowed_networks if network.version == address.version)


def require_local_or_user(request: Request) -> None:
    """Lets in clients of the allowed networks, and logged-in users from anywhere.

    The forwarded-for headers are ignored on purpose: nothing sits in front of HomeStart, so they could be forged.
    """
    settings: Settings = request.app.state.settings
    if is_local(settings, client_ip(request)):
        return
    # A short database session: the dependency must not hold a connection for the length of an audio stream.
    with SessionLocal() as db:
        try:
            user_for_token(db, settings, current_session_token(request))
        except HTTPException:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only available from the local network") from None


def logged_in_user_id(request: Request) -> int:
    """The id of the logged-in user, without keeping a database connection open for the rest of the request.

    For endpoints that stream for a long time.
    """
    settings: Settings = request.app.state.settings
    with SessionLocal() as db:
        return user_for_token(db, settings, current_session_token(request)).id
