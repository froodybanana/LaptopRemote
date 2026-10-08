namespace LaptopRemote.Viewer.Core;

/// <summary>
/// From what the Windows low-level keyboard hook reports for a key to the Linux key code of the same
/// physical key. Characters play no part: the laptop applies the layout.
/// </summary>
public static class KeyMap
{
    private const int VkPause = 0x13, VkFake = 0xFF;
    private const int Pause = 119, NumLock = 69, RightShift = 54;

    // keys whose scan code carries the E0 prefix
    private static readonly Dictionary<int, int> Extended = new()
    {
        [0x1C] = 96,   // keypad Enter
        [0x1D] = 97,   // right Ctrl
        [0x35] = 98,   // keypad /
        [0x37] = 99,   // PrintScreen
        [0x38] = 100,  // right Alt
        [0x46] = Pause,  // Ctrl+Pause
        [0x47] = 102,  // Home
        [0x48] = 103,  // Up
        [0x49] = 104,  // Page Up
        [0x4B] = 105,  // Left
        [0x4D] = 106,  // Right
        [0x4F] = 107,  // End
        [0x50] = 108,  // Down
        [0x51] = 109,  // Page Down
        [0x52] = 110,  // Insert
        [0x53] = 111,  // Delete
        [0x5B] = 125,  // left Windows
        [0x5C] = 126,  // right Windows
        [0x5D] = 127,  // Menu
    };

    /// <summary>The Linux key code, or null for what is no physical key the laptop should see.</summary>
    public static int? ToLinux(int scanCode, bool extended, int virtualKey)
    {
        // Windows makes up shift and ctrl presses around some keys (AltGr, PrintScreen, the arrow block);
        // they carry virtual key 0xFF or a scan code above one byte
        if (virtualKey == VkFake || scanCode is <= 0 or > 0xFF) return null;
        // the hook reports Pause and Num Lock with the same scan code, and right Shift with or without the prefix
        if (scanCode == 0x45) return virtualKey == VkPause ? Pause : NumLock;
        if (scanCode == 0x36) return RightShift;
        if (extended) return Extended.TryGetValue(scanCode, out var code) ? code : null;
        return scanCode switch
        {
            // Linux numbered the keys of the PC keyboard by their scan codes
            <= 0x53 or (>= 0x56 and <= 0x58) => scanCode,
            0x54 => 99,                                  // Alt+PrintScreen
            >= 0x64 and <= 0x6E => scanCode - 0x64 + 183,  // F13 to F23
            0x76 => 194,                                 // F24
            _ => null,
        };
    }
}
