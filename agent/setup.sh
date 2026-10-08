#!/bin/bash
# Installs or removes the LaptopRemote agent on this laptop. Run here, on the laptop:
#   bash agent/setup.sh install      from a clone, or from ~/laptopremote after deploy.sh
#   bash agent/setup.sh remove       takes everything out again; --purge also deletes ~/.config/laptopremote
# Running install again updates the code and restarts the agent.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
install_dir="$HOME/laptopremote"
picker="$HOME/.local/bin/laptopremote-picker"
unit="$HOME/.config/systemd/user/laptopremote-agent.service"
xdph="$HOME/.config/hypr/xdph.conf"
bindings="$HOME/.config/hypr/bindings.lua"
config_dir="$HOME/.config/laptopremote"
config="$config_dir/config.toml"
marker="# LaptopRemote replaced:"   # above the picker line setup put into xdph.conf; holds the line it replaced
block_begin="# LaptopRemote begin"  # around a whole screencopy block, when xdph.conf had no picker line
block_end="# LaptopRemote end"

say() { printf '%s\n' "$*"; }
die() { printf 'setup: %s\n' "$*" >&2; exit 1; }

hypr_env() {
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && [ -d "$XDG_RUNTIME_DIR/hypr" ]; then
        HYPRLAND_INSTANCE_SIGNATURE=$(ls -t "$XDG_RUNTIME_DIR/hypr" | head -n 1)
        export HYPRLAND_INSTANCE_SIGNATURE
    fi
}

# a value from config.toml that is safe to put into Lua: plain characters only, else the default
toml_value() {  # key default
    local value
    value=$(tr -d '\r' < "$config" 2>/dev/null |
        sed -n "s/^$1[ \t]*=[ \t]*[\"']\([A-Za-z0-9._+ -]*\)[\"'].*$/\1/p" | head -n 1)
    printf '%s' "${value:-$2}"
}

check_requirements() {
    local missing=0
    for tool in hyprctl jq openssl python3 gst-inspect-1.0 hyprland-preview-share-picker systemctl; do
        command -v "$tool" >/dev/null || { say "missing: $tool"; missing=1; }
    done
    for module in gi dbus pywayland tomllib; do
        python3 -c "import $module" 2>/dev/null || { say "missing: python3 module $module"; missing=1; }
    done
    python3 -c "import gi; gi.require_version('Gst', '1.0'); from gi.repository import Gst" 2>/dev/null \
        || { say "missing: GStreamer typelib for python3 (gst-python / gobject-introspection)"; missing=1; }
    gst-inspect-1.0 pipewiresrc >/dev/null 2>&1 || { say "missing: GStreamer pipewire plugin"; missing=1; }
    if grep -Eq '^[ \t]*encoder[ \t]*=' "$config" 2>/dev/null; then
        say "config.toml sets its own encoder; not checked here"
    else
        gst-inspect-1.0 vah265lpenc >/dev/null 2>&1 \
            || { say "missing: GStreamer element vah265lpenc (gst-plugins-bad with VA); or set encoder in config.toml"; missing=1; }
    fi
    [ -f /usr/share/wayland/wayland.xml ] || { say "missing: /usr/share/wayland/wayland.xml (wayland package)"; missing=1; }
    [ -f "$xdph" ] || { say "missing: $xdph (xdg-desktop-portal-hyprland config)"; missing=1; }
    [ -f "$bindings" ] || { say "missing: $bindings (Hyprland Lua config as Omarchy ships it)"; missing=1; }
    [ "$missing" -eq 0 ] || die "install what is missing and run again"
}

