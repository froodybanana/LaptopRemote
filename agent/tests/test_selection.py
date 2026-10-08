"""The pipes and timers of WaylandSelection, without a compositor: the Wayland objects are stand-ins."""
import os
import time
import unittest

from gi.repository import GLib

from laptopremote_agent.wayland import InputError, WaylandSelection

LIMIT = 1000


def pump(seconds):
    context = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        context.iteration(False)
        time.sleep(0.001)


class FakeDisplay:
    def flush(self):
        return 0

    def disconnect(self):
        pass


class FakeOffer:
    """The program that copied: `pipe` is its end, once the selection has asked for the text."""

    def __init__(self):
        self.pipe, self.asked, self.destroyed = None, None, False

    def receive(self, kind, fd):
        self.asked, self.pipe = kind, os.dup(fd)

    def destroy(self):
        self.destroyed = True


class FakeSource:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


def is_open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.texts, self.replaced, self.pipes = [], [], []
        selection = self.selection = object.__new__(WaylandSelection)
        selection.on_text, selection.limit, selection.timeout_ms = self.texts.append, LIMIT, 100
        selection.on_replaced = lambda: self.replaced.append(True)
        selection.ready, selection.offers, selection.reading, selection.writing = True, {}, None, {}
        selection.sources, selection.current = set(), None
        selection.display, selection.watch = FakeDisplay(), None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.selection.close()
        for pipe in self.pipes:
            if is_open(pipe):
                os.close(pipe)
        pump(0.01)

    def copy(self, kinds=("text/plain", "text/plain;charset=utf-8")):
        """A program on the laptop copies something that has these types."""
        offer = FakeOffer()
        self.selection.offers[offer] = list(kinds)
        self.selection._on_selection(None, offer)
        if offer.pipe is not None:
            self.pipes.append(offer.pipe)
        return offer

    def test_text_is_read_to_the_end(self):
        offer = self.copy()
        self.assertEqual(offer.asked, "text/plain;charset=utf-8")  # the best type on offer
        self.assertTrue(offer.destroyed)
        os.write(offer.pipe, b"one ")
        pump(0.05)
        self.assertEqual(self.texts, [])  # the program has not finished
        os.write(offer.pipe, b"two")
        os.close(offer.pipe)
        pump(0.05)
        self.assertEqual(self.texts, [b"one two"])
        self.assertIsNone(self.selection.reading)

    def test_something_that_is_not_text_is_not_read(self):
        offer = self.copy(kinds=("image/png",))
        self.assertIsNone(offer.pipe)
        self.assertTrue(offer.destroyed)

    def test_what_the_clipboard_held_at_the_start_is_not_read(self):
        self.selection.ready = False
        offer = self.copy()
        self.assertIsNone(offer.pipe)
        self.assertTrue(offer.destroyed)

    def test_an_empty_clipboard_is_nothing(self):
        self.selection._on_selection(None, None)
        self.assertIsNone(self.selection.reading)

    def test_text_at_the_limit_is_reported_and_longer_is_given_up(self):
        offer = self.copy()
        os.write(offer.pipe, b"x" * LIMIT)
        os.close(offer.pipe)
        pump(0.05)
        self.assertEqual(self.texts, [b"x" * LIMIT])
        offer = self.copy()
        os.write(offer.pipe, b"x" * (LIMIT + 1))
        pump(0.05)
        self.assertIsNone(self.selection.reading)  # without waiting for the end
        with self.assertRaises(BrokenPipeError):
            os.write(offer.pipe, b"more")
        self.assertEqual(len(self.texts), 1)

    def test_a_program_that_never_finishes_is_given_up(self):
        offer = self.copy()
        os.write(offer.pipe, b"begun")
        pump(0.3)
        self.assertIsNone(self.selection.reading)
        with self.assertRaises(BrokenPipeError):
            os.write(offer.pipe, b"more")
        self.assertEqual(self.texts, [])

    def test_a_newer_selection_ends_the_reading_of_the_older(self):
        first = self.copy()
        os.write(first.pipe, b"old")
        second = self.copy()
        with self.assertRaises(BrokenPipeError):
            os.write(first.pipe, b"more")
        os.write(second.pipe, b"new")
        os.close(second.pipe)
        pump(0.3)  # past the first one's timeout, which must be gone with it
        self.assertEqual(self.texts, [b"new"])

    def test_a_failing_receiver_of_the_text_does_not_stop_the_reading(self):
        def broken(data):
            raise OSError("viewer gone")
        self.selection.on_text = broken
        offer = self.copy()
        os.close(offer.pipe)
        pump(0.05)
        self.selection.on_text = self.texts.append
        offer = self.copy()
        os.write(offer.pipe, b"next")
        os.close(offer.pipe)
        pump(0.05)
        self.assertEqual(self.texts, [b"next"])

    def paste(self, data):
        """A program on the laptop asks for our text; gives its end of the pipe."""
        reader, writer = os.pipe()
        self.pipes.append(reader)
        self.selection._serve(writer, data)
        return reader, writer

    def test_a_small_text_is_served_at_once(self):
        reader, writer = self.paste(b"from the PC")
        self.assertEqual(os.read(reader, 100), b"from the PC")
        self.assertEqual(os.read(reader, 100), b"")  # our end is closed
        self.assertEqual(self.selection.writing, {})

    def test_a_text_longer_than_the_pipe_is_served_as_it_is_read(self):
        data = bytes(range(256)) * 4096  # a megabyte; a pipe holds 64 kB
        reader, writer = self.paste(data)
        self.assertIn(writer, self.selection.writing)
        os.set_blocking(reader, False)
        got = bytearray()
        for _ in range(2000):
            pump(0.001)
            try:
                chunk = os.read(reader, 1 << 20)
            except BlockingIOError:
                continue
            if not chunk:
                break
            got += chunk
        self.assertEqual(bytes(got), data)
        self.assertEqual(self.selection.writing, {})
        self.assertFalse(is_open(writer))

    def test_a_reader_that_hangs_up_is_let_go(self):
        reader, writer = os.pipe()
        os.close(reader)
        self.selection._serve(writer, b"nobody reads this")
        self.assertEqual(self.selection.writing, {})
        self.assertFalse(is_open(writer))

    def test_a_reader_that_hangs_up_half_way_is_let_go(self):
        reader, writer = self.paste(b"x" * (1 << 20))
        os.close(reader)
        pump(0.05)
        self.assertEqual(self.selection.writing, {})
        self.assertFalse(is_open(writer))

    def test_a_reader_that_stops_reading_is_given_up(self):
        reader, writer = self.paste(b"x" * (1 << 20))
        pump(0.3)
        self.assertEqual(self.selection.writing, {})
        self.assertFalse(is_open(writer))

    def test_close_lets_go_of_everything(self):
        offer = self.copy()
        mine = self.selection.reading[0]
        reader, writer = self.paste(b"x" * (1 << 20))
        self.selection.close()
        self.assertFalse(is_open(mine))
        self.assertFalse(is_open(writer))
        self.assertIsNone(self.selection.reading)
        self.assertEqual(self.selection.writing, {})
        pump(0.3)  # no timer or watch is left to run on a closed pipe
        self.selection.close()  # and closing twice is harmless
        with self.assertRaises(InputError):
            self.selection.set(b"too late")

    def test_our_text_replaced_by_another_copy_is_told(self):
        source = FakeSource()
        self.selection.sources.add(source)
        self.selection.current = source
        self.selection._on_cancelled(source)
        self.assertTrue(source.destroyed)
        self.assertEqual(self.replaced, [True])
        self.assertEqual(self.selection.sources, set())

    def test_our_text_replaced_by_our_next_text_is_not_told(self):
        older, newer = FakeSource(), FakeSource()
        self.selection.sources.update((older, newer))
        self.selection.current = newer
        self.selection._on_cancelled(older)
        self.assertTrue(older.destroyed)
        self.assertEqual(self.replaced, [])
        self.assertIs(self.selection.current, newer)


if __name__ == "__main__":
    unittest.main()
