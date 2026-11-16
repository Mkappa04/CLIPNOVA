"""AI Editing Planner, presets, SFX library/mixing, caption emphasis, subject tracking (unit level)."""

import json
import subprocess
import wave

import httpx
import numpy as np
import pytest

from backend.editing import effects, planner
from backend.editing.config import EditConfig, resolve_fps
from backend.editing.planner import EditPlan, PlannerInput, PlanSegment, make_plan
from backend.editing.presets import all_presets, apply_preset, get_preset


def words_from(text: str, start: float = 0.0, step: float = 0.4) -> list[dict]:
    return [{"start": round(start + i * step, 2), "end": round(start + i * step + 0.3, 2), "word": w}
            for i, w in enumerate(text.split())]


def exciting_input(d: float = 24.0) -> PlannerInput:
    """Calm talk, then a shouted reaction at ~10 s and a loud burst without voice at ~18 s."""
    words = words_from("allora ragazzi oggi facciamo un giro tranquillo per la città e parliamo un po'") + \
        words_from("oddio no ma cosa è successo pazzesco incredibile", start=9.6)
    n = int(d / 0.5)
    excess = np.zeros(n)
    excess[20] = 16.0   # 10.25 s, with voice → reaction
    excess[36] = 20.0   # 18.25 s, no voice → action
    return PlannerInput(duration=d, words=words, excess_db=excess, rms_db=np.full(n, -25.0), peak=10.0,
                        game="GTA 6", word_counts={}, total_words=0)


def rules(preset: str, **kw) -> EditConfig:
    return EditConfig(preset=preset, planner="rules", **kw)


# ------------------------------------------------------------------ presets
def test_three_presets_with_parameters():
    ps = all_presets()
    assert list(ps)[:3] == ["gaming_dynamic", "sports_highlights", "podcast_clean"]
    for pid in ("gaming_dynamic", "sports_highlights", "podcast_clean"):
        p = ps[pid]
        assert p.name and len(p.description) > 40 and p.features
        EditConfig.model_validate(p.config)          # every preset value is a valid EditConfig value
    assert ps["podcast_clean"].config["subject"] == "faces" and not ps["podcast_clean"].config["sfx"]
    assert ps["sports_highlights"].config["remove_silences"] is False      # never cut inside the action
    assert "flash" not in ps["podcast_clean"].policy.allowed_effects       # no superfluous effects
    cfg = apply_preset(EditConfig(layout="pip", intro_text="ciao"), "gaming_dynamic")
    assert cfg.preset == "gaming_dynamic" and cfg.layout == "pip" and cfg.intro_text == "ciao" and cfg.sfx


def test_preset_overrides_file(tmp_path, monkeypatch):
    from backend.core.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "editing_presets.json").write_text(json.dumps({
        "gaming_dynamic": {"policy": {"max_effects_per_min": 2}, "config": {"sfx": False}},
        "podcast_clean": {"config": {"zoom_strength": 99}}}))           # invalid → ignored
    assert get_preset("gaming_dynamic").policy.max_effects_per_min == 2
    assert get_preset("gaming_dynamic").config["sfx"] is False
    assert get_preset("podcast_clean").config["zoom_strength"] == 1.1


def test_fps_follows_the_source():
    assert resolve_fps("auto", 29.97) == 30 and resolve_fps("auto", 59.94) == 60
    assert resolve_fps("auto", 23.976) == 24 and resolve_fps("auto", 120) == 60
    assert resolve_fps("auto", None) == 30 and resolve_fps(25, 60) == 25


