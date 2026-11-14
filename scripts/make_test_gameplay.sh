#!/usr/bin/env bash
# Generate a synthetic 60 s "gameplay" video to exercise the analysis pipeline:
# 3 visual scenes (cuts at 20 s and 35 s), background noise, speech at 25 s, loud burst at 45 s.
# Usage: scripts/make_test_gameplay.sh <speech_audio> <output.mp4>
set -euo pipefail
speech="$1"; out="$2"
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=20" \
  -f lavfi -i "color=c=0x802020:size=1280x720:rate=30:duration=15,noise=alls=40:allf=t" \
  -f lavfi -i "mandelbrot=size=1280x720:rate=30,trim=duration=25" \
  -f lavfi -i "anoisesrc=color=pink:amplitude=0.03:duration=60:sample_rate=44100" \
  -i "$speech" \
  -f lavfi -i "sine=frequency=180:duration=1.5:sample_rate=44100,volume=6" \
  -filter_complex "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v];\
[4:a]aresample=44100,adelay=25000|25000,volume=2[sp];[5:a]adelay=45000|45000[boom];\
[3:a][sp][boom]amix=inputs=3:duration=first:normalize=0[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset ultrafast -c:a aac -t 60 "$out"
