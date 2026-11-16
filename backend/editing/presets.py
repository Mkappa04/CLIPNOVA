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

from backend.editing.plan import (  # noqa: E402,F401 - re-exported for older imports
    VISUAL_ZOOMS, Effect, LookName, MusicMood, SfxCategory, Style, TimeKind, TransitionKind)


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
    # --- 2.0: AI Video Director. The preset gives the style and the budget; the Director decides inside it.
    style: Style = Field("balanced", description="Base style; the Director may go calmer when the content asks")
    allowed_time_effects: list[TimeKind] = Field(default_factory=list)
    max_time_effects: int = Field(0, ge=0, le=4)
    slowmo_speed: float = Field(0.5, ge=0.25, le=0.9)
    time_min_strength: float = Field(0.72, ge=0, le=1, description="Only moments this strong get a time effect")
    transition_kinds: list[TransitionKind] = Field(default_factory=lambda: ["crossfade"])
    transition_sfx: bool = False
    look: LookName = "none"
    look_intensity: float = Field(0.5, ge=0, le=1)
    vignette: float = Field(0.0, ge=0, le=1)
    music_moods: list[MusicMood] = Field(default_factory=list, description="Preferred moods, best first")
    music_level_db: float = Field(-21.0, ge=-36, le=-10)
    duck_db: float = Field(-10.0, ge=-24, le=0)
    overlays: list[Literal["hook_title", "callout"]] = Field(default_factory=list)
    max_callouts: int = Field(0, ge=0, le=5)


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
        "description": "Per clip di videogiochi, streamer e creator gaming: ritmo serrato, zoom e speed ramp sui "
                       "momenti decisivi, transizioni rapide, musica dinamica sotto il parlato, effetti sonori "
                       "solo sui momenti forti.",
        "features": ["Zoom contestuali", "Speed ramp", "Camera shake", "Musica dinamica", "SFX sincronizzati",
                     "Sottotitoli animati", "Taglio pause"],
        "config": {"crop_mode": "smart", "subject": "action", "follow_speed": 1.0, "zoom": True,
                   "zoom_strength": 1.28, "transitions": True, "effects": True, "caption_emphasis": True,
                   "sfx": True, "sfx_volume": 0.5, "intensity": 0.7, "remove_silences": True,
                   "silence_strategy": "quiet", "min_silence_s": 0.6, "subtitles": True,
                   "subtitle_preset": "gaming", "subtitle_position": "auto", "highlight_words": True,
                   "intro": False, "outro": False, "time_effects": True, "motion_graphics": True,
                   "look": "auto", "music": "auto", "music_mood": "auto"},
        "policy": {"allowed_effects": ["subtle_zoom", "progressive_zoom", "punch_zoom", "caption_emphasis",
                                       "flash", "shake", "glitch"],
                   "reaction_effect": "punch_zoom", "highlight_effect": "progressive_zoom",
                   "action_effect": "subtle_zoom", "max_effects_per_min": 8, "min_gap_s": 2.5,
                   "max_effect_s": 2.2, "min_strength": 0.4, "emphasis_per_min": 10, "sfx_per_min": 3,
                   "sfx_min_gap_s": 7, "sfx_min_strength": 0.65,
                   "style": "energetic", "allowed_time_effects": ["speed_ramp", "freeze_frame"], "max_time_effects": 1,
                   "slowmo_speed": 0.45, "transition_kinds": ["zoom_blur", "glitch", "crossfade"],
                   "transition_sfx": True, "look": "vivid", "look_intensity": 0.45, "vignette": 0.15,
                   "music_moods": ["gaming", "electronic", "dynamic"], "music_level_db": -20, "duck_db": -11,
                   "overlays": ["hook_title", "callout"], "max_callouts": 2},
    },
    "gaming_cinematic": {
        "name": "Gaming Cinematic",
        "description": "Per momenti epici e scene d'atmosfera: slow motion sul culmine, color grading "
                       "cinematografico, transizioni morbide, musica cinematica e impatti sonori misurati.",
        "features": ["Slow motion", "Color grading", "Transizioni morbide", "Musica cinematica",
                     "Impatti sonori", "Montaggio atmosferico"],
        "config": {"crop_mode": "smart", "subject": "action", "follow_speed": 0.8, "zoom": True,
                   "zoom_strength": 1.18, "transitions": True, "effects": True, "caption_emphasis": True,
                   "sfx": True, "sfx_volume": 0.55, "intensity": 0.6, "remove_silences": True,
                   "silence_strategy": "quiet", "min_silence_s": 0.9, "subtitles": True,
                   "subtitle_preset": "clean", "subtitle_position": "bottom", "highlight_words": False,
                   "intro": False, "outro": False, "time_effects": True, "motion_graphics": True,
                   "look": "auto", "music": "auto", "music_mood": "auto", "slowmo_audio": "muffle"},
        "policy": {"allowed_effects": ["subtle_zoom", "progressive_zoom", "caption_emphasis", "flash"],
                   "reaction_effect": "subtle_zoom", "highlight_effect": "progressive_zoom",
                   "action_effect": "progressive_zoom", "max_effects_per_min": 5, "min_gap_s": 4,
                   "max_effect_s": 3.0, "min_strength": 0.45, "emphasis_per_min": 4, "sfx_per_min": 2,
                   "sfx_min_gap_s": 9, "sfx_min_strength": 0.7,
                   "style": "cinematic", "allowed_time_effects": ["slow_motion", "speed_ramp"], "max_time_effects": 2,
                   "slowmo_speed": 0.4, "time_min_strength": 0.65, "transition_kinds": ["crossfade", "dip"],
                   "transition_sfx": False, "look": "cinematic", "look_intensity": 0.7, "vignette": 0.35,
                   "music_moods": ["cinematic", "dramatic"], "music_level_db": -19, "duck_db": -12,
                   "overlays": ["hook_title"], "max_callouts": 0},
    },
    "sports_highlights": {
        "name": "Sports Highlights",
        "description": "Per calcio e altri sport: reframing veloce che segue l'azione, slow motion sull'azione "
                       "decisiva, zoom misurati, sound design sugli eventi. Nessun taglio dentro l'azione.",
        "features": ["Reframing che segue l'azione", "Slow motion", "Zoom sulle azioni", "Sound design",
                     "Titolo iniziale", "Azione mai tagliata"],
        "config": {"crop_mode": "smart", "subject": "action", "follow_speed": 1.8, "zoom": True,
                   "zoom_strength": 1.2, "transitions": True, "effects": False, "caption_emphasis": True,
                   "sfx": True, "sfx_volume": 0.45, "intensity": 0.55, "remove_silences": False,
                   "subtitles": True, "subtitle_preset": "clean", "subtitle_position": "bottom",
                   "highlight_words": True, "intro": True, "intro_duration": 1.2, "outro": False,
                   "time_effects": True, "motion_graphics": False, "look": "auto", "music": "auto",
                   "music_mood": "auto", "slowmo_audio": "tempo"},
        "policy": {"allowed_effects": ["subtle_zoom", "progressive_zoom", "caption_emphasis"],
                   "reaction_effect": "subtle_zoom", "highlight_effect": "progressive_zoom",
                   "action_effect": "subtle_zoom", "max_effects_per_min": 5, "min_gap_s": 4,
                   "max_effect_s": 3.0, "min_strength": 0.5, "emphasis_per_min": 5, "sfx_per_min": 1.5,
                   "sfx_min_gap_s": 12, "sfx_min_strength": 0.8, "keep_dramatic_pauses": True,
                   "camera_dead_zone": 0.03, "camera_max_speed": 0.45,
                   "style": "balanced", "allowed_time_effects": ["slow_motion"], "max_time_effects": 1,
                   "slowmo_speed": 0.5, "time_min_strength": 0.7, "transition_kinds": ["crossfade"],
                   "look": "punchy", "look_intensity": 0.5, "vignette": 0.1,
                   "music_moods": ["dynamic", "electronic"], "music_level_db": -22, "duck_db": -10,
                   "overlays": [], "max_callouts": 0},
    },
    "podcast_clean": {
        "name": "Podcast Clean",
        "description": "Per podcast, interviste e video parlati: inquadratura sullo speaker, sottotitoli "
                       "leggibili, zoom leggerissimi, pause rimosse, musica discreta solo se non disturba.",
        "features": ["Inquadratura sullo speaker", "Sottotitoli puliti", "Parole chiave evidenziate",
                     "Zoom leggerissimi", "Pause rimosse", "Musica discreta"],
        "config": {"crop_mode": "smart", "subject": "faces", "follow_speed": 0.7, "zoom": True,
                   "zoom_strength": 1.1, "transitions": True, "effects": False, "caption_emphasis": True,
                   "sfx": False, "intensity": 0.45, "remove_silences": True, "silence_strategy": "no_speech",
                   "min_silence_s": 0.5, "subtitles": True, "subtitle_preset": "clean",
                   "subtitle_position": "bottom", "highlight_words": True, "intro": False, "outro": False,
                   "time_effects": False, "motion_graphics": False, "look": "auto", "music": "auto",
                   "music_mood": "auto"},
        "policy": {"allowed_effects": ["subtle_zoom", "caption_emphasis"],
                   "reaction_effect": "subtle_zoom", "highlight_effect": "subtle_zoom",
                   "action_effect": "none", "max_effects_per_min": 4, "min_gap_s": 6, "max_effect_s": 3.0,
                   "intensity_scale": 0.8, "min_strength": 0.5, "emphasis_per_min": 6, "sfx_per_min": 0,
                   "camera_dead_zone": 0.08, "camera_max_speed": 0.12,
                   "style": "minimal", "transition_kinds": ["crossfade"], "look": "warm", "look_intensity": 0.3,
                   "vignette": 0.0, "music_moods": ["chill"], "music_level_db": -27, "duck_db": -9,
                   "overlays": [], "max_callouts": 0},
    },
    "storytelling": {
        "name": "Storytelling",
        "description": "Per racconti, aneddoti e momenti narrativi: musica narrativa che segue il racconto, "
                       "ritmo variabile, transizioni coerenti, titolo di contesto quando serve, grading caldo.",
        "features": ["Musica narrativa", "Transizioni coerenti", "Ritmo variabile", "Testi contestuali",
                     "Color grading"],
        "config": {"crop_mode": "smart", "subject": "auto", "follow_speed": 0.8, "zoom": True,
                   "zoom_strength": 1.14, "transitions": True, "effects": False, "caption_emphasis": True,
                   "sfx": True, "sfx_volume": 0.4, "intensity": 0.5, "remove_silences": True,
                   "silence_strategy": "quiet", "min_silence_s": 0.8, "subtitles": True,
                   "subtitle_preset": "clean", "subtitle_position": "bottom", "highlight_words": True,
                   "intro": False, "outro": False, "time_effects": True, "motion_graphics": True,
                   "look": "auto", "music": "auto", "music_mood": "auto"},
        "policy": {"allowed_effects": ["subtle_zoom", "progressive_zoom", "caption_emphasis"],
                   "reaction_effect": "subtle_zoom", "highlight_effect": "progressive_zoom",
                   "action_effect": "none", "max_effects_per_min": 4, "min_gap_s": 5, "max_effect_s": 3.0,
                   "min_strength": 0.5, "emphasis_per_min": 6, "sfx_per_min": 1, "sfx_min_gap_s": 15,
                   "sfx_min_strength": 0.75, "keep_dramatic_pauses": True,
                   "style": "balanced", "allowed_time_effects": ["freeze_frame"], "max_time_effects": 1,
                   "time_min_strength": 0.8, "transition_kinds": ["crossfade", "dip"], "look": "warm",
                   "look_intensity": 0.5, "vignette": 0.25, "music_moods": ["cinematic", "chill"],
                   "music_level_db": -24, "duck_db": -10, "overlays": ["hook_title"], "max_callouts": 0},
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
                   "sfx_per_min": 0, "keep_dramatic_pauses": False,
                   "allowed_time_effects": ["slow_motion", "speed_ramp", "freeze_frame"], "max_time_effects": 1,
                   "transition_kinds": ["crossfade"], "music_moods": list(("cinematic", "dynamic", "electronic",
                                                                            "chill", "dramatic", "gaming")),
                   "overlays": ["hook_title", "callout"], "max_callouts": 1},
    },
}

ORDER = ["gaming_dynamic", "gaming_cinematic", "sports_highlights", "podcast_clean", "storytelling", "custom"]


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
