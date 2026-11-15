"""Optional local LLM (Ollama) rewrite of the template copy.

Guardrails against invented content:
- the prompt contains ONLY clip facts (game, category, creator, transcript, keywords) and forbids new facts;
- output is strict JSON with the same fields; length limits enforced;
- hashtags are restricted to the template set plus words present in the facts;
- proper-noun-like words that appear nowhere in the facts are reported as warnings for the reviewer.
The model is unloaded right after the call (keep_alive=0) to free VRAM for Whisper/NVENC.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from backend.core.config import get_settings

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


def status() -> dict:
    s = get_settings()
    info = {"provider": s.llm_provider, "model": s.llm_model, "available": False, "models": []}
    if s.llm_provider != "ollama":
        return info
    try:
        r = httpx.get(f"{s.llm_url}/api/tags", timeout=3)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        info["models"] = names
        info["available"] = s.llm_model in names or f"{s.llm_model}:latest" in names
        if not info["available"]:
            info["reason"] = f"Model {s.llm_model} not installed in Ollama"
    except (httpx.HTTPError, ValueError) as e:
        info["reason"] = f"Ollama not reachable at {s.llm_url}: {e}"
    return info


PROMPT = """You write short social media copy for a vertical gaming clip.
Language: {language_name}. Platform style: TikTok / Instagram Reels / YouTube Shorts.

FACTS (the ONLY information you may use):
- Game: {game}
- Clip category (heuristic estimate): {category}
- Creator: {creator}
- Words actually spoken in the clip (transcript): "{transcript}"
- Keywords detected in the speech: {keywords}

RULES:
- Do NOT invent events, places, characters, results, numbers or quotes that are not in the FACTS.
- Do NOT describe actions, feelings or reactions that are not literally in the transcript.
- If the transcript is empty, keep the copy generic (game + category), do not describe what happens.
- Quotes must be copied verbatim from the transcript.
- No hashtags inside title/hook/caption/description.
- title <= 90 chars, hook <= 90 chars, caption <= 220 chars, cta <= 80 chars. Short and punchy.

Return ONLY a JSON object with keys: "title", "hook", "caption", "cta".
Draft to improve (same facts):
{draft}
"""


LLM_FIELDS = ("title", "hook", "caption", "cta")  # the description stays factual (template)
MAX_NOVELTY = 0.2

STOPWORDS = set("""
il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi non più come quando dove perché
questo questa quello quella sono sei è siamo siete hanno ha ho hai fa fare ci si mi ti vi ne del della dei delle
al alla ai alle dal dalla nel nella sul sulla anche ancora già poi solo tutto tutti molto troppo qui ora oggi
the a an of to in on at for with and or but if that this these those is are was were be been it its you your
we our they their he she his her i me my not no so just all more very what when where how why who
clip video gioco game momento moment guarda watch segui seguimi follow altre altro more per
""".split())


def novelty(text: str, facts: str) -> float:
    """Share of meaningful words (≥ 4 letters, not stopwords) that do not occur in the facts."""
    known = {w[:5] for w in _words(facts)}  # 5-letter stems tolerate inflection (polizia/polizie)
    words = [w for w in _words(text) if len(w) >= 4 and w not in STOPWORDS and not w.isdigit()]
    if not words:
        return 0.0
    return sum(1 for w in words if w[:5] not in known) / len(words)


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[\wÀ-ÿ']+", text or "")}


def unsupported_terms(text: str, facts: str) -> list[str]:
    """Capitalised words (likely names/places) not present anywhere in the facts."""
    known = _words(facts)
    out = []
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-ZÀ-Ý][\wà-ÿ]{3,})\b", text or ""):
        w = m.group(1)
        if w.lower() not in known and w not in out:
            out.append(w)
    return out


def rewrite(draft: dict, *, game: str, category: str, creator: str, transcript: str, keywords: list[str],
            language: str, client: httpx.Client | None = None) -> tuple[dict, list[str]]:
    s = get_settings()
    if s.llm_provider != "ollama":
        raise LLMUnavailable("LLM disabled (CLIPNOVA_LLM_PROVIDER=none)")
    prompt = PROMPT.format(
        language_name="Italian" if language == "it" else "English", game=game, category=category,
        creator=creator or "-", transcript=(transcript or "")[:1500].replace('"', "'"),
        keywords=", ".join(keywords) or "-",
        draft=json.dumps({k: draft.get(k, "") for k in LLM_FIELDS},
                         ensure_ascii=False))
    body = {"model": s.llm_model, "prompt": prompt, "stream": False, "format": "json", "think": False,
            "keep_alive": 0, "options": {"temperature": 0.4, "num_ctx": 4096}}
    own = client is None
    client = client or httpx.Client(timeout=s.llm_timeout_s)
    try:
        r = client.post(f"{s.llm_url}/api/generate", json=body)
        r.raise_for_status()
        data = json.loads(r.json().get("response", "{}"))
    except (httpx.HTTPError, ValueError) as e:
        raise LLMUnavailable(f"Local LLM call failed: {e}") from e
    finally:
        if own:
            client.close()

    limits = {"title": 100, "hook": 120, "caption": 300, "cta": 120}
    out = dict(draft)
    facts = " ".join([game, category, creator, transcript, " ".join(keywords), json.dumps(draft, ensure_ascii=False)])
    warnings = []
    used = 0
    for k, lim in limits.items():
        v = data.get(k)
        if not (isinstance(v, str) and v.strip()):
            continue
        v = re.sub(r"#\w+", "", v).strip()[:lim]
        ratio = novelty(v, facts)
        if ratio > MAX_NOVELTY:
            warnings.append(f"{k}: proposta LLM scartata ({ratio:.0%} di parole non presenti nella clip)")
            continue
        bad = unsupported_terms(v, facts)
        if bad:
            warnings.append(f"{k}: termini non presenti nella clip, verifica: {', '.join(bad)}")
        out[k] = v
        used += 1
    out["generated_by"] = f"ollama:{s.llm_model}" if used else "template"
    return out, warnings
