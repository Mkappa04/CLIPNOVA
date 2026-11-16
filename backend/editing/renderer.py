"""Vertical clip renderer.

  AI Editing Planner (planner.py: where to zoom / emphasise / add a sound / keep a pause, or nothing)
  → FFmpeg decode (rawvideo BGR) → Python/OpenCV compositor (layout, subject tracking, planned zooms,
  flash/shake, transitions, intro/outro) → FFmpeg encode (Brand Kit logo overlay, ASS subtitles via
  libass, audio chain: silence cuts, high-pass, optional denoise, compressor, loudnorm, SFX mix + limiter)
  → H.264 (NVENC, libx264 fallback on CPU) + AAC, 1080x1920 MP4.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from backend.clip_detection.pipeline import SIGNALS_FILE, cache_dir, load_transcript
from backend.core.config import get_settings
from backend.core.exceptions import MediaError
from backend.editing.compositor import Compositor, blend, card_from
from backend.clip_detection.lexicon import normalize
from backend.editing import planner as planner_mod
from backend.editing.config import LAYOUT_NEEDS_WEBCAM, OUT_H, OUT_W, EditConfig, Region
from backend.editing.effects import mix_filters
from backend.editing.frames import FrameReader, grab_frame, scaled_size
from backend.editing.logo_overlay import LogoPlacement, overlay_filter
from backend.editing.planner import EditPlan, PlannerInput
from backend.editing.presets import get_preset as get_edit_preset
from backend.editing.reframe import CameraPath, camera_path, face_track, faces_path
from backend.editing.timeline import Segment, compute_segments, cut_points, map_interval, map_time, output_duration
from backend.services import ffmpeg
from backend.subtitles.ass import build_ass, build_srt
from backend.subtitles.cues import build_cues, clip_words, validate_cues
from backend.subtitles.presets import FONTS_DIR, get_preset

log = logging.getLogger(__name__)

QUALITY = {
    "draft": {"cq": 28, "maxrate": "4M", "crf": 26, "x264": "ultrafast"},
    "standard": {"cq": 23, "maxrate": "8M", "crf": 21, "x264": "veryfast"},
    "high": {"cq": 19, "maxrate": "14M", "crf": 18, "x264": "medium"},
}


class RenderCancelled(Exception):
    pass


@dataclass
class ClipSource:
    """Everything the renderer needs, detached from the DB session."""

    clip_id: str
    video_id: str
    src: Path
    start: float
    end: float
    peak_time: float | None
    title: str
    width: int
    height: int
    has_audio: bool
    webcam: Region | None
    subtitles: list[dict] | None
    config: EditConfig
    fps: int = 30                       # resolved output fps (EditConfig.fps "auto" → source rate)
    category: str = ""
    game: str = ""
    hook: str = ""                      # verbatim key line (semantic analysis), if any
    stored_plan: dict | None = None     # Clip.edit_plan, reused while its key matches
    logo: LogoPlacement | None = None   # Brand Kit logo (None = no logo)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class RenderPlan:
    cfg: EditConfig
    layout: str
    segments: list[Segment]
    cues: list[dict]                 # output-timeline cues (intro offset applied)
    ass: str
    srt: str
    intro: float
    outro: float
    body: float
    edit: EditPlan                   # AI editing plan (clip-relative source times)
    sfx: list[tuple[float, str, float]] = field(default_factory=list)  # (output time, category, volume)
    warnings: list[str] = field(default_factory=list)
    tracking: str = "center"

    @property
    def zoom_peaks(self) -> list[float]:
        return [round(s.start, 2) for s in self.edit.segments if s.effect.endswith("zoom")]

    @property
    def total(self) -> float:
        return self.intro + self.body + self.outro


# ----------------------------------------------------------------- planning
def _signals(video_id: str) -> tuple[np.ndarray | None, np.ndarray | None, float]:
    sig = _all_signals(video_id)
    return sig.get("rms_db"), sig.get("excess_db"), sig.get("window_s", 0.5)


def _all_signals(video_id: str) -> dict:
    path = cache_dir(video_id) / SIGNALS_FILE
    if not path.exists():
        return {"window_s": 0.5}
    with np.load(path) as z:
        meta = json.loads(str(z["meta"]))
        out = {k: z[k].copy() for k in z.files if k != "meta"}
    out["window_s"] = float(meta["window_s"])
    return out


def planner_input(cs: ClipSource) -> PlannerInput:
    """Everything the planner looks at: words, audio/visual signals of the clip window, peak, hook."""
    transcript = load_transcript(cs.video_id)
    words = clip_words(transcript, cs.start, cs.end)  # clip-relative
    sig = _all_signals(cs.video_id)
    ws = float(sig.get("window_s", 0.5))
    i0, i1 = int(cs.start / ws), int(np.ceil(cs.end / ws))

    def sl(k):
        a = sig.get(k)
        return None if a is None else a[i0:i1].astype(np.float64)

    counts: dict[str, int] = {}
    total = 0
    if transcript is not None:
        for seg in transcript.segments:
            for w in seg.words or []:
                tok = normalize(w.word)
                if tok:
                    counts[tok] = counts.get(tok, 0) + 1
                    total += 1
    return PlannerInput(
        duration=cs.duration, words=words, window_s=ws, rms_db=sl("rms_db"), excess_db=sl("excess_db"),
        motion=sl("motion"), flash=sl("flash"),
        peak=(cs.peak_time - cs.start) if cs.peak_time is not None and cs.start <= cs.peak_time <= cs.end else None,
        category=cs.category, game=cs.game, language=transcript.language if transcript else "",
        hook=cs.hook, word_counts=counts, total_words=total)


def get_plan(cs: ClipSource, *, allow_llm: bool = True) -> EditPlan:
    """The stored plan if it still matches this clip + config, else a new one (rules only if not allow_llm)."""
    inp = planner_input(cs)
    key = planner_mod.plan_key(inp, cs.config)
    if cs.stored_plan and cs.stored_plan.get("key") == key:
        try:
            return EditPlan.model_validate(cs.stored_plan)
        except ValueError:
            pass
    cfg = cs.config if allow_llm else cs.config.model_copy(update={"planner": "rules"})
    plan = planner_mod.make_plan(inp, cfg)
    plan.key = key
    return plan


def source_cues(cs: ClipSource) -> list[dict]:
    """Clip-relative cues: user-edited ones if present, else built from the transcript."""
    if cs.subtitles is not None:
        return validate_cues(cs.subtitles, cs.duration)
    style = get_preset(cs.config.subtitle_preset)
    words = clip_words(load_transcript(cs.video_id), cs.start, cs.end)
    return build_cues(words, max_words=style.max_words, max_chars=style.max_chars, max_lines=style.max_lines)


def plan_render(cs: ClipSource, divider_y: int | None = None, edit: EditPlan | None = None) -> RenderPlan:
    cfg = cs.config
    warnings: list[str] = []
    layout = cfg.layout
    if layout in LAYOUT_NEEDS_WEBCAM and cs.webcam is None:
        warnings.append(f"Layout '{layout}' richiede la regione webcam: uso 'full'")
        layout = "full"
    fps = cs.fps
    if edit is None:
        edit = get_plan(cs, allow_llm=False)

    transcript = load_transcript(cs.video_id)
    words_abs = clip_words(transcript, cs.start, cs.end)
    rms, excess, ws = _signals(cs.video_id)
    segments = compute_segments(
        cs.duration, fps, words=[(w["start"], w["end"]) for w in words_abs], rms_db=rms, window_s=ws,
        rms_offset=cs.start, remove_silences=cfg.remove_silences, strategy=cfg.silence_strategy,
        min_silence_s=cfg.min_silence_s, padding_s=cfg.silence_padding_s, keep=edit.kept_pauses())
    if cfg.remove_silences and not words_abs:
        warnings.append("Riduzione silenzi non applicata: nessuna trascrizione per questa clip")
    body = output_duration(segments)
    intro = cfg.intro_duration if cfg.intro else 0.0
    outro = cfg.outro_duration if cfg.outro else 0.0

    # Subtitles → output timeline
    out_cues: list[dict] = []
    emph = [(e.start, e.end) for e in edit.emphasis] if cfg.caption_emphasis else []
    if cfg.subtitles:
        for cue in source_cues(cs):
            iv = map_interval(cue["start"], cue["end"], segments)
            if iv is None or iv[1] - iv[0] < 0.05:
                continue
            words = []
            for w in cue.get("words", []):
                m = map_interval(w["start"], w["end"], segments)
                if m is not None:
                    is_emph = any(min(w["end"], b) - max(w["start"], a) > 0.02 for a, b in emph)
                    words.append({"start": m[0] + intro, "end": m[1] + intro, "word": w["word"], "emph": is_emph})
            out_cues.append({"start": iv[0] + intro, "end": iv[1] + intro, "text": cue["text"], "words": words})
    style = get_preset(cfg.subtitle_preset)
    titles = []
    if intro:
        titles.append((0.0, intro, cfg.intro_text.strip() or cs.title))
    if outro:
        titles.append((intro + body, intro + body + outro, cfg.outro_text))
    ass = build_ass(out_cues, style, position=cfg.subtitle_position, divider_y=divider_y,
                    highlight=cfg.highlight_words, scale=cfg.subtitle_scale, titles=titles)

    # Sound effects → output timeline (a sound whose instant was cut is dropped)
    sfx: list[tuple[float, str, float]] = []
    if cfg.sfx and cs.has_audio:
        for cue in edit.sfx_cues():
            t_out = map_time(cue.at, segments)
            if t_out is not None and cue.volume > 0:
                sfx.append((round(t_out + intro, 3), cue.category, cue.volume))
    elif cfg.sfx and not cs.has_audio:
        warnings.append("Effetti sonori non applicati: il video non ha audio")
    del excess
    if cs.logo is not None:
        warnings += cs.logo.warnings
    return RenderPlan(cfg.model_copy(update={"layout": layout}), layout, segments, out_cues, ass,
                      build_srt(out_cues), intro, outro, body, edit, sfx, warnings)


def subject_path(cs: ClipSource, plan: RenderPlan, decoded_w: int, decoded_h: int) -> tuple[CameraPath, str]:
    """Smart crop path: faces (speaker framing) and/or on-screen action, with safe fallbacks.
    Returns (path, what is tracked: faces | action | center)."""
    cfg = plan.cfg
    if cfg.crop_mode != "smart":
        return CameraPath.fixed(), "center"
    box_h = OUT_H * (cfg.stack_ratio if plan.layout == "stack" else 0.5 if plan.layout == "split" else 1.0)
    crop_w_norm = min(1.0, (decoded_h * OUT_W / box_h) / decoded_w)
    if crop_w_norm >= 0.999:
        return CameraPath.fixed(), "center"
    policy = get_edit_preset(cfg.preset).policy
    speed = policy.camera_max_speed * cfg.follow_speed
    if cfg.subject in ("faces", "auto") and plan.layout == "full":
        try:
            times, faces, grays = face_track(cs.src, cs.start, cs.end, cs.width, cs.height)
            path = faces_path(times, faces, grays, crop_w_norm=crop_w_norm,
                              dead_zone=max(policy.camera_dead_zone, 0.04), max_speed=speed)
            if path is not None:
                return path, "faces"
            if cfg.subject == "faces":
                plan.warnings.append("Volti non rilevati in modo affidabile: seguo l'azione")
        except Exception as e:  # noqa: BLE001 - tracking is best effort
            log.warning("Face tracking failed (%s)", e)
            plan.warnings.append("Tracking dei volti non riuscito: seguo l'azione")
    proxy = cache_dir(cs.video_id) / "proxy.mp4"
    if not proxy.exists():
        plan.warnings.append("Smart crop richiede l'analisi del video: uso il crop centrale")
        return CameraPath.fixed(), "center"
    try:
        path = camera_path(proxy, cs.start, cs.end, crop_w_norm=crop_w_norm, exclude=cs.webcam,
                           dead_zone=policy.camera_dead_zone, max_speed=speed)
        return path, "action"
    except Exception as e:  # noqa: BLE001 - fall back to centred crop
        log.warning("Smart crop path failed (%s); using centre", e)
        plan.warnings.append("Smart crop non disponibile (analisi mancante): crop centrale")
        return CameraPath.fixed(), "center"


def make_compositor(cs: ClipSource, plan: RenderPlan, decoded_w: int, decoded_h: int,
                    path: CameraPath | None = None) -> Compositor:
    cfg = plan.cfg
    webcam = cs.webcam if plan.layout != "full" else None
    if path is None:
        path, plan.tracking = subject_path(cs, plan, decoded_w, decoded_h)
    edit = plan.edit
    return Compositor(cfg, decoded_w, decoded_h, webcam=webcam, path=path,
                      zoom_fn=lambda t: planner_mod.zoom_envelope(edit, t))


def post_effects(img: np.ndarray, edit: EditPlan, t_src: float) -> np.ndarray:
    """Planned flash / shake on the composed frame (no-ops outside their segments)."""
    dx, dy = planner_mod.shake_offset(edit, t_src)
    if dx or dy:
        M = np.float32([[1.03, 0, dx - OUT_W * 0.015], [0, 1.03, dy - OUT_H * 0.015]])
        img = cv2.warpAffine(img, M, (OUT_W, OUT_H), borderMode=cv2.BORDER_REPLICATE)
    a = planner_mod.flash_amount(edit, t_src)
    if a > 0.01:
        img = cv2.addWeighted(img, 1 - a, np.full_like(img, 255), a, 0)
    return img


# ----------------------------------------------------------------- encode
def _escape_filter_path(p: Path) -> str:
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _pre_chain(cs: ClipSource, plan: RenderPlan) -> list[str]:
    """Audio filters applied before loudness normalisation (silence cuts, cleanup, compression)."""
    cfg = plan.cfg
    parts = []
    if len(plan.segments) > 1 or plan.segments[0].start > 0 or abs(plan.segments[0].end - cs.duration) > 0.05:
        expr = "+".join(f"between(t,{s.start:.4f},{s.end - 1e-4:.4f})" for s in plan.segments)
        parts += [f"aselect='{expr}'", "asetpts=N/SR/TB"]
    parts += ["aresample=48000", "aformat=channel_layouts=stereo", "highpass=f=70"]
    if cfg.denoise:
        parts.append("afftdn=nf=-25")
    if cfg.normalize_audio:
        parts.append("acompressor=threshold=-20dB:ratio=3:attack=5:release=150:makeup=2")
    return parts


def measure_loudness(cs: ClipSource, plan: RenderPlan) -> dict | None:
    """First loudnorm pass (audio only, fast): returns measured values for linear normalisation."""
    s = get_settings()
    chain = ",".join(_pre_chain(cs, plan) + [f"loudnorm=I={plan.cfg.target_lufs}:TP=-1.5:LRA=20:print_format=json"])
    cmd = [s.ffmpeg_bin, "-hide_banner", "-nostdin", "-nostats", "-ss", f"{cs.start:.3f}", "-t", f"{cs.duration:.3f}",
           "-i", str(cs.src), "-vn", "-af", chain, "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        text = proc.stderr
        data = json.loads(text[text.rindex("{"): text.rindex("}") + 1])
        if any(data.get(k) in (None, "-inf", "inf") for k in ("input_i", "input_tp", "input_lra", "input_thresh")):
            return None
        return data
    except (ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        log.warning("Loudness measurement failed: %s", e)
        return None


def _audio_filter(cs: ClipSource, plan: RenderPlan, measured: dict | None = None, out: str = "a") -> str:
    cfg = plan.cfg
    parts = _pre_chain(cs, plan)
    if cfg.normalize_audio:
        if measured:
            parts.append(f"loudnorm=I={cfg.target_lufs}:TP=-1.5:LRA=20:measured_I={measured['input_i']}:"
                         f"measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}:"
                         f"measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true")
        else:
            parts.append(f"loudnorm=I={cfg.target_lufs}:TP=-1.5:LRA=11")
        parts.append("aresample=48000")
    if cfg.transitions:
        parts.append("afade=t=in:st=0:d=0.15")
        parts.append(f"afade=t=out:st={max(0.0, plan.body - 0.3):.3f}:d=0.3")
    if plan.intro:
        ms = int(plan.intro * 1000)
        parts.append(f"adelay={ms}|{ms}")
    parts.append(f"apad=whole_dur={plan.total:.3f}")
    return f"[1:a]{','.join(parts)}[{out}]"


def _encoder_args(cfg: EditConfig, use_nvenc: bool) -> list[str]:
    q = QUALITY[cfg.quality]
    if use_nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(q["cq"]),
                "-b:v", "0", "-maxrate", q["maxrate"], "-bufsize", q["maxrate"].replace("M", "") + "M",
                "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", q["x264"], "-crf", str(q["crf"]), "-maxrate", q["maxrate"],
            "-bufsize", str(int(q["maxrate"][:-1]) * 2) + "M", "-profile:v", "high"]


def render(
    cs: ClipSource, out_dir: Path, *, on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None, edit: EditPlan | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = cs.config
    dw, dh = scaled_size(cs.width, cs.height)
    probe_comp = Compositor(cfg.model_copy(update={"layout": cfg.layout if cs.webcam else "full"}),
                            dw, dh, webcam=cs.webcam, path=CameraPath.fixed(), zoom_fn=lambda t: 0.0)
    plan = plan_render(cs, divider_y=probe_comp.divider_y(), edit=edit)
    (out_dir / "subtitles.ass").write_text(plan.ass, encoding="utf-8")
    (out_dir / "subtitles.srt").write_text(plan.srt, encoding="utf-8")
    (out_dir / "plan.json").write_text(plan.edit.model_dump_json(indent=1), encoding="utf-8")
    if on_progress:
        on_progress(0.0, "Inquadratura: tracking del soggetto")
    comp = make_compositor(cs, plan, dw, dh)
    out = out_dir / "clip.mp4"

    nvenc = get_settings().use_gpu and ffmpeg.capabilities().get("nvenc_h264", False)
    attempts = [True, False] if nvenc else [False]
    last_err: Exception | None = None
    for use_nvenc in attempts:
        try:
            stats = _encode(cs, plan, comp, out, use_nvenc, on_progress, should_cancel)
            stats.update({"warnings": plan.warnings, "layout": plan.layout, "segments": len(plan.segments),
                          "cut_seconds": round(cs.duration - plan.body, 2), "zoom_peaks": plan.zoom_peaks,
                          "cues": len(plan.cues), "plan": plan.edit.summary(), "tracking": plan.tracking,
                          "sfx": [{"t": t, "category": c, "volume": v} for t, c, v in plan.sfx],
                          "logo": ({"corner": cs.logo.corner, "x": cs.logo.x, "y": cs.logo.y, "w": cs.logo.w,
                                    "h": cs.logo.h, "opacity": cs.logo.opacity} if cs.logo else None),
                          "fps": cs.fps, "preset": cfg.preset})
            return stats
        except RenderCancelled:
            out.unlink(missing_ok=True)
            raise
        except MediaError as e:
            last_err = e
            log.warning("Render with %s failed: %s", "NVENC" if use_nvenc else "libx264", e)
    out.unlink(missing_ok=True)
    raise MediaError(f"Render failed: {last_err}")


def _encode(cs: ClipSource, plan: RenderPlan, comp: Compositor, out: Path, use_nvenc: bool,
            on_progress, should_cancel) -> dict:
    s = get_settings()
    cfg = plan.cfg
    fps = cs.fps
    ass_path = out.parent / "subtitles.ass"
    ass = f"ass=filename='{_escape_filter_path(ass_path)}':fontsdir='{_escape_filter_path(FONTS_DIR)}'"
    audio_in = ["-ss", f"{cs.start:.3f}", "-t", f"{cs.duration:.3f}", "-i", str(cs.src)] if cs.has_audio else \
        ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    extra_in: list[str] = []
    next_input = 2
    # Brand Kit logo: input 2, overlaid under the subtitles at a deterministic position
    if cs.logo is not None:
        extra_in += ["-i", str(cs.logo.path)]
        vf = f"{overlay_filter(next_input, '0:v', 'vl', cs.logo)};[vl]{ass}[v]"
        next_input += 1
    else:
        vf = f"[0:v]{ass}[v]"
    measured = measure_loudness(cs, plan) if cs.has_audio and cfg.normalize_audio else None
    if cs.has_audio:
        afilter = _audio_filter(cs, plan, measured, out="amain")
        sfx_in, sfx_parts = mix_filters(plan.sfx, next_input, "amain", "a", plan.total)
        extra_in += sfx_in
        afilter = ";".join([afilter, *sfx_parts])
    else:
        afilter = f"[1:a]atrim=0:{plan.total:.3f}[a]"
    cmd = [s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}", "-r", str(fps), "-i", "pipe:0",
           *audio_in, *extra_in, "-filter_complex", f"{vf};{afilter}", "-map", "[v]", "-map", "[a]",
           *_encoder_args(cfg, use_nvenc), "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{plan.total:.3f}",
           "-movflags", "+faststart", str(out)]
    log.debug("encode: %s", " ".join(cmd))
    err_file = tempfile.TemporaryFile()
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err_file)
    assert enc.stdin is not None
    reader = FrameReader(cs.src, cs.start, cs.duration, fps, cs.width, cs.height)

    total_frames = max(1, int(round(plan.total * fps)))
    written = 0
    t0 = time.monotonic()
    cuts = cut_points(plan.segments) if cfg.transitions else []
    xfade_frames = max(1, int(0.12 * fps))
    last_frame: np.ndarray | None = None
    prev_before_cut: np.ndarray | None = None

    def write(img: np.ndarray) -> None:
        nonlocal written
        if should_cancel and should_cancel():
            raise RenderCancelled()
        try:
            enc.stdin.write(img.tobytes())  # type: ignore[union-attr]
        except BrokenPipeError as e:
            raise MediaError(_stderr(err_file)) from e
        written += 1
        if on_progress and written % 10 == 0:
            el = time.monotonic() - t0
            speed = written / fps / el if el > 0 else 0
            on_progress(written / total_frames, f"Rendering {written}/{total_frames} frame ({speed:.1f}x)")

    def writer_failed() -> bool:
        return enc.poll() is not None

    try:
        body_frames = int(round(plan.body * fps))
        out_i = 0
        for i, frame in enumerate(reader):
            if writer_failed():
                break
            t_src = i / fps
            t_out = map_time(t_src, plan.segments)
            if t_out is None or out_i >= body_frames:
                if t_out is None and last_frame is not None:
                    prev_before_cut = last_frame
                continue
            img = post_effects(comp.compose(frame, t_src), plan.edit, t_src)
            if out_i == 0 and plan.intro:
                card = card_from(img)
                n = int(round(plan.intro * fps))
                for k in range(n):
                    a = min(1.0, max(0.0, (k - (n - int(0.25 * fps))) / max(1, int(0.25 * fps))))
                    write(blend(card, img, a) if a > 0 else card)
            # transitions: fade from black at start (no intro), crossfade after jump cuts, fade out at end
            t_body = out_i / fps
            if cfg.transitions:
                if not plan.intro and t_body < 0.25:
                    img = (img.astype(np.float32) * (t_body / 0.25)).astype(np.uint8)
                for c in cuts:
                    k = out_i - int(round(c * fps))
                    if 0 <= k < xfade_frames and prev_before_cut is not None:
                        img = blend(prev_before_cut, img, (k + 1) / (xfade_frames + 1))
                if not plan.outro and t_body > plan.body - 0.3:
                    img = (img.astype(np.float32) * max(0.0, (plan.body - t_body) / 0.3)).astype(np.uint8)
            write(img)
            last_frame = img
            out_i += 1
        if writer_failed():
            raise MediaError(_stderr(err_file))
        # pad if the decoder produced fewer frames than expected (rounding at the end)
        while out_i < body_frames and last_frame is not None:
            write(last_frame)
            out_i += 1
        if plan.outro and last_frame is not None:
            card = card_from(last_frame)
            n = int(round(plan.outro * fps))
            fade = max(1, int(0.25 * fps))
            for k in range(n):
                write(blend(last_frame, card, min(1.0, (k + 1) / fade)))
        enc.stdin.close()
        rc = enc.wait(timeout=600)
        if rc != 0:
            raise MediaError(_stderr(err_file))
    except RenderCancelled:
        enc.kill()
        enc.wait()
        raise
    except BrokenPipeError as e:
        raise MediaError(_stderr(err_file)) from e
    finally:
        reader.close()
        if enc.poll() is None:
            enc.kill()
            enc.wait()
        err_file.close()

    elapsed = time.monotonic() - t0
    info = ffmpeg.probe(out)
    return {"encoder": "h264_nvenc" if use_nvenc else "libx264", "frames": written, "elapsed_s": round(elapsed, 1),
            "speed_x": round(plan.total / elapsed, 2) if elapsed else None, "duration": info.duration,
            "width": info.width, "height": info.height, "file_size": out.stat().st_size}


def _stderr(f) -> str:
    try:
        f.seek(0)
        return "ffmpeg encoder: " + f.read().decode(errors="ignore")[-800:].strip()
    except Exception:  # noqa: BLE001
        return "ffmpeg encoder failed"


# ----------------------------------------------------------------- previews
_preview_lock = threading.Lock()


def preview_frame(cs: ClipSource, t: float) -> bytes:
    """JPEG of the composed vertical frame at clip-relative source time t (subtitles burnt in)."""
    dw, dh = scaled_size(cs.width, cs.height)
    probe_comp = Compositor(cs.config.model_copy(update={"layout": cs.config.layout if cs.webcam else "full"}),
                            dw, dh, webcam=cs.webcam, path=CameraPath.fixed(), zoom_fn=lambda _t: 0.0)
    plan = plan_render(cs, divider_y=probe_comp.divider_y())
    # preview: static crop path through the subject's position at t would need the full tracking pass,
    # which is too slow for a live preview → action/centre path only (faces are tracked in the render)
    comp = make_compositor(cs, plan, dw, dh, path=CameraPath.fixed() if cs.config.subject == "faces" else None)
    t = float(np.clip(t, 0, max(0.0, cs.duration - 0.05)))
    frame = grab_frame(cs.src, cs.start + t, cs.width, cs.height)
    img = post_effects(comp.compose(frame, t), plan.edit, t)
    t_out = (map_time(t, plan.segments) or 0.0) + plan.intro
    s = get_settings()
    with _preview_lock, tempfile.TemporaryDirectory(prefix="clipnova-pv-") as tmp:
        ass = Path(tmp) / "s.ass"
        ass.write_text(plan.ass, encoding="utf-8")
        subs = (f"setpts=PTS+{t_out:.3f}/TB,ass=filename='{_escape_filter_path(ass)}':"
                f"fontsdir='{_escape_filter_path(FONTS_DIR)}',scale=540:960")
        if cs.logo is not None:
            graph = ["-i", str(cs.logo.path), "-filter_complex",
                     f"{overlay_filter(1, '0:v', 'vl', cs.logo)};[vl]{subs}[v]", "-map", "[v]"]
        else:
            graph = ["-vf", subs]
        cmd = [s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{OUT_W}x{OUT_H}", "-i", "pipe:0", *graph,
               "-frames:v", "1", "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]
        proc = subprocess.run(cmd, input=img.tobytes(), capture_output=True, timeout=60)
    if proc.returncode != 0 or not proc.stdout:
        raise MediaError(f"Preview failed: {proc.stderr.decode(errors='ignore')[-400:]}")
    return proc.stdout
