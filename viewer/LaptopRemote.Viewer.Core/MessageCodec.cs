using System.Buffers.Binary;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace LaptopRemote.Viewer.Core;

/// <summary>Control protocol: 4-byte big-endian length + UTF-8 JSON object. See protocol/README.md.</summary>
public static class MessageCodec
{
    public const int Version = 1;
    public const int MaxFrame = 2 * 1024 * 1024;

    // the default escapes everything outside ASCII, and clipboard text would grow up to sixfold
    private static readonly JsonWriterOptions Plain = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    public static byte[] Encode(Message message)
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, Plain))
        {
            writer.WriteStartObject();
            switch (message)
            {
                case Hello hello:
                    writer.WriteString("type", "hello");
                    writer.WriteNumber("version", hello.Version);
                    writer.WriteNumber("width", hello.Width);
                    writer.WriteNumber("height", hello.Height);
                    writer.WriteNumber("scale", hello.Scale);
                    writer.WriteNumber("video_port", hello.VideoPort);
                    writer.WriteString("secret", hello.Secret);
                    break;
                case Welcome welcome:
                    writer.WriteString("type", "welcome");
                    writer.WriteNumber("version", welcome.Version);
                    writer.WriteNumber("video_send_port", welcome.VideoSendPort);
                    break;
                case Resize resize:
                    writer.WriteString("type", "resize");
                    writer.WriteNumber("width", resize.Width);
                    writer.WriteNumber("height", resize.Height);
                    writer.WriteNumber("scale", resize.Scale);
                    break;
                case Keyframe: writer.WriteString("type", "keyframe"); break;
                case Pause: writer.WriteString("type", "pause"); break;
                case Resume: writer.WriteString("type", "resume"); break;
                case MouseMove move:
                    writer.WriteString("type", "mouse_move");
                    writer.WriteNumber("x", move.X);
                    writer.WriteNumber("y", move.Y);
                    break;
                case MouseButton button:
                    writer.WriteString("type", "mouse_button");
                    writer.WriteString("button", button.Button);
                    writer.WriteBoolean("down", button.Down);
                    break;
                case MouseWheel wheel:
                    writer.WriteString("type", "mouse_wheel");
                    writer.WriteNumber("dx", wheel.Dx);
                    writer.WriteNumber("dy", wheel.Dy);
                    break;
                case Key key:
                    writer.WriteString("type", "key");
                    writer.WriteNumber("code", key.Code);
                    writer.WriteBoolean("down", key.Down);
                    break;
                case Release: writer.WriteString("type", "release"); break;
                case ClipboardText clipboard:
                    writer.WriteString("type", "clipboard");
                    writer.WriteString("text", clipboard.Text);
                    break;
                case Heartbeat: writer.WriteString("type", "heartbeat"); break;
                case Goodbye: writer.WriteString("type", "goodbye"); break;
                case Error error:
                    writer.WriteString("type", "error");
                    writer.WriteString("message", error.Text);
                    break;
                default: throw new ProtocolException($"cannot encode {message.GetType().Name}");
            }
            writer.WriteEndObject();
        }
        var body = stream.ToArray();
        var frame = new byte[4 + body.Length];
        BinaryPrimitives.WriteUInt32BigEndian(frame, (uint)body.Length);
        body.CopyTo(frame, 4);
        return frame;
    }

    public static Message Decode(ReadOnlySpan<byte> json)
    {
        JsonDocument document;
        try { document = JsonDocument.Parse(json.ToArray()); }
        catch (JsonException error) { throw new ProtocolException($"bad JSON: {error.Message}"); }
        using (document)
        {
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object) throw new ProtocolException("message is not an object");
            if (!root.TryGetProperty("type", out var type) || type.ValueKind != JsonValueKind.String)
                throw new ProtocolException("message has no type");
            return type.GetString() switch
            {
                "hello" => new Hello(Int(root, "version"), Int(root, "width"), Int(root, "height"), Number(root, "scale"), Int(root, "video_port"), Text(root, "secret")),
                "welcome" => new Welcome(Int(root, "version"), Int(root, "video_send_port")),
                "resize" => new Resize(Int(root, "width"), Int(root, "height"), Number(root, "scale")),
                "keyframe" => new Keyframe(),
                "pause" => new Pause(),
                "resume" => new Resume(),
                "mouse_move" => new MouseMove(Int(root, "x"), Int(root, "y")),
                "mouse_button" => new MouseButton(Text(root, "button"), Bool(root, "down")),
                "mouse_wheel" => new MouseWheel(Number(root, "dx"), Number(root, "dy")),
                "key" => new Key(Int(root, "code"), Bool(root, "down")),
                "release" => new Release(),
                "clipboard" => new ClipboardText(Text(root, "text")),
                "heartbeat" => new Heartbeat(),
                "goodbye" => new Goodbye(),
                "error" => new Error(Text(root, "message")),
                var other => throw new ProtocolException($"unknown message type '{other}'"),
            };
        }
    }

    private static int Int(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number : throw new ProtocolException($"{name} is missing or not a whole number");

    private static double Number(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number
            ? value.GetDouble() : throw new ProtocolException($"{name} is missing or not a number");

    private static bool Bool(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean() : throw new ProtocolException($"{name} is missing or not true or false");

    private static string Text(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()! : throw new ProtocolException($"{name} is missing or not text");
}
