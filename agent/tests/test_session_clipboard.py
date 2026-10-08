import unittest

from laptopremote_agent.config import Config
from laptopremote_agent.session import Session
from test_session import FakeCapture, FakeHypr, FakePipeline, pump


class FakeClipboard:
    def __init__(self, send, log):
        self.send, self.calls, self.broken = send, [], False
        log.append(self)

    def set(self, text):
        if self.broken:
            raise OSError("compositor gone")
        self.calls.append(("set", text))

    def close(self):
        self.calls.append(("close",))


class SessionClipboardTests(unittest.TestCase):
    def setUp(self):
        FakeCapture.made, FakePipeline.made = [], []
        self.hypr, self.clipboards, self.received = FakeHypr(), [], []
        self.session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                               pipeline_factory=FakePipeline, settle_ms=0,
                               clipboard_factory=lambda send: FakeClipboard(send, self.clipboards))

    def tearDown(self):
        pump()

    def start(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail,
                           on_clipboard=self.received.append)

    def test_clipboard_opens_with_the_session(self):
        self.assertEqual(self.clipboards, [])  # nobody reads the laptop's clipboard while no viewer is connected
        self.start()
        self.session.resize(1280, 720, 1)
        self.assertEqual(len(self.clipboards), 1)

    def test_text_from_the_viewer_is_set(self):
        self.start()
        self.session.set_clipboard("from the PC")
        self.assertEqual(self.clipboards[0].calls, [("set", "from the PC")])

    def test_laptop_text_reaches_the_callback(self):
        self.start()
        self.clipboards[0].send("from the laptop")
        self.assertEqual(self.received, ["from the laptop"])

    def test_laptop_text_still_crosses_while_paused(self):
        self.start()
        self.session.pause()
        self.clipboards[0].send("from the laptop")
        self.session.set_clipboard("from the PC")
        self.assertEqual(self.received, ["from the laptop"])
        self.assertEqual(self.clipboards[0].calls, [("set", "from the PC")])

    def test_stop_closes_the_clipboard(self):
        self.start()
        self.session.stop()
        self.assertEqual(self.clipboards[0].calls, [("close",)])
        self.assertIn(("enable", "eDP-1"), self.hypr.calls)

    def test_nothing_after_stop(self):
        self.start()
        self.session.stop()
        self.clipboards[0].send("too late")
        self.session.set_clipboard("too late")
        self.assertEqual(self.received, [])
        self.assertEqual(self.clipboards[0].calls, [("close",)])

    def test_a_new_session_gets_a_new_clipboard(self):
        self.start()
        self.session.stop()
        self.start()
        self.assertEqual(len(self.clipboards), 2)

    def test_clipboard_failure_leaves_the_session_running(self):
        def refuse(send):
            raise RuntimeError("no data control")
        self.session.clipboard_factory = refuse
        self.start()
        pump()
        self.assertTrue(self.session.active)
        self.assertEqual(len(FakeCapture.made), 1)
        self.session.set_clipboard("nowhere to put it")  # and nothing raised

    def test_broken_clipboard_is_dropped(self):
        self.start()
        self.clipboards[0].broken = True
        self.session.set_clipboard("one")  # raises inside, is logged, the clipboard is closed
        self.assertEqual(self.clipboards[0].calls, [("close",)])
        self.assertTrue(self.session.active)
        self.session.set_clipboard("two")
        self.assertEqual(self.clipboards[0].calls, [("close",)])

    def test_a_failing_callback_does_not_reach_the_clipboard(self):
        def broken(text):
            raise OSError("viewer gone")
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail, on_clipboard=broken)
        self.clipboards[0].send("from the laptop")  # raised inside a GLib callback it would end the watch

    def test_a_resize_brings_the_clipboard_back(self):
        self.start()
        self.clipboards[0].broken = True
        self.session.set_clipboard("one")
        self.session.resize(1280, 720, 1)
        self.assertEqual(len(self.clipboards), 2)

    def test_session_without_clipboard_ignores_it(self):
        session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                          pipeline_factory=FakePipeline, settle_ms=0)
        session.set_clipboard("before any start")
        session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        session.set_clipboard("no clipboard")
        session.stop()


if __name__ == "__main__":
    unittest.main()
