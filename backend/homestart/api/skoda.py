import hashlib

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..models import User
from ..security import current_session_token, get_current_user
from ..services.skoda.service import SkodaError, SkodaService

router = APIRouter(prefix="/api/skoda", tags=["skoda"])

VIN_PATTERN = r"^[A-HJ-NPR-Z0-9]{17}$"


def get_service(request: Request) -> SkodaService:
    return request.app.state.skoda


def _session_key(request: Request) -> str:
    # Identifies the HomeStart login, so the first visit after each login fetches fresh data.
    return hashlib.sha256((current_session_token(request) or "").encode()).hexdigest()


class AccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    force: bool = False


def _raise(exc: SkodaError):
    raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/vehicles")
def vehicles(user: User = Depends(get_current_user), service: SkodaService = Depends(get_service)):
    return service.overview(user.id)


@router.put("/account")
async def connect_account(
    body: AccountIn,
    request: Request,
    user: User = Depends(get_current_user),
    service: SkodaService = Depends(get_service),
):
    try:
        return await service.sign_in(user.id, body.username.strip(), body.password, _session_key(request))
    except SkodaError as exc:
        # The terms or consent page belongs to this login attempt, so it goes to the browser and not to the log.
        return JSONResponse({"detail": str(exc), "action_url": exc.action_url}, status_code=exc.status_code)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(user: User = Depends(get_current_user), service: SkodaService = Depends(get_service)):
    service.sign_out(user.id)


@router.post("/refresh")
async def refresh(
    body: RefreshIn,
    request: Request,
    user: User = Depends(get_current_user),
    service: SkodaService = Depends(get_service),
):
    try:
        refreshed = await service.refresh(user.id, _session_key(request), body.force)
    except SkodaError as exc:
        _raise(exc)
    return {"refreshed": refreshed, **service.overview(user.id)}


@router.get("/vehicles/{vin}/image")
def vehicle_image(
    vin: str = Path(pattern=VIN_PATTERN),
    user: User = Depends(get_current_user),
    service: SkodaService = Depends(get_service),
):
    path = service.image_path(user.id, vin)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture of this vehicle")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
