# LaptopRemote design

Sections are added as they are approved.

## Purpose

Show the Linux laptop as a window on the Windows PC so the laptop never has to be touched. VNC in principle, but app-like: crisp, hardware-encoded, and the desktop resizes to fit the window. Built for exactly one laptop and one PC, not for general use.

## Machines

- Laptop: Omarchy (Arch Linux), Hyprland on Wayland
- PC: Windows 10

## Scope

Version 1:

- Video from laptop to PC
- Keyboard and mouse from PC to laptop
- Clipboard in both directions

Later: audio.

## Approach

Custom agent and viewer built on standard media plumbing. No codec, display driver, or kernel module is written. Sunshine and Moonlight were rejected because clipboard and resize-to-fit do not fit the Moonlight protocol and the result is somebody else's app in a window.

## Stack

- Agent on the laptop: Python, GStreamer bindings, Wayland virtual pointer and virtual keyboard protocols
- Viewer on the PC: C# on .NET 10, owns the window, input capture and clipboard, hands GStreamer a window handle to render into with Direct3D decoding
- Control protocol: length-prefixed JSON over TCP, defined once per language

## Architecture and session lifecycle

### Programs and channels

- Agent: systemd user service inside the Hyprland session, listens for the viewer
- Viewer: plain Windows app with one resizable window
- Control channel: one TCP connection carrying hello, resize, input events, clipboard, heartbeat, goodbye
- Video channel: H.265 over UDP from laptop to PC, tuned for low latency over smoothness

### Lifecycle

1. Viewer connects and sends its window size
2. Agent creates a headless Hyprland output at that size, disables the laptop panel so workspaces move onto it, and starts the encode pipeline aimed at the PC
3. Video flows laptop to PC; input and clipboard flow over the control channel
4. On window resize the viewer waits for the drag to settle and sends the new size; the agent changes the output mode and the stream restarts at the new resolution with a fresh keyframe
5. On disconnect the agent removes the headless output and re-enables the laptop panel

### Never strand the laptop

With the panel off the laptop has no visible screen if anything goes wrong.

- The agent restores the panel on disconnect, on a lost viewer heartbeat, on its own exit, and on service stop
- A Hyprland keybind on the laptop restores the panel, so there is always a physical way out

### Capture without a picker

Hyprland's PipeWire screen share normally shows a picker asking which output to share, which an unattended agent cannot answer, and an unanswered picker blocks the portal.

- The portal's picker is replaced by a wrapper script, `LaptopRemote/agent/laptopremote-picker`, installed at `~/.local/bin/laptopremote-picker` and named as `screencopy.custom_picker_binary` in `~/.config/hypr/xdph.conf`
- Just before asking the portal for a stream the agent writes the headless output's name to `$XDG_RUNTIME_DIR/laptopremote-pick`; the wrapper sees the file, deletes it and answers with that output
- Any other screen share on the laptop finds no file and gets the normal picker
- Restore tokens are not used
- The headless output is always named `LAPTOPREMOTE`

## Video path

Target: under 50 ms from laptop render to PC pixels on wired or 5 GHz Wi-Fi. The probe measured a median of 19 ms and a 90th percentile of 25 ms from a cursor move sent to the laptop until the frame reached the PC's video sink, with the laptop on Wi-Fi.

### Capture

- Source is the headless output only, at native resolution
- Frames are sent when the screen changes, so a still desktop costs almost no bandwidth or battery

### Encode

- H.265 with colour at full resolution (4:4:4) on the laptop's Intel GPU through VAAPI: `videoconvert ! vah265lpenc`. At half resolution (4:2:0) coloured text on a dark background smears
- Frames reach the encoder through system memory and are converted to YUV on the CPU, about 3 ms a frame: given frames that stay on the GPU (`vapostproc`), the 4:4:4 encoder smears the colour of the top rows or shears the picture at most sizes
- Up to 60 fps, no B-frames, around 20 Mbit/s, tuned for lowest delay
- Keyframes on demand, not on a timer
- The agent answers the encoder's "is the source live" question itself with yes; left alone the encoder asks before the PipeWire source knows, holds every frame back by 35–70 ms and never releases the last frame of a burst

### Transport

- RTP over UDP on the LAN, jitter buffer of about 10–20 ms on the PC
- On a detected gap, and whenever it has no decodable picture (session start, after a resize), the viewer requests a keyframe over the control channel and repeats the request until a picture arrives; nothing is retransmitted

### Decode and display

- Hardware decode on the PC's NVIDIA GPU (`nvh265dec`; the Direct3D 11 H.265 decoder does not take 4:4:4), rendered by Direct3D 11 straight into the viewer window with no clock sync
- The stream is 1:1 with the window's pixels; during a resize drag the old picture is stretched until the new resolution arrives
- The viewer sends the PC monitor's scale factor with the window size and the agent sets the same scale on the headless output

### Cursor

- Version 1: the laptop cursor is drawn into the video and trails the real mouse by the stream latency
- Later: a locally drawn cursor on the PC, which needs cursor shapes forwarded from Hyprland

