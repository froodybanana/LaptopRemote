import unittest

from gi.repository import GLib

from laptopremote_agent import config as config_module
from laptopremote_agent.config import Config
from laptopremote_agent.session import Session


class FakeHypr:
    def __init__(self):
        self.outputs, self.disabled, self.calls, self.workspace = set(), set(), [], 3
        self.workspaces = {}

    def output_exists(self, name):
        return name in self.outputs

    def create_output(self, name):
        self.outputs.add(name)
        self.calls.append(("create", name))

    def remove_output(self, name):
        self.outputs.discard(name)
        self.calls.append(("remove", name))

    def set_mode(self, name, width, height, scale):
        self.calls.append(("mode", name, width, height, scale))

    def output_disabled(self, name):
        return name in self.disabled

    def active_workspace(self, name):
        return self.workspaces.get(name, self.workspace)

    def disable_output(self, name):
        self.disabled.add(name)
        self.calls.append(("disable", name))

    def enable_output(self, name):
        self.disabled.discard(name)
        self.calls.append(("enable", name))

    def focus_workspace(self, number):
        self.calls.append(("focus", number))

    def wake(self):
        self.calls.append(("wake",))


class FakeCapture:
    made = []

    def __init__(self, output, on_ready, on_error):
        self.output, self.on_ready, self.on_error, self.closed = output, on_ready, on_error, False
        FakeCapture.made.append(self)

    def start(self):
        pass

    def close(self):
        self.closed = True


class FakePipeline:
    made = []

    def __init__(self, fd, node, host, port, bind_port, encoder, on_error):
        self.args, self.on_error = (fd, node, host, port, bind_port, encoder), on_error
        self.started = self.stopped = False
        self.keyframes = self.frames = 0
        FakePipeline.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def force_keyframe(self):
        self.keyframes += 1


def pump():
    context = GLib.MainContext.default()
    for _ in range(50):
        context.iteration(False)


