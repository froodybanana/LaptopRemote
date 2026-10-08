"""What the viewer's mouse and keyboard messages become on the laptop, apart from the Wayland calls themselves."""
import math
import traceback

BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112, "back": 0x113, "forward": 0x114}
MAX_KEY = 767  # the highest Linux key code
NOTCH = 15.0  # the scroll distance compositors give one wheel notch
MAX_NOTCHES = 100


def open(output_name, keymap):
    """Virtual pointer and keyboard on the output of this name, typing with this xkb.Keymap."""
    from .wayland import WaylandDevice  # needs pywayland and the compositor; nothing else here does
    device = WaylandDevice(output_name, keymap.text)
    try:
        return Injector(device, keymap.state())
    except Exception:
        device.close()
        raise


class Injector:
    """Remembers what is held so it can all be let go, and keeps nonsense away from the device."""

    def __init__(self, device, state):
        self.device, self.state = device, state
        self.keys, self.buttons = [], []  # held, oldest first
        self.remainder = {False: 0.0, True: 0.0}  # part of a notch not yet counted as a step, per axis
        device.modifiers(state.mods())

    def move(self, x, y, width, height):
        if width > 0 and height > 0:
            self.device.motion(min(max(x, 0), width - 1), min(max(y, 0), height - 1), width, height)

    def button(self, name, down):
        code = BUTTONS.get(name)
        if code is None or (code in self.buttons) == down:
            return
        self.buttons.append(code) if down else self.buttons.remove(code)
        self.device.button(code, down)

    def wheel(self, dx, dy):
        for horizontal, notches in ((True, dx), (False, dy)):
            if not math.isfinite(notches) or notches == 0:
                continue
            notches = min(max(notches, -MAX_NOTCHES), MAX_NOTCHES)
            total = self.remainder[horizontal] + notches
            steps = math.trunc(total)
            self.remainder[horizontal] = total - steps
            self.device.wheel(horizontal, notches * NOTCH, steps)

    def key(self, code, down):
        if not 1 <= code <= MAX_KEY or (code in self.keys) == down:
            return
        self.keys.append(code) if down else self.keys.remove(code)
        self.device.key(code, down, self.state.update(code, down))

    def release(self):
        """Lets go of every key and button still held, newest first."""
        for code in self.keys[::-1]:
            self.key(code, False)
        for code in self.buttons[::-1]:
            self.buttons.remove(code)
            self.device.button(code, False)

    def close(self):
        try:
            self.release()
        except Exception:  # the devices go away with the connection, and what they held with them
            traceback.print_exc()
        self.device.close()
