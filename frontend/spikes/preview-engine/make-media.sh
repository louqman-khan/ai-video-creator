#!/bin/bash
# Builds the test media for the preview-engine spike from real cached stock clips.
# usage: make-media.sh <out-dir>     (run from the repo root; needs tools/bin/ffmpeg)
set -euo pipefail
OUT=${1:?out dir}; mkdir -p "$OUT"
FF=tools/bin/ffmpeg; SRC=work/cache/media
CLIPS=(pixabay_14293 pixabay_28097 pixabay_188778)          # 29.97 / 30 / 29.97 fps, 1080p
VF="scale=960:540:force_original_aspect_ratio=increase,crop=960:540,fps=30,format=yuv420p"
for i in 0 1 2; do
  c=${CLIPS[$i]}
  # proxy: 960x540, constant 30 fps, a keyframe every 0.5 s (fast scrubbing)
  $FF -y -hide_banner -loglevel error -stream_loop -1 -i $SRC/$c.mp4 -t 62 -vf "$VF" -an \
      -c:v libx264 -preset veryfast -crf 28 -g 15 -keyint_min 15 -sc_threshold 0 "$OUT/proxy_$i.mp4"
  # same size, default long GOP (what a naive downscale gives)
  $FF -y -hide_banner -loglevel error -stream_loop -1 -i $SRC/$c.mp4 -t 62 -vf "$VF" -an \
      -c:v libx264 -preset veryfast -crf 28 -g 250 "$OUT/longgop_$i.mp4"
  # the untouched 1080p source (variable fps per clip, long GOP)
  cp $SRC/$c.mp4 "$OUT/source_$i.mp4"
done
# two audio tracks, synthesised (no input paths from globs: an unquoted glob once turned extra matches
# into ffmpeg *output* files and overwrote a project's cache with an endless looped file)
$FF -y -hide_banner -loglevel error -f lavfi -i "anoisesrc=color=brown:amplitude=0.08:duration=62" -f lavfi -i "sine=frequency=180:duration=62" \
    -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0" -t 62 -c:a aac -b:a 128k "$OUT/narration.m4a"
$FF -y -hide_banner -loglevel error -f lavfi -i "anoisesrc=color=pink:amplitude=0.05:duration=62" -f lavfi -i "sine=frequency=330:duration=62" \
    -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0" -t 62 -c:a aac -b:a 128k "$OUT/music.m4a"
ls -la "$OUT" | awk '{print $5, $9}' | tail -n +4
