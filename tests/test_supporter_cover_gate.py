import pytest
from fastapi.testclient import TestClient

from app import base_path, catalog, covers, db, profile_devices, profiles, services
from app import main as main_module


TOKEN = "test-only-supporter-cover-token"
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def cover_gate_client(library, monkeypatch):
    monkeypatch.setattr(main_module, "PROFILES_ENABLED", True)
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    monkeypatch.setattr(services, "PUBLIC_BASE_URL", "http://192.168.1.26:8230/viewer")
    monkeypatch.setenv("SUPPORTER_API_TOKEN", TOKEN)
    monkeypatch.setenv("INTEGRATION_TOKEN", "scan-only-token")
    monkeypatch.setattr(services, "is_rescan_enabled", lambda: False)

    async def skip_initial_scan():
        pass

    monkeypatch.setattr(services, "initial_scan", skip_initial_scan)
    monkeypatch.setattr(covers, "_cache", {"example": (1, b"private-cover", "image/jpeg")})
    with TestClient(main_module.app) as client:
        for sid, excluded in (("example", False), ("hidden", True)):
            catalog.add_series({
                "id": sid, "title": sid, "platform": "naver", "chapters": [],
                "latest_mtime": 1, "cover_mtime": 1, "excluded": excluded,
            }, {})
        yield client


def test_shelf_cover_is_fetchable_with_same_bearer_through_real_gate(cover_gate_client):
    before = db.export_backup_data()
    shelf = cover_gate_client.get("/viewer/api/supporter/shelf", headers=HEADERS)
    assert shelf.status_code == 200
    url = shelf.json()["items"][0]["coverUrl"]
    assert url.startswith("http://192.168.1.26:8230/viewer/api/supporter/covers/example?v=")
    response = cover_gate_client.get(url, headers=HEADERS)
    assert response.status_code == 200
    assert response.content == b"private-cover"
    assert response.headers["cache-control"] == "no-store"
    assert db.export_backup_data() == before
    assert cover_gate_client.get("/viewer/api/series/example/cover", headers=HEADERS).status_code == 401


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer scan-only-token"},
])
def test_cover_bearer_cannot_be_replaced_with_admin_or_scan_auth(cover_gate_client, headers):
    response = cover_gate_client.get("/viewer/api/supporter/covers/example", headers=headers)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", [
    "/api/supporter/covers", "/api/supporter/covers/example/extra",
    "/api/supporter/covers/example/", "/api/supporter/covers/example.invalid",
    "/api/supporter/covers/" + "x" * 129,
])
def test_cover_gate_exception_only_matches_concrete_valid_id(cover_gate_client, path):
    assert cover_gate_client.get("/viewer" + path, headers=HEADERS).status_code == 401


def test_shared_cover_is_hidden_before_device_registration(cover_gate_client):
    profile = profiles.create_profile("shared")
    response = cover_gate_client.get(
        f"/viewer/p/{profile['token']}/api/supporter/covers/example", headers=HEADERS,
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert profile_devices.count_devices(profile["id"]) == 0


@pytest.mark.parametrize("sid", ["missing", "hidden"])
def test_private_cover_cannot_expose_unknown_or_excluded_series(cover_gate_client, sid):
    response = cover_gate_client.get("/viewer/api/supporter/covers/" + sid, headers=HEADERS)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
