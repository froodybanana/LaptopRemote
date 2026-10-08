using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class OutboxTests
{
    private readonly Outbox outbox = new();

    private List<Message> Drain()
    {
        outbox.Complete();
        var taken = new List<Message>();
        while (outbox.Take(out var message)) taken.Add(message);
        return taken;
    }

    [Fact]
    public void MessagesComeOutInOrder()
    {
        outbox.Add(new Key(30, true));
        outbox.Add(new Heartbeat());
        outbox.Add(new Key(30, false));
        Assert.Equal([new Key(30, true), new Heartbeat(), new Key(30, false)], Drain());
    }

    [Fact]
    public void QueuedPointerPositionsCollapseIntoTheNewest()
    {
        // the connection is slower than the mouse: only where the pointer is now matters
        outbox.Add(new MouseMove(1, 1));
        outbox.Add(new MouseMove(2, 2));
        outbox.Add(new MouseMove(3, 3));
        Assert.Equal([new MouseMove(3, 3)], Drain());
    }

    [Fact]
    public void APositionIsNotMovedAcrossAClick()
    {
        // the press must happen where the pointer was at that moment
        outbox.Add(new MouseMove(1, 1));
        outbox.Add(new MouseButton("left", true));
        outbox.Add(new MouseMove(2, 2));
        outbox.Add(new MouseMove(3, 3));
        outbox.Add(new MouseButton("left", false));
        Assert.Equal([new MouseMove(1, 1), new MouseButton("left", true), new MouseMove(3, 3),
                      new MouseButton("left", false)], Drain());
    }

    [Fact]
    public async Task TakeWaitsForAMessage()
    {
        var taking = Task.Run(() => outbox.Take(out var message) ? message : null);
        await Task.Delay(100);
        Assert.False(taking.IsCompleted);
        outbox.Add(new Heartbeat());
        Assert.Equal(new Heartbeat(), await taking.WaitAsync(TimeSpan.FromSeconds(3)));
    }

    [Fact]
    public async Task CompleteLetsTheQueueDrainAndThenEndsTake()
    {
        outbox.Add(new Goodbye());
        outbox.Complete();
        Assert.True(outbox.Take(out var last));
        Assert.Equal(new Goodbye(), last);
        Assert.False(outbox.Take(out _));
        var empty = new Outbox();
        var waiting = Task.Run(() => empty.Take(out _));
        await Task.Delay(50);
        empty.Complete();
        Assert.False(await waiting.WaitAsync(TimeSpan.FromSeconds(3)));
    }

    [Fact]
    public void NothingIsAcceptedAfterComplete()
    {
        outbox.Complete();
        outbox.Add(new Heartbeat());
        Assert.False(outbox.Take(out _));
    }

    [Fact]
    public void APileUpOfMessagesIsRefused()
    {
        // nothing is being written any more; the connection is about to be given up for silent
        for (var count = 0; count < Outbox.Limit; count++) Assert.True(outbox.Add(new Key(30, count % 2 == 0)));
        Assert.False(outbox.Add(new Key(31, true)));
        Assert.Equal(Outbox.Limit, Drain().Count);
    }
}