copy_code() {
    if [ "$here" = "$install_dir" ]; then
        say "running from $install_dir; code already in place"
    else
        # copied beside the installed files and swapped in at the end: a copy that breaks off half-way
        # must not leave the laptop without the restore script its service and keybind run
        rm -rf "$install_dir/incoming"
        mkdir -p "$install_dir/incoming"
        cp -r "$here/agent" "$here/protocol" "$install_dir/incoming/"
        rm -rf "$install_dir/incoming/agent/laptopremote_agent/__pycache__" "$install_dir/incoming/agent/tests/__pycache__"
        find "$install_dir/incoming" -type f \( -name "*.py" -o -name "*.sh" -o -name "*.service" \
            -o -name "laptopremote-picker" -o -name "laptopremote-restore" \) -exec sed -i 's/\r$//' {} +
        rm -rf "$install_dir/agent" "$install_dir/protocol"
        mv "$install_dir/incoming/agent" "$install_dir/incoming/protocol" "$install_dir/"
        rmdir "$install_dir/incoming"
    fi
    # Wayland protocol classes for the virtual pointer, keyboard and clipboard, generated here so
    # they always fit the pywayland this laptop has
    python3 -m pywayland.scanner -i /usr/share/wayland/wayland.xml "$install_dir"/agent/protocols/*.xml \
        -o "$install_dir/agent/laptopremote_agent/wl" 2>/dev/null
    [ -f "$install_dir/agent/laptopremote_agent/wl/wlr_virtual_pointer_unstable_v1.py" ] \
        || die "pywayland's scanner did not write the protocol classes"
}

write_config() {
    [ -f "$config" ] && return 0
    say "No $config yet. Enter to accept a default."
    local panel layout keybind
    read -r -p "Laptop panel connector [eDP-1]: " panel </dev/tty || true
    read -r -p "PC keyboard layout, XKB name [us]: " layout </dev/tty || true
    read -r -p "Keybind that gives the laptop its screen back [SUPER + CTRL + SHIFT + Delete]: " keybind </dev/tty || true
    panel=${panel:-eDP-1}; layout=${layout:-us}; keybind=${keybind:-SUPER + CTRL + SHIFT + Delete}
    printf '%s' "$panel" | grep -Eq '^[A-Za-z0-9._-]+$' || die "panel must be a connector name such as eDP-1"
    printf '%s' "$layout" | grep -Eq '^[A-Za-z0-9_-]+$' || die "keyboard layout must be an XKB name such as us or dk"
    printf '%s' "$keybind" | grep -Eq '^[A-Za-z0-9_+ ]+$' || die "keybind must be plain, such as SUPER + F12"
    mkdir -p "$config_dir"
    (
        umask 077
        cat > "$config" <<EOF
# LaptopRemote agent. The PC's address is added here by pairing from the viewer; the secret too.
allowed_addresses = []
panel = "$panel"
keyboard_layout = "$layout"
restore_keybind = "$keybind"
# encoder = "video/x-raw,format=VUYA ! vah265lpenc name=enc rate-control=cbr bitrate={bitrate_kbps} b-frames=0 key-int-max=1024 target-usage=7"
# bitrate_kbps = 20000
EOF
    )
    chmod 600 "$config"
    say "wrote $config"
}

install_picker() {
    mkdir -p "$(dirname "$picker")"
    install -m 755 "$install_dir/agent/laptopremote-picker" "$picker"
    # sed delimiter is | throughout: the marker holds a # and the paths hold /
    if grep -qF "$marker" "$xdph"; then
        # ours already; make sure the active line below the marker points at this install
        sed -i "/^$marker/{n;s|^\([ \t]*custom_picker_binary[ \t]*=[ \t]*\).*|\1$picker|}" "$xdph"
    elif grep -qF "$block_begin" "$xdph"; then
        sed -i "/^$block_begin\$/,/^$block_end\$/{s|^\([ \t]*custom_picker_binary[ \t]*=[ \t]*\).*|\1$picker|}" "$xdph"
    elif grep -Eq '^[ \t]*custom_picker_binary[ \t]*=' "$xdph"; then
        local current original
        current=$(grep -E -m 1 '^[ \t]*custom_picker_binary[ \t]*=' "$xdph")
        # a line that already names a laptopremote-picker was put there by hand before setup.sh
        # existed; what remove must restore then is the portal's own picker
        case "$current" in
            */laptopremote-picker*) original="    custom_picker_binary = hyprland-preview-share-picker" ;;
            *) original=$current ;;
        esac
        # the old line stays as a marked comment above the new one, so remove can put it back
        sed -i "0,/^[ \t]*custom_picker_binary[ \t]*=.*/{s|^[ \t]*custom_picker_binary[ \t]*=.*|$marker $original\n    custom_picker_binary = $picker|}" "$xdph"
    else
        printf '\n%s\nscreencopy {\n    custom_picker_binary = %s\n}\n%s\n' "$block_begin" "$picker" "$block_end" >> "$xdph"
    fi
    systemctl --user restart xdg-desktop-portal-hyprland.service xdg-desktop-portal.service 2>/dev/null || true
}

