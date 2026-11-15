"""Production analytics (all local data)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.timeutil import utcnow
from backend.database.session import get_db
from backend.models.automation_entities import WatchedFile
from backend.models.entities import Analysis, Clip, Export, Publication, Render, Video
from backend.services.system import dir_size_cached

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _day(d) -> str:
    return d.date().isoformat()


@router.get("")
def analytics(days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)) -> dict:
    now = utcnow()
    since = now - timedelta(days=days)
    s = get_settings()

    # --- daily throughput
    series = {(since + timedelta(days=i + 1)).date().isoformat(): {"videos": 0, "renders": 0, "approved": 0}
              for i in range(days)}
    for (created,) in db.execute(select(Video.created_at).where(Video.created_at >= since)):
        series.setdefault(_day(created), {"videos": 0, "renders": 0, "approved": 0})["videos"] += 1
    for (finished,) in db.execute(select(Render.finished_at).where(Render.status == "completed",
                                                                   Render.finished_at >= since)):
        series.setdefault(_day(finished), {"videos": 0, "renders": 0, "approved": 0})["renders"] += 1
    for (approved,) in db.execute(select(Clip.approved_at).where(Clip.approved_at >= since)):
        series.setdefault(_day(approved), {"videos": 0, "renders": 0, "approved": 0})["approved"] += 1
    daily = [{"day": d, **v} for d, v in sorted(series.items())][-days:]

    # --- workflow funnel (all time)
    total_clips = db.scalar(select(func.count(Clip.id))) or 0
    rendered = db.scalar(select(func.count(func.distinct(Render.clip_id))).where(Render.status == "completed")) or 0
    approved = db.scalar(select(func.count(Clip.id)).where(Clip.status.in_(["approved", "exported"]))) or 0
    exported = db.scalar(select(func.count(func.distinct(Export.clip_id)))) or 0
    published = db.scalar(select(func.count(Publication.id)).where(Publication.status == "published")) or 0
    rejected = db.scalar(select(func.count(Clip.id)).where(Clip.status == "rejected")) or 0
    funnel = [{"stage": "detected", "count": total_clips}, {"stage": "rendered", "count": rendered},
              {"stage": "approved", "count": approved}, {"stage": "exported", "count": exported},
              {"stage": "published", "count": published}]

    # --- categories
    cat_rows = db.execute(select(Clip.category, func.count(), func.avg(Clip.score),
                                 func.sum(func.iif(Clip.status.in_(["approved", "exported"]), 1, 0)))
                          .group_by(Clip.category)).all()
    categories = sorted([{"category": c, "count": n, "avg_score": round(a or 0, 1), "approved": int(ap or 0)}
                         for c, n, a, ap in cat_rows], key=lambda x: -x["count"])
    scores = [sc for (sc,) in db.execute(select(Clip.score).where(Clip.origin == "auto"))]
    hist = Counter(min(9, int(sc // 10)) for sc in scores)
    score_hist = [{"bucket": f"{b * 10}-{b * 10 + 9 if b < 9 else 100}", "count": hist.get(b, 0)} for b in range(10)]

    # --- performance
    an_rows = db.execute(select(Analysis.stats, Video.duration, Analysis.transcription_device)
                         .join(Video, Video.id == Analysis.video_id).where(Analysis.status == "completed")).all()
    per_min, devices = [], Counter()
    stage_tot: dict[str, float] = defaultdict(float)
    stage_n = 0
    for stats, dur, dev in an_rows:
        t = (stats or {}).get("timings") or {}
        if dur and t and not (stats or {}).get("media_cached"):
            per_min.append(sum(t.values()) / (dur / 60))
            for k, v in t.items():
                stage_tot[k] += v / (dur / 60)
            stage_n += 1
        devices[dev or "off"] += 1
    rn = db.execute(select(Render.stats).where(Render.status == "completed")).all()
    speeds = [r[0].get("speed_x") for r in rn if r[0] and r[0].get("speed_x")]
    encoders = Counter(r[0].get("encoder", "?") for r in rn if r[0])
    perf = {
        "analysis_s_per_video_min": round(sum(per_min) / len(per_min), 1) if per_min else None,
        "analysis_stages_s_per_min": {k: round(v / stage_n, 2) for k, v in stage_tot.items()} if stage_n else {},
        "analyses": len(an_rows), "transcription_devices": dict(devices),
        "render_speed_x": round(sum(speeds) / len(speeds), 2) if speeds else None,
        "renders": len(rn), "encoders": dict(encoders),
    }

    # --- automation
    wf = db.execute(select(WatchedFile.status, WatchedFile.first_seen_at, WatchedFile.updated_at)).all()
    lead = [(u - f).total_seconds() for st, f, u in wf if st == "done" and u and f]
    automation = {"by_status": dict(Counter(st for st, _, _ in wf)),
                  "avg_minutes_to_review": round(sum(lead) / len(lead) / 60, 1) if lead else None}

    # --- library & storage
    by_game = dict(db.execute(select(Video.game, func.count()).group_by(Video.game)).all())
    total_minutes = round((db.scalar(select(func.coalesce(func.sum(Video.duration), 0.0))) or 0) / 60, 1)
    areas = {"videos": s.videos_dir, "cache": s.cache_dir, "renders": s.renders_dir, "exports": s.exports_dir,
             "previews": s.previews_dir, "models": s.models_dir, "logs": s.logs_dir}
    storage = [{"area": k, "bytes": dir_size_cached(Path(p))} for k, p in areas.items()]
    db_file = s.data_dir / "clipnova.db"
    storage.append({"area": "database", "bytes": db_file.stat().st_size if db_file.exists() else 0})
    storage.sort(key=lambda x: -x["bytes"])

    return {
        "days": days, "daily": daily, "funnel": funnel, "rejected": rejected, "categories": categories,
        "score_hist": score_hist, "performance": perf, "automation": automation,
        "library": {"videos": db.scalar(select(func.count(Video.id))) or 0, "minutes": total_minutes, "by_game": by_game},
        "storage": storage,
        "kpi": {"clips": total_clips, "approval_rate": round(approved / rendered, 3) if rendered else None,
                "renders_in_period": sum(d["renders"] for d in daily), "videos_in_period": sum(d["videos"] for d in daily)},
    }
