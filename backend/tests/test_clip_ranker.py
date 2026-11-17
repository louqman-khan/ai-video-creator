from pathlib import Path

import pytest

from app.config import Settings
from app.models import MediaAsset, Scene
from app.providers.media_ranker import create_ranker
from app.providers.media_ranker.clip import ClipRanker, models_present
from app.providers.media_ranker.heuristic import HeuristicRanker

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "assets" / "models" / "clip"
needs_model = pytest.mark.skipif(not models_present(CLIP), reason="CLIP model files are not installed (docs/clip-ranker.md)")


def colour(tmp_path, name, rgb):
    from PIL import Image

    p = tmp_path / f"{name}.png"
    Image.new("RGB", (320, 240), rgb).save(p)
    return MediaAsset(id=f"t:{name}", source="t", kind="image", url=p.as_uri(), thumb_url=p.as_uri(), width=1920, height=1080, license="CC0", title="")


def scene(text):
    return Scene(id=1, start=0, end=5, text=text, query_en=text)


@needs_model
def test_pictures_that_match_the_words_come_first(tmp_path):
    cands = [colour(tmp_path, "green", "green"), colour(tmp_path, "red", "red"), colour(tmp_path, "blue", "blue")]
    r = ClipRanker(CLIP, tmp_path / "cache")
    assert r.rank(scene("a plain red background"), cands)[0].id == "t:red"
    assert r.rank(scene("a plain blue background"), cands)[0].id == "t:blue"
    assert r.rank(scene("a plain green background"), cands)[0].id == "t:green"


@needs_model
def test_embeddings_are_remembered_on_disk(tmp_path):
    cands = [colour(tmp_path, "red", "red"), colour(tmp_path, "blue", "blue")]
    r = ClipRanker(CLIP, tmp_path / "cache")
    first = r.rank(scene("red"), cands)
    assert len(list((tmp_path / "cache").glob("*.npy"))) == 2
    for a in cands:                                                   # the previews are gone: the answer still comes from the cache
        Path(a.thumb_url[len("file://"):]).unlink()
    assert [a.id for a in ClipRanker(CLIP, tmp_path / "cache").rank(scene("red"), cands)] == [a.id for a in first]


@needs_model
def test_candidates_without_a_usable_preview_keep_their_heuristic_score(tmp_path):
    good = colour(tmp_path, "red", "red")
    none = good.model_copy(update={"id": "t:none", "thumb_url": "", "url": "https://example.com/x.mp4", "kind": "video"})
    broken_file = tmp_path / "broken.png"
    broken_file.write_bytes(b"not a picture")
    broken = good.model_copy(update={"id": "t:broken", "thumb_url": broken_file.as_uri()})
    out = ClipRanker(CLIP, tmp_path / "cache").rank(scene("red"), [none, broken, good])
    assert {a.id for a in out} == {"t:none", "t:broken", "t:red"}      # nobody is dropped, nothing crashes
    assert ClipRanker(CLIP, None).rank(scene("red"), []) == []


def test_a_broken_model_falls_back_to_the_heuristic(tmp_path, monkeypatch):
    r = ClipRanker(tmp_path, None)                                    # no model files at all
    a = MediaAsset(id="x:1", source="x", kind="image", url="u", license="L", width=1920, height=1080, title="red")
    b = MediaAsset(id="x:2", source="x", kind="image", url="u", license="L", width=640, height=480, title="blue")
    assert [x.id for x in r.rank(scene("red"), [b, a])] == [x.id for x in HeuristicRanker(True).rank(scene("red"), [b, a])]


def test_auto_uses_clip_only_when_its_files_exist(tmp_path):
    none = create_ranker(Settings(_env_file=None, clip_dir=str(tmp_path / "missing"), work_dir=str(tmp_path)))
    assert isinstance(none, HeuristicRanker)
    for f in ("vision_model_quantized.onnx", "text_model_quantized.onnx", "tokenizer.json"):
        (tmp_path / f).write_bytes(b"x")
    assert isinstance(create_ranker(Settings(_env_file=None, clip_dir=str(tmp_path), work_dir=str(tmp_path))), ClipRanker)
    assert isinstance(create_ranker(Settings(_env_file=None, media_ranker="heuristic", clip_dir=str(tmp_path), work_dir=str(tmp_path))), HeuristicRanker)
