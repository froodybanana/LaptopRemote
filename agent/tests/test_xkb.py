import unittest

from laptopremote_agent import xkb

SHIFT, LOCK, NUM = 1, 2, 16  # modifier bits of every xkeyboard-config layout
KEY_LEFTSHIFT, KEY_CAPSLOCK, KEY_NUMLOCK = 42, 58, 69


class KeymapTests(unittest.TestCase):
    def test_text_is_a_keymap_ending_in_nul(self):
        text = xkb.Keymap("us").text
        self.assertTrue(text.startswith(b"xkb_keymap"))
        self.assertTrue(text.endswith(b"}\n\0") or text.endswith(b"};\n\0"), text[-20:])

    def test_layouts_differ(self):
        self.assertNotEqual(xkb.Keymap("us").text, xkb.Keymap("dk").text)

    def test_variant_and_options_are_used(self):
        plain = xkb.Keymap("us").text
        self.assertNotEqual(xkb.Keymap("us", variant="dvorak").text, plain)
        self.assertNotEqual(xkb.Keymap("us", options="compose:caps").text, plain)

    def test_unknown_layout_is_an_error(self):
        with self.assertRaises(xkb.XkbError) as caught:
            xkb.Keymap("nosuchlayout")
        self.assertIn("nosuchlayout", str(caught.exception))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = xkb.Keymap("us").state()

    def test_num_lock_starts_on(self):
        # a PC keypad types digits; without this it would move the cursor until Num Lock is pressed
        self.assertEqual(self.state.mods(), (0, 0, NUM, 0))

    def test_shift_is_depressed_while_held(self):
        self.assertEqual(self.state.update(KEY_LEFTSHIFT, True), (SHIFT, 0, NUM, 0))
        self.assertEqual(self.state.update(KEY_LEFTSHIFT, False), (0, 0, NUM, 0))

    def test_caps_lock_toggles(self):
        self.state.update(KEY_CAPSLOCK, True)
        self.assertEqual(self.state.update(KEY_CAPSLOCK, False), (0, 0, NUM | LOCK, 0))
        self.state.update(KEY_CAPSLOCK, True)
        self.assertEqual(self.state.update(KEY_CAPSLOCK, False), (0, 0, NUM, 0))

    def test_num_lock_key_turns_it_off(self):
        self.state.update(KEY_NUMLOCK, True)
        self.assertEqual(self.state.update(KEY_NUMLOCK, False), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
