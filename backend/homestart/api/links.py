from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Link, User
from ..schemas import EmbedCheck, LinkCreate, LinkOrder, LinkOut, LinkUpdate
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/links", tags=["links"])

EMBED_CHECK_TIMEOUT = 4.0


def _get_link(db: Session, link_id: int) -> Link:
    link = db.get(Link, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    return link


@router.get("", response_model=list[LinkOut])
def list_links(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Link).order_by(Link.sort_order, Link.id)).all()


@router.post("", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
def create_link(body: LinkCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    next_order = (db.scalar(select(func.max(Link.sort_order))) or 0) + 1
    link = Link(**body.model_dump(), created_by=admin.id, sort_order=next_order)
    db.add(link)
    db.commit()
    return link


@router.put("/order", response_model=list[LinkOut])
def reorder_links(body: LinkOrder, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    links = {link.id: link for link in db.scalars(select(Link)).all()}
    if sorted(body.ids) != sorted(links):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The order must list every link exactly once")
    for position, link_id in enumerate(body.ids, start=1):
        links[link_id].sort_order = position
    db.commit()
    return [links[link_id] for link_id in body.ids]


@router.put("/{link_id}", response_model=LinkOut)
def update_link(link_id: int, body: LinkUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    link = _get_link(db, link_id)
    for field, value in body.model_dump().items():
        setattr(link, field, value)
    db.commit()
    return link


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(link_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    db.delete(_get_link(db, link_id))
    db.commit()


def _frame_blocked_reason(headers: httpx.Headers, app_origin: str, target_origin: str) -> str | None:
    app_host = urlsplit(app_origin).hostname or ""
    xfo = headers.get("x-frame-options", "").strip().lower()
    if xfo in ("deny", "sameorigin"):
        return f"The site sends X-Frame-Options: {xfo.upper()}"

    for policy in headers.get_list("content-security-policy"):
        for directive in policy.split(";"):
            name, _, sources = directive.strip().partition(" ")
            if name.lower() != "frame-ancestors":
                continue
            tokens = sources.lower().split()
            if (
                "*" in tokens
                or ("'self'" in tokens and app_origin == target_origin)
                or (app_host and any(app_host in token for token in tokens))
            ):
                return None
            return "The site's Content-Security-Policy (frame-ancestors) forbids embedding"
    return None


@router.get("/{link_id}/embed-check", response_model=EmbedCheck)
async def embed_check(
    link_id: int,
    request: Request,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Checks from the server whether the stored link URL allows being shown in an iframe.

    Only URLs already saved by an administrator are fetched, so this endpoint cannot be used
    to make the server request arbitrary addresses.
    """
    link = _get_link(db, link_id)
    try:
        async with httpx.AsyncClient(timeout=EMBED_CHECK_TIMEOUT, follow_redirects=True, verify=False) as client:
            response = await client.get(link.url, headers={"Accept": "text/html"})
    except httpx.HTTPError:
        # The browser may still reach an address the server cannot, so this is not treated as an error.
        return EmbedCheck(reachable=False, embeddable=None)

    app_origin = str(request.base_url).rstrip("/")
    target = urlsplit(str(response.url))
    reason = _frame_blocked_reason(response.headers, app_origin, f"{target.scheme}://{target.netloc}")
    return EmbedCheck(reachable=True, embeddable=reason is None, reason=reason)
