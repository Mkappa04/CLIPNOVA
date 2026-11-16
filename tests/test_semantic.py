import json

import httpx
import numpy as np

from backend.clip_detection import semantic
from backend.clip_detection.scoring import RawSignals, ScoringConfig, hybrid_clips
from backend.transcription.whisper_engine import Segment, Transcript, Word


def sentence(start, text, step=0.4):
    ws = [Word(start + i * step, start + i * step + 0.35, " " + t, 0.9) for i, t in enumerate(text.split())]
    return Segment(0, start, ws[-1].end, text, -0.2, 0.05, ws)


def story_transcript() -> Transcript:
    segs = []
    t = 0.0
    lines = [
        "allora ragazzi oggi facciamo un giro per la città e vediamo un po' di posti",            # filler
        "qui è dove io e un amico abbiamo fatto la nostra prima collaborazione",                   # setup
        "eravamo emozionatissimi e tutto andava benissimo fino a quando",                          # build-up
        "abbiamo litigato in diretta e non ci siamo parlati per un anno intero!",                   # payoff
        "comunque andiamo avanti vediamo cosa c'è da questa parte della mappa",                    # filler
    ]
    for rep in range(3):
        for ln in lines:
            segs.append(sentence(t, ln))
            t = segs[-1].end + 1.2  # pause between thoughts
    for i, s in enumerate(segs):
        s.id = i
    return Transcript("it", 0.99, t + 5, "cuda", "test", segs)


def test_units_are_cut_at_pauses_and_blocks_are_about_a_minute():
    units = semantic.build_units(story_transcript())
    assert len(units) == 15 and units[3].text.startswith("abbiamo litigato")
    blocks = semantic.build_blocks(units, target_s=60, max_s=90)
    assert all(b[-1].end - b[0].start <= 90 for b in blocks)


def mocked_ollama(calls, hook="non ci siamo parlati per un anno intero!"):
    def h(req: httpx.Request):
        body = json.loads(req.content)
        if "prompt" not in body:  # unload request
            return httpx.Response(200, json={})
        calls.append(body)
        ids = [int(x) for x in __import__("re").findall(r"^\[(\d+)\]", body["prompt"], flags=8)]
        if '"ranking"' in body["prompt"]:  # listwise ranking: keep the given order
            return httpx.Response(200, json={"response": json.dumps({"ranking": ids, "best_reason": "ok"})})
        assert body["format"] == "json" and "non inventare" in body["prompt"].lower()
        payoff = [i for i in ids if i % 5 == 3]
        if not payoff:
            return httpx.Response(200, json={"response": json.dumps({"score": 2, "first": ids[0], "last": ids[-1],
                                                                     "category": "storytelling", "hook": "",
                                                                     "reason": "chiacchiere"})})
        p = payoff[0]
        return httpx.Response(200, json={"response": json.dumps({
            "score": 8, "first": str(p - 2), "last": p, "category": "storytelling", "hook": hook, "standalone": True,
            "reason": "Aneddoto completo con un finale a sorpresa"})})
    return httpx.Client(transport=httpx.MockTransport(h))


def test_judge_validates_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic.get_settings(), "llm_model", "test-model")
    calls = []
    data = semantic.judge_blocks(story_transcript(), game="GTA 6", cache_dir=tmp_path, client=mocked_ollama(calls), model="test-model")
    good = [j for j in data["judgements"] if j["score"] >= 8]
    assert good and good[0]["hook"] == "non ci siamo parlati per un anno intero!"
    n = len(calls)
    again = semantic.judge_blocks(story_transcript(), game="GTA 6", cache_dir=tmp_path, client=mocked_ollama(calls), model="test-model")
    assert len(calls) == n and again["key"] == data["key"]          # served from cache

    (tmp_path / semantic.SEMANTIC_FILE).unlink()
    bad = semantic.judge_blocks(story_transcript(), game="GTA 6", cache_dir=tmp_path,
                                client=mocked_ollama([], hook="frase che nessuno ha mai detto"), model="test-model")
    assert all(j["hook"] == "" for j in bad["judgements"])          # non-verbatim quotes are dropped


