"""Scores for discovered items and creators. Explainable: every score comes with a reason."""

from __future__ import annotations

import math
from datetime import datetime, timezone


def _norm(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    return [0.5 if hi - lo < 1e-9 else (v - lo) / (hi - lo) for v in values]


def _hours_since(iso: str | None) -> float:
    if not iso:
        return 24 * 30
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return max(1.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)


def rank_items(items: list[dict]) -> list[dict]:
    """popularity (views), trend (views/hour since publication), engagement ((likes+comments)/views)."""
    views = [math.log10(1 + (i.get("views") or 0)) for i in items]
    trend = [math.log10(1 + (i.get("views") or 0) / _hours_since(i.get("published_at"))) for i in items]
    eng = [((i.get("likes") or 0) + (i.get("comments") or 0)) / max(1, i.get("views") or 0) for i in items]
    nv, nt, ne = _norm(views), _norm(trend), _norm(eng)
    for i, item in enumerate(items):
        has_eng = item.get("likes") is not None
        score = 0.4 * nv[i] + 0.4 * nt[i] + (0.2 * ne[i] if has_eng else 0.0)
        per_hour = (item.get("views") or 0) / _hours_since(item.get("published_at"))
        parts = [f"{item.get('views') or 0:,} visualizzazioni".replace(",", "."),
                 f"{per_hour:,.0f}/ora dalla pubblicazione".replace(",", ".")]
        if has_eng and item.get("views"):
            parts.append(f"engagement {eng[i]:.1%}")
        item["score"] = round(100 * score, 1)
        item["score_reason"] = " · ".join(parts)
    return sorted(items, key=lambda x: x["score"], reverse=True)


def rank_creators(items: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for it in items:
        key = f"{it['platform']}:{it.get('channel_id') or it.get('creator')}"
        g = groups.setdefault(key, {"platform": it["platform"], "channel_id": it.get("channel_id"),
                                    "name": it.get("creator") or "?", "url": it.get("channel_url"),
                                    "items": 0, "total_views": 0, "languages": set(), "latest": None, "cc_by": 0})
        g["items"] += 1
        g["total_views"] += it.get("views") or 0
        if it.get("language"):
            g["languages"].add(it["language"][:2])
        if it.get("license") == "creativeCommon":
            g["cc_by"] += 1
        if it.get("published_at") and (g["latest"] is None or it["published_at"] > g["latest"]):
            g["latest"] = it["published_at"]
    out = list(groups.values())
    tv = _norm([math.log10(1 + g["total_views"]) for g in out])
    cnt = _norm([g["items"] for g in out])
    rec = _norm([-_hours_since(g["latest"]) for g in out])
    for i, g in enumerate(out):
        g["languages"] = sorted(g["languages"])
        g["score"] = round(100 * (0.5 * tv[i] + 0.3 * cnt[i] + 0.2 * rec[i]), 1)
        g["score_reason"] = (f"{g['items']} contenuti nei risultati · {g['total_views']:,} visualizzazioni totali"
                             .replace(",", "."))
    return sorted(out, key=lambda g: g["score"], reverse=True)
