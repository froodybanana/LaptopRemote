"""One viewing session: headless output in place of the laptop panel, capture and sender pipeline."""
import time
import traceback

from gi.repository import GLib

from . import hypr as real_hypr
from .capture import PortalCapture
from .geometry import normalize
from .pipeline import SenderPipeline


class Session:
    OUTPUT = "LAPTOPREMOTE"

    def __init__(self, config, hypr=real_hypr, capture_factory=PortalCapture,
                 pipeline_factory=SenderPipeline, settle_ms=300, max_restarts=3, restart_ms=500, healthy_ms=10000,
                 wake_ms=30000, stall_ms=2000, stall_check_ms=500, input_factory=None, clipboard_factory=None):
        self.config, self.hypr = config, hypr
        self.capture_factory, self.pipeline_factory, self.settle_ms = capture_factory, pipeline_factory, settle_ms
        self.max_restarts, self.restart_ms, self.healthy_ms = max_restarts, restart_ms, healthy_ms
        # a stream that delivers no frame for stall_ms is dead: with keepalive-time set, a healthy one repeats
        # the last frame several times a second even on a still screen
        self.stall_ms, self.stall_check_ms = stall_ms, stall_check_ms
        self.wake_ms, self.wake_timer = wake_ms, None
        self.active = self.paused = False
        self.restarts = 0
        self.generation = 0
        self.capture = self.pipeline = None
        # input_factory(output name) gives the injector for mouse and keyboard; without one the session only shows
        self.input_factory, self.input = input_factory, None
        # clipboard_factory(send) follows the laptop's clipboard and calls send(text) when its text changes
        self.clipboard_factory, self.clipboard, self.on_clipboard = clipboard_factory, None, None

    def start(self, width, height, scale, host, port, on_error, on_clipboard=None):
        self.active, self.target, self.on_error = True, (host, port), on_error
        self.on_clipboard = on_clipboard
        self.paused, self.restarts = False, 0
        if self.wake_timer is None:
            # no input reaches the laptop, so its idle timer would put the output to sleep under the viewer
            self.wake_timer = GLib.timeout_add(self.wake_ms, self._on_wake_timer)
        self._apply(width, height, scale)

    def resize(self, width, height, scale):
        if self.active:
            self.restarts = 0
            self._apply(width, height, scale)

    def pause(self):
        """The viewer is minimized: stop capturing and encoding, keep the output and the panel as they are."""
        if self.active and not self.paused:
            self.paused = True
            self.release_input()
            self._teardown_stream()

    def resume(self):
        if self.active and self.paused:
            self.paused, self.restarts = False, 0
            self._wake()
            self._schedule_capture()

    def keyframe(self):
        if self.pipeline:
            self.pipeline.force_keyframe()

    def pointer_move(self, x, y):
        """x, y are pixels of the size the viewer last sent, which is the output's mode."""
        self._inject(lambda device: device.move(x, y, self.size[0], self.size[1]))

    def pointer_button(self, name, down):
        self._inject(lambda device: device.button(name, down))

    def pointer_wheel(self, dx, dy):
        self._inject(lambda device: device.wheel(dx, dy))

    def key(self, code, down):
        self._inject(lambda device: device.key(code, down))

    def release_input(self):
        """The viewer lost focus: nothing may stay held down on the laptop."""
        self._inject(lambda device: device.release())

    def _inject(self, action):
        if not self.active or self.input is None:
            return
        try:
            action(self.input)
        except Exception:  # input must never end a session: it goes on showing, without mouse and keyboard
            traceback.print_exc()
            print("input failed; the session goes on without it until the next resize", flush=True)
            self._close_input()

    def _open_input(self):
        self._close_input()
        try:
            self.input = self.input_factory(self.OUTPUT)
        except Exception as error:
            traceback.print_exc()
            print(f"no mouse and keyboard in this session: {type(error).__name__}: {error}", flush=True)

    def _close_input(self):
        device, self.input = self.input, None
        if device is not None:
            try:
                device.close()  # lets go of every key and button first
            except Exception:
                traceback.print_exc()

    def set_clipboard(self, text):
        """The viewer's clipboard text, to be pasted on the laptop."""
        if not self.active or self.clipboard is None:
            return
        try:
            self.clipboard.set(text)
        except Exception:  # like input: the session goes on showing, without the clipboard
            traceback.print_exc()
            print("clipboard failed; the session goes on without it until the next resize", flush=True)
            self._close_clipboard()

    def _on_clipboard_text(self, text):
        if not self.active or self.on_clipboard is None:
            return
        try:
            self.on_clipboard(text)
        except Exception:  # it is called from the clipboard's own callbacks on the main loop
            traceback.print_exc()

    def _open_clipboard(self):
        try:
            self.clipboard = self.clipboard_factory(self._on_clipboard_text)
        except Exception as error:
            traceback.print_exc()
            print(f"no clipboard in this session: {type(error).__name__}: {error}", flush=True)

    def _close_clipboard(self):
        clipboard, self.clipboard = self.clipboard, None
        if clipboard is not None:
            try:
                clipboard.close()
            except Exception:
                traceback.print_exc()

    def reapply(self):
        """Hyprland reloaded its config, which turns the panel back on and resets the output's mode."""
        if not self.active:
            return
        try:
            self._apply(*self.size)
        except Exception as error:
            traceback.print_exc()
            self.on_error(f"config reload: {type(error).__name__}: {error}")

    def stop(self):
        was_active, self.active = self.active, False
        if self.wake_timer is not None:
            GLib.source_remove(self.wake_timer)
            self.wake_timer = None
        self._close_input()
        self._close_clipboard()
        try:
            self._teardown_stream()
        except Exception:
            traceback.print_exc()
        if was_active:
            self._restore()

    def recover(self):
        """Undo what an agent that died mid-session left behind. Called before listening."""
        try:
            if not self.active and (self.hypr.output_exists(self.OUTPUT)
                                    or self.hypr.output_disabled(self.config.panel)):
                self._restore()
        except Exception:
            traceback.print_exc()

    def _restore(self):
        # the panel first: the laptop must never be left without a screen, whatever else fails
        try:
            self.hypr.enable_output(self.config.panel)
        except Exception:  # the compositor may be gone; stopping must still succeed
            traceback.print_exc()
        try:
            if self.hypr.output_exists(self.OUTPUT):
                # the re-enabled panel shows a new empty workspace; go back to the one the viewer was showing
                showing = self.hypr.active_workspace(self.OUTPUT)
                self.hypr.remove_output(self.OUTPUT)
                if showing is not None:
                    self.hypr.focus_workspace(showing)
        except Exception:
            traceback.print_exc()

    def _apply(self, width, height, scale):
        width, height = normalize(width, height)
        self.size = (width, height, scale)
        self._teardown_stream()
        existed = self.hypr.output_exists(self.OUTPUT)
        if not existed:
            self.hypr.create_output(self.OUTPUT)
        self.hypr.set_mode(self.OUTPUT, width, height, scale)
        if self.input_factory is not None and (self.input is None or not existed):
            self._open_input()  # the pointer is bound to the output, so a new output needs a new one
        if self.clipboard_factory is not None and self.clipboard is None:
            self._open_clipboard()
        panel = self.config.panel
        if not self.hypr.output_disabled(panel):
            # the panel's workspaces move to the headless output, which would go on showing its own empty one.
            # After a config reload it is the other way round: the panel came back with an empty workspace.
            showing = self.hypr.active_workspace(self.OUTPUT if existed else panel)
            self.hypr.disable_output(panel)
            if showing is not None:
                self.hypr.focus_workspace(showing)
        self._wake()
        if not self.paused:
            self._schedule_capture()

    def _wake(self):
        try:
            self.hypr.wake()
        except Exception:  # a display that stays asleep shows black; that is no reason to end the session
            traceback.print_exc()

    def _on_wake_timer(self):
        if self.active and not self.paused:
            self._wake()
        return True

    def _schedule_capture(self):
        # give Hyprland a moment to apply the mode before the portal captures the output
        GLib.timeout_add(self.settle_ms, self._begin_capture, self.generation)

    def _begin_capture(self, generation):
        if generation == self.generation and self.active:
            try:
                self.capture = self.capture_factory(
                    self.OUTPUT, lambda fd, node: self._on_stream(generation, fd, node),
                    lambda text: self._fail(generation, text))
                self.capture.start()
            except Exception as error:
                self._fail(generation, f"screen capture: {error}")
        return False

    def _on_stream(self, generation, fd, node):
        if generation != self.generation or not self.active:
            return
        host, port = self.target
        try:
            self.pipeline = self.pipeline_factory(fd, node, host, port, self.config.video_send_port,
                                                  self.config.encoder_fragment(),
                                                  lambda text: self._fail(generation, text))
            self.pipeline.start()
        except Exception as error:  # raised inside a D-Bus handler it would only be printed
            self._fail(generation, f"video pipeline: {error}")
            return
        GLib.timeout_add(self.healthy_ms, self._on_healthy, generation)
        self.stall_frames, self.stall_since = self.pipeline.frames, time.monotonic()
        GLib.timeout_add(self.stall_check_ms, self._on_stall_check, generation)

    def _on_stall_check(self, generation):
        """A brief hold-up of the capture makes the portal run out of buffers, and its own retry never
        recovers; a new capture does, so the stream is restarted like a failed one."""
        if generation != self.generation or not self.active or self.paused or self.pipeline is None:
            return False
        frames, now = self.pipeline.frames, time.monotonic()
        if frames != self.stall_frames:
            self.stall_frames, self.stall_since = frames, now
        elif now - self.stall_since >= self.stall_ms / 1000:
            self._fail(generation, f"video stalled: no frame for {self.stall_ms} ms")
            return False
        return True

    def _on_healthy(self, generation):
        if generation == self.generation:
            self.restarts = 0  # the stream has held: a later failure gets its full set of restarts
        return False

    def _teardown_stream(self):
        self.generation += 1
        if self.pipeline:
            self.pipeline.stop()
            self.pipeline = None
        if self.capture:
            self.capture.close()
            self.capture = None

    def _fail(self, generation, text):
        """A stream failed: restart it a few times, then give the error to the viewer."""
        if generation != self.generation or not self.active:
            return
        try:
            self._teardown_stream()
        except Exception:
            traceback.print_exc()
        if self.restarts >= self.max_restarts:
            self.on_error(text)
            return
        self.restarts += 1
        print(f"{text}; restart {self.restarts} of {self.max_restarts}", flush=True)
        GLib.timeout_add(self.restart_ms, self._restart, self.generation)

    def _restart(self, generation):
        if generation == self.generation and self.active and not self.paused:
            try:
                self._apply(*self.size)  # the whole setup, so an output or mode that was lost is put back
            except Exception as error:
                traceback.print_exc()
                self.on_error(f"restart: {type(error).__name__}: {error}")
        return False
