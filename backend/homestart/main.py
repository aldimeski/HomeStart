import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, func, select

from .api import auth, icons, links, users
from .config import Settings, prepare_directories
from .db import SessionLocal, make_engine
from .models import ROLE_ADMIN, User, UserSettings
from .security import CSRF_HEADER, hash_password

log = logging.getLogger("homestart")

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Linked pages are shown in iframes, so frame-src must allow any http(s) address.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "frame-src http: https:; frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
)


def run_migrations(engine: Engine) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def ensure_initial_admin() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return
        db.add(
            User(
                username="admin",
                password_hash=hash_password("admin"),
                role=ROLE_ADMIN,
                settings=UserSettings(),
            )
        )
        db.commit()
        log.warning("Created initial administrator 'admin' with the default password; change it in Configuration")


def create_app(settings: Settings) -> FastAPI:
    prepare_directories(settings)
    engine = make_engine(settings.db_file)
    SessionLocal.configure(bind=engine)
    run_migrations(engine)
    ensure_initial_admin()

    app = FastAPI(title="HomeStart", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings

    @app.middleware("http")
    async def csrf_and_headers(request: Request, call_next):
        # Browsers do not allow cross-site pages to set custom headers without CORS,
        # so requiring one blocks forged form posts and cross-site fetches.
        if (
            request.url.path.startswith("/api/")
            and request.method not in SAFE_METHODS
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing CSRF header"}, status_code=status.HTTP_403_FORBIDDEN)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(GZipMiddleware, minimum_size=1024)

    for module in (auth, users, links, icons):
        app.include_router(module.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
    def api_not_found(rest: str):
        return JSONResponse({"detail": "Not found"}, status_code=status.HTTP_404_NOT_FOUND)

    _mount_frontend(app, settings.frontend_dir)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.is_file():
        log.warning("Frontend build not found in %s; run 'npm run build' in frontend/", dist)
        return

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    dist_resolved = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist_resolved):
            return FileResponse(candidate)
        # Client-side routes (e.g. /link/3) all load the single-page app.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
