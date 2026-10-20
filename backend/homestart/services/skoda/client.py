"""Reads vehicle data from the MyŠkoda API through the myskoda library.

This is the only module that talks to the library, and it calls read-only methods only: HomeStart never sends
commands to a vehicle. Library objects are turned into plain dicts here, so the stored cache and the API do not
depend on the library version.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from myskoda import MySkoda
from myskoda.auth.authorization import (
    AuthorizationError,
    AuthorizationFailedError,
    MarketingConsentError,
    NotAuthorizedError,
    TermsAndConditionsError,
    TokenExpiredError,
)
from myskoda.models.status import DoorWindowState

log = logging.getLogger("homestart.skoda")

# The library logs request details at DEBUG; nothing below WARNING is needed and tokens must stay out of logs.
logging.getLogger("myskoda").setLevel(logging.WARNING)

REQUEST_TIMEOUT_SECONDS = 30
PREFERRED_VIEW_POINTS = ("MAIN", "EXTERIOR_SIDE", "EXTERIOR_FRONT")


class SkodaLoginError(Exception):
    """The account rejected the login; the message is shown to the user."""


class SkodaUnavailable(Exception):
    """Škoda servers could not be reached or answered unexpectedly; the message is shown to the user."""


@dataclass
class FetchResult:
    refresh_token: str | None
    vehicles: list[dict[str, Any]]


def _enum(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _open_state(value: Any) -> str:
    text = (_enum(value) or "").upper()
    return {"OPEN": "open", "CLOSED": "closed", "UNSUPPORTED": "unsupported"}.get(text, "unknown")


def _door_and_window(state: DoorWindowState) -> tuple[str, str]:
    return {
        DoorWindowState.CLOSED: ("closed", "closed"),
        DoorWindowState.WINDOW_OPEN: ("closed", "open"),
        DoorWindowState.DOOR_OPEN: ("open", "closed"),
        DoorWindowState.ALL_OPEN: ("open", "open"),
    }.get(state, ("unknown", "unknown"))


def _lock_state(overall: Any) -> str:
    reliable = (_enum(getattr(overall, "reliable_lock_status", None)) or "").upper()
    if reliable in ("LOCKED", "UNLOCKED"):
        return reliable.lower()
    locked = (_enum(getattr(overall, "locked", None)) or "").upper()
    if locked == "YES":
        return "locked"
    if locked in ("NO", "OPENED", "TRUNK_OPENED"):
        return "unlocked"
    return "unknown"


def _image_url(info: Any) -> str | None:
    renders = getattr(info, "renders", None) or []
    for view_point in PREFERRED_VIEW_POINTS:
        for render in renders:
            if _enum(render.view_point) == view_point and render.url.startswith("https://"):
                return render.url
    return next((r.url for r in renders if r.url.startswith("https://")), None)


def _timestamp(*responses: Any) -> str | None:
    """When the car itself last reported, if the API says so."""
    stamps = [r.car_captured_timestamp for r in responses if r is not None and r.car_captured_timestamp]
    return max(stamps).isoformat() if stamps else None


def vehicle_data(vin: str, info: Any, status: Any, parking: Any, driving_range: Any, health: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"vin": vin, "unavailable": []}

    if info is not None:
        spec = info.specification
        data.update(
            name=info.name,
            title=spec.title,
            model=spec.model,
            model_year=spec.model_year,
            body=_enum(spec.body),
            license_plate=getattr(info, "license_plate", None),
            exterior_colour=getattr(spec, "exterior_colour", None),
            image_url=_image_url(info),
        )
    else:
        data["unavailable"].append("vehicle details")

    if status is not None:
        doors, windows = {}, {}
        for key, attr in (
            ("front_left", "left_front_door"),
            ("front_right", "right_front_door"),
            ("rear_left", "left_back_door"),
            ("rear_right", "right_back_door"),
        ):
            doors[key], windows[key] = _door_and_window(getattr(status, attr))
        data.update(
            doors=doors,
            windows=windows,
            windows_overall=_open_state(status.overall.windows),
            trunk=_open_state(status.detail.trunk),
            bonnet=_open_state(status.detail.bonnet),
            sunroof=_open_state(status.detail.sunroof),
            lock=_lock_state(status.overall),
            lights=(_enum(status.overall.lights) or "unknown").lower(),
        )
    else:
        data["unavailable"].append("doors and lock status")

    if parking is not None:
        coordinates = parking.parking_position.gps_coordinates
        data["position"] = {
            "latitude": coordinates.latitude,
            "longitude": coordinates.longitude,
            "address": parking.parking_position.formatted_address,
        }
    else:
        data["unavailable"].append("parking position")

    if driving_range is not None:
        primary = driving_range.primary_engine_range
        secondary = driving_range.secondary_engine_range
        engines = [engine for engine in (primary, secondary) if engine is not None]
        data.update(
            engine_type=_enum(driving_range.car_type),
            range_km=driving_range.total_range_in_km or primary.remaining_range_in_km,
            fuel_percent=next((e.current_fuel_level_in_percent for e in engines if e.current_fuel_level_in_percent is not None), None),
            battery_percent=next((e.current_soc_in_percent for e in engines if e.current_soc_in_percent is not None), None),
        )
    else:
        data["unavailable"].append("range and fuel level")

    if health is not None:
        data["mileage_km"] = health.mileage_in_km
    else:
        data["unavailable"].append("mileage")

    data["captured_at"] = _timestamp(status, parking, driving_range)
    return data


async def _optional(call, what: str, vin: str) -> Any:
    """A vehicle may lack a capability (e.g. no parking position while driving); that part is then missing."""
    try:
        return await call(vin)
    except (aiohttp.ClientError, TimeoutError):
        raise
    except Exception as exc:  # the library raises plain errors for unsupported capabilities
        log.info("Škoda %s not available for a vehicle: %s", what, type(exc).__name__)
        return None


async def fetch_account(username: str, password: str, refresh_token: str | None) -> FetchResult:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)) as session:
            api = MySkoda(session, mqtt_enabled=False)
            await _login(api, username, password, refresh_token)
            vehicles = []
            for vin in await api.list_vehicle_vins():
                info, status, parking, driving_range, health = await asyncio.gather(
                    _optional(api.get_info, "vehicle details", vin),
                    _optional(api.get_status, "status", vin),
                    _optional(api.get_parking_position, "parking position", vin),
                    _optional(api.get_driving_range, "driving range", vin),
                    _optional(api.get_health, "mileage", vin),
                )
                vehicles.append(vehicle_data(vin, info, status, parking, driving_range, health))
            new_token = await api.get_refresh_token()
            return FetchResult(new_token, vehicles)
    except (SkodaLoginError, SkodaUnavailable):
        raise
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise SkodaUnavailable("The Škoda servers cannot be reached right now.") from exc
    except Exception as exc:
        log.warning("Unexpected answer from the Škoda API: %s", type(exc).__name__)
        raise SkodaUnavailable(
            "The Škoda servers answered unexpectedly. The MyŠkoda API may have changed; an update of HomeStart may be needed."
        ) from exc


async def _login(api: MySkoda, username: str, password: str, refresh_token: str | None) -> None:
    if refresh_token:
        try:
            await api.connect(refresh_token=refresh_token)
            return
        except (TokenExpiredError, NotAuthorizedError, AuthorizationFailedError):
            log.info("Stored Škoda session expired; signing in with the password again")
    try:
        await api.connect(email=username, password=password)
    except (TermsAndConditionsError, MarketingConsentError) as exc:
        raise SkodaLoginError(
            "Škoda asks you to accept new terms or a consent screen. Open the MyŠkoda app, accept it and try again."
        ) from exc
    except (AuthorizationFailedError, AuthorizationError, NotAuthorizedError) as exc:
        raise SkodaLoginError("The MyŠkoda account rejected the email address or password.") from exc
