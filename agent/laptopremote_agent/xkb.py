"""Keymap and modifier state from libxkbcommon, through ctypes: the laptop has no Python binding for it.

Hyprland does not work out Shift, Caps Lock and the like from the keys a virtual keyboard sends; the
client has to say which modifiers are in effect, so the agent keeps the state itself.
"""
import ctypes

KEYMAP_FORMAT_TEXT_V1 = 1
KEY_UP, KEY_DOWN = 0, 1
MODS_DEPRESSED, MODS_LATCHED, MODS_LOCKED, LAYOUT_EFFECTIVE = 1, 2, 4, 128
EVDEV_OFFSET = 8  # an XKB keycode is the Linux key code plus 8


class XkbError(Exception):
    pass


class _Names(ctypes.Structure):
    _fields_ = [(name, ctypes.c_char_p) for name in ("rules", "model", "layout", "variant", "options")]


def _library():
    lib = ctypes.CDLL("libxkbcommon.so.0")
    pointer, uint32 = ctypes.c_void_p, ctypes.c_uint32
    for name, result, arguments in (
            ("xkb_context_new", pointer, [ctypes.c_int]),
            ("xkb_context_unref", None, [pointer]),
            ("xkb_keymap_new_from_names", pointer, [pointer, ctypes.POINTER(_Names), ctypes.c_int]),
            ("xkb_keymap_get_as_string", pointer, [pointer, ctypes.c_int]),
            ("xkb_keymap_mod_get_index", uint32, [pointer, ctypes.c_char_p]),
            ("xkb_keymap_unref", None, [pointer]),
            ("xkb_state_new", pointer, [pointer]),
            ("xkb_state_unref", None, [pointer]),
            ("xkb_state_update_key", ctypes.c_int, [pointer, uint32, ctypes.c_int]),
            ("xkb_state_update_mask", ctypes.c_int, [pointer] + [uint32] * 6),
            ("xkb_state_serialize_mods", uint32, [pointer, ctypes.c_int]),
            ("xkb_state_serialize_layout", uint32, [pointer, ctypes.c_int])):
        function = getattr(lib, name)
        function.restype, function.argtypes = result, arguments
    return lib


class Keymap:
    def __init__(self, layout, variant="", options=""):
        try:
            self.lib = _library()
        except OSError as error:
            raise XkbError(f"libxkbcommon: {error}") from None
        self.pointer = None
        context = self.lib.xkb_context_new(0)
        if not context:
            raise XkbError("libxkbcommon gave no context")
        try:
            names = _Names(None, None, layout.encode(), variant.encode() or None, options.encode() or None)
            self.pointer = self.lib.xkb_keymap_new_from_names(context, ctypes.byref(names), 0)
        finally:
            self.lib.xkb_context_unref(context)  # the keymap keeps its own reference
        if not self.pointer:
            raise XkbError(f"no keymap for keyboard layout {layout!r}, variant {variant!r}, options {options!r}")
        text = self.lib.xkb_keymap_get_as_string(self.pointer, KEYMAP_FORMAT_TEXT_V1)
        self.text = ctypes.string_at(text) + b"\0"
        ctypes.CDLL(None).free(ctypes.c_void_p(text))

    def state(self):
        return State(self)

    def __del__(self):
        if getattr(self, "pointer", None):
            self.lib.xkb_keymap_unref(self.pointer)


class State:
    """Which modifiers are held, latched and locked, as the keys go down and up."""

    def __init__(self, keymap):
        self.keymap, self.lib = keymap, keymap.lib  # the keymap must outlive the state
        self.pointer = self.lib.xkb_state_new(keymap.pointer)
        if not self.pointer:
            raise XkbError("libxkbcommon gave no state")
        # Num Lock on from the start: a PC keypad types digits
        index = self.lib.xkb_keymap_mod_get_index(keymap.pointer, b"Mod2")
        if index < 32:
            self.lib.xkb_state_update_mask(self.pointer, 0, 0, 1 << index, 0, 0, 0)

    def update(self, code, down):
        self.lib.xkb_state_update_key(self.pointer, code + EVDEV_OFFSET, KEY_DOWN if down else KEY_UP)
        return self.mods()

    def mods(self):
        """(depressed, latched, locked, group): the arguments of the virtual keyboard's modifiers request."""
        return (*(self.lib.xkb_state_serialize_mods(self.pointer, part)
                  for part in (MODS_DEPRESSED, MODS_LATCHED, MODS_LOCKED)),
                self.lib.xkb_state_serialize_layout(self.pointer, LAYOUT_EFFECTIVE))

    def __del__(self):
        if getattr(self, "pointer", None):
            self.lib.xkb_state_unref(self.pointer)
