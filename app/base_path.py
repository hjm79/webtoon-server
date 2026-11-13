"""Public URL prefix without changing internal API routes or persisted data."""
import json
import os
import re
from pathlib import Path

import anyio
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request, cookie_parser


def parse_base_path(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if not re.fullmatch(r"/[A-Za-z0-9_~.-]+(?:/[A-Za-z0-9_~.-]+)*", value):
        raise ValueError("BASE_PATH must be an absolute path prefix")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError("BASE_PATH cannot contain dot segments")
    return value


BASE_PATH = parse_base_path(os.environ.get("BASE_PATH", ""))
_SENTINEL = "__WEBTOON_BASE_PATH__"


def public_path(path: str) -> str:
    return BASE_PATH + path


def cookie_path() -> str:
    return BASE_PATH + "/"


def device_cookie(request: Request, name: str) -> str | None:
    if not BASE_PATH:
        return request.cookies.get(name)
    # Browsers send the longer matching cookie path first; do not let a legacy
    # root cookie override that selected device or fall back to another device.
    for chunk in request.headers.get("cookie", "").split(";"):
        parsed = cookie_parser(chunk)
        if name in parsed:
            return parsed[name]
    return None


async def html_response(path: str | Path) -> HTMLResponse:
    text = await anyio.Path(path).read_text(encoding="utf-8")
    return HTMLResponse(text.replace(_SENTINEL, BASE_PATH), headers={"Cache-Control": "no-store"})


class PublicStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers):
        if response_headers.get("content-type", "").startswith(("text/html", "application/json", "text/javascript", "application/javascript", "text/css")):
            return False
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code != 200 or not getattr(response, "path", None):
            return response
        if response.media_type == "text/html":
            return await html_response(response.path)
        if response.media_type in ("text/javascript", "application/javascript", "text/css"):
            response.headers["Cache-Control"] = "no-store"
        if path == "manifest.json":
            manifest = json.loads(await anyio.Path(response.path).read_text(encoding="utf-8"))
            profile = scope.get("state", {}).get("profile")
            prefix = BASE_PATH + (f"/p/{profile['token']}" if profile else "")
            manifest["start_url"] = prefix + "/"
            manifest["scope"] = prefix + "/"
            for icon in manifest.get("icons", []):
                icon["src"] = public_path(icon["src"])
            return JSONResponse(manifest, headers={"Cache-Control": "no-store"})
        return response
