#!/usr/bin/env bash
# omarchy-m-test's on-screen video check: make the test card, play it full
# screen on the built-in screen with mpv and screenshot the screen with grim.
#
#   video-card.sh DIR CODEC [MPV_ARGS...]
#
# DIR is an empty private directory (the CLI makes it and removes it when the
# section ends); CODEC is h264 or hevc. Writes DIR/card-CODEC.mp4 (the test
# card: six solid colour bars, 1920x1080, BT.709, encoded by ffmpeg with
# libx264 or libx265), DIR/CODEC.log (mpv's verbose log) and DIR/CODEC.png
# (grim's screenshot of the built-in screen, at half its logical size).
# Prints "output: NAME" (the built-in screen). mpv runs with the machine's own
# configuration plus MPV_ARGS (the CLI adds --hwdec=auto-safe when that
# configuration leaves hardware decode off).
#
# Exit status: mpv's own (0 once the screenshot is taken), or
#   3  ffmpeg couldn't make the test card
#   4  no built-in screen (a desktop Mac, or the lid is closed)
#   5  Hyprland didn't answer (no Hyprland session to show the card in)
#   6  grim couldn't take the screenshot
#   7  mpv never showed the test card
set -u
dir=$1 codec=$2
shift 2
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

monitors=$(hyprctl monitors -j 2>/dev/null) || { echo "hyprctl monitors failed" >&2; exit 5; }
output=$(printf '%s' "$monitors" | python3 -c '
import json, re, sys
names = [m.get("name", "") for m in json.load(sys.stdin) if not m.get("disabled")]
print(next((n for n in names if re.match(r"(eDP|LVDS|DSI)-", n)), ""))' 2>/dev/null) || { echo "hyprctl monitors printed no monitor list" >&2; exit 5; }
[[ -n $output ]] || { echo "no built-in screen among Hyprland's monitors" >&2; exit 4; }
echo "output: $output"

case $codec in
  h264) encoder=(-c:v libx264 -preset veryfast) ;;
  hevc) encoder=(-c:v libx265 -preset veryfast -x265-params log-level=error) ;;
  *) echo "unknown codec $codec" >&2; exit 3 ;;
esac
card="$dir/card-$codec.mp4"
bars="color=c=0xff0000:s=320x1080:r=30:d=1[a];color=c=0x00ff00:s=320x1080:r=30:d=1[b];color=c=0xffff00:s=320x1080:r=30:d=1[c];"
bars+="color=c=0x0000ff:s=320x1080:r=30:d=1[d];color=c=0xff00ff:s=320x1080:r=30:d=1[e];color=c=0x00ffff:s=320x1080:r=30:d=1[f];"
bars+="[a][b][c][d][e][f]hstack=inputs=6,format=gbrp,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
ffmpeg -nostdin -hide_banner -loglevel error -y -f lavfi -i "$bars" -t 1 "${encoder[@]}" \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv "$card" || exit 3

OMT_SHOT="$dir/$codec.png" OMT_OUTPUT="$output" timeout 40 mpv "$@" \
  --no-audio --fs --fs-screen-name="$output" --keepaspect=no --pause \
  --osd-level=0 --osc=no --no-input-default-bindings --input-vo-keyboard=no --cursor-autohide=always \
  --msg-level=all=v --log-file="$dir/$codec.log" --script="$here/testcard.lua" \
  "$card" >/dev/null 2>&1
