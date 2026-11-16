"""AI Video Director + Editing Planner v2: different content gets a different edit; validation & repair.

Five content types (synthetic but realistic signals): gaming fight, gaming dialogue, cinematic scene,
podcast, sports. Rules only (deterministic) + a mocked local LLM for the constrained hints."""

import json

import httpx
import numpy as np
import pytest

from backend.editing import director
from backend.editing.config import EditConfig
from backend.editing.plan import EditPlan, MusicCue, PauseDecision, PlanSegment, SoundCue, TextOverlay, TimeEffect, \
    Transition
from backend.editing.planner import PlannerInput, find_candidates, make_plan
from backend.editing.presets import apply_preset, get_preset

CATALOG = [{"id": f"m-{m}", "category": m, "title": f"{m} track", "origin": "builtin", "license": "cc0", "bpm": b,
            "path": f"/x/{m}.flac", "duration": 60, "enabled": True}
           for m, b in (("cinematic", 90), ("dynamic", 128), ("electronic", 124), ("chill", 84), ("dramatic", 80),
                        ("gaming", 140))]


def words(text: str, start: float = 0.0, step: float = 0.35) -> list[dict]:
    return [{"start": round(start + i * step, 2), "end": round(start + i * step + 0.28, 2), "word": w}
            for i, w in enumerate(text.split())]


def preset_cfg(pid: str, **kw) -> EditConfig:
    return apply_preset(EditConfig(planner="rules"), pid).model_copy(update=kw)


def gaming_fight(d=30.0) -> PlannerInput:
    n = int(d / 0.5)
    ex, fl, mo = np.zeros(n), np.zeros(n), np.random.default_rng(1).normal(1, 0.1, n)
    ex[30] = 20          # 15 s: huge burst, no voice (the kill)
    fl[30] = 9.0
    ex[44] = 15          # 22 s: shouted reaction
    w = words("vai vai lo vedo è dietro la cassa", 2.0) + words("oddio l'ho preso pazzesco", 21.8)
    return PlannerInput(duration=d, words=w, excess_db=ex, flash=fl, motion=mo, rms_db=np.full(n, -22.0),
                        peak=15.2, category="clutch", game="Valorant", clip_id="fight", title="Ace con lo Sheriff",
                        visual={"kind": "videogioco", "action": "elimina tre avversari", "confidence": 0.8,
                                "on_screen_text": "ACE"})


def gaming_dialogue(d=30.0) -> PlannerInput:
    n = int(d / 0.5)
    text = ("allora ragazzi oggi vi spiego come funziona il sistema di crafting perché molti me lo chiedono "
            "e secondo me è la parte più interessante del gioco quindi partiamo dalle basi")
    return PlannerInput(duration=d, words=words(text, 0.5, 0.9), excess_db=np.zeros(n), rms_db=np.full(n, -24.0),
                        motion=np.random.default_rng(2).normal(1, 0.05, n), category="educational",
                        game="Minecraft", clip_id="dialog", title="Come funziona il crafting")


def cinematic_scene(d=30.0) -> PlannerInput:
    n = int(d / 0.5)
    rms = np.full(n, -30.0)
    rms[24:34] = np.linspace(-30, -12, 10)   # build-up to 17 s
    ex = np.zeros(n)
    ex[34] = 17.0                              # impact at 17 s, no voice
    fl = np.zeros(n)
    fl[34] = 8.0
    return PlannerInput(duration=d, words=words("non può finire così", 4.0), rms_db=rms, excess_db=ex, flash=fl,
                        peak=17.1, category="epic", game="Elden Ring", clip_id="cine", title="L'ultimo colpo",
                        visual={"kind": "videogioco", "action": "un boss crolla dopo un colpo", "confidence": 0.7})


def podcast(d=40.0) -> PlannerInput:
    n = int(d / 0.5)
    text = " ".join(["secondo me il problema del lavoro da remoto non è la produttività è la solitudine"] * 4)
    w = words(text, 0.3, 0.55)
    ex = np.zeros(n)
    ex[40] = 7.0                               # a laugh-ish bump with voice
    return PlannerInput(duration=d, words=w, excess_db=ex, rms_db=np.full(n, -20.0), category="storytelling",
                        clip_id="pod", title="La solitudine del lavoro da remoto",
                        semantic={"payoff_type": "rivelazione", "standalone": 4},
                        visual={"kind": "podcast/intervista", "action": "due persone parlano", "confidence": 0.8})


def sports(d=24.0) -> PlannerInput:
    n = int(d / 0.5)
    ex = np.zeros(n)
    ex[22] = 19.0                              # crowd roar at 11 s (goal), no commentary
    mo = np.random.default_rng(3).normal(1, 0.1, n)
    mo[21] = 6
    return PlannerInput(duration=d, words=words("palla al limite tiro", 6.0), excess_db=ex, motion=mo,
                        rms_db=np.full(n, -18.0), peak=11.0, category="epic", game="Serie A", clip_id="sport",
                        title="Gol all'incrocio", visual={"kind": "sport", "action": "tiro all'incrocio",
                                                          "confidence": 0.8})


