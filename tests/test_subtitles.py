import subprocess

from backend.subtitles.ass import ass_color, ass_time, build_ass, build_srt, wrap
from backend.subtitles.cues import build_cues, retime_words, validate_cues
from backend.subtitles.presets import FONTS_DIR, PRESETS


def words(text, start=0.0, step=0.4):
    return [{"start": start + i * step, "end": start + i * step + 0.35, "word": w} for i, w in enumerate(text.split())]


def test_cue_chunking_respects_limits_and_sentences():
    ws = words("ciao a tutti. oggi facciamo una rapina in banca pazzesca")
    cues = build_cues(ws, max_words=3, max_chars=18)
    assert cues[0]["text"] == "ciao a tutti."  # sentence end closes the cue
    assert all(len(c["words"]) <= 3 for c in cues)
    assert sum(len(c["words"]) for c in cues) == len(ws)


def test_cue_splits_on_long_gap():
    ws = words("prima parte", 0) + words("dopo pausa", 5)
    cues = build_cues(ws, max_words=10, max_chars=40)
    assert [c["text"] for c in cues] == ["prima parte", "dopo pausa"]


def test_retime_and_validate():
    cue = {"start": 1.0, "end": 3.0, "text": "uno due", "words": words("one two", 1.0)}
    same = retime_words({**cue, "text": "UNO DUE"})
    assert [w["start"] for w in same["words"]] == [w["start"] for w in cue["words"]]
    spread = retime_words({**cue, "text": "uno due tre quattro"})
    assert len(spread["words"]) == 4 and spread["words"][-1]["end"] <= 3.0 + 1e-6
    out = validate_cues([{"start": 5, "end": 4, "text": "x"}, {"start": 2, "end": 99, "text": " ok "},
                         {"start": 0, "end": 1, "text": ""}], clip_duration=10)
    assert len(out) == 1 and out[0]["end"] == 10 and out[0]["text"] == "ok"


def test_ass_highlight_one_event_per_word_and_escaping():
    cues = [{"start": 0.0, "end": 1.2, "text": "a {b} c", "words": words("a {b} c")}]
    ass = build_ass(cues, PRESETS["gaming"], highlight=True)
    events = [ln for ln in ass.splitlines() if ln.startswith("Dialogue: 0")]
    assert len(events) == 3
    assert "{b}" not in ass.split("[Events]")[1].replace("{\\", "")  # braces from text are neutralised
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Anton" in ass and ass_color("#22D3EE") in ass
    plain = build_ass(cues, PRESETS["clean"], highlight=False)
    assert len([ln for ln in plain.splitlines() if ln.startswith("Dialogue: 0")]) == 1


def test_formats_and_wrap():
    assert ass_time(3725.456) == "1:02:05.46"
    assert ass_color("#FF8000") == "&H000080FF"
    srt = build_srt([{"start": 1.5, "end": 2.25, "text": "ciao"}])
    assert srt.startswith("1\n00:00:01,500 --> 00:00:02,250\nciao")
    assert len(wrap("uno due tre quattro cinque sei sette".split(), 12, 2)) == 2


def test_preset_fonts_are_available():
    found = subprocess.run(["fc-scan", "--format", "%{family}\n", *map(str, FONTS_DIR.glob("*.ttf"))],
                           capture_output=True, text=True).stdout
    system = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    for p in PRESETS.values():
        assert p.font in found or p.font in system, p.font


def test_emoji_removed_from_burned_text():
    from backend.subtitles.ass import escape

    assert escape("“Ma che fai” 😂 | GTA 6 😮‍💨 perché 🔥") == "“Ma che fai” | GTA 6 perché"
    ass = build_ass([], PRESETS["gaming"], titles=[(0, 1, "Segui! 🔥")])
    assert "🔥" not in ass and "Segui!" in ass
