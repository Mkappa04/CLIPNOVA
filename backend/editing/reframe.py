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
    pos = virtual_camera(times, tx, half, dead_zone, max_speed)
    cy = np.clip(_gauss(ty, 1.5 / dt), 0.35, 0.65) if follow_y else np.full_like(pos, 0.5)
    return CameraPath(times, pos, cy)


def virtual_camera(times: np.ndarray, tx: np.ndarray, half: float, dead_zone: float, max_speed: float) -> np.ndarray:
    """Follow a target x with a dead-zone and a speed limit, then smooth: calm, cinematic pans."""
    dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.1
    pos = np.empty_like(tx)
    p = float(np.clip(tx[: max(1, int(1.5 / dt))].mean(), half, 1 - half))
    for i, target in enumerate(np.clip(tx, half, 1 - half)):
        err = target - p
        if abs(err) > dead_zone:
            step = np.clip(err - np.sign(err) * dead_zone, -max_speed * dt, max_speed * dt)
            p += float(step)
        pos[i] = p
    return np.clip(_gauss(pos, 0.3 / dt), half, 1 - half)


# ------------------------------------------------------------------ faces (speaker framing)
FACE_SAMPLE_FPS = 4.0
FACE_MIN_COVERAGE = 0.35   # faces in at least 35% of the sampled frames, else not reliable


def face_track(src: Path, start: float, end: float, width: int, height: int) -> tuple[np.ndarray, list[list[tuple]], list[np.ndarray]]:
    """Faces sampled at 4 fps on a 640-px copy: (times, faces per frame [(x,y,w,h,score) normalised], gray frames)."""
    from backend.editing.frames import FrameReader
    from backend.editing.webcam import detect_faces

    reader = FrameReader(src, start, max(0.1, end - start), FACE_SAMPLE_FPS, width, height, max_w=640)
    frames = list(reader)
    if not frames:
        return np.array([]), [], []
    h, w = frames[0].shape[:2]
    det = detect_faces(frames, min_score=0.7)
    faces = [[(x / w, y / h, fw / w, fh / h, sc) for (x, y, fw, fh, sc) in fs if fw / w > 0.025] for fs in det]
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    times = np.arange(len(frames)) / FACE_SAMPLE_FPS
    return times, faces, grays


def _mouth_motion(prev: np.ndarray, cur: np.ndarray, face: tuple) -> float:
    """Pixel change in the lower half of a face box: a talking mouth moves, a listener's mostly doesn't."""
    H, W = cur.shape
    x, y, w, h = face[0] * W, face[1] * H, face[2] * W, face[3] * H
    x0, x1 = int(max(0, x + 0.2 * w)), int(min(W, x + 0.8 * w))
    y0, y1 = int(max(0, y + 0.55 * h)), int(min(H, y + 1.0 * h))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0.0
    return float(np.mean(np.abs(cur[y0:y1, x0:x1].astype(np.int16) - prev[y0:y1, x0:x1].astype(np.int16))))


def faces_path(times: np.ndarray, faces: list[list[tuple]], grays: list[np.ndarray], *, crop_w_norm: float,
               dead_zone: float = 0.06, max_speed: float = 0.15) -> CameraPath | None:
    """Speaker framing. None when faces are not reliable enough (caller falls back to action/centre).

    One face, or several that fit together in the crop → frame them all. Otherwise follow the
    active speaker (largest mouth motion), switching only after it stays dominant for ~1 s."""
    n = len(times)
    if n < 3 or crop_w_norm >= 0.999:
        return None
    coverage = sum(1 for f in faces if f) / n
    if coverage < FACE_MIN_COVERAGE:
        return None
    half = min(0.5, crop_w_norm / 2)
    tx = np.full(n, np.nan)
    ty = np.full(n, np.nan)
    current: tuple | None = None
    challenger_count = 0
    for i, fs in enumerate(faces):
        if not fs:
            continue
        x0 = min(f[0] for f in fs)
        x1 = max(f[0] + f[2] for f in fs)
        if x1 - x0 <= crop_w_norm * 0.85:          # everyone fits
            tx[i] = (x0 + x1) / 2
            ty[i] = float(np.mean([f[1] + f[3] / 2 for f in fs]))
            continue
        motion = [(_mouth_motion(grays[i - 1], grays[i], f) if i > 0 else 0.0) for f in fs]
        best = fs[int(np.argmax(motion))]
        if current is None:
            current = max(fs, key=lambda f: f[2] * f[3])
        # match the current speaker to this frame's faces (nearest centre)
        cur = min(fs, key=lambda f: abs(f[0] + f[2] / 2 - current[0] - current[2] / 2))
        if best is not cur and max(motion) > 1.5 * motion[fs.index(cur)] + 0.5:
            challenger_count += 1
            if challenger_count >= int(FACE_SAMPLE_FPS):  # dominant for ~1 s → cut to the new speaker
                cur, challenger_count = best, 0
        else:
            challenger_count = 0
        current = cur
        tx[i] = cur[0] + cur[2] / 2
        ty[i] = cur[1] + cur[3] / 2
    for arr in (tx, ty):
        last = np.nan
        first = next((v for v in arr if not np.isnan(v)), 0.5)
        for i in range(n):
            if np.isnan(arr[i]):
                arr[i] = first if np.isnan(last) else last
            else:
                last = arr[i]
    dt = 1.0 / FACE_SAMPLE_FPS
    pos = virtual_camera(times, _gauss(tx, 0.5 / dt), half, dead_zone, max_speed)
    cy = np.clip(_gauss(ty, 1.0 / dt) + 0.05, 0.35, 0.65)  # a little headroom above the face
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