class SessionTests(unittest.TestCase):
    def setUp(self):
        FakeCapture.made, FakePipeline.made = [], []
        self.hypr = FakeHypr()
        self.session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                               pipeline_factory=FakePipeline, settle_ms=0)

    def tearDown(self):
        pump()  # let timers of this test's session run out before the next test

    def test_start_creates_output_and_streams(self):
        self.session.start(1601, 901, 1.25, "192.0.2.10", 47801, on_error=self.fail)
        pump()
        self.assertEqual(self.hypr.calls, [("create", "LAPTOPREMOTE"), ("mode", "LAPTOPREMOTE", 1600, 900, 1.25),
                                           ("disable", "eDP-1"), ("focus", 3), ("wake",)])
        FakeCapture.made[0].on_ready(9, 90)
        self.assertEqual(FakePipeline.made[0].args, (9, 90, "192.0.2.10", 47801, 47802,
                                                     config_module.DEFAULT_ENCODER.format(bitrate_kbps=20000)))
        self.assertTrue(FakePipeline.made[0].started)

    def test_resize_restarts_stream_and_ignores_stale_capture(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        pump()
        first = FakeCapture.made[0]
        self.session.resize(1280, 720, 1)
        pump()
        self.assertTrue(first.closed)
        first.on_ready(9, 90)
        self.assertEqual(FakePipeline.made, [])
        FakeCapture.made[1].on_ready(10, 91)
        self.assertEqual(len(FakePipeline.made), 1)
        self.assertIn(("mode", "LAPTOPREMOTE", 1280, 720, 1), self.hypr.calls)
        self.assertEqual(self.hypr.calls.count(("create", "LAPTOPREMOTE")), 1)

    def test_pipeline_that_cannot_be_built_is_reported(self):
        def broken(*args):
            raise RuntimeError("no such element")

        errors = []
        session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                          pipeline_factory=broken, settle_ms=0, max_restarts=0)
        session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=errors.append)
        pump()
        FakeCapture.made[0].on_ready(9, 90)
        self.assertEqual(len(errors), 1)
        self.assertIn("no such element", errors[0])

    def test_stop_survives_a_compositor_error(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        pump()

        def broken(name):
            raise RuntimeError("compositor gone")

        self.hypr.remove_output = broken
        self.session.stop()  # must not raise
        self.assertFalse(self.session.active)

    def test_keyframe_reaches_pipeline(self):
        self.session.keyframe()  # nothing running: no error
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        pump()
        FakeCapture.made[0].on_ready(9, 90)
        self.session.keyframe()
        self.assertEqual(FakePipeline.made[0].keyframes, 1)

    def test_stop_tears_everything_down(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        pump()
        FakeCapture.made[0].on_ready(9, 90)
        self.session.stop()
        self.assertTrue(FakePipeline.made[0].stopped)
        self.assertTrue(FakeCapture.made[0].closed)
        # the laptop ends up showing the workspace the viewer was showing, not an empty new one
        self.assertEqual(self.hypr.calls[-3:], [("enable", "eDP-1"), ("remove", "LAPTOPREMOTE"), ("focus", 3)])
        self.session.stop()  # twice is harmless
        self.assertEqual(self.hypr.calls.count(("remove", "LAPTOPREMOTE")), 1)

    def test_resize_does_not_touch_the_panel_again(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        self.session.resize(1280, 720, 1)
        self.assertEqual(self.hypr.calls.count(("disable", "eDP-1")), 1)
        self.assertEqual(self.hypr.calls.count(("focus", 3)), 1)

    def test_stop_enables_panel_before_removing_output(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        self.session.stop()
        # the laptop ends up showing the workspace the viewer was showing, not an empty new one
        self.assertEqual(self.hypr.calls[-3:], [("enable", "eDP-1"), ("remove", "LAPTOPREMOTE"), ("focus", 3)])

    def test_stop_enables_panel_even_if_removal_fails(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)

        def broken(name):
            raise RuntimeError("compositor gone")

        self.hypr.output_exists = broken
        self.session.stop()  # must not raise
        self.assertIn(("enable", "eDP-1"), self.hypr.calls)

    def test_stop_removes_output_even_if_enable_fails(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)

        def broken(name):
            raise RuntimeError("no such monitor")

        self.hypr.enable_output = broken
        self.session.stop()  # must not raise
        self.assertIn(("remove", "LAPTOPREMOTE"), self.hypr.calls)

    def test_failed_takeover_is_undone_by_stop(self):
        real = self.hypr.disable_output

        def broken(name):
            real(name)
            raise RuntimeError("refused")

        self.hypr.disable_output = broken
        with self.assertRaises(RuntimeError):
            self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        self.session.stop()
        # the laptop ends up showing the workspace the viewer was showing, not an empty new one
        self.assertEqual(self.hypr.calls[-3:], [("enable", "eDP-1"), ("remove", "LAPTOPREMOTE"), ("focus", 3)])

    def test_recover_cleans_up_after_a_dead_agent(self):
        self.session.recover()
        self.assertEqual(self.hypr.calls, [])
        self.hypr.outputs, self.hypr.disabled = {"LAPTOPREMOTE"}, {"eDP-1"}
        self.session.recover()
        self.assertEqual(self.hypr.calls, [("enable", "eDP-1"), ("remove", "LAPTOPREMOTE"), ("focus", 3)])

    def test_recover_survives_a_compositor_error(self):
        def broken(name):
            raise RuntimeError("compositor gone")

        self.hypr.output_exists = broken
        self.session.recover()  # must not raise

    def test_reapply_takes_the_panel_again_after_a_config_reload(self):
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)
        pump()
        # what a reload leaves: the panel back on showing a new empty workspace, the output at the config's mode
        self.hypr.disabled.clear()
        self.hypr.workspaces = {"eDP-1": 4, "LAPTOPREMOTE": 3}
        self.session.reapply()
        pump()
        self.assertEqual(self.hypr.calls[-4:], [("mode", "LAPTOPREMOTE", 1600, 900, 1), ("disable", "eDP-1"),
                                                ("focus", 3), ("wake",)])
        self.assertTrue(FakeCapture.made[0].closed)
        self.assertEqual(len(FakeCapture.made), 2)

    def test_reapply_without_a_session_does_nothing(self):
        self.session.reapply()
        pump()
        self.assertEqual(self.hypr.calls, [])
        self.assertEqual(FakeCapture.made, [])

    def test_reapply_that_fails_is_reported(self):
        errors = []
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=errors.append)
        pump()

        def broken(*args):
            raise RuntimeError("compositor gone")

        self.hypr.set_mode = broken
        self.session.reapply()  # must not raise: it runs inside an event callback
        self.assertEqual(len(errors), 1)
        self.assertIn("compositor gone", errors[0])

    def test_recover_enables_a_panel_left_off_without_an_output(self):
        self.hypr.disabled = {"eDP-1"}
        self.session.recover()
        self.assertEqual(self.hypr.calls, [("enable", "eDP-1")])

    def test_a_failed_wake_does_not_end_the_session(self):
        def broken():
            raise RuntimeError("dpms refused")

        self.hypr.wake = broken
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.fail)  # must not raise
        pump()
        self.assertEqual(len(FakeCapture.made), 1)
        self.session.pause()
        self.session.resume()  # must not raise
