import io
import os
import zipfile

from PIL import Image

from app import page_geometry
from conftest import make_chapter_zip


def test_headers_are_bounded_and_do_not_decode_the_full_image():
    raw = io.BytesIO()
    Image.new("RGB", (720, 900), "red").save(raw, format="JPEG")
    raw.seek(0)
    assert page_geometry._size(raw) == (720, 900)
    assert raw.tell() <= 1024
    invalid = io.BytesIO(b"x" * (page_geometry.HEADER_LIMIT * 2))
    assert page_geometry._size(invalid) is None
    assert invalid.tell() == page_geometry.HEADER_LIMIT


def test_cached_geometry_uses_natural_order_and_invalid_images_fall_back(tmp_path, monkeypatch):
    path = tmp_path / "chapter.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("2.jpg", b"not an image")
        raw = io.BytesIO()
        Image.new("RGB", (123, 456)).save(raw, format="PNG")
        archive.writestr("1.png", raw.getvalue())
    assert page_geometry.chapter_page_sizes(str(path)) == [{"width": 123, "height": 456}, None]
    monkeypatch.setattr(page_geometry, "_size", lambda _: (_ for _ in ()).throw(AssertionError("cache missed")))
    returned = page_geometry.chapter_page_sizes(str(path))
    returned[0]["height"] = 1
    assert page_geometry.chapter_page_sizes(str(path))[0]["height"] == 456


def test_replaced_zip_invalidates_geometry_and_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(page_geometry, "CACHE_SIZE", 2)
    page_geometry._cache.clear()
    path = tmp_path / "chapter.zip"
    make_chapter_zip(str(path), 1, width=200, height=300)
    assert page_geometry.chapter_page_sizes(str(path))[0]["height"] == 300
    replacement = tmp_path / "replacement.zip"
    make_chapter_zip(str(replacement), 1, width=200, height=400)
    os.replace(replacement, path)
    assert page_geometry.chapter_page_sizes(str(path))[0]["height"] == 400
    other = tmp_path / "other.zip"
    make_chapter_zip(str(other), 1)
    page_geometry.chapter_page_sizes(str(other))
    assert len(page_geometry._cache) == 2


def test_geometry_is_opt_in_and_keeps_library_files_unchanged(client, library):
    path = library / "naver" / "Sample" / "001.zip"
    make_chapter_zip(str(path), 2, width=640, height=1200)
    before = path.stat()
    client.post("/api/rescan")
    series = client.get("/api/series").json()[0]
    chapter = client.get("/api/series/" + series["id"] + "/chapters").json()["chapters"][0]
    base = "/api/chapters/" + chapter["id"] + "/pages"
    assert client.get(base).json() == {"page_count": 2}
    result = client.get(base + "?dimensions=1")
    assert result.status_code == 200
    assert result.json() == {"page_count": 2, "page_sizes": [{"width": 640, "height": 1200}] * 2}
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