remove_picker() {
    if grep -qF "$block_begin" "$xdph" 2>/dev/null; then
        sed -i "/^$block_begin\$/,/^$block_end\$/d" "$xdph"
        sed -i -e ':a' -e '/^\n*$/{$d;N;ba' -e '}' "$xdph"
    elif grep -qF "$marker" "$xdph" 2>/dev/null; then
        # the marked comment holds the original line; it replaces the line below it
        sed -i "/^$marker /{N;s|^$marker \(.*\)\n.*|\1|}" "$xdph"
    fi
    rm -f "$picker"
    systemctl --user restart xdg-desktop-portal-hyprland.service xdg-desktop-portal.service 2>/dev/null || true
}

install_keybind() {
    local keybind
    keybind=$(toml_value restore_keybind "SUPER + CTRL + SHIFT + Delete")
    remove_keybind quiet
    cat >> "$bindings" <<LUA

-- LaptopRemote begin
-- The physical way out while the PC shows this laptop: brings the laptop display back and stops
-- the agent, so the viewer cannot take the display again. Start the agent again with
--   systemctl --user start laptopremote-agent
o.bind("$keybind", "LaptopRemote: bring the laptop display back",
  "sh " .. os.getenv("HOME") .. "/laptopremote/agent/laptopremote-restore --stop-agent", { locked = true })
-- LaptopRemote end
LUA
}

remove_keybind() {
    [ -f "$bindings" ] || return 0
    if grep -q '^-- LaptopRemote begin' "$bindings"; then
        # the block and the blank line setup put before it
        sed -i -e '/^-- LaptopRemote begin$/,/^-- LaptopRemote end$/d' "$bindings"
        sed -i -e ':a' -e '/^\n*$/{$d;N;ba' -e '}' "$bindings"
        [ "${1:-}" = quiet ] || say "keybind block removed from $bindings"
    fi
}

install_unit() {
    mkdir -p "$(dirname "$unit")"
    install -m 644 "$install_dir/agent/laptopremote-agent.service" "$unit"
    systemctl --user daemon-reload
    systemctl --user enable --quiet laptopremote-agent.service
    # before pairing the config has no secret and no addresses; the agent would only exit with a
    # config error, so it is started by the pairing command instead
    if grep -Eq '^[ \t]*secret[ \t]*=' "$config"; then
        systemctl --user restart laptopremote-agent.service
    else
        systemctl --user reset-failed laptopremote-agent.service 2>/dev/null || true
        say "the agent starts when the PC pairs"
    fi
}

do_install() {
    hypr_env
    check_requirements
    copy_code
    write_config
    install_picker
    install_keybind
    hyprctl reload >/dev/null 2>&1 || true
    install_unit
    say "installed. Next: on the PC start LaptopRemote.exe; its setup dialog pairs over ssh and adds the PC's address."
    if systemctl is-active --quiet ufw 2>/dev/null; then
        say "ufw is active; allow ssh and the control port from the PC (or its subnet), as root:"
        say "  sudo ufw allow proto tcp from <PC address or subnet> to any port 22,47800"
    fi
}

remove_code() {
    # only what install put there: a clone that was installed from $install_dir itself keeps its files
    if [ -e "$install_dir/.git" ]; then
        say "$install_dir is a git clone; its files are left alone"
        return 0
    fi
    rm -rf "$install_dir/agent" "$install_dir/protocol" "$install_dir/incoming"
    rmdir "$install_dir" 2>/dev/null || true
}

do_remove() {
    hypr_env
    [ -x "$install_dir/agent/laptopremote-restore" ] && sh "$install_dir/agent/laptopremote-restore" --stop-agent || true
    systemctl --user disable --now laptopremote-agent.service 2>/dev/null || true
    rm -f "$unit"
    systemctl --user daemon-reload
    remove_keybind
    hyprctl reload >/dev/null 2>&1 || true
    remove_picker
    remove_code
    if [ "${1:-}" = "--purge" ]; then
        rm -rf "$config_dir"
        say "removed, config and certificate included"
    else
        say "removed; $config_dir kept (use remove --purge to delete it)"
    fi
}

case "${1:-}" in
    install) do_install ;;
    remove) do_remove "${2:-}" ;;
    *) die "usage: setup.sh install | remove [--purge]" ;;
esac
