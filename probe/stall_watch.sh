#!/bin/sh
# Laptop side. Waits for the portal to report a capture stall ("Out of buffers" from
# xdg-desktop-portal-hyprland) and writes what the agent, its sockets, PipeWire and the Wi-Fi link
# look like at that moment, so the cause of a stalled picture can be read afterwards.
#
#   systemd-run --user --unit=lr-stallwatch -p RuntimeMaxSec=86400 sh ~/laptopremote-probe/stall_watch.sh
#   systemctl --user stop lr-stallwatch
#
# Snapshots go to ~/laptopremote-probe/stall-<time>.txt; a baseline is written at start.
out="$HOME/laptopremote-probe"
mkdir -p "$out"
wifi=$(iw dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }')

snapshot() {
    file="$out/stall-$(date +%Y%m%d-%H%M%S)-$1.txt"
    pid=$(pgrep -f 'laptopremote_agent$' | head -1)
    {
        echo "== $(date -Is) $1, agent pid ${pid:-none}"
        if [ -n "$pid" ]; then
            echo "== agent threads: tid comm state wchan syscall utime stime"
            for t in /proc/"$pid"/task/*; do
                printf '%s %s ' "$(basename "$t")" "$(cat "$t/comm")"
                awk '{ printf "%s ", $3 }' "$t/stat"
                printf 'wchan=%s ' "$(cat "$t/wchan" 2>/dev/null)"
                printf 'syscall=%s ' "$(cut -d' ' -f1 "$t/syscall" 2>/dev/null)"
                awk '{ print $14, $15 }' "$t/stat"
            done
            echo "== agent fds"
            ls -l /proc/"$pid"/fd 2>/dev/null | awk '{ print $NF }' | sort | uniq -c | sort -rn | head -12
        fi
        echo "== udp sockets (send queue is the udpsink)"
        ss -uanpm
        echo "== control tcp"
        ss -tnpmi | grep -A 2 ':47800'
        echo "== wifi $wifi"
        [ -n "$wifi" ] && iw dev "$wifi" link
        [ -n "$wifi" ] && iw dev "$wifi" station dump | grep -E 'signal|tx (retries|failed|packets|bitrate)|rx (packets|bitrate)|expected'
        echo "== pipewire"
        timeout 5 pw-top -b -n 2 2>/dev/null | tail -8
        echo "== agent journal"
        journalctl --user -u laptopremote-agent -n 15 --no-pager -o short-iso
        echo "== portal journal, last 30 lines"
        journalctl --user -u xdg-desktop-portal-hyprland -n 30 --no-pager -o short-iso | cut -c1-160
    } > "$file" 2>&1
    echo "wrote $file"
}

snapshot baseline
last=0
journalctl --user -u xdg-desktop-portal-hyprland -f -n 0 -o cat | while IFS= read -r line; do
    case $line in
        *"Out of buffers"*) ;;
        *) continue ;;
    esac
    now=$(date +%s)
    [ $((now - last)) -lt 300 ] && continue
    last=$now
    snapshot stall
    sleep 10
    snapshot stall+10s
    sleep 50
    snapshot stall+60s
done
