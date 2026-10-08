using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class ClipboardSyncTests
{
    private readonly ClipboardSync sync = new();

    [Fact]
    public void WindowsTextIsSent() =>
        Assert.Equal(new ClipboardText("from the PC"), sync.ToSend("from the PC"));

    [Fact]
    public void ReceivedTextIsNotSentBack()
    {
        Assert.Equal("from the laptop", sync.Received("from the laptop"));
        Assert.Null(sync.ToSend("from the laptop"));
    }

    [Fact]
    public void ReceivedTextWithWindowsLineEndsIsNotSentBack()
    {
        // a laptop program may have copied CRLF itself; Windows gets it unchanged and it compares equal
        Assert.Equal("one\r\ntwo", sync.Received("one\r\ntwo"));
        Assert.Null(sync.ToSend("one\r\ntwo"));
    }

    [Fact]
    public void LineEndsAreConvertedBothWays()
    {
        Assert.Equal("one\r\ntwo\r\n", sync.Received("one\ntwo\n"));
        Assert.Null(sync.ToSend("one\r\ntwo\r\n"));
        Assert.Equal(new ClipboardText("three\nfour\rfive"), sync.ToSend("three\r\nfour\rfive"));
    }

    [Fact]
    public void SameTextIsSentOnce()
    {
        Assert.NotNull(sync.ToSend("from the PC"));
        Assert.Null(sync.ToSend("from the PC"));  // the window gained the focus again with nothing new copied
    }

    [Fact]
    public void TextCopiedAgainAfterAnotherCrossedIsSent()
    {
        Assert.NotNull(sync.ToSend("one"));
        Assert.NotNull(sync.Received("two"));
        Assert.Equal(new ClipboardText("one"), sync.ToSend("one"));  // the laptop holds "two" by now
    }

    [Fact]
    public void TheSameTextCopiedAgainIsSent()
    {
        // the laptop may hold an image by now, which never crosses; a new copy on the PC says the text is wanted
        Assert.NotNull(sync.ToSend("one"));
        Assert.Null(sync.ToSend("one", copiedAgain: false));
        Assert.Equal(new ClipboardText("one"), sync.ToSend("one", copiedAgain: true));
    }

    [Fact]
    public void TooLongIsNeitherSentNorSet()
    {
        var most = new string('x', ClipboardSync.MaxBytes);
        Assert.NotNull(sync.ToSend(most));
        Assert.Null(sync.ToSend(most + "x"));
        Assert.Null(sync.ToSend(new string('æ', ClipboardSync.MaxBytes / 2 + 1)));  // counted in bytes of UTF-8
        Assert.NotNull(sync.Received(most));
        Assert.Null(sync.Received(most + "x"));
    }

    [Fact]
    public void ARefusedTextIsNotRemembered()
    {
        Assert.NotNull(sync.Received("one"));
        Assert.Null(sync.Received(new string('x', ClipboardSync.MaxBytes + 1)));
        Assert.Null(sync.ToSend("one"));  // still what both sides hold
    }

    [Fact]
    public void EmptyGivesNothing()
    {
        Assert.Null(sync.ToSend(null));
        Assert.Null(sync.ToSend(""));
        Assert.Null(sync.Received(""));
    }

    [Fact]
    public void LoneSurrogateIsReplaced()
    {
        // half a surrogate pair cannot be written as JSON
        var message = sync.ToSend("a\ud83db");
        Assert.Equal(new ClipboardText("a�b"), message);
        MessageCodec.Encode(message!);
    }

    [Fact]
    public void TextThatDoesNotFitAFrameIsNotSent()
    {
        // control characters take six bytes each in JSON
        Assert.Null(sync.ToSend(new string('\u0001', 400_000)));
        Assert.NotNull(sync.ToSend(new string('\u0001', 1000)));
    }

    [Fact]
    public void ANewSessionGetsTheSentTextAgain()
    {
        // the laptop's clipboard held our text only as long as the session that put it there
        Assert.NotNull(sync.ToSend("from the PC"));
        sync.SessionStarted();
        Assert.NotNull(sync.ToSend("from the PC"));
    }

    [Fact]
    public void ANewSessionDoesNotGetBackWhatItSent()
    {
        Assert.NotNull(sync.Received("from the laptop"));
        sync.SessionStarted();
        Assert.Null(sync.ToSend("from the laptop"));
    }
}
