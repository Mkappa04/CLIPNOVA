import numpy as np
import pytest

from backend.editing.timeline import compute_segments, cut_points, map_interval, map_time, output_duration

WORDS = [(1.0, 1.5), (1.6, 2.0), (6.0, 6.5), (6.6, 7.0)]  # 4 s pause between 2.0 and 6.0


def test_no_removal_keeps_everything():
    segs = compute_segments(10, 30, words=WORDS, remove_silences=False)
    assert len(segs) == 1 and output_duration(segs) == pytest.approx(10)


def test_no_speech_strategy_cuts_pauses_with_padding():
    segs = compute_segments(10, 30, words=WORDS, remove_silences=True, strategy="no_speech",
                            min_silence_s=0.8, padding_s=0.15)
    # leading silence (0-1), the 2-6 pause and the trailing 7-10 tail are removed (minus padding)
    assert segs[0].start == pytest.approx(0.0) or segs[0].start == pytest.approx(0.85, abs=0.04)
    assert output_duration(segs) < 4.0
    assert map_time(1.2, segs) is not None and map_time(4.0, segs) is None
    assert all(abs(s.start * 30 - round(s.start * 30)) < 1e-3 for s in segs), "edges on the frame grid"
    assert cut_points(segs) == [s.out_start for s in segs[1:]]


def test_quiet_strategy_keeps_loud_pauses():
    rms = np.full(40, -20.0, dtype=np.float32)  # 0.5 s windows, the whole clip is loud (gameplay audio)
    segs = compute_segments(10, 30, words=WORDS, rms_db=rms, window_s=0.5, remove_silences=True,
                            strategy="quiet", min_silence_s=0.8)
    assert len(segs) == 1  # nothing quiet → nothing cut
    rms[5:12] = -60  # pause 2.5-6 s is quiet
    segs = compute_segments(10, 30, words=WORDS, rms_db=rms, window_s=0.5, remove_silences=True,
                            strategy="quiet", min_silence_s=0.8)
    assert map_time(4.0, segs) is None and map_time(8.0, segs) is not None


def test_map_interval_clamps_to_kept_part():
    segs = compute_segments(10, 30, words=WORDS, remove_silences=True, strategy="no_speech")
    a, b = map_interval(1.8, 3.0, segs)
    assert b - a < 1.2 and a >= 0
