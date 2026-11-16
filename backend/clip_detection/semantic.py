"""Semantic highlight detection with the optional local LLM (Ollama).

Audio/visual heuristics find *loud* or *busy* moments; they cannot tell a good story from filler talk.
Here the transcript is split into "thought units" (sentences grouped and cut at pauses), grouped into
~1-minute blocks, and the local LLM rates each block as a stand-alone short:
  - does it make sense without the rest of the video?
  - does it have a payoff (joke, reveal, strong reaction, conflict, surprising fact, complete anecdote)?
It picks the best contiguous span of units (so clips start and end on whole thoughts), a category and a
hook quoted VERBATIM from the text. Quotes that are not in the transcript are discarded.

Results are cached per transcript+model in data/cache/<video>/semantic.json, so re-scoring is instant.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from backend.clip_detection.lexicon import normalize
from backend.core.config import get_settings
from backend.transcription.whisper_engine import Transcript

log = logging.getLogger(__name__)

CATEGORIES = ("funny", "rage", "epic", "fail", "reaction", "clutch", "storytelling", "unexpected", "gameplay_highlight")
SEMANTIC_FILE = "semantic.json"
PROMPT_VERSION = "v2-rubric"


@dataclass
class Unit:
    id: int
    start: float
    end: float
    text: str


@dataclass
class Judgement:
    block: int
    score: float               # 0..10
    first: int                 # unit ids (inclusive)
    last: int
    category: str
    hook: str
    reason: str
    standalone: bool = True
    raw: dict = field(default_factory=dict)


# ----------------------------------------------------------------- units & blocks
def build_units(transcript: Transcript, pause_s: float = 0.8, max_s: float = 28.0) -> list[Unit]:
    """Group words into thought units: cut at pauses, at sentence ends after a few seconds, or when too long."""
    words = [(w.start, w.end, w.word) for s in transcript.segments for w in s.words]
    if not words:
        words = [(s.start, s.end, " " + s.text) for s in transcript.segments]
    units: list[Unit] = []
    cur: list[tuple[float, float, str]] = []

    def flush() -> None:
        if cur:
            text = "".join(w for _, _, w in cur).strip()
            if text:
                units.append(Unit(len(units), round(cur[0][0], 2), round(cur[-1][1], 2), text))
            cur.clear()

    for w in words:
        if cur:
            gap = w[0] - cur[-1][1]
            length = cur[-1][1] - cur[0][0]
            sentence_end = re.search(r"[.!?…]$", cur[-1][2].strip()) is not None
            if gap >= pause_s or length >= max_s or (sentence_end and length >= 6):
                flush()
        cur.append(w)
    flush()
    return units


def build_blocks(units: list[Unit], target_s: float = 60.0, max_s: float = 90.0) -> list[list[Unit]]:
    blocks, cur = [], []
    for u in units:
        if cur and (u.end - cur[0].start > max_s or (u.start - cur[0].start >= target_s)):
            blocks.append(cur)
            cur = []
        cur.append(u)
    if cur:
        if blocks and cur[-1].end - cur[0].start < target_s * 0.35:
            blocks[-1].extend(cur)  # tiny tail: merge
        else:
            blocks.append(cur)
    return blocks


def _fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


PROMPT = """Sei un editor di Shorts/TikTok di gaming. Analizza questo blocco di trascrizione di un video di {game}
(parlato del creator, lingua {lang}). Ogni riga è un'unità di pensiero: [id numerico] (minuto) testo.

{context}BLOCCO:
{lines}

