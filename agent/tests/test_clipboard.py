import unittest

from laptopremote_agent.clipboard import MAX_BYTES, Clipboard


class FakeDevice:
    def __init__(self):
        self.calls = []

    def set(self, data):
        self.calls.append(("set", data))

    def close(self):
        self.calls.append(("close",))


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.sent, self.device = [], FakeDevice()
        self.clipboard = Clipboard(self.sent.append, self.device)

    def test_laptop_text_is_sent(self):
        self.clipboard.changed("blåbær\n".encode())
        self.assertEqual(self.sent, ["blåbær\n"])

    def test_text_from_the_viewer_is_set(self):
        self.clipboard.set("from the PC")
        self.assertEqual(self.device.calls, [("set", b"from the PC")])

    def test_text_from_the_viewer_is_not_sent_back(self):
        self.clipboard.set("from the PC")
        # the compositor tells of our own selection, and again whenever a clipboard manager takes it over
        self.clipboard.changed(b"from the PC")
        self.clipboard.changed(b"from the PC")
        self.assertEqual(self.sent, [])

    def test_same_text_goes_again_after_another(self):
        self.clipboard.set("one")
        self.clipboard.changed(b"two")
        self.clipboard.changed(b"one")  # copied on the laptop this time, and the PC has "two"
        self.assertEqual(self.sent, ["two", "one"])

    def test_same_text_goes_after_our_selection_was_replaced(self):
        # the laptop copied something that is not text, the PC too; then the laptop copies the old text itself
        self.clipboard.set("one")
        self.clipboard.changed(b"one")
        self.clipboard.replaced()
        self.clipboard.changed(b"one")
        self.assertEqual(self.sent, ["one"])

    def test_laptop_text_copied_twice_is_sent_twice(self):
        # the PC may have copied something else in between without the viewer having the focus
        self.clipboard.changed(b"one")
        self.clipboard.changed(b"one")
        self.assertEqual(self.sent, ["one", "one"])

    def test_too_long_is_ignored(self):
        self.clipboard.changed(b"x" * MAX_BYTES)
        self.clipboard.changed(b"x" * (MAX_BYTES + 1))
        self.assertEqual([len(text) for text in self.sent], [MAX_BYTES])
        self.clipboard.set("y" * MAX_BYTES)
        self.clipboard.set("y" * (MAX_BYTES + 1))
        self.clipboard.set("æ" * (MAX_BYTES // 2 + 1))  # counted in bytes, not characters
        self.assertEqual([len(call[1]) for call in self.device.calls], [MAX_BYTES])

    def test_a_refused_text_is_not_remembered(self):
        self.clipboard.set("one")
        self.clipboard.set("y" * (MAX_BYTES + 1))
        self.clipboard.changed(b"one")
        self.assertEqual(self.sent, [])

    def test_empty_is_ignored(self):
        self.clipboard.changed(b"")
        self.clipboard.set("")
        self.assertEqual((self.sent, self.device.calls), ([], []))

    def test_invalid_utf8_is_replaced(self):
        self.clipboard.changed(b"a\xffb")
        self.assertEqual(self.sent, ["a�b"])

    def test_invalid_utf8_that_grows_past_the_limit_is_ignored(self):
        self.clipboard.changed(b"\xff" * MAX_BYTES)  # three bytes each once replaced
        self.assertEqual(self.sent, [])

    def test_lone_surrogate_from_the_viewer(self):
        self.clipboard.set("a" + chr(0xD800) + "b")
        self.assertEqual(self.device.calls, [("set", b"a?b")])

    def test_close_closes_the_device(self):
        self.clipboard.close()
        self.assertEqual(self.device.calls, [("close",)])


if __name__ == "__main__":
    unittest.main()
