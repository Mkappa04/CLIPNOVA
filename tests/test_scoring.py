import numpy as np
import pytest

from backend.clip_detection.scoring import RawSignals, ScoringConfig, ScoringWeights, detect_clips
from backend.transcription.whisper_engine import Segment, Transcript, Word

WS = 0.5
DUR = 180.0


def seg(i, start, text, step=0.35):
    toks = text.split()
    ws = [Word(start + k * step, start + k * step + step * 0.9, " " + t, 0.9) for k, t in enumerate(toks)]
    return Segment(i, start, ws[-1].end, text, -0.3, 0.05, ws)


def raw_signals() -> RawSignals:
    n = int(DUR / WS)
    rng = np.random.default_rng(0)
    rms = (-35 + rng.normal(0, 1.0, n)).astype(np.float32)
    excess = np.zeros(n, dtype=np.float32)
    for t, db in ((31, 12), (82, 16), (140, 22)):   # funny, rage, explosion
        i = int(t / WS)
        rms[i - 2:i + 3] += db
        excess[i - 2:i + 3] = db
    motion = (5 + rng.normal(0, 0.5, n)).astype(np.float32)
    motion[int(138 / WS):int(146 / WS)] += 25
    return RawSignals(WS, DUR, rms, excess, np.abs(rng.normal(0, 0.1, n)).astype(np.float32),
                      motion, np.zeros(n, dtype=np.float32), scenes=[60.0, 120.0, 139.0, 143.0])


def transcript() -> Transcript:
    segs = [
        seg(0, 5, "allora oggi facciamo un giro in città con calma"),
        seg(1, 29, "ahahah ma che ridere sto morendo ahahah"),
        seg(2, 80, "ma porca miseria che schifo maledetta polizia"),
        seg(3, 100, "vabbè andiamo avanti con la missione tranquilli"),
    ]
    return Transcript("it", 0.99, DUR, "cpu", "test", segs)


@pytest.fixture(scope="module")
def result():
    return detect_clips(raw_signals(), transcript(), "GTA 6", ScoringConfig())


def test_detects_the_three_moments(result):
    _, clips = result
    peaks = sorted(c.peak_time for c in clips)
    for t in (31, 82, 140):
        assert any(abs(p - t) <= 4 for p in peaks), (t, peaks)


def test_categories_follow_evidence(result):
    _, clips = result
    by_peak = {round(c.peak_time): c for c in clips}

    def near(t):
        return min(clips, key=lambda c: abs(c.peak_time - t))

    assert near(31).category == "funny"
    assert near(82).category == "rage"
    assert near(140).category in ("epic", "unexpected", "gameplay_highlight")
    assert by_peak  # keep reference


def test_clip_constraints(result):
    _, clips = result
    cfg = ScoringConfig()
    for c in clips:
        assert 0 <= c.start < c.end <= DUR
        assert cfg.min_clip_s - 0.01 <= c.duration <= cfg.max_clip_s + 0.01
        assert 0 <= c.score <= 100 and 0 < c.confidence <= 0.95
        assert c.reason.startswith("Categoria stimata") and "euristica" in c.reason
    ordered = sorted(clips, key=lambda c: c.start)
    for a, b in zip(ordered, ordered[1:]):
        assert a.end <= b.start + 0.01, "clips must not overlap"


def test_reason_and_title_use_real_transcript(result):
    _, clips = result
    funny = min(clips, key=lambda c: abs(c.peak_time - 31))
    assert "ridere" in funny.transcript
    assert "ridere" in funny.suggested_title or "ahahah" in funny.suggested_title
    assert "Risate" in funny.reason
    rage = min(clips, key=lambda c: abs(c.peak_time - 82))
    assert "porca" in rage.reason or "maledett" in rage.reason


def test_sentence_snapping(result):
    _, clips = result
    rage = min(clips, key=lambda c: abs(c.peak_time - 82))
    assert rage.start <= 80.0, "clip should start at the sentence start, not mid-sentence"


def test_no_transcript_lowers_confidence_and_uses_template_title():
    _, clips = detect_clips(raw_signals(), None, "GTA 6", ScoringConfig())
    assert clips
    assert all(c.confidence <= 0.75 for c in clips)
    assert all(c.suggested_title.startswith("GTA 6 ·") for c in clips)


def test_weights_and_limits_are_configurable():
    cfg = ScoringConfig(max_clips=1, min_clip_s=10, max_clip_s=20,
                        weights=ScoringWeights(laughter=5, keywords=5, audio_peak=0, audio_energy=0,
                                               visual_motion=0, scene_changes=0, speech_excitement=0))
    _, clips = detect_clips(raw_signals(), transcript(), "GTA 6", cfg)
    assert len(clips) == 1
    assert abs(clips[0].peak_time - 31) <= 4  # laughter-weighted config picks the funny moment
    assert 10 - 0.01 <= clips[0].duration <= 20 + 0.01


def test_min_score_filters_everything():
    _, clips = detect_clips(raw_signals(), transcript(), "GTA 6", ScoringConfig(min_score=99.9))
    assert clips == []


def test_close_events_do_not_overlap():
    """Two events 11 s apart with 12 s pre-roll must produce non-overlapping clips."""
    n = int(60 / WS)
    rms = np.full(n, -40, dtype=np.float32)
    excess = np.zeros(n, dtype=np.float32)
    for t in (34, 45):
        i = int(t / WS)
        rms[i - 1:i + 2] += 20
        excess[i - 1:i + 2] = 20
    raw = RawSignals(WS, 60.0, rms, excess, np.zeros(n, np.float32), np.ones(n, np.float32),
                     np.zeros(n, np.float32), scenes=[20.0])
    _, clips = detect_clips(raw, None, "GTA 6", ScoringConfig(min_score=5))
    assert len(clips) == 2
    a, b = sorted(clips, key=lambda c: c.start)
    assert a.end <= b.start + 0.01
    assert a.start <= 34 <= a.end and b.start <= 45 <= b.end
