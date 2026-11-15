import pytest

from backend.editing.webcam import detect_webcam


def test_detects_facecam_overlay(webcam_video):
    d = detect_webcam(webcam_video, 20.0, 1920, 1080)
    assert d.region is not None, d.reason
    r = d.region
    # overlay content: x=60 y=700 420x320 on 1920x1080
    assert r.x * 1920 == pytest.approx(60, abs=25)
    assert r.y * 1080 == pytest.approx(700, abs=25)
    assert r.w * 1920 == pytest.approx(420, abs=40)
    assert r.h * 1080 == pytest.approx(320, abs=40)
    assert r.source == "auto" and r.confidence >= 0.7


def test_no_webcam_in_plain_gameplay(gameplay_video):
    d = detect_webcam(gameplay_video, 60.0, 1280, 720)
    assert d.region is None
