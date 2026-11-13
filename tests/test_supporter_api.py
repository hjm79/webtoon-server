import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import base_path, catalog, db, scan, services
from app.routers import supporter

TOKEN = "supporter-test-only-token-with-32-bytes"
PUBLIC = "https://webtoon.example/viewer"
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def supporter_client(library, monkeypatch):
    monkeypatch.setenv("SUPPORTER_API_TOKEN", TOKEN)
    monkeypatch.setattr(services, "PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    app = FastAPI()

    @app.middleware("http")
    async def profile_state(request, call_next):
        request.state.profile = {"id": "shared"} if request.headers.get("X-Test-Profile") else None
        return await call_next(request)

    app.include_router(supporter.router)
    app.include_router(supporter.router, prefix="/p/shared")
    with TestClient(app) as client:
        yield client


def add_series(sid, *, title=None, timestamp=1000, excluded=False, chapters=2):
    values = [{"id": sid + "-" + str(i), "label": str(i + 1) + "화", "path": "/private/library/secret.zip"}
              for i in range(chapters)]
    catalog.add_series({
        "id": sid, "title": title or sid, "platform": "naver", "chapters": values,
        "latest_mtime": timestamp, "excluded": excluded, "cover_path": "/private/library/cover.jpg",
        "cover_mtime": timestamp,
    }, {chapter["id"]: chapter["path"] for chapter in values})
    return values


def metadata_stub(monkeypatch, values=None):
    monkeypatch.setattr(db, "get_progress_metadata", lambda sid: (values or {}).get(sid), raising=False)


@pytest.mark.parametrize("path", ["/api/supporter/shelf", "/api/supporter/health"])
def test_dedicated_bearer_token_is_required(supporter_client, monkeypatch, path):
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"X-Integration-Token": TOKEN},
                    {"Authorization": "bearer " + TOKEN}, {"Authorization": "Bearer " + TOKEN + " "}):
        response = supporter_client.get(path, headers=headers)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in response.text
    monkeypatch.setenv("INTEGRATION_TOKEN", "scan-test-token")
    assert supporter_client.get(path, headers={"Authorization": "Bearer scan-test-token"}).status_code == 401
    assert supporter_client.get(path + "?token=" + TOKEN).status_code == 401
    assert supporter_client.get(path, headers=[("Authorization", "Bearer " + TOKEN),
                                               ("Authorization", "Bearer wrong")]).status_code == 401
    monkeypatch.delenv("SUPPORTER_API_TOKEN")
    response = supporter_client.get(path, headers=HEADERS)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/api/supporter/shelf", "/api/supporter/health"])
def test_shared_profiles_cannot_read_admin_summaries(supporter_client, path):
    assert supporter_client.get(path, headers={**HEADERS, "X-Test-Profile": "yes"}).status_code == 404
    assert supporter_client.get("/p/shared" + path, headers=HEADERS).status_code == 404


@pytest.mark.parametrize("url", [
    "", "http://webtoon-server:8000/viewer", "http://localhost/viewer", "http://127.0.0.1/viewer",
    "http://169.254.1.1/viewer", "https://user:password@webtoon.example/viewer",
    "https://webtoon.example/viewer?token=secret", "https://webtoon.example/viewer#secret",
    "https://webtoon.example/", "https://webtoon.example/viewer/child", "file:///viewer",
    "https://webtoon.example:bad/viewer", "https://webtoon.example/viewer\n",
])
def test_invalid_public_url_fails_closed(supporter_client, monkeypatch, url):
    monkeypatch.setattr(services, "PUBLIC_BASE_URL", url)
    response = supporter_client.get("/api/supporter/shelf", headers={**HEADERS, "Host": "untrusted.example"})
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "untrusted.example" not in response.text
    assert "password" not in response.text


