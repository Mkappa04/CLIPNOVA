"""Social metadata generator: validation, grounding, hashtags, partial regeneration, fallbacks (mocked LLM).

The semantic quality with the real model is evaluated by scripts/eval_metadata.py (8 scenarios)."""

import json
from collections import Counter

import httpx
import pytest

from backend.content_generation import metadata as M
from backend.content_generation.context import ClipContext
from backend.content_generation.templates import for_platform


def ctx(**kw) -> ClipContext:
    base = dict(clip_id="c1", language="it", speech_language="it", game="Minecraft", creator="", category="fail",
                preset="gaming_dynamic", duration=25.0,
                transcript="metto la TNT sotto la casa di Luca aspetta no è esplosa la mia casa ho sbagliato casa",
                timed_transcript="(0.0s) metto la TNT sotto la casa di Luca", before="", after="",
                semantic={"payoff_type": "colpo di scena"}, detection_reason="", signals=[],
                visual={"setting": "villaggio a blocchi", "action": "una casa esplode", "kind": "videogioco",
                        "people": "", "on_screen_text": "", "confidence": 0.8}, word_count=19)
    base.update(kw)
    return ClipContext(**base)


ANALYSIS = {"category": "fail", "subject": "Minecraft", "event": "Fa esplodere la propria casa per errore con la TNT",
            "context": "Voleva colpire la casa di Luca", "key_moment": "la casa esplode", "why_interesting": "errore comico",
            "speaker": "non identificabile", "tone": "divertente", "emotion": "sorpresa",
            "evidence": ["ho sbagliato casa", "frase mai detta"], "confidence": 0.8, "insufficient_context": False}
WRITE = {"titles": ["Non ci posso credere!", "Fa saltare la sua casa al posto di quella di Luca",
                    "Il piano di Marco contro Luca finisce male", "La TNT sotto la casa sbagliata"],
         "best": 1, "youtube_title": "Minecraft: la TNT finisce sotto la casa sbagliata",
         "instagram": "Voleva far saltare la casa di Luca, ma la TNT era sotto la sua. Tu te ne saresti accorto? #fyp",
         "tiktok": "Piazza la TNT, sbaglia casa 😂😂😂", "youtube_description": "Un errore con la TNT in Minecraft.",
         "keywords": ["TNT", "Minecraft", "Creeper", "viral"]}


def ollama(answers: list, calls: list | None = None):
    """Mock /api/generate returning the queued answers (dict → JSON, str → raw text, int → HTTP status)."""
    queue = list(answers)

    def h(req: httpx.Request):
        if req.url.path.endswith("/api/ps"):
            return httpx.Response(200, json={"models": []})
        body = json.loads(req.content)
        if "prompt" not in body:
            return httpx.Response(200, json={})
        if calls is not None:
            calls.append(body)
        a = queue.pop(0)
        if isinstance(a, int):
            return httpx.Response(a, json={"error": "runner crashed"})
        return httpx.Response(200, json={"response": a if isinstance(a, str) else json.dumps(a)})
    return httpx.Client(transport=httpx.MockTransport(h))


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    from backend.clip_detection import semantic

    monkeypatch.setattr(semantic, "_RETRY_WAIT_S", 0)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)


def test_full_generation_is_validated_and_grounded():
    calls = []
    meta, warnings = M.generate(ctx(), client=ollama([ANALYSIS, WRITE], calls), model="m",
                                recent_tags=Counter({"gamingitalia": 9}))
    a = meta.content_analysis
    assert a.source == "llm" and a.evidence == ["ho sbagliato casa"]          # non-verbatim evidence dropped
    opts = meta.titles.options
    assert "Non ci posso credere!" not in opts                                  # generic title rejected
    assert not any("Marco" in t for t in opts)                                  # invented name rejected
    assert meta.titles.selected == "Fa saltare la sua casa al posto di quella di Luca"   # the model's best
    ig, tt = meta.platforms.instagram, meta.platforms.tiktok
    assert "#" not in ig.caption and tt.caption.count("😂") == 1               # no hashtags in text, ≤1 emoji
    assert ig.caption != tt.caption
    for p in (ig.hashtags, tt.hashtags, meta.platforms.youtube_shorts.hashtags):
        assert p[0] == "Minecraft" and not {t.lower() for t in p} & M.BANNED_TAGS
        assert "Creeper" not in p                                               # keyword not in the facts
    assert len(meta.platforms.youtube_shorts.hashtags) <= 4 and len(ig.hashtags) <= 5
    assert "Tnt" in tt.hashtags or "TNT" in [t.upper() for t in tt.hashtags]
    assert any("generico" in w for w in warnings) and any("Marco" in w for w in warnings)
    assert "Minecraft" in calls[0]["prompt"] and "villaggio a blocchi" in calls[0]["prompt"]   # visual context used
    legacy = meta.legacy()
    assert legacy["title"] == meta.titles.selected and legacy["caption"] == ig.caption


