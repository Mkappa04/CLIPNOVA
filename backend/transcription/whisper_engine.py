"""faster-whisper transcription with GPU/CPU selection, VRAM guard and fallback.

- GPU (CTranslate2 CUDA, int8_float16) when CUDA works and enough VRAM is free.
- Falls back to CPU (int8, smaller model) on load failure or CUDA OOM.
- Model weights are cached in data/models/whisper (downloaded once from Hugging Face).
- Runs in a spawned child process per job, so RAM/VRAM are fully released afterwards
  (unless CLIPNOVA_WHISPER_KEEP_LOADED=true, which keeps the model in the server process).
"""

from __future__ import annotations

import gc
import json as _json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from backend.core import gpu
from backend.core.config import get_settings

log = logging.getLogger(__name__)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# Phrases Whisper is known to hallucinate on music/silence (not spoken in the video).
_HALLUCINATIONS = [
    r"sottotitoli (creati |a cura )?(dalla|di|da)", r"qtss", r"amara\.org", r"thanks? for watching",
    r"grazie (a tutti )?per (la visione|l'ascolto|aver guardato)", r"iscriviti al canale",
    r"subtitles by", r"please subscribe", r"www\.\w+\.(com|it)",
]
_HALLU_RE = re.compile("|".join(_HALLUCINATIONS), re.IGNORECASE)


@dataclass
class Word:
    start: float
    end: float
    word: str
    probability: float


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    language_probability: float
    duration: float
    device: str
    model: str
    segments: list[Segment]
    elapsed_s: float = 0.0
    filtered_segments: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Transcript:
        segs = [Segment(**{**s, "words": [Word(**w) for w in s.get("words", [])]}) for s in d.get("segments", [])]
        return Transcript(**{**d, "segments": segs})

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


class TranscriptionCancelled(Exception):
    pass


def is_hallucination(seg) -> bool:
    if _HALLU_RE.search(seg.text or ""):
        return True
    # Very unlikely speech + very low confidence = noise transcribed as words
    return seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0


