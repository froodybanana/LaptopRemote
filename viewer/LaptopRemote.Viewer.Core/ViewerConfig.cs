using System.Text.Json;

namespace LaptopRemote.Viewer.Core;

public sealed record ViewerConfig(string LaptopAddress, int ControlPort, int VideoPort, string? GStreamerBin,
    string Decoder, string? SshTarget, string Secret, string CertificateSha256)
{
    public const int SecretLength = 32;  // the shortest secret accepted; pairing makes one of 64
    public const string DefaultDecoder = "nvh265dec";  // the GStreamer H.265 decoder element; nvh265dec takes 4:4:4
    public const int DefaultControlPort = 47800, DefaultVideoPort = 47801;

    public static string DefaultPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "LaptopRemote", "config.json");

    public static ViewerConfig Parse(string json)
    {
        JsonDocument parsed;
        try { parsed = JsonDocument.Parse(json); }
        catch (JsonException error) { throw new FormatException($"config.json: {error.Message}"); }
        using var document = parsed;
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object) throw new FormatException("config.json: must be an object");
        string? Text(string name) =>
            root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
        var address = Text("laptopAddress") ?? throw new FormatException("config.json: laptopAddress is required");
        int Port(string name, int fallback)
        {
            if (!root.TryGetProperty(name, out var value)) return fallback;
            return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var port) && port is >= 1 and <= 65535
                ? port : throw new FormatException($"config.json: {name} must be a port number");
        }
        // the messages name the key and never repeat its value
        if (Text("secret") is not { Length: >= SecretLength } secret)
            throw new FormatException("config.json: secret is missing or too short; run LaptopRemote.exe --setup");
        if (CertificatePin.Normalize(Text("certificateSha256") ?? "") is not { } pin)
            throw new FormatException("config.json: certificateSha256 must be the 64 hex digits of the laptop's certificate; run LaptopRemote.exe --setup");
        var decoder = Text("decoder") ?? DefaultDecoder;
        if (root.TryGetProperty("decoder", out var decoderValue) && (decoderValue.ValueKind != JsonValueKind.String
            || decoder.Length == 0 || !decoder.All(c => char.IsAsciiLetterOrDigit(c) || c is '_' or '-')))
            throw new FormatException("config.json: decoder must be one GStreamer element name such as nvh265dec");
        var sshTarget = Text("sshTarget");
        if (sshTarget is not null && (sshTarget.Length == 0 || sshTarget.Any(char.IsWhiteSpace)))
            throw new FormatException("config.json: sshTarget must be user@host");
        return new ViewerConfig(address, Port("controlPort", DefaultControlPort), Port("videoPort", DefaultVideoPort),
            Text("gstreamerBin"), decoder, sshTarget, secret, pin);
    }

    /// <summary>Null when there is no text or it does not parse; the setup dialog then starts from nothing.</summary>
    public static ViewerConfig? TryParse(string? json) => TryParse(json, out _);

    /// <summary>Like <see cref="TryParse(string?)"/>; <paramref name="problem"/> says why a text was rejected, null otherwise.</summary>
    public static ViewerConfig? TryParse(string? json, out string? problem)
    {
        problem = null;
        if (json is null) return null;
        try { return Parse(json); }
        catch (FormatException error) { problem = error.Message; return null; }
    }

    public string ToJson()
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("laptopAddress", LaptopAddress);
            writer.WriteNumber("controlPort", ControlPort);
            writer.WriteNumber("videoPort", VideoPort);
            if (GStreamerBin is not null) writer.WriteString("gstreamerBin", GStreamerBin);
            writer.WriteString("decoder", Decoder);
            if (SshTarget is not null) writer.WriteString("sshTarget", SshTarget);
            writer.WriteString("secret", Secret);
            writer.WriteString("certificateSha256", CertificateSha256);
            writer.WriteEndObject();
        }
        return System.Text.Encoding.UTF8.GetString(stream.ToArray()) + "\n";
    }

    public string ResolveGStreamerBin(Func<string, string?> environment)
    {
        if (GStreamerBin is not null) return GStreamerBin;
        if (environment("GSTREAMER_1_0_ROOT_MSVC_X86_64") is { } root) return Path.Combine(root, "bin");
        return Path.Combine(environment("LOCALAPPDATA") ?? "", "Programs", "gstreamer", "1.0", "msvc_x86_64", "bin");
    }

    /// <summary>Without the secret, so it cannot end up in a message or a log by accident.</summary>
    public override string ToString() => $"ViewerConfig {{ LaptopAddress = {LaptopAddress}, ControlPort = {ControlPort}, VideoPort = {VideoPort} }}";
}
