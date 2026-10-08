"""Control channel: TLS, one authenticated viewer at a time, heartbeats, messages handed to the session."""
import socket
import ssl
import time
import traceback

from gi.repository import GLib

from . import protocol, security


class Peer:
    """One accepted connection. It is `secure` once the TLS handshake is done."""

    def __init__(self, conn, host):
        self.conn, self.host = conn, host
        self.reader = protocol.FrameReader()
        self.secure = False
        self.refused = False  # told why it is not welcome; nothing it sends counts any more
        self.accepted = self.heard = time.monotonic()
        self.watch = None


class Server:
    def __init__(self, config, session, context, heartbeat_timeout=5.0, tick_ms=1000, bind_address="0.0.0.0"):
        self.config, self.session, self.context = config, session, context
        self.heartbeat_timeout = heartbeat_timeout
        self.listener = socket.create_server((bind_address, config.control_port))
        self.port = self.listener.getsockname()[1]
        # waiting: accepted but has not said hello with the secret; it can do nothing to the session.
        # active: the viewer the session belongs to.
        self.waiting = self.active = None
        self.accept_watch = GLib.io_add_watch(self.listener.fileno(), GLib.PRIORITY_DEFAULT,
                                              GLib.IO_IN, self._on_accept)
        self.tick = GLib.timeout_add(tick_ms, self._on_tick)

    def close(self):
        for peer in (self.waiting, self.active):
            if peer is not None:
                self._close(peer)
        GLib.source_remove(self.accept_watch)
        GLib.source_remove(self.tick)
        self.listener.close()

    def _on_accept(self, fd, condition):
        conn, (host, _) = self.listener.accept()
        if not self.config.allows(host):
            conn.close()
            return True
        # never blocking: a peer that has proved nothing must not be able to hold up the main loop
        conn.setblocking(False)
        try:
            conn = self.context.wrap_socket(conn, server_side=True, do_handshake_on_connect=False)
        except OSError:
            conn.close()
            return True
        if self.waiting is not None:
            self._close(self.waiting)
        self.waiting = peer = Peer(conn, host)
        peer.watch = GLib.io_add_watch(conn.fileno(), GLib.PRIORITY_DEFAULT,
                                       GLib.IO_IN | GLib.IO_HUP, self._on_data, peer)
        return True

    def _on_data(self, fd, condition, peer):
        if not peer.secure:
            try:
                peer.conn.do_handshake()
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                return True
            except OSError:  # not TLS, a refused version, or gone
                self._close(peer)
                return True
            peer.secure = True
        while peer.conn is not None:
            try:
                data = peer.conn.recv(65536)
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                break
            except OSError:
                data = b""
            if not data:
                self._close(peer)
                break
            self._on_bytes(peer, data)
            if peer.conn is not None and not peer.conn.pending():
                break
        return True

    def _on_bytes(self, peer, data):
        peer.heard = time.monotonic()
        try:
            messages = peer.reader.feed(data)
        except protocol.ProtocolError as error:
            self._send(peer, {"type": "error", "message": str(error)})
            self._close(peer)
            return
        for message in messages:
            if peer.conn is None:
                break
            try:
                self._handle(peer, message)
            except Exception as error:  # an exception escaping a GLib callback would remove the watch
                traceback.print_exc()
                self._send(peer, {"type": "error", "message": f"{type(error).__name__}: {error}"})
                self._close(peer)

    def _handle(self, peer, message):
        kind = message["type"]
        if peer.refused:
            return
        if kind == "hello":
            if message["version"] != protocol.VERSION:
                self._refuse(peer, f"agent speaks protocol version {protocol.VERSION}")
                return
            if not security.same_secret(self.config.secret, message["secret"]):
                self._refuse(peer, "wrong secret")
                return
            if peer is not self.active:
                if self.active is not None:
                    self._close(self.active)  # a new viewer from the PC replaces the old one
                self.waiting, self.active = None, peer
            self.session.start(message["width"], message["height"], message["scale"], peer.host,
                               message["video_port"], on_error=self._on_session_error,
                               on_clipboard=self._on_session_clipboard)
            self._send(peer, {"type": "welcome", "version": protocol.VERSION,
                              "video_send_port": self.config.video_send_port})
        elif peer is not self.active:
            return
        elif kind == "resize":
            self.session.resize(message["width"], message["height"], message["scale"])
        elif kind == "keyframe":
            self.session.keyframe()
        elif kind == "pause":
            self.session.pause()
        elif kind == "resume":
            self.session.resume()
        elif kind == "mouse_move":
            self.session.pointer_move(message["x"], message["y"])
        elif kind == "mouse_button":
            self.session.pointer_button(message["button"], message["down"])
        elif kind == "mouse_wheel":
            self.session.pointer_wheel(message["dx"], message["dy"])
        elif kind == "key":
            self.session.key(message["code"], message["down"])
        elif kind == "release":
            self.session.release_input()
        elif kind == "clipboard":
            self.session.set_clipboard(message["text"])
        elif kind == "goodbye":
            self._close(peer)

    def _refuse(self, peer, text):
        self._send(peer, {"type": "error", "message": text})
        if peer is self.waiting:
            # not closed here: closing while it has unread bytes on the way resets the connection and
            # the viewer never sees the reason. It hangs up itself, or the tick closes it.
            peer.refused = True
        else:
            self._close(peer)

    def _on_session_error(self, text):
        if self.active is not None:
            self._send(self.active, {"type": "error", "message": text})

    def _on_session_clipboard(self, text):
        if self.active is not None:
            try:
                self._send(self.active, {"type": "clipboard", "text": text})
            except protocol.ProtocolError:  # mostly characters that JSON escapes; never the text itself in the log
                print("clipboard text does not fit a frame and was not sent", flush=True)

    def _on_tick(self):
        now = time.monotonic()
        if self.active is not None:
            if now - self.active.heard > self.heartbeat_timeout:
                self._close(self.active)
            else:
                self._send(self.active, {"type": "heartbeat"})
        # counted from the accept, whatever it sends: only a good hello keeps a connection
        if self.waiting is not None and now - self.waiting.accepted > self.heartbeat_timeout:
            self._close(self.waiting)
        return True

    def _send(self, peer, message):
        if peer.conn is None or not peer.secure:
            return
        frame = protocol.encode(message)  # before the socket is touched: it raises for a text too long to frame
        try:
            if peer is self.active:
                peer.conn.settimeout(2)
                peer.conn.sendall(frame)
                peer.conn.setblocking(False)
            else:
                # the main loop never waits for a peer that has proved nothing; all it is ever
                # sent is one short error, which is simply lost if it does not fit
                peer.conn.send(frame)
        except (ssl.SSLWantWriteError, ssl.SSLWantReadError):
            pass
        except OSError:
            self._close(peer)

    def _close(self, peer):
        if peer.conn is None:
            return
        GLib.source_remove(peer.watch)
        conn, peer.conn = peer.conn, None
        conn.close()
        if peer is self.waiting:
            self.waiting = None
        if peer is self.active:
            self.active = None
            try:
                self.session.stop()
            except Exception:  # a failed cleanup must not take the accept or tick source with it
                traceback.print_exc()
