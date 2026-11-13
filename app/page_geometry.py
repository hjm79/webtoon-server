"""Bounded image-header reads for stable lazy-loading placeholders."""

import os
import threading
import zipfile
from collections import OrderedDict

from PIL import Image, ImageFile, UnidentifiedImageError

from . import scan

HEADER_LIMIT = 64 * 1024
CACHE_SIZE = 128
_cache = OrderedDict()
_lock = threading.Lock()


def _size(handle):
    parser = ImageFile.Parser()
    try:
        remaining = HEADER_LIMIT
        while remaining:
            chunk = handle.read(min(1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            parser.feed(chunk)
            if parser.image is not None:
                width, height = parser.image.size
                if 0 < width <= 200_000 and 0 < height <= 200_000:
                    return width, height
                break
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    return None


def chapter_page_sizes(zip_path: str) -> list[dict | None]:
    stat = os.stat(zip_path)
    key = (zip_path, stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
    if cached is None:
        sizes = []
        with zipfile.ZipFile(zip_path) as archive:
            for name in scan.list_zip_image_names(zip_path, archive):
                try:
                    with archive.open(name) as handle:
                        sizes.append(_size(handle))
                except (OSError, ValueError, zipfile.BadZipFile):
                    sizes.append(None)
        cached = tuple(sizes)
        with _lock:
            _cache[key] = cached
            _cache.move_to_end(key)
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
    return [{"width": size[0], "height": size[1]} if size else None for size in cached]
