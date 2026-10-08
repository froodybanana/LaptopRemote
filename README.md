# LaptopRemote

Shows a Linux computer as a resizable window on a Windows computer, with keyboard, mouse and clipboard. The video is hardware encoded on the Linux side and hardware decoded on the Windows side, and the Linux desktop takes the size of the window.

> **This project was written for one specific pair of machines: a Windows 10 PC with an NVIDIA GPU and an Omarchy (Arch Linux, Hyprland) laptop with an Intel GPU using VAAPI. It is published as it is. Anyone wanting to use it on anything else must expect to adjust the code and the configuration to their own hardware and setup. There is no support and no promise it works anywhere else.**

## What it assumes

Linux computer:

- Hyprland with the Lua configuration as Omarchy ships it (`hyprctl eval`, `~/.config/hypr/bindings.lua`)
- PipeWire and `xdg-desktop-portal-hyprland` with `hyprland-preview-share-picker`
- A GPU whose VAAPI driver offers low-power H.265 4:4:4 encoding (`vah265lpenc`)
- `python3` 3.11 or newer with PyGObject, dbus-python and python-pywayland
- GStreamer with the `va`, `pipewire` and `rtp` plugins
- `openssl`, `jq`, systemd user services, an ssh server with key authentication

Windows computer:

- Windows 10 or 11, x64
- An NVIDIA GPU (`nvh265dec` is the only decoder in GStreamer that takes H.265 4:4:4 here)
- The GStreamer 1.x MSVC x86_64 runtime from https://gstreamer.freedesktop.org/download/
- The built-in OpenSSH client
- .NET 10 to build

## What is configurable

Linux computer, `~/.config/laptopremote/config.toml`:

| key | default | meaning |
|-----|---------|---------|
| `allowed_addresses` | written by pairing | IP addresses or networks a viewer may connect from |
| `secret` | written by pairing | shared secret, 32 characters or more |
| `panel` | `eDP-1` | the Linux computer's own screen, off while a viewer is connected |
| `keyboard_layout` | `us` | the Windows keyboard's layout, by its XKB name; `keyboard_variant` and `keyboard_options` too |
| `restore_keybind` | `SUPER + CTRL + SHIFT + Delete` | Hyprland bind that gives the Linux computer its screen back and stops the agent |
| `encoder` | `video/x-raw,format=VUYA ! vah265lpenc name=enc rate-control=cbr bitrate={bitrate_kbps} b-frames=0 key-int-max=1024 target-usage=7` | GStreamer fragment between `videoconvert` and `h265parse`; its encoder must be named `enc` |
| `bitrate_kbps` | `20000` | filled into the encoder fragment |
| `control_port`, `video_send_port` | `47800`, `47802` | TCP control port on the Linux computer, UDP port the video is sent from |
| `certificate`, `private_key` | `cert.pem`, `key.pem` beside the config | the agent's TLS certificate, made by pairing |

Windows computer, `%APPDATA%\LaptopRemote\config.json`:

| key | default | meaning |
|-----|---------|---------|
| `laptopAddress` | from the setup dialog | address of the Linux computer |
| `sshTarget` | from the setup dialog | `user@host` used for pairing |
| `secret`, `certificateSha256` | written by pairing | shared secret and the pin of the Linux computer's certificate |
| `decoder` | `nvh265dec` | GStreamer H.265 decoder element |
| `controlPort`, `videoPort` | `47800`, `47801` | TCP control port on the Linux computer, UDP port the video arrives on |
| `gstreamerBin` | the runtime's default folder | folder with the GStreamer DLLs |

Everything else in this README is a statement of what the code assumes.

## Install

On the Linux computer:

1. Clone this repository anywhere and run `bash agent/setup.sh install`; the code is installed to `~/laptopremote` (a clone living there is used in place, and `remove` leaves it alone)
2. Answer the three prompts (panel, keyboard layout, restore keybind) or press Enter for the defaults
3. If ufw is on, run the firewall commands the script prints

The script checks the requirements and names each missing one, copies the agent to `~/laptopremote`, installs the share picker, the keybind and the systemd user service. Running it again updates the code and restarts the agent.

On the Windows computer:

1. Install the GStreamer runtime
2. Build `LaptopRemote.exe`, for example as a trimmed single file: `dotnet publish viewer/LaptopRemote.Viewer -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=none -p:PublishTrimmed=true -p:_SuppressWinFormsTrimError=true -o publish`
3. Start it. The setup dialog asks for the Linux computer's address and your user name on it; Pair runs the agent's pairing over ssh, which makes the certificate and the secret, allows this Windows computer's address and starts the agent. The window then shows the Linux desktop
4. If the Linux computer has no ssh key for this Windows computer yet, the dialog offers "Install ssh key…": a console makes a key and copies it over, asking for the Linux password once

`LaptopRemote.exe --setup` opens the dialog again, prefilled.

## Remove

- Linux computer: `bash agent/setup.sh remove` takes out everything the install put in place; `remove --purge` also deletes `~/.config/laptopremote`
- Windows computer: delete `%APPDATA%\LaptopRemote`

## Security model

- The agent is a remote keyboard into the Linux computer, so it answers only the Windows computer
- A connection is accepted only from an address in the agent's `allowed_addresses` and only with the shared secret both configs hold
- The control channel runs over TLS with a pinned self-signed certificate, so keystrokes and clipboard contents never cross the network in clear
- Video is unencrypted on the LAN; over a VPN it is encrypted by the VPN
- Setup opens one TCP port on the Linux firewall; the Windows computer needs no firewall rule, because the viewer sends a small UDP packet every second to the agent's sending port and Windows Firewall lets the stream in as a reply

## Remote access (optional)

On one LAN nothing more is needed. Away from home the Linux computer can be reached through a WireGuard network with a hub on a server both machines can reach, so neither home router needs a port opened. Any other VPN that gives the Windows computer a route to the Linux computer works the same way; LaptopRemote only needs the tunnel addresses in its configs.

`bash remote/wireguard.sh --endpoint HOST:PORT --subnet A.B.C.0/24 --out DIR laptop CLIENT...` writes a config file per machine and prints the commands to install them. It touches no machine. The first peer name is always `laptop`, the Linux computer.

## Development

- `agent/test.sh` deploys the agent to the Linux computer and runs its tests there; `agent/deploy.sh` only deploys. Both need `LAPTOPREMOTE_HOST=user@host`
- `dotnet test viewer/LaptopRemote.slnx` runs the viewer's tests
- `protocol/` holds the message reference and sample messages both test suites read
- `probe/` holds throwaway measurement and check scripts
- `design.md` is the design

## Licence

MIT, see `LICENSE`.