CASES = {"fight": (gaming_fight, "gaming_dynamic"), "dialog": (gaming_dialogue, "gaming_dynamic"),
         "cine": (cinematic_scene, "gaming_cinematic"), "podcast": (podcast, "podcast_clean"),
         "sport": (sports, "sports_highlights")}


@pytest.fixture(scope="module")
def plans() -> dict[str, EditPlan]:
    return {k: make_plan(f(), preset_cfg(p), catalog=CATALOG) for k, (f, p) in CASES.items()}


def fingerprint(p: EditPlan) -> tuple:
    return (tuple(sorted({s.effect for s in p.segments} - {"none"})), tuple(e.kind for e in p.time_effects),
            p.look.grade, p.music.mood if p.music else None, tuple(o.kind for o in p.overlays),
            p.director.style if p.director else None)


def test_every_content_type_gets_a_different_edit(plans):
    prints = {k: fingerprint(p) for k, p in plans.items()}
    assert len(set(prints.values())) == len(prints), prints
    for p in plans.values():
        EditPlan.model_validate(json.loads(p.model_dump_json()))      # valid JSON round trip
        assert all(s.reason for s in p.segments) and p.director is not None


def test_fight_gets_speed_ramp_sound_design_and_gaming_music(plans):
    p = plans["fight"]
    assert p.director.style == "energetic"
    ramp = [e for e in p.time_effects if e.kind == "speed_ramp"]
    assert ramp and ramp[0].start < 15.2 < ramp[0].end                       # on the kill, not on the talk
    assert p.music and p.music.mood in ("gaming", "electronic", "dynamic") and p.music.sync_at is not None
    assert any(c.category in ("explosion", "hit", "impact") for c in p.sfx_cues())
    assert any(o.kind == "callout" and o.text == "ACE" for o in p.overlays)  # verbatim on-screen text


def test_dialogue_in_a_gaming_preset_is_edited_calmly(plans):
    p = plans["dialog"]
    assert p.director.style in ("minimal", "balanced")                       # the content wins over the preset
    assert not p.time_effects                                                # never slow down speech
    assert len([s for s in p.segments if s.effect != "none"]) <= 1
    assert p.music is None or p.music.duck_db < 0


def test_cinematic_scene_slow_motion_grade_and_dramatic_music(plans):
    p = plans["cine"]
    assert p.director.style == "cinematic" and p.look.grade == "cinematic" and p.look.vignette > 0
    assert [e.kind for e in p.time_effects] == ["slow_motion"]
    assert p.music and p.music.mood in ("cinematic", "dramatic")
    assert not p.effect_segments("glitch", "shake")


def test_podcast_is_minimal(plans):
    p = plans["podcast"]
    assert p.director.style == "minimal" and not p.time_effects and not p.overlays
    assert {s.effect for s in p.segments} <= {"none", "subtle_zoom", "caption_emphasis"}
    assert not p.sfx_cues()
    assert p.music is not None and p.music.mood == "chill" and p.music.level_db <= -27


def test_sports_slow_motion_on_the_goal(plans):
    p = plans["sport"]
    sm = [e for e in p.time_effects if e.kind == "slow_motion"]
    assert sm and sm[0].start <= 11.0 <= sm[0].end and p.look.grade == "punchy"


def test_movement_alone_is_not_a_moment():
    d = 20.0
    n = int(d / 0.5)
    mo = np.random.default_rng(4).normal(1, 0.05, n)
    mo[20] = 12                                  # a big camera move, no sound, no words, no semantic hint
    inp = PlannerInput(duration=d, words=[], motion=mo, rms_db=np.full(n, -30.0), clip_id="m")
    plan = make_plan(inp, preset_cfg("gaming_dynamic"), catalog=CATALOG)
    assert plan.director.moments and plan.director.moments[0].type == "action_only"
    assert not [s for s in plan.segments if s.effect != "none"] and not plan.time_effects
    assert any("solo movimento" in s.reason.lower() for s in plan.segments)


def test_feature_switches_are_respected():
    inp = gaming_fight()
    off = make_plan(inp, preset_cfg("gaming_dynamic", time_effects=False, motion_graphics=False, music="off",
                                    look="none", sfx=False, transitions=False), catalog=CATALOG)
    assert not off.time_effects and not off.overlays and off.music is None and off.look.grade == "none"
    assert not off.sfx_cues() and not off.transitions
    forced = make_plan(inp, preset_cfg("gaming_dynamic", music_mood="chill", look="bw"), catalog=CATALOG)
    assert forced.music.mood == "chill" and forced.look.grade == "bw"
    quiet = make_plan(inp, preset_cfg("gaming_dynamic", music_volume=0.0), catalog=CATALOG)
    assert quiet.music is None