def test_semantic_clips_cover_the_whole_story(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic.get_settings(), "llm_model", "test-model")
    tr = story_transcript()
    data = semantic.judge_blocks(tr, game="GTA 6", cache_dir=tmp_path, client=mocked_ollama([]), model="test-model")
    n = int(tr.duration / 0.5)
    rms = np.full(n, -25, dtype=np.float32)
    raw = RawSignals(0.5, tr.duration, rms, np.zeros(n, np.float32), np.zeros(n, np.float32), np.ones(n, np.float32),
                     np.zeros(n, np.float32), scenes=[])
    _, clips = hybrid_clips(raw, tr, "GTA 6", ScoringConfig(min_score=0), data)
    assert clips and all(c.reason.startswith("Valutazione AI locale 8/10") for c in clips)
    first = clips[0]
    assert "prima collaborazione" in first.transcript and "per un anno intero" in first.transcript  # setup + payoff
    assert "allora ragazzi" not in first.transcript                                                  # filler excluded
    assert 12 <= first.duration <= 75 + 0.01
    assert first.suggested_title.startswith("“non ci siamo parlati")
    # without the semantic data the same video falls back to heuristics
    _, heur = hybrid_clips(raw, tr, "GTA 6", ScoringConfig(min_score=0, use_semantic=False), data)
    assert all("Valutazione AI locale" not in c.reason for c in heur)


def test_filler_keywords_lose_weight():
    from backend.clip_detection.scoring import build_timeline

    tr = Transcript("it", 0.9, 120, "cpu", "t", [sentence(i * 6, "ma che ma che") for i in range(15)]
                    + [sentence(100, "wasted")])
    n = 240
    raw = RawSignals(0.5, 120, np.full(n, -30, np.float32), np.zeros(n, np.float32), np.zeros(n, np.float32),
                     np.zeros(n, np.float32), np.zeros(n, np.float32), [])
    tl = build_timeline(raw, tr, "GTA 6", ScoringConfig())
    kw = tl.features["keywords"]
    assert kw[int(100.2 / 0.5)] > kw[int(30.2 / 0.5)]   # one rare «wasted» beats a filler said 30 times


def test_llm_crash_is_retried_and_model_unloaded_once(tmp_path, monkeypatch):
    """A 500 from Ollama (llama runner crashed, e.g. CUDA OOM) is retried; judging and ranking share one loaded
    model instance (same num_ctx, no unload in between) and the model is unloaded once at the end."""
    monkeypatch.setattr(semantic, "_RETRY_WAIT_S", 0)
    inner, log, crashed = mocked_ollama([]), [], []

    def h(req: httpx.Request):
        body = json.loads(req.content)
        log.append(body)
        if "prompt" not in body:
            return httpx.Response(200, json={})
        if '"ranking"' in body["prompt"]:
            if not crashed:
                crashed.append(1)
                return httpx.Response(500, json={"error": "llama runner process has terminated"})
            ids = [int(x) for x in __import__("re").findall(r"^\[(\d+)\]", body["prompt"], flags=8)]
            return httpx.Response(200, json={"response": json.dumps({"ranking": ids[::-1], "best_reason": "ok"})})
        return inner._transport.handle_request(req)

    data = semantic.judge_blocks(story_transcript(), game="GTA 6", cache_dir=tmp_path,
                                 client=httpx.Client(transport=httpx.MockTransport(h)), model="test-model")
    assert crashed and "best_reason" in data["ranking"]                     # ranking succeeded on the retry
    assert all("rank" in j for j in data["judgements"])
    gens = [b for b in log if "prompt" in b]
    assert {b["options"]["num_ctx"] for b in gens} == {semantic.NUM_CTX}  # no reload between phases
    assert all(b["keep_alive"] != 0 for b in gens)
    assert [b for b in log if "prompt" not in b] == [log[-1]]             # one unload, at the very end


def test_ranking_prompt_fits_the_context():
    units = [{"id": i, "text": "parola " * 120} for i in range(80)]
    js = [{"first": i, "last": i, "score": float(i % 10)} for i in range(80)]
    prompts = []

    def h(req: httpx.Request):
        prompts.append(json.loads(req.content)["prompt"])
        return httpx.Response(200, json={"response": json.dumps({"ranking": [], "best_reason": ""})})

    ex = {"positive": [{"text": "x" * 400}] * 5, "negative": [{"text": "y" * 400}] * 5, "signature": "s"}
    data = semantic.rank_candidates({"units": units, "judgements": js}, game="GTA 6", examples=ex,
                                    client=httpx.Client(transport=httpx.MockTransport(h)), model="m")
    assert len(prompts[0]) / semantic._CHARS_PER_TOKEN <= semantic.NUM_CTX - semantic._RANK_OUTPUT_TOKENS
    assert sorted(j["rank"] for j in data["judgements"]) == list(range(1, 81))
    assert prompts[0].count("\n[") <= semantic.RANK_MAX_ITEMS
