import importlib
import re

import pytest
from fastapi.testclient import TestClient

from app import auth, base_path, db, profile_devices, profiles
from conftest import make_chapter_zip


@pytest.mark.parametrize("value", ["viewer", "//viewer", "/viewer?x=1", "/viewer#x", "/a/../b", "/a/./b", "/a\\b", "/a%2fb", "/a b"])
def test_invalid_base_path_fails_closed(value):
    with pytest.raises(ValueError):
        base_path.parse_base_path(value)


def test_prefix_normalization_and_root_compatibility():
    assert base_path.parse_base_path("") == ""
    assert base_path.parse_base_path("/") == ""
    assert base_path.parse_base_path(" /viewer/ ") == "/viewer"


def test_prefixed_html_assets_and_manifest_do_not_escape_to_manager_root(client, monkeypatch):
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    for page in ["", "reader.html", "login.html", "device-approval.html"]:
        response = client.get("/viewer/" + page)
        assert response.status_code == 200
        assert '__WEBTOON_BASE_PATH__' not in response.text
        assert 'content="/viewer"' in response.text
        assert 'src="/viewer/base-path.js"' in response.text
        assert 'href="/viewer/style.css"' in response.text
        assert response.headers["cache-control"] == "no-store"
        for url in re.findall(r'(?:href|src)="(/[^"?]+)', response.text):
            assert url.startswith("/viewer/"), url
    assert client.get("/viewer/base-path.js").status_code == 200
    assert client.get("/viewer/style.css").status_code == 200
    manifest = client.get("/viewer/manifest.json").json()
    assert manifest["start_url"] == manifest["scope"] == "/viewer/"
    assert all(icon["src"].startswith("/viewer/icons/") for icon in manifest["icons"])
    # The manager strips the prefix before forwarding; internal root routes remain valid.
    assert 'content="/viewer"' in client.get("/reader.html").text
    assert client.get("/api/series").status_code == 200
    assert client.get("/viewerevil/api/series").status_code == 404


def test_prefixed_cover_pages_and_saved_continuation_keep_the_same_records(client, library, monkeypatch):
    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    make_chapter_zip(str(library / "naver" / "경로 검증" / "001.zip"), page_count=5)
    client.post("/viewer/api/rescan")
    item = client.get("/viewer/api/series").json()[0]
    assert item["cover_url"].startswith("/viewer/api/series/")
    assert client.get(item["cover_url"]).status_code == 200
    chapter = client.get(f"/viewer/api/series/{item['id']}/chapters").json()["chapters"][0]
    before = db.get_progress(item["id"])
    assert before is None
    assert client.put(f"/viewer/api/series/{item['id']}/progress", json={"chapter_id": chapter["id"], "page_index": 2}).status_code == 200
    expected = {"chapter_id": chapter["id"], "page_index": 2}
    assert client.get(f"/viewer/api/series/{item['id']}/continue").json() == expected
    assert client.get(f"/api/series/{item['id']}/continue").json() == expected
    assert client.get(f"/viewer/api/chapters/{chapter['id']}/pages/2").status_code == 200


