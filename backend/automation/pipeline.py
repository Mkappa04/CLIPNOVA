"""auto.pipeline job: everything after a watched file is imported, in ONE job.

copy (optional) → metadata → analysis + transcription → clip detection → webcam detection →
render the best N clips (score ≥ min) → Approval Center (status review). Never approves or publishes.
Running as a single job keeps the "one heavy job at a time" rule (Whisper, NVENC, Ollama never overlap).
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from backend.automation.common import notify
from backend.core.config import get_settings
from backend.database.session import session_scope
from backend.editing.config import EditConfig, default_config_for
from backend.models.automation_entities import WatchedFile
from backend.models.entities import Clip, ClipStatus, StorageMode, Video, VideoStatus, new_id
from backend.workers.queue import JobCancelled, SubContext, job_manager

log = logging.getLogger(__name__)

PIPELINE_DEFAULTS = {
    "analyze": True,
    "language": "auto",
    "render_top_n": 3,
    "min_score": 45,
    "detect_webcam": True,
    "edit_config": {},     # partial EditConfig applied to the rendered clips
}


STAGE_LABELS = {"copy": "Copia nel filesystem Linux", "metadata": "Lettura metadati", "analysis": "Analisi e trascrizione",
                "webcam": "Rilevamento webcam", "render": "Render delle migliori clip"}


def pipeline_config(raw: dict | None) -> dict:
    cfg = {**PIPELINE_DEFAULTS, **(raw or {})}
    cfg["render_top_n"] = max(0, min(10, int(cfg["render_top_n"])))
    return cfg


def _stage(wf_id: str, stage: str, reason: str | None = None) -> None:
    with session_scope() as db:
        wf = db.get(WatchedFile, wf_id)
        if wf is not None:
            wf.stage = stage
            wf.reason = reason if reason is not None else STAGE_LABELS.get(stage.split(" ")[0], stage)


@job_manager.register("auto.pipeline")
def auto_pipeline(ctx) -> dict:
    from backend.editing.webcam import detect_webcam
    from backend.services.video_service import copy_with_progress, safe_filename
    from backend.workers.handlers import _probe_video, run_analysis_job, run_render_job

    wf_id = ctx.payload["watched_file_id"]
    with session_scope() as db:
        wf = db.get(WatchedFile, wf_id)
        if wf is None or wf.video_id is None:
            raise RuntimeError("Watched file or video missing")
        video_id, folder = wf.video_id, wf.folder
        cfg = pipeline_config(folder.pipeline)
        mode, game, folder_name = folder.mode, folder.game, folder.name or folder.path
        video = db.get(Video, video_id)
        src = Path(video.file_path)
        needs_copy = mode == "copy" and video.storage_mode == StorageMode.REFERENCED.value

    try:
        if needs_copy:
            _stage(wf_id, "copy")
            dest = get_settings().videos_dir / f"{new_id()[:12]}_{safe_filename(src.name)}"
            try:
                copy_with_progress(src, dest, on_progress=lambda p: ctx.progress(0.05 * p, f"Copia {p:.0%}"),
                                   should_cancel=lambda: ctx.cancelled)
            except InterruptedError as e:
                raise JobCancelled() from e
            with session_scope() as db:
                v = db.get(Video, video_id)
                v.file_path, v.storage_mode = str(dest), StorageMode.COPIED.value

        _stage(wf_id, "metadata")
        _probe_video(SubContext(ctx, 0.05, 0.03, "Metadati: "), video_id)

        result: dict = {"clips_rendered": 0}
        if cfg["analyze"]:
            _stage(wf_id, "analysis")
            res = run_analysis_job(SubContext(ctx, 0.08, 0.52, "Analisi: "), video_id,
                                   {"language": cfg["language"], "transcribe": True})
            result["clips_detected"] = res.get("clips", 0)

            if cfg["detect_webcam"]:
                _stage(wf_id, "webcam")
                ctx.progress(0.61, "Rilevamento webcam", force=True)
                with session_scope() as db:
                    v = db.get(Video, video_id)
                    path, dur, w, h, has_region = Path(v.file_path), v.duration or 0, v.width or 1920, v.height or 1080, \
                        bool(v.webcam_region)
                if not has_region:
                    det = detect_webcam(path, dur, w, h)
                    if det.region is not None:
                        with session_scope() as db:
                            db.get(Video, video_id).webcam_region = det.region.model_dump()
                    result["webcam"] = det.reason

            # pick the best clips and give them the folder's edit settings
            with session_scope() as db:
                v = db.get(Video, video_id)
                clips = db.scalars(select(Clip).where(
                    Clip.video_id == video_id, Clip.status == ClipStatus.DETECTED.value,
                    Clip.score >= cfg["min_score"]).order_by(Clip.score.desc()).limit(cfg["render_top_n"])).all()
                base = default_config_for(bool(v.webcam_region)).model_dump()
                for c in clips:
                    c.edit_config = EditConfig.model_validate({**base, **(cfg["edit_config"] or {})}).model_dump()
                clip_ids = [c.id for c in clips]

            n = len(clip_ids)
            for i, cid in enumerate(clip_ids):
                _stage(wf_id, f"render {i + 1}/{n}")
                ctx.check_cancelled()
                span = 0.37 / max(1, n)
                run_render_job(SubContext(ctx, 0.63 + i * span, span, f"Render {i + 1}/{n}: "), cid)
                result["clips_rendered"] += 1

        with session_scope() as db:
            wf = db.get(WatchedFile, wf_id)
            wf.status, wf.stage = "done", "review" if result["clips_rendered"] else "analyzed"
            if result["clips_rendered"]:
                wf.reason = f"{result['clips_rendered']} clip pronte da revisionare"
                notify(db, f"{result['clips_rendered']} nuove clip da revisionare",
                       f"{Path(src).name} · {game} · {folder_name}", "/approval", kind="review")
            else:
                wf.reason = "Nessuna clip sopra lo score minimo" if cfg["analyze"] else "Importato (analisi disattivata)"
        return {"message": wf_reason_message(result), **result}
    except JobCancelled:
        with session_scope() as db:
            wf = db.get(WatchedFile, wf_id)
            wf.status, wf.reason = "error", "Pipeline annullata"
            v = db.get(Video, video_id)
            if v is not None and v.status == VideoStatus.ANALYZING.value:
                v.status = VideoStatus.READY.value
        raise


def wf_reason_message(result: dict) -> str:
    n = result.get("clips_rendered", 0)
    return f"Pipeline completata: {n} clip in revisione" if n else "Pipeline completata"
