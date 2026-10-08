import unittest

from laptopremote_agent.config import Config
from laptopremote_agent.session import Session
from test_session import FakeCapture, FakeHypr, FakePipeline, pump


class FakeInput:
    def __init__(self, output, log):
        self.output, self.calls, self.broken = output, [], False
        log.append(self)

    def _note(self, *call):
        if self.broken:
            raise OSError("compositor gone")
        self.calls.append(call)

    def move(self, x, y, width, height):
        self._note("move", x, y, width, height)

    def button(self, name, down):
        self._note("button", name, down)

    def wheel(self, dx, dy):
        self._note("wheel", dx, dy)

    def key(self, code, down):
        self._note("key", code, down)

    def release(self):
        self._note("release")

    def close(self):
        self.calls.append(("close",))


class SessionInputTests(unittest.TestCase):
    def setUp(self):
        FakeCapture.made, FakePipeline.made = [], []
        self.hypr, self.inputs = FakeHypr(), []
        self.session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                               pipeline_factory=FakePipeline, settle_ms=0, input_factory=self.open_input)

    def tearDown(self):
        pump()

    def open_input(self, output):
        # the pointer is bound to the output, so the output has to be there and have its mode already
        self.assertIn(("mode", "LAPTOPREMOTE", 1600, 900, 1), self.hypr.calls)
        self.assertTrue(self.hypr.output_exists(output))
        return FakeInput(output, self.inputs)

    def start(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)

    def test_input_opens_after_the_output_exists(self):
        self.start()
        self.assertEqual([made.output for made in self.inputs], ["LAPTOPREMOTE"])

    def test_resize_keeps_the_input(self):
        self.start()
        self.session.resize(1280, 720, 1)
        self.assertEqual(len(self.inputs), 1)
        self.assertEqual(self.inputs[0].calls, [])

    def test_pointer_uses_the_session_size(self):
        self.start()
        self.session.pointer_move(10, 20)
        self.session.resize(1281, 721, 1)
        self.session.pointer_move(30, 40)
        self.assertEqual(self.inputs[0].calls, [("move", 10, 20, 1600, 900), ("move", 30, 40, 1280, 720)])

    def test_buttons_wheel_and_keys_are_passed_on(self):
        self.start()
        self.session.pointer_button("left", True)
        self.session.pointer_wheel(0, -1.5)
        self.session.key(30, True)
        self.session.release_input()
        self.assertEqual(self.inputs[0].calls, [("button", "left", True), ("wheel", 0, -1.5), ("key", 30, True),
                                                ("release",)])

    def test_stop_releases_input(self):
        self.start()
        self.session.key(30, True)
        self.session.stop()
        self.assertEqual(self.inputs[0].calls[-1], ("close",))
        # the keys are let go while the output they were typed on is still there
        self.assertNotIn(("remove", "LAPTOPREMOTE"), self.hypr.calls[:self.hypr.calls.index(("enable", "eDP-1"))])
        self.session.key(30, False)  # after the end nothing is injected
        self.assertEqual(self.inputs[0].calls[-1], ("close",))

    def test_pause_releases_input(self):
        self.start()
        self.session.key(30, True)
        self.session.pause()
        self.assertEqual(self.inputs[0].calls, [("key", 30, True), ("release",)])

    def test_input_failure_leaves_the_session_running(self):
        def refuse(output):
            raise RuntimeError("no virtual pointer")
        self.session.input_factory = refuse
        self.start()
        pump()
        self.assertTrue(self.session.active)
        self.assertEqual(len(FakeCapture.made), 1)
        self.session.pointer_move(1, 1)  # nothing to move, and nothing raised
        self.session.key(30, True)

    def test_broken_injector_is_dropped(self):
        self.start()
        self.inputs[0].broken = True
        self.session.key(30, True)  # raises inside, is logged, the input is closed
        self.assertEqual(self.inputs[0].calls, [("close",)])
        self.assertTrue(self.session.active)
        self.session.key(30, False)
        self.assertEqual(self.inputs[0].calls, [("close",)])

    def test_a_resize_brings_dropped_input_back(self):
        self.start()
        self.inputs[0].broken = True
        self.session.pointer_move(1, 1)
        self.session.resize(1280, 720, 1)
        self.assertEqual(len(self.inputs), 2)

    def test_session_without_input_ignores_input(self):
        session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                          pipeline_factory=FakePipeline, settle_ms=0)
        session.pointer_move(1, 1)  # before any start
        session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        session.pointer_move(1, 1)
        session.pointer_button("left", True)
        session.pointer_wheel(1, 1)
        session.key(30, True)
        session.release_input()
        session.stop()

    def test_recreated_output_gets_new_input(self):
        self.start()
        self.hypr.outputs.discard("LAPTOPREMOTE")  # lost, as after a compositor hiccup
        self.session.reapply()
        self.assertEqual(len(self.inputs), 2)
        self.assertEqual(self.inputs[0].calls, [("close",)])  # its pointer was bound to the output that is gone


if __name__ == "__main__":
    unittest.main()
