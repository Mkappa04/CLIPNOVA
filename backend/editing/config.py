"""Per-clip edit configuration (stored in Clip.edit_config)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

OUT_W, OUT_H = 1080, 1920

Layout = Literal["full", "stack", "pip", "split"]
PresetId = Literal["custom", "gaming_dynamic", "gaming_cinematic", "sports_highlights", "podcast_clean", "storytelling"]
LookChoice = Literal["auto", "none", "teal_orange", "warm", "cool", "punchy", "bw", "cinematic", "vivid"]
MusicMoodChoice = Literal["auto", "cinematic", "dynamic", "electronic", "chill", "dramatic", "gaming"]
HEX = r"^#[0-9A-Fa-f]{6}$"
FpsChoice = Literal["auto", 24, 25, 30, 50, 60]
LAYOUT_NEEDS_WEBCAM = {"stack", "pip", "split"}


class Region(BaseModel):
    """Normalised rectangle in the source frame (0..1)."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0.01, le=1)
    h: float = Field(gt=0.01, le=1)
    source: Literal["auto", "manual"] = "manual"
    confidence: float = Field(1.0, ge=0, le=1)

    @model_validator(mode="after")
    def _inside(self) -> Region:
        self.w = min(self.w, 1 - self.x)
        self.h = min(self.h, 1 - self.y)
        return self


class EditConfig(BaseModel):
    # Editing preset: decides the AI planner policy (which effects, how often, how strong). "custom" = the
    # pre-1.2 behaviour (punch-in zoom on the clip peak and the strongest audio spikes).
    preset: PresetId = "custom"
    intensity: float = Field(0.6, ge=0, le=1, description="Overall effect intensity (scales every planned effect)")
    planner: Literal["auto", "rules"] = Field(
        "auto", description="auto = local LLM (Ollama) refines the rule-based plan when available; rules = rules only")
    # Layout A=full, B=stack (gameplay top, webcam bottom), C=pip, D=split (dynamic 50/50)
    layout: Layout = "full"
    crop_mode: Literal["smart", "center", "fit"] = Field(
        "smart", description="smart = follow the subject; center = fixed; fit = whole frame on blurred background")
    subject: Literal["action", "faces", "auto"] = Field(
        "action", description="What smart crop follows: on-screen motion, people's faces, or faces when reliable")
    follow_speed: float = Field(1.0, ge=0.5, le=2.5, description="Virtual camera speed (sports: faster)")
    webcam_region: Region | None = Field(None, description="Override of the video's webcam region")
    hide_webcam_in_gameplay: bool = Field(True, description="Avoid framing the webcam overlay in the gameplay crop")
    pip_corner: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "top-right"
    pip_size: float = Field(0.36, ge=0.2, le=0.6, description="PiP width as fraction of the output width")
    stack_ratio: float = Field(0.6, ge=0.4, le=0.75, description="Gameplay height share in stack layout")

    zoom: bool = True
    zoom_strength: float = Field(1.18, ge=1.0, le=1.6)
    transitions: bool = True
    effects: bool = True                  # flash / shake chosen by the planner (never random)
    caption_emphasis: bool = True         # highlight the important words chosen by the planner
    sfx: bool = False                     # contextual sound effects (licensed/generated library only)
    sfx_volume: float = Field(0.5, ge=0, le=1)
    logo: bool = True                     # apply the Brand Kit logo (if one is configured and enabled)

    # 2.0 — AI Video Director (all off in "custom": the presets switch them on)
    time_effects: bool = False            # slow motion / speed ramp / freeze frame where the Director sees fit
    motion_graphics: bool = False         # animated hook title + callouts chosen by the Director
    watermark: bool = True                # Brand Kit text watermark (if configured)
    look: LookChoice = Field("none", description="Colour grade; auto = chosen by the Director within the preset")
    vignette: bool = True                 # allow the vignette of the chosen look
    music: Literal["auto", "off"] = Field("off", description="auto = the Director picks a licensed track; off = original audio only")
    music_mood: MusicMoodChoice = "auto"
    music_track: str | None = Field(None, max_length=40, description="Audio library asset id (None = Director's choice)")
    music_volume: float = Field(0.5, ge=0, le=1, description="0.5 = preset level; 0 = silent, 1 = +6 dB")
    music_ducking: float = Field(0.6, ge=0, le=1, description="How much the music drops while someone speaks")
    slowmo_audio: Literal["muffle", "tempo", "mute"] = Field(
        "muffle", description="Original audio during slow motion: muffled + slowed, slowed only, or silent")
    disabled_items: list[str] = Field(default_factory=list, max_length=200,
                                      description="Plan item ids switched off by the user")

    remove_silences: bool = False
    silence_strategy: Literal["quiet", "no_speech"] = Field(
        "quiet", description="quiet = cut only pauses that are also quiet; no_speech = cut every pause in speech")
    min_silence_s: float = Field(0.8, ge=0.3, le=10)
    silence_padding_s: float = Field(0.15, ge=0, le=1)

    normalize_audio: bool = True
    target_lufs: float = Field(-14.0, ge=-30, le=-8)
    denoise: bool = False

    subtitles: bool = True
    subtitle_preset: Literal["clean", "gaming", "viral"] = "gaming"
    subtitle_position: Literal["auto", "top", "middle", "bottom"] = "auto"
    subtitle_scale: float = Field(1.0, ge=0.6, le=1.6)
    highlight_words: bool = True
    subtitle_font: Literal["preset", "Anton", "Luckiest Guy", "Lato"] = "preset"
    subtitle_color: str | None = Field(None, pattern=HEX)
    subtitle_highlight_color: str | None = Field(None, pattern=HEX)
    subtitle_animation: Literal["preset", "none", "pop", "bounce"] = "preset"

    intro: bool = False
    intro_text: str = Field("", max_length=120, description="Empty = clip title")
    intro_duration: float = Field(1.2, ge=0.5, le=5)
    outro: bool = False
    outro_text: str = Field("Segui per altre clip!", max_length=120)
    outro_duration: float = Field(1.6, ge=0.5, le=5)

    fps: FpsChoice = 30  # "auto" = same as the source (nearest standard rate, max 60)
    quality: Literal["draft", "standard", "high"] = "standard"


STANDARD_FPS = (24, 25, 30, 50, 60)


def resolve_fps(choice: FpsChoice, source_fps: float | None) -> int:
    if choice != "auto":
        return int(choice)
    if not source_fps or source_fps <= 0:
        return 30
    return min(STANDARD_FPS, key=lambda f: (abs(f - source_fps), -f))


def default_config_for(has_webcam: bool) -> EditConfig:
    return EditConfig(layout="stack" if has_webcam else "full")
