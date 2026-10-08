#!/bin/bash
# Developer tool: copies agent/ and protocol/ to ~/laptopremote on the laptop and generates the
# Wayland protocol classes there. Install or update the service afterwards with
#   ssh $LAPTOPREMOTE_HOST 'bash ~/laptopremote/agent/setup.sh install'
set -e
host=${LAPTOPREMOTE_HOST:?set LAPTOPREMOTE_HOST to user@laptop}
root=$(cd "$(dirname "$0")/.." && pwd)
# copied beside the installed files and swapped in at the end: a copy that breaks off half-way
# must not leave the laptop without the restore script its service and keybind run.
# The Wayland protocol classes for the virtual pointer, keyboard and clipboard are written there by pywayland's
# scanner, into laptopremote_agent/wl, so they always fit the pywayland the laptop has.
ssh -o BatchMode=yes "$host" 'rm -rf ~/laptopremote/incoming && mkdir -p ~/laptopremote/incoming'
scp -q -r -o BatchMode=yes "$root/agent" "$root/protocol" "$host:laptopremote/incoming/"
ssh -o BatchMode=yes "$host" 'cd ~/laptopremote && find incoming -type f \( -name "*.py" -o -name "*.sh" -o -name "*.service" -o -name "laptopremote-picker" -o -name "laptopremote-restore" \) -exec sed -i "s/\r$//" {} + && python3 -m pywayland.scanner -i /usr/share/wayland/wayland.xml incoming/agent/protocols/*.xml -o incoming/agent/laptopremote_agent/wl 2>/dev/null && test -f incoming/agent/laptopremote_agent/wl/wlr_virtual_pointer_unstable_v1.py && rm -rf agent protocol && mv incoming/agent incoming/protocol . && rmdir incoming'
