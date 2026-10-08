using System.Security.Cryptography;

namespace LaptopRemote.Viewer.Core;

/// <summary>The laptop's certificate is self-signed; the viewer trusts exactly the one whose SHA-256 is in its config.</summary>
public static class CertificatePin
{
    /// <summary>64 lowercase hex digits, or null when the text is not a SHA-256. Colons and white space are dropped.</summary>
    public static string? Normalize(string text)
    {
        var digits = string.Concat(text.Where(c => c != ':' && !char.IsWhiteSpace(c))).ToLowerInvariant();
        return digits.Length == 64 && digits.All(char.IsAsciiHexDigit) ? digits : null;
    }

    public static bool Matches(string pin, ReadOnlySpan<byte> certificate) =>
        Normalize(pin) is { } wanted && wanted == Convert.ToHexStringLower(SHA256.HashData(certificate));
}
