"""Pause, resume and the automatic restart of a failed stream."""
import unittest

from laptopremote_agent.config import Config
from laptopremote_agent.session import Session

from test_session import FakeCapture, FakeHypr, FakePipeline, pump


class StreamTests(unittest.TestCase):
    def setUp(self):
        FakeCapture.made, FakePipeline.made = [], []
        self.hypr, self.errors = FakeHypr(), []

    def tearDown(self):
        pump()  # let timers of this test's session run out before the next test

    def start(self, healthy_ms=10**6, max_restarts=3):
        self.session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                               pipeline_factory=FakePipeline, settle_ms=0, restart_ms=0,
                               healthy_ms=healthy_ms, max_restarts=max_restarts)
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.errors.append)
        return self.stream()

    def stream(self):
        """Lets the newest capture deliver its stream and returns the pipeline built for it."""
        pump()
        FakeCapture.made[-1].on_ready(9, 90)
        return FakePipeline.made[-1]

    def test_pause_stops_stream_and_keeps_output(self):
        pipeline = self.start()
        before = list(self.hypr.calls)
        self.session.pause()
        pump()
        self.assertTrue(pipeline.stopped)
        self.assertTrue(FakeCapture.made[0].closed)
        self.assertEqual(self.hypr.calls, before)
        self.assertEqual(len(FakeCapture.made), 1)

    def test_resume_starts_a_new_stream(self):
        self.start()
        self.session.pause()
        self.session.resume()
        # the laptop may have put its displays to sleep while the viewer was minimized
        self.assertEqual(self.hypr.calls[-1], ("wake",))
        second = self.stream()
        self.assertEqual(len(FakeCapture.made), 2)
        self.assertTrue(second.started)
        self.session.resume()  # not paused: nothing happens
        pump()
        self.assertEqual(len(FakeCapture.made), 2)

    def test_resume_without_a_session_does_nothing(self):
        session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                          pipeline_factory=FakePipeline, settle_ms=0)
        session.pause()
        session.resume()
        pump()
        self.assertEqual(FakeCapture.made, [])
        self.assertEqual(self.hypr.calls, [])

    def test_resize_while_paused_keeps_stream_off(self):
        self.start()
        self.session.pause()
        self.session.resize(1280, 720, 1)
        pump()
        self.assertIn(("mode", "LAPTOPREMOTE", 1280, 720, 1), self.hypr.calls)
        self.assertEqual(len(FakeCapture.made), 1)
        self.session.resume()
        pump()
        self.assertEqual(len(FakeCapture.made), 2)

    def test_a_new_session_is_not_paused(self):
        self.start()
        self.session.pause()
        self.session.stop()
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.errors.append)
        pump()
        self.assertEqual(len(FakeCapture.made), 2)

    def test_pipeline_error_restarts_the_stream(self):
        first = self.start()
        first.on_error("video pipeline: encoder lost")
        second = self.stream()
        self.assertTrue(first.stopped)
        self.assertIsNot(second, first)
        self.assertTrue(second.started)
        self.assertEqual(self.errors, [])
        # the restart goes through the whole setup again, so an output that vanished is put back
        self.assertEqual(self.hypr.calls.count(("mode", "LAPTOPREMOTE", 1600, 900, 1)), 2)

    def test_capture_error_restarts_the_stream(self):
        self.start()
        self.session.resize(1280, 720, 1)
        pump()
        FakeCapture.made[-1].on_error("portal Start answered 2")
        pump()
        self.assertEqual(len(FakeCapture.made), 3)
        self.assertEqual(self.errors, [])

    def test_error_is_reported_after_three_restarts(self):
        pipeline = self.start()
        for _ in range(3):
            pipeline.on_error("video pipeline: encoder lost")
            pipeline = self.stream()
        self.assertEqual(self.errors, [])
        pipeline.on_error("video pipeline: encoder lost")
        pump()
        self.assertEqual(self.errors, ["video pipeline: encoder lost"])
        self.assertEqual(len(FakeCapture.made), 4)  # no fifth attempt
        self.assertTrue(pipeline.stopped)

    def test_healthy_stream_resets_the_restart_count(self):
        pipeline = self.start(healthy_ms=0)
        for _ in range(5):
            pump()  # the stream has now run for healthy_ms
            pipeline.on_error("video pipeline: encoder lost")
            pipeline = self.stream()
        self.assertEqual(self.errors, [])

    def test_resize_resets_the_restart_count(self):
        pipeline = self.start()
        for _ in range(3):
            pipeline.on_error("video pipeline: encoder lost")
            pipeline = self.stream()
        self.session.resize(1280, 720, 1)
        pipeline = self.stream()
        pipeline.on_error("video pipeline: encoder lost")
        pump()
        self.assertEqual(self.errors, [])

    def test_error_from_an_old_stream_is_ignored(self):
        first = self.start()
        self.session.resize(1280, 720, 1)
        self.stream()
        first.on_error("late")
        pump()
        self.assertEqual(len(FakeCapture.made), 2)
        self.assertEqual(self.errors, [])

    def test_no_restart_while_paused_or_after_stop(self):
        pipeline = self.start()
        self.session.pause()
        pipeline.on_error("late")
        pump()
        self.assertEqual(len(FakeCapture.made), 1)
        self.session.stop()
        pipeline.on_error("later")
        pump()
        self.assertEqual(len(FakeCapture.made), 1)
        self.assertEqual(self.errors, [])

    def test_restart_that_cannot_reach_the_compositor_is_reported(self):
        pipeline = self.start()

        def broken(*args):
            raise RuntimeError("compositor gone")

        self.hypr.set_mode = broken
        pipeline.on_error("video pipeline: encoder lost")
        pump()
        self.assertEqual(len(self.errors), 1)
        self.assertIn("compositor gone", self.errors[0])

    def wakes(self, seconds=0.15):
        import time
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pump()
            time.sleep(0.005)
        return self.hypr.calls.count(("wake",))

    def watched(self, stall_ms=30):
        """A session whose stall watchdog fires quickly; returns the first stream's pipeline."""
        self.session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                               pipeline_factory=FakePipeline, settle_ms=0, restart_ms=0,
                               stall_ms=stall_ms, stall_check_ms=5)
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.errors.append)
        return self.stream()

    def run_for(self, seconds, each=None):
        import time
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if each is not None:
                each()
            pump()
            time.sleep(0.005)

    def test_stream_that_delivers_no_frame_is_restarted(self):
        # a short hiccup makes the portal run out of buffers and its retry never recovers; a new capture does
        first = self.watched()
        self.run_for(0.2)
        self.assertTrue(first.stopped)
        self.assertGreaterEqual(len(FakeCapture.made), 2)
        self.assertEqual(self.errors, [])

    def test_stream_that_delivers_frames_is_left_alone(self):
        pipeline = self.watched()

        def frame():
            pipeline.frames += 1

        self.run_for(0.2, frame)
        self.assertFalse(pipeline.stopped)
        self.assertEqual(len(FakeCapture.made), 1)

    def test_stall_watchdog_stops_with_the_stream(self):
        pipeline = self.watched()
        self.session.pause()
        self.run_for(0.2)
        self.assertEqual(len(FakeCapture.made), 1)
        self.session.resume()
        second = self.stream()
        self.session.stop()
        self.run_for(0.2)
        self.assertEqual(len(FakeCapture.made), 2)
        self.assertEqual(self.errors, [])
        self.assertTrue(second.stopped)

    def test_displays_are_kept_awake_while_the_viewer_is_watching(self):
        # nothing reaches the laptop as input, so its idle timer would put the output to sleep: a black picture
        self.session = Session(Config(["192.0.2.10"]), hypr=self.hypr, capture_factory=FakeCapture,
                               pipeline_factory=FakePipeline, settle_ms=0, wake_ms=20)
        self.session.start(1600, 900, 1, "192.0.2.10", 47801, on_error=self.errors.append)
        self.assertGreaterEqual(self.wakes(), 4)
        self.session.pause()
        paused = self.wakes(0)
        self.assertEqual(self.wakes(), paused)  # minimized: let the laptop sleep
        self.session.resume()
        self.assertGreater(self.wakes(), paused + 2)
        self.session.stop()
        stopped = self.wakes(0)
        self.assertEqual(self.wakes(), stopped)
