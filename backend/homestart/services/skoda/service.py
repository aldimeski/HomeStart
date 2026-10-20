"""MyŠkoda accounts per HomeStart user, the vehicle cache and when to ask Škoda for fresh data.

Fresh data is fetched only on demand: the first time a user opens the Škoda page after logging in to HomeStart,
when the cached data is older than AUTO_REFRESH_AFTER, or when the user presses Refresh.
"""

import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select

from ...config import Settings
from ...db import SessionLocal
from ...models import SkodaAccount, VehicleCache, utcnow
from ..secret_box import SecretBox
from . import client
from .client import SkodaLoginError, SkodaUnavailable

log = logging.getLogger("homestart.skoda")

AUTO_REFRESH_AFTER = timedelta(minutes=15)
MAX_REMEMBERED_SESSIONS = 1000
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class SkodaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _is_public_https(url: str) -> bool:
    """Vehicle images are downloaded by the server, so their address must not point into the local network."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


class SkodaService:
    def __init__(self, settings: Settings, secret_box: SecretBox):
        self.box = secret_box
        self.images_dir = settings.cache_dir / "skoda"
        self._fetch = client.fetch_account  # replaced in tests
        self._locks: dict[int, asyncio.Lock] = {}
        # Login sessions that already fetched fresh data; an insertion-ordered dict used as a bounded set.
        self._synced_sessions: dict[str, None] = {}

    # --- reading ---------------------------------------------------------------------

    def _account(self, db, user_id: int) -> SkodaAccount | None:
        return db.scalar(select(SkodaAccount).where(SkodaAccount.user_id == user_id))

    def overview(self, user_id: int) -> dict[str, Any]:
        with SessionLocal() as db:
            account = self._account(db, user_id)
            if account is None:
                return {"account": {"connected": False}, "vehicles": []}
            rows = db.scalars(
                select(VehicleCache).where(VehicleCache.account_id == account.id).order_by(VehicleCache.name)
            ).all()
            return {"account": self._account_view(account), "vehicles": [self._vehicle_view(row) for row in rows]}

    def _account_view(self, account: SkodaAccount) -> dict[str, Any]:
        try:
            username = self.box.decrypt(account.username_enc)
        except Exception:
            username = None
        return {
            "connected": True,
            "username": username,
            "last_sync": account.last_sync.isoformat() if account.last_sync else None,
            "last_error": account.last_error,
        }

    @staticmethod
    def _vehicle_view(row: VehicleCache) -> dict[str, Any]:
        data = json.loads(row.data_json)
        data.pop("image_url", None)  # the browser gets the cached copy instead
        return {**data, "has_image": bool(row.image_file), "updated_at": row.updated_at.isoformat()}

    def image_path(self, user_id: int, vin: str) -> Path | None:
        with SessionLocal() as db:
            account = self._account(db, user_id)
            if account is None:
                return None
            row = db.scalar(select(VehicleCache).where(VehicleCache.account_id == account.id, VehicleCache.vin == vin))
        if row is None or not row.image_file:
            return None
        path = self.images_dir / row.image_file
        return path if path.is_file() else None

    # --- account ---------------------------------------------------------------------

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    def _remember_session(self, session_key: str) -> None:
        self._synced_sessions[session_key] = None
        while len(self._synced_sessions) > MAX_REMEMBERED_SESSIONS:
            del self._synced_sessions[next(iter(self._synced_sessions))]

    async def sign_in(self, user_id: int, username: str, password: str, session_key: str) -> dict[str, Any]:
        async with self._lock(user_id):
            try:
                result = await self._fetch(username, password, None)
            except SkodaLoginError as exc:
                raise SkodaError(str(exc), 400) from exc
            except SkodaUnavailable as exc:
                raise SkodaError(str(exc), 502) from exc
            images = await self._download_images(result, {})

            with SessionLocal() as db:
                account = self._account(db, user_id)
                if account is not None:
                    # Reconnecting the same account downloads the same pictures, under the same file names.
                    self._delete_images(db, account, keep=set(images.values()))
                    db.delete(account)
                    db.flush()
                account = SkodaAccount(
                    user_id=user_id,
                    username_enc=self.box.encrypt(username),
                    password_enc=self.box.encrypt(password),
                )
                db.add(account)
                db.flush()
                self._store(db, account, result, images)
                db.commit()
            self._remember_session(session_key)
            log.info("MyŠkoda account connected for user %d (%d vehicles)", user_id, len(result.vehicles))
        return self.overview(user_id)

    def sign_out(self, user_id: int) -> None:
        with SessionLocal() as db:
            account = self._account(db, user_id)
            if account is None:
                return
            self._delete_images(db, account)
            db.delete(account)  # vehicles_cache rows go with it (ON DELETE CASCADE)
            db.commit()
        log.info("MyŠkoda account removed for user %d", user_id)

    def _delete_images(self, db, account: SkodaAccount, keep: set[str | None] = frozenset()) -> None:
        for name in db.scalars(select(VehicleCache.image_file).where(VehicleCache.account_id == account.id)):
            if name and name not in keep:
                (self.images_dir / name).unlink(missing_ok=True)

    # --- refreshing --------------------------------------------------------------------

    async def refresh(self, user_id: int, session_key: str, force: bool) -> bool:
        """Returns True when Škoda was asked; problems are stored as last_error and the cache stays shown."""
        async with self._lock(user_id):
            # No database transaction stays open while waiting for Škoda: SQLite would refuse a later write
            # if another part of HomeStart wrote in the meantime.
            with SessionLocal() as db:
                account = self._account(db, user_id)
                if account is None:
                    raise SkodaError("No MyŠkoda account is connected", 404)
                recent = account.last_attempt and utcnow() - account.last_attempt < AUTO_REFRESH_AFTER
                if not force and session_key in self._synced_sessions and recent:
                    return False
                account_id = account.id
                try:
                    username = self.box.decrypt(account.username_enc)
                    password = self.box.decrypt(account.password_enc)
                    token = self.box.decrypt(account.refresh_token_enc) if account.refresh_token_enc else None
                except Exception:
                    log.error("Stored MyŠkoda login cannot be decrypted; was the key file replaced?")
                    account.last_error = "The stored MyŠkoda login cannot be read. Sign out and connect the account again."
                    account.last_attempt = utcnow()
                    db.commit()
                    return True
                known = {
                    row.vin: (json.loads(row.data_json).get("image_url"), row.image_file)
                    for row in db.scalars(select(VehicleCache).where(VehicleCache.account_id == account_id))
                }

            self._remember_session(session_key)
            error: Exception | None = None
            try:
                result = await self._fetch(username, password, token)
                images = await self._download_images(result, known)
            except (SkodaLoginError, SkodaUnavailable) as exc:
                error = exc
                log.warning("MyŠkoda refresh failed for user %d: %s", user_id, type(exc).__name__)

            with SessionLocal() as db:
                account = db.get(SkodaAccount, account_id)
                if account is None:  # signed out while Škoda was being asked
                    return True
                account.last_attempt = utcnow()
                if error is None:
                    self._store(db, account, result, images)
                else:
                    account.last_error = str(error)
                    if isinstance(error, SkodaLoginError):
                        account.refresh_token_enc = None
                db.commit()
            return True

    def _store(self, db, account: SkodaAccount, result: client.FetchResult, images: dict[str, str | None]) -> None:
        now = utcnow()
        if result.refresh_token:
            account.refresh_token_enc = self.box.encrypt(result.refresh_token)
        account.last_sync = account.last_attempt = now
        account.last_error = None

        existing = {row.vin: row for row in db.scalars(select(VehicleCache).where(VehicleCache.account_id == account.id))}
        vins = set()
        for data in result.vehicles:
            vin = data["vin"]
            vins.add(vin)
            row = existing.get(vin) or VehicleCache(account_id=account.id, vin=vin)
            row.name = data.get("name") or data.get("title") or vin
            row.data_json = json.dumps(data)
            row.updated_at = now
            row.image_file = images.get(vin, row.image_file)
            db.add(row)

        # Vehicles removed from the MyŠkoda account disappear here too.
        for vin, row in existing.items():
            if vin not in vins:
                if row.image_file:
                    (self.images_dir / row.image_file).unlink(missing_ok=True)
                db.execute(delete(VehicleCache).where(VehicleCache.id == row.id))

    async def _download_images(
        self, result: client.FetchResult, known: dict[str, tuple[str | None, str | None]]
    ) -> dict[str, str | None]:
        """New image file per VIN; a vehicle whose picture did not change keeps its cached file."""
        images: dict[str, str | None] = {}
        for data in result.vehicles:
            url = data.get("image_url")
            old_url, old_file = known.get(data["vin"], (None, None))
            if url and (url != old_url or not old_file or not (self.images_dir / old_file).is_file()):
                images[data["vin"]] = await self._download_image(url, old_file)
        return images

    async def _download_image(self, url: str, old_file: str | None) -> str | None:
        if not await asyncio.to_thread(_is_public_https, url):
            log.warning("Ignoring a vehicle image address outside the internet")
            return old_file
        try:
            # IPv4 only: on networks without IPv6, httpx would wait about 5 s before falling back.
            transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, transport=transport) as http:
                response = await http.get(url)
        except httpx.HTTPError:
            return old_file
        extension = IMAGE_TYPES.get(response.headers.get("content-type", "").split(";")[0].strip())
        if response.status_code != 200 or extension is None or len(response.content) > IMAGE_MAX_BYTES:
            return old_file

        self.images_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(url.encode()).hexdigest()[:32] + extension
        (self.images_dir / name).write_bytes(response.content)
        if old_file and old_file != name:
            (self.images_dir / old_file).unlink(missing_ok=True)
        return name
