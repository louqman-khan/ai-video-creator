import httpx
import pytest
import respx

from app.config import Settings
from app.models import MediaAsset
from app.providers.media_search import CompositeSearch, build_sources
from app.providers.media_search.openverse import OpenverseSearch
from app.providers.media_search.pexels import PexelsSearch
from app.providers.media_search.pixabay import PixabaySearch
from app.providers.media_search.wikimedia import WikimediaSearch


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_pexels_skipped_without_key_and_pixabay_used():
    names = [s.name for s in build_sources(settings(pixabay_api_key="k"))]
    assert names == ["pixabay", "openverse", "wikimedia"]


def test_pexels_enabled_with_key():
    names = [s.name for s in build_sources(settings(pixabay_api_key="k", pexels_api_key="p"))]
    assert "pexels" in names


def test_pixabay_skipped_without_key_keeps_keyless_sources():
    names = [s.name for s in build_sources(settings())]
    assert names == ["openverse", "wikimedia"]


@respx.mock
def test_pixabay_video_and_image_license():
    respx.get("https://pixabay.com/api/videos/").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 7,
                        "pageURL": "https://pixabay.com/videos/x-7/",
                        "tags": "sea, wave",
                        "duration": 12,
                        "user": "bob",
                        "videos": {
                            "large": {"url": "https://cdn/l.mp4", "width": 1920, "height": 1080},
                            "tiny": {"url": "https://cdn/t.mp4", "width": 640, "height": 360},
                        },
                    }
                ]
            },
        )
    )
    respx.get("https://pixabay.com/api/").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 9,
                        "pageURL": "https://pixabay.com/photos/y-9/",
                        "tags": "city",
                        "user": "amy",
                        "user_id": 5,
                        "largeImageURL": "https://cdn/i.jpg",
                        "imageWidth": 4000,
                        "imageHeight": 3000,
                    }
                ]
            },
        )
    )
    src = PixabaySearch("key")
    [v] = src.search("sea", "video")
    assert (v.id, v.url, v.duration, v.kind) == ("pixabay:7", "https://cdn/l.mp4", 12.0, "video")
    assert v.license == "Pixabay Content License" and "bob" in v.attribution
    [i] = src.search("city", "image")
    assert (i.width, i.height) == (1280, 960)  # capped to what largeImageURL really is
    assert i.license_url


@respx.mock
def test_openverse_filters_and_license_label():
    respx.get("https://api.openverse.org/v1/images/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "a", "url": "https://x/a.jpg", "license": "by-sa", "license_version": "4.0",
                     "license_url": "https://cc/by-sa", "creator": "Zed", "title": "T",
                     "attribution": "\"T\" by Zed is licensed under CC BY-SA 4.0",
                     "foreign_landing_url": "https://x/page", "width": 3000, "height": 2000},
                    {"id": "b", "url": "https://x/b.tiff", "license": "cc0", "license_version": "1.0"},
                    {"id": "c", "url": "https://x/c.png", "license": "cc0", "license_version": "1.0"},
                ]
            },
        )
    )
    res = OpenverseSearch().search("tree", "image")
    assert [a.id for a in res] == ["openverse:a", "openverse:c"]  # .tiff dropped
    assert res[0].license == "CC BY-SA 4.0" and res[0].attribution_required
    assert res[1].license == "CC0 1.0" and not res[1].attribution_required
    assert OpenverseSearch().search("tree", "video") == []


@respx.mock
def test_wikimedia_parses_license_and_drops_unknown():
    def page(pid, idx, lic):
        meta = {"Artist": {"value": '<a href="u">Jane &amp; Co</a>'}, "AttributionRequired": {"value": "true"}}
        if lic:
            meta["LicenseShortName"] = {"value": lic}
            meta["LicenseUrl"] = {"value": "https://cc/by"}
        return {
            "pageid": pid, "index": idx, "title": f"File:P{pid}.jpg",
            "imageinfo": [{"url": "https://u/o.jpg", "thumburl": "https://u/t.jpg", "mime": "image/jpeg",
                           "width": 4000, "height": 3000, "thumbwidth": 1920, "thumbheight": 1440,
                           "descriptionurl": f"https://commons/File:P{pid}.jpg", "extmetadata": meta}],
        }

    respx.get("https://commons.wikimedia.org/w/api.php").mock(
        return_value=httpx.Response(
            200, json={"query": {"pages": {"2": page(2, 2, "CC BY 4.0"), "1": page(1, 1, None)}}}
        )
    )
    res = WikimediaSearch().search("bridge", "image")
    assert len(res) == 1  # page without license dropped
    a = res[0]
    assert a.license == "CC BY 4.0" and a.author == "Jane & Co" and a.url == "https://u/t.jpg"
    assert "Wikimedia Commons" in a.attribution


