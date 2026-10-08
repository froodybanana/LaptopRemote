using System.Text.Json;
using System.Text.RegularExpressions;

namespace LaptopRemote.Viewer.Core;

public sealed record PairResult(string Secret, string CertificateSha256);

/// <summary>What the setup dialog needs to pair with the agent over ssh. Nothing here runs a process.</summary>
public static class Pairing
{
    /// <summary>Run on the laptop: certificate and secret made if missing, the ssh client's address allowed, agent restarted.</summary>
    public const string RemoteCommand =
        "cd ~/laptopremote/agent && python3 -W ignore -m laptopremote_agent.pair --allow-client " +
        "&& systemctl --user restart laptopremote-agent.service";

    // the target also goes into a cmd.exe line (KeyCopyCommand), so only plain characters pass
    private static readonly Regex UserPattern = new("^[A-Za-z0-9._-]+$"), HostPattern = new("^[A-Za-z0-9._:-]+$");

    /// <summary>user@host, or null when either part is blank, holds anything but plain characters, or would read as an ssh option.</summary>
    public static string? Target(string user, string host)
    {
        user = user.Trim();
        host = host.Trim();
        if (!UserPattern.IsMatch(user) || !HostPattern.IsMatch(host)) return null;
        if (user.StartsWith('-') || host.StartsWith('-')) return null;
        return $"{user}@{host}";
    }

    public static IReadOnlyList<string> SshArguments(string target) =>
        ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", "--", target, RemoteCommand];

    /// <summary>The pair module prints one JSON line; ssh may put a banner before it.</summary>
    public static PairResult ParseResult(string stdout)
    {
        var line = stdout.Split('\n').Select(l => l.Trim()).LastOrDefault(l => l.StartsWith('{'))
            ?? throw new FormatException("the laptop did not answer with a pair result");
        JsonDocument parsed;
        try { parsed = JsonDocument.Parse(line); }
        catch (JsonException) { throw new FormatException("the laptop's pair result is not JSON"); }
        using var document = parsed;
        var root = document.RootElement;
        string? Text(string name) =>
            root.ValueKind == JsonValueKind.Object && root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
                ? value.GetString() : null;
        // the messages name the key and never repeat its value
        if (Text("secret") is not { Length: >= ViewerConfig.SecretLength } secret)
            throw new FormatException("the pair result has no usable secret");
        if (CertificatePin.Normalize(Text("certificateSha256") ?? "") is not { } pin)
            throw new FormatException("the pair result has no certificate fingerprint");
        return new PairResult(secret, pin);
    }

    /// <summary>A config for the paired laptop; ports, GStreamer path and decoder are kept from an existing config.</summary>
    public static ViewerConfig Paired(string laptopAddress, string target, PairResult result, ViewerConfig? existing) =>
        new(laptopAddress.Trim(), existing?.ControlPort ?? ViewerConfig.DefaultControlPort,
            existing?.VideoPort ?? ViewerConfig.DefaultVideoPort, existing?.GStreamerBin,
            existing?.Decoder ?? ViewerConfig.DefaultDecoder, target, result.Secret, result.CertificateSha256);

    public static bool LooksLikeKeyRefused(string stderr) =>
        stderr.Contains("Permission denied", StringComparison.OrdinalIgnoreCase);

    /// <summary>One cmd.exe line: make an ed25519 key if there is none, then append its public half on the laptop.
    /// The user types the laptop password once.</summary>
    public static string KeyCopyCommand(string target) =>
        @"(if not exist ""%USERPROFILE%\.ssh"" mkdir ""%USERPROFILE%\.ssh"") & " +
        @"(if not exist ""%USERPROFILE%\.ssh\id_ed25519"" ssh-keygen -q -t ed25519 -N """" -f ""%USERPROFILE%\.ssh\id_ed25519"") & " +
        $@"type ""%USERPROFILE%\.ssh\id_ed25519.pub"" | ssh -o StrictHostKeyChecking=accept-new {target} " +
        @"""mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"" " +
        "&& echo Key installed. Close this window and press Pair again.";
}
