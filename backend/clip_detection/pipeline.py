"""Analysis pipeline: media prep → audio → scenes → motion → transcription → scoring.

Expensive artefacts are cached in data/cache/<video_id>/ so clips can be
re-scored instantly with a different ScoringConfig (no re-analysis).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.clip_detection import audio as audio_mod
from backend.clip_detection import visual
from backend.clip_detection.media_prep import prepare_media
from backend.clip_detection.scoring import DetectedClip, RawSignals, ScoringConfig, Timeline
from backend.core.config import get_settings
from backend.models.entities import Analysis, AnalysisStatus, Clip, ClipStatus, Video
from backend.transcription import whisper_engine
from backend.transcription.whisper_engine import Transcript

log = logging.getLogger(__name__)

SIGNALS_FILE = "signals.npz"
TRANSCRIPT_FILE = "transcript.json"


def cache_dir(video_id: str) -> Path:
    return get_settings().cache_dir / video_id


class Stage:
    """Maps a sub-step's 0..1 progress into a slice of the overall job progress."""

    def __init__(self, report: Callable[[float, str], None], lo: float, hi: float, label: str):
        self.report, self.lo, self.hi, self.label = report, lo, hi, label

    def __call__(self, frac: float, message: str | None = None) -> None:
        self.report(self.lo + (self.hi - self.lo) * max(0.0, min(1.0, frac)), message or self.label)


def run_analysis(
    video: Video, *, language: str | None, transcribe: bool, force: bool, cfg: ScoringConfig,
    report: Callable[[float, str], None], should_cancel: Callable[[], bool],
) -> dict:
    """Heavy part of the analysis (no DB session held). Returns artefact info + stats."""
    s = get_settings()
    src = Path(video.file_path)
    if not src.exists():
        raise FileNotFoundError(f"Source file missing: {src}")
    cdir = cache_dir(video.id)
    timings: dict[str, float] = {}
    duration = float(video.duration or 0)

    t = time.monotonic()
    st = Stage(report, 0.0, 0.25, "Preparazione proxy e audio")
    st(0)
    media = prepare_media(src, cdir, duration=duration or None, has_audio=video.has_audio,
                          on_progress=lambda f: st(f, f"Estrazione proxy/audio ({f:.0%})"),
                          should_cancel=should_cancel, force=force)
    timings["prepare"] = round(time.monotonic() - t, 1)

    ws = s.analysis_window_s
    n_windows = max(1, int(duration / ws)) if duration else 1

    t = time.monotonic()
    st = Stage(report, 0.25, 0.30, "Analisi audio")
    if media.audio is not None:
        feats = audio_mod.analyze_audio(media.audio, ws, on_progress=st, should_cancel=should_cancel)
        n_windows = len(feats.rms_db)
    else:
        feats = audio_mod.empty_features(n_windows, ws)
    timings["audio"] = round(time.monotonic() - t, 1)

    t = time.monotonic()
    st = Stage(report, 0.30, 0.42, "Scene detection (PySceneDetect)")
    scenes = visual.detect_scenes(media.proxy, on_progress=st, should_cancel=should_cancel)
    timings["scenes"] = round(time.monotonic() - t, 1)

    t = time.monotonic()
    st = Stage(report, 0.42, 0.50, "Analisi movimento (OpenCV)")
    motion, flash = visual.motion_activity(media.proxy, ws, n_windows, on_progress=st, should_cancel=should_cancel)
    timings["motion"] = round(time.monotonic() - t, 1)

    np.savez_compressed(
        cdir / SIGNALS_FILE, rms_db=feats.rms_db, excess_db=feats.excess_db, flux=feats.flux,
        centroid=feats.centroid_hz, motion=motion, flash=flash,
        meta=np.array(json.dumps({"window_s": ws, "duration": duration, "has_audio": media.audio is not None})),
    )

    transcript: Transcript | None = None
    tpath = cdir / TRANSCRIPT_FILE
    if transcribe and media.audio is not None:
        t = time.monotonic()
        st = Stage(report, 0.50, 0.85, "Trascrizione (faster-whisper)")
        cached = _load_cached_transcript(tpath, language) if not force else None
        if cached is not None:
            transcript = cached
            st(1.0, "Trascrizione dalla cache")
        else:
            transcript = whisper_engine.transcribe(media.audio, language=language, duration=duration or None,
                                                   on_progress=st, should_cancel=should_cancel)
            tpath.write_text(json.dumps({"requested_language": language or "auto", **transcript.to_dict()},
                                        ensure_ascii=False))
        timings["transcription"] = round(time.monotonic() - t, 1)
    elif tpath.exists() and not transcribe:
        tpath.unlink()

    semantic_info = None
    if transcript is not None and transcript.segments and cfg.use_semantic:
        from backend.clip_detection import semantic

        sstat = semantic.status()
        if sstat["available"]:
            t = time.monotonic()
            st = Stage(report, 0.85, 0.96, "Analisi semantica (LLM locale)")
            st(0, f"Analisi semantica con {sstat['model']}")
            try:
                from backend.clip_detection.preferences import collect_examples
                from backend.database.session import session_scope

                with session_scope() as db:
                    examples = collect_examples(db)
                data = semantic.judge_blocks(transcript, game=video.game, cache_dir=cdir, on_progress=st,
                                             should_cancel=should_cancel, examples=examples)
                semantic_info = {"model": data["model"], "blocks": data["blocks"],
                                 "judged": len(data["judgements"]), "elapsed_s": data["elapsed_s"]}
            except InterruptedError:
                raise
            except Exception as e:  # noqa: BLE001 - semantic pass is an enhancement, never fatal
                log.warning("Semantic analysis failed: %s", e)
                semantic_info = {"error": str(e)[:200]}
            timings["semantic"] = round(time.monotonic() - t, 1)
        else:
            semantic_info = {"skipped": sstat.get("reason", "LLM non disponibile")}

    report(0.97, "Scoring delle clip")
    return {
        "semantic": semantic_info,
        "decoder": media.decoder, "media_cached": media.cached, "scenes": scenes, "timings": timings,
        "audio_stats": feats.stats, "transcript": transcript,
    }


