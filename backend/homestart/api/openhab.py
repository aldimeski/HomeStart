"""Forwards openHAB (Basic UI, icons, REST) through HomeStart, so a device only talks to one address.

Only the paths listed in `openhab_paths` are forwarded, and only to `openhab_url` from the settings.
"""

import logging

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask

from ..access import require_local_or_user
from ..config import Settings
from ..security import SESSION_COOKIE

log = logging.getLogger("homestart.openhab")

METHODS = ["GET", "HEAD", "POST", "PUT", "DELETE"]
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.openhab_url,
        verify=settings.openhab_verify_tls,
        # No read timeout: Basic UI keeps a connection open to receive state changes.
        timeout=httpx.Timeout(10.0, read=None),
        limits=httpx.Limits(max_connections=50),
        transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", verify=settings.openhab_verify_tls),
    )


def _request_headers(request: Request) -> dict[str, str]:
    headers = {}
    for name, value in request.headers.items():
        if name in HOP_BY_HOP or name in ("host", "content-length", "accept-encoding"):
            continue
        if name == "cookie":
            # HomeStart's own session must not reach openHAB.
            value = "; ".join(part for part in value.split("; ") if not part.startswith(f"{SESSION_COOKIE}="))
            if not value:
                continue
        headers[name] = value
    headers["accept-encoding"] = "identity"
    return headers


def register(app: FastAPI, settings: Settings) -> None:
    if not settings.openhab_url:
        return

    async def forward(request: Request):
        client: httpx.AsyncClient = request.app.state.openhab
        # The page comes from openHAB with its own security policy, which HomeStart must not replace.
        request.state.skip_csp = True
        target = request.scope.get("raw_path", request.url.path.encode()).decode()
        if request.url.query:
            target += f"?{request.url.query}"
        try:
            upstream_request = client.build_request(
                request.method, target, headers=_request_headers(request), content=await request.body()
            )
            upstream = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            log.warning("openHAB did not answer (%s)", type(exc).__name__)
            return PlainTextResponse("openHAB is not reachable", status_code=502)

        headers = []
        for name, value in upstream.headers.multi_items():
            name = name.lower()
            if name in HOP_BY_HOP or name == "x-frame-options":
                continue
            if name == "location" and value.startswith(settings.openhab_url):
                value = value[len(settings.openhab_url) :] or "/"
            headers.append((name.encode(), value.encode()))
        if not any(name == b"content-encoding" for name, _ in headers):
            # Marks the body as already encoded, so the gzip middleware does not hold back live updates.
            headers.append((b"content-encoding", b"identity"))

        response = StreamingResponse(
            upstream.aiter_raw(), status_code=upstream.status_code, background=BackgroundTask(upstream.aclose)
        )
        response.raw_headers = headers
        return response

    for prefix in settings.openhab_paths:
        for path in (prefix, f"{prefix}/{{rest:path}}"):
            app.add_api_route(
                path, forward, methods=METHODS, include_in_schema=False, dependencies=[Depends(require_local_or_user)]
            )