def test_partial_regeneration_keeps_the_other_parts():
    meta, _ = M.generate(ctx(), client=ollama([ANALYSIS, WRITE]), model="m")
    cur = meta.model_dump()
    new_titles = {"titles": ["La casa sbagliata salta in aria", "Errore di mira con la TNT", "Luca si salva, la sua casa no"],
                  "best": 0, "youtube_title": "Minecraft: la casa sbagliata salta in aria"}
    calls = []
    meta2, _ = M.generate(ctx(), parts=["titles"], current=cur, client=ollama([new_titles], calls), model="m")
    assert len(calls) == 1 and "3 titoli" in calls[0]["prompt"]                 # analysis reused, one call only
    assert meta2.titles.selected == "La casa sbagliata salta in aria"
    assert meta2.platforms.instagram.caption == meta.platforms.instagram.caption
    assert meta2.platforms.tiktok.hashtags == meta.platforms.tiktok.hashtags
    calls = []
    meta3, _ = M.generate(ctx(), parts=["hashtags"], current=meta2.model_dump(),
                          client=ollama([{"keywords": ["casa", "TNT"]}], calls), model="m")
    assert meta3.titles == meta2.titles and meta3.platforms.instagram.caption == meta2.platforms.instagram.caption


def test_invalid_json_and_crashes_are_retried_then_fall_back():
    # grammar-mode answer empty → retried without grammar (free text with chatter around the JSON)
    meta, w = M.generate(ctx(), client=ollama([ANALYSIS, "", "Ecco:\n```json\n" + json.dumps(WRITE) + "\n```"]), model="m")
    assert meta.generated_by == "ollama:m" and not any("non riuscita" in x for x in w)
    # the runner keeps crashing → prudent texts from the facts, with a warning
    meta, w = M.generate(ctx(), client=ollama([ANALYSIS, 500, 500, 500, 500, 500]), model="m")
    assert meta.generated_by == "rules" and any("Scrittura AI non riuscita" in x for x in w)
    assert meta.titles.selected.startswith("Fa esplodere la propria casa")      # fallback uses the AI analysis
    assert all(not M.is_generic(t, "Minecraft") for t in meta.titles.options)


def test_without_ai_texts_are_prudent_and_from_facts_only():
    c = ctx(visual={})
    meta, w = M.generate(c, use_ai=False)
    assert meta.generated_by == "rules" and any("non disponibile" in x for x in w)
    facts = c.facts_text()
    for t in meta.titles.options + [meta.platforms.instagram.caption, meta.platforms.tiktok.caption]:
        assert not M.unsupported(t, facts), t
    assert any("“" in t for t in meta.titles.options)                           # a verbatim quote


def test_no_speech_and_no_visual_does_not_invent():
    c = ctx(transcript="", timed_transcript="", word_count=0, visual={}, game="")
    calls = []
    meta, w = M.generate(c, client=ollama([], calls), model="m")
    assert calls == []                                                          # nothing to describe: no LLM call
    assert meta.content_analysis.insufficient_context
    assert any("scrivi tu" in x for x in w)
    assert not meta.platforms.instagram.hashtags or all(t.lower() not in M.BANNED_TAGS for t in meta.platforms.instagram.hashtags)


def test_generic_and_grounding_helpers():
    assert M.is_generic("Non ci posso credere! 😱 | Fortnite", "Fortnite")
    assert M.is_generic("Momento incredibile!", "")
    assert not M.is_generic("Perde la partita all'ultimo secondo per un errore", "")
    facts = "avevo diciannove anni al novantesimo minuto"
    assert M.unsupported("A 19 anni sul palco", facts) == []
    assert M.unsupported("Gol al 90", facts) == []
    assert M.unsupported("Segna 3 gol", facts) == ["3"]
    assert M.unsupported("Il gol di Messi al novantesimo", facts) == ["Messi"]
    assert M.unsupported("Gets Choked On The Dock", "dock") == []               # Title Case is not a name
    assert M.FILLER_RE.sub("", "Palla all'incrocio. Che gol!").strip() == "Palla all'incrocio."


def test_hashtag_counts_are_configurable(monkeypatch):
    from backend.core.config import get_settings

    monkeypatch.setattr(get_settings(), "hashtags_tiktok", (2, 2))
    monkeypatch.setattr(get_settings(), "hashtags_youtube", (1, 1))
    tags = M.build_hashtags(ctx(), M.ContentAnalysis(category="fail"), ["TNT", "casa"], Counter(), seed=1)
    assert len(tags["tiktok"]) == 2 and tags["youtube_shorts"] == ["Minecraft"]
    assert len(set(t.lower() for t in tags["instagram"])) == len(tags["instagram"])   # no duplicates


def test_exporter_uses_per_platform_texts():
    meta, _ = M.generate(ctx(), client=ollama([ANALYSIS, WRITE]), model="m")
    content = {**meta.legacy(), "metadata": meta.model_dump()}
    tt = for_platform(content, "tiktok", "Credit: @x")
    ig = for_platform(content, "instagram")
    yt = for_platform(content, "youtube")
    assert tt["caption"].startswith(meta.platforms.tiktok.caption) and "Credit: @x" in tt["caption"]
    assert ig["caption"].startswith(meta.platforms.instagram.caption) and ig["caption"] != tt["caption"]
    assert yt["title"] == meta.platforms.youtube_shorts.title and "#Shorts" in yt["description"]
    assert all(f"#{t}" in tt["caption"] for t in meta.platforms.tiktok.hashtags)
