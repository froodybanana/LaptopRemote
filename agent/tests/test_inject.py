import unittest

from laptopremote_agent import xkb
from laptopremote_agent.inject import Injector

NUM = (0, 0, 16, 0)
SHIFT = (1, 0, 16, 0)
KEY_A, KEY_LEFTSHIFT = 30, 42
KEYMAP = xkb.Keymap("us")


class FakeDevice:
    def __init__(self):
        self.calls = []

    def motion(self, x, y, width, height):
        self.calls.append(("motion", x, y, width, height))

    def button(self, code, down):
        self.calls.append(("button", code, down))

    def wheel(self, horizontal, value, steps):
        self.calls.append(("wheel", horizontal, value, steps))

    def key(self, code, down, mods):
        self.calls.append(("key", code, down, mods))

    def modifiers(self, mods):
        self.calls.append(("modifiers", mods))

    def close(self):
        self.calls.append(("close",))


class InjectorTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeDevice()
        self.injector = Injector(self.device, KEYMAP.state())
        self.calls = self.device.calls
        self.calls.clear()

    def test_lock_state_is_sent_at_the_start(self):
        device = FakeDevice()
        Injector(device, KEYMAP.state())
        self.assertEqual(device.calls, [("modifiers", NUM)])

    def test_move_is_clamped(self):
        for x, y in ((10, 20), (-5, -1), (5000, 900), (1599, 899)):
            self.injector.move(x, y, 1600, 900)
        self.assertEqual(self.calls, [("motion", 10, 20, 1600, 900), ("motion", 0, 0, 1600, 900),
                                      ("motion", 1599, 899, 1600, 900), ("motion", 1599, 899, 1600, 900)])

    def test_buttons_map_to_linux_codes(self):
        for name in ("left", "right", "middle", "back", "forward"):
            self.injector.button(name, True)
        self.assertEqual([call[1] for call in self.calls], [0x110, 0x111, 0x112, 0x113, 0x114])

    def test_unknown_button_is_ignored(self):
        self.injector.button("fourth", True)
        self.injector.button("", False)
        self.assertEqual(self.calls, [])

    def test_repeated_down_is_one_press(self):
        for _ in range(3):
            self.injector.key(KEY_A, True)
            self.injector.button("left", True)
        self.assertEqual(self.calls, [("key", KEY_A, True, NUM), ("button", 0x110, True)])

    def test_up_without_down_is_ignored(self):
        self.injector.key(KEY_A, False)
        self.injector.button("left", False)
        self.assertEqual(self.calls, [])

    def test_key_carries_modifiers(self):
        self.injector.key(KEY_LEFTSHIFT, True)
        self.injector.key(KEY_A, True)
        self.injector.key(KEY_A, False)
        self.injector.key(KEY_LEFTSHIFT, False)
        self.assertEqual(self.calls, [("key", KEY_LEFTSHIFT, True, SHIFT), ("key", KEY_A, True, SHIFT),
                                      ("key", KEY_A, False, SHIFT), ("key", KEY_LEFTSHIFT, False, NUM)])

    def test_wheel_counts_whole_notches(self):
        self.injector.wheel(0, 1)        # one notch down
        self.injector.wheel(0, -0.5)     # half a notch up: no whole step yet
        self.injector.wheel(0, -0.5)     # the second half makes one
        self.injector.wheel(2, 0)        # two notches right
        self.assertEqual(self.calls, [("wheel", False, 15.0, 1), ("wheel", False, -7.5, 0),
                                      ("wheel", False, -7.5, -1), ("wheel", True, 30.0, 2)])

    def test_wheel_sends_both_axes(self):
        self.injector.wheel(1, -1)
        self.assertEqual(self.calls, [("wheel", True, 15.0, 1), ("wheel", False, -15.0, -1)])

    def test_nonsense_is_ignored(self):
        for code in (0, -1, 768, 100000):
            self.injector.key(code, True)
        self.injector.wheel(float("nan"), float("inf"))
        self.injector.wheel(0, 0)
        self.injector.move(5, 5, 0, 0)
        self.assertEqual(self.calls, [])
        self.injector.wheel(0, 1e9)
        self.assertEqual(self.calls, [("wheel", False, 1500.0, 100)])

    def test_release_lets_go_of_everything(self):
        self.injector.key(KEY_LEFTSHIFT, True)
        self.injector.key(KEY_A, True)
        self.injector.button("left", True)
        self.injector.button("right", True)
        self.calls.clear()
        self.injector.release()
        self.assertEqual(self.calls, [("key", KEY_A, False, SHIFT), ("key", KEY_LEFTSHIFT, False, NUM),
                                      ("button", 0x111, False), ("button", 0x110, False)])
        self.calls.clear()
        self.injector.release()  # nothing is held any more
        self.injector.key(KEY_A, False)
        self.assertEqual(self.calls, [])

    def test_close_releases_then_closes(self):
        self.injector.key(KEY_A, True)
        self.calls.clear()
        self.injector.close()
        self.assertEqual(self.calls, [("key", KEY_A, False, NUM), ("close",)])

    def test_close_closes_even_when_release_fails(self):
        self.injector.key(KEY_A, True)
        self.device.key = lambda code, down, mods: (_ for _ in ()).throw(OSError("compositor gone"))
        self.calls.clear()
        self.injector.close()
        self.assertEqual(self.calls, [("close",)])


if __name__ == "__main__":
    unittest.main()
