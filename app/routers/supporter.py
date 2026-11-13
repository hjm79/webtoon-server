"""Read-only library summaries for a separately authenticated dashboard."""

import ipaddress
import math
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import access_control, base_path, catalog, covers, db, services

_NO_STORE = {"Cache-Control": "no-store"}
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def require_supporter_token(request: Request) -> None:
    if access_control.get_profile(request) is not None or request.url.path.startswith("/p/"):
        raise HTTPException(404, "Not Found", headers=_NO_STORE)
    expected = os.environ.get("SUPPORTER_API_TOKEN", "")
    if not expected or not expected.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in expected):
        raise HTTPException(503, "supporter API is not configured", headers=_NO_STORE)
    values = request.headers.getlist("authorization")
    supplied = values[0] if len(values) == 1 else ""
    if not secrets.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(401, "invalid supporter token", headers={**_NO_STORE, "WWW-Authenticate": "Bearer"})


router = APIRouter(dependencies=[Depends(require_supporter_token)])


def public_base_url() -> str:
    raw = services.PUBLIC_BASE_URL
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        if (not raw or len(raw) > 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in raw)
                or parsed.scheme not in ("http", "https") or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") != base_path.BASE_PATH):
            raise ValueError
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.lower().rstrip(".") == "localhost" or host.lower().endswith(".localhost"):
                raise ValueError from None
        else:
            if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
                raise ValueError
    except ValueError:
        raise HTTPException(503, "supporter public URL is not configured", headers=_NO_STORE) from None
    return urlunsplit((parsed.scheme, parsed.netloc, base_path.BASE_PATH, "", ""))


def _timestamp(value) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _last_read(value) -> tuple[str | None, float]:
    if not isinstance(value, str) or not value:
        return None, 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(), parsed.timestamp()
    except (ValueError, OverflowError):
        return None, 0


def _iso_timestamp(timestamp: float) -> str | None:
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else None
    except (ValueError, OverflowError, OSError):
        return None


def _shelf_items(public: str) -> list[dict]:
    items = []
    for series in catalog.get_series_map().values():
        sid = series.get("id")
        if series.get("excluded") or not isinstance(sid, str) or not _ID.fullmatch(sid):
            continue
        chapters = series["chapters"]
        progress = db.get_progress(sid)
        metadata = db.get_progress_metadata(sid) or {}
        last_read, last_read_timestamp = _last_read(metadata.get("updated_at"))
        read_ids = db.get_read_chapter_ids(sid)
        unread = sum(chapter["id"] not in read_ids for chapter in chapters)
        latest_timestamp = _timestamp(series.get("latest_mtime"))
        reading = services.reading_chapter(chapters, progress)
        offset = _timestamp(metadata.get("page_offset")) if reading else 0
        page_index = max(0, progress["page_index"]) if reading else 0
        items.append({
            "id": sid,
            "title": series["title"],
            "platform": series["platform"],
            "coverUrl": public + covers.cover_url(series),
            "href": public + "/reader.html?" + urlencode({"series": sid}),
            "lastReadAt": last_read,
            "pageIndex": page_index,
            "pageOffset": min(offset, 1),
            "chapterCount": len(chapters),
            "unreadCount": unread,
            "lastChapter": reading["label"] if reading else None,
            "latestChapter": chapters[-1]["label"] if chapters else None,
            "isNew": bool(unread and (not last_read or latest_timestamp > last_read_timestamp)),
            "readingNow": reading is not None,
            "latestUpdatedAt": _iso_timestamp(latest_timestamp),
            "_lastReadTimestamp": last_read_timestamp,
            "_latestTimestamp": latest_timestamp,
        })
    items.sort(key=lambda item: (-item["_lastReadTimestamp"], -item["_latestTimestamp"], item["title"], item["id"]))
    for item in items:
        item.pop("_lastReadTimestamp")
        item.pop("_latestTimestamp")
    return items


@router.get("/api/supporter/shelf")
def supporter_shelf(response: Response, limit: int = Query(default=12, ge=1, le=50)):
    public = public_base_url()
    items = _shelf_items(public)
    response.headers.update(_NO_STORE)
    return {
        "status": "success",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": public,
        "items": items[:limit],
        "totals": {"count": min(len(items), limit), "available": len(items), "limit": limit},
    }


@router.get("/api/supporter/health")
def supporter_health(response: Response):
    public = public_base_url()
    response.headers.update(_NO_STORE)
    return {
        "status": "success",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baseUrl": public,
        "checks": {"tokenAccepted": True, "publicUrlConfigured": True},
    }
