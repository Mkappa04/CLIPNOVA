"""Subtitle style presets. Fonts: Lato (system), Anton (OFL), Luckiest Guy (Apache-2.0) in assets/fonts.

Safe area for 1080x1920 (TikTok / Reels / Shorts): keep text away from the
top ~220 px (status/tabs), the bottom ~480 px (caption, buttons, music) and
~90 px from the sides (right-hand action buttons start ~120 px from the edge).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from backend.core.config import PROJECT_ROOT

FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"

SAFE_TOP = 220
SAFE_BOTTOM = 480
SAFE_SIDE = 90


@dataclass(frozen=True)
class SubtitleStyle:
    id: str
    name: str
    font: str
    size: int
    bold: bool
    uppercase: bool
    primary: str        # #RRGGBB
    highlight: str
    outline_color: str
    outline: float
    shadow: float
    shadow_color: str
    max_words: int      # words per cue
    max_chars: int      # characters per line
    max_lines: int
    position: str       # default vertical position: bottom | middle
    animation: str      # none | pop | bounce
    highlight_scale: int  # % scale of the active word
    emphasis: str = "#FFD60A"   # colour of the key words chosen by the AI planner (always visible in the cue)
    emphasis_scale: int = 106
    description: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


PRESETS: dict[str, SubtitleStyle] = {
    "clean": SubtitleStyle(
        id="clean", name="Clean Captions", font="Lato", size=66, bold=True, uppercase=False,
        primary="#FFFFFF", highlight="#FFE45C", outline_color="#000000", outline=4, shadow=1.5,
        shadow_color="#000000", max_words=7, max_chars=28, max_lines=2, position="bottom",
        animation="none", highlight_scale=100, emphasis="#5EEAD4", emphasis_scale=100,
        description="Leggibili e sobri: 2 righe in basso, parola attiva colorata, nessuna animazione"),
    "gaming": SubtitleStyle(
        id="gaming", name="Dynamic Captions", font="Anton", size=104, bold=False, uppercase=True,
        primary="#FFFFFF", highlight="#22D3EE", outline_color="#000000", outline=6, shadow=4,
        shadow_color="#7C3AED", max_words=3, max_chars=18, max_lines=1, position="middle",
        animation="pop", highlight_scale=114, emphasis="#FACC15", emphasis_scale=108,
        description="Animati: 3 parole alla volta al centro, pop, parola attiva ingrandita"),
    "viral": SubtitleStyle(
        id="viral", name="Viral (bounce)", font="Luckiest Guy", size=108, bold=False, uppercase=True,
        primary="#FFFFFF", highlight="#A3FF12", outline_color="#000000", outline=8, shadow=5,
        shadow_color="#000000", max_words=2, max_chars=14, max_lines=1, position="middle",
        animation="bounce", highlight_scale=118, emphasis="#FF4D6D", emphasis_scale=110,
        description="Massimo impatto: 2 parole, rimbalzo, colori accesi"),
}


def get_preset(name: str) -> SubtitleStyle:
    return PRESETS.get(name, PRESETS["gaming"])