# ------------------------------------------------------------------ plan generation
def test_valid_plan_per_preset():
    inp = exciting_input()
    plans = {p: make_plan(inp, rules(p, sfx=p != "podcast_clean")) for p in
             ("gaming_dynamic", "sports_highlights", "podcast_clean")}
    for pid, plan in plans.items():
        EditPlan.model_validate(plan.model_dump())  # round-trips through validation
        segs = plan.segments
        assert segs[0].start == 0 and segs[-1].end == pytest.approx(inp.duration)
        assert all(a.end == pytest.approx(b.start) for a, b in zip(segs, segs[1:]))   # a partition
        assert all(s.reason for s in segs)
        assert any(s.effect == "none" for s in segs)                                   # explicit "none"
        assert all(0 <= s.intensity <= 1 for s in segs)
    g = plans["gaming_dynamic"]
    reaction = [s for s in g.segments if s.start <= 10.25 <= s.end][0]
    assert reaction.effect in ("punch_zoom", "shake")                  # shouted "oddio… pazzesco"
    assert g.sfx_cues() and all(c.category in effects.CATEGORIES for c in g.sfx_cues())
    assert g.emphasis                                                   # key words chosen
    p = plans["podcast_clean"]
    assert {s.effect for s in p.segments} <= {"none", "subtle_zoom", "caption_emphasis"}
    assert not p.sfx_cues()
    assert len(p.effect_segments("subtle_zoom")) <= 2


def test_no_effects_when_nothing_happens():
    inp = PlannerInput(duration=20, words=words_from("oggi parliamo con calma del meteo e della settimana"),
                       excess_db=np.zeros(40), rms_db=np.full(40, -30.0))
    plan = make_plan(inp, rules("gaming_dynamic", sfx=True))
    assert [s.effect for s in plan.segments] == ["none"]
    assert plan.segments[0].start == 0 and plan.segments[0].end == 20
    assert not plan.sfx_cues()
    assert any("Nessun momento forte" in n for n in plan.notes)
    # strong moment but zoom and effects switched off by the user → none as well
    off = make_plan(exciting_input(), rules("gaming_dynamic", zoom=False, effects=False, caption_emphasis=False))
    assert {s.effect for s in off.segments} == {"none"}


def test_limits_on_number_and_frequency():
    d = 30.0
    n = int(d / 0.5)
    excess = np.zeros(n)
    excess[4::6] = 18.0                     # a spike every 3 s
    words = [{"start": t, "end": t + 0.3, "word": "oddio"} for t in np.arange(1.5, 29, 3.0)]
    plan = make_plan(PlannerInput(duration=d, words=words, excess_db=excess), rules("gaming_dynamic", sfx=True))
    pol = get_preset("gaming_dynamic").policy
    fx = [s for s in plan.segments if s.effect != "none"]
    assert len(fx) <= round(pol.max_effects_per_min * d / 60)
    assert all(b.start - a.end >= pol.min_gap_s - 1e-6 for a, b in zip(fx, fx[1:]))
    assert all(s.end - s.start <= pol.max_effect_s + 1e-6 for s in fx)
    sfx_t = [c.at for c in plan.sfx_cues()]
    assert len(sfx_t) <= max(1, round(pol.sfx_per_min * d / 60))
    assert all(b - a >= pol.sfx_min_gap_s for a, b in zip(sfx_t, sfx_t[1:]))


def test_plan_validation_clamps_and_repairs():
    plan = EditPlan(preset="gaming_dynamic", duration=10, segments=[
        PlanSegment(start=2, end=4, effect="punch_zoom", intensity=7, reason="x"),       # intensity clamped
        PlanSegment(start=3, end=5, effect="subtle_zoom", intensity=0.5, reason="overlap"),  # dropped
        PlanSegment(start=8, end=25, effect="subtle_zoom", intensity=-1, reason="beyond end")])
    fx = [s for s in plan.segments if s.effect != "none"]
    assert [(s.start, s.end) for s in fx] == [(2, 4), (8, 10)]
    assert fx[0].intensity == 1.0 and fx[1].intensity == 0.0
    with pytest.raises(ValueError):
        PlanSegment(start=5, end=4, effect="none")
    with pytest.raises(ValueError):
        PlanSegment(start=1, end=2, effect="explode")


def test_pause_decisions_match_the_quiet_strategy():
    words = words_from("prima frase", 0) + words_from("seconda frase", 3.0) + words_from("terza frase", 6.0)
    rms = np.full(20, -20.0)
    rms[8:12] = -45.0        # 4.0-6.0 s really quiet; 0.7-3.0 s is a pause in speech but full of game audio
    plan = make_plan(PlannerInput(duration=10, words=words, rms_db=rms),
                     rules("gaming_dynamic", remove_silences=True, silence_strategy="quiet", min_silence_s=0.6))
    acts = {(round(p.start, 1), p.action) for p in plan.pauses}
    assert (0.7, "keep") in acts and (3.7, "cut") in acts


