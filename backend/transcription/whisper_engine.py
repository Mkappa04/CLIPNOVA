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


# ---------------------------------------------------------------- process isolation + chunking
CHUNK_TARGET_S = 45.0
CHUNK_SEARCH_S = 6.0
MAX_GPU_RESTARTS = 8


def plan_chunks(wav: Path, target_s: float = CHUNK_TARGET_S, search_s: float = CHUNK_SEARCH_S) -> list[tuple[float, float]]:
    """Split the audio into ~target_s chunks, cutting at the quietest point near each boundary."""
    import wave

    import numpy as np

    with wave.open(str(wav), "rb") as wf:
        sr, n = wf.getframerate(), wf.getnframes()
        hop = int(sr * 0.25)
        levels = []
        while True:
            raw = wf.readframes(hop * 400)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            usable = (len(x) // hop) * hop
            if usable:
                levels.extend(np.sqrt((x[:usable].reshape(-1, hop) ** 2).mean(axis=1)).tolist())
    duration = n / sr
    if duration <= target_s * 1.5:
        return [(0.0, duration)]
    cuts, t = [0.0], target_s
    while t < duration - target_s * 0.5:
        lo, hi = int((t - search_s) / 0.25), int((t + search_s) / 0.25)
        window = levels[max(0, lo):min(len(levels), hi)]
        best = (max(0, lo) + int(np.argmin(window))) * 0.25 if window else t
        cuts.append(round(best, 2))
        t = best + target_s
    cuts.append(duration)
    return list(zip(cuts[:-1], cuts[1:]))


def _read_slice(wav: Path, start: float, end: float):
    import wave

    import numpy as np

    with wave.open(str(wav), "rb") as wf:
        sr = wf.getframerate()
        wf.setpos(int(start * sr))
        raw = wf.readframes(int((end - start) * sr))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _die_with_parent() -> None:
    """Linux: terminate this worker if the server process dies (no orphaned GPU workers)."""
    try:
        import ctypes
        import signal

        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


def _chunk_worker(audio: str, chunks: list, start_idx: int, language: str | None, force_device: str | None,
                  only_one: bool, q) -> None:  # pragma: no cover - runs in a child process
    _die_with_parent()
    try:
        s = get_settings()
        device, model_name, compute, _ = engine.choose_device()
        if force_device == "cpu":
            device, model_name, compute = "cpu", s.whisper_cpu_model, s.whisper_compute_type_cpu
        q.put(("loading", device, model_name))
        model = engine._load(model_name, device, compute)
        crash_marker = os.environ.get("CLIPNOVA_TEST_CRASH_CHUNK")  # test hook: simulate a CUDA abort once
        for i in range(start_idx, len(chunks)):
            if crash_marker and device == "cuda" and i == int(crash_marker.split(":")[0]):
                flag = Path(crash_marker.split(":", 1)[1])
                if not flag.exists():
                    flag.write_text("crashed")
                    os.abort()
            c0, c1 = chunks[i]
            segs_iter, info = model.transcribe(
                _read_slice(Path(audio), c0, c1), language=language, word_timestamps=True,
                beam_size=s.whisper_beam_size, vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False)
            out, filtered = [], 0
            for seg in segs_iter:
                if is_hallucination(seg):
                    filtered += 1
                    continue
                out.append(asdict(Segment(
                    id=0, start=round(float(seg.start) + c0, 2), end=round(float(seg.end) + c0, 2), text=seg.text.strip(),
                    avg_logprob=round(float(seg.avg_logprob), 3), no_speech_prob=round(float(seg.no_speech_prob), 3),
                    words=[Word(round(float(w.start) + c0, 2), round(float(w.end) + c0, 2), w.word,
                                round(float(w.probability), 3)) for w in (seg.words or [])])))
            if language is None and out:
                language = info.language  # keep the detected language for the following chunks
            q.put(("chunk", i, out, info.language, float(info.language_probability), filtered, device, model_name))
            if only_one:
                break
        q.put(("done",))
    except Exception as e:  # noqa: BLE001
        q.put(("error", f"{type(e).__name__}: {e}"))


def transcribe_isolated(
    audio: Path, *, language: str | None = None, duration: float | None = None,
    on_progress: Callable[[float, str], None] | None = None, should_cancel: Callable[[], bool] | None = None,
) -> Transcript:
    """Chunked, resumable transcription in spawned worker processes.

    - The worker exits after the job → the OS reclaims all RAM/VRAM.
    - The audio is split at quiet points into ~45 s chunks. If the GPU worker crashes (CUDA errors kill
      the whole process), a new GPU worker resumes from the failed chunk; a chunk that crashes twice is
      done on CPU, then the GPU continues. Only after MAX_GPU_RESTARTS crashes the rest goes to CPU.
    """
    import multiprocessing as mp
    import queue as _queue

    t0 = time.monotonic()
    audio = Path(audio).resolve()  # workers may not share our notion of the working directory
    chunks = plan_chunks(audio)
    total = len(chunks)
    results: dict[int, list[dict]] = {}
    lang, lang_prob, filtered = language, 0.0, 0
    devices, models = set(), set()
    gpu_crashes = 0
    crashes_per_chunk: dict[int, int] = {}
    ctx = mp.get_context("spawn")
    next_idx = 0
    gpu_disabled = False

    while next_idx < total:
        force_cpu = gpu_disabled or crashes_per_chunk.get(next_idx, 0) >= 2
        q = ctx.Queue()
        proc = ctx.Process(target=_chunk_worker, daemon=True, name="clipnova-whisper",
                           args=(str(audio), chunks, next_idx, lang, "cpu" if force_cpu else None,
                                 force_cpu and not gpu_disabled, q))
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
                if msg[0] == "loading" and on_progress:
                    cached = any((get_settings().models_dir / "whisper").glob(f"models--*{msg[2]}*"))
                    on_progress(len(results) / total, f"Caricamento modello {msg[2]} ({msg[1]})" if cached else
                                f"Download modello {msg[2]} (una sola volta, può richiedere qualche minuto)")
                elif msg[0] == "chunk":
                    _, i, segs, det_lang, prob, filt, dev, mname = msg
                    results[i] = segs
                    filtered += filt
                    devices.add(dev)
                    models.add(mname)
                    if lang is None and segs:
                        lang, lang_prob = det_lang, prob
                    elif not lang_prob and det_lang == lang:
                        lang_prob = prob
                    next_idx = i + 1
                    if on_progress:
                        on_progress(len(results) / total, f"Trascrizione {dev.upper()} blocco {len(results)}/{total}")
                    if force_cpu and not gpu_disabled:
                        status = "done"  # the problematic chunk is done on CPU: go back to the GPU
                elif msg[0] in ("done", "error"):
                    status, error = msg[0], (msg[1] if msg[0] == "error" else None)
        finally:
            proc.join(10)
            if proc.is_alive():
                proc.kill()
        if status == "error":
            raise RuntimeError(f"Transcription failed: {error}")
        if status == "crashed":
            if force_cpu:
                raise RuntimeError(f"Transcription failed on CPU: {error}")
            gpu_crashes += 1
            crashes_per_chunk[next_idx] = crashes_per_chunk.get(next_idx, 0) + 1
            log.warning("Whisper GPU worker crashed at chunk %d/%d (%s); crash %d", next_idx + 1, total, error, gpu_crashes)
            if gpu_crashes >= max(MAX_GPU_RESTARTS, total):  # a restart costs seconds, CPU costs minutes
                gpu_disabled = True
                log.warning("Too many GPU crashes: finishing the transcription on CPU")
            if on_progress:
                on_progress(len(results) / total, f"Errore GPU sul blocco {next_idx + 1}: riprendo da lì")

    segments: list[Segment] = []
    for i in range(total):
        for sd in results.get(i, []):
            sd["id"] = len(segments)
            segments.append(Segment(**{**sd, "words": [Word(**w) for w in sd["words"]]}))
    dur = duration or (chunks[-1][1] if chunks else 0.0)
    device = "+".join(sorted(devices)) or "cpu"
    return Transcript(language=lang or "", language_probability=round(lang_prob, 3), duration=round(dur, 2),
                      device=device, model="+".join(sorted(models)), segments=segments,
                      elapsed_s=round(time.monotonic() - t0, 1), filtered_segments=filtered)


def transcribe(audio: Path, **kwargs) -> Transcript:
    """Entry point used by the pipeline: isolated process unless the model must stay loaded."""
    if get_settings().whisper_keep_loaded:
        return engine.transcribe(audio, **kwargs)
    return transcribe_isolated(audio, **kwargs)
