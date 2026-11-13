def test_unversioned_reader_scripts_and_styles_are_never_heuristically_cached(client):
    for path in ("/reader-position.js", "/reader-images.js", "/style.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        unchanged = client.get(path, headers={"If-None-Match": response.headers["etag"]})
        assert unchanged.status_code == 200
        assert unchanged.content == response.content


def test_reader_uses_new_cache_keys_for_clients_with_legacy_assets(client):
    response = client.get("/reader.html")
    assert 'reader-position.js?v=2' in response.text
    assert 'style.css?v=reader-position-2' in response.text
