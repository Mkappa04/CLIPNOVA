"""Learn the user's taste from their own review decisions.

Positive examples: clips the user approved or exported. Negative examples: clips the user rejected.
Two uses:
1. Content affinity (embeddings, deterministic and fast): each candidate is compared with the liked and
   disliked clips; similar to liked → up, similar to disliked → down. Recomputed at every re-score, so
   every approve/reject counts immediately.
2. Few-shot examples for the local-LLM listwise ranking (see semantic.rank_candidates).

Embeddings come from a small local model through Ollama (default embeddinggemma, multilingual).
"""

from __future__ import annotations

import hashlib
import logging
import math

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.entities import Clip

log = logging.getLogger(__name__)

POSITIVE = ("approved", "exported")
NEGATIVE = ("rejected",)
MIN_POSITIVE = 2
_cache: dict[str, list[float]] = {}


def collect_examples(db: Session, limit: int = 8, exclude_ids: set[str] | None = None) -> dict:
    exclude_ids = exclude_ids or set()

    def rows(states):
        stmt = select(Clip).where(Clip.status.in_(states)).order_by(Clip.updated_at.desc()).limit(limit * 3)
        out = []
        for c in db.scalars(stmt):
            text = (c.transcript or "").strip()
            if c.id in exclude_ids or len(text) < 30:
                continue
            out.append({"id": c.id, "text": text[:600], "category": c.category, "title": c.suggested_title})
            if len(out) >= limit:
                break
        return out

    pos, neg = rows(POSITIVE), rows(NEGATIVE)
    sig = hashlib.sha256("|".join(sorted(e["id"] for e in pos + neg)).encode()).hexdigest()[:16]
    return {"positive": pos, "negative": neg, "signature": sig}


def _key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{text}".encode()).hexdigest()


def embed(texts: list[str], client: httpx.Client | None = None) -> list[list[float]] | None:
    s = get_settings()
    model = s.preference_embed_model
    missing = [t for t in dict.fromkeys(texts) if _key(model, t) not in _cache]
    if missing:
        own = client is None
        client = client or httpx.Client(timeout=120)
        try:
            r = client.post(f"{s.llm_url}/api/embed", json={"model": model, "input": missing, "keep_alive": "1m"})
            r.raise_for_status()
            for t, v in zip(missing, r.json()["embeddings"]):
                _cache[_key(model, t)] = v
        except (httpx.HTTPError, ValueError, KeyError) as e:
            log.warning("Embedding with %s failed: %s", model, e)
            return None
        finally:
            if own:
                client.close()
    return [_cache[_key(model, t)] for t in texts]


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def affinity(candidates: list[str], examples: dict, client: httpx.Client | None = None) -> list[float] | None:
    """0..1 per candidate (1 = most like the clips you approved and least like the ones you rejected).
    None when there are not enough examples or the embedding model is unavailable."""
    pos, neg = examples.get("positive", []), examples.get("negative", [])
    if len(pos) < MIN_POSITIVE or not candidates:
        return None
    vecs = embed(candidates + [e["text"] for e in pos] + [e["text"] for e in neg], client)
    if vecs is None:
        return None
    cv, pv, nv = vecs[:len(candidates)], vecs[len(candidates):len(candidates) + len(pos)], vecs[len(candidates) + len(pos):]
    raw = []
    for v in cv:
        # nearest-neighbour similarity: tastes are made of distinct kinds of moments, not one average
        like = max(_cos(v, p) for p in pv)
        dislike = max((_cos(v, n) for n in nv), default=0.0)
        raw.append(like - 0.8 * dislike)
    lo, hi = min(raw), max(raw)
    return [0.5 if hi - lo < 1e-6 else (r - lo) / (hi - lo) for r in raw]


def describe(examples: dict) -> str:
    return f"{len(examples.get('positive', []))} approvate/esportate, {len(examples.get('negative', []))} rifiutate"
