from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.clip_detection import pipeline
from backend.clip_detection.lexicon import CATEGORY_KEYWORDS, GAME_KEYWORDS
from backend.clip_detection.scoring import CATEGORIES, LABELS, ScoringConfig
from backend.core.config import get_settings
from backend.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.models.entities import ACTIVE_JOB_STATUSES, AnalysisStatus, Job, VideoStatus
from backend.models.schemas import AnalysisOut, AnalyzeRequest, ClipOut
from backend.services import video_service as vs
from backend.transcription.whisper_engine import to_srt
from backend.workers.queue import job_manager

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/scoring/defaults")
def scoring_defaults() -> dict:
    return {
        "config": ScoringConfig().model_dump(),
        "weights_help": {k: f.description for k, f in ScoringConfig.model_fields["weights"].annotation.model_fields.items()},
        "categories": [{"id": c, "label_it": LABELS["it"][c], "label_en": LABELS["en"][c]} for c in CATEGORIES],
        "lexicon_sizes": {**{k: len(v) for k, v in CATEGORY_KEYWORDS.items()},
                          **{f"game:{k}": len(v) for k, v in GAME_KEYWORDS.items()}},
    }


@router.post("/videos/{video_id}/analyze", status_code=202)
def start_analysis(video_id: str, body: AnalyzeRequest, db: Session = Depends(get_db)) -> dict:
    video = vs.get_video(db, video_id)
    if video.status not in (VideoStatus.READY.value, VideoStatus.ANALYZED.value):
        raise ValidationFailed(f"Video is '{video.status}': it must be 'ready' (metadata read) before analysis")
    active = db.scalar(select(func.count(Job.id)).where(
        Job.video_id == video_id, Job.type == "video.analyze", Job.status.in_(ACTIVE_JOB_STATUSES)))
    if active:
        raise ConflictError("An analysis for this video is already queued or running")
    payload = {"video_id": video_id, "language": body.language, "transcribe": body.transcribe,
               "force": body.force, "scoring": body.scoring.model_dump() if body.scoring else None}
    return {"job_id": job_manager.submit("video.analyze", payload, video_id=video_id)}


@router.get("/videos/{video_id}/analysis")
def get_analysis(video_id: str, timeline: bool = True, db: Session = Depends(get_db)) -> dict:
    video = vs.get_video(db, video_id)
    analysis = video.analysis
    if analysis is None:
        return {"analysis": None, "timeline": None}
    out = {"analysis": AnalysisOut.model_validate(analysis).model_dump(mode="json"), "timeline": None}
    if timeline and analysis.status == AnalysisStatus.COMPLETED.value:
        try:
            cfg = ScoringConfig.model_validate(analysis.config or {})
            tl, _ = pipeline.score_video(video, analysis, cfg)
            out["timeline"] = pipeline.timeline_payload(tl)
        except FileNotFoundError:
            out["timeline"] = None
    return out


@router.get("/videos/{video_id}/transcript")
def get_transcript(video_id: str, format: str = Query("json", pattern="^(json|srt|txt)$"),
                   db: Session = Depends(get_db)):
    vs.get_video(db, video_id)
    transcript = pipeline.load_transcript(video_id)
    if transcript is None:
        raise NotFoundError("No transcript: run the analysis with transcription enabled")
    if format == "srt":
        return PlainTextResponse(to_srt(transcript), media_type="application/x-subrip",
                                 headers={"Content-Disposition": f'attachment; filename="{video_id}.srt"'})
    if format == "txt":
        return PlainTextResponse(transcript.text)
    return transcript.to_dict()


@router.post("/videos/{video_id}/detect", response_model=list[ClipOut])
def rescore(video_id: str, cfg: ScoringConfig, db: Session = Depends(get_db)):
    """Re-run clip scoring on cached analysis data with a new configuration (fast, no re-analysis)."""
    video = vs.get_video(db, video_id)
    analysis = video.analysis
    if analysis is None or analysis.status != AnalysisStatus.COMPLETED.value:
        raise ValidationFailed("Run the analysis first")
    try:
        _tl, detected = pipeline.score_video(video, analysis, cfg)
    except FileNotFoundError as e:
        raise ValidationFailed(str(e)) from e
    pipeline.replace_detected_clips(db, video, detected, analysis.language)
    analysis.config = cfg.model_dump()
    db.commit()
    from backend.api.routers.clips import clip_out

    return [clip_out(c) for c in sorted(video.clips, key=lambda c: c.start)]


@router.post("/videos/{video_id}/rerank", response_model=list[ClipOut])
def rerank(video_id: str, db: Session = Depends(get_db)):
    """Re-run the local-LLM comparison using your latest approved/rejected clips as examples, then re-score."""
    from backend.clip_detection import semantic
    from backend.clip_detection.preferences import collect_examples

    video = vs.get_video(db, video_id)
    analysis = video.analysis
    sem = semantic.load_cached(pipeline.cache_dir(video_id))
    if analysis is None or analysis.status != AnalysisStatus.COMPLETED.value or not sem:
        raise ValidationFailed("Serve un'analisi completata con l'analisi semantica (LLM locale)")
    if not semantic.status()["available"]:
        raise ValidationFailed("LLM locale non disponibile")
    import json as _json

    examples = collect_examples(db)
    sem = semantic.rank_candidates(sem, game=video.game, examples=examples, force=True)
    (pipeline.cache_dir(video_id) / semantic.SEMANTIC_FILE).write_text(_json.dumps(sem, ensure_ascii=False))
    cfg = ScoringConfig.model_validate(analysis.config or {})
    _tl, detected = pipeline.score_video(video, analysis, cfg, examples=examples)
    pipeline.replace_detected_clips(db, video, detected, analysis.language)
    db.commit()
    from backend.api.routers.clips import clip_out

    return [clip_out(c) for c in sorted(video.clips, key=lambda c: c.start)]


@router.get("/preferences")
def preferences_status(db: Session = Depends(get_db)) -> dict:
    from backend.clip_detection.preferences import MIN_POSITIVE, collect_examples

    ex = collect_examples(db)
    return {"positive": len(ex["positive"]), "negative": len(ex["negative"]), "min_positive": MIN_POSITIVE,
            "active": len(ex["positive"]) >= MIN_POSITIVE, "model": get_settings().preference_embed_model}
