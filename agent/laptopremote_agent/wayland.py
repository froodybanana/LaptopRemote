"""What the agent does in the Hyprland session through Wayland protocols: a virtual pointer and keyboard,
and the clipboard.

The protocol classes in `wl` are not in the repository: deploy.sh has pywayland's scanner write them on
the laptop from `agent/protocols/*.xml`.
"""
import errno
import os
import time
import traceback

from gi.repository import GLib

WHEEL = 0  # wl_pointer.axis_source
KEYMAP_XKB_V1 = 1
# what programs call plain text, the best first
TEXT_TYPES = ("text/plain;charset=utf-8", "UTF8_STRING", "text/plain", "TEXT", "STRING")


class InputError(Exception):
    pass


def _now():
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


class _Client:
    """A connection to the compositor of its own, read on the GLib loop."""

    display = watch = None

    def _connect(self):
        try:
            from pywayland import ffi
            from pywayland.client import Display
        except ImportError as error:
            raise InputError(f"pywayland is missing ({error})") from None
        self.ffi = ffi
        display = Display(os.environ.get("WAYLAND_DISPLAY") or _socket_name())
        try:
            display.connect()
        except Exception as error:
            raise InputError(f"no Wayland connection: {error}") from None
        self.display = display

    def _watch_events(self):
        # the compositor's events may be few, but unread they would fill the socket and end the connection
        self.watch = GLib.io_add_watch(self.display.get_fd(), GLib.PRIORITY_DEFAULT,
                                       GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_events)

    def _check(self):
        if self.display is None:
            raise InputError("the Wayland connection is gone")

    def _flush(self):
        # a full socket (EAGAIN) keeps what is queued for the next flush; anything else is the end
        if self.display.flush() < 0 and self.ffi.errno != errno.EAGAIN:
            self._lost()
            raise InputError("the Wayland connection is gone")

    def _lost(self):
        if self.watch is not None:
            GLib.source_remove(self.watch)
            self.watch = None
        display, self.display = self.display, None
        if display is not None:
            try:
                display.disconnect()
            except Exception:
                pass

    def _on_events(self, fd, condition):
        if condition & GLib.IO_IN:
            try:
                self.display.read()
                self.display.dispatch(block=False)
                self.display.flush()  # what the handlers of those events asked for
                return True
            except Exception as error:
                print(f"Wayland connection lost: {error}", flush=True)
        self.watch = None  # returning False removes it
        self._lost()
        return False


class WaylandDevice(_Client):
    """The pointer is bound to one output: its positions are fractions of that output, whatever else is connected."""

    def __init__(self, output_name, keymap_text):
        try:
            from .wl.virtual_keyboard_unstable_v1 import ZwpVirtualKeyboardManagerV1
            from .wl.wayland import WlOutput, WlSeat
            from .wl.wlr_virtual_pointer_unstable_v1 import ZwlrVirtualPointerManagerV1
        except ImportError as error:
            raise InputError(f"pywayland or the generated protocol classes are missing ({error}); "
                             "run agent/deploy.sh") from None
        self._connect()
        try:
            found, outputs = {}, {}
            registry = self.display.get_registry()

            def on_global(registry, name, interface, version):
                if interface == "wl_output" and version >= 4:  # version 4 is the first that tells its name
                    output = registry.bind(name, WlOutput, 4)
                    output.dispatcher["name"] = lambda output, text: outputs.__setitem__(text, output)
                else:
                    found[interface] = name

            registry.dispatcher["global"] = on_global
            self.display.roundtrip()  # the globals
            self.display.roundtrip()  # the names of the outputs bound above
            for interface in ("wl_seat", "zwlr_virtual_pointer_manager_v1", "zwp_virtual_keyboard_manager_v1"):
                if interface not in found:
                    raise InputError(f"the compositor does not offer {interface}")
            if output_name not in outputs:
                raise InputError(f"the compositor shows no output named {output_name}")
            seat = registry.bind(found["wl_seat"], WlSeat, 1)
            pointers = registry.bind(found["zwlr_virtual_pointer_manager_v1"], ZwlrVirtualPointerManagerV1, 2)
            keyboards = registry.bind(found["zwp_virtual_keyboard_manager_v1"], ZwpVirtualKeyboardManagerV1, 1)
            self.pointer = pointers.create_virtual_pointer_with_output(seat, outputs[output_name])
            self.keyboard = keyboards.create_virtual_keyboard(seat)
            fd = os.memfd_create("laptopremote-keymap")
            try:
                os.write(fd, keymap_text)
                self.keyboard.keymap(KEYMAP_XKB_V1, fd, len(keymap_text))
                self.display.roundtrip()  # a refusal of any of the above shows here
            finally:
                os.close(fd)
            self._watch_events()
        except Exception as error:
            self.display.disconnect()
            self.display = None
            if isinstance(error, InputError):
                raise
            raise InputError(f"virtual input devices: {type(error).__name__}: {error}") from None

    def motion(self, x, y, width, height):
        self._check()
        self.pointer.motion_absolute(_now(), x, y, width, height)
        self.pointer.frame()
        self._flush()

    def button(self, code, down):
        self._check()
        self.pointer.button(_now(), code, 1 if down else 0)
        self.pointer.frame()
        self._flush()

    def wheel(self, horizontal, value, steps):
        """value is the scroll distance (15 a notch), steps the whole notches it completes."""
        self._check()
        axis = 1 if horizontal else 0
        self.pointer.axis_source(WHEEL)
        if steps:
            self.pointer.axis_discrete(_now(), axis, value, steps)
        else:
            self.pointer.axis(_now(), axis, value)
        self.pointer.frame()
        self._flush()

    def key(self, code, down, mods):
        self._check()
        self.keyboard.key(_now(), code, 1 if down else 0)
        # Hyprland does not work the modifiers out from the keys of a virtual keyboard
        self.keyboard.modifiers(*mods)
        self._flush()

    def modifiers(self, mods):
        self._check()
        self.keyboard.modifiers(*mods)
        self._flush()

    def close(self):
        if self.watch is not None:
            GLib.source_remove(self.watch)
            self.watch = None
        display, self.display = self.display, None
        if display is None:
            return
        try:
            self.keyboard.destroy()
            self.pointer.destroy()
            display.flush()
        finally:
            display.disconnect()


