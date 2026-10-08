import socket
import unittest

from laptopremote_agent.events import EventWatch

from test_session import pump


class EventWatchTests(unittest.TestCase):
    def setUp(self):
        self.ours, theirs = socket.socketpair()
        self.addCleanup(self.ours.close)
        self.events = []
        self.watch = EventWatch(theirs, lambda name, data: self.events.append((name, data)))
        self.addCleanup(self.watch.close)

    def test_events_are_split_into_name_and_data(self):
        self.ours.sendall(b"configreloaded>>\nworkspace>>2\n")
        pump()
        self.assertEqual(self.events, [("configreloaded", ""), ("workspace", "2")])

    def test_an_event_cut_in_two_is_delivered_once_whole(self):
        self.ours.sendall(b"configrel")
        pump()
        self.assertEqual(self.events, [])
        self.ours.sendall(b"oaded>>\n")
        pump()
        self.assertEqual(self.events, [("configreloaded", "")])

    def test_a_failing_handler_does_not_stop_the_watch(self):
        def broken(name, data):
            self.events.append(name)
            raise RuntimeError("handler failed")

        self.watch.on_event = broken
        self.ours.sendall(b"one>>\n")
        pump()
        self.ours.sendall(b"two>>\n")
        pump()
        self.assertEqual(self.events, ["one", "two"])

    def test_compositor_going_away_ends_the_watch_quietly(self):
        self.ours.close()
        pump()
        self.assertTrue(self.watch.closed)
        self.watch.close()  # twice is harmless
