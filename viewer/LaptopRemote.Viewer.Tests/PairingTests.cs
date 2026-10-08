using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class PairingTests
{
    private const string Secret = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    private const string Pin = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    [Fact]
    public void TargetJoinsUserAndHostAndRefusesBlanks()
    {
        Assert.Equal("me@192.0.2.20", Pairing.Target(" me ", "192.0.2.20 "));
        Assert.Null(Pairing.Target("", "192.0.2.20"));
        Assert.Null(Pairing.Target("me", ""));
        Assert.Null(Pairing.Target("m e", "laptop"));
        Assert.Null(Pairing.Target("me", "-oProxyCommand=x"));
    }

    [Fact]
    public void SshArgumentsAreBatchAndEndWithTheRemoteCommand()
    {
        var args = Pairing.SshArguments("me@laptop");
        Assert.Contains("BatchMode=yes", string.Join(" ", args));
        Assert.Contains("StrictHostKeyChecking=accept-new", string.Join(" ", args));
        Assert.Equal("me@laptop", args[^2]);
        Assert.Equal(Pairing.RemoteCommand, args[^1]);
        Assert.Contains("--allow-client", Pairing.RemoteCommand);
        Assert.Contains("systemctl --user restart laptopremote-agent.service", Pairing.RemoteCommand);
    }

    [Fact]
    public void ParseResultTakesTheJsonLineAndIgnoresBanners()
    {
        var text = $"Welcome to the laptop\r\n{{\"secret\": \"{Secret}\", \"certificateSha256\": \"{Pin.ToUpperInvariant()}\"}}\n";
        Assert.Equal(new PairResult(Secret, Pin), Pairing.ParseResult(text));
    }

    [Theory]
    [InlineData("")]
    [InlineData("not json")]
    [InlineData("{\"secret\": \"short\", \"certificateSha256\": \"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\"}")]
    [InlineData("{\"secret\": \"0123456789abcdef0123456789abcdef\", \"certificateSha256\": \"zz\"}")]
    [InlineData("{\"secret\": \"0123456789abcdef0123456789abcdef\"}")]
    public void ParseResultRejectsWhatIsNotAPairResult(string text)
    {
        var error = Assert.Throws<FormatException>(() => Pairing.ParseResult(text));
        Assert.DoesNotContain("0123456789abcdef", error.Message);
    }

    [Fact]
    public void PairedKeepsPortsAndDecoderOfAnExistingConfig()
    {
        var existing = new ViewerConfig("old", 1, 2, @"E:\bin", "d3d11h265dec", "x@y", "k", "p");
        var paired = Pairing.Paired("192.0.2.20", "me@192.0.2.20", new PairResult(Secret, Pin), existing);
        Assert.Equal(new ViewerConfig("192.0.2.20", 1, 2, @"E:\bin", "d3d11h265dec", "me@192.0.2.20", Secret, Pin), paired);
        var fresh = Pairing.Paired("192.0.2.20", "me@192.0.2.20", new PairResult(Secret, Pin), null);
        Assert.Equal(new ViewerConfig("192.0.2.20", 47800, 47801, null, "nvh265dec", "me@192.0.2.20", Secret, Pin), fresh);
    }

    [Fact]
    public void KeyRefusedIsRecognised()
    {
        Assert.True(Pairing.LooksLikeKeyRefused("me@laptop: Permission denied (publickey,password)."));
        Assert.False(Pairing.LooksLikeKeyRefused("ssh: connect to host laptop port 22: Connection timed out"));
    }

    [Fact]
    public void KeyCopyCommandMakesAKeyIfMissingAndAppendsItOnTheLaptop()
    {
        var command = Pairing.KeyCopyCommand("me@laptop");
        Assert.Contains("ssh-keygen", command);
        Assert.Contains("id_ed25519.pub", command);
        Assert.Contains("me@laptop", command);
        Assert.Contains("authorized_keys", command);
    }

    [Fact]
    public void TargetRefusesShellCharacters()
    {
        Assert.Null(Pairing.Target("me", "lap&top"));
        Assert.Null(Pairing.Target("me", "laptop|x"));
        Assert.Null(Pairing.Target("m\"e", "laptop"));
        Assert.Null(Pairing.Target("me", "%TEMP%"));
        Assert.Equal("me@2001:db8::1", Pairing.Target("me", "2001:db8::1"));
        Assert.Equal("my.user-1@lap_top.local", Pairing.Target("my.user-1", "lap_top.local"));
    }

    [Fact]
    public void KeyCopyCommandParenthesisesEachConditionSoTheChainContinues()
    {
        // in cmd.exe everything after `if <cond>` on the line is the conditional body, & chains included
        var command = Pairing.KeyCopyCommand("me@laptop");
        Assert.DoesNotContain(@""" if not exist", command);
        Assert.Contains(@"(if not exist ""%USERPROFILE%\.ssh"" mkdir ""%USERPROFILE%\.ssh"") & ", command);
        Assert.Contains(@"(if not exist ""%USERPROFILE%\.ssh\id_ed25519"" ssh-keygen", command);
        Assert.Contains(@""") & type ""%USERPROFILE%\.ssh\id_ed25519.pub"" | ssh", command);
    }
}
