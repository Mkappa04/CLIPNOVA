"""What is visible in a clip: a local vision model (Ollama, default qwen3.5:4b) describes 4 frames.

Factual only (setting, people, action, on-screen text). Names are allowed only if readable on screen.
The result is a hint for the metadata generator — treated as possibly wrong — and cached per clip range.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from pathlib import Path

import cv2
import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.clip_detection.pipeline import cache_dir
from backend.core.config import get_settings
from backend.editing.frames import grab_frame
from backend.models.entities import Clip

log = logging.getLogger(__name__)

VERSION = 1

PROMPT = """Questi sono {n} fotogrammi in ordine temporale di una clip video ({duration:.0f} s).
Descrivi in modo FATTUALE cosa si vede. Non inventare: nomi di persone, personaggi, squadre o luoghi solo se sono
scritti a schermo. Se un dettaglio non è chiaro, dillo. Scrivi in italiano.

Rispondi SOLO con JSON:
{{"setting": "ambiente/scena", "people": "chi/quanti si vedono e come (senza nomi inventati)",
 "action": "cosa succede tra i fotogrammi", "on_screen_text": "testo leggibile a schermo o \\"\\"",
 "kind": "videogioco|sport|persona che parla|podcast/intervista|altro",
 "has_facecam": true/false, "confidence": 0.0-1.0}}"""


class VisualDescription(BaseModel):
    setting: str = ""
    people: str = ""
    action: str = ""
    on_screen_text: str = ""
    kind: str = "altro"
    has_facecam: bool = False
    confidence: float = Field(0.5, ge=0, le=1)

    @field_validator("setting", "people", "action", "on_screen_text", "kind", mode="before")
    @classmethod
    def _text(cls, v) -> str:
        return " ".join(str(v or "").split())[:300]

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v) -> float:
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


def vision_model() -> str | None:
    """The configured vision model if installed (None → no visual description)."""
    s = get_settings()
    if s.semantic_scoring == "off" or not s.vision_model:
        return None
    try:
        r = httpx.post(f"{s.llm_url}/api/show", json={"model": s.vision_model}, timeout=5)
        r.raise_for_status()
        return s.vision_model if "vision" in (r.json().get("capabilities") or []) else None
    except (httpx.HTTPError, ValueError):
        return None


def _cache_path(clip: Clip) -> Path:
    key = hashlib.sha1(f"{VERSION}:{clip.start:.2f}:{clip.end:.2f}".encode()).hexdigest()[:10]
    return cache_dir(clip.video_id) / f"visual_{clip.id[:12]}_{key}.json"


def frame_times(clip: Clip, n: int = 4) -> list[float]:
    """Spread over the clip, one of them on the peak when known."""
    d = clip.duration
    ts = [clip.start + d * f for f in (0.12, 0.4, 0.65, 0.9)][:n]
    if clip.peak_time and clip.start < clip.peak_time < clip.end:
        ts[1] = clip.peak_time
    return sorted(ts)


def describe(clip: Clip, *, client: httpx.Client | None = None, model: str | None = None,
             use_cache: bool = True) -> dict:
    """VisualDescription dict, {} when no vision model / frames unavailable."""
    path = _cache_path(clip)
    if use_cache and path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    model = model or vision_model()
    if not model:
        return {}
    video = clip.video
    images = []
    for t in frame_times(clip):
        try:
            f = grab_frame(Path(video.file_path), t, video.width or 1920, video.height or 1080, max_w=640)
        except Exception as e:  # noqa: BLE001 - a missing frame is not fatal
            log.debug("frame %.1f failed: %s", t, e)
            continue
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            images.append(base64.b64encode(buf.tobytes()).decode())
    if not images:
        return {}
    s = get_settings()
    from backend.clip_detection.semantic import _generate_raw

    own = client is None
    client = client or httpx.Client(timeout=s.llm_timeout_s)
    t0 = time.monotonic()
    try:
        raw = _generate_raw(client, {"model": model, "prompt": PROMPT.format(n=len(images), duration=clip.duration),
                                     "images": images, "stream": False, "format": "json", "think": False,
                                     "keep_alive": 0, "options": {"temperature": 0.1, "num_ctx": 4096}})
        desc = VisualDescription.model_validate(raw).model_dump()
    except (httpx.HTTPError, ValueError, ValidationError) as e:
        log.info("Vision description failed: %s", e)
        return {}
    finally:
        if own:
            client.close()
    desc["model"] = model
    desc["elapsed_s"] = round(time.monotonic() - t0, 1)
    try:
        path.write_text(json.dumps(desc, ensure_ascii=False))
    except OSError:
        pass
    return desc
