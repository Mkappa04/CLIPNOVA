"""Webcam overlay detection.

Heuristic, two cues combined:
1. Faces (OpenCV YuNet DNN) that appear repeatedly in the *same place* across
   frames sampled over the whole video. Game characters move; a facecam doesn't.
2. Static rectangular borders around that place: the per-pixel edge strength
   averaged over time keeps overlay frames/borders and washes out gameplay.

Returns a normalised Region with a confidence. When nothing convincing is
found it returns None, and the user selects the region manually in the UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from backend.core.config import PROJECT_ROOT
from backend.editing.config import Region
from backend.editing.frames import sample_frames

log = logging.getLogger(__name__)
YUNET = PROJECT_ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"


@dataclass
class WebcamDetection:
    region: Region | None
    frames: int
    face_frames: int
    reason: str
    candidates: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"region": self.region.model_dump() if self.region else None, "frames": self.frames,
                "face_frames": self.face_frames, "reason": self.reason, "candidates": self.candidates}


def detect_faces(frames: list[np.ndarray], min_score: float = 0.75) -> list[list[tuple[float, float, float, float, float]]]:
    """Per frame: list of (x, y, w, h, score) in pixels."""
    if not frames:
        return []
    h, w = frames[0].shape[:2]
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), score_threshold=min_score, nms_threshold=0.3, top_k=50)
    out = []
    for f in frames:
        _, faces = det.detect(f)
        out.append([] if faces is None else [tuple(float(v) for v in face[:4]) + (float(face[-1]),) for face in faces])
    return out


def static_edges(frames: list[np.ndarray]) -> np.ndarray:
    """Fraction of frames in which each pixel is a strong edge (0..1)."""
    acc = None
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        mag = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
        thr = max(40.0, float(np.percentile(mag, 90)))
        e = (mag > thr).astype(np.float32)
        acc = e if acc is None else acc + e
    return acc / max(1, len(frames))


def _border(profile: np.ndarray, start: int, step: int, limit: int, min_strength: float) -> int | None:
    """Scan from `start` towards `limit`; among the strongest persistent lines return the nearest.

    Overlay borders are static in ~every frame, so they beat edges inside the camera image."""
    idx = np.arange(start, limit + step, step)
    idx = idx[(idx >= 0) & (idx < len(profile))]
    if len(idx) == 0:
        return None
    vals = profile[idx]
    best = float(vals.max())
    if best < min_strength:
        return None
    near_best = np.flatnonzero(vals >= best - 0.08)
    return int(idx[near_best[0]])


def estimate_box(edges: np.ndarray, face: tuple[float, float, float, float]) -> tuple[int, int, int, int, float]:
    """Grow a rectangle from the median face until persistent straight borders (or the frame edge).

    Border profiles are averaged over a band ~3 face-sizes wide: an overlay border spans the whole
    box, while edges inside the face/background only cover a small part of the band.
    """
    H, W = edges.shape
    fx, fy, fw, fh = face
    cx, cy = fx + fw / 2, fy + fh / 2
    rx, ry = int(fw * 3.5), int(fh * 3.0)
    band_y0, band_y1 = int(max(0, cy - fh * 1.4)), int(min(H, cy + fh * 1.4))
    band_x0, band_x1 = int(max(0, cx - fw * 1.4)), int(min(W, cx + fw * 1.4))
    strength = 0.5
    left = right = top = bottom = None
    # Alternate: borders found in one direction narrow the band used for the other direction
    for _ in range(2):
        rows = edges[:, band_x0:band_x1].mean(axis=1)  # horizontal lines
        top = _border(rows, int(fy) - 2, -1, max(0, int(cy - ry)), strength)
        bottom = _border(rows, int(fy + fh) + 2, 1, min(H - 1, int(cy + ry)), strength)
        if top is not None:
            band_y0 = top + 3
        if bottom is not None:
            band_y1 = bottom - 3
        cols = edges[band_y0:band_y1].mean(axis=0)   # vertical lines
        left = _border(cols, int(fx) - 2, -1, max(0, int(cx - rx)), strength)
        right = _border(cols, int(fx + fw) + 2, 1, min(W - 1, int(cx + rx)), strength)
        if left is not None:
            band_x0 = left + 3
        if right is not None:
            band_x1 = right - 3
    found = sum(v is not None for v in (left, right, top, bottom))

    def snap(v: int | None, fallback: float, edge: int, size: float) -> int:
        if v is not None:
            return v
        # No border found: if the face is close to the frame edge, assume the overlay is flush with it
        return edge if abs(fallback - edge) < size * 2.2 else int(fallback)

    L = snap(left, fx - fw * 1.2, 0, fw)
    R = snap(right, fx + fw * 2.2, W, fw)
    T = snap(top, fy - fh * 0.9, 0, fh)
    B = snap(bottom, fy + fh * 2.0, H, fh)
    return max(0, L), max(0, T), min(W, R), min(H, B), found / 4


def detect_webcam(src: Path, duration: float, width: int, height: int, n_frames: int = 24) -> WebcamDetection:
    frames = sample_frames(src, duration, width, height, n=n_frames, max_w=960)
    if len(frames) < 4:
        return WebcamDetection(None, len(frames), 0, "Video troppo corto per il rilevamento")
    H, W = frames[0].shape[:2]
    faces = detect_faces(frames)
    face_frames = sum(1 for f in faces if f)

    # Vote face centres on a coarse grid; a webcam keeps its face in the same cell(s)
    gx, gy = 16, 9
    votes = np.zeros((gy, gx), dtype=np.float32)
    per_cell: dict[tuple[int, int], list] = {}
    for flist in faces:
        seen = set()
        for x, y, w, h, s in flist:
            if w > W * 0.45:  # full-screen face (IRL/cutscene close-up) is not an overlay
                continue
            c = (min(gx - 1, int((x + w / 2) / W * gx)), min(gy - 1, int((y + h / 2) / H * gy)))
            if c in seen:
                continue
            seen.add(c)
            votes[c[1], c[0]] += 1
            per_cell.setdefault(c, []).append((x, y, w, h))
    # Smooth votes over neighbouring cells (a face can sit on a boundary)
    smoothed = cv2.blur(votes, (3, 3), borderType=cv2.BORDER_CONSTANT) * 9
    cy, cx = np.unravel_index(int(smoothed.argmax()), smoothed.shape)
    persistence = float(smoothed[cy, cx]) / len(frames)
    candidates = [{"cell": [int(c[0]), int(c[1])], "frames": len(v)} for c, v in
                  sorted(per_cell.items(), key=lambda kv: -len(kv[1]))[:5]]
    if persistence < 0.35:
        return WebcamDetection(None, len(frames), face_frames,
                               f"Nessun volto stabile trovato (persistenza {persistence:.0%}): selezione manuale",
                               candidates)

    boxes = [b for (c, bl) in per_cell.items() if abs(c[0] - cx) <= 1 and abs(c[1] - cy) <= 1 for b in bl]
    face = tuple(float(np.median([b[i] for b in boxes])) for i in range(4))
    L, T, R, B, border_score = estimate_box(static_edges(frames), face)  # type: ignore[arg-type]
    if R - L < face[2] * 1.2 or B - T < face[3] * 1.2:
        return WebcamDetection(None, len(frames), face_frames, "Riquadro webcam non determinabile", candidates)
    # Small inset so the overlay border is not included in the crop
    inset_x, inset_y = int((R - L) * 0.015), int((B - T) * 0.015)
    L, T, R, B = L + inset_x, T + inset_y, R - inset_x, B - inset_y
    confidence = round(min(1.0, 0.6 * min(1.0, persistence / 0.8) + 0.4 * border_score), 2)
    region = Region(x=L / W, y=T / H, w=(R - L) / W, h=(B - T) / H, source="auto", confidence=confidence)
    reason = (f"Volto stabile nel {persistence:.0%} dei fotogrammi campionati; "
              f"{int(border_score * 4)}/4 bordi dell'overlay individuati")
    return WebcamDetection(region, len(frames), face_frames, reason, candidates)
