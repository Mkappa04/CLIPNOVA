import subprocess

from backend.clip_detection.audio import analyze_audio


def test_peak_and_silence_detection(media_dir):
    wav = media_dir / "a.wav"
    # 20 s: quiet noise, loud burst at 10 s, digital silence from 15 s to 18 s
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.05:duration=20:sample_rate=16000",
        "-f", "lavfi", "-i", "sine=frequency=300:duration=1:sample_rate=16000,volume=8",
        "-filter_complex",
        "[1:a]adelay=10000[b];[0:a][b]amix=inputs=2:duration=first:normalize=0,"
        "volume=enable='between(t,15,18)':volume=0",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
    f = analyze_audio(wav, 0.5)
    assert len(f.rms_db) == 40
    assert any(abs(p["time"] - 10.25) <= 1.0 and p["excess_db"] > 10 for p in f.peaks), f.peaks
    assert any(s <= 15.5 and e >= 17.5 for s, e in f.silences), f.silences
    assert f.stats["has_audio"]
