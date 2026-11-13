import importlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import auth, db, profile_progress
from conftest import make_chapter_zip


def _series(client, library):
    for number in range(1, 4):
        make_chapter_zip(str(library / "naver" / "정밀 이어 읽기" / f"{number:03d}.zip"))
    assert client.post("/api/rescan").status_code == 200
    sid = client.get("/api/series").json()[0]["id"]
    chapters = client.get(f"/api/series/{sid}/chapters").json()["chapters"]
    return sid, chapters


def test_additive_migration_preserves_existing_admin_and_profile_data(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE progress(series_id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL,
                chapter_index INTEGER NOT NULL, page_index INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
            CREATE TABLE profile_progress(profile_id TEXT NOT NULL, series_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL, chapter_index INTEGER NOT NULL,
                page_index INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
                PRIMARY KEY(profile_id,series_id));
            CREATE TABLE read_chapters(series_id TEXT NOT NULL, chapter_id TEXT NOT NULL,
                PRIMARY KEY(series_id,chapter_id));
            CREATE TABLE profile_read_chapters(profile_id TEXT NOT NULL, series_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL, PRIMARY KEY(profile_id,series_id,chapter_id));
            CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO progress VALUES('series','admin-chapter',4,5,'2020-01-02T03:04:05');
            INSERT INTO profile_progress VALUES('profile','series','profile-chapter',2,3,'2021-02-03T04:05:06');
            INSERT INTO read_chapters VALUES('series','read-admin');
            INSERT INTO profile_read_chapters VALUES('profile','series','read-profile');
            INSERT INTO app_settings VALUES('existing-setting','keep');
        """)
    for _ in range(2):
        db.init_schema()
        profile_progress.init_schema()
    assert db.get_progress("series") == {"chapter_id": "admin-chapter", "chapter_index": 4, "page_index": 5}
    assert profile_progress.get_progress("profile", "series") == {
        "chapter_id": "profile-chapter", "chapter_index": 2, "page_index": 3,
    }
    assert db.get_progress_metadata("series") == {"updated_at": "2020-01-02T03:04:05", "page_offset": 0.0}
    assert db.get_read_chapter_ids("series") == {"read-admin"}
    assert profile_progress.get_read_chapter_ids("profile", "series") == {"read-profile"}
    assert db.get_setting("existing-setting") == "keep"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT updated_at,page_offset FROM profile_progress").fetchone() == (
            "2021-02-03T04:05:06", 0.0,
        )


def test_precise_position_roundtrips_without_marking_current_chapter_read(client, library):
    sid, chapters = _series(client, library)
    response = client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapters[1]["id"], "page_index": 1, "page_offset": 0.4375,
    })
    assert response.status_code == 200
    assert client.get(f"/api/series/{sid}/continue").json() == {
        "chapter_id": chapters[1]["id"], "page_index": 1, "page_offset": 0.4375,
    }
    assert db.get_progress_metadata(sid)["page_offset"] == 0.4375
    updated = client.get(f"/api/series/{sid}/chapters").json()["chapters"]
    assert updated[0]["read"] is True
    assert updated[1]["read"] is False
    assert updated[2]["read"] is False


@pytest.mark.parametrize("offset", [-0.1, 1.1, "0.5", True, None, [], {}])
def test_invalid_offset_is_rejected_without_changing_position(client, library, offset):
    sid, chapters = _series(client, library)
    body = {"chapter_id": chapters[0]["id"], "page_index": 1, "page_offset": 0.25}
    assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 200
    before = db.export_backup_data()
    body["page_offset"] = offset
    assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 422
    assert db.export_backup_data() == before


@pytest.mark.parametrize("offset", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_offset_is_rejected_without_a_server_error(client, library, offset):
    sid, chapters = _series(client, library)
    raw = '{"chapter_id":' + json.dumps(chapters[0]["id"]) + ',"page_index":1,"page_offset":' + offset + '}'
    assert client.put(f"/api/series/{sid}/progress", content=raw,
                      headers={"Content-Type": "application/json"}).status_code == 422
    assert db.get_progress(sid) is None


def test_legacy_updates_clear_offset_and_completed_chapters_do_not_carry_it_forward(client, library):
    sid, chapters = _series(client, library)
    db.set_progress(sid, chapters[0]["id"], 0, 1, page_offset=0.7)
    assert client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapters[0]["id"], "page_index": 1,
    }).status_code == 200
    assert client.get(f"/api/series/{sid}/continue").json() == {
        "chapter_id": chapters[0]["id"], "page_index": 1,
    }
    db.set_progress(sid, chapters[0]["id"], 0, 99, page_offset=0.7)
    assert client.get(f"/api/series/{sid}/continue").json() == {
        "chapter_id": chapters[1]["id"], "page_index": 0,
    }
    db.set_progress(sid, chapters[2]["id"], 2, 99, page_offset=0.7)
    assert client.get(f"/api/series/{sid}/continue").json() == {
        "chapter_id": chapters[2]["id"], "page_index": 2,
    }


def test_admin_and_profile_precision_remain_isolated_and_backup_compatible(library):
    profile_progress.init_schema()
    db.set_progress("series", "admin-chapter", 1, 2, page_offset=0.125)
    profile_progress.set_progress("a", "series", "profile-chapter", 3, 4, page_offset=0.875)
    profile_progress.set_progress("b", "series", "other-chapter", 5, 6, page_offset=0.5)
    admin = db.export_backup_data()
    profiles = profile_progress.export_all()
    db.import_backup_data(admin["progress"], admin["app_settings"], admin["read_chapters"])
    profile_progress.import_all(profiles["profile_progress"], profiles["profile_read_chapters"])
    assert db.get_progress("series")["page_offset"] == 0.125
    assert profile_progress.get_progress("a", "series")["page_offset"] == 0.875
    assert profile_progress.get_progress("b", "series")["page_offset"] == 0.5
    for row in admin["progress"]:
        row.pop("page_offset")
    for row in profiles["profile_progress"]:
        row.pop("page_offset")
    db.import_backup_data(admin["progress"], admin["app_settings"], admin["read_chapters"])
    profile_progress.import_all(profiles["profile_progress"], profiles["profile_read_chapters"])
    assert "page_offset" not in db.get_progress("series")
    assert "page_offset" not in profile_progress.get_progress("a", "series")


def test_api_backup_and_restore_preserves_exact_offset(client, library):
    sid, chapters = _series(client, library)
    assert client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapters[1]["id"], "page_index": 1, "page_offset": 0.625,
    }).status_code == 200
    backup = client.get("/api/backup").json()
    assert backup["progress"][0]["page_offset"] == 0.625
    assert client.post("/api/restore", json=backup).status_code == 200
    assert client.get(f"/api/series/{sid}/continue").json()["page_offset"] == 0.625


def test_profile_precision_uses_existing_authorization_and_does_not_modify_admin(library, monkeypatch):
    import app.main as main_module
    monkeypatch.setenv("PROFILES_ENABLED", "true")
    importlib.reload(main_module)
    try:
        with TestClient(main_module.app) as client:
            sid, chapters = _series_after_login(client, library)
            created = client.post("/api/admin/profiles", json={"name": "allowed"}).json()
            client.put(f"/api/admin/profiles/{created['id']}/allowed-series", json={"series_ids": [sid]})
            denied = client.post("/api/admin/profiles", json={"name": "denied"}).json()
            body = {"chapter_id": chapters[1]["id"], "page_index": 1, "page_offset": 0.75}
            denied_response = client.put(f"/p/{denied['token']}/api/series/{sid}/progress", json=body)
            assert denied_response.status_code == 403
            assert profile_progress.get_progress(denied["id"], sid) is None
            assert client.put(f"/p/{created['token']}/api/series/{sid}/progress", json=body).status_code == 200
            assert client.get(f"/p/{created['token']}/api/series/{sid}/continue").json()["page_offset"] == 0.75
            assert db.get_progress(sid) is None
            client.cookies.clear()
            assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 401
    finally:
        monkeypatch.delenv("PROFILES_ENABLED", raising=False)
        importlib.reload(main_module)


def _series_after_login(client, library):
    password = auth.ensure_admin_password_exists()
    assert client.post("/api/auth/login", json={"password": password}).status_code == 200
    return _series(client, library)
