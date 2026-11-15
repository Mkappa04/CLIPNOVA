#!/usr/bin/env bash
# Synthetic 1080p "stream" with a facecam overlay for webcam-detection / layout tests.
# Webcam box: x=60 y=700 size 420x320 (+6 px border) on 1920x1080 gameplay; speech audio at 2 s.
# Usage: scripts/make_test_webcam.sh <face.jpg> <speech_audio> <output.mp4> [duration]
set -euo pipefail
face="$1"; speech="$2"; out="$3"; dur="${4:-20}"
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=$dur" \
  -loop 1 -framerate 30 -t "$dur" -i "$face" \
  -f lavfi -i "anoisesrc=color=pink:amplitude=0.02:duration=$dur:sample_rate=44100" -i "$speech" \
  -filter_complex "[1:v]scale=420:-2,crop=420:320:'8+8*sin(t*1.3)':'40+10*sin(t*0.9)',noise=alls=6:allf=t,eq=brightness='0.03*sin(t*2)':eval=frame,pad=432:332:6:6:white[cam];\
[0:v][cam]overlay=54:694:shortest=1,format=yuv420p[v];\
[3:a]aresample=44100,adelay=2000|2000[s];[2:a][s]amix=inputs=2:duration=first:normalize=0[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset ultrafast -crf 23 -c:a aac -t "$dur" "$out"
