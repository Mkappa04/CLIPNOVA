"""Editing presets: named bundles of EditConfig values + an AI-planner policy.

A preset is data, not code: every value below can be overridden per installation in
``data/config/editing_presets.json`` (same shape, partial objects are merged), e.g.::

    {"gaming_dynamic": {"policy": {"max_effects_per_min": 5}, "config": {"sfx": false}}}

Applying a preset copies its ``config`` values into a clip's EditConfig (the user can still
change any of them afterwards); the ``policy`` is read by the planner at render time.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from backend.core.config import get_settings
from backend.editing.config import EditConfig, PresetId

log = logging.getLogger(__name__)

Effect = Literal["none", "subtle_zoom", "progressive_zoom", "punch_zoom", "caption_emphasis", "flash", "shake"]
VISUAL_ZOOMS = ("subtle_zoom", "progressive_zoom", "punch_zoom")
SfxCategory = Literal["whoosh", "impact", "pop", "riser", "ding"]


class PlannerPolicy(BaseModel):
    """How the planner is allowed to edit. Limits are hard caps enforced after the AI decision."""

    allowed_effects: list[Effect] = Field(default_factory=lambda: ["subtle_zoom", "punch_zoom"])
    # strongest moment kind → preferred effect (the planner may still pick "none")
    reaction_effect: Effect = "punch_zoom"    # shouting, surprise, strong keywords
    highlight_effect: Effect = "subtle_zoom"  # semantic hook / clip peak without shouting
    action_effect: Effect = "subtle_zoom"     # big on-screen motion / flashes (sports, explosions)
    max_effects_per_min: float = Field(6, ge=0, le=30)
    min_gap_s: float = Field(3.0, ge=0.5, le=30, description="Minimum time between two visual effects")
    max_effect_s: float = Field(2.5, ge=0.3, le=10)
    intensity_scale: float = Field(1.0, ge=0, le=1.5)
    min_strength: float = Field(0.45, ge=0, le=1, description="Candidates weaker than this get 'none'")
    emphasis_per_min: float = Field(8, ge=0, le=40, description="Max emphasised caption words per minute")
    sfx_per_min: float = Field(0, ge=0, le=10)
    sfx_min_gap_s: float = Field(8.0, ge=2, le=60)
    sfx_min_strength: float = Field(0.7, ge=0, le=1, description="Only the strongest moments get a sound")
    keep_dramatic_pauses: bool = True        # don't cut the pause right before a punchline / reaction
    camera_dead_zone: float = Field(0.05, ge=0.0, le=0.3)
    camera_max_speed: float = Field(0.22, ge=0.05, le=1.5, description="Crop centre speed (fraction of width / s)")


class EditingPreset(BaseModel):
    id: PresetId
    name: str
    description: str
    features: list[str] = []
    config: dict = Field(default_factory=dict, description="EditConfig values applied by the preset")
    policy: PlannerPolicy = Field(default_factory=PlannerPolicy)


_BUILTIN: dict[str, dict] = {
    "gaming_dynamic": {
        "name": "Gaming Dynamic",
        "description": "Per clip di videogiochi, streamer e creator gaming: sottotitoli animati, zoom sulle "
                       "reazioni, effetti sonori solo sui momenti forti, pause tagliate, ritmo serrato.",
        "features": ["Sottotitoli dinamici", "Parole chiave evidenziate", "Zoom su urla e sorprese",
                     "SFX contestuali", "Taglio pause", "Transizioni pulite"],
        "config": {"crop_mode": "smart", "subject": "action", "follow_speed": 1.0, "zoom": True,
                   "zoom_strength": 1.28, "transitions": True, "effects": True, "caption_emphasis": True,
                   "sfx": True, "sfx_volume": 0.5, "intensity": 0.7, "remove_silences": True,
                   "silence_strategy": "quiet", "min_silence_s": 0.6, "subtitles": True,
                   "subtitle_preset": "gaming", "subtitle_position": "auto", "highlight_words": True,
                   "intro": False, "outro": False},
        "policy": {"allowed_effects": ["subtle_zoom", "progressive_zoom", "punch_zoom", "caption_emphasis",
                                       "flash", "shake"],
                   "reaction_effect": "punch_zoom", "highlight_effect": "progressive_zoom",
                   "action_effect": "subtle_zoom", "max_effects_per_min": 8, "min_gap_s": 2.5,
                   "max_effect_s": 2.2, "min_strength": 0.4, "emphasis_per_min": 10, "sfx_per_min": 3,
                   "sfx_min_gap_s": 7, "sfx_min_strength": 0.65},
    },
    "sports_highlights": {
        "name": "Sports Highlights",
        "description": "Per calcio e altri sport: reframing veloce che segue l'azione, zoom misurati sui momenti "
                       "chiave, titoli e sottotitoli puliti. Nessun taglio dentro l'azione, nessun replay inventato.",
        "features": ["Reframing che segue l'azione", "Zoom sui momenti chiave", "Titolo iniziale",
                     "Sottotitoli puliti", "SFX rari", "Azione mai tagliata"],
        "config": {"crop_mode": "smart", "subject": "action", "follow_speed": 1.8, "zoom": True,
                   "zoom_strength": 1.2, "transitions": True, "effects": False, "caption_emphasis": True,
                   "sfx": True, "sfx_volume": 0.4, "intensity": 0.55, "remove_silences": False,
                   "subtitles": True, "subtitle_preset": "clean", "subtitle_position": "bottom",
                   "highlight_words": True, "intro": True, "intro_duration": 1.2, "outro": False},
        "policy": {"allowed_effects": ["subtle_zoom", "progressive_zoom", "caption_emphasis"],
                   "reaction_effect": "subtle_zoom", "highlight_effect": "progressive_zoom",
                   "action_effect": "subtle_zoom", "max_effects_per_min": 5, "min_gap_s": 4,
                   "max_effect_s": 3.0, "min_strength": 0.5, "emphasis_per_min": 5, "sfx_per_min": 1.5,
                   "sfx_min_gap_s": 12, "sfx_min_strength": 0.8, "keep_dramatic_pauses": True,
                   "camera_dead_zone": 0.03, "camera_max_speed": 0.45},
    },
    "podcast_clean": {
        "name": "Podcast Clean",
        "description": "Per podcast, interviste e video parlati: inquadratura sullo speaker, sottotitoli "
                       "leggibili con le parole chiave evidenziate, zoom leggerissimi, pause rimosse, nessun effetto superfluo.",
        "features": ["Inquadratura sullo speaker", "Sottotitoli puliti", "Parole chiave evidenziate",
                     "Zoom leggerissimi", "Pause rimosse", "Nessun effetto superfluo"],
        "config": {"crop_mode": "smart", "subject": "faces", "follow_speed": 0.7, "zoom": True,
                   "zoom_strength": 1.1, "transitions": True, "effects": False, "caption_emphasis": True,
                   "sfx": False, "intensity": 0.45, "remove_silences": True, "silence_strategy": "no_speech",
                   "min_silence_s": 0.5, "subtitles": True, "subtitle_preset": "clean",
                   "subtitle_position": "bottom", "highlight_words": True, "intro": False, "outro": False},
        "policy": {"allowed_effects": ["subtle_zoom", "caption_emphasis"],
                   "reaction_effect": "subtle_zoom", "highlight_effect": "subtle_zoom",
                   "action_effect": "none", "max_effects_per_min": 4, "min_gap_s": 6, "max_effect_s": 3.0,
                   "intensity_scale": 0.8, "min_strength": 0.5, "emphasis_per_min": 6, "sfx_per_min": 0,
                   "camera_dead_zone": 0.08, "camera_max_speed": 0.12},
    },
    "custom": {
        "name": "Personalizzato",
        "description": "Le tue impostazioni manuali. Il planner applica uno zoom solo sul picco della clip e sui "
                       "picchi audio più forti (comportamento classico).",
        "features": ["Impostazioni manuali"],
        "config": {},
        "policy": {"allowed_effects": ["punch_zoom"], "reaction_effect": "punch_zoom",
                   "highlight_effect": "punch_zoom", "action_effect": "punch_zoom", "max_effects_per_min": 6,
                   "min_gap_s": 4, "max_effect_s": 1.9, "min_strength": 0.5, "emphasis_per_min": 0,
                   "sfx_per_min": 0, "keep_dramatic_pauses": False},
    },
}

ORDER = ["gaming_dynamic", "sports_highlights", "podcast_clean", "custom"]


def _overrides() -> dict:
    path = get_settings().data_dir / "config" / "editing_presets.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Ignoring invalid %s: %s", path, e)
        return {}


def all_presets() -> dict[str, EditingPreset]:
    over = _overrides()
    out: dict[str, EditingPreset] = {}
    for pid in ORDER:
        base = _BUILTIN[pid]
        o = over.get(pid) or {}
        merged = {**base, **{k: v for k, v in o.items() if k in ("name", "description", "features")},
                  "config": {**base.get("config", {}), **(o.get("config") or {})},
                  "policy": {**base.get("policy", {}), **(o.get("policy") or {})}, "id": pid}
        try:
            # validate config values against EditConfig (unknown keys / bad values → ignore the override)
            EditConfig.model_validate({**merged["config"]})
            out[pid] = EditingPreset.model_validate(merged)
        except ValidationError as e:
            log.warning("Invalid override for preset %s ignored: %s", pid, e.errors()[:2])
            out[pid] = EditingPreset.model_validate({**base, "id": pid})
    return out


def get_preset(pid: str) -> EditingPreset:
    presets = all_presets()
    return presets.get(pid) or presets["custom"]


def apply_preset(cfg: EditConfig, pid: str) -> EditConfig:
    """Preset values over the current config (layout, webcam and text choices are kept)."""
    p = get_preset(pid)
    return EditConfig.model_validate({**cfg.model_dump(), **p.config, "preset": p.id})
