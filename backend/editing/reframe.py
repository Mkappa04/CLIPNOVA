"""Smart crop: a smoothed "virtual camera" path that follows on-screen action.

Computed on the low-res analysis proxy (10 fps): per frame, motion energy per
column (webcam area masked out) gives a target x; the camera then follows the
target with a dead-zone and a speed limit, and is smoothed, so the vertical
crop pans calmly instead of jittering.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from backend.editing.config import Region


@dataclass
class CameraPath:
    times: np.ndarray   # clip-relative seconds
    cx: np.ndarray      # normalised horizontal centre (0..1 of source width)
    cy: np.ndarray      # normalised vertical centre

    def at(self, t: float) -> tuple[float, float]:
        if len(self.times) == 0:
            return 0.5, 0.5
        return float(np.interp(t, self.times, self.cx)), float(np.interp(t, self.times, self.cy))

    @staticmethod
    def fixed(cx: float = 0.5, cy: float = 0.5) -> CameraPath:
        return CameraPath(np.array([0.0]), np.array([cx]), np.array([cy]))


def _gauss(x: np.ndarray, sigma_samples: float) -> np.ndarray:
    if sigma_samples <= 0 or len(x) < 3:
        return x
    r = int(3 * sigma_samples)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_samples) ** 2)
    k /= k.sum()
    padded = np.pad(x, r, mode="edge")
    return np.convolve(padded, k, mode="valid")


def action_targets(proxy: Path, start: float, end: float, exclude: Region | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Raw per-frame motion centroid (cx, cy), weight (motion amount) and times."""
    cap = cv2.VideoCapture(str(proxy))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open proxy {proxy}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start) * 1000)
    times, xs, ys, ws = [], [], [], []
    prev = None
    mask = None
    t = start
    while t <= end:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        g = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        if mask is None:
            h, w = g.shape
            mask = np.ones((h, w), np.float32)
            if exclude is not None:
                x0, y0 = int(exclude.x * w), int(exclude.y * h)
                mask[y0:y0 + int(exclude.h * h) + 1, x0:x0 + int(exclude.w * w) + 1] = 0
            # ignore the outer 3% (letterbox edges, HUD borders)
            bx, by = max(1, w // 33), max(1, h // 33)
            mask[:by] = mask[-by:] = 0
            mask[:, :bx] = mask[:, -bx:] = 0
        if prev is not None:
            diff = np.abs(g - prev) * mask
            diff[diff < 8] = 0
            total = float(diff.sum())
            col, row = diff.sum(axis=0), diff.sum(axis=1)
            if total > 0:
                xs.append(float((col * np.arange(len(col))).sum() / total / len(col)))
                ys.append(float((row * np.arange(len(row))).sum() / total / len(row)))
            else:
                xs.append(np.nan)
                ys.append(np.nan)
            ws.append(total / diff.size)
            times.append(t - start)
        prev = g
    cap.release()
    del fps
    return np.array(times), np.array(xs), np.array(ys), np.array(ws)


def camera_path(proxy: Path | None, start: float, end: float, *, crop_w_norm: float,
                exclude: Region | None = None, dead_zone: float = 0.05, max_speed: float = 0.22,
                follow_y: bool = False) -> CameraPath:
    """crop_w_norm: crop width as a fraction of the source width (limits the reachable centre)."""
    half = min(0.5, crop_w_norm / 2)
    if proxy is None or not proxy.exists() or crop_w_norm >= 0.999:
        return CameraPath.fixed()
    times, xs, ys, ws = action_targets(proxy, start, end, exclude)
    if len(times) < 3:
        return CameraPath.fixed()

    # Low-motion frames carry no information: hold the last good target (start from centre)
    strong = ws > max(np.percentile(ws, 30), 1e-3)
    tx = np.where(strong & ~np.isnan(xs), xs, np.nan)
    ty = np.where(strong & ~np.isnan(ys), ys, np.nan)
    for arr in (tx, ty):
        last = 0.5
        for i in range(len(arr)):
            if np.isnan(arr[i]):
                arr[i] = last
            else:
                last = arr[i]
    dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.1
    tx = _gauss(tx, 1.0 / dt)

    # Virtual camera: dead-zone + speed limit
    pos = np.empty_like(tx)
    p = float(np.clip(tx[: max(1, int(1.5 / dt))].mean(), half, 1 - half))
    for i, target in enumerate(np.clip(tx, half, 1 - half)):
        err = target - p
        if abs(err) > dead_zone:
            step = np.clip(err - np.sign(err) * dead_zone, -max_speed * dt, max_speed * dt)
            p += float(step)
        pos[i] = p
    pos = np.clip(_gauss(pos, 0.3 / dt), half, 1 - half)
    cy = np.clip(_gauss(ty, 1.5 / dt), 0.35, 0.65) if follow_y else np.full_like(pos, 0.5)
    return CameraPath(times, pos, cy)


def zoom_envelope(t: float, peaks: list[float], ramp_in: float = 0.25, hold: float = 1.1, ramp_out: float = 0.5) -> float:
    """0..1 punch-in envelope: eases in to each peak, holds, eases out."""
    e = 0.0
    for p in peaks:
        a = p - ramp_in
        if t < a or t > p + hold + ramp_out:
            continue
        if t < p:
            v = (t - a) / ramp_in
        elif t <= p + hold:
            v = 1.0
        else:
            v = 1 - (t - p - hold) / ramp_out
        v = v * v * (3 - 2 * v)  # smoothstep
        e = max(e, v)
    return e
