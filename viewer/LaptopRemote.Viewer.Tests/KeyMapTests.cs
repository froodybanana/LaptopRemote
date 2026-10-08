using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class KeyMapTests
{
    private const int VkPause = 0x13, VkNumLock = 0x90, VkA = 0x41;

    [Theory]
    [InlineData(0x01, 1)]    // Esc
    [InlineData(0x1E, 30)]   // A
    [InlineData(0x1C, 28)]   // Enter
    [InlineData(0x1D, 29)]   // left Ctrl
    [InlineData(0x2A, 42)]   // left Shift
    [InlineData(0x38, 56)]   // left Alt
    [InlineData(0x39, 57)]   // Space
    [InlineData(0x3A, 58)]   // Caps Lock
    [InlineData(0x46, 70)]   // Scroll Lock
    [InlineData(0x47, 71)]   // keypad 7
    [InlineData(0x53, 83)]   // keypad .
    [InlineData(0x56, 86)]   // the key between left Shift and Z on ISO keyboards
    [InlineData(0x57, 87)]   // F11
    [InlineData(0x58, 88)]   // F12
    [InlineData(0x54, 99)]   // Alt+PrintScreen
    [InlineData(0x64, 183)]  // F13
    [InlineData(0x76, 194)]  // F24
    public void PlainKeys(int scanCode, int linux) =>
        Assert.Equal(linux, KeyMap.ToLinux(scanCode, extended: false, VkA));

    [Theory]
    [InlineData(0x1C, 96)]   // keypad Enter
    [InlineData(0x1D, 97)]   // right Ctrl
    [InlineData(0x35, 98)]   // keypad /
    [InlineData(0x37, 99)]   // PrintScreen
    [InlineData(0x38, 100)]  // right Alt, AltGr
    [InlineData(0x46, 119)]  // Ctrl+Pause
    [InlineData(0x47, 102)]  // Home
    [InlineData(0x48, 103)]  // Up
    [InlineData(0x49, 104)]  // Page Up
    [InlineData(0x4B, 105)]  // Left
    [InlineData(0x4D, 106)]  // Right
    [InlineData(0x4F, 107)]  // End
    [InlineData(0x50, 108)]  // Down
    [InlineData(0x51, 109)]  // Page Down
    [InlineData(0x52, 110)]  // Insert
    [InlineData(0x53, 111)]  // Delete
    [InlineData(0x5B, 125)]  // left Windows
    [InlineData(0x5C, 126)]  // right Windows
    [InlineData(0x5D, 127)]  // Menu
    public void ExtendedKeys(int scanCode, int linux) =>
        Assert.Equal(linux, KeyMap.ToLinux(scanCode, extended: true, VkA));

    [Fact]
    public void PauseAndNumLockShareAScanCode()
    {
        // the low-level hook reports both as 0x45; only the virtual key tells them apart
        Assert.Equal(119, KeyMap.ToLinux(0x45, extended: false, VkPause));
        Assert.Equal(69, KeyMap.ToLinux(0x45, extended: true, VkNumLock));
        Assert.Equal(69, KeyMap.ToLinux(0x45, extended: false, VkNumLock));
    }

    [Fact]
    public void RightShiftWithOrWithoutTheExtendedFlag()
    {
        Assert.Equal(54, KeyMap.ToLinux(0x36, extended: false, 0xA1));
        Assert.Equal(54, KeyMap.ToLinux(0x36, extended: true, 0xA1));
    }

    [Theory]
    [InlineData(0x21D, false, 0xA2)]  // the left Ctrl Windows makes up when AltGr goes down
    [InlineData(0x2A, true, 0xFF)]    // the shift Windows makes up around PrintScreen and the arrow block
    [InlineData(0x2A, true, 0xA0)]
    [InlineData(0x1E, false, 0xFF)]
    [InlineData(0, false, 0xE7)]      // a character sent by another program, no physical key
    [InlineData(0x20, true, 0xAD)]    // Mute: media keys stay with the PC
    [InlineData(0x59, false, VkA)]
    [InlineData(0x7F, true, VkA)]
    [InlineData(-1, false, VkA)]
    public void WhatIsNotAPhysicalKeyForTheLaptopMapsToNothing(int scanCode, bool extended, int virtualKey) =>
        Assert.Null(KeyMap.ToLinux(scanCode, extended, virtualKey));
}
