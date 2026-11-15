"""Subtitle cues built from Whisper word timestamps.

A cue = {"start", "end", "text", "words": [{"start", "end", "word"}]} in
clip-relative seconds. Cues are stored on the clip when the user edits them.
"""

from __future__ import annotations

import re

from backend.transcription.whisper_engine import Transcript

_SENTENCE_END = re.compile(r"[.!?…]$")
_SOFT_BREAK = re.compile(r"[,;:]$")


def clip_words(transcript: Transcript | None, start: float, end: float) -> list[dict]:
    if transcript is None:
        return []
    out = []
    for seg in transcript.segments:
        for w in seg.words:
            if w.end <= start or w.start >= end:
                continue
            text = w.word.strip()
            if not text:
                continue
            out.append({"start": round(max(0.0, w.start - start), 3),
                        "end": round(min(end, w.end) - start, 3), "word": text})
    return out


def build_cues(words: list[dict], *, max_words: int, max_chars: int, max_lines: int = 1,
               max_gap_s: float = 0.6, max_duration_s: float = 3.5) -> list[dict]:
    cues: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        if cur:
            cues.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                         "text": " ".join(w["word"] for w in cur), "words": list(cur)})
            cur.clear()

    limit_chars = max_chars * max_lines
    for w in words:
        if cur:
            text_len = len(" ".join(x["word"] for x in cur)) + 1 + len(w["word"])
            if (len(cur) >= max_words or text_len > limit_chars or w["start"] - cur[-1]["end"] > max_gap_s
                    or w["end"] - cur[0]["start"] > max_duration_s):
                flush()
        cur.append(w)
        if _SENTENCE_END.search(w["word"]) or (_SOFT_BREAK.search(w["word"]) and len(cur) >= 2):
            flush()
    flush()

    # Close tiny gaps between cues to avoid flicker
    for a, b in zip(cues, cues[1:]):
        if 0 < b["start"] - a["end"] < 0.3:
            a["end"] = b["start"]
    return cues


def retime_words(cue: dict) -> dict:
    """After a text edit: keep word timings when the word count is unchanged, else spread evenly."""
    tokens = cue["text"].split()
    old = cue.get("words") or []
    start, end = float(cue["start"]), float(cue["end"])
    if not tokens:
        return {**cue, "words": []}
    if len(old) == len(tokens):
        words = [{**w, "word": t} for w, t in zip(old, tokens)]
    else:
        weights = [max(1, len(t)) for t in tokens]
        total = sum(weights)
        words, t = [], start
        for tok, wgt in zip(tokens, weights):
            d = (end - start) * wgt / total
            words.append({"start": round(t, 3), "end": round(t + d, 3), "word": tok})
            t += d
    return {"start": start, "end": end, "text": " ".join(tokens), "words": words}


def validate_cues(cues: list[dict], clip_duration: float) -> list[dict]:
    out = []
    for c in sorted(cues, key=lambda c: float(c["start"])):
        s, e = max(0.0, float(c["start"])), min(clip_duration, float(c["end"]))
        text = str(c.get("text", "")).strip()
        if e - s < 0.05 or not text:
            continue
        out.append(retime_words({**c, "start": round(s, 3), "end": round(e, 3), "text": text}))
    return out
