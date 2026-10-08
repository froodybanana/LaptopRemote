using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class ResizeDebouncerTests
{
    private static TimeSpan Ms(int value) => TimeSpan.FromMilliseconds(value);

    [Fact]
    public void ReportsOnceAfterTheDragSettles()
    {
        var debouncer = new ResizeDebouncer(Ms(150));
        debouncer.MarkSent(1600, 900);
        debouncer.Changed(1500, 900, Ms(0));
        debouncer.Changed(1400, 800, Ms(100));
        Assert.Null(debouncer.Poll(Ms(200)));
        Assert.Equal((1400, 800), debouncer.Poll(Ms(250)));
        Assert.Null(debouncer.Poll(Ms(400)));
    }

    [Fact]
    public void SentIsTheSizeTheLaptopWasLastTold()
    {
        var debouncer = new ResizeDebouncer(Ms(150));
        debouncer.MarkSent(1601, 901);
        Assert.Equal((1600, 900), debouncer.Sent);
        debouncer.Changed(1400, 800, Ms(0));
        Assert.Equal((1600, 900), debouncer.Sent);  // not yet told: mouse positions still belong to the old size
        debouncer.Poll(Ms(200));
        Assert.Equal((1400, 800), debouncer.Sent);
    }

    [Fact]
    public void ReturningToTheSentSizeReportsNothing()
    {
        var debouncer = new ResizeDebouncer(Ms(150));
        debouncer.MarkSent(1600, 900);
        debouncer.Changed(1500, 900, Ms(0));
        debouncer.Changed(1600, 900, Ms(50));
        Assert.Null(debouncer.Poll(Ms(500)));
    }

    [Fact]
    public void SizesAreNormalizedBeforeComparing()
    {
        var debouncer = new ResizeDebouncer(Ms(150));
        debouncer.MarkSent(1600, 900);
        debouncer.Changed(1601, 901, Ms(0));
        Assert.Null(debouncer.Poll(Ms(500)));
    }

    [Fact]
    public void AnEmptySizeIsIgnored()
    {
        // a minimized window reports 0x0; that must not shrink the laptop's output
        var debouncer = new ResizeDebouncer(Ms(150));
        debouncer.MarkSent(1600, 900);
        debouncer.Changed(0, 0, Ms(0));
        Assert.Null(debouncer.Poll(Ms(500)));
    }
}
