namespace LaptopRemote.Viewer.Core;

public abstract record Message;
public sealed record Hello(int Version, int Width, int Height, double Scale, int VideoPort, string Secret) : Message;
public sealed record Welcome(int Version, int VideoSendPort) : Message;
public sealed record Resize(int Width, int Height, double Scale) : Message;
public sealed record Keyframe : Message;
public sealed record Pause : Message;
public sealed record Resume : Message;
public sealed record MouseMove(int X, int Y) : Message;
public sealed record MouseButton(string Button, bool Down) : Message;
public sealed record MouseWheel(double Dx, double Dy) : Message;
public sealed record Key(int Code, bool Down) : Message;
public sealed record Release : Message;
public sealed record ClipboardText(string Text) : Message;
public sealed record Heartbeat : Message;
public sealed record Goodbye : Message;
public sealed record Error(string Text) : Message;

public sealed class ProtocolException(string message) : Exception(message);
