using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class PointerMapTests
{
    [Fact]
    public void OneToOneWhenTheAreaIsTheStreamSize()
    {
        Assert.Equal((0, 0), PointerMap.ToStream(0, 0, 1600, 900, 1600, 900));
        Assert.Equal((640, 360), PointerMap.ToStream(640, 360, 1600, 900, 1600, 900));
        Assert.Equal((1599, 899), PointerMap.ToStream(1599, 899, 1600, 900, 1600, 900));
    }

    [Fact]
    public void ScaledWhileAResizeIsInFlight()
    {
        // the window is already 800 wide, the laptop still sends 1600: the old picture is stretched
        Assert.Equal((800, 450), PointerMap.ToStream(400, 225, 800, 450, 1600, 900));
        Assert.Equal((1598, 898), PointerMap.ToStream(799, 449, 800, 450, 1600, 900));
        Assert.Equal((200, 100), PointerMap.ToStream(400, 200, 3200, 1800, 1600, 900));
    }

    [Fact]
    public void OddAreaSizesStayInsideTheStream()
    {
        // the stream is the area rounded down to even numbers
        Assert.Equal((1599, 899), PointerMap.ToStream(1600, 900, 1601, 901, 1600, 900));
    }

    [Theory]
    [InlineData(-10, -1, 0, 0)]
    [InlineData(5000, 20, 1599, 20)]
    [InlineData(30, 5000, 30, 899)]
    [InlineData(int.MaxValue, int.MinValue, 1599, 0)]
    public void PositionsOutsideTheAreaGoToTheEdge(int x, int y, int wantX, int wantY) =>
        Assert.Equal((wantX, wantY), PointerMap.ToStream(x, y, 1600, 900, 1600, 900));

    [Theory]
    [InlineData(0, 900, 1600, 900)]
    [InlineData(1600, 0, 1600, 900)]
    [InlineData(1600, 900, 0, 900)]
    [InlineData(1600, 900, 1600, -2)]
    public void NothingWithoutAnAreaOrAStream(int areaWidth, int areaHeight, int streamWidth, int streamHeight) =>
        Assert.Null(PointerMap.ToStream(10, 10, areaWidth, areaHeight, streamWidth, streamHeight));
}
