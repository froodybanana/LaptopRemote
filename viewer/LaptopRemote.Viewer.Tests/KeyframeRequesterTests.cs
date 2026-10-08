using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class KeyframeRequesterTests
{
    private static TimeSpan Ms(int value) => TimeSpan.FromMilliseconds(value);

    [Fact]
    public void AsksRepeatedlyUntilAFrameArrives()
    {
        var requester = new KeyframeRequester(Ms(250));
        Assert.False(requester.Poll(Ms(0)));
        requester.NeedPicture();
        Assert.True(requester.Poll(Ms(10)));
        Assert.False(requester.Poll(Ms(100)));
        Assert.True(requester.Poll(Ms(260)));
        requester.FrameArrived(Ms(300));
        Assert.False(requester.Poll(Ms(600)));
    }

    [Fact]
    public void ANewNeedAsksAtOnce()
    {
        var requester = new KeyframeRequester(Ms(250));
        requester.NeedPicture();
        Assert.True(requester.Poll(Ms(0)));
        requester.FrameArrived(Ms(10));
        requester.NeedPicture();
        Assert.True(requester.Poll(Ms(20)));
    }

    [Fact]
    public void FramesDuringTheHoldWindowDoNotStopTheAsking()
    {
        // after a resize, frames of the old stream keep arriving for a moment
        var requester = new KeyframeRequester(Ms(250));
        requester.NeedPicture(Ms(0), Ms(1000));
        Assert.True(requester.Poll(Ms(0)));
        requester.FrameArrived(Ms(50));
        Assert.True(requester.Poll(Ms(260)));
        requester.FrameArrived(Ms(900));
        Assert.True(requester.Poll(Ms(950)));
        requester.FrameArrived(Ms(1100));
        Assert.False(requester.Poll(Ms(1300)));
    }
}
