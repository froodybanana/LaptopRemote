namespace LaptopRemote.Viewer.Core;

/// <summary>While there is no decodable picture, says when to ask the agent for a keyframe again.</summary>
public sealed class KeyframeRequester(TimeSpan interval)
{
    private bool needed;
    private TimeSpan? lastAsked;
    private TimeSpan holdUntil;

    public void NeedPicture()
    {
        needed = true;
        lastAsked = null;
        holdUntil = TimeSpan.Zero;
    }

    /// <summary>Keeps asking for at least <paramref name="hold"/>: after a resize, frames of the old stream still arrive for a moment.</summary>
    public void NeedPicture(TimeSpan now, TimeSpan hold)
    {
        NeedPicture();
        holdUntil = now + hold;
    }

    public void FrameArrived(TimeSpan now)
    {
        if (now >= holdUntil) needed = false;
    }

    public bool Poll(TimeSpan now)
    {
        if (!needed || (lastAsked is { } asked && now - asked < interval)) return false;
        lastAsked = now;
        return true;
    }
}
