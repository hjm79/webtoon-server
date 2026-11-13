from fastapi.testclient import TestClient

from app import base_path, db, profile_devices, profiles, services
from app import main as main_module
from conftest import make_chapter_zip


def test_dedicated_token_works_through_real_gate_without_expanding_admin_access(library, monkeypatch):
    monkeypatch.setattr(main_module, "PROFILES_ENABLED", True)
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    monkeypatch.setattr(services, "PUBLIC_BASE_URL", "http://192.168.1.26:8230/viewer")
    monkeypatch.setenv("SUPPORTER_API_TOKEN", "test-only-dedicated-token")
    headers = {"Authorization": "Bearer test-only-dedicated-token"}
    make_chapter_zip(str(library / "naver" / "Example" / "001.zip"))
    with TestClient(main_module.app) as client:
        assert client.get("/viewer/api/supporter/health").status_code == 401
        response = client.get("/viewer/api/supporter/health", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/viewer/api/supporter/health/extra", headers=headers).status_code == 401
        assert client.get("/viewer/api/backup", headers=headers).status_code == 401
        assert client.get("/viewer/api/series", headers=headers).status_code == 401


def test_shared_profile_cannot_call_supporter_or_register_a_device(library, monkeypatch):
    monkeypatch.setattr(main_module, "PROFILES_ENABLED", True)
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    monkeypatch.setenv("SUPPORTER_API_TOKEN", "test-only-dedicated-token")
    with TestClient(main_module.app) as client:
        profile = profiles.create_profile("shared")
        for endpoint in ("shelf", "health"):
            response = client.get(
                f"/viewer/p/{profile['token']}/api/supporter/{endpoint}",
                headers={"Authorization": "Bearer test-only-dedicated-token"},
            )
            assert response.status_code == 404
            assert response.headers["cache-control"] == "no-store"
        assert profile_devices.count_devices(profile["id"]) == 0


def test_supporter_real_metadata_keeps_exact_resume_position(client, library, monkeypatch):
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    monkeypatch.setattr(services, "PUBLIC_BASE_URL", "http://192.168.1.26:8230/viewer")
    monkeypatch.setenv("SUPPORTER_API_TOKEN", "test-only-dedicated-token")
    make_chapter_zip(str(library / "naver" / "Example" / "001.zip"), page_count=5)
    client.post("/viewer/api/rescan")
    item = client.get("/viewer/api/series").json()[0]
    chapter = client.get(f"/viewer/api/series/{item['id']}/chapters").json()["chapters"][0]
    assert client.put(f"/viewer/api/series/{item['id']}/progress", json={
        "chapter_id": chapter["id"], "page_index": 2, "page_offset": 0.45,
    }).status_code == 200
    before = db.export_backup_data()
    response = client.get("/viewer/api/supporter/shelf", headers={"Authorization": "Bearer test-only-dedicated-token"})
    assert response.status_code == 200
    row = response.json()["items"][0]
    assert row["id"] == item["id"]
    assert row["pageIndex"] == 2 and row["pageOffset"] == 0.45
    assert row["lastReadAt"]
    assert row["href"] == f"http://192.168.1.26:8230/viewer/reader.html?series={item['id']}"
    assert db.export_backup_data() == before
