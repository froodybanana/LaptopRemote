using System.Runtime.InteropServices;

namespace LaptopRemote.Viewer.Native;

/// <summary>The few GStreamer and GLib C functions the viewer needs. x64 only.</summary>
internal static class Gst
{
    private const string Core = "gstreamer-1.0-0.dll", Video = "gstvideo-1.0-0.dll",
        GObject = "gobject-2.0-0.dll", Gio = "gio-2.0-0.dll", GLib = "glib-2.0-0.dll";

    public const int StateNull = 1, StatePlaying = 4;
    public const int MessageError = 2;
    public const int PadProbeBuffer = 16, PadProbeOk = 1;

    [StructLayout(LayoutKind.Sequential)]
    public struct GError { public uint Domain; public int Code; public IntPtr Message; }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate int PadProbeCallback(IntPtr pad, IntPtr info, IntPtr data);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool SetDllDirectory(string path);

    [DllImport(Core)] public static extern void gst_init(IntPtr argc, IntPtr argv);
    [DllImport(Core)] public static extern IntPtr gst_parse_launch([MarshalAs(UnmanagedType.LPUTF8Str)] string description, out IntPtr error);
    [DllImport(Core)] public static extern int gst_element_set_state(IntPtr element, int state);
    [DllImport(Core)] public static extern IntPtr gst_bin_get_by_name(IntPtr bin, [MarshalAs(UnmanagedType.LPUTF8Str)] string name);
    [DllImport(Core)] public static extern IntPtr gst_element_get_bus(IntPtr element);
    [DllImport(Core)] public static extern IntPtr gst_bus_pop_filtered(IntPtr bus, int types);
    [DllImport(Core)] public static extern void gst_message_parse_error(IntPtr message, out IntPtr error, out IntPtr debug);
    [DllImport(Core)] public static extern void gst_mini_object_unref(IntPtr miniObject);
    [DllImport(Core)] public static extern void gst_object_unref(IntPtr instance);
    [DllImport(Core)] public static extern IntPtr gst_element_factory_find([MarshalAs(UnmanagedType.LPUTF8Str)] string name);
    [DllImport(Core)] public static extern IntPtr gst_element_get_static_pad(IntPtr element, [MarshalAs(UnmanagedType.LPUTF8Str)] string name);
    [DllImport(Core)] public static extern nuint gst_pad_add_probe(IntPtr pad, int mask, PadProbeCallback callback, IntPtr data, IntPtr destroy);
    [DllImport(Core)] public static extern bool gst_structure_get_uint64(IntPtr structure, [MarshalAs(UnmanagedType.LPUTF8Str)] string field, out ulong value);
    [DllImport(Core)] public static extern void gst_structure_free(IntPtr structure);
    [DllImport(Video)] public static extern void gst_video_overlay_set_window_handle(IntPtr overlay, IntPtr handle);
    [DllImport(Video)] public static extern void gst_video_overlay_expose(IntPtr overlay);
    [DllImport(GObject)] public static extern void g_object_get(IntPtr instance, [MarshalAs(UnmanagedType.LPUTF8Str)] string property, out IntPtr value, IntPtr end);
    [DllImport(GObject)] public static extern void g_object_unref(IntPtr instance);
    [DllImport(Gio)] public static extern IntPtr g_inet_socket_address_new_from_string([MarshalAs(UnmanagedType.LPUTF8Str)] string address, uint port);
    [DllImport(Gio)] public static extern nint g_socket_send_to(IntPtr socket, IntPtr address, byte[] buffer, nuint size, IntPtr cancellable, out IntPtr error);
    [DllImport(GLib)] public static extern void g_error_free(IntPtr error);
    [DllImport(GLib)] public static extern void g_free(IntPtr memory);

    public static string TakeError(IntPtr error)
    {
        var text = Marshal.PtrToStringUTF8(Marshal.PtrToStructure<GError>(error).Message) ?? "unknown error";
        g_error_free(error);
        return text;
    }
}
