import json

import httpx
import pytest
import respx

from app.models import Segment, Transcript, Word
from app.providers.scene_planner.gemini import GeminiPlanner
from app.providers.scene_planner.interface import PlannerError

URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"


def tr():
    ws = [Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate("a castle on a hill".split())]
    return Transcript(language="en", duration=3.0, segments=[Segment(text="a castle on a hill", start=0, end=3, words=ws)])


def ok(query="castle on hill"):
    body = json.dumps([{"id": 1, "query_en": query, "keywords": ["fortress"], "preferred_kind": "image"}])
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": body}]}}]})


def planner(models):
    return GeminiPlanner("k", models, 1, 8, client=httpx.Client(timeout=5))


@respx.mock
def test_first_healthy_model_is_used_and_others_not_called():
    a = respx.post(URL.format("fast")).mock(return_value=ok())
    b = respx.post(URL.format("slow")).mock(return_value=ok("other"))
    [s] = planner("fast,slow").plan(tr())
    assert s.query_en == "castle on hill" and a.call_count == 1 and b.call_count == 0


@respx.mock
def test_503_and_timeout_fail_over_to_the_next_model():
    respx.post(URL.format("m1")).mock(return_value=httpx.Response(503))
    respx.post(URL.format("m2")).mock(side_effect=httpx.ReadTimeout("slow"))
    c = respx.post(URL.format("m3")).mock(return_value=ok("from third"))
    [s] = planner("m1, m2 ,m3").plan(tr())  # spaces around names are tolerated
    assert s.query_en == "from third" and c.call_count == 1


@respx.mock
def test_503_is_not_retried_on_the_same_model():
    a = respx.post(URL.format("m1")).mock(return_value=httpx.Response(503))
    respx.post(URL.format("m2")).mock(return_value=ok())
    planner("m1,m2").plan(tr())
    assert a.call_count == 1  # fail over immediately instead of waiting through retries


@respx.mock
def test_all_models_failing_raises_planner_error_without_the_key():
    respx.post(URL.format("m1")).mock(return_value=httpx.Response(503))
    respx.post(URL.format("m2")).mock(return_value=httpx.Response(404))
    with pytest.raises(PlannerError) as e:
        planner("m1,m2").plan(tr())
    msg = str(e.value)
    assert "m1" in msg and "m2" in msg and "503" in msg and "404" in msg and "k" != msg  # both reported
    assert "key=" not in msg


@respx.mock
def test_garbage_answer_fails_over():
    respx.post(URL.format("m1")).mock(return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))
    respx.post(URL.format("m2")).mock(return_value=ok())
    [s] = planner("m1,m2").plan(tr())
    assert s.query_en == "castle on hill"