@pytest.fixture
def prefixed_enabled_app(library, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(base_path, "BASE_PATH", "/viewer")
    monkeypatch.setenv("PROFILES_ENABLED", "true")
    importlib.reload(main_module)
    yield main_module.app
    monkeypatch.delenv("PROFILES_ENABLED", raising=False)
    importlib.reload(main_module)


def test_prefixed_auth_redirect_assets_cookie_and_existing_device(prefixed_enabled_app):
    with TestClient(prefixed_enabled_app) as client:
        response = client.get("/viewer/reader.html", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/viewer/login.html"
        assert client.get("/viewer/api/series").status_code == 401
        assert client.get("/viewer/base-path.js").status_code == 200
        password = auth.ensure_admin_password_exists()
        response = client.post("/viewer/api/auth/login", json={"password": password})
        assert response.status_code == 200
        assert "Path=/viewer/" in response.headers["set-cookie"]
        assert client.get("/viewer/api/series").status_code == 200
        old_device = auth.create_remembered_device(label="기존 기기")
        client.cookies.clear()
        client.cookies.set("webtoon_device", old_device, path="/")
        assert client.get("/viewer/api/series").status_code == 200


def test_prefixed_login_replaces_a_revoked_legacy_root_cookie(prefixed_enabled_app):
    with TestClient(prefixed_enabled_app) as client:
        password = auth.ensure_admin_password_exists()
        revoked = auth.create_remembered_device(label="기존 루트 기기")
        auth.remove_remembered_device(revoked)
        client.cookies.set("webtoon_device", revoked, path="/", domain="testserver.local")
        assert client.get("/viewer/api/series").status_code == 401
        response = client.post("/viewer/api/auth/login", json={"password": password})
        assert response.status_code == 200
        cookie_headers = response.headers.get_list("set-cookie")
        assert any("Path=/;" in value and "Max-Age=0" in value for value in cookie_headers)
        assert any("Path=/viewer/;" in value for value in cookie_headers)
        assert not any(cookie.name == "webtoon_device" and cookie.path == "/" for cookie in client.cookies.jar)
        assert client.get("/viewer/api/series").status_code == 200


@pytest.mark.parametrize("scoped_valid, expected_status", [(True, 200), (False, 401)])
def test_prefixed_admin_cookie_keeps_the_scoped_device_without_root_fallback(prefixed_enabled_app, scoped_valid, expected_status):
    with TestClient(prefixed_enabled_app) as client:
        valid = auth.create_remembered_device(label="승인된 기기")
        scoped, root = (valid, "revoked-root") if scoped_valid else ("unapproved-scoped", valid)
        client.cookies.set("webtoon_device", root, path="/", domain="testserver.local")
        client.cookies.set("webtoon_device", scoped, path="/viewer/", domain="testserver.local")
        response = client.get("/viewer/api/series")
        assert response.status_code == expected_status
        assert "set-cookie" not in response.headers


@pytest.mark.parametrize("scoped, root, expected_status", [
    ("approved-device", "revoked-root", 200),
    ("unapproved-scoped", "approved-device", 403),
    (None, "approved-device", 200),
])
def test_prefixed_profile_cookie_preserves_the_selected_device_and_limit(prefixed_enabled_app, scoped, root, expected_status):
    with TestClient(prefixed_enabled_app) as client:
        profile = profiles.create_profile("기존 승인 기기")
        profile_devices.register_device(profile["id"], "approved-device", "기존 기기")
        profile_devices.register_device(profile["id"], "second-device", "두 번째 기기")
        client.cookies.set("webtoon_profile_device", root, path="/", domain="testserver.local")
        if scoped is not None:
            client.cookies.set("webtoon_profile_device", scoped, path="/viewer/", domain="testserver.local")
        response = client.get(f"/viewer/p/{profile['token']}/api/series")
        assert response.status_code == expected_status
        assert profile_devices.count_devices(profile["id"]) == 2
        assert profile_devices.is_device_registered(profile["id"], "approved-device")
        if expected_status == 403:
            assert "set-cookie" not in response.headers
            assert response.json()["status"] == "needs_request"
        else:
            assert next(cookie.value for cookie in client.cookies.jar if cookie.path == "/viewer/" and cookie.name == "webtoon_profile_device") == "approved-device"


def test_prefixed_profile_cookie_cannot_fall_back_to_a_different_profiles_device(prefixed_enabled_app):
    with TestClient(prefixed_enabled_app) as client:
        first = profiles.create_profile("첫 번째 프로필")
        second = profiles.create_profile("두 번째 프로필")
        for profile, selected in [(first, "first-approved"), (second, "second-approved")]:
            profile_devices.register_device(profile["id"], selected, "승인된 기기")
            profile_devices.register_device(profile["id"], "other-" + selected, "다른 기기")
        client.cookies.set("webtoon_profile_device", "second-approved", path="/", domain="testserver.local")
        client.cookies.set("webtoon_profile_device", "first-approved", path="/viewer/", domain="testserver.local")
        assert client.get(f"/viewer/p/{first['token']}/api/series").status_code == 200
        assert client.get(f"/viewer/p/{second['token']}/api/series").status_code == 403
        assert profile_devices.count_devices(first["id"]) == profile_devices.count_devices(second["id"]) == 2
        assert not profile_devices.is_device_registered(second["id"], "first-approved")


def test_prefixed_profile_assets_manifest_and_device_gate_preserve_authorization(prefixed_enabled_app):
    with TestClient(prefixed_enabled_app) as admin:
        created = profiles.create_profile("공유 경로")
        prefix = f"/viewer/p/{created['token']}"
        first = TestClient(prefixed_enabled_app)
        response = first.get(prefix + "/")
        assert response.status_code == 200
        assert 'content="/viewer"' in response.text
        assert "Path=/viewer/" in response.headers["set-cookie"]
        assert first.get(prefix + "/reader.html").status_code == 200
        assert first.get(prefix + "/embed.js").status_code == 200
        manifest = first.get(prefix + "/manifest.json").json()
        assert manifest["start_url"] == manifest["scope"] == prefix + "/"
        assert first.get(prefix + "/api/backup").status_code == 404
        second = TestClient(prefixed_enabled_app)
        assert second.get(prefix + "/api/series").status_code == 200
        third = TestClient(prefixed_enabled_app)
        blocked = third.get(prefix + "/reader.html")
        assert "승인" in blocked.text and '__WEBTOON_BASE_PATH__' not in blocked.text
        assert 'src="/viewer/base-path.js"' in blocked.text
        assert third.get(prefix + "/api/series").status_code == 403
        assert third.get(prefix + "/api/device/status").status_code == 200
        assert third.get("/viewer/p/invalid/reader.html").status_code == 404
