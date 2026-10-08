using System.Text;

namespace LaptopRemote.Viewer.Core;

/// <summary>
/// Which clipboard text crosses between Windows and the laptop. Text only; on the wire line ends are LF,
/// in Windows CRLF. A text that came from the laptop is not sent back to it.
/// </summary>
public sealed class ClipboardSync
{
    /// <summary>Of UTF-8. A longer text is not sent and not set, never cut.</summary>
    public const int MaxBytes = 1024 * 1024;

    private string? shared;  // the text that last crossed, either way, as it is on the wire
    private bool sent;       // it went from here to the laptop

    /// <summary>The laptop's clipboard text arrived. Gives what to put on the Windows clipboard, or null for nothing.</summary>
    public string? Received(string text)
    {
        if (text.Length == 0 || Encoding.UTF8.GetByteCount(text) > MaxBytes) return null;
        shared = ToLf(text);
        sent = false;
        return shared.Replace("\n", "\r\n");
    }

    /// <summary>
    /// The window gained the focus with this text on the Windows clipboard (null for none).
    /// Gives the message for the laptop, or null when there is nothing new to send.
    /// <paramref name="copiedAgain"/>: something was copied in Windows since the last text crossed; then the
    /// same text goes again, because the laptop may hold something by now that never crosses, an image say.
    /// </summary>
    public ClipboardText? ToSend(string? windowsText, bool copiedAgain = false)
    {
        // a CRLF is two characters here and one byte there, so only twice the limit is surely too long
        if (string.IsNullOrEmpty(windowsText) || windowsText.Length > 2 * MaxBytes) return null;
        var bytes = Encoding.UTF8.GetBytes(ToLf(windowsText));
        if (bytes.Length > MaxBytes) return null;
        var text = Encoding.UTF8.GetString(bytes);  // through UTF-8: half a surrogate pair cannot be written as JSON
        if (text == shared && !copiedAgain) return null;
        var message = new ClipboardText(text);
        // what JSON has to escape takes up to six bytes a character
        if (MessageCodec.Encode(message).Length - 4 > MessageCodec.MaxFrame) return null;
        shared = text;
        sent = true;
        return message;
    }

    /// <summary>
    /// A new session: the laptop held a text sent to it only as long as the session that put it there,
    /// so that one may go again. A text that came from the laptop is still its own.
    /// </summary>
    public void SessionStarted()
    {
        if (sent) shared = null;
    }

    private static string ToLf(string text) => text.Replace("\r\n", "\n");
}
