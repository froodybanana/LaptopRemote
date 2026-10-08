import pathlib
import socket
import ssl
import tempfile
import time
import unittest

from gi.repository import GLib

from laptopremote_agent import protocol, security
from laptopremote_agent.config import Config
from laptopremote_agent.server import Server

SECRET = "s" * 64
HELLO = {"type": "hello", "version": 1, "width": 1600, "height": 900, "scale": 1, "video_port": 47801,
         "secret": SECRET}

FOLDER = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(FOLDER.cleanup)
security.create_certificate(pathlib.Path(FOLDER.name) / "cert.pem", pathlib.Path(FOLDER.name) / "key.pem")
CONTEXT = security.server_context(pathlib.Path(FOLDER.name) / "cert.pem", pathlib.Path(FOLDER.name) / "key.pem")
CLIENT = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
CLIENT.check_hostname = False
CLIENT.verify_mode = ssl.CERT_NONE


class FakeSession:
    def __init__(self):
        self.calls = []

    def start(self, width, height, scale, host, port, on_error, on_clipboard=None):
        self.on_error, self.on_clipboard = on_error, on_clipboard
        self.calls.append(("start", width, height, scale, host, port))

    def resize(self, width, height, scale):
        self.calls.append(("resize", width, height, scale))

    def keyframe(self):
        self.calls.append(("keyframe",))

    def pause(self):
        self.calls.append(("pause",))

    def resume(self):
        self.calls.append(("resume",))

    def stop(self):
        self.calls.append(("stop",))

    def pointer_move(self, x, y):
        self.calls.append(("pointer_move", x, y))

    def pointer_button(self, name, down):
        self.calls.append(("pointer_button", name, down))

    def pointer_wheel(self, dx, dy):
        self.calls.append(("pointer_wheel", dx, dy))

    def key(self, code, down):
        self.calls.append(("key", code, down))

    def release_input(self):
        self.calls.append(("release_input",))

    def set_clipboard(self, text):
        self.calls.append(("set_clipboard", text))


def pump(seconds=0.2):
    context = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        context.iteration(False)
        time.sleep(0.005)


