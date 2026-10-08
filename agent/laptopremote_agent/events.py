"""Hyprland's event socket: one line per event, NAME>>DATA."""
import os
import socket
import traceback

from gi.repository import GLib

from . import hypr


def connect():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(os.path.join(os.path.dirname(hypr._socket_path()), ".socket2.sock"))
    return sock


class EventWatch:
    """Calls on_event(name, data) for every event on a connected event socket, until the compositor goes away."""

    def __init__(self, sock, on_event):
        self.sock, self.on_event = sock, on_event
        self.buffer = b""
        self.closed = False
        self.watch = GLib.io_add_watch(sock.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_data)

    def close(self):
        if not self.closed:
            self.closed = True
            GLib.source_remove(self.watch)
            self.sock.close()

    def _on_data(self, fd, condition):
        try:
            data = self.sock.recv(65536)
        except OSError:
            data = b""
        if not data:
            self.close()
            return False
        self.buffer += data
        *lines, self.buffer = self.buffer.split(b"\n")
        for line in lines:
            name, _, text = line.decode(errors="replace").partition(">>")
            try:
                self.on_event(name, text)
            except Exception:  # an exception escaping a GLib callback would remove the watch
                traceback.print_exc()
        return True
