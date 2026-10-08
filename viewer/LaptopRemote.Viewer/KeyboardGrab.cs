using System.Runtime.InteropServices;
using LaptopRemote.Viewer.Native;

namespace LaptopRemote.Viewer;

/// <summary>
/// A low-level keyboard hook: the only way to see the Windows key, Alt+Tab and the like before Windows
/// acts on them. While installed, every key on the PC passes through <paramref name="onKey"/> on the
/// UI thread, so it is installed only while the viewer window is active and the callback must not wait.
/// </summary>
/// <param name="onKey">scan code, extended flag, virtual key, down; true keeps the key from Windows.</param>
internal sealed class KeyboardGrab(Func<int, bool, int, bool, bool> onKey) : IDisposable
{
    private User32.HookProc? callback;  // kept in a field so the delegate outlives the native hook
    private IntPtr hook;

    public void Install()
    {
        if (hook != IntPtr.Zero) return;
        callback ??= OnHook;
        hook = User32.SetWindowsHookExW(User32.WhKeyboardLl, callback, User32.GetModuleHandleW(null), 0);
    }

    public void Remove()
    {
        if (hook == IntPtr.Zero) return;
        User32.UnhookWindowsHookEx(hook);
        hook = IntPtr.Zero;
    }

    private IntPtr OnHook(int code, IntPtr wParam, IntPtr lParam)
    {
        if (code == 0)
        {
            var data = Marshal.PtrToStructure<User32.KeyboardHookData>(lParam);
            var down = (int)wParam is User32.WmKeyDown or User32.WmSysKeyDown;
            var taken = false;
            try
            {
                taken = onKey((int)data.ScanCode, (data.Flags & User32.LlkhfExtended) != 0, (int)data.VirtualKey, down);
            }
            catch (Exception)
            {
                // an exception must not travel into Windows' hook chain; the key goes to Windows instead
            }
            if (taken) return 1;
        }
        return User32.CallNextHookEx(IntPtr.Zero, code, wParam, lParam);
    }

    public void Dispose() => Remove();
}
