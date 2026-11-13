import pytest

from app.embedding import frame_ancestors, parse_allowed_origins


def test_allowed_origins_are_canonical_exact_origins():
    assert parse_allowed_origins("http://192.168.1.26:8230, https://READER.example:443/ http://[::1]:8232") == (
        "http://192.168.1.26:8230", "https://reader.example", "http://[::1]:8232"
    )
    assert parse_allowed_origins("https://reader.example,https://reader.example/") == ("https://reader.example",)


@pytest.mark.parametrize("value", [
    "*", "https://*.example", "https:", "javascript:alert(1)", "https://user:password@example.com",
    "https://example.com/reader", "https://example.com?token=secret", "https://example.com#reader",
    "http://example.com:0", "http://example.com:65536", "https://example.com;frame-ancestors",
    "https://good.example https://bad.example/path", "https://example%2ecom", "https://example..com",
])
def test_invalid_origin_configuration_fails_closed(value):
    with pytest.raises(ValueError, match="exact HTTP"):
        parse_allowed_origins(value)


def test_default_policy_limits_framing_to_same_origin(client):
    import app.main as main_module

    assert main_module.EMBED_ALLOWED_ORIGINS == ()
    response = client.get("/reader.html")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert client.get("/api/embed/config").json() == {
        "enabled": False, "allowed_origins": [], "protocol": "webtoon-reader", "version": 1
    }


def test_configured_manager_origin_is_the_only_cross_origin_frame_allowance(client, monkeypatch):
    import app.main as main_module

    origins = ("http://192.168.1.26:8230", "http://192.168.1.26:8232")
    monkeypatch.setattr(main_module, "EMBED_ALLOWED_ORIGINS", origins)
    response = client.get("/reader.html?embed=1&parent_origin=http%3A%2F%2Fevil.example")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == frame_ancestors(origins)
    assert "evil.example" not in response.headers["content-security-policy"]
    assert "x-frame-options" not in response.headers
    assert client.get("/api/embed/config").json()["allowed_origins"] == list(origins)
    assert client.get("/embed.js").status_code == 200


def test_embed_mode_does_not_bypass_admin_login(client, monkeypatch):
    import app.main as main_module
    from app import auth

    auth.init_schema()
    monkeypatch.setattr(main_module, "PROFILES_ENABLED", True)
    monkeypatch.setattr(main_module, "EMBED_ALLOWED_ORIGINS", ("http://manager.example",))
    response = client.get("/reader.html?embed=1&parent_origin=http%3A%2F%2Fmanager.example", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/login.html"
    assert response.headers["content-security-policy"] == "frame-ancestors 'self' http://manager.example"
    assert client.get("/api/series?embed=1").status_code == 401
    assert client.get("/api/embed/config").status_code == 200


def test_profile_reader_and_embed_asset_keep_profile_authorization(client, monkeypatch):
    import app.main as main_module
    from app import profile_devices, profiles

    profiles.init_schema()
    profile_devices.init_schema()
    created = profiles.create_profile("읽기 프로필")
    monkeypatch.setattr(main_module, "PROFILES_ENABLED", True)
    monkeypatch.setattr(main_module, "EMBED_ALLOWED_ORIGINS", ("http://manager.example",))
    prefix = f"/p/{created['token']}"
    assert client.get(prefix + "/reader.html?embed=1").status_code == 200
    assert client.get(prefix + "/embed.js").status_code == 200
    assert client.get("/p/invalid-profile/reader.html?embed=1").status_code == 404