def test_dramatic_pause_is_kept():
    words = words_from("e allora sai cosa ha fatto", 0) + words_from("ha vinto tutto oddio", 3.6)
    excess = np.zeros(40)
    excess[7] = 18.0                         # 3.75 s: reaction right after the pause 2.3-3.6 s
    plan = make_plan(PlannerInput(duration=20, words=words, excess_db=excess),
                     rules("gaming_dynamic", remove_silences=True, min_silence_s=0.6))
    kept = plan.kept_pauses()
    assert kept and kept[0][1] == pytest.approx(3.6)
    assert any(p.action == "cut" for p in plan.pauses)   # the final silence is still cut


# ------------------------------------------------------------------ local LLM (mocked Ollama)
def llm_client(answer: dict | None, status: int = 200):
    def h(req: httpx.Request):
        body = json.loads(req.content)
        if "prompt" not in body:
            return httpx.Response(200, json={})
        assert "none" in body["prompt"] and "MOMENTI CANDIDATI" in body["prompt"]
        if answer is None:
            return httpx.Response(status, json={"error": "boom"})
        return httpx.Response(200, json={"response": json.dumps(answer)})
    return httpx.Client(transport=httpx.MockTransport(h))


def test_llm_decisions_are_validated_and_limited(monkeypatch):
    inp = exciting_input()
    cands = planner.find_candidates(inp)
    first, last = cands[0].id, cands[-1].id
    pazz = next(i for i, w in enumerate(inp.words) if w["word"] == "pazzesco")
    answer = {"decisions": [{"id": first, "effect": "explode", "reason": "invalid effect"},
                            {"id": 999, "effect": "punch_zoom", "reason": "unknown id"},
                            {"id": last, "effect": "punch_zoom", "intensity": 3, "sfx": "impact",
                             "reason": "il culmine"}],
              "emphasis_words": [12, pazz, 9999], "keep_pauses": []}   # 12 = "un" (stopword) → dropped
    plan = make_plan(inp, EditConfig(preset="gaming_dynamic", sfx=True), client=llm_client(answer), model="m")
    assert plan.source == "llm"
    fx = [s for s in plan.segments if s.effect != "none"]
    assert [s.candidate for s in fx] == [last] and fx[0].reason.startswith("AI:")
    assert fx[0].intensity <= 1 and fx[0].sfx and fx[0].sfx.category == "impact"
    assert any(e.word == "pazzesco" and e.reason == "scelta dall'AI planner" for e in plan.emphasis)
    assert all(e.word != "un" for e in plan.emphasis)


def test_llm_failure_falls_back_to_rules(monkeypatch):
    from backend.clip_detection import semantic
    monkeypatch.setattr(semantic, "_RETRY_WAIT_S", 0)
    plan = make_plan(exciting_input(), EditConfig(preset="gaming_dynamic"), client=llm_client(None, 500), model="m")
    assert plan.source == "rules" and any("piano a regole" in n for n in plan.notes)
    assert any(s.effect != "none" for s in plan.segments)


def test_rules_mode_never_calls_the_llm():
    def h(req):
        raise AssertionError("LLM called in rules mode")
    plan = make_plan(exciting_input(), rules("gaming_dynamic"),
                     client=httpx.Client(transport=httpx.MockTransport(h)), model="m")
    assert plan.source == "rules"


