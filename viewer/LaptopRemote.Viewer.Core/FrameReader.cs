using System.Buffers.Binary;
using System.Runtime.InteropServices;

namespace LaptopRemote.Viewer.Core;

public sealed class FrameReader
{
    private readonly List<byte> buffer = [];

    public IReadOnlyList<Message> Feed(ReadOnlySpan<byte> data)
    {
        buffer.AddRange(data);
        var messages = new List<Message>();
        while (buffer.Count >= 4)
        {
            var span = CollectionsMarshal.AsSpan(buffer);
            var length = BinaryPrimitives.ReadUInt32BigEndian(span);
            if (length > MessageCodec.MaxFrame) throw new ProtocolException("frame too long");
            if (buffer.Count < 4 + (int)length) break;
            messages.Add(MessageCodec.Decode(span.Slice(4, (int)length)));
            buffer.RemoveRange(0, 4 + (int)length);
        }
        return messages;
    }
}
