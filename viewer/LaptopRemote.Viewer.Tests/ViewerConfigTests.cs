using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class ViewerConfigTests
{
    private const string Secret = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private const string Pin = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    private static string Json(string extra = "", string? secret = Secret, string? pin = Pin) =>
        "{ \"laptopAddress\": \"192.0.2.20\""
        + (secret is null ? "" : $", \"secret\": \"{secret}\"")
        + (pin is null ? "" : $", \"certificateSha256\": \"{pin}\"")
        + extra + " }";

    [Fact]
    public void ParsesWithDefaults() =>
        Assert.Equal(new ViewerConfig("192.0.2.20", 47800, 47801, null, "nvh265dec", null, Secret, Pin), ViewerConfig.Parse(Json()));

    [Fact]
    public void PinIsStoredNormalized() =>
        Assert.Equal(Pin, ViewerConfig.Parse(Json(pin: Pin.ToUpperInvariant().Insert(2, ":"))).CertificateSha256);

    [Fact]
    public void MissingAddressThrows() =>
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(
            $$"""{ "controlPort": 1, "secret": "{{Secret}}", "certificateSha256": "{{Pin}}" }"""));

    [Fact]
    public void SecretAndPinAreRequired()
    {
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(secret: null)));
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(secret: new string('k', 31))));
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(pin: null)));
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(pin: "zz")));
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(", \"secret\": 5", secret: null)));
    }

    [Fact]
    public void ErrorsAndTextNeverShowTheSecret()
    {
        var error = Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(pin: "zz")));
        Assert.DoesNotContain(Secret, error.Message);
        Assert.Contains("--setup", error.Message);
        var shortSecret = new string('k', 31);
        error = Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(secret: shortSecret)));
        Assert.DoesNotContain(shortSecret, error.Message);
        Assert.DoesNotContain(Secret, ViewerConfig.Parse(Json()).ToString());
    }

    [Theory]
    [InlineData("{ not json")]
    [InlineData(", \"controlPort\": 70000")]
    [InlineData(", \"videoPort\": \"x\"")]
    public void BrokenConfigThrowsFormatException(string text) =>
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(text.StartsWith(',') ? Json(text) : text));

    [Fact]
    public void GStreamerBinPrefersConfigThenEnvironmentThenDefault()
    {
        string? Env(string name) => name == "GSTREAMER_1_0_ROOT_MSVC_X86_64" ? @"D:\gst" : name == "LOCALAPPDATA" ? @"C:\L" : null;
        Assert.Equal(@"E:\bin", new ViewerConfig("a", 1, 2, @"E:\bin", "nvh265dec", null, "", "").ResolveGStreamerBin(Env));
        Assert.Equal(@"D:\gst\bin", new ViewerConfig("a", 1, 2, null, "nvh265dec", null, "", "").ResolveGStreamerBin(Env));
        Assert.Equal(@"C:\L\Programs\gstreamer\1.0\msvc_x86_64\bin",
            new ViewerConfig("a", 1, 2, null, "nvh265dec", null, "", "").ResolveGStreamerBin(name => name == "LOCALAPPDATA" ? @"C:\L" : null));
    }

    [Fact]
    public void DecoderAndSshTargetParse()
    {
        var parsed = ViewerConfig.Parse(Json(", \"decoder\": \"d3d11h265dec\", \"sshTarget\": \"me@laptop\""));
        Assert.Equal("d3d11h265dec", parsed.Decoder);
        Assert.Equal("me@laptop", parsed.SshTarget);
        Assert.Equal("nvh265dec", ViewerConfig.Parse(Json()).Decoder);
        Assert.Null(ViewerConfig.Parse(Json()).SshTarget);
    }

    [Theory]
    [InlineData(", \"decoder\": \"nvh265dec ! queue\"")]
    [InlineData(", \"decoder\": \"\"")]
    [InlineData(", \"decoder\": 5")]
    [InlineData(", \"sshTarget\": \"me laptop\"")]
    public void DecoderIsOneElementNameAndSshTargetHasNoSpaces(string extra) =>
        Assert.Throws<FormatException>(() => ViewerConfig.Parse(Json(extra)));

    [Fact]
    public void ToJsonRoundTrips()
    {
        var config = new ViewerConfig("192.0.2.20", 1, 2, @"E:\bin", "d3d11h265dec", "me@laptop", Secret, Pin);
        Assert.Equal(config, ViewerConfig.Parse(config.ToJson()));
        var minimal = new ViewerConfig("192.0.2.20", 47800, 47801, null, "nvh265dec", null, Secret, Pin);
        var json = minimal.ToJson();
        Assert.Equal(minimal, ViewerConfig.Parse(json));
        Assert.DoesNotContain("gstreamerBin", json);
        Assert.DoesNotContain("sshTarget", json);
    }

    [Fact]
    public void TryParseIsNullForMissingOrBrokenText()
    {
        Assert.Null(ViewerConfig.TryParse(null));
        Assert.Null(ViewerConfig.TryParse("{ not json"));
        Assert.Null(ViewerConfig.TryParse(Json(secret: null)));
        Assert.NotNull(ViewerConfig.TryParse(Json()));
    }

    [Fact]
    public void TryParseReportsWhyTheTextWasRejected()
    {
        Assert.Null(ViewerConfig.TryParse("{ not json", out var problem));
        Assert.NotNull(problem);
        Assert.Contains("config.json", problem);
        Assert.NotNull(ViewerConfig.TryParse(Json(), out problem));
        Assert.Null(problem);
        Assert.Null(ViewerConfig.TryParse(null, out problem));
        Assert.Null(problem);
    }
}
