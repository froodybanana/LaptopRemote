using LaptopRemote.Viewer.Native;

namespace LaptopRemote.Viewer;

/// <summary>A GStreamer pipeline whose element "sink" draws into a window we own.
/// Optional elements: "src" (udpsrc, for Punch) and "jitter" (rtpjitterbuffer, for LostPackets).</summary>
internal sealed class VideoPipeline : IDisposable
{
    private readonly IntPtr pipeline, sink, bus, source, jitter;
    private readonly Gst.PadProbeCallback onBuffer;  // kept in a field so the delegate outlives the native probe
    private int frameArrived;

    public static void Initialize(string gstreamerBin)
    {
        if (!Directory.Exists(gstreamerBin))
            throw new DirectoryNotFoundException($"GStreamer not found at {gstreamerBin}");
        Gst.SetDllDirectory(gstreamerBin);
        Gst.gst_init(IntPtr.Zero, IntPtr.Zero);
    }

    /// <summary>Whether this GStreamer has an element of that name; call after Initialize.</summary>
    public static bool HasElement(string name)
    {
        var factory = Gst.gst_element_factory_find(name);
        if (factory == IntPtr.Zero) return false;
        Gst.gst_object_unref(factory);
        return true;
    }

    public VideoPipeline(string description, IntPtr windowHandle)
    {
        pipeline = Gst.gst_parse_launch(description, out var error);
        if (error != IntPtr.Zero) throw new InvalidOperationException(Gst.TakeError(error));
        sink = Gst.gst_bin_get_by_name(pipeline, "sink");
        source = Gst.gst_bin_get_by_name(pipeline, "src");
        jitter = Gst.gst_bin_get_by_name(pipeline, "jitter");
        bus = Gst.gst_element_get_bus(pipeline);
        Gst.gst_video_overlay_set_window_handle(sink, windowHandle);
        onBuffer = (_, _, _) => { Interlocked.Exchange(ref frameArrived, 1); return Gst.PadProbeOk; };
        var pad = Gst.gst_element_get_static_pad(sink, "sink");
        Gst.gst_pad_add_probe(pad, Gst.PadProbeBuffer, onBuffer, IntPtr.Zero, IntPtr.Zero);
        Gst.gst_object_unref(pad);
    }

    public void Play() => Gst.gst_element_set_state(pipeline, Gst.StatePlaying);

    public void Expose() => Gst.gst_video_overlay_expose(sink);

    public bool TakeFrameArrived() => Interlocked.Exchange(ref frameArrived, 0) == 1;

    public string? PollError()
    {
        var message = Gst.gst_bus_pop_filtered(bus, Gst.MessageError);
        if (message == IntPtr.Zero) return null;
        Gst.gst_message_parse_error(message, out var error, out var debug);
        Gst.g_free(debug);
        Gst.gst_mini_object_unref(message);
        return Gst.TakeError(error);
    }

    public ulong LostPackets()
    {
        if (jitter == IntPtr.Zero) return 0;
        Gst.g_object_get(jitter, "stats", out var stats, IntPtr.Zero);
        if (stats == IntPtr.Zero) return 0;
        Gst.gst_structure_get_uint64(stats, "num-lost", out var lost);
        Gst.gst_structure_free(stats);
        return lost;
    }

    /// <summary>Sends a small packet from the video receive socket so Windows Firewall lets the stream in as a reply.</summary>
    public void Punch(string address, int port)
    {
        if (source == IntPtr.Zero) return;
        Gst.g_object_get(source, "used-socket", out var socket, IntPtr.Zero);
        if (socket == IntPtr.Zero) return;
        var target = Gst.g_inet_socket_address_new_from_string(address, (uint)port);
        if (target == IntPtr.Zero)
        {
            Gst.g_object_unref(socket);
            return;
        }
        byte[] packet = [(byte)'p', (byte)'u', (byte)'n', (byte)'c', (byte)'h'];
        Gst.g_socket_send_to(socket, target, packet, (nuint)packet.Length, IntPtr.Zero, out var error);
        if (error != IntPtr.Zero) Gst.g_error_free(error);
        Gst.g_object_unref(target);
        Gst.g_object_unref(socket);
    }

    public void Dispose()
    {
        Gst.gst_element_set_state(pipeline, Gst.StateNull);
        if (jitter != IntPtr.Zero) Gst.gst_object_unref(jitter);
        if (source != IntPtr.Zero) Gst.gst_object_unref(source);
        Gst.gst_object_unref(sink);
        Gst.gst_object_unref(bus);
        Gst.gst_object_unref(pipeline);
    }
}
