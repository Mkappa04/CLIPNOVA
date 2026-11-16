"""Visual Effects Engine: parameterised frame effects (numpy / OpenCV) applied to the composed 1080x1920 frame.

Every effect is a pure function of (frame, parameters, local time) — deterministic (glitch noise is seeded
by the time), so previews and renders match and tests can check pixels. ``FrameFX`` wires the effects of
one plan together; precomputed tables (colour LUTs, vignette mask) keep the per-frame cost low.

Catalogue (``CATALOG``) — what exists and where it is applied:

=================  ==========================================================================
dynamic zoom       compositor (punch / progressive / subtle zoom envelopes from the plan)
smooth zoom        compositor (subtle_zoom ease in/out) + freeze-frame push-in
camera shake       ``shake`` (decaying, deterministic offsets)
slow motion        timeline time remapping + frame blending (renderer)
speed ramping      timeline: eased speed steps into and out of the moment (renderer)
motion blur        ``motion_blur`` (temporal blend with the previous output frame) and ``zoom_blur``
flash              ``flash`` (white, eased decay)
blur               ``blur`` (fast downscaled gaussian; used by transitions and freeze frames)
glitch             ``glitch`` (RGB split, slice displacement, scanlines)
freeze frame       timeline hold + ``freeze_look`` (push-in, desaturation, white edge)
transitions        ``transition`` (crossfade, zoom blur, flash, glitch, dip to black)
color grading      ``Grade`` (per-look channel curves + saturation + contrast, mixed by intensity)
vignette           ``Grade`` (radial mask)
crop / reframing   compositor + reframe.py (subject tracking, faces, virtual camera)
=================  ==========================================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from backend.editing.config import OUT_H, OUT_W

CATALOG = [
    {"id": "dynamic_zoom", "name": "Dynamic Zoom", "params": ["intensità", "durata", "tipo (rapido/progressivo)"],
     "where": "compositor"},
    {"id": "smooth_zoom", "name": "Smooth Zoom In/Out", "params": ["intensità", "durata"], "where": "compositor"},
    {"id": "shake", "name": "Camera Shake", "params": ["intensità", "durata", "frequenza"], "where": "vfx"},
    {"id": "slow_motion", "name": "Slow Motion", "params": ["velocità", "inizio", "fine"], "where": "timeline"},
    {"id": "speed_ramp", "name": "Speed Ramping", "params": ["velocità minima", "durata rampa"], "where": "timeline"},
    {"id": "motion_blur", "name": "Motion Blur", "params": ["intensità"], "where": "vfx"},
    {"id": "flash", "name": "Flash", "params": ["intensità", "durata"], "where": "vfx"},
    {"id": "blur", "name": "Blur", "params": ["raggio"], "where": "vfx"},
    {"id": "glitch", "name": "Glitch", "params": ["intensità", "durata"], "where": "vfx"},
    {"id": "freeze_frame", "name": "Freeze Frame", "params": ["durata", "push-in"], "where": "timeline + vfx"},
    {"id": "transitions", "name": "Transizioni dinamiche", "params": ["tipo", "durata"], "where": "vfx"},
    {"id": "color_grading", "name": "Color Grading", "params": ["look", "intensità"], "where": "vfx"},
    {"id": "vignette", "name": "Vignette", "params": ["intensità"], "where": "vfx"},
    {"id": "reframing", "name": "Crop e reframing intelligente", "params": ["soggetto", "velocità camera"],
     "where": "compositor"},
]


# ------------------------------------------------------------------ colour
def _curve(x: np.ndarray, lift: float = 0.0, gamma: float = 1.0, gain: float = 1.0) -> np.ndarray:
    y = np.clip(x * gain + lift, 0, 1)
    return np.power(y, 1.0 / max(0.05, gamma))


def _s_curve(x: np.ndarray, k: float) -> np.ndarray:
    """Contrast S-curve around mid-grey (k = 0 identity)."""
    return np.clip(x + k * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 2, 0, 1)


# per look: ((B curve), (G curve), (R curve)) as (lift, gamma, gain), contrast k, saturation
LOOKS: dict[str, dict] = {
    "teal_orange": {"b": (0.04, 1.0, 0.92), "g": (0.0, 1.02, 0.98), "r": (-0.02, 1.0, 1.06), "contrast": 0.18,
                    "sat": 1.12, "label": "Teal & orange"},
    "warm": {"b": (0.0, 0.96, 0.92), "g": (0.0, 1.0, 0.99), "r": (0.02, 1.03, 1.04), "contrast": 0.08, "sat": 1.05,
             "label": "Caldo"},
    "cool": {"b": (0.02, 1.03, 1.05), "g": (0.0, 1.0, 1.0), "r": (0.0, 0.97, 0.94), "contrast": 0.1, "sat": 0.98,
             "label": "Freddo"},
    "punchy": {"b": (0.0, 1.0, 1.0), "g": (0.0, 1.0, 1.0), "r": (0.0, 1.0, 1.0), "contrast": 0.28, "sat": 1.22,
               "label": "Deciso"},
    "bw": {"b": (0.0, 1.0, 1.0), "g": (0.0, 1.0, 1.0), "r": (0.0, 1.0, 1.0), "contrast": 0.25, "sat": 0.0,
           "label": "Bianco e nero"},
    "cinematic": {"b": (0.035, 0.98, 0.95), "g": (0.01, 0.99, 0.97), "r": (0.0, 1.0, 1.02), "contrast": 0.22,
                  "sat": 0.88, "label": "Cinematografico"},
    "vivid": {"b": (0.0, 1.0, 1.02), "g": (0.0, 1.0, 1.02), "r": (0.0, 1.0, 1.02), "contrast": 0.15, "sat": 1.3,
              "label": "Vivido"},
}


class Grade:
    """Colour look + vignette, precomputed. intensity 0 → identity."""

    def __init__(self, look: str = "none", intensity: float = 0.6, vignette: float = 0.0,
                 size: tuple[int, int] = (OUT_W, OUT_H)) -> None:
        self.look = look if look in LOOKS else "none"
        self.k = float(np.clip(intensity, 0, 1))
        self.v = float(np.clip(vignette, 0, 1))
        self.lut: np.ndarray | None = None
        self.sat = 1.0
        if self.look != "none" and self.k > 0:
            p = LOOKS[self.look]
            x = np.arange(256) / 255.0
            chans = [_s_curve(_curve(x, *p[c]), p["contrast"]) for c in ("b", "g", "r")]
            lut = np.stack(chans, axis=1)                     # (256, 3) in BGR
            lut = x[:, None] * (1 - self.k) + lut * self.k
            self.lut = np.clip(lut * 255 + 0.5, 0, 255).astype(np.uint8).reshape(256, 1, 3)
            self.sat = 1 + (p["sat"] - 1) * self.k
        self.mask: np.ndarray | None = None
        if self.v > 0:
            w, h = size
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
            m = 1 - self.v * 0.75 * np.clip((r - 0.35) / 0.65, 0, 1) ** 1.6
            self.mask = cv2.merge([np.clip(m * 255, 0, 255).astype(np.uint8)] * 3)

    @property
    def active(self) -> bool:
        return self.lut is not None or self.mask is not None

    def __call__(self, img: np.ndarray) -> np.ndarray:
        if self.lut is not None:
            img = cv2.LUT(img, self.lut)
            if abs(self.sat - 1) > 0.01:
                img = saturate(img, self.sat)
        if self.mask is not None and self.mask.shape[:2] == img.shape[:2]:
            img = cv2.multiply(img, self.mask, scale=1 / 255)
        return img


def saturate(img: np.ndarray, s: float) -> np.ndarray:
    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(img, s, gray, 1 - s, 0)


# ------------------------------------------------------------------ frame effects
def flash(img: np.ndarray, amount: float) -> np.ndarray:
    if amount <= 0.01:
        return img
    return cv2.addWeighted(img, 1 - amount, np.full_like(img, 255), amount, 0)


def shake(img: np.ndarray, dx: int, dy: int, scale: float = 1.03) -> np.ndarray:
    if not dx and not dy:
        return img
    h, w = img.shape[:2]
    M = np.float32([[scale, 0, dx - w * (scale - 1) / 2], [0, scale, dy - h * (scale - 1) / 2]])
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def blur(img: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0.5:
        return img
    h, w = img.shape[:2]
    f = 4
    small = cv2.resize(img, (w // f, h // f), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(0.5, radius / f))
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def zoom_blur(img: np.ndarray, amount: float, zoom: float = 1.0, taps: int = 4) -> np.ndarray:
    """Radial blur toward the centre (whip / punch feel). amount 0..1."""
    h, w = img.shape[:2]
    if amount <= 0.02 and zoom <= 1.001:
        return img
    acc = np.zeros(img.shape, np.float32)
    for k in range(taps):
        s = zoom * (1 + amount * 0.08 * k / max(1, taps - 1))
        M = np.float32([[s, 0, w / 2 * (1 - s)], [0, s, h / 2 * (1 - s)]])
        acc += cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
    return (acc / taps).astype(np.uint8)


def motion_blur(img: np.ndarray, prev: np.ndarray | None, amount: float) -> np.ndarray:
    """Temporal motion blur: blend with the previous output frame (amount 0..0.6)."""
    if prev is None or amount <= 0.02 or prev.shape != img.shape:
        return img
    return cv2.addWeighted(img, 1 - amount, prev, amount, 0)


def glitch(img: np.ndarray, amount: float, seed: int) -> np.ndarray:
    """RGB split + horizontal slice displacement + scanlines. Deterministic for a given seed."""
    if amount <= 0.02:
        return img
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    out = img.copy()
    dx = int(6 + 26 * amount)
    out[:, :, 2] = np.roll(img[:, :, 2], dx, axis=1)       # red right
    out[:, :, 0] = np.roll(img[:, :, 0], -dx // 2, axis=1)  # blue left
    for _ in range(int(3 + 7 * amount)):
        y0 = int(rng.integers(0, h - 20))
        hh = int(rng.integers(8, max(9, int(h * 0.06 * amount) + 10)))
        shift = int(rng.integers(-1, 2) * rng.integers(10, 10 + int(120 * amount)))
        out[y0:y0 + hh] = np.roll(out[y0:y0 + hh], shift, axis=1)
    if amount > 0.3:
        out[::4] = (out[::4].astype(np.uint16) * 7 // 10).astype(np.uint8)
    return out


def freeze_look(img: np.ndarray, progress: float, intensity: float = 0.7) -> np.ndarray:
    """Freeze frame: gentle push-in, desaturation and a white edge that fades in. progress 0..1 of the hold."""
    h, w = img.shape[:2]
    s = 1 + 0.06 * intensity * min(1.0, progress * 1.2)
    M = np.float32([[s, 0, w / 2 * (1 - s)], [0, s, h / 2 * (1 - s)]])
    out = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
    out = saturate(out, 1 - 0.55 * intensity)
    edge = int(10 + 8 * intensity)
    a = min(1.0, progress * 4)
    if a > 0:
        frame = out.copy()
        cv2.rectangle(frame, (edge, edge), (w - edge, h - edge), (255, 255, 255), edge)
        out = cv2.addWeighted(out, 1 - a, frame, a, 0)
    return out


def transition(img: np.ndarray, kind: str, x: float, seed: int = 0) -> np.ndarray:
    """One frame of a cut transition. x in [-1, 1]: signed distance to the cut (0 = the cut frame).
    'crossfade' needs the previous shot and is blended by the renderer; here it is a no-op."""
    p = max(0.0, 1.0 - abs(x))          # 1 at the cut, 0 at the edges
    if p <= 0:
        return img
    if kind == "zoom_blur":
        return zoom_blur(img, p, zoom=1 + 0.18 * p * p)
    if kind == "flash":
        return flash(img, 0.9 * p * p)
    if kind == "glitch":
        return glitch(img, p, seed)
    if kind == "dip":
        return (img.astype(np.float32) * (1 - p)).astype(np.uint8)
    return img


@dataclass
class CutFx:
    t_out: float          # output time of the cut
    kind: str
    duration: float


class FrameFX:
    """All plan-driven frame effects for one render (except zoom/reframing, done by the compositor)."""

    def __init__(self, plan, cfg) -> None:
        from backend.editing import planner as pl

        self.plan = plan
        self._pl = pl
        look = plan.look
        self.grade = Grade(look.grade, look.intensity, look.vignette if cfg.vignette else 0.0)
        self.glitches = [s for s in plan.segments if s.effect == "glitch"]
        self.cuts: list[CutFx] = []
        self._prev: np.ndarray | None = None

    def accents(self, img: np.ndarray, t_src: float, frame_seed: int) -> np.ndarray:
        """Shake, flash, glitch at clip-relative source time t_src."""
        dx, dy = self._pl.shake_offset(self.plan, t_src)
        if dx or dy:
            img = shake(img, dx, dy)
            img = motion_blur(img, self._prev, 0.35)
        a = self._pl.flash_amount(self.plan, t_src)
        if a > 0.01:
            img = flash(img, a)
        for g in self.glitches:
            if g.start <= t_src <= g.end:
                local = (t_src - g.start) / max(0.05, g.end - g.start)
                # bursts: strong at the start, flickering after
                amt = g.intensity * (1 - local) * (1.0 if (frame_seed // 2) % 3 else 0.35)
                img = glitch(img, amt, frame_seed)
        return img

    def cut_effect(self, img: np.ndarray, t_out: float, frame_seed: int) -> np.ndarray:
        for c in self.cuts:
            half = c.duration / 2
            if c.kind != "crossfade" and abs(t_out - c.t_out) <= half:
                img = transition(img, c.kind, (t_out - c.t_out) / max(1e-3, half), frame_seed)
        return img

    def finish(self, img: np.ndarray) -> np.ndarray:
        img = self.grade(img) if self.grade.active else img
        self._prev = img
        return img
