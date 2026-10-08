#!/bin/bash
# Encode probe: capture the headless output, encode H.264 on the GPU, send RTP to the PC.
#   encode_probe.sh PC_ADDRESS VARIANT [SECONDS] [WIDTHxHEIGHT]
# VARIANT: sys-enc | sys-lpenc | dmabuf-enc | dmabuf-lpenc
# Moves the cursor over the headless output while running so frames keep coming.
set -u
pc=$1
variant=$2
seconds=${3:-8}
mode=${4:-1600x900}
port=5600

export XDG_RUNTIME_DIR=/run/user/$(id -u)
export HYPRLAND_INSTANCE_SIGNATURE=$(ls -t "$XDG_RUNTIME_DIR/hypr/" | head -1)
export WAYLAND_DISPLAY=wayland-1
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
cd "$(dirname "$0")"

case $variant in
    sys-*)    caps='video/x-raw' ;;
    dmabuf-*) caps='video/x-raw(memory:DMABuf)' ;;
esac
case $variant in
    *-enc)   encoder=vah264enc ;;
    *-lpenc) encoder=vah264lpenc ;;
esac
pipeline="$caps ! vapostproc name=live ! $encoder rate-control=cbr bitrate=20000 b-frames=0 key-int-max=${KEYINT:-600} target-usage=7 \
 ! h264parse ! identity name=mark ! rtph264pay config-interval=-1 aggregate-mode=zero-latency mtu=1200 \
 ! udpsink host=$pc port=$port bind-port=$((port + 1)) sync=false async=false"
# PIPELINE in the environment replaces the whole tail, for one-off experiments
pipeline=${PIPELINE:-$pipeline}

hyprctl output create headless LAPTOPREMOTE >/dev/null
hyprctl eval "hl.monitor({output=\"LAPTOPREMOTE\", mode=\"$mode@60\", position=\"auto\", scale=1})" >/dev/null
sleep 1
left=$(hyprctl monitors all | awk '/^Monitor LAPTOPREMOTE/{getline; split($3, at, "x"); print at[1]}')

# NOMOVE=1 leaves the cursor alone (the round-trip probe moves it itself)
[ -n "${NOMOVE:-}" ] || (
    end=$((SECONDS + seconds + 2))
    i=0
    while [ $SECONDS -lt $end ]; do
        i=$((i + 1))
        hyprctl eval "hl.dispatch(hl.dsp.cursor.move({x=$((left + 100 + i * 7 % 1200)), y=$((100 + i * 3 % 600))}))" >/dev/null 2>&1
    done
) &

echo "=== $variant $mode"
top -b -d "$seconds" -n 2 -p "$(pgrep -x Hyprland)" 2>/dev/null | awk '/Hyprland/{cpu=$9} END{print "Hyprland cpu% " cpu}' &
timeout $((seconds + 15)) python3 -u capture_probe.py LAPTOPREMOTE --seconds "$seconds" --pipeline "$pipeline" 2>&1 \
    | grep -E "first frame|frames:|fps|interval|capture-to-mark|FAIL" | cut -c1-260
wait
hyprctl eval "hl.dispatch(hl.dsp.cursor.move({x=960, y=540}))" >/dev/null
hyprctl output remove LAPTOPREMOTE >/dev/null
