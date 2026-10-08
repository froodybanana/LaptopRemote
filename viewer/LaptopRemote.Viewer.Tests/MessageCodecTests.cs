using System.Buffers.Binary;
using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class MessageCodecTests
{
    private static string Samples(string kind) => Path.Combine(AppContext.BaseDirectory, "samples", kind);

    [Fact]
    public void ValidSamplesRoundTrip()
    {
        var files = Directory.GetFiles(Samples("valid"), "*.json");
        Assert.Equal(15, files.Length);
        foreach (var file in files)
        {
            var message = MessageCodec.Decode(File.ReadAllBytes(file));
            var frame = MessageCodec.Encode(message);
            Assert.Equal(frame.Length - 4, (int)BinaryPrimitives.ReadUInt32BigEndian(frame));
            Assert.Equal(message, MessageCodec.Decode(frame.AsSpan(4)));
        }
    }

    [Fact]
    public void ValidSamplesDecodeToTheRightTypes()
    {
        Message Load(string name) => MessageCodec.Decode(File.ReadAllBytes(Path.Combine(Samples("valid"), name)));
        Assert.Equal(new Hello(1, 1600, 900, 1.25, 47801, "0123456789abcdef0123456789abcdef"), Load("hello.json"));
        Assert.Equal(new Welcome(1, 47802), Load("welcome.json"));
        Assert.Equal(new Resize(1280, 720, 1), Load("resize.json"));
        Assert.Equal(new Keyframe(), Load("keyframe.json"));
        Assert.Equal(new Heartbeat(), Load("heartbeat.json"));
        Assert.Equal(new Goodbye(), Load("goodbye.json"));
        Assert.Equal(new Error("encoder failed"), Load("error.json"));
        Assert.Equal(new Pause(), Load("pause.json"));
        Assert.Equal(new Resume(), Load("resume.json"));
        Assert.Equal(new MouseMove(640, 360), Load("mouse_move.json"));
        Assert.Equal(new MouseButton("left", true), Load("mouse_button.json"));
        Assert.Equal(new MouseWheel(0, -1.5), Load("mouse_wheel.json"));
        Assert.Equal(new Key(30, false), Load("key.json"));
        Assert.Equal(new Release(), Load("release.json"));
        Assert.Equal(new ClipboardText("blåbær\n\"grød\""), Load("clipboard.json"));
    }

    [Fact]
    public void NonAsciiTextIsNotEscaped()
    {
        // a megabyte of clipboard text must not grow to six on the way
        var frame = MessageCodec.Encode(new ClipboardText("blåbær <b>"));
        Assert.True(frame.AsSpan().IndexOf("blåbær <b>"u8) > 0);
    }

    [Fact]
    public void InvalidSamplesAreRejected()
    {
        var files = Directory.GetFiles(Samples("invalid"), "*.json");
        Assert.Equal(12, files.Length);
        foreach (var file in files)
            Assert.Throws<ProtocolException>(() => MessageCodec.Decode(File.ReadAllBytes(file)));
    }

    [Fact]
    public void BadJsonIsRejected() =>
        Assert.Throws<ProtocolException>(() => MessageCodec.Decode("{no"u8));
}
