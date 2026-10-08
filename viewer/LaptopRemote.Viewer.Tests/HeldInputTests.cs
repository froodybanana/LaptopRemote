using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class HeldInputTests
{
    private const int A = 30, LeftCtrl = 29, RightCtrl = 97, LeftAlt = 56, RightAlt = 100, Delete = 111, KeypadDot = 83;
    private readonly HeldInput held = new();

    [Fact]
    public void AKeyRepeatedByWindowsIsSentOnce()
    {
        Assert.Equal(KeyVerdict.Send, held.Key(A, down: true, downInWindows: false));
        Assert.Equal(KeyVerdict.Keep, held.Key(A, down: true, downInWindows: false));
        Assert.Equal(KeyVerdict.Keep, held.Key(A, down: true, downInWindows: false));
        Assert.Equal(KeyVerdict.Send, held.Key(A, down: false, downInWindows: false));
        Assert.Equal(KeyVerdict.Send, held.Key(A, down: true, downInWindows: false));
    }

    [Fact]
    public void AnUpForAKeyThatNeverWentDownHereGoesToWindows()
    {
        // Alt of the Alt+Tab that brought the window to the front: Windows saw the press and needs the release
        Assert.Equal(KeyVerdict.Pass, held.Key(LeftAlt, down: false, downInWindows: true));
        Assert.False(held.ButtonUp("left"));
    }

    [Fact]
    public void AKeyWindowsAlreadyHasDownStaysWithWindowsThroughItsRepeats()
    {
        // Ctrl held while clicking into the viewer: taking a repeat would leave Windows waiting for the release for ever
        Assert.Equal(KeyVerdict.Pass, held.Key(LeftCtrl, down: true, downInWindows: true));
        Assert.Equal(KeyVerdict.Pass, held.Key(LeftCtrl, down: true, downInWindows: true));
        Assert.Equal(KeyVerdict.Pass, held.Key(LeftCtrl, down: false, downInWindows: true));
        // pressed again, it is the laptop's
        Assert.Equal(KeyVerdict.Send, held.Key(LeftCtrl, down: true, downInWindows: false));
    }

    [Theory]
    [InlineData(LeftCtrl, LeftAlt, Delete)]
    [InlineData(RightCtrl, RightAlt, Delete)]
    [InlineData(LeftCtrl, RightAlt, KeypadDot)]
    public void CtrlAltDelLetsGoOfEverything(int ctrl, int alt, int delete)
    {
        // Windows takes the keyboard away for its security screen and the releases never arrive
        held.Key(ctrl, down: true, downInWindows: false);
        held.Key(alt, down: true, downInWindows: false);
        held.ButtonDown("left");
        Assert.Equal(KeyVerdict.ReleaseAllAndPass, held.Key(delete, down: true, downInWindows: false));
        Assert.False(held.Clear());
        Assert.Equal(KeyVerdict.Pass, held.Key(ctrl, down: false, downInWindows: false));
    }

    [Fact]
    public void DeleteWithOnlyCtrlOrOnlyAltIsAnOrdinaryKey()
    {
        held.Key(LeftCtrl, down: true, downInWindows: false);
        Assert.Equal(KeyVerdict.Send, held.Key(Delete, down: true, downInWindows: false));
        held.Clear();
        held.Key(LeftAlt, down: true, downInWindows: false);
        Assert.Equal(KeyVerdict.Send, held.Key(Delete, down: true, downInWindows: false));
    }

    [Fact]
    public void AKeyPressedWhileAnotherWindowIsInFrontGoesToWindows()
    {
        // the window can be active without being the one the user types in
        Assert.Equal(KeyVerdict.Pass, held.Key(A, down: true, downInWindows: false, inFront: false));
        Assert.Equal(KeyVerdict.Pass, held.Key(A, down: false, downInWindows: false, inFront: false));
    }

    [Fact]
    public void AKeyTheLaptopHasIsReleasedThereWhateverIsInFront()
    {
        Assert.Equal(KeyVerdict.Send, held.Key(A, down: true, downInWindows: false, inFront: true));
        Assert.Equal(KeyVerdict.Keep, held.Key(A, down: true, downInWindows: false, inFront: false));
        Assert.Equal(KeyVerdict.Send, held.Key(A, down: false, downInWindows: false, inFront: false));
    }

    [Fact]
    public void ButtonsAreSentOncePerPress()
    {
        Assert.True(held.ButtonDown("left"));
        Assert.False(held.ButtonDown("left"));  // a double click arrives as a second down
        Assert.True(held.ButtonDown("right"));
        Assert.True(held.ButtonUp("left"));
        Assert.False(held.ButtonUp("left"));
    }

    [Fact]
    public void ClearForgetsEverythingAndSaysWhetherAnythingWasHeld()
    {
        Assert.False(held.Clear());
        held.Key(A, down: true, downInWindows: false);
        held.ButtonDown("left");
        Assert.True(held.Clear());
        Assert.False(held.Clear());
        Assert.Equal(KeyVerdict.Pass, held.Key(A, down: false, downInWindows: false));
        held.ButtonDown("left");
        Assert.True(held.Clear());
    }
}