## Input and clipboard

### Mouse

- Position is sent as absolute coordinates mapped 1:1 from window pixels to the headless output
- All buttons, vertical and horizontal wheel with smooth-scroll precision
- Relative (captured) mouse for games is out of scope

### Keyboard

- If the viewer window has focus it gets the input: Win key, Alt+Tab and other system shortcuts are grabbed and sent to the laptop
- There is no release key; focus leaves by clicking another window or the taskbar
- Ctrl+Alt+Del stays with Windows because no app can intercept it
- The viewer sends physical keys, not characters; the agent's config names the PC keyboard's layout and the laptop applies it
- On focus loss or disconnect the agent releases every key still held

### Injection on the laptop

- Hyprland's virtual-pointer and virtual-keyboard protocols, pointer bound to the headless output, no root needed
- Fallback if the probe shows trouble: a kernel `uinput` device with a one-time permission rule

### Clipboard

- Text only in version 1, capped at 1 MB
- Laptop to PC: sent immediately when the laptop clipboard changes
- PC to laptop: sent when the viewer window gains focus, not on every copy
- Each side remembers the last value it received and does not send it back

## Viewer window behaviour

### Window

- Standard Windows title bar, not borderless: it is the mouse-only way to move, snap, minimize and close, and lets VirtualDisplay region-maximize work on it
- Maximize fills the monitor or region and the laptop desktop resizes to match; true fullscreen is left for later
- The window reopens where and how big it was left

### Starting and connecting

- Plain single-instance app, no tray icon
- On start it connects to the laptop named in its config
- While the laptop is unreachable the window shows "Waiting for laptop…" and retries quietly

### Ending and pausing

- Close ends the session and the laptop panel comes back on
- Minimize keeps the session but the agent stops encoding; restore resumes with a fresh keyframe
- If the laptop sleeps or drops off the network the viewer returns to "Waiting for laptop…" and reconnects when it is back

### Config

- PC: `%APPDATA%\LaptopRemote\config.json` — laptop address and ports, the ssh target used for pairing, and `decoder` (the GStreamer decoder element, default `nvh265dec`)
- Laptop: `~/.config/laptopremote/config.toml` — panel name, PC keyboard layout, PC addresses allowed to connect, `encoder` (the GStreamer fragment between `videoconvert` and `h265parse`, naming its encoder `enc` and using `{bitrate_kbps}`; default is the VUYA plus `vah265lpenc` text) and `restore_keybind` (default `SUPER + CTRL + SHIFT + Delete`)
- Both configs also hold the shared secret and the pinned certificate described under Security
- Timing constants (retry, silence, debounce, keyframe interval) are tuning values and stay in code

## Security

- The agent is a remote keyboard into the laptop, so it answers only this PC
- A connection is accepted only from the PC address in the agent's config and only with the shared secret both configs hold
- The control channel runs over TLS with a pinned self-signed certificate, so keystrokes and clipboard contents never cross the network in clear
- Video is unencrypted in version 1
- Setup opens one TCP port on the laptop firewall; the PC needs no firewall rule
- The viewer sends a small UDP packet every second from its video receive socket to the agent's video sending port, so Windows Firewall lets the stream in as a reply; the agent sends video from that fixed port

## Remote access (optional)

On one LAN nothing here is needed. Away from home the laptop is reached through a WireGuard network with a hub on a server both machines can reach, so neither home router needs a port opened. Any other VPN that gives the PC a route to the laptop works the same way; LaptopRemote only needs the tunnel addresses in its configs.

### Network

- The hub listens on one UDP port and forwards between peers; the tunnel is one private subnet, the hub its first address, the laptop and each client an address of their own
- Every peer routes only the tunnel subnet through the tunnel; the rest of its traffic is untouched
- Laptop and clients keep the tunnel open with a 25 s keepalive, so the laptop stays reachable behind NAT
- The hub firewall opens the UDP port and allows forwarding from `wg0` to `wg0`; the laptop firewall allows ssh and the control port from the tunnel subnet
- Agent RTP packets are 1200 bytes, so video crosses the tunnel without fragmenting

### Use

- SSH to the laptop's tunnel address from any peer
- Viewer: `laptopAddress` is the laptop's tunnel address on a remote client and its LAN address at home, so the LAN path stays the fast one; a remote client needs the same GPU class and GStreamer runtime as the PC
- The agent's `allowed_addresses` lists the LAN address of the PC and the tunnel subnet; the shared secret and pinned certificate apply unchanged
- Video over the tunnel is encrypted by WireGuard; on the LAN it stays in clear

### Configuration

WireGuard is configured by one text file per machine: an `[Interface]` block with that machine's private key and tunnel address, and one `[Peer]` block per other machine with its public key, its allowed addresses and, for the hub, its endpoint. On Linux the file is `/etc/wireguard/wg0.conf`, brought up by `wg-quick@wg0`; on Windows the WireGuard app imports the same file as a tunnel.

