namespace LaptopRemote.Viewer.Core;

/// <summary>
/// Messages waiting to be written to the laptop. Whoever adds never waits; one thread takes and writes.
/// </summary>
public sealed class Outbox
{
    /// <summary>More waiting messages than this means nothing is being written any more.</summary>
    public const int Limit = 4096;

    private readonly LinkedList<Message> queue = new();
    private bool completed;

    /// <summary>False when the message was not taken in: the outbox is completed or full.</summary>
    public bool Add(Message message)
    {
        lock (queue)
        {
            if (completed) return false;
            // a slow connection gets where the pointer is now, not everywhere it has been; only a position
            // directly behind another is dropped, so a click still happens where the pointer was
            if (message is MouseMove && queue.Last?.Value is MouseMove) queue.RemoveLast();
            else if (queue.Count >= Limit) return false;
            queue.AddLast(message);
            Monitor.Pulse(queue);
            return true;
        }
    }

    /// <summary>Waits for the next message. False once the outbox is completed and empty.</summary>
    public bool Take(out Message message)
    {
        lock (queue)
        {
            while (queue.Count == 0 && !completed) Monitor.Wait(queue);
            if (queue.First is not { } first)
            {
                message = null!;
                return false;
            }
            message = first.Value;
            queue.RemoveFirst();
            return true;
        }
    }

    /// <summary>Nothing more is accepted; what is waiting can still be taken.</summary>
    public void Complete()
    {
        lock (queue)
        {
            completed = true;
            Monitor.PulseAll(queue);
        }
    }
}