def test_shelf_uses_public_links_and_existing_local_progress(supporter_client, monkeypatch):
    chapters = add_series("series-a", title="긴 웹툰", timestamp=2000)
    add_series("hidden", excluded=True)
    add_series("bad/id", title="malformed ID")
    db.set_progress("series-a", chapters[0]["id"], 0, 4)
    db.mark_chapters_read("series-a", [chapters[0]["id"]])
    metadata_stub(monkeypatch, {"series-a": {"updated_at": "1970-01-01T00:20:00", "page_offset": 0.375}})
    response = supporter_client.get("/api/supporter/shelf", headers={**HEADERS, "Host": "untrusted.example"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["baseUrl"] == PUBLIC
    assert body["totals"] == {"count": 1, "available": 1, "limit": 12}
    item = body["items"][0]
    assert item == {
        "id": "series-a", "title": "긴 웹툰", "platform": "naver",
        "coverUrl": PUBLIC + "/api/series/series-a/cover?v=" + supporter.covers.cover_version(catalog.get_series("series-a")),
        "href": PUBLIC + "/reader.html?series=series-a", "lastReadAt": "1970-01-01T00:20:00+00:00",
        "pageIndex": 4, "pageOffset": 0.375, "chapterCount": 2, "unreadCount": 1,
        "lastChapter": "1화", "latestChapter": "2화", "isNew": True, "readingNow": True,
        "latestUpdatedAt": datetime.fromtimestamp(2000, timezone.utc).isoformat(),
    }
    assert "/private/" not in response.text
    assert "token" not in response.text.lower()
    assert "untrusted.example" not in response.text


def test_order_is_recent_reading_then_local_file_update_with_limit(supporter_client, monkeypatch):
    for sid, timestamp in (("never-new", 3000), ("read-new", 1000), ("read-old", 2000), ("never-old", 1000)):
        add_series(sid, timestamp=timestamp)
    metadata_stub(monkeypatch, {
        "read-new": {"updated_at": "2026-11-13T02:00:00+00:00", "page_offset": 0},
        "read-old": {"updated_at": "2026-11-13T01:00:00+00:00", "page_offset": 0},
    })
    response = supporter_client.get("/api/supporter/shelf?limit=3", headers=HEADERS)
    assert [item["id"] for item in response.json()["items"]] == ["read-new", "read-old", "never-new"]
    assert response.json()["totals"] == {"count": 3, "available": 4, "limit": 3}
    for value in (0, 51, -1, "bad"):
        assert supporter_client.get("/api/supporter/shelf?limit=" + str(value), headers=HEADERS).status_code == 422


def test_finished_or_missing_chapter_has_no_active_page(supporter_client, monkeypatch):
    chapters = add_series("finished")
    add_series("removed")
    db.set_progress("finished", chapters[-1]["id"], 1, db.PAGE_FINISHED_SENTINEL)
    db.mark_chapters_read("finished", [chapter["id"] for chapter in chapters])
    db.set_progress("removed", "old-chapter", 0, 8)
    metadata_stub(monkeypatch)
    response = supporter_client.get("/api/supporter/shelf", headers=HEADERS)
    for item in response.json()["items"]:
        assert item["pageIndex"] == item["pageOffset"] == 0
        assert item["lastChapter"] is None
        assert item["readingNow"] is False
    assert next(item for item in response.json()["items"] if item["id"] == "finished")["isNew"] is False


def test_reads_do_not_scan_open_zips_migrate_or_write_state(supporter_client, monkeypatch):
    chapters = add_series("legacy")
    db.set_progress("legacy", chapters[1]["id"], 1, 2)
    metadata_stub(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("supporter summary attempted library IO or a write")

    monkeypatch.setattr(services, "migrate_legacy_progress_if_needed", forbidden)
    monkeypatch.setattr(services, "start_background_scan", forbidden)
    monkeypatch.setattr(scan, "list_zip_image_names", forbidden)
    monkeypatch.setattr(db, "set_progress", forbidden)
    monkeypatch.setattr(db, "mark_chapters_read", forbidden)
    with sqlite3.connect(db.DB_PATH) as connection:
        before = list(connection.iterdump())
    for path in ("/api/supporter/shelf", "/api/supporter/health"):
        response = supporter_client.get(path, headers=HEADERS)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
    with sqlite3.connect(db.DB_PATH) as connection:
        assert list(connection.iterdump()) == before
    health = supporter_client.get("/api/supporter/health", headers=HEADERS).json()
    assert health["checks"] == {"tokenAccepted": True, "publicUrlConfigured": True}
    assert "/private/" not in str(health)
    assert "userId" not in str(health)


def test_empty_library_and_lan_public_origin_are_supported(supporter_client, monkeypatch):
    metadata_stub(monkeypatch)
    monkeypatch.setattr(services, "PUBLIC_BASE_URL", "http://192.168.1.26:8230/viewer/")
    response = supporter_client.get("/api/supporter/shelf", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["baseUrl"] == "http://192.168.1.26:8230/viewer"
    assert response.json()["items"] == []
