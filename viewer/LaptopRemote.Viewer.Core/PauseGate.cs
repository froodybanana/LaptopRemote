namespace LaptopRemote.Viewer.Core;

/// <summary>Tells the agent to stop encoding while the window is minimized, once per change.</summary>
public sealed class PauseGate
{
    private bool paused;

    /// <summary>The message to send now that the window is or is not minimized, or null when nothing changed.</summary>
    public Message? Update(bool minimized)
    {
        if (minimized == paused) return null;
        paused = minimized;
        return minimized ? new Pause() : new Resume();
    }

    /// <summary>A new connection starts unpaused on the agent's side.</summary>
    public void Reset() => paused = false;
}