def test_user_tracks_are_preferred_and_unlicensed_never_used():
    mine = {"id": "u1", "category": "electronic", "title": "mine", "origin": "user", "license": "cc_by", "bpm": 138,
            "path": "/x/u1.mp3", "duration": 120, "enabled": True}
    unlicensed = {**mine, "id": "u2", "license": ""}
    plan = make_plan(gaming_fight(), preset_cfg("gaming_dynamic"), catalog=CATALOG + [mine, unlicensed])
    assert plan.music.asset_id == "u1"
    assert director.choose_track([unlicensed], "electronic", 0.5, 30, 0) is None


def test_disabled_items_are_removed():
    plan = make_plan(gaming_fight(), preset_cfg("gaming_dynamic"), catalog=CATALOG)
    ids = plan.item_ids()
    assert "music" in ids and any(i.startswith("speed_ramp@") for i in ids)
    off = plan.without(["music", next(i for i in ids if i.startswith("speed_ramp@")), "look"])
    assert off.music is None and not off.time_effects and off.look.grade == "none"
    assert len(off.item_ids()) == len(ids) - 3


def test_plan_validator_repairs_and_reports():
    plan = EditPlan(preset="x", duration=10, pauses=[PauseDecision(start=6, end=7, action="cut")],
                    segments=[PlanSegment(start=4.6, end=5.4, effect="shake", intensity=1),
                              PlanSegment(start=1.0, end=2.0, effect="glitch", intensity=1)],
                    time_effects=[TimeEffect(kind="freeze_frame", start=5.0, hold=0.4),
                                  TimeEffect(kind="slow_motion", start=0.5, end=3.0, speed=0.5),
                                  TimeEffect(kind="slow_motion", start=6.2, end=6.8, speed=0.5),   # in the cut
                                  TimeEffect(kind="slow_motion", start=0.0, end=9.9, speed=0.2)],  # too long
                    transitions=[Transition(kind="flash", at=2.0), Transition(kind="dip", at=6.0)],
                    overlays=[TextOverlay(kind="callout", start=1, end=2, text="A{\\b1}B"),
                              TextOverlay(kind="callout", start=1.5, end=2.5, text="C")],
                    sounds=[SoundCue(category="impact", at=3.0), SoundCue(category="hit", at=3.1)],
                    music=MusicCue(asset_id="a", mood="chill", sync_at=50))
    kinds = [(e.kind, e.start) for e in plan.time_effects]
    assert ("freeze_frame", 5.0) in kinds and ("slow_motion", 0.5) in kinds and len(kinds) == 2
    assert not plan.effect_segments("shake")                # incompatible with the freeze frame
    assert not plan.effect_segments("glitch")               # no glitch during slow motion
    assert [t.at for t in plan.transitions] == [6.0]        # only on the real cut
    assert [o.text for o in plan.overlays] == ["AB"]        # escaped, no overlap
    assert len(plan.sounds) == 1 and plan.music.sync_at == 10
    assert len(plan.issues) >= 6
    with pytest.raises(ValueError):
        EditPlan.model_validate({"preset": "x", "duration": 5, "time_effects": [{"kind": "rewind", "start": 1}]})
    with pytest.raises(ValueError):
        TimeEffect(kind="slow_motion", start=1, end=1.1)


def llm(answer: dict):
    def h(req: httpx.Request):
        body = json.loads(req.content)
        if "prompt" not in body:
            return httpx.Response(200, json={})
        assert "tipo=" in body["prompt"] and "Effetti di tempo" in body["prompt"]
        return httpx.Response(200, json={"response": json.dumps(answer)})
    return httpx.Client(transport=httpx.MockTransport(h))


def test_llm_hints_are_options_not_orders():
    inp = gaming_fight()
    cands = find_candidates(inp)
    director.analyse(inp, cands, get_preset("gaming_dynamic").policy)
    kill = min(cands, key=lambda c: abs(c.t - 15.2))
    talk = min(cands, key=lambda c: abs(c.t - 22.0))
    answer = {"decisions": [{"id": kill.id, "effect": "punch_zoom", "time_effect": "speed_ramp", "reason": "kill"},
                            {"id": talk.id, "effect": "punch_zoom", "time_effect": "speed_ramp", "reason": "parla"}],
              "emphasis_words": [], "music_mood": "electronic"}
    cfg = preset_cfg("gaming_dynamic", planner="auto")
    plan = make_plan(inp, cfg, client=llm(answer), model="m", catalog=CATALOG)
    assert plan.source == "llm" and plan.music.mood == "electronic"
    assert [e.candidate for e in plan.time_effects] == [kill.id]   # the one over speech is refused
    bad = make_plan(inp, cfg, client=llm({**answer, "music_mood": "polka"}), model="m", catalog=CATALOG)
    assert bad.music.mood in ("gaming", "electronic", "dynamic")
