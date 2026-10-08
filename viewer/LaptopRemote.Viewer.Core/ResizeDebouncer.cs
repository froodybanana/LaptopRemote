namespace LaptopRemote.Viewer.Core;

/// <summary>Waits for a resize drag to settle, then reports the new size once.</summary>
public sealed class ResizeDebouncer(TimeSpan quiet)
{
    private (int Width, int Height) sent, pending;
    private TimeSpan changedAt;
    private bool dirty;

    /// <summary>The size the laptop was last told; mouse positions are pixels of it.</summary>
    public (int Width, int Height) Sent => sent;

    public void MarkSent(int width, int height) => sent = pending = SizeRules.Normalize(width, height);

    public void Changed(int width, int height, TimeSpan now)
    {
        if (width <= 0 || height <= 0) return;  // minimized: keep the laptop's output as it is
        pending = SizeRules.Normalize(width, height);
        changedAt = now;
        dirty = true;
    }

    public (int Width, int Height)? Poll(TimeSpan now)
    {
        if (!dirty || now - changedAt < quiet) return null;
        dirty = false;
        if (pending == sent) return null;
        sent = pending;
        return pending;
    }
}
