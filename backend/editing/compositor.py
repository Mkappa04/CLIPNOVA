"""Frame compositor: source frame (any size) → 1080x1920 vertical frame.

Never distorts: every area is filled by a crop with the *target* aspect ratio
(cover) or by the whole frame letter-boxed over a blurred copy (fit).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np

from backend.editing.config import OUT_H, OUT_W, EditConfig, Region
from backend.editing.reframe import CameraPath

DIVIDER = 6
ACCENT_A = (246, 92, 139)   # BGR violet #8b5cf6
ACCENT_B = (238, 211, 34)   # BGR cyan   #22d3ee


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int


def _divider_bar(width: int) -> np.ndarray:
    ramp = np.linspace(0, 1, width, dtype=np.float32)[None, :, None]
    a, b = np.array(ACCENT_A, np.float32), np.array(ACCENT_B, np.float32)
    row = (a * (1 - ramp) + b * ramp).astype(np.uint8)
    return np.repeat(row, DIVIDER, axis=0)


def _rounded_mask(w: int, h: int, r: int) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r - 1, h - 1), 255, -1)
    cv2.rectangle(m, (0, r), (w - 1, h - r - 1), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(m, (cx, cy), r, 255, -1, lineType=cv2.LINE_AA)
    return (m.astype(np.float32) / 255.0)[..., None]


class Compositor:
    def __init__(self, cfg: EditConfig, src_w: int, src_h: int, *, webcam: Region | None,
                 path: CameraPath, zoom_fn: Callable[[float], float]) -> None:
        self.cfg, self.W, self.H = cfg, src_w, src_h
        self.webcam = webcam if cfg.layout != "full" else None
        self.path = path
        self.zoom_fn = zoom_fn  # t -> envelope 0..1
        self.divider = _divider_bar(OUT_W)
        self._pip_cache: tuple | None = None

    # ------------------------------------------------------------- geometry
    def gameplay_box(self, t: float) -> Box:
        layout = self.cfg.layout
        if layout == "stack":
            return Box(0, 0, OUT_W, int(OUT_H * self.cfg.stack_ratio))
        if layout == "split":
            share = 0.5 + 0.12 * self.zoom_fn(t)  # dynamic: gameplay grows on action peaks
            return Box(0, 0, OUT_W, int(OUT_H * share) // 2 * 2)
        return Box(0, 0, OUT_W, OUT_H)

    def webcam_box(self, t: float) -> Box | None:
        if self.webcam is None:
            return None
        layout = self.cfg.layout
        if layout in ("stack", "split"):
            g = self.gameplay_box(t)
            return Box(0, g.h, OUT_W, OUT_H - g.h)
        if layout == "pip":
            w = int(OUT_W * self.cfg.pip_size) // 2 * 2
            aspect = float(np.clip((self.webcam.w * self.W) / max(1, self.webcam.h * self.H), 0.75, 1.6))
            h = int(w / aspect) // 2 * 2
            margin_x, top, bottom = 40, 240, 540
            corner = self.cfg.pip_corner
            x = margin_x if "left" in corner else OUT_W - w - margin_x
            y = top if "top" in corner else OUT_H - h - bottom
            return Box(x, y, w, h)
        return None

    def divider_y(self) -> int | None:
        """Static seam position (used to place subtitles in stack/split layouts)."""
        if self.webcam is None or self.cfg.layout not in ("stack", "split"):
            return None
        return self.gameplay_box(0.0).h

    # ------------------------------------------------------------- crops
    def _crop_cover(self, frame: np.ndarray, box: Box, cx: float, cy: float, zoom: float,
                    avoid: Region | None) -> np.ndarray:
        H, W = frame.shape[:2]
        A = box.w / box.h
        if A <= W / H:
            ch, cw = H, H * A
        else:
            cw, ch = W, W / A
        cw, ch = cw / zoom, ch / zoom
        lo_x, hi_x = 0.0, float(W)
        if avoid is not None:  # keep the webcam overlay out of the gameplay crop when possible
            margin = 0.02 * W  # overlay borders/shadows extend slightly beyond the detected region
            ax0, ax1 = max(0.0, avoid.x * W - margin), min(float(W), (avoid.x + avoid.w) * W + margin)
            if ax1 < W / 2 and W - ax1 >= cw:
                lo_x = ax1
            elif ax0 > W / 2 and ax0 >= cw:
                hi_x = ax0
        x0 = float(np.clip(cx * W - cw / 2, lo_x, hi_x - cw))
        y0 = float(np.clip(cy * H - ch / 2, 0, H - ch))
        s = box.w / cw
        M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
        if interp == cv2.INTER_AREA:  # warpAffine has no area filter: crop + resize instead
            crop = frame[int(y0):int(y0 + ch), int(x0):int(x0 + cw)]
            return cv2.resize(crop, (box.w, box.h), interpolation=cv2.INTER_AREA)
        return cv2.warpAffine(frame, M, (box.w, box.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def _fit(self, frame: np.ndarray, box: Box, zoom: float) -> np.ndarray:
        H, W = frame.shape[:2]
        small = cv2.resize(frame, (max(16, W // 10), max(16, H // 10)), interpolation=cv2.INTER_AREA)
        bg = self._crop_cover(cv2.GaussianBlur(small, (0, 0), 6), box, 0.5, 0.5, 1.0, None)
        bg = (bg.astype(np.float32) * 0.45).astype(np.uint8)
        fw = int(box.w * zoom) // 2 * 2
        fh = int(round(fw * H / W)) // 2 * 2
        fg = cv2.resize(frame, (fw, fh), interpolation=cv2.INTER_AREA if fw < W else cv2.INTER_LINEAR)
        x = (box.w - fw) // 2
        y = int(box.h * 0.42 - fh / 2)
        # paste with clipping (zoom may exceed the box width)
        sx0, sy0 = max(0, -x), max(0, -y)
        dx0, dy0 = max(0, x), max(0, y)
        w = min(fw - sx0, box.w - dx0)
        h = min(fh - sy0, box.h - dy0)
        bg[dy0:dy0 + h, dx0:dx0 + w] = fg[sy0:sy0 + h, sx0:sx0 + w]
        return bg

    def _webcam_crop(self, frame: np.ndarray, box: Box) -> np.ndarray:
        H, W = frame.shape[:2]
        r = self.webcam
        assert r is not None
        x0, y0, rw, rh = r.x * W, r.y * H, r.w * W, r.h * H
        A = box.w / box.h
        if rw / rh > A:   # region wider than box: trim sides
            nw = rh * A
            x0 += (rw - nw) / 2
            rw = nw
        else:             # region taller: trim top/bottom (keep the upper part: faces sit high)
            nh = rw / A
            y0 += (rh - nh) * 0.35
            rh = nh
        crop = frame[int(y0):int(y0 + rh), int(x0):int(x0 + rw)]
        if crop.size == 0:
            return np.zeros((box.h, box.w, 3), np.uint8)
        interp = cv2.INTER_AREA if crop.shape[1] > box.w else cv2.INTER_CUBIC
        return cv2.resize(crop, (box.w, box.h), interpolation=interp)

    # ------------------------------------------------------------- compose
    def compose(self, frame: np.ndarray, t: float) -> np.ndarray:
        cfg = self.cfg
        out = np.zeros((OUT_H, OUT_W, 3), np.uint8)
        env = self.zoom_fn(t) if cfg.zoom else 0.0
        zoom = 1.0 + (cfg.zoom_strength - 1.0) * env
        gbox = self.gameplay_box(t)
        if cfg.crop_mode == "fit":
            g = self._fit(frame, gbox, 1.0 + (zoom - 1.0) * 0.6)
        else:
            cx, cy = self.path.at(t) if cfg.crop_mode == "smart" else (0.5, 0.5)
            avoid = self.webcam if cfg.hide_webcam_in_gameplay else None
            g = self._crop_cover(frame, gbox, cx, cy, zoom, avoid)
        out[gbox.y:gbox.y + gbox.h, gbox.x:gbox.x + gbox.w] = g

        wbox = self.webcam_box(t)
        if wbox is not None:
            cam = self._webcam_crop(frame, wbox)
            if cfg.layout == "pip":
                key = (wbox.w, wbox.h)
                if self._pip_cache is None or self._pip_cache[0] != key:
                    self._pip_cache = (key, _rounded_mask(wbox.w, wbox.h, 28),
                                       _rounded_mask(wbox.w + 10, wbox.h + 10, 33))
                _, mask, ring = self._pip_cache
                # accent ring
                rx, ry = wbox.x - 5, wbox.y - 5
                region = out[ry:ry + wbox.h + 10, rx:rx + wbox.w + 10].astype(np.float32)
                ring_col = np.array(ACCENT_B, np.float32)
                out[ry:ry + wbox.h + 10, rx:rx + wbox.w + 10] = (region * (1 - ring) + ring_col * ring).astype(np.uint8)
                region = out[wbox.y:wbox.y + wbox.h, wbox.x:wbox.x + wbox.w].astype(np.float32)
                out[wbox.y:wbox.y + wbox.h, wbox.x:wbox.x + wbox.w] = (region * (1 - mask) + cam * mask).astype(np.uint8)
            else:
                out[wbox.y:wbox.y + wbox.h, wbox.x:wbox.x + wbox.w] = cam
                y = max(0, wbox.y - DIVIDER // 2)
                out[y:y + DIVIDER] = self.divider[: min(DIVIDER, OUT_H - y)]
        return out


def card_from(frame: np.ndarray) -> np.ndarray:
    """Background for intro/outro title cards: blurred, darkened still."""
    small = cv2.resize(frame, (OUT_W // 6, OUT_H // 6), interpolation=cv2.INTER_AREA)
    blur = cv2.resize(cv2.GaussianBlur(small, (0, 0), 5), (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)
    return (blur.astype(np.float32) * 0.4).astype(np.uint8)


def blend(a: np.ndarray, b: np.ndarray, alpha: float) -> np.ndarray:
    """alpha=0 → a, alpha=1 → b."""
    return cv2.addWeighted(a, 1 - alpha, b, alpha, 0)