@respx.mock
def test_pexels_video():
    respx.get("https://api.pexels.com/videos/search").mock(
        return_value=httpx.Response(
            200,
            json={"videos": [{"id": 1, "url": "https://pexels/v/1", "duration": 9,
                              "user": {"name": "Kim", "url": "https://pexels/kim"},
                              "video_files": [{"link": "https://cdn/v.mp4", "file_type": "video/mp4",
                                               "width": 1920, "height": 1080}]}]},
        )
    )
    [v] = PexelsSearch("k").search("x", "video")
    assert v.license == "Pexels License" and v.author == "Kim"


class Boom:
    name = "boom"
    kinds = frozenset({"image"})

    def search(self, *a, **k):
        raise RuntimeError("down")


class Fixed:
    kinds = frozenset({"image"})

    def __init__(self, name, n):
        self.name, self.n = name, n

    def search(self, query, kind, **k):
        return [MediaAsset(id=f"{self.name}:{i}", source=self.name, kind="image", url="u", license="L")
                for i in range(self.n)]


def test_composite_interleaves_survives_failure_and_skips_cache_on_error(tmp_path):
    comp = CompositeSearch([Fixed("a", 2), Boom(), Fixed("b", 2)], cache_dir=tmp_path)
    assert [x.id for x in comp.search("q", "image")] == ["a:0", "b:0", "a:1", "b:1"]
    assert not list(tmp_path.glob("search_*.json"))  # partial result must not be cached
    ok = CompositeSearch([Fixed("a", 1)], cache_dir=tmp_path)
    ok.search("q", "image")
    assert len(list(tmp_path.glob("search_*.json"))) == 1


def test_asset_requires_license():
    with pytest.raises(Exception):
        MediaAsset(id="x:1", source="x", kind="image", url="u")


# ---- downloads are checked before they are accepted

@respx.mock
def test_cache_rejects_downloads_that_are_not_media_and_keeps_real_ones(tmp_path):
    from app.media.cache import MediaCache

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    respx.get("https://cdn.example/photo.jpg").mock(return_value=httpx.Response(200, content=jpeg))
    respx.get("https://cdn.example/page.jpg").mock(return_value=httpx.Response(200, content=b"<html>not an image</html>"))
    respx.get("https://cdn.example/list.mp4").mock(return_value=httpx.Response(200, content=b"#EXTM3U\n#EXTINF:1,\nhttp://x/seg.ts\n"))
    cache = MediaCache(tmp_path)

    def asset(name):
        return MediaAsset(id=f"x:{name}", source="x", kind="image", url=f"https://cdn.example/{name}", license="L")

    ok = cache.get(asset("photo.jpg"))
    assert ok.read_bytes() == jpeg
    for bad in ("page.jpg", "list.mp4"):
        with pytest.raises(ValueError, match="not a supported"):
            cache.get(asset(bad))
        assert not cache.path_for(asset(bad)).exists()                # nothing bad left in the cache
        assert not list(tmp_path.glob("*.part"))


def test_a_stalled_source_is_skipped_after_the_deadline_and_the_others_still_answer():
    import threading
    import time

    from app.models import MediaAsset
    from app.providers.media_search import CompositeSearch

    def asset(i):
        return MediaAsset(id=f"a:{i}", source="a", kind="image", url="https://x/d.jpg", license="CC0")

    class Fast:
        name, kinds = "fast", frozenset({"image"})

        def search(self, q, kind, *, orientation="landscape", limit=10):
            return [asset(1)]

    class Stalled:
        name, kinds = "stalled", frozenset({"image"})
        release = threading.Event()

        def search(self, q, kind, *, orientation="landscape", limit=10):
            self.release.wait(10)
            return [asset(2)]

    class Broken:
        name, kinds = "broken", frozenset({"image"})

        def search(self, q, kind, *, orientation="landscape", limit=10):
            raise RuntimeError("boom")

    s = CompositeSearch([Stalled(), Broken(), Fast()], deadline=0.5)
    t0 = time.monotonic()
    out = s.search("x", "image")
    took = time.monotonic() - t0
    Stalled.release.set()
    assert [a.id for a in out] == ["a:1"] and took < 3          # the fast one answered; neither the stalled nor the broken one blocked it


def test_a_source_that_keeps_failing_is_left_out_for_a_while_and_comes_back():
    import time

    from app.models import MediaAsset
    from app.providers.media_search import CompositeSearch

    calls = {"down": 0}

    class Up:
        name, kinds = "up", frozenset({"image"})

        def search(self, q, kind, *, orientation="landscape", limit=10):
            return [MediaAsset(id="u:1", source="u", kind="image", url="https://x/d.jpg", license="CC0")]

    class Down:
        name, kinds = "down", frozenset({"image"})

        def search(self, q, kind, *, orientation="landscape", limit=10):
            calls["down"] += 1
            raise ConnectionError("unreachable")

    s = CompositeSearch([Down(), Up()], breaker_failures=2, breaker_pause=0.3)
    for q in ("a", "b", "c", "d"):
        assert [a.id for a in s.search(q, "image")] == ["u:1"]
    assert calls["down"] == 2                      # asked twice, then left out
    time.sleep(0.4)
    s.search("e", "image")
    assert calls["down"] == 3                      # the pause is over: it is tried again
