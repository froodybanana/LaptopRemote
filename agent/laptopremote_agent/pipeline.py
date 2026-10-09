"""GStreamer sender: PipeWire frames -> VAAPI H.265 4:4:4 -> RTP over UDP."""
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo  # noqa: E402

Gst.init(None)


def launch_text(fd, node, host, port, bind_port, encoder):
    """The gst-launch text of the sender; `encoder` is Config.encoder_fragment()."""
    # keepalive-time: on a still screen PipeWire delivers nothing, and the encoder can only
    # answer a keyframe request when a frame arrives, so the last frame is repeated 4 times a second.
    # videoconvert in system memory: given vapostproc's surfaces the VA encoder smears the colour of
    # the top rows, or shears the picture, at most sizes; frames it copies in itself come out right
    return (f"pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time=250 "
            f"! video/x-raw ! videoconvert name=live n-threads=2 ! {encoder} "
            "! h265parse ! rtph265pay config-interval=-1 aggregate-mode=zero-latency mtu=1200 "
            f"! udpsink host={host} port={port} bind-port={bind_port} sync=false async=false")


class SenderPipeline:
    def __init__(self, fd, node, host, port, bind_port, encoder, on_error):
        self.on_error = on_error
        self.keyframes = self.frames = 0  # frames: buffers that left the capture, read by the session's stall check
        self.pipeline = Gst.parse_launch(launch_text(fd, node, host, port, bind_port, encoder))
        # pipewiresrc only reports itself live after caps are set, too late for the VA encoder,
        # which then holds frames back. Answer the encoder's latency query here instead.
        live = self.pipeline.get_by_name("live").get_static_pad("src")
        live.add_probe(Gst.PadProbeType.QUERY_UPSTREAM, self._on_query)
        live.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer)
        self.encoder = self.pipeline.get_by_name("enc")
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_bus_error)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.get_bus().remove_signal_watch()
        self.pipeline.set_state(Gst.State.NULL)

    def force_keyframe(self):
        self.keyframes += 1
        event = GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, self.keyframes)
        self.encoder.get_static_pad("src").send_event(event)

    def _on_buffer(self, pad, info):
        self.frames += 1
        return Gst.PadProbeReturn.OK

    @staticmethod
    def _on_query(pad, info):
        query = info.get_query()
        if query.type != Gst.QueryType.LATENCY:
            return Gst.PadProbeReturn.OK
        # PyGObject holds a second reference, which makes the query read-only; drop it for the write
        query.mini_object.refcount -= 1
        query.set_latency(True, 0, Gst.CLOCK_TIME_NONE)
        query.mini_object.refcount += 1
        return Gst.PadProbeReturn.HANDLED

    def _on_bus_error(self, bus, message):
        error, _ = message.parse_error()
        self.on_error(f"video pipeline: {error.message}")
