import pytest
from fastapi.testclient import TestClient

from app import db, main as main_module, profile_progress, profiles
from conftest import make_chapter_zip


def _series(client, library, *, chapter_count=1, page_count=2):
    for number in range(chapter_count):
        make_chapter_zip(str(library / "naver" / "Completion contract" / f"{number + 1:03d}.zip"),
                         page_count=page_count, width=720, height=5000)
    assert client.post("/api/rescan").status_code == 200
    item = client.get("/api/series").json()[0]
    return item["id"], client.get(f"/api/series/{item['id']}/chapters").json()["chapters"]


@pytest.mark.parametrize("completed", [None, False])
@pytest.mark.parametrize("page_count", [1, 2])
@pytest.mark.parametrize("offset", [0, 0.375])
def test_last_image_precision_does_not_imply_completion(client, library, completed, page_count, offset):
    sid, chapters = _series(client, library, page_count=page_count)
    chapter = chapters[-1]["id"]
    body = {"chapter_id": chapter, "page_index": page_count - 1, "page_offset": offset}
    if completed is not None:
        body["completed"] = completed
    assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 200
    stored = db.get_progress(sid)
    assert stored["page_index"] == page_count - 1
    assert stored.get("page_offset", 0) == offset
    resumed = client.get(f"/api/series/{sid}/continue").json()
    assert resumed["page_index"] == page_count - 1
    assert resumed.get("page_offset", 0) == offset
    assert not db.get_read_chapter_ids(sid)


def test_explicit_false_without_offset_keeps_last_image_unread(client, library):
    sid, chapters = _series(client, library)
    assert client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapters[-1]["id"], "page_index": 1, "completed": False,
    }).status_code == 200
    assert db.get_progress(sid)["page_index"] == 1
    assert not db.get_read_chapter_ids(sid)


def test_explicit_completion_marks_finished_and_clears_precision(client, library):
    sid, chapters = _series(client, library)
    chapter = chapters[-1]["id"]
    for body in [
        {"chapter_id": chapter, "page_index": 1, "page_offset": 0.375, "completed": False},
        {"chapter_id": chapter, "page_index": 1, "completed": True},
    ]:
        assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 200
    assert db.get_progress(sid)["page_index"] == db.PAGE_FINISHED_SENTINEL
    assert db.get_progress_metadata(sid)["page_offset"] == 0
    assert db.get_read_chapter_ids(sid) == {chapter}


def test_legacy_no_offset_request_keeps_previous_completion_contract(client, library):
    sid, chapters = _series(client, library)
    chapter = chapters[-1]["id"]
    assert client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapter, "page_index": 1,
    }).status_code == 200
    assert db.get_progress(sid)["page_index"] == db.PAGE_FINISHED_SENTINEL
    assert db.get_read_chapter_ids(sid) == {chapter}


@pytest.mark.parametrize("chapter_index,page_index", [(0, 1), (1, 0), (1, 99)])
def test_invalid_completion_cannot_write_any_progress_or_read_flags(client, library, chapter_index, page_index):
    sid, chapters = _series(client, library, chapter_count=2)
    before = db.export_backup_data()
    response = client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapters[chapter_index]["id"], "page_index": page_index, "completed": True,
    })
    assert response.status_code == 422
    assert db.export_backup_data() == before


@pytest.mark.parametrize("completed", [None, 0, 1, "true", "false", [], {}])
def test_completion_requires_an_explicit_boolean(client, library, completed):
    sid, chapters = _series(client, library)
    response = client.put(f"/api/series/{sid}/progress", json={
        "chapter_id": chapters[-1]["id"], "page_index": 1, "completed": completed,
    })
    assert response.status_code == 422
    assert db.get_progress(sid) is None
    assert not db.get_read_chapter_ids(sid)


@pytest.mark.parametrize("completed", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_completion_returns_422_without_writes(client, library, completed):
    sid, chapters = _series(client, library)
    response = client.put(
        f"/api/series/{sid}/progress",
        content=f'{{"chapter_id":"{chapters[-1]["id"]}","page_index":1,"completed":{completed}}}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert db.get_progress(sid) is None
    assert not db.get_read_chapter_ids(sid)


def test_profile_last_image_precision_and_completion_remain_separate(library, monkeypatch):
    profile_progress.init_schema()
    profiles.init_schema()
    with TestClient(main_module.app) as client:
        sid, chapters = _series(client, library)
        profile = profiles.create_profile("Reader")
        profiles.set_allowed_series(profile["id"], [sid])
        from app.routers import series as routes
        monkeypatch.setattr(routes.access_control, "get_profile", lambda request: profile)
        chapter = chapters[-1]["id"]
        body = {"chapter_id": chapter, "page_index": 1, "page_offset": 0.625, "completed": False}
        assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 200
        assert client.get(f"/api/series/{sid}/continue").json()["page_offset"] == 0.625
        assert not profile_progress.get_read_chapter_ids(profile["id"], sid)
        assert db.get_progress(sid) is None
        body["completed"] = True
        assert client.put(f"/api/series/{sid}/progress", json=body).status_code == 200
        assert profile_progress.get_progress(profile["id"], sid)["page_index"] == db.PAGE_FINISHED_SENTINEL
        assert profile_progress.get_read_chapter_ids(profile["id"], sid) == {chapter}
        assert db.get_progress(sid) is None
