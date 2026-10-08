"""LaptopRemote agent. Run inside the Hyprland session: python3 -m laptopremote_agent"""
import os
import signal
import sys

import dbus.mainloop.glib
from gi.repository import GLib

from . import clipboard
from . import config as config_module
from . import events
from . import inject
from . import security
from . import xkb
from .server import Server
from .session import Session


def main():
    runtime = os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    try:
        config = config_module.load()
        context = security.server_context(config.certificate_path, config.private_key_path)
        keymap = xkb.Keymap(config.keyboard_layout, config.keyboard_variant, config.keyboard_options)
    except (config_module.ConfigError, security.SecurityError, xkb.XkbError, OSError) as error:
        print(error, flush=True)
        return 1
    session = Session(config, input_factory=lambda output: inject.open(output, keymap),
                      clipboard_factory=clipboard.open)
    session.recover()
    server = Server(config, session, context)
    try:
        events.EventWatch(events.connect(),
                          lambda name, data: session.reapply() if name == "configreloaded" else None)
    except OSError as error:
        print(f"no Hyprland event socket ({error}); a config reload during a session will not be noticed", flush=True)
    loop = GLib.MainLoop()
    for number in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, number, loop.quit)
    allowed = ", ".join(str(network) for network in config.allowed_addresses)
    print(f"listening on port {server.port} for {allowed}", flush=True)
    try:
        loop.run()
    finally:
        server.close()  # stops the session: panel back on, headless output removed
    return 0


if __name__ == "__main__":
    sys.exit(main())
