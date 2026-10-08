using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class WindowPlacementTests
{
    private static readonly (int X, int Y, int Width, int Height)[] OneScreen = [(0, 0, 1920, 1040)];

    [Fact]
    public void RoundTrips()
    {
        var placement = new WindowPlacement(-1200, 40, 1296, 759, true);
        Assert.Equal(placement, WindowPlacement.Parse(placement.ToJson()));
    }

    [Theory]
    [InlineData("")]
    [InlineData("{ not json")]
    [InlineData("[]")]
    [InlineData("""{ "x": 1 }""")]
    [InlineData("""{ "x": "a", "y": 0, "width": 800, "height": 600, "maximized": false }""")]
    [InlineData("""{ "x": 0, "y": 0, "width": 800.5, "height": 600, "maximized": false }""")]
    [InlineData("""{ "x": 0, "y": 0, "width": 800, "height": 600, "maximized": "yes" }""")]
    public void BrokenTextGivesNull(string json) =>
        Assert.Null(WindowPlacement.Parse(json));

    [Fact]
    public void FitsWhenInsideAWorkArea() =>
        Assert.True(new WindowPlacement(100, 100, 1296, 759, false).FitsAny(OneScreen));

    [Fact]
    public void DoesNotFitWhenItsMonitorIsGone() =>
        Assert.False(new WindowPlacement(3000, 100, 1296, 759, false).FitsAny(OneScreen));

    [Fact]
    public void DoesNotFitWhenTitleBarIsAboveTheScreen() =>
        Assert.False(new WindowPlacement(100, -200, 1296, 759, false).FitsAny(OneScreen));

    [Fact]
    public void DoesNotFitWhenOnlyASliverShows() =>
        Assert.False(new WindowPlacement(1900, 100, 1296, 759, false).FitsAny(OneScreen));

    [Fact]
    public void DoesNotFitWhenTiny() =>
        Assert.False(new WindowPlacement(100, 100, 50, 50, false).FitsAny(OneScreen));

    [Fact]
    public void FitsOnASecondMonitorWithNegativeCoordinates() =>
        Assert.True(new WindowPlacement(-1800, -300, 1296, 759, false)
            .FitsAny([(0, 0, 1920, 1040), (-1920, -400, 1920, 1080)]));

    [Fact]
    public void FitsWhenMaximizedBoundsOverhangTheWorkAreaALittle() =>
        // Windows reports a maximized window 8 px outside its monitor on every side
        Assert.True(new WindowPlacement(-8, -8, 1936, 1056, true).FitsAny(OneScreen));
}