def _load_cached_transcript(path: Path, language: str | None) -> Transcript | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if data.pop("requested_language", "auto") != (language or "auto"):
            return None
        return Transcript.from_dict(data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def load_transcript(video_id: str) -> Transcript | None:
    path = cache_dir(video_id) / TRANSCRIPT_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    data.pop("requested_language", None)
    return Transcript.from_dict(data)


def load_raw(video_id: str, scenes: list[float]) -> RawSignals:
    path = cache_dir(video_id) / SIGNALS_FILE
    if not path.exists():
        raise FileNotFoundError("Analysis cache missing: run the analysis again")
    with np.load(path) as z:
        meta = json.loads(str(z["meta"]))
        return RawSignals(window_s=meta["window_s"], duration=meta["duration"], rms_db=z["rms_db"],
                          excess_db=z["excess_db"], flux=z["flux"], motion=z["motion"], flash=z["flash"],
                          scenes=list(scenes), has_audio=meta["has_audio"])


def with_preferences(sem: dict | None, examples: dict | None) -> dict | None:
    """Annotate semantic candidates with their affinity to the user's approved/rejected clips."""
    from backend.clip_detection import preferences

    if not sem or not sem.get("judgements") or not examples:
        return sem
    units = {u["id"]: u for u in sem.get("units", [])}
    texts = [" ".join(units[k]["text"] for k in range(j["first"], j["last"] + 1) if k in units)
             for j in sem["judgements"]]
    aff = preferences.affinity(texts, examples)
    if aff is not None:
        for j, a in zip(sem["judgements"], aff):
            j["pref"] = round(a, 3)
        sem["preferences"] = preferences.describe(examples)
    return sem


def score_video(video: Video, analysis: Analysis, cfg: ScoringConfig,
                examples: dict | None = None) -> tuple[Timeline, list[DetectedClip]]:
    from backend.clip_detection import semantic
    from backend.clip_detection.scoring import hybrid_clips

    raw = load_raw(video.id, analysis.scenes or [])
    if not raw.duration:
        raw.duration = float(video.duration or len(raw.rms_db) * raw.window_s)
    sem = semantic.load_cached(cache_dir(video.id))
    if cfg.use_semantic and examples is None and sem:
        from sqlalchemy.orm import object_session

        from backend.clip_detection.preferences import collect_examples

        db = object_session(video)
        examples = collect_examples(db) if db is not None else None
    sem = with_preferences(sem, examples) if cfg.use_semantic else sem
    return hybrid_clips(raw, load_transcript(video.id), video.game, cfg, sem)


def replace_detected_clips(db: Session, video: Video, detected: list[DetectedClip], language: str) -> list[Clip]:
    """Replace auto-detected clips that the user has not touched; keep reviewed/manual ones."""
    existing = db.scalars(select(Clip).where(Clip.video_id == video.id)).all()
    kept = []
    for c in existing:
        if c.origin == "auto" and c.status == ClipStatus.DETECTED.value and not c.renders and not c.subtitles \
                and not c.edit_config:
            if c.preview_path:
                Path(c.preview_path).unlink(missing_ok=True)
            db.delete(c)
        else:
            kept.append(c)

    def overlaps(d: DetectedClip) -> bool:
        for k in kept:
            inter = min(d.end, k.end) - max(d.start, k.start)
            if inter > 0.5 * min(d.duration, k.end - k.start):
                return True
        return False

    created = []
    for d in detected:
        if overlaps(d):
            continue
        clip = Clip(video_id=video.id, start=d.start, end=d.end, category=d.category, score=d.score,
                    confidence=d.confidence, transcript=d.transcript, reason=d.reason,
                    suggested_title=d.suggested_title, origin="auto", peak_time=d.peak_time, language=language,
                    signals=d.signals, category_scores=d.category_scores, keywords=d.keywords)
        db.add(clip)
        created.append(clip)
    db.flush()
    return created


def timeline_payload(tl: Timeline, max_points: int = 1200) -> dict:
    """Downsample timeline curves for the UI chart (max-pooling keeps peaks visible)."""
    n = len(tl.interest)
    step = max(1, int(np.ceil(n / max_points)))

    def pool(x: np.ndarray) -> list[float]:
        pad = (-len(x)) % step
        xp = np.pad(x, (0, pad), constant_values=0)
        return [round(float(v), 3) for v in xp.reshape(-1, step).max(axis=1)]

    return {
        "step_s": tl.window_s * step,
        "interest": pool(tl.interest),
        "audio": pool(tl.features["audio_energy"]),
        "speech": pool(tl.features["speech"]),
        "motion": pool(tl.features["visual_motion"]),
        "scenes": tl.scenes,
        "laughs": [round(t, 2) for t in tl.laughs],
        "keywords": [{"time": round(h.time, 2), "category": h.category, "keyword": h.keyword} for h in tl.hits],
    }


def get_or_create_analysis(db: Session, video: Video) -> Analysis:
    analysis = db.scalar(select(Analysis).where(Analysis.video_id == video.id))
    if analysis is None:
        analysis = Analysis(video_id=video.id, status=AnalysisStatus.RUNNING.value)
        db.add(analysis)
        db.flush()
    return analysis
