"""Which clipboard text crosses between the laptop and the viewer, apart from the Wayland calls themselves."""

MAX_BYTES = 1024 * 1024  # of UTF-8; a longer text is not sent and not set, never cut


def open(send):
    """Follows the session's clipboard: send(text) is called when its text changes."""
    from .wayland import WaylandSelection  # needs pywayland and the compositor; nothing else here does
    clipboard = Clipboard(send)
    clipboard.device = WaylandSelection(clipboard.changed, MAX_BYTES, on_replaced=clipboard.replaced)
    return clipboard


class Clipboard:
    """Text only. What the viewer sent is not sent back to it."""

    def __init__(self, send, device=None):
        self.send, self.device = send, device
        self.ours = None  # the text last put on the clipboard for the viewer

    def changed(self, data):
        """The laptop's clipboard holds this text now."""
        if not data or len(data) > MAX_BYTES:
            return
        # our own selection is reported like any other, and again when a clipboard manager takes it over
        if data == self.ours:
            return
        text = data.decode("utf-8", "replace")
        if len(text.encode()) > MAX_BYTES:
            return
        self.ours = None
        self.send(text)

    def replaced(self):
        """Something else was copied on the laptop in place of the viewer's text, text or not."""
        self.ours = None  # the same text copied on the laptop from now on is news for the viewer

    def set(self, text):
        """The viewer's clipboard text, to be pasted on the laptop."""
        data = text.encode("utf-8", "replace")  # half a surrogate pair becomes "?"
        if not data or len(data) > MAX_BYTES:
            return
        self.ours = data
        self.device.set(data)

    def close(self):
        self.device.close()
