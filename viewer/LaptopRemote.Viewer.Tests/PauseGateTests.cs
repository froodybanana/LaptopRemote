using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class PauseGateTests
{
    [Fact]
    public void FirstUpdateNotMinimizedSendsNothing() =>
        Assert.Null(new PauseGate().Update(minimized: false));

    [Fact]
    public void MinimizeSendsPauseOnce()
    {
        var gate = new PauseGate();
        Assert.Equal(new Pause(), gate.Update(minimized: true));
        Assert.Null(gate.Update(minimized: true));
    }

    [Fact]
    public void RestoreSendsResumeOnce()
    {
        var gate = new PauseGate();
        gate.Update(minimized: true);
        Assert.Equal(new Resume(), gate.Update(minimized: false));
        Assert.Null(gate.Update(minimized: false));
    }

    [Fact]
    public void ResetWhileMinimizedSendsPauseAgain()
    {
        // a new connection knows nothing of the old one's pause
        var gate = new PauseGate();
        gate.Update(minimized: true);
        gate.Reset();
        Assert.Equal(new Pause(), gate.Update(minimized: true));
    }

    [Fact]
    public void ResetWhileRestoredSendsNothing()
    {
        var gate = new PauseGate();
        gate.Update(minimized: true);
        gate.Reset();
        Assert.Null(gate.Update(minimized: false));
    }
}
