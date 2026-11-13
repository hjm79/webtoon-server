import pytest

from conftest import make_chapter_zip


@pytest.mark.parametrize("endpoint", ["latest", "read-state"])
def test_lookup_does_not_pick_an_arbitrary_same_title_across_platforms(client, library, endpoint):
    for platform in ("naver", "kakao"):
        make_chapter_zip(str(library / platform / "동명 웹툰" / "001.zip"))
    client.post("/api/rescan")

    response = client.get(f"/api/lookup/{endpoint}", params={"series": "동명 웹툰"})
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "ambiguous_series", "platforms": ["kakao", "naver"]}

    expected = {row["platform"]: row["id"] for row in client.get("/api/series").json()}
    for platform in ("naver", "kakao"):
        exact = client.get(f"/api/lookup/{endpoint}", params={"series": "동명 웹툰", "platform": platform})
        assert exact.status_code == 200
        assert exact.json()["series_id"] == expected[platform]


@pytest.mark.parametrize("endpoint", ["latest", "read-state"])
def test_lookup_same_platform_duplicates_are_also_ambiguous(client, library, endpoint):
    for group in ("첫 보관 폴더", "다른 보관 폴더"):
        make_chapter_zip(str(library / "archive" / group / "동명 웹툰" / "001.zip"))
    client.post("/api/rescan")

    response = client.get(f"/api/lookup/{endpoint}", params={"series": "동명 웹툰", "platform": "archive"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "ambiguous_series"


def test_lookup_unique_custom_archive_platform_remains_available_without_platform(client, library):
    make_chapter_zip(str(library / "기타 보관" / "보관된 웹툰" / "001.zip"))
    client.post("/api/rescan")

    response = client.get("/api/lookup/latest", params={"series": "보관된 웹툰"})
    assert response.status_code == 200
    assert response.json()["series_id"] == client.get("/api/series").json()[0]["id"]