Trova nel blocco il momento migliore per una clip verticale autonoma (20-75 secondi) e descrivilo con dati concreti:
- "tipo_culmine": uno tra battuta, storia_con_finale, rivelazione, reazione_forte, scontro, fatto_sorprendente,
  momento_di_gioco, nessuno. (Un'opinione, un saluto, una descrizione del paesaggio o un ricordo generico = nessuno.)
- "forza_culmine": 1-5 (5 = fa ridere o sorprende davvero; 3 = interessante; 1 = nessun culmine).
- "autonomia": 1-5 (5 = si capisce senza il resto del video; 1 = serve il contesto).
- "chiacchiera_generica": true se è solo commento di passaggio o divagazione.
- "first"/"last": id delle unità dove inizia la premessa e dove finisce il culmine.
- "hook": massimo 12 parole copiate ESATTAMENTE dal testo (la frase più forte).
- "category": funny, rage, epic, fail, reaction, clutch, storytelling, unexpected, gameplay_highlight.
- "reason": una frase in italiano su cosa succede. Usa SOLO il testo, non inventare.

Rispondi SOLO con JSON: {{"tipo_culmine": "...", "forza_culmine": n, "autonomia": n, "chiacchiera_generica": bool,
"first": id_numerico, "last": id_numerico, "hook": "...", "category": "...", "reason": "..."}}
"""


def _cache_key(transcript: Transcript, model: str) -> str:
    h = hashlib.sha256()
    h.update(f"{PROMPT_VERSION}|{model}|".encode())
    for s in transcript.segments:
        h.update(f"{s.start:.2f}{s.text}".encode())
    return h.hexdigest()[:24]


def status() -> dict:
    """Which model will judge clips: the semantic model if installed, else the general LLM model."""
    s = get_settings()
    mode = s.semantic_scoring
    info = {"mode": mode, "model": s.semantic_model or s.llm_model, "available": False}
    if mode == "off":
        info["reason"] = "Analisi semantica disattivata (CLIPNOVA_SEMANTIC_SCORING=off)"
        return info
    try:
        r = httpx.get(f"{s.llm_url}/api/tags", timeout=3)
        names = [m["name"] for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        info["reason"] = f"Ollama non raggiungibile su {s.llm_url}"
        return info
    for candidate in [m for m in (s.semantic_model, s.llm_model) if m]:
        if candidate in names or f"{candidate}:latest" in names:
            info.update(model=candidate, available=True)
            return info
    info["reason"] = f"Nessun modello tra {s.semantic_model}, {s.llm_model} installato in Ollama"
    return info


# One context size for the whole job: Ollama reloads the model when num_ctx changes, and on a 6 GB GPU a reload
# racing the previous instance's unload crashes the runner (CUDA OOM → HTTP 500). Prompts are sized to fit it.
NUM_CTX = 4096
_RETRY_WAIT_S = 3.0


def _generate(client: httpx.Client, model: str, prompt: str, *, temperature: float, keep_alive: str | int,
              timeout: float | None = None) -> dict:
    """POST /api/generate (JSON mode). A 5xx/connection error usually means the llama runner crashed and Ollama is
    restarting it, so retry once after a short pause."""
    body = {"model": model, "prompt": prompt, "stream": False, "format": "json", "think": False,
            "keep_alive": keep_alive, "options": {"temperature": temperature, "num_ctx": NUM_CTX}}
    for attempt in (1, 2):
        try:
            r = client.post(f"{get_settings().llm_url}/api/generate", json=body,
                            **({"timeout": timeout} if timeout else {}))
            r.raise_for_status()
            return json.loads(r.json().get("response", "{}"))
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            retryable = isinstance(e, httpx.TransportError) or e.response.status_code >= 500
            if attempt == 2 or not retryable:
                raise
            log.info("Ollama error (%s), retrying in %.0f s", e, _RETRY_WAIT_S)
            time.sleep(_RETRY_WAIT_S)
    raise AssertionError("unreachable")


def _unload(client: httpx.Client, model: str) -> None:
    """Free the VRAM for Whisper/NVENC right away."""
    try:
        client.post(f"{get_settings().llm_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
    except httpx.HTTPError:
        pass


def _validate(raw: dict, block: list[Unit], bid: int) -> Judgement | None:
    ids = {u.id for u in block}
    try:
        if "forza_culmine" in raw:  # rubric: concrete questions are answered more reliably than a global 1-10 rating
            forza = max(1.0, min(5.0, float(raw.get("forza_culmine", 1))))
            auto = max(1.0, min(5.0, float(raw.get("autonomia", 1))))
            score = (0.6 * forza + 0.4 * auto) * 2
            tipo = str(raw.get("tipo_culmine", "nessuno")).lower()
            if tipo in ("nessuno", "", "none") or raw.get("chiacchiera_generica") in (True, "true", "si", "sì"):
                score = min(score, 3.0)
        else:
            score = float(raw.get("score", 0))
        first, last = int(raw.get("first", block[0].id)), int(raw.get("last", block[-1].id))
    except (TypeError, ValueError):
        return None
    first = first if first in ids else block[0].id
    last = last if last in ids else block[-1].id
    if last < first:
        first, last = last, first
    cat = str(raw.get("category", "")).strip().lower()
    cat = cat if cat in CATEGORIES else "storytelling"
    hook = str(raw.get("hook", "")).strip().strip('"“”')
    block_text = normalize(" ".join(u.text for u in block))
    if hook and normalize(hook) not in block_text:
        hook = ""  # not verbatim → never shown
    return Judgement(block=bid, score=max(0.0, min(10.0, score)), first=first, last=last, category=cat, hook=hook,
                     reason=str(raw.get("reason", ""))[:300], standalone=bool(raw.get("standalone", True)), raw=raw)


def judge_blocks(
    transcript: Transcript, *, game: str, cache_dir: Path | None = None,
    on_progress: Callable[[float, str], None] | None = None, should_cancel: Callable[[], bool] | None = None,
    client: httpx.Client | None = None, model: str | None = None, examples: dict | None = None,
) -> dict:
    """Rate every block with the local LLM. Returns {"units": [...], "judgements": [...], ...} (cached)."""
    s = get_settings()
    model = model or status().get("model") or s.llm_model
    units = build_units(transcript)
    blocks = build_blocks(units)
    key = _cache_key(transcript, model)
    cache = (cache_dir / SEMANTIC_FILE) if cache_dir else None
    if cache and cache.exists():
        try:
            data = json.loads(cache.read_text())
            if data.get("key") == key:
                return data
        except json.JSONDecodeError:
            pass

    own = client is None
    client = client or httpx.Client(timeout=s.llm_timeout_s)
    judgements: list[Judgement] = []
    t0 = time.monotonic()
    failures = 0
    try:
        for bid, block in enumerate(blocks):
            if should_cancel and should_cancel():
                raise InterruptedError
            if block[-1].end - block[0].start < 12 or sum(len(u.text) for u in block) < 80:
                continue
            prev = blocks[bid - 1] if bid else []
            context = ("CONTESTO PRECEDENTE (solo per capire, non selezionabile):\n"
                       + " ".join(u.text for u in prev)[-500:] + "\n\n") if prev else ""
            lines = "\n".join(f"[{u.id}] ({_fmt(u.start)}) {u.text}" for u in block)
            prompt = PROMPT.format(game=game, lang=transcript.language or "it", context=context, lines=lines)
            try:
                raw = _generate(client, model, prompt, temperature=0.2, keep_alive="2m")
                for k in ("first", "last"):
                    if isinstance(raw.get(k), str):
                        raw[k] = re.sub(r"\D", "", raw[k]) or -1
                j = _validate(raw, block, bid)
                if j:
                    judgements.append(j)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                failures += 1
                log.warning("Semantic judge failed on block %d: %s", bid, e)
                if failures >= 3 and not judgements:
                    raise RuntimeError(f"Local LLM not usable: {e}") from e
            if on_progress:
                on_progress((bid + 1) / len(blocks), f"Analisi semantica blocco {bid + 1}/{len(blocks)}")

        data = {"key": key, "model": model, "elapsed_s": round(time.monotonic() - t0, 1),
                "units": [asdict(u) for u in units], "blocks": len(blocks),
                "judgements": [asdict(j) for j in judgements]}
        if on_progress:
            on_progress(0.99, "Classifica dei momenti migliori")
        # same loaded model instance (no unload/reload in between), unloaded once below
        data = rank_candidates(data, game=game, model=model, examples=examples, client=client, unload=False)
    finally:
        _unload(client, model)
        if own:
            client.close()
    data["elapsed_s"] = round(time.monotonic() - t0, 1)
    if cache:
        cache.write_text(json.dumps(data, ensure_ascii=False))
    return data


RANK_PROMPT = """Sei un editor di Shorts/TikTok di gaming per un pubblico italiano. Questi sono {n} momenti candidati
dallo stesso video di {game}. Confrontali TRA LORO e ordinali dal migliore al peggiore come clip verticale autonoma:
premia storie con un finale, battute, rivelazioni, reazioni forti; penalizza chiacchiere, saluti, descrizioni generiche.

{examples}{items}

Rispondi SOLO con JSON: {{"ranking": [id del migliore, ..., id del peggiore], "best_reason": "perché il primo è il migliore"}}
Includi tutti gli id una sola volta."""


def _examples_block(examples: dict | None) -> str:
    if not examples or not examples.get("positive"):
        return ""
    parts = ["GUSTI DEL CREATOR (clip che ha già scelto o scartato: usale come metro di giudizio):"]
    for e in examples["positive"][:5]:
        parts.append(f"+ PIACIUTA: {e['text'][:280]}")
    for e in examples.get("negative", [])[:5]:
        parts.append(f"- SCARTATA: {e['text'][:280]}")
    return "\n".join(parts) + "\n\nCANDIDATI:\n"


RANK_MAX_ITEMS = 30
_CHARS_PER_TOKEN = 3.0  # conservative for Italian with Qwen's tokenizer
_RANK_OUTPUT_TOKENS = 600


def rank_candidates(data: dict, *, game: str, client: httpx.Client | None = None, model: str | None = None,
                    examples: dict | None = None, force: bool = False, unload: bool = True) -> dict:
    """Listwise ranking of all candidates in one call: small models give flat absolute ratings
    (everything 8/10) but compare reliably. Adds "rank" (1 = best) to every judgement."""
    s = get_settings()
    js = data.get("judgements", [])
    sig = (examples or {}).get("signature", "")
    if len(js) < 2 or (not force and all("rank" in j for j in js) and data.get("ranking", {}).get("examples") == sig):
        return data
    model = model or data.get("model") or s.llm_model
    units = {u["id"]: u for u in data.get("units", [])}
    by_score = sorted(range(len(js)), key=lambda k: -js[k]["score"])
    pool = sorted(by_score[:RANK_MAX_ITEMS])  # the weakest beyond the cap keep their score order at the bottom
    examples_txt = _examples_block(examples)
    # fit the prompt in NUM_CTX: shorten each candidate's text instead of growing the context
    fixed = len(RANK_PROMPT) + len(examples_txt) + len(game) + 10 * len(pool)
    budget = int((NUM_CTX - _RANK_OUTPUT_TOKENS) * _CHARS_PER_TOKEN) - fixed
    per_item = max(80, min(420, budget // max(1, len(pool))))
    items = []
    for i in pool:
        j = js[i]
        text = " ".join(units[k]["text"] for k in range(j["first"], j["last"] + 1) if k in units)
        items.append(f"[{i}] {text[:per_item]}")
    prompt = RANK_PROMPT.format(n=len(pool), game=game, items="\n\n".join(items), examples=examples_txt)
    own = client is None
    client = client or httpx.Client(timeout=s.llm_timeout_s)
    try:
        raw = _generate(client, model, prompt, temperature=0.1, keep_alive=0 if unload else "2m",
                        timeout=s.llm_timeout_s * 2)
        order = []
        for x in raw.get("ranking", []):
            try:
                i = int(re.sub(r"\D", "", str(x)))
            except ValueError:
                continue
            if i in pool and i not in order:
                order.append(i)
        order += [i for i in by_score if i not in order]
        for pos, i in enumerate(order, 1):
            js[i]["rank"] = pos
        data["ranking"] = {"best_reason": str(raw.get("best_reason", ""))[:300], "n": len(js), "examples": sig}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("Listwise ranking failed (absolute ratings kept): %s", e)
    finally:
        if own:
            client.close()
    return data


def load_cached(cache_dir: Path) -> dict | None:
    p = cache_dir / SEMANTIC_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
