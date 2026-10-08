import dataclasses
import ipaddress
import pathlib
import re
import tomllib

DEFAULT_PATH = pathlib.Path.home() / ".config" / "laptopremote" / "config.toml"
SECRET_LENGTH = 32  # the shortest secret accepted; pairing makes one of 64
# GStreamer fragment between videoconvert and h265parse: caps the encoder wants, then the encoder,
# which must be named enc so a keyframe can be forced on it. {bitrate_kbps} is filled from the config.
DEFAULT_ENCODER = ("video/x-raw,format=VUYA ! vah265lpenc name=enc rate-control=cbr bitrate={bitrate_kbps} "
                   "b-frames=0 key-int-max=1024 target-usage=7")
DEFAULT_RESTORE_KEYBIND = "SUPER + CTRL + SHIFT + Delete"


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Config:
    allowed_addresses: tuple  # IP networks a viewer may connect from; a single address counts as its own network
    secret: str = ""  # an empty secret matches nothing
    control_port: int = 47800
    video_send_port: int = 47802
    bitrate_kbps: int = 20000
    panel: str = "eDP-1"  # the laptop's own screen, switched off while a viewer is connected
    certificate: str = "~/.config/laptopremote/cert.pem"
    private_key: str = "~/.config/laptopremote/key.pem"
    keyboard_layout: str = "us"  # the PC keyboard's layout, by its XKB name; the viewer sends physical keys
    keyboard_variant: str = ""
    keyboard_options: str = ""
    encoder: str = DEFAULT_ENCODER
    restore_keybind: str = DEFAULT_RESTORE_KEYBIND  # written into Lua by setup.sh

    def __post_init__(self):
        self.allowed_addresses = tuple(ipaddress.ip_network(entry) for entry in self.allowed_addresses)

    def allows(self, host):
        """Whether a connection from `host` (the address it came from, as text) may become a viewer."""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(address.version == network.version and address in network for network in self.allowed_addresses)

    def encoder_fragment(self):
        """The encoder text with the bitrate filled in, ready for the pipeline."""
        return self.encoder.format(bitrate_kbps=self.bitrate_kbps)

    @property
    def certificate_path(self):
        return pathlib.Path(self.certificate).expanduser()

    @property
    def private_key_path(self):
        return pathlib.Path(self.private_key).expanduser()


def load(path=DEFAULT_PATH):
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    allowed = data.get("allowed_addresses")
    if not isinstance(allowed, list) or not allowed:
        raise ConfigError(f"{path}: allowed_addresses is required, a list such as [\"192.0.2.10\", \"10.0.0.0/24\"]")
    for entry in allowed:  # compared with the address a connection comes from, so a host name would never match
        try:
            if not isinstance(entry, str):
                raise ValueError
            ipaddress.ip_network(entry)
        except ValueError:
            raise ConfigError(f"{path}: allowed_addresses must hold IP addresses or networks "
                              "such as 192.0.2.10 or 10.0.0.0/24") from None
    secret = data.get("secret")
    if not isinstance(secret, str) or len(secret) < SECRET_LENGTH:
        raise ConfigError(f"{path}: secret is missing or too short; run LaptopRemote.exe --setup on the PC")
    # the panel name is written into Lua that Hyprland runs, so only a plain connector name may pass
    panel = data.get("panel", Config.panel)
    if not isinstance(panel, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", panel):
        raise ConfigError(f"{path}: panel must be a connector name such as eDP-1")
    for name, low, high in (("control_port", 1, 65535), ("video_send_port", 1, 65535),
                            ("bitrate_kbps", 500, 200000)):
        value = data.get(name, low)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"{path}: {name} must be a whole number from {low} to {high}")
    for name in ("certificate", "private_key"):
        if not isinstance(data.get(name, ""), str):
            raise ConfigError(f"{path}: {name} must be a file path")
    for name, pattern in (("keyboard_layout", r"[A-Za-z0-9_-]+"), ("keyboard_variant", r"[A-Za-z0-9_-]*"),
                          ("keyboard_options", r"[A-Za-z0-9_:,+()-]*")):
        value = data.get(name, getattr(Config, name))
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ConfigError(f"{path}: {name} must be an XKB name such as us or dk")
    encoder = data.get("encoder", DEFAULT_ENCODER)
    if not isinstance(encoder, str) or "name=enc" not in encoder:
        raise ConfigError(f"{path}: encoder must be a GStreamer fragment whose encoder element is named enc")
    try:
        encoder.format(bitrate_kbps=1)
    except (KeyError, IndexError, ValueError):
        raise ConfigError(f"{path}: encoder may only use the placeholder {{bitrate_kbps}}") from None
    keybind = data.get("restore_keybind", DEFAULT_RESTORE_KEYBIND)
    if not isinstance(keybind, str) or not re.fullmatch(r"[A-Za-z0-9_+ ]+", keybind):
        raise ConfigError(f"{path}: restore_keybind must be a Hyprland bind such as SUPER + CTRL + SHIFT + Delete")
    known = {field.name for field in dataclasses.fields(Config)}
    return Config(**{key: value for key, value in data.items() if key in known})