- `remote/wireguard.sh` writes those files from a few values: hub endpoint, tunnel subnet, and a name per peer. It generates a key pair per peer, prints the hub's `[Peer]` blocks to paste into the hub's file, and writes `laptop.conf` and one `.conf` per client, ready to install on Linux or import on Windows
- The script never touches a machine; installing the files, opening the hub port and the laptop firewall rules are listed as commands for the user to run
- Nothing in the agent or the viewer knows about WireGuard

## Failure handling

- Heartbeats run every second; after 5 seconds of silence the agent ends the session and restores the laptop panel
- The systemd unit runs a restore script on any exit, so the panel comes back even if the Python process dies
- On an encoder or pipeline error the agent restarts the pipeline a few times, then reports the error and the viewer shows it in the window
- A new connection from the PC replaces the old one
- Window sizes are clamped to a minimum and rounded to even dimensions

## Layout

- `LaptopRemote/agent` — Python agent, its `setup.sh` and developer scripts
- `LaptopRemote/viewer` — C# viewer
- `LaptopRemote/protocol` — message reference and sample messages
- `LaptopRemote/remote` — the optional WireGuard config writer
- `LaptopRemote/README.md`, `LICENSE` — the public face of the folder

## Release

The folder is published on GitHub as a repository of its own, seeded from a single clean commit of the folder after this pass; later releases re-snapshot the folder. Nothing else from the parent repository, its history or `agent.db` is published.

### Disclaimer and scope

- The README opens with a prominent disclaimer: the project was written for one particular pair of machines, a Windows PC with an NVIDIA GPU and an Omarchy laptop with an Intel VAAPI GPU, and anyone else must adjust code and configuration to their own setup
- The README gives a brief specification of each side: laptop Hyprland with the Lua config as Omarchy ships it, PipeWire with `xdg-desktop-portal-hyprland`, a VAAPI GPU with low-power H.265 4:4:4 encoding, `python3` with PyGObject, dbus-python and pywayland, GStreamer VA plugins, `openssl`, `jq`; PC Windows 10 or 11 x64, an NVIDIA GPU, the GStreamer MSVC runtime, the built-in OpenSSH client
- What is configurable without code changes: encoder and decoder elements, ports, bitrate, panel, keyboard layout, restore keybind, allowed addresses; everything else in the README is a statement of what the code assumes

### Scrubbing

- No login names, host names, LAN or tunnel addresses of the author anywhere in the folder; tests and error texts use documentation addresses such as `192.0.2.10` and `10.0.0.0/24`
- `deploy.sh` and `test.sh` stay as developer tools and require `LAPTOPREMOTE_HOST`; the PC-side `pair.py` and `install.sh` are replaced by the setup below

### Laptop setup

`agent/setup.sh install|remove [--purge]`, run on the laptop from a clone:

- Install checks requirements and names each missing one; copies `agent/` and `protocol/` to `~/laptopremote` and generates the pywayland bindings; installs the picker to `~/.local/bin` and points `custom_picker_binary` in `~/.config/hypr/xdph.conf` at it, keeping the previous line as a marked comment above; appends the keybind block between the `-- LaptopRemote begin` and `end` markers in `~/.config/hypr/bindings.lua`; installs and enables the unit; restarts the portal services
- Install writes `config.toml` if absent, asking for panel, keyboard layout and restore keybind with defaults; the PC's address is added by pairing, not asked for
- Firewall commands that need root are printed, not run
- Rerunning install updates the code and restarts the agent; it adopts an installation made by hand through the same markers
- Remove runs the restore script, stops and disables the unit, and reverses every item above, restoring the original `xdph.conf` line; `--purge` also deletes `~/.config/laptopremote`

### PC first run

- With no `config.json`, or with `--setup`, the viewer opens a dialog: laptop address, ssh user, Pair. It runs the built-in `ssh.exe` in batch mode with the agent's pair command, writes the secret, certificate pin, address and ssh target to `config.json`, and starts
- The agent's pair module takes `--allow-client` and adds the ssh client's address from `SSH_CONNECTION` to `allowed_addresses` when missing
- When ssh is refused for lack of a key, the dialog offers to open a console that creates a key and copies it to the laptop; the user types the laptop password once there
- The dialog checks the GStreamer runtime folder and the decoder element and shows the download link if either is missing
- Parsing the pair result and writing the config are Core code with tests; the dialog itself is thin

### Verification

- `dotnet test` and `agent/test.sh` cover the new config keys, the pair result and `--allow-client`
- Setup checklist on the laptop: install over the existing installation, remove, install again, pair from the PC's dialog, then the existing manual checklist

## Testing

- Both test suites read the same sample-message files in `LaptopRemote/protocol`, so a protocol change made on one side only fails the other side's tests
- Unit tests, written test-first: Windows scancode to Linux keycode mapping, coordinate mapping, resize debounce, clipboard echo suppression, reconnect logic
- Video, input injection and panel restore are checked on the real machines with a written manual checklist
- The capture and latency probe ran before anything else was built; its scripts are in `LaptopRemote/probe`
