"""Motion Graphics Engine: animated text rendered by libass (ASS events burnt in with the subtitles).

- hook title: the clip's title at the top in the first seconds (context / hook), boxed;
- callouts: a verbatim word (spoken, on-screen text or reaction keyword) popping on the moment;
- watermark: Brand Kit text (e.g. "@handle"), low opacity, inside the safe area;
- animations: pop (scale overshoot), slide (from the side), fade, typewriter (word by word);
  every element has an entry and an exit.

Times here are OUTPUT times; the renderer maps the plan's source times. Text is escaped, emoji removed
(the fonts have no glyphs for them) and kept inside the platform safe areas.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.editing.config import OUT_H, OUT_W
from backend.subtitles.ass import ass_color, ass_time, escape
from backend.subtitles.presets import SAFE_SIDE, SAFE_TOP, SubtitleStyle

Y = {"top": SAFE_TOP + 110, "upper": int(OUT_H * 0.36), "center": OUT_H // 2}


@dataclass
class Graphic:
    kind: str           # hook_title | callout | watermark
    start: float        # output seconds
    end: float
    text: str
    animation: str = "pop"
    position: str = "upper"


def styles(sub: SubtitleStyle, accent: str = "#FF5A1F") -> list[str]:
    """Hook: boxed title (BorderStyle 3 = opaque box). Callout: big outlined word. Watermark: small, faded."""
    font = sub.font
    return [
        f"Style: Hook,{font},64,{ass_color('#FFFFFF')},{ass_color(accent)},{ass_color('#111111', 0x30)},"
        f"{ass_color('#000000', 0x80)},-1,0,0,0,100,100,0,0,3,18,0,8,{SAFE_SIDE},{SAFE_SIDE},0,1",
        f"Style: Callout,{font},132,{ass_color(sub.emphasis)},{ass_color('#FFFFFF')},{ass_color('#000000')},"
        f"{ass_color('#000000', 0x50)},-1,0,0,0,100,100,2,-4,1,9,6,5,{SAFE_SIDE},{SAFE_SIDE},0,1",
        f"Style: Watermark,Lato,38,{ass_color('#FFFFFF', 0x70)},{ass_color('#FFFFFF')},{ass_color('#000000', 0x90)},"
        f"{ass_color('#000000', 0xC0)},-1,0,0,0,100,100,1,0,1,2,0,3,{SAFE_SIDE},{SAFE_SIDE},0,1",
    ]


def _wrap(text: str, n: int = 24) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n and len(lines) < 1:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "\\N".join(escape(x) for x in lines)


def _anim(kind: str, dur_ms: int, x: int, y: int) -> str:
    out = min(220, dur_ms // 3)
    if kind == "slide":
        return f"\\move({x - 160},{y},{x},{y},0,260)\\fad(200,{out})"
    if kind == "fade":
        return f"\\pos({x},{y})\\fad(400,{max(out, 300)})"
    if kind == "typewriter":
        return f"\\pos({x},{y})\\fad(0,{out})"
    # pop: overshoot then settle, quick fade out
    return f"\\pos({x},{y})\\fscx40\\fscy40\\t(0,120,\\fscx112\\fscy112)\\t(120,220,\\fscx100\\fscy100)\\fad(60,{out})"


def events(graphics: list[Graphic]) -> list[str]:
    lines: list[str] = []
    for g in graphics:
        if g.end - g.start < 0.2 or not g.text.strip():
            continue
        dur = int((g.end - g.start) * 1000)
        x, y = OUT_W // 2, Y.get(g.position, Y["upper"])
        if g.kind == "watermark":
            lines.append(f"Dialogue: 2,{ass_time(g.start)},{ass_time(g.end)},Watermark,,0,0,0,,"
                         f"{{\\an3\\pos({OUT_W - SAFE_SIDE - 60},{OUT_H - 560})}}{escape(g.text)}")
            continue
        style = "Hook" if g.kind == "hook_title" else "Callout"
        an = "\\an8" if g.kind == "hook_title" else "\\an5"
        text = _wrap(g.text, 24) if g.kind == "hook_title" else escape(g.text.upper())
        if g.animation == "typewriter":
            words = g.text.split()
            step = min(0.18, (g.end - g.start) * 0.5 / max(1, len(words)))
            for i in range(len(words)):
                a = g.start + i * step
                b = g.start + (i + 1) * step if i + 1 < len(words) else g.end
                lines.append(f"Dialogue: 3,{ass_time(a)},{ass_time(b)},{style},,0,0,0,,"
                             f"{{{an}{_anim('typewriter', dur, x, y)}}}{escape(' '.join(words[:i + 1]))}")
            continue
        lines.append(f"Dialogue: 3,{ass_time(g.start)},{ass_time(g.end)},{style},,0,0,0,,"
                     f"{{{an}{_anim(g.animation, dur, x, y)}}}{text}")
    return lines
