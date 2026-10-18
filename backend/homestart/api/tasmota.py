import asyncio
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, field_validator

from ..db import SessionLocal
from ..models import User
from ..security import SESSION_COOKIE, get_current_user, require_admin, user_for_token
from ..services.tasmota.manager import DeviceError, TasmotaManager
from ..services.tasmota.mqtt_link import MqttUnavailable

router = APIRouter(tags=["tasmota"])

HOST_PATTERN = r"^[A-Za-z0-9.-]{1,253}$"


def get_manager(request: Request) -> TasmotaManager:
    return request.app.state.tasmota


def _optional_text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


class DeviceCreate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    host: str = Field(pattern=HOST_PATTERN)
    port: int = Field(default=80, ge=1, le=65535)
    group_name: str | None = Field(default=None, max_length=64)

    _clean = field_validator("name", "group_name")(_optional_text)


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    group_name: str | None = Field(default=None, max_length=64)

    _clean = field_validator("name", "group_name")(_optional_text)


class PowerRequest(BaseModel):
    channel: int = Field(default=1, ge=1, le=32)
    action: Literal["on", "off", "toggle"]


class CredentialsUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # None keeps the stored password, so the form does not need to show it.
    password: str | None = Field(default=None, max_length=128)


def _raise(exc: DeviceError | MqttUnavailable):
    if isinstance(exc, MqttUnavailable):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MQTT broker is not connected") from exc
    raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/api/tasmota/devices")
def list_devices(_: User = Depends(get_current_user), manager: TasmotaManager = Depends(get_manager)):
    return {"mqtt_connected": manager.mqtt_connected, "devices": manager.snapshot()}


@router.post("/api/tasmota/devices", status_code=status.HTTP_201_CREATED)
async def add_device(
    body: DeviceCreate, _: User = Depends(require_admin), manager: TasmotaManager = Depends(get_manager)
):
    try:
        return await manager.add_manual(body.name, body.host, body.port, body.group_name)
    except DeviceError as exc:
        _raise(exc)


@router.get("/api/tasmota/devices/{device_id}/status")
def device_status(device_id: int, _: User = Depends(get_current_user), manager: TasmotaManager = Depends(get_manager)):
    try:
        return manager.view(manager.get(device_id))
    except DeviceError as exc:
        _raise(exc)


@router.put("/api/tasmota/devices/{device_id}")
def update_device(
    device_id: int,
    body: DeviceUpdate,
    _: User = Depends(require_admin),
    manager: TasmotaManager = Depends(get_manager),
):
    try:
        return manager.update_device(device_id, body.name, body.group_name)
    except DeviceError as exc:
        _raise(exc)


@router.delete("/api/tasmota/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_device(device_id: int, _: User = Depends(require_admin), manager: TasmotaManager = Depends(get_manager)):
    try:
        manager.remove(device_id)
    except DeviceError as exc:
        _raise(exc)


@router.post("/api/tasmota/devices/{device_id}/power")
async def set_power(
    device_id: int,
    body: PowerRequest,
    _: User = Depends(get_current_user),
    manager: TasmotaManager = Depends(get_manager),
):
    try:
        return await manager.set_power(device_id, body.channel, body.action)
    except (DeviceError, MqttUnavailable) as exc:
        _raise(exc)


@router.post("/api/tasmota/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh(_: User = Depends(get_current_user), manager: TasmotaManager = Depends(get_manager)):
    try:
        await manager.refresh()
    except (DeviceError, MqttUnavailable) as exc:
        _raise(exc)
    return {"mqtt_connected": manager.mqtt_connected}


@router.post("/api/tasmota/scan")
async def scan(_: User = Depends(require_admin), manager: TasmotaManager = Depends(get_manager)):
    return await manager.scan()


@router.get("/api/tasmota/credentials")
def get_credentials(_: User = Depends(require_admin), manager: TasmotaManager = Depends(get_manager)):
    credentials = manager.credentials()
    return {
        "username": credentials.username if credentials else None,
        "has_password": bool(credentials and credentials.password),
    }


@router.put("/api/tasmota/credentials", status_code=status.HTTP_204_NO_CONTENT)
def set_credentials(
    body: CredentialsUpdate, _: User = Depends(require_admin), manager: TasmotaManager = Depends(get_manager)
):
    manager.set_credentials(body.username.strip(), body.password)


@router.delete("/api/tasmota/credentials", status_code=status.HTTP_204_NO_CONTENT)
def clear_credentials(_: User = Depends(require_admin), manager: TasmotaManager = Depends(get_manager)):
    manager.set_credentials(None, None)


@router.websocket("/ws/tasmota")
async def device_updates(websocket: WebSocket):
    # Browsers send cookies on cross-site WebSocket handshakes, so the origin must be checked explicitly.
    origin = websocket.headers.get("origin")
    if origin and urlsplit(origin).netloc != websocket.headers.get("host"):
        await websocket.close(code=4403)
        return
    try:
        with SessionLocal() as db:
            user_for_token(db, websocket.app.state.settings, websocket.cookies.get(SESSION_COOKIE))
    except HTTPException:
        await websocket.close(code=4401)
        return

    manager: TasmotaManager = websocket.app.state.tasmota
    await websocket.accept()
    queue = manager.subscribe()
    receiver: asyncio.Task | None = None

    async def send_snapshot() -> None:
        await websocket.send_json(
            {"type": "snapshot", "mqtt_connected": manager.mqtt_connected, "devices": manager.snapshot()}
        )

    try:
        await send_snapshot()
        receiver = asyncio.create_task(websocket.receive_text())
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                receiver.result()  # raises WebSocketDisconnect when the browser closes the page
                receiver = asyncio.create_task(websocket.receive_text())
                continue
            message = getter.result()
            if message["type"] == "resync":
                await send_snapshot()
            else:
                await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(queue)
        if receiver and not receiver.done():
            receiver.cancel()