class WhisperEngine:
    def __init__(self) -> None:
        self._model = None
        self._key: tuple[str, str, str] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- device
    def choose_device(self) -> tuple[str, str, str, str]:
        """Return (device, model, compute_type, reason)."""
        s = get_settings()
        if not s.use_gpu:
            return "cpu", s.whisper_cpu_model, s.whisper_compute_type_cpu, "GPU disabled in settings"
        if gpu.cuda_device_count() < 1:
            return "cpu", s.whisper_cpu_model, s.whisper_compute_type_cpu, "No CUDA device"
        if not gpu.preload_cuda_libs():
            return "cpu", s.whisper_cpu_model, s.whisper_compute_type_cpu, "CUDA libraries not available"
        free = gpu.free_vram_mb()
        loaded_on_gpu = self._key is not None and self._key[1] == "cuda"
        if free is not None and free < s.whisper_min_free_vram_mb and not loaded_on_gpu:
            return "cpu", s.whisper_cpu_model, s.whisper_compute_type_cpu, f"Only {free} MB VRAM free"
        return "cuda", s.whisper_model, s.whisper_compute_type_gpu, "GPU"

    def _load(self, model: str, device: str, compute: str):
        from faster_whisper import WhisperModel

        key = (model, device, compute)
        if self._key == key and self._model is not None:
            return self._model
        self.unload()
        s = get_settings()
        root = s.models_dir / "whisper"
        root.mkdir(parents=True, exist_ok=True)
        t = time.monotonic()
        log.info("Loading Whisper %s on %s (%s)…", model, device, compute)
        cpu_threads = max(1, (os.cpu_count() or 4) - 2)
        self._model = WhisperModel(model, device=device, compute_type=compute, download_root=str(root),
                                   cpu_threads=cpu_threads if device == "cpu" else 0)
        self._key = key
        log.info("Whisper loaded in %.1fs", time.monotonic() - t)
        return self._model

    def unload(self) -> None:
        if self._model is not None:
            log.info("Unloading Whisper model %s", self._key)
        self._model = None
        self._key = None
        gc.collect()

    # ------------------------------------------------------------- transcribe
    def transcribe(
        self, audio: Path, *, language: str | None = None, duration: float | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        force_device: str | None = None,
    ) -> Transcript:
        with self._lock:
            try:
                device, model, compute, reason = self.choose_device()
                if force_device == "cpu":
                    s = get_settings()
                    device, model, compute, reason = "cpu", s.whisper_cpu_model, s.whisper_compute_type_cpu, "forced"
                try:
                    return self._run(audio, model, device, compute, language, duration, on_progress, should_cancel)
                except TranscriptionCancelled:
                    raise
                except Exception as e:  # noqa: BLE001 - GPU problems -> CPU fallback
                    if device != "cuda":
                        raise
                    log.warning("GPU transcription failed (%s); falling back to CPU", e)
                    self.unload()
                    s = get_settings()
                    if on_progress:
                        on_progress(0.0, f"GPU non disponibile ({type(e).__name__}), uso CPU")
                    return self._run(audio, s.whisper_cpu_model, "cpu", s.whisper_compute_type_cpu,
                                     language, duration, on_progress, should_cancel)
            finally:
                if not get_settings().whisper_keep_loaded:
                    self.unload()

    def _run(self, audio, model_name, device, compute, language, duration, on_progress, should_cancel) -> Transcript:
        s = get_settings()
        if on_progress:
            cached = any((get_settings().models_dir / "whisper").glob(f"models--*{model_name}*"))
            on_progress(0.0, f"Caricamento modello {model_name} ({device})" if cached else
                        f"Download modello {model_name} (una sola volta, può richiedere qualche minuto)")
        model = self._load(model_name, device, compute)
        t0 = time.monotonic()
        segments_iter, info = model.transcribe(
            str(audio), language=language, word_timestamps=True, beam_size=s.whisper_beam_size,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        total = duration or info.duration or 1.0
        out: list[Segment] = []
        filtered = 0
        for seg in segments_iter:
            if should_cancel and should_cancel():
                raise TranscriptionCancelled()
            if on_progress:
                on_progress(min(1.0, seg.end / total), f"Trascrizione {device.upper()} {seg.end / 60:.1f}/{total / 60:.1f} min")
            if is_hallucination(seg):
                filtered += 1
                continue
            out.append(Segment(
                id=len(out), start=round(float(seg.start), 2), end=round(float(seg.end), 2), text=seg.text.strip(),
                avg_logprob=round(float(seg.avg_logprob), 3), no_speech_prob=round(float(seg.no_speech_prob), 3),
                words=[Word(round(float(w.start), 2), round(float(w.end), 2), w.word, round(float(w.probability), 3))
                       for w in (seg.words or [])],
            ))
        return Transcript(language=info.language, language_probability=round(float(info.language_probability), 3),
                          duration=round(float(info.duration), 2), device=device, model=model_name, segments=out,
                          elapsed_s=round(time.monotonic() - t0, 1), filtered_segments=filtered)


def to_srt(t: Transcript) -> str:
    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        sec, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{sec:02},{ms:03}"
    blocks = [f"{i}\n{ts(s.start)} --> {ts(s.end)}\n{s.text}\n" for i, s in enumerate(t.segments, 1)]
    return "\n".join(blocks)


engine = WhisperEngine()


# ---------------------------------------------------------------- process isolation
def _worker(audio: str, language: str | None, duration: float | None, out_path: str, force_device: str | None,
            q) -> None:  # pragma: no cover - runs in a child process
    try:
        def progress(frac: float, msg: str) -> None:
            q.put(("progress", frac, msg))

        result = engine.transcribe(Path(audio), language=language, duration=duration, on_progress=progress,
                                   force_device=force_device)
        Path(out_path).write_text(_json.dumps(result.to_dict(), ensure_ascii=False))
        q.put(("done",))
    except Exception as e:  # noqa: BLE001
        q.put(("error", f"{type(e).__name__}: {e}"))


def transcribe_isolated(
    audio: Path, *, language: str | None = None, duration: float | None = None,
    on_progress: Callable[[float, str], None] | None = None, should_cancel: Callable[[], bool] | None = None,
) -> Transcript:
    """Run Whisper in a spawned child process.

    When the child exits, the OS reclaims all RAM and VRAM (CUDA contexts and the
    allocator otherwise keep ~2 GB resident). A CUDA crash cannot take the server
    down, and cancellation is immediate (the child is terminated).
    """
    import multiprocessing as mp
    import queue as _queue
    import tempfile

    ctx = mp.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="clipnova-whisper-") as tmp:
        out = Path(tmp) / "transcript.json"
        for force_device in (None, "cpu"):
            q = ctx.Queue()
            proc = ctx.Process(target=_worker, args=(str(audio), language, duration, str(out), force_device, q),
                               daemon=True, name="clipnova-whisper")
            proc.start()
            status, error = None, None
            try:
                while status is None:
                    if should_cancel and should_cancel():
                        proc.terminate()
                        proc.join(5)
                        raise TranscriptionCancelled()
                    try:
                        msg = q.get(timeout=0.3)
                    except _queue.Empty:
                        if not proc.is_alive():
                            status, error = "crashed", f"worker exited with code {proc.exitcode}"
                        continue
                    if msg[0] == "progress" and on_progress:
                        on_progress(msg[1], msg[2])
                    elif msg[0] in ("done", "error"):
                        status, error = msg[0], (msg[1] if msg[0] == "error" else None)
            finally:
                proc.join(10)
                if proc.is_alive():
                    proc.kill()
            if status == "done":
                return Transcript.from_dict(_json.loads(out.read_text()))
            if status == "crashed" and force_device is None:
                log.warning("Whisper worker crashed (%s); retrying on CPU", error)
                if on_progress:
                    on_progress(0.0, "Worker GPU terminato in modo anomalo, riprovo su CPU")
                continue
            raise RuntimeError(f"Transcription failed: {error}")
    raise RuntimeError("Transcription failed")


def transcribe(audio: Path, **kwargs) -> Transcript:
    """Entry point used by the pipeline: isolated process unless the model must stay loaded."""
    if get_settings().whisper_keep_loaded:
        return engine.transcribe(audio, **kwargs)
    return transcribe_isolated(audio, **kwargs)
