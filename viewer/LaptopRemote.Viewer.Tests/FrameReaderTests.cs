using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class FrameReaderTests
{
    [Fact]
    public void FramesSplitAcrossFeeds()
    {
        byte[] data = [.. MessageCodec.Encode(new Heartbeat()), .. MessageCodec.Encode(new Welcome(1, 47802))];
        var reader = new FrameReader();
        var seen = new List<Message>();
        for (var index = 0; index < data.Length; index++)
            seen.AddRange(reader.Feed(data.AsSpan(index, 1)));
        Assert.Equal([new Heartbeat(), new Welcome(1, 47802)], seen);
    }

    [Fact]
    public void OversizeFrameIsRejected()
    {
        byte[] header = [0x00, 0x20, 0x00, 0x01];
        Assert.Throws<ProtocolException>(() => new FrameReader().Feed(header));
    }
}
