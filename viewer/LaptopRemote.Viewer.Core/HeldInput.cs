namespace LaptopRemote.Viewer.Core;

/// <summary>What to do with a key the keyboard hook reports.</summary>
public enum KeyVerdict
{
    /// <summary>Not the laptop's: Windows gets it.</summary>
    Pass,
    /// <summary>Kept from Windows, and no news for the laptop: a repeat of a key it already has down.</summary>
    Keep,
    /// <summary>Kept from Windows and sent to the laptop.</summary>
    Send,
    /// <summary>Windows gets it, and the laptop is told to let go of everything.</summary>
    ReleaseAllAndPass,
}

/// <summary>
/// Which keys and mouse buttons the laptop has been told are down, and from that who gets a key: Windows
/// or the laptop, never the press to one and the release to the other.
/// </summary>
public sealed class HeldInput
{
    private const int LeftCtrl = 29, RightCtrl = 97, LeftAlt = 56, RightAlt = 100, Delete = 111, KeypadDot = 83;

    private readonly HashSet<int> keys = [];
    private readonly HashSet<string> buttons = [];

    /// <param name="code">Linux key code.</param>
    /// <param name="down">Press or release.</param>
    /// <param name="downInWindows">Windows already has this key down, so it saw a press the hook did not take.</param>
    /// <param name="inFront">The viewer is the window the user types in; a key pressed elsewhere is not the laptop's.</param>
    public KeyVerdict Key(int code, bool down, bool downInWindows, bool inFront = true)
    {
        if (!down) return keys.Remove(code) ? KeyVerdict.Send : KeyVerdict.Pass;
        if (keys.Contains(code)) return KeyVerdict.Keep;  // Windows repeats a held key; the laptop does that itself
        // a key that went down before the hook was looking stays with Windows, repeats and release included
        if (downInWindows || !inFront) return KeyVerdict.Pass;
        // Ctrl+Alt+Del: Windows takes the keyboard for its security screen and the releases never arrive
        if (code is Delete or KeypadDot && (keys.Contains(LeftCtrl) || keys.Contains(RightCtrl))
                                        && (keys.Contains(LeftAlt) || keys.Contains(RightAlt)))
        {
            Clear();
            return KeyVerdict.ReleaseAllAndPass;
        }
        keys.Add(code);
        return KeyVerdict.Send;
    }

    /// <summary>True when the press is news for the laptop; a double click arrives as a second press.</summary>
    public bool ButtonDown(string button) => buttons.Add(button);

    /// <summary>True when the laptop has this button down.</summary>
    public bool ButtonUp(string button) => buttons.Remove(button);

    /// <summary>Forgets everything, as after a release message. True if anything was held.</summary>
    public bool Clear()
    {
        var any = keys.Count > 0 || buttons.Count > 0;
        keys.Clear();
        buttons.Clear();
        return any;
    }
}
