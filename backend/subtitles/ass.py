"""ASS (Advanced SubStation Alpha) and SRT writers.

Word highlighting: one Dialogue event per word interval, showing the whole cue
with the active word coloured (and scaled for the "pop"/"bounce" presets).
This renders reliably with libass and keeps karaoke timing exact.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from backend.editing.config import OUT_H, OUT_W
from backend.subtitles.presets import SAFE_BOTTOM, SAFE_SIDE, SAFE_TOP, SubtitleStyle


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def strip_emoji(text: str) -> str:
    """Remove emoji/pictographs: subtitle fonts have no glyphs for them (libass would draw boxes)."""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF or cp in (0x200D, 0xFE0F, 0xFE0E) or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF \
                or unicodedata.category(ch) == "So":
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def escape(text: str) -> str:
    text = strip_emoji(text)
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def wrap(words: list[str], max_chars: int, max_lines: int) -> list[list[int]]:
    """Group word indices into at most max_lines balanced lines."""
    if max_lines <= 1 or len(" ".join(words)) <= max_chars:
        return [list(range(len(words)))]
    total = len(" ".join(words))
    target = total / min(max_lines, max(1, -(-total // max_chars)))
    lines, cur, length = [], [], 0
    for i, w in enumerate(words):
        if cur and length + 1 + len(w) > target * 1.15 and len(lines) < max_lines - 1:
            lines.append(cur)
            cur, length = [], 0
        cur.append(i)
        length += len(w) + (1 if length else 0)
    lines.append(cur)
    return lines


@dataclass
class Placement:
    alignment: int          # numpad layout: 2 = bottom-center, 5 = middle-center, 8 = top-center
    margin_v: int
    pos_y: int | None = None  # explicit \pos y (middle-center anchor) when set


def placement_for(style: SubtitleStyle, position: str, divider_y: int | None) -> Placement:
    pos = style.position if position == "auto" else position
    if position == "auto" and divider_y is not None:
        return Placement(5, 0, divider_y)          # on the gameplay/webcam seam
    if pos == "top":
        return Placement(8, SAFE_TOP + 40)
    if pos == "middle":
        return Placement(5, 0, int(OUT_H * 0.62))   # lower-middle: above the platform UI
    return Placement(2, SAFE_BOTTOM + 60)


def _header(style: SubtitleStyle, scale: float) -> str:
    size = int(style.size * scale)
    bold = -1 if style.bold else 0
    title_size = int(style.size * 1.4)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{style.font},{size},{ass_color(style.primary)},{ass_color(style.highlight)},{ass_color(style.outline_color)},{ass_color(style.shadow_color, 0x40)},{bold},0,0,0,100,100,1,0,1,{style.outline * scale:.1f},{style.shadow * scale:.1f},2,{SAFE_SIDE},{SAFE_SIDE},{SAFE_BOTTOM + 60},1
Style: Title,{style.font},{title_size},{ass_color("#FFFFFF")},{ass_color(style.highlight)},{ass_color("#000000")},{ass_color("#000000", 0x60)},{bold},0,0,0,100,100,1,0,1,7,4,5,{SAFE_SIDE + 20},{SAFE_SIDE + 20},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(cues: list[dict], style: SubtitleStyle, *, position: str = "auto", divider_y: int | None = None,
              highlight: bool = True, scale: float = 1.0, titles: list[tuple[float, float, str]] = ()) -> str:
    """cues: output-timeline cues (seconds). titles: (start, end, text) for intro/outro cards."""
    place = placement_for(style, position, divider_y)
    lines = [_header(style, scale)]
    prefix = f"{{\\an{place.alignment}"
    prefix += f"\\pos({OUT_W // 2},{place.pos_y})" if place.pos_y is not None else ""
    prefix += "}"
    margin_v = place.margin_v
    hl = ass_color(style.highlight)
    pr = ass_color(style.primary)

    for cue in cues:
        words = [w["word"].upper() if style.uppercase else w["word"] for w in cue["words"]] or \
                [cue["text"].upper() if style.uppercase else cue["text"]]
        groups = wrap(words, style.max_chars, style.max_lines)
        entry = ""
        if style.animation == "bounce":
            entry = "{\\fscx70\\fscy70\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)}"
        elif style.animation == "pop":
            entry = "{\\fscx88\\fscy88\\t(0,80,\\fscx100\\fscy100)}"

        def render(active: int | None) -> str:
            out_lines = []
            for g in groups:
                parts = []
                for i in g:
                    w = escape(words[i])
                    if active is not None and i == active:
                        s = style.highlight_scale
                        grow = f"\\fscx{s}\\fscy{s}" if s != 100 else ""
                        parts.append(f"{{\\c{hl}{grow}}}{w}{{\\c{pr}\\fscx100\\fscy100}}")
                    else:
                        parts.append(w)
                out_lines.append(" ".join(parts))
            return "\\N".join(out_lines)

        ws = cue["words"]
        if highlight and ws and len(ws) == len(words):
            for i, w in enumerate(ws):
                start = cue["start"] if i == 0 else w["start"]
                end = ws[i + 1]["start"] if i + 1 < len(ws) else cue["end"]
                if end - start < 0.02:
                    continue
                anim = entry if i == 0 else ""
                lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,{margin_v},,"
                             f"{prefix}{anim}{render(i)}")
        else:
            lines.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},Sub,,0,0,{margin_v},,"
                         f"{prefix}{entry}{render(None)}")

    for start, end, text in titles:
        if text.strip():
            lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Title,,0,0,0,,"
                         f"{{\\an5\\pos({OUT_W // 2},{OUT_H // 2})\\fad(180,180)\\q0}}{escape(text)}")
    return "\n".join(lines) + "\n"


def build_srt(cues: list[dict]) -> str:
    blocks = [f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1)]
    return "\n".join(blocks)