# ------------------------------------------------------------------ zoom shapes
def test_zoom_envelopes_follow_the_plan():
    plan = EditPlan(preset="gaming_dynamic", duration=20, segments=[
        PlanSegment(start=2, end=3.5, effect="punch_zoom", intensity=1),
        PlanSegment(start=8, end=10, effect="progressive_zoom", intensity=1),
        PlanSegment(start=14, end=16, effect="subtle_zoom", intensity=1)])
    z = lambda t: planner.zoom_envelope(plan, t)  # noqa: E731
    assert z(1.0) == 0 and z(6) == 0 and z(19) == 0                      # "none" → no zoom
    assert z(2.15) > 0.9                                                   # punch: fast
    assert z(8.5) < z(9.5) < z(9.99)                                       # progressive: grows
    assert 0 < z(15) <= 0.56                                               # subtle: gentle
    assert z(4.2) == 0                                                     # eases out after the segment
    flash = EditPlan(preset="x", duration=5, segments=[PlanSegment(start=1, end=1.3, effect="flash", intensity=1)])
    assert planner.flash_amount(flash, 1.0) > 0.8 and planner.flash_amount(flash, 2) == 0


# ------------------------------------------------------------------ SFX
def test_builtin_sfx_library():
    lib = effects.library()
    assert [x["category"] for x in lib] == list(effects.CATEGORIES) and all(x["available"] for x in lib)
    for c in effects.CATEGORIES:
        with wave.open(str(effects.sfx_file(c))) as w:
            assert w.getframerate() == 48000 and w.getnframes() > 1000
            y = np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768
        assert -7 < effects.db_peak(y) < -5                                # normalised to −6 dBFS


def test_sfx_mix_lands_at_the_planned_time(tmp_path):
    out = tmp_path / "mix.wav"
    inputs, parts = effects.mix_filters([(1.0, "impact", 0.8)], 1, "base", "a", 3.0)
    graph = ";".join(["[0:a]anull[base]", *parts])
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo:d=3", *inputs, "-filter_complex", graph, "-map", "[a]",
                    "-ac", "1", "-ar", "48000", str(out)], check=True)
    with wave.open(str(out)) as w:
        y = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
    assert len(y) == pytest.approx(3 * 48000, abs=480)
    before, during = y[: int(0.95 * 48000)], y[int(1.0 * 48000): int(1.3 * 48000)]
    assert np.abs(before).max() < 1e-3 and np.abs(during).max() > 0.2
    assert effects.mix_filters([], 1, "base", "a", 3.0) == ([], ["[base]anull[a]"])  # SFX off → untouched


# ------------------------------------------------------------------ caption emphasis
def test_emphasised_words_get_their_own_colour():
    from backend.subtitles.ass import ass_color, build_ass
    from backend.subtitles.presets import get_preset as sub_preset

    st = sub_preset("clean")
    cue = {"start": 0, "end": 2, "text": "ha vinto tutto", "words": [
        {"start": 0, "end": 0.5, "word": "ha"}, {"start": 0.5, "end": 1.2, "word": "vinto", "emph": True},
        {"start": 1.2, "end": 2, "word": "tutto"}]}
    ass = build_ass([cue], st, highlight=False)
    assert f"{{\\c{ass_color(st.emphasis)}}}vinto" in ass
    assert sub_preset("clean").name == "Clean Captions" and sub_preset("gaming").name == "Dynamic Captions"


# ------------------------------------------------------------------ speaker framing
def test_faces_path_frames_the_active_speaker():
    from backend.editing.reframe import faces_path

    n = 24
    times = np.arange(n) / 4
    left, right = (0.10, 0.3, 0.12, 0.2, 0.9), (0.75, 0.3, 0.12, 0.2, 0.9)
    rng = np.random.default_rng(0)
    grays = []
    for i in range(n):
        g = np.full((360, 640), 100, np.uint8)
        # mouth area of the right face moves from frame 8 on, the left one before
        x0 = int((0.75 if i >= 8 else 0.10) * 640 + 0.3 * 0.12 * 640)
        y0 = int((0.3 + 0.6 * 0.2) * 360)
        g[y0:y0 + 20, x0:x0 + 30] = rng.integers(0, 255, (20, 30))
        grays.append(g)
    path = faces_path(times, [[left, right]] * n, grays, crop_w_norm=0.32, max_speed=2.0, dead_zone=0.02)
    assert path is not None
    assert path.at(0.5)[0] < 0.3 and path.at(5.5)[0] > 0.6               # follows who is talking
    assert faces_path(times, [[]] * n, grays, crop_w_norm=0.32) is None   # no faces → caller falls back