class WaylandSelection(_Client):
    """The session's clipboard through ext-data-control: tells when its text changes, and sets it.

    on_text(bytes) is called with the text of every selection made after this was opened, our own included;
    what the clipboard held before is not read. Text longer than `limit` bytes is not reported.
    """

    def __init__(self, on_text, limit, timeout_ms=5000, on_replaced=None):
        try:
            from .wl.ext_data_control_v1 import ExtDataControlManagerV1
            from .wl.wayland import WlSeat
        except ImportError as error:
            raise InputError(f"pywayland or the generated protocol classes are missing ({error}); "
                             "run agent/deploy.sh") from None
        self.on_text, self.limit, self.timeout_ms, self.on_replaced = on_text, limit, timeout_ms, on_replaced
        self.current = None  # the source of the text set last, while it is the clipboard
        self.ready = False
        self.offers = {}  # offer -> the types it has, until the compositor says what the offer is
        self.reading = None  # (pipe, watch, timer, bytearray) of the selection being read
        self.writing = {}  # pipe -> (watch, timer) of each reader of our text that is not served yet
        self.sources = set()  # pywayland drops the events of an object nothing refers to any more
        self._connect()
        try:
            found = {}
            # kept for as long as the connection: pywayland makes the object of a new offer with the display
            # of whatever registry is alive
            self.registry = registry = self.display.get_registry()
            registry.dispatcher["global"] = lambda registry, name, interface, version: found.__setitem__(interface, name)
            self.display.roundtrip()
            for interface in ("wl_seat", "ext_data_control_manager_v1"):
                if interface not in found:
                    raise InputError(f"the compositor does not offer {interface}")
            self.seat = registry.bind(found["wl_seat"], WlSeat, 1)
            self.manager = registry.bind(found["ext_data_control_manager_v1"], ExtDataControlManagerV1, 1)
            self.device = self.manager.get_data_device(self.seat)
            self.device.dispatcher["data_offer"] = self._on_offer
            self.device.dispatcher["selection"] = self._on_selection
            self.device.dispatcher["primary_selection"] = self._on_primary
            # not from inside the dispatch: disconnecting there frees what libwayland is still working on
            self.device.dispatcher["finished"] = lambda device: GLib.idle_add(self._on_finished)
            # a new device is told what the clipboard holds now; that is not a change and is left unread
            self.display.roundtrip()
            self.ready = True
            self._watch_events()
        except Exception as error:
            self.display.disconnect()
            self.display = None
            if isinstance(error, InputError):
                raise
            raise InputError(f"clipboard: {type(error).__name__}: {error}") from None

    def set(self, data):
        """Makes these bytes the clipboard's text, served to whoever pastes."""
        self._check()
        self._stop_reading()  # what was being read is about to be replaced
        source = self.manager.create_data_source()
        for kind in TEXT_TYPES:
            source.offer(kind)
        source.dispatcher["send"] = lambda source, kind, fd: self._serve(fd, data)
        source.dispatcher["cancelled"] = self._on_cancelled
        self.sources.add(source)
        self.current = source
        self.device.set_selection(source)
        self._flush()

    def close(self):
        self._stop_reading()
        for pipe, (watch, timer) in self.writing.items():
            GLib.source_remove(watch)
            GLib.source_remove(timer)
            os.close(pipe)
        self.writing = {}
        self._lost()  # our selection goes with the connection

    def _lost(self):
        # an offer that is still waiting would otherwise be destroyed after the connection it belongs to
        offers, self.offers = self.offers, {}
        for offer in offers:
            try:
                offer.destroy()
            except Exception:
                pass
        self.sources = set()
        super()._lost()

    def _on_cancelled(self, source):
        """Another selection took the place of this one."""
        self.sources.discard(source)
        source.destroy()
        if source is self.current:  # not when it was our own next text that replaced it
            self.current = None
            if self.on_replaced is not None:
                self.on_replaced()

    def _on_finished(self):
        """The compositor has no use for our device any more."""
        self._lost()
        return False

    def _on_offer(self, device, offer):
        # pywayland gives an object the compositor makes the display of whichever registry it finds first,
        # which may belong to a connection closed long ago; with that display the offer is never destroyed,
        # its id never becomes free, and the compositor's next use of the id ends our connection
        offer._display = self.display
        self.offers[offer] = kinds = []
        offer.dispatcher["offer"] = lambda offer, kind: kinds.append(kind)

    def _on_primary(self, device, offer):
        if offer is not None:
            self.offers.pop(offer, None)
            offer.destroy()

    def _on_selection(self, device, offer):
        # exceptions do not leave a Wayland event handler, so they are dealt with here
        try:
            self._stop_reading()  # what was being read is no longer the clipboard
            if offer is None:
                return
            kinds = self.offers.pop(offer, [])
            kind = next((kind for kind in TEXT_TYPES if kind in kinds), None)
            if self.ready and kind is not None:
                self._read(offer, kind)
            offer.destroy()
        except Exception:
            traceback.print_exc()

    def _read(self, offer, kind):
        pipe, their_end = os.pipe()
        try:
            os.set_blocking(pipe, False)  # only ours: the program that writes may not cope with a full pipe
            offer.receive(kind, their_end)
            self.display.flush()
        finally:
            os.close(their_end)
        watch = GLib.io_add_watch(pipe, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                                  self._on_readable)
        # a program that never finishes writing must not keep the pipe open for ever
        timer = GLib.timeout_add(self.timeout_ms, self._on_read_timeout)
        self.reading = (pipe, watch, timer, bytearray())

    def _stop_reading(self, ending=None):
        """`ending` is the watch or timer that is running this and ends by returning False."""
        reading, self.reading = self.reading, None
        if reading is not None:
            pipe, watch, timer, _ = reading
            for source in (watch, timer):
                if source != ending:
                    GLib.source_remove(source)
            os.close(pipe)

    def _on_read_timeout(self):
        self._stop_reading(ending=self.reading[2])
        return False

    def _on_readable(self, pipe, condition):
        watch, data = self.reading[1], self.reading[3]
        try:
            chunk = os.read(pipe, 65536)
        except BlockingIOError:
            return True
        except OSError:
            self._stop_reading(ending=watch)
            return False
        if chunk:
            data += chunk
            if len(data) <= self.limit:
                return True
            self._stop_reading(ending=watch)  # too long to send: the rest is not read
            return False
        self._stop_reading(ending=watch)
        try:
            self.on_text(bytes(data))
        except Exception:  # an exception leaving a GLib callback is only printed, without saying where it was
            traceback.print_exc()
        return False

    def _serve(self, pipe, data):
        try:
            os.set_blocking(pipe, False)  # a reader that stops reading must not stop the agent
            left = [memoryview(data)]
            if self._write(pipe, left):
                watch = GLib.io_add_watch(pipe, GLib.PRIORITY_DEFAULT, GLib.IO_OUT | GLib.IO_HUP | GLib.IO_ERR,
                                          self._on_writable, left)
                timer = GLib.timeout_add(self.timeout_ms, self._on_write_timeout, pipe)
                self.writing[pipe] = (watch, timer)
        except Exception:
            traceback.print_exc()

    def _write(self, pipe, left):
        """Writes what the pipe takes; True when there is more to write later. Closes the pipe when done."""
        try:
            while left[0]:
                left[0] = left[0][os.write(pipe, left[0]):]
        except BlockingIOError:
            return True
        except OSError:  # the reader hung up
            pass
        os.close(pipe)
        return False

    def _on_writable(self, pipe, condition, left):
        if self._write(pipe, left):
            return True
        GLib.source_remove(self.writing.pop(pipe)[1])
        return False

    def _on_write_timeout(self, pipe):
        GLib.source_remove(self.writing.pop(pipe)[0])
        os.close(pipe)
        return False


def _socket_name():
    """The compositor's socket when the environment does not name it, as in a bare ssh session."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    names = sorted(name for name in os.listdir(runtime) if name.startswith("wayland-") and not name.endswith(".lock"))
    if not names:
        raise InputError(f"no Wayland socket in {runtime}")
    return names[0]
