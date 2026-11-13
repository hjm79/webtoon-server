import os
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import pytest

from app import catalog, db, profile_progress, profiles, scan, services
from app.routers import series as routes
from conftest import make_chapter_zip


def _series(client, library, title="Metadata", summary=None):
    folder = library / "naver" / title
    for number in (1, 2):
        make_chapter_zip(str(folder / f"{number:03d} {number}화.zip"))
    if summary is not None:
        (folder / "info.xml").write_text(
            f"<ComicInfo><Summary>{escape(summary)}</Summary><Year>1999</Year></ComicInfo>",
            encoding="utf-8",
        )
    assert client.post("/api/rescan").status_code == 200
    item = next(row for row in client.get("/api/series").json() if row["title"] == title)
    chapters = client.get(f"/api/series/{item['id']}/chapters").json()["chapters"]
    return item["id"], chapters, folder


def test_library_card_uses_cached_summary_and_latest_chapter_file_date(client, library, monkeypatch):
    sid, chapters, folder = _series(client, library, summary="<p>작품 <b>소개</b>&nbsp;입니다.</p><p>둘째 줄</p>")
    first_time = datetime(2026, 11, 13, 12, tzinfo=timezone.utc).timestamp()
    last_time = datetime(2026, 11, 12, 16, tzinfo=timezone.utc).timestamp()
    os.utime(folder / "001 1화.zip", (first_time, first_time))
    os.utime(folder / "002 2화.zip", (last_time, last_time))
    assert client.post("/api/rescan").status_code == 200
    before = db.export_backup_data()

    def unexpected_io(*args, **kwargs):
        raise AssertionError("library card request must reuse scanned metadata")

    monkeypatch.setattr(scan, "_parse_series_info", unexpected_io)
    monkeypatch.setattr(scan, "list_zip_image_names", unexpected_io)
    monkeypatch.setattr(scan, "scan_single_series", unexpected_io)
    monkeypatch.setattr(services, "run_platform_io", unexpected_io)
    monkeypatch.setattr(scan.os.path, "getmtime", unexpected_io)
    item = client.get("/api/series").json()[0]
    assert item["summary"] == "작품 소개 입니다. 둘째 줄"
    assert item["latest_update"] == first_time
    assert item["latest_chapter"] == {
        "id": chapters[-1]["id"], "label": chapters[-1]["label"],
        "date": "2026-11-12T16:00:00+00:00", "date_source": "file_modified",
    }
    assert item["recently_read_chapter"] is None
    assert db.export_backup_data() == before
    assert catalog.get_series(sid)["chapters"][-1]["mtime"] == last_time


def test_summary_is_plain_bounded_and_does_not_change_original_info(client, library):
    original = "<style>hidden</style><script>alert('hidden')</script><p>소개<br>다음 줄 &amp; 설명</p>" + "가" * 2000
    sid, _, _ = _series(client, library, summary=original)
    item = client.get("/api/series").json()[0]
    assert item["summary"].startswith("소개 다음 줄 & 설명")
    assert len(item["summary"]) == 1000
    assert "hidden" not in item["summary"] and "<" not in item["summary"]
    assert client.get(f"/api/series/{sid}/info").json()["summary"] == original


def test_missing_description_and_unread_progress_have_explicit_empty_values(client, library):
    _, chapters, _ = _series(client, library)
    item = client.get("/api/series").json()[0]
    assert item["summary"] == ""
    assert item["recently_read_chapter"] is None
    assert item["latest_chapter"]["id"] == chapters[-1]["id"]


@pytest.mark.parametrize("page_index", [0, db.PAGE_FINISHED_SENTINEL])
def test_recently_read_uses_saved_chapter_even_when_completed(client, library, page_index):
    sid, chapters, _ = _series(client, library)
    db.set_progress(sid, chapters[-1]["id"], 1, page_index)
    db.mark_chapters_read(sid, [chapters[0]["id"]])
    if page_index == db.PAGE_FINISHED_SENTINEL:
        db.mark_chapters_read(sid, [chapters[-1]["id"]])
    before = db.export_backup_data()
    item = client.get("/api/series").json()[0]
    assert item["recently_read_chapter"] == {"id": chapters[-1]["id"], "label": chapters[-1]["label"]}
    assert item["reading_now"] is (page_index != db.PAGE_FINISHED_SENTINEL)
    assert db.export_backup_data() == before


def test_invalid_saved_chapter_does_not_invent_a_recently_read_chapter(client, library):
    sid, chapters, _ = _series(client, library)
    db.set_progress(sid, "deleted-chapter", 99, 0)
    db.mark_chapters_read(sid, [chapters[-1]["id"]])
    assert client.get("/api/series").json()[0]["recently_read_chapter"] is None


def test_recently_read_progress_is_profile_isolated_and_series_filtered(client, library, monkeypatch):
    sid, chapters, _ = _series(client, library)
    _series(client, library, title="Not shared", summary="Private series")
    profiles.init_schema()
    profile_progress.init_schema()
    reader = profiles.create_profile("Reader")
    profiles.set_allowed_series(reader["id"], [sid])
    db.set_progress(sid, chapters[-1]["id"], 1, db.PAGE_FINISHED_SENTINEL)
    db.mark_chapters_read(sid, [chapter["id"] for chapter in chapters])
    profile_progress.set_progress(reader["id"], sid, chapters[0]["id"], 0, 0)
    before = db.export_backup_data()
    monkeypatch.setattr(routes.access_control, "get_profile", lambda request: reader)
    items = client.get("/api/series").json()
    assert [item["id"] for item in items] == [sid]
    assert items[0]["recently_read_chapter"] == {"id": chapters[0]["id"], "label": chapters[0]["label"]}
    assert "list" not in items[0]
    monkeypatch.setattr(routes.access_control, "get_profile", lambda request: None)
    admin = next(item for item in client.get("/api/series").json() if item["id"] == sid)
    assert admin["recently_read_chapter"]["id"] == chapters[-1]["id"]
    assert db.export_backup_data() == before


@pytest.mark.parametrize("mtime", [None, 0, -1, "bad", float("nan"), float("inf"), 1e300])
def test_missing_or_invalid_cached_file_date_is_unknown(client, library, mtime):
    sid, _, _ = _series(client, library)
    catalog.get_series(sid)["chapters"][-1]["mtime"] = mtime
    latest = client.get("/api/series").json()[0]["latest_chapter"]
    assert latest["date"] is None
    assert latest["date_source"] == "unknown"
