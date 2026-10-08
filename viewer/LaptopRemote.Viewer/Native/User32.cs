using System.Runtime.InteropServices;

namespace LaptopRemote.Viewer.Native;

internal static class User32
{
    private const int SwRestore = 9;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindowW(string? className, string title);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr window, int command);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);

    /// <summary>Goes up every time the clipboard's content is replaced, by any program.</summary>
    [DllImport("user32.dll")]
    public static extern uint GetClipboardSequenceNumber();

    /// <summary>The window the user is working in, which is the one the keyboard goes to.</summary>
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    public const int WhKeyboardLl = 13, WmKeyDown = 0x100, WmSysKeyDown = 0x104, WmMouseWheel = 0x20A, WmMouseHWheel = 0x20E;
    public const uint LlkhfExtended = 1;

    public delegate IntPtr HookProc(int code, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    public struct KeyboardHookData
    {
        public uint VirtualKey, ScanCode, Flags, Time;
        public UIntPtr ExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SetWindowsHookExW(int kind, HookProc callback, IntPtr module, uint thread);

    [DllImport("user32.dll")]
    public static extern bool UnhookWindowsHookEx(IntPtr hook);

    [DllImport("user32.dll")]
    public static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr GetModuleHandleW(string? name);

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int virtualKey);

    /// <summary>Whether Windows has this key down. Inside the keyboard hook that is the state before the hooked event.</summary>
    public static bool IsKeyDown(int virtualKey) => GetAsyncKeyState(virtualKey) < 0;

    private delegate bool EnumProc(IntPtr window, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern bool EnableWindow(IntPtr window, bool enable);

    [DllImport("user32.dll")]
    private static extern bool IsWindowEnabled(IntPtr window);

    /// <summary>
    /// Disables every window inside this one. Windows gives the mouse input of a disabled child to its parent,
    /// which is how the video panel gets the mouse although the video sink puts a window of its own on top.
    /// </summary>
    public static void DisableChildren(IntPtr parent) =>
        EnumChildWindows(parent, (child, _) =>
        {
            if (IsWindowEnabled(child)) EnableWindow(child, false);
            return true;
        }, IntPtr.Zero);

    /// <summary>Brings the window with this title to the front, restoring it if minimized. False if there is none.</summary>
    public static bool Activate(string title)
    {
        var window = FindWindowW(null, title);
        if (window == IntPtr.Zero) return false;
        if (IsIconic(window)) ShowWindow(window, SwRestore);
        SetForegroundWindow(window);
        return true;
    }
}
