import json

import httpx
import pytest

from backend.content_generation import llm
from backend.content_generation.templates import for_platform, generate

FACTS = dict(category="rage", transcript="Allora andiamo verso la banca. Ma porca miseria, la polizia di nuovo! Vabbè.",
             keywords=["porca", "polizia", "banca"], game="GTA 6", creator="Flavio")


def test_template_uses_only_spoken_quote_and_safe_hashtags():
    c = generate(**FACTS, language="it", attribution="Credit: @creator")
    assert "Ma porca miseria, la polizia di nuovo!" in c["title"] and len(c["title"]) <= 100
    assert "porca" not in [t.lower() for t in c["hashtags"]]          # rage cue never becomes a hashtag
    assert {"GTA6", "polizia", "banca"} <= set(c["hashtags"])
    assert "Credit: @creator" in c["description"] and c["generated_by"] == "template"


def test_no_transcript_gives_generic_copy():
    c = generate(category="epic", transcript="", keywords=[], game="GTA 6", creator="", language="en")
    assert c["title"].startswith("GTA 6 – Epic moment") and "“" not in c["hook"]


def test_platform_limits_and_attribution():
    c = generate(**FACTS, language="it")
    c["caption"] = "x" * 3000
    tk = for_platform(c, "tiktok", "Credit: @creator")
    assert len(tk["caption"]) <= 2200 and "#GTA6" in tk["caption"]
    yt = for_platform(c, "youtube", "Credit: @creator")
    assert len(yt["title"]) <= 100 and "#Shorts" in yt["description"] and "Credit: @creator" in yt["description"]


def _ollama(response: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["keep_alive"] == 0 and body["format"] == "json" and body["think"] is False
        assert "Do NOT invent" in body["prompt"] and "polizia di nuovo" in body["prompt"]
        return httpx.Response(200, json={"response": json.dumps(response)})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_rewrite_keeps_faithful_fields_and_rejects_invented(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "llm_provider", "ollama")
    draft = generate(**FACTS, language="it")
    fake = {"title": "La polizia di nuovo! #gta", "hook": "Porca miseria, la polizia!",
            "caption": "Flavio affronta un inseguimento epico con elicotteri e carri armati", "cta": "Seguimi!"}
    out, warnings = llm.rewrite(draft, language="it", client=_ollama(fake), **FACTS)
    assert out["title"] == "La polizia di nuovo!"                  # hashtags stripped
    assert out["caption"] == draft["caption"]                       # invented caption rejected → template kept
    assert out["description"] == draft["description"]               # description never rewritten
    assert any("caption" in w and "scartata" in w for w in warnings)
    assert out["generated_by"].startswith("ollama:")


def test_llm_disabled_raises(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "llm_provider", "none")
    with pytest.raises(llm.LLMUnavailable):
        llm.rewrite({}, language="it", **FACTS)


def test_unsupported_terms_flags_new_names():
    assert llm.unsupported_terms("Rapina a Vice City con Lucia!", "GTA 6 polizia Lucia") == ["Vice", "City"]
