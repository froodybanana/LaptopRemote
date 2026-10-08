"""Unattended ScreenCast portal session for one Hyprland output."""
import os

import dbus

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"
_counter = 0


class PortalCapture:
    """Calls on_ready(fd, node) once the stream exists, or on_error(text). Needs the GLib D-Bus main loop."""

    def __init__(self, output, on_ready, on_error):
        self.output, self.on_ready, self.on_error = output, on_ready, on_error
        self.bus = dbus.SessionBus()
        self.portal = dbus.Interface(self.bus.get_object(PORTAL, PORTAL_PATH), SCREENCAST)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.session = None
        self.fd = None
        self.closed = False
        self.matches = []
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.flag = os.path.join(runtime, "laptopremote-pick")

    def start(self):
        global _counter
        _counter += 1
        self._call(self.portal.CreateSession, self._on_session,
                   options={"session_handle_token": f"lr{os.getpid()}_{_counter}"})

    def close(self):
        self.closed = True
        # a flag the picker never consumed would answer another program's share request
        try:
            os.unlink(self.flag)
        except FileNotFoundError:
            pass
        for match in self.matches:
            match.remove()
        self.matches = []
        if self.session:
            try:
                dbus.Interface(self.bus.get_object(PORTAL, self.session),
                               "org.freedesktop.portal.Session").Close()
            except dbus.DBusException:
                pass
            self.session = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _call(self, method, handler, *args, options):
        global _counter
        _counter += 1
        token = f"lr{os.getpid()}_{_counter}"
        path = f"{PORTAL_PATH}/request/{self.sender}/{token}"
        self.matches.append(self.bus.add_signal_receiver(handler, "Response", REQUEST, PORTAL, path))
        try:
            method(*args, dbus.Dictionary({**options, "handle_token": token}, signature="sv"))
        except dbus.DBusException as error:
            self._fail(f"portal call failed: {error.get_dbus_message()}")

    def _fail(self, text):
        if not self.closed:
            self.on_error(text)

    def _on_session(self, code, results):
        if self.closed:
            return
        if code != 0:
            return self._fail(f"portal CreateSession answered {code}")
        self.session = str(results["session_handle"])
        # the portal runs the picker inside SelectSources and blocks on it: the flag must be there first
        with open(self.flag, "w") as flag:
            flag.write(self.output)
        self._call(self.portal.SelectSources, self._on_selected, self.session, options={
            "types": dbus.UInt32(1), "multiple": False, "cursor_mode": dbus.UInt32(2)})

    def _on_selected(self, code, results):
        if self.closed:
            return
        if code != 0:
            return self._fail(f"portal SelectSources answered {code}")
        self._call(self.portal.Start, self._on_started, self.session, "", options={})

    def _on_started(self, code, results):
        if self.closed:
            return
        if code != 0:
            return self._fail(f"portal Start answered {code}")
        try:
            node = int(results["streams"][0][0])
            self.fd = self.portal.OpenPipeWireRemote(self.session, dbus.Dictionary({}, signature="sv")).take()
        except Exception as error:  # raised inside a D-Bus handler it would only be printed
            return self._fail(f"portal stream: {error}")
        self.on_ready(self.fd, node)
