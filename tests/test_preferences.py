import json

import httpx

from backend.clip_detection import preferences, semantic
from backend.clip_detection.pipeline import with_preferences


def fake_embed(texts, client=None):
    def vec(t):
        t = t.lower()
        return [1.0 if ("censura" in t or "figuraccia" in t) else 0.0, 1.0 if "tramonto" in t else 0.0,
                1.0 if "chiacchiera" in t else 0.0, 0.1]
    return [vec(t) for t in texts]


EXAMPLES = {
    "positive": [{"id": "p1", "text": "ho sbagliato la censura che figuraccia", "category": "funny", "title": ""},
                 {"id": "p2", "text": "una figuraccia in diretta con la censura", "category": "funny", "title": ""}],
    "negative": [{"id": "n1", "text": "guardate che bel tramonto", "category": "storytelling", "title": ""}],
    "signature": "sig1",
}


def test_affinity_follows_your_choices(monkeypatch):
    monkeypatch.setattr(preferences, "embed", fake_embed)
    aff = preferences.affinity(["un'altra figuraccia con la censura", "che tramonto stasera", "chiacchiera generica"],
                               EXAMPLES)
    assert aff[0] == 1.0 and aff[1] == 0.0 and 0 < aff[2] < 1
    assert preferences.affinity(["x"], {"positive": EXAMPLES["positive"][:1], "negative": []}) is None  # too few


def test_collect_examples_uses_your_decisions(client):
    from backend.database.session import session_scope
    from backend.models import Clip, Video

    with session_scope() as db:
        v = Video(title="pref", original_filename="p.mp4", file_path="/nonexistent/p.mp4", game="GTA 6")
        db.add(v)
        db.flush()
        for status, text in (("approved", "storia della censura sbagliata, una figuraccia incredibile"),
                             ("exported", "la figuraccia della censura raccontata dall'inizio alla fine"),
                             ("rejected", "guardate che bel tramonto sulla città stasera ragazzi"),
                             ("detected", "questo non deve contare come esempio perché non è stato deciso")):
            db.add(Clip(video_id=v.id, start=0, end=30, transcript=text, status=status))
        vid = v.id
    ex = client.get("/api/preferences").json()
    assert ex["positive"] >= 2 and ex["negative"] >= 1 and ex["active"]
    with session_scope() as db:
        got = preferences.collect_examples(db)
        texts = [e["text"] for e in got["positive"] + got["negative"]]
        assert not any("non deve contare" in t for t in texts)
        db.delete(db.get(Video, vid))


def test_affinity_changes_the_order(monkeypatch):
    monkeypatch.setattr(preferences, "embed", fake_embed)
    sem = {"units": [{"id": 0, "start": 0, "end": 30, "text": "un'altra figuraccia con la censura"},
                     {"id": 1, "start": 40, "end": 70, "text": "che tramonto stasera"}],
           "judgements": [{"block": 0, "score": 6, "first": 0, "last": 0, "category": "funny", "hook": "", "reason": "x", "rank": 2},
                          {"block": 1, "score": 6, "first": 1, "last": 1, "category": "storytelling", "hook": "", "reason": "y", "rank": 1}]}
    out = with_preferences(sem, EXAMPLES)
    funny, sunset = out["judgements"]
    assert funny["pref"] > sunset["pref"] and "approvate" in out["preferences"]


def test_ranking_prompt_contains_your_examples():
    seen = {}

    def h(req):
        body = json.loads(req.content)
        seen["prompt"] = body["prompt"]
        return httpx.Response(200, json={"response": json.dumps({"ranking": [1, 0]})})

    data = {"model": "m", "units": [{"id": 0, "text": "a"}, {"id": 1, "text": "b"}],
            "judgements": [{"first": 0, "last": 0, "score": 5}, {"first": 1, "last": 1, "score": 5}]}
    out = semantic.rank_candidates(data, game="GTA 6", client=httpx.Client(transport=httpx.MockTransport(h)),
                                   examples=EXAMPLES)
    assert "+ PIACIUTA: ho sbagliato la censura" in seen["prompt"] and "- SCARTATA: guardate che bel tramonto" in seen["prompt"]
    assert [j["rank"] for j in out["judgements"]] == [2, 1] and out["ranking"]["examples"] == "sig1"


def test_rerank_requires_semantic_analysis(client):
    from backend.database.session import session_scope
    from backend.models import Video

    with session_scope() as db:
        v = Video(title="x", original_filename="x.mp4", file_path="/nonexistent/x.mp4")
        db.add(v)
        db.flush()
        vid = v.id
    assert client.post(f"/api/videos/{vid}/rerank").status_code == 422