class ServerTests(unittest.TestCase):
    def make(self, allowed="127.0.0.1", timeout=5.0):
        self.session = FakeSession()
        self.server = Server(Config([allowed], control_port=0, secret=SECRET), self.session, CONTEXT,
                             heartbeat_timeout=timeout, tick_ms=50, bind_address="127.0.0.1")
        self.addCleanup(self.server.close)

    def connect_plain(self):
        client = socket.create_connection(("127.0.0.1", self.server.port))
        client.settimeout(1)
        self.addCleanup(client.close)
        pump()
        return client

    def connect(self):
        """A viewer that has finished the TLS handshake and said nothing yet."""
        raw = socket.create_connection(("127.0.0.1", self.server.port))
        client = CLIENT.wrap_socket(raw, do_handshake_on_connect=False)
        self.addCleanup(client.close)
        client.setblocking(False)
        for _ in range(200):
            try:
                client.do_handshake()
                break
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                pump(0.01)
        else:
            self.fail("the TLS handshake did not finish")
        pump()
        return client

    def viewer(self, allowed="127.0.0.1", timeout=5.0):
        self.make(allowed, timeout)
        return self.connect()

    def drain(self, client):
        """Everything the agent has sent so far, and whether it has closed the connection."""
        pump()
        reader, messages = protocol.FrameReader(), []
        while True:
            try:
                data = client.recv(65536)
            except ssl.SSLWantReadError:
                return messages, False
            except OSError:
                return messages, True
            if not data:
                return messages, True
            messages += reader.feed(data)

    def read(self, client, heartbeats=False):
        # once a viewer is welcomed, heartbeats are mixed into everything it reads
        return [message for message in self.drain(client)[0] if heartbeats or message["type"] != "heartbeat"]

    def closed(self, client):
        return self.drain(client)[1]

    def test_hello_starts_session_and_is_welcomed(self):
        client = self.viewer()
        client.sendall(protocol.encode({**HELLO, "scale": 1.25}))
        pump()
        self.assertEqual(self.session.calls, [("start", 1600, 900, 1.25, "127.0.0.1", 47801)])
        self.assertEqual(self.read(client)[0], {"type": "welcome", "version": 1, "video_send_port": 47802})

    def test_resize_keyframe_goodbye(self):
        client = self.viewer()
        for message in (HELLO, {"type": "resize", "width": 1280, "height": 720, "scale": 1},
                        {"type": "keyframe"}, {"type": "goodbye"}):
            client.sendall(protocol.encode(message))
        pump()
        self.assertEqual(self.session.calls[1:], [("resize", 1280, 720, 1), ("keyframe",), ("stop",)])

    def test_pause_and_resume_reach_the_session(self):
        client = self.viewer()
        for message in (HELLO, {"type": "pause"}, {"type": "resume"}):
            client.sendall(protocol.encode(message))
        pump()
        self.assertEqual(self.session.calls[1:], [("pause",), ("resume",)])

    INPUT = ({"type": "mouse_move", "x": 640, "y": 360}, {"type": "mouse_button", "button": "left", "down": True},
             {"type": "mouse_wheel", "dx": 0, "dy": -1.5}, {"type": "key", "code": 30, "down": True},
             {"type": "release"})

    def test_input_reaches_the_session(self):
        client = self.viewer()
        for message in (HELLO, *self.INPUT):
            client.sendall(protocol.encode(message))
        pump()
        self.assertEqual(self.session.calls[1:], [("pointer_move", 640, 360), ("pointer_button", "left", True),
                                                  ("pointer_wheel", 0, -1.5), ("key", 30, True),
                                                  ("release_input",)])

    def test_input_before_hello_is_ignored(self):
        client = self.viewer()
        for message in self.INPUT:
            client.sendall(protocol.encode(message))
        pump()
        self.assertEqual(self.session.calls, [])

    def test_input_from_an_unauthenticated_connection_does_not_reach_the_session(self):
        first = self.viewer()
        first.sendall(protocol.encode(HELLO))
        pump()
        second = self.connect()
        for message in self.INPUT:
            second.sendall(protocol.encode(message))
        pump()
        self.assertEqual(len(self.session.calls), 1)

    def test_clipboard_reaches_the_session(self):
        client = self.viewer()
        for message in (HELLO, {"type": "clipboard", "text": "blåbær\n"}):
            client.sendall(protocol.encode(message))
        pump()
        self.assertEqual(self.session.calls[1:], [("set_clipboard", "blåbær\n")])

    def test_clipboard_before_hello_is_ignored(self):
        client = self.viewer()
        client.sendall(protocol.encode({"type": "clipboard", "text": "not yet"}))
        pump()
        self.assertEqual(self.session.calls, [])

    def test_laptop_clipboard_is_sent_to_the_viewer(self):
        client = self.viewer()
        client.sendall(protocol.encode(HELLO))
        pump()
        self.session.on_clipboard("from the laptop")
        self.assertIn({"type": "clipboard", "text": "from the laptop"}, self.read(client))

    def test_clipboard_that_does_not_fit_is_not_sent(self):
        client = self.viewer()
        client.sendall(protocol.encode(HELLO))
        pump()
        self.session.on_clipboard("\x01" * 400000)  # six bytes each in JSON: longer than a frame may be
        messages, closed = self.drain(client)
        self.assertEqual([message["type"] for message in messages if message["type"] != "heartbeat"], ["welcome"])
        self.assertFalse(closed)
        self.assertEqual(len(self.session.calls), 1)

    def test_clipboard_after_the_viewer_left_goes_nowhere(self):
        client = self.viewer()
        client.sendall(protocol.encode(HELLO) + protocol.encode({"type": "goodbye"}))
        pump()
        self.session.on_clipboard("too late")  # nobody to send it to, and nothing raised

    def test_messages_before_hello_are_ignored(self):
        client = self.viewer()
        for kind in ("keyframe", "pause", "resume"):
            client.sendall(protocol.encode({"type": kind}))
        pump()
        self.assertEqual(self.session.calls, [])

    def test_wrong_version_gets_error(self):
        client = self.viewer()
        client.sendall(protocol.encode({**HELLO, "version": 2}) + protocol.encode(HELLO))
        pump()
        self.assertEqual([message["type"] for message in self.read(client)], ["error"])
        self.assertEqual(self.session.calls, [])

    def test_wrong_secret_is_refused(self):
        client = self.viewer(timeout=1.0)
        client.sendall(protocol.encode({**HELLO, "secret": "x" * 64}))
        messages, closed = self.drain(client)
        self.assertEqual([message["type"] for message in messages], ["error"])
        self.assertNotIn(SECRET, messages[0]["message"])
        # left open for a moment: closing with unread bytes waiting would reset the connection
        # and the viewer would never see why it was refused
        self.assertFalse(closed)
        pump(1.0)
        self.assertTrue(self.closed(client))
        self.assertEqual(self.session.calls, [])

    def test_a_refused_connection_gets_no_second_try(self):
        client = self.viewer()
        for message in ({**HELLO, "secret": "x" * 64}, {"type": "keyframe"}, HELLO):
            client.sendall(protocol.encode(message))
        self.assertEqual([message["type"] for message in self.drain(client)[0]], ["error"])
        self.assertEqual(self.session.calls, [])

    def assert_still_served(self, client):
        messages, closed = self.drain(client)  # whatever was sent before now
        self.assertFalse(closed)
        pump(0.2)
        messages, closed = self.drain(client)
        self.assertFalse(closed)
        self.assertIn({"type": "heartbeat"}, messages)

    def test_wrong_secret_does_not_disturb_the_session(self):
        first = self.viewer()
        first.sendall(protocol.encode(HELLO))
        self.read(first)
        second = self.connect()
        second.sendall(protocol.encode({**HELLO, "secret": "x" * 64}))
        self.assertEqual([message["type"] for message in self.read(second)], ["error"])
        self.assertEqual([call[0] for call in self.session.calls], ["start"])
        self.assert_still_served(first)

    def test_a_stalled_handshake_does_not_disturb_the_session(self):
        first = self.viewer()
        first.sendall(protocol.encode(HELLO))
        self.read(first)
        stalled = self.connect_plain()
        stalled.sendall(b"")  # the first three bytes of a TLS hello, then nothing
        self.assertEqual([call[0] for call in self.session.calls], ["start"])
        self.assert_still_served(first)

    def test_a_huge_bad_frame_gets_a_short_answer(self):
        # echoing it back to a peer that does not read would hold up everything else
        client = self.viewer()
        body = b'{"type":"' + b"A" * 500000 + b'"}'
        data = len(body).to_bytes(4, "big") + body
        while data:
            try:
                data = data[client.send(data[:16384]):]
            except (ssl.SSLWantWriteError, ssl.SSLWantReadError):
                pump(0.01)
        messages = self.read(client)
        self.assertEqual([message["type"] for message in messages], ["error"])
        self.assertIn("unknown message type", messages[0]["message"])
        self.assertLess(len(messages[0]["message"]), 200)

    def test_a_frame_longer_than_one_tls_record_arrives_whole(self):
        client = self.viewer()
        client.sendall(protocol.encode(HELLO))
        self.read(client)
        client.sendall(protocol.encode({"type": "resize", "width": 1280, "height": 720, "scale": 1,
                                        "padding": "p" * 40000}))
        pump()
        self.assertEqual(self.session.calls[-1], ("resize", 1280, 720, 1))

    def test_a_wrong_secret_from_the_active_viewer_ends_its_session(self):
        client = self.viewer()
        client.sendall(protocol.encode(HELLO))
        self.read(client)
        client.sendall(protocol.encode({**HELLO, "secret": "x" * 64}))
        pump()
        self.assertEqual([call[0] for call in self.session.calls], ["start", "stop"])

    def test_unauthenticated_connection_does_not_disturb_the_session(self):
        first = self.viewer()
        first.sendall(protocol.encode(HELLO))
        self.read(first)
        self.connect_plain()  # connects and says nothing
        third = self.connect()  # finishes TLS and asks for things without a hello
        for kind in ("keyframe", "pause", "goodbye"):
            third.sendall(protocol.encode({"type": kind}))
        pump()
        self.assertEqual([call[0] for call in self.session.calls], ["start"])
        self.assert_still_served(first)

    def test_a_newer_unauthenticated_connection_closes_the_older_one(self):
        older = self.viewer()
        self.connect()
        self.assertTrue(self.closed(older))

    def test_silent_connection_is_closed(self):
        self.make(timeout=0.3)
        silent = self.connect_plain()
        pump(0.6)
        self.assertEqual(silent.recv(10), b"")

    def test_chatter_without_hello_is_closed_all_the_same(self):
        client = self.viewer(timeout=0.3)
        try:
            for _ in range(6):
                client.sendall(protocol.encode({"type": "heartbeat"}))
                pump(0.1)
        except OSError:
            pass  # the agent has already closed it
        self.assertTrue(self.closed(client))

    def test_plaintext_is_refused(self):
        self.make()
        plain = self.connect_plain()
        plain.sendall(protocol.encode(HELLO))
        pump()
        plain.settimeout(0.5)
        try:
            while plain.recv(65536):  # a TLS alert may come before the close
                pass
        except ConnectionError:
            pass  # closed either way; a timeout here would mean it was left open
        self.assertEqual(self.session.calls, [])

    def test_no_heartbeat_before_hello(self):
        client = self.viewer()
        pump(0.3)
        self.assertEqual(self.drain(client), ([], False))

    def test_silence_ends_session(self):
        client = self.viewer(timeout=0.3)
        client.sendall(protocol.encode(HELLO))
        pump(0.6)
        self.assertEqual(self.session.calls[-1], ("stop",))

    def test_heartbeats_are_sent_and_keep_session_alive(self):
        client = self.viewer(timeout=0.3)
        client.sendall(protocol.encode(HELLO))
        for _ in range(6):
            pump(0.1)
            client.sendall(protocol.encode({"type": "heartbeat"}))
        self.assertNotIn(("stop",), self.session.calls)
        self.assertIn({"type": "heartbeat"}, self.read(client, heartbeats=True))

    def test_foreign_address_rejected(self):
        self.make(allowed="127.0.0.2")
        client = self.connect_plain()
        self.assertEqual(client.recv(10), b"")  # closed by the agent without a word
        self.assertEqual(self.session.calls, [])

    def test_address_inside_an_allowed_network_is_accepted(self):
        client = self.viewer(allowed="127.0.0.0/8")
        client.sendall(protocol.encode(HELLO))
        pump()
        self.assertEqual(self.read(client)[0]["type"], "welcome")

    def test_new_connection_replaces_old(self):
        first = self.viewer()
        first.sendall(protocol.encode(HELLO))
        pump()
        second = self.connect()
        self.assertEqual([call[0] for call in self.session.calls], ["start"])  # not replaced before its hello
        second.sendall(protocol.encode(HELLO))
        pump()
        self.assertEqual([call[0] for call in self.session.calls], ["start", "stop", "start"])
        self.assertTrue(self.closed(first))
        self.assertEqual(self.read(second)[0]["type"], "welcome")

    def test_session_error_is_forwarded(self):
        client = self.viewer()
        client.sendall(protocol.encode(HELLO))
        pump()
        self.session.on_error("encoder failed")
        self.assertIn({"type": "error", "message": "encoder failed"}, self.read(client))

    def test_session_start_failure_is_reported_and_server_lives_on(self):
        client = self.viewer()

        def broken(*args, **kwargs):
            raise RuntimeError("compositor gone")

        self.session.start = broken
        client.sendall(protocol.encode(HELLO))
        pump()
        messages = self.read(client)
        self.assertEqual(messages[0]["type"], "error")
        self.assertIn("compositor gone", messages[0]["message"])
        # the takeover may have got as far as switching the panel off: the session must be stopped
        self.assertEqual(self.session.calls, [("stop",)])
        del self.session.start
        second = self.connect()
        second.sendall(protocol.encode(HELLO))
        self.assertEqual(self.read(second)[0]["type"], "welcome")

    def test_session_stop_failure_does_not_stop_the_heartbeat(self):
        client = self.viewer(timeout=0.3)

        def broken():
            raise RuntimeError("compositor gone")

        self.session.stop = broken
        client.sendall(protocol.encode(HELLO))
        pump(0.6)  # silence: the server drops the session and stop() raises
        second = self.connect()
        second.sendall(protocol.encode(HELLO))
        pump(0.2)
        self.assertIn({"type": "heartbeat"}, self.read(second, heartbeats=True))

    def test_garbage_closes_connection(self):
        client = self.viewer()
        client.sendall(b"\x00\x00\x00\x03{no")
        messages, closed = self.drain(client)
        self.assertEqual(messages[0]["type"], "error")
        self.assertTrue(closed)

    def test_a_failing_resize_or_resume_stops_the_session(self):
        for kind in ("resize", "resume"):
            client = self.viewer()

            def broken(*args):
                raise RuntimeError("compositor gone")

            setattr(self.session, kind, broken)
            client.sendall(protocol.encode(HELLO))
            client.sendall(protocol.encode({"type": "resize", "width": 1280, "height": 720, "scale": 1}
                                           if kind == "resize" else {"type": "resume"}))
            pump()
            self.assertEqual(self.session.calls[-1], ("stop",), kind)
            self.assertIn("error", [message["type"] for message in self.read(client)], kind)
            self.server.close()
