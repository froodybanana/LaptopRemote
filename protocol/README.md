# LaptopRemote control protocol, version 1

One TCP connection, viewer to agent, under TLS 1.2 or newer. The agent presents its self-signed
certificate; the viewer goes on only if the certificate's SHA-256 equals the pin in its config.
The agent starts a session only for a `hello` whose `secret` equals the one in its own config;
any other `hello` is answered with `error` and the connection is closed, and every other message
before a good `hello` is ignored.

Each message is a 4-byte big-endian length followed by
that many bytes of UTF-8 JSON: one object with a `type` string. A frame longer than 2 MiB, an
unknown type, a missing field or a field of the wrong kind is a protocol error and closes the
connection. Extra fields are ignored.

| type      | direction | fields                                                           |
|-----------|-----------|------------------------------------------------------------------|
| hello     | viewer →  | version int, width int, height int, scale number, video_port int, secret string |
| welcome   | ← agent   | version int, video_send_port int                                 |
| resize    | viewer →  | width int, height int, scale number                              |
| keyframe  | viewer →  | none; asks for a keyframe now                                    |
| pause     | viewer →  | none; window minimized: stop encoding, keep the session          |
| resume    | viewer →  | none; start encoding again, the first frame is a keyframe        |
| mouse_move | viewer → | x int, y int; pointer position in pixels of the size last sent   |
| mouse_button | viewer → | button string (`left`, `right`, `middle`, `back`, `forward`), down bool |
| mouse_wheel | viewer → | dx number, dy number; wheel notches, positive is right and down |
| key       | viewer →  | code int (Linux evdev key code), down bool                       |
| release   | viewer →  | none; every key and button still held is let go                  |
| clipboard | both      | text string; the whole clipboard text, line ends as LF           |
| heartbeat | both      | none; sent every second                                          |
| goodbye   | both      | none; orderly end                                                |
| error     | ← agent   | message string                                                   |

Sizes are physical pixels of the viewer's video area. `scale` is the PC monitor's scale factor.
The viewer sends a held key or button down once, never as a repeat. A button name the agent does
not know, a key code outside 1 to 767 and a position outside the size are not protocol errors: the
first two are ignored, the position is moved to the nearest edge. The agent lets go of everything
held on `release`, on `pause` and when the session ends.
The agent sends `clipboard` when the laptop's clipboard text changes during a session, the viewer
when its window gains the focus; neither sends back a text it was sent. A `clipboard` text that is
empty or longer than 1 MiB of UTF-8 is ignored by the receiver and is not a protocol error. JSON is
written without escaping characters outside ASCII, so text keeps its size; a text that still does
not fit a frame is not sent.
`samples/valid` and `samples/invalid` are read by both test suites.
