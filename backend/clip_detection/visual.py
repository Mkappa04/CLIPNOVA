"""Visual analysis on the low-res proxy: scene cuts (PySceneDetect) and motion/flash (OpenCV)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np


def detect_scenes(
    proxy: Path, *, on_progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None, chunk_frames: int = 3000,
) -> list[float]:
    """Return scene-cut timestamps (seconds). Processed in chunks for progress/cancel."""
    from scenedetect import AdaptiveDetector, SceneManager, open_video

    video = open_video(str(proxy), backend="opencv")
    total = max(1, int(video.duration.get_frames()))
    manager = SceneManager()
    manager.add_detector(AdaptiveDetector(min_scene_len=5))
    done = 0
    while True:
        if should_cancel and should_cancel():
            raise InterruptedError
        n = manager.detect_scenes(video=video, duration=chunk_frames, show_progress=False)
        done += n
        if on_progress:
            on_progress(min(1.0, done / total))
        if n < chunk_frames:
            break
    return [round(c.get_seconds(), 2) for c in manager.get_cut_list()]


def motion_activity(
    proxy: Path, window_s: float, n_windows: int, *,
    on_progress: Callable[[float], None] | None = None, should_cancel: Callable[[], bool] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-window mean frame difference (motion) and max luminance jump (flashes/explosions)."""
    cap = cv2.VideoCapture(str(proxy))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV cannot open {proxy}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    motion = np.zeros(n_windows, dtype=np.float32)
    flash = np.zeros(n_windows, dtype=np.float32)
    counts = np.zeros(n_windows, dtype=np.int32)
    prev, prev_lum, idx = None, None, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            w = min(n_windows - 1, int((idx / fps) / window_s))
            lum = float(gray.mean())
            if prev is not None:
                motion[w] += float(cv2.absdiff(gray, prev).mean())
                counts[w] += 1
                flash[w] = max(flash[w], abs(lum - prev_lum))
            prev, prev_lum = gray, lum
            idx += 1
            if idx % 500 == 0:
                if should_cancel and should_cancel():
                    raise InterruptedError
                if on_progress:
                    on_progress(min(1.0, idx / total))
    finally:
        cap.release()
    motion = np.divide(motion, np.maximum(counts, 1)).astype(np.float32)
    return motion, flash
