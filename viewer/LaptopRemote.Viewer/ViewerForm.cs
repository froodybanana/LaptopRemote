using System.Diagnostics;
using System.Runtime.InteropServices;
using LaptopRemote.Viewer.Core;
using LaptopRemote.Viewer.Native;
using Microsoft.Win32;

namespace LaptopRemote.Viewer;

internal sealed class ViewerForm : Form
{
    private static readonly TimeSpan Second = TimeSpan.FromSeconds(1), Silence = TimeSpan.FromSeconds(5),
        RetryEvery = TimeSpan.FromSeconds(2), RetryAfterError = TimeSpan.FromSeconds(10),
        ResizeHold = TimeSpan.FromMilliseconds(1500);

    public const string Title = "LaptopRemote";
    private const string WaitingText = "Waiting for laptop…";

    private readonly ViewerConfig config;
    private readonly Panel video = new() { Dock = DockStyle.Fill, BackColor = Color.Black };
    private readonly Label status = new()
    {
        Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, Text = WaitingText,
        ForeColor = Color.Gainsboro, BackColor = Color.FromArgb(24, 24, 24), Font = new Font("Segoe UI", 14),
    };
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 50 };
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private readonly ResizeDebouncer debouncer = new(TimeSpan.FromMilliseconds(150));
    private readonly KeyframeRequester keyframes = new(TimeSpan.FromMilliseconds(250));
    private readonly PauseGate pauseGate = new();
    private readonly HeldInput held = new();
    private readonly ClipboardSync clipboardSync = new();
    private uint clipboardSeen;  // the Windows clipboard's sequence number when a text last crossed
    private bool clipboardDue;  // the window gained the focus and the laptop has not been given the clipboard since
    private readonly KeyboardGrab? grab;
    private readonly bool remembersPlacement;
    private bool wasMaximized;
    private VideoPipeline? pipeline;
    private ControlClient? control;
    private bool connecting;
    private int videoSendPort;
    private ulong lostSeen;
    private TimeSpan nextConnect, lastHeard, lastBeat, lastPunch;
    private Size lastSize = new(1280, 720);  // the video area while it was last visible; a minimized window reports 0x0

    public ViewerForm(ViewerConfig config, string? testPipeline)
    {
        this.config = config;
        Text = Title;
        ClientSize = new Size(1280, 720);
        Controls.Add(video);
        Controls.Add(status);
        if (testPipeline is not null)
        {
            Text = $"{Title} (test pipeline)";
            Shown += (_, _) => ShowVideo(testPipeline);
            return;
        }
        remembersPlacement = true;
        RestorePlacement();
        Resize += (_, _) =>
        {
            if (WindowState != FormWindowState.Minimized) wasMaximized = WindowState == FormWindowState.Maximized;
        };
        status.BringToFront();  // both controls fill the window; the label is on top until there is video
        video.Resize += (_, _) =>
        {
            if (video.ClientSize is { Width: > 0, Height: > 0 } size) lastSize = size;
            debouncer.Changed(video.ClientSize.Width, video.ClientSize.Height, clock.Elapsed);
        };
        // the keyboard belongs to the laptop while this window has the focus, the mouse while it is over the picture
        grab = new KeyboardGrab(OnKey);
        Activated += (_, _) =>
        {
            grab.Install();
            clipboardDue = true;  // read in Tick: another program may hold the clipboard and make this wait
        };
        Deactivate += (_, _) =>
        {
            clipboardDue = false;
            grab.Remove();
            ReleaseInput();
        };
        SystemEvents.SessionSwitch += OnSessionSwitch;
        video.MouseMove += (_, e) => SendPointer(e.Location);
        video.MouseDown += (_, e) => SendButton(e, down: true);
        video.MouseUp += (_, e) => SendButton(e, down: false);
        timer.Tick += (_, _) => Tick(clock.Elapsed);
        timer.Start();
    }

    /// <summary>A session is running: there is a laptop to give input to.</summary>
    private bool Live => control is not null && pipeline is not null;

    /// <summary>
    /// The user is working in this window. Activated alone does not say so: a window started while another
    /// program keeps the foreground, a full-screen game for one, is activated without getting the keyboard.
    /// </summary>
    private bool InFront => IsHandleCreated && User32.GetForegroundWindow() == Handle;

    /// <summary>Called by the keyboard hook for every key on the PC while this window is active.</summary>
    private bool OnKey(int scanCode, bool extended, int virtualKey, bool down)
    {
        if (!Live || KeyMap.ToLinux(scanCode, extended, virtualKey) is not { } code) return false;
        // inside the hook the key state is still the one from before this event
        switch (held.Key(code, down, User32.IsKeyDown(virtualKey), InFront))
        {
            case KeyVerdict.Send:
                control!.Send(new Key(code, down));
                return true;
            case KeyVerdict.Keep:
                return true;
            case KeyVerdict.ReleaseAllAndPass:
                control!.Send(new Release());
                return false;
            default:
                return false;
        }
    }

    private bool SendPointer(Point at)
    {
        if (!Live) return false;
        var area = video.ClientSize;
        var (width, height) = debouncer.Sent;
        if (PointerMap.ToStream(at.X, at.Y, area.Width, area.Height, width, height) is not { } position) return false;
        control!.Send(new MouseMove(position.X, position.Y));
        return true;
    }

    private void SendButton(MouseEventArgs e, bool down)
    {
        var name = e.Button switch
        {
            MouseButtons.Left => "left",
            MouseButtons.Right => "right",
            MouseButtons.Middle => "middle",
            MouseButtons.XButton1 => "back",
            MouseButtons.XButton2 => "forward",
            _ => null,
        };
        // the position first: the click that brings the window to the front has no mouse move before it
        if (name is null || !SendPointer(e.Location)) return;
        if (down ? held.ButtonDown(name) : held.ButtonUp(name)) control!.Send(new MouseButton(name, down));
    }

    /// <summary>The focus is going elsewhere: nothing may stay held down on the laptop.</summary>
    private void ReleaseInput()
    {
        held.Clear();
        if (Live) control!.Send(new Release());
    }

    /// <summary>What the PC has copied goes to the laptop when the window gains the focus, not on every copy.</summary>
    private void SendClipboard()
    {
        string? text;
        try { text = Clipboard.ContainsText() ? Clipboard.GetText() : null; }
        catch (ExternalException) { return; }  // another program holds the clipboard open
        var number = User32.GetClipboardSequenceNumber();
        if (clipboardSync.ToSend(text, copiedAgain: number != clipboardSeen) is { } message) control!.Send(message);
        clipboardSeen = number;
    }

    private void SetClipboard(string? text)
    {
        if (text is null) return;
        try { Clipboard.SetDataObject(text, copy: true, retryTimes: 5, retryDelay: 20); }
        catch (ExternalException) { }
        clipboardSeen = User32.GetClipboardSequenceNumber();
    }

    // locking the PC takes the keyboard away without a Deactivate
    private void OnSessionSwitch(object sender, SessionSwitchEventArgs e)
    {
        if (IsHandleCreated && !IsDisposed) BeginInvoke(ReleaseInput);
    }

    protected override void WndProc(ref System.Windows.Forms.Message m)
    {
        // the wheel goes to the window with the focus, which is this one, or comes up from the video panel
        if (m.Msg is User32.WmMouseWheel or User32.WmMouseHWheel && Live)
        {
            var notches = (short)((long)m.WParam >> 16) / 120.0;
            // Windows counts up and right as positive, the protocol down and right
            control!.Send(m.Msg == User32.WmMouseWheel ? new MouseWheel(0, -notches) : new MouseWheel(notches, 0));
            m.Result = IntPtr.Zero;
            return;
        }
        base.WndProc(ref m);
    }

    private double DpiScale => DeviceDpi / 96.0;

    /// <summary>Reopens the window where it was left, unless that place is no longer on a monitor.</summary>
    private void RestorePlacement()
    {
        WindowPlacement? saved;
        try { saved = WindowPlacement.Parse(File.ReadAllText(WindowPlacement.DefaultPath)); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return; }
        var workAreas = Screen.AllScreens.Select(screen => screen.WorkingArea)
            .Select(area => (area.X, area.Y, area.Width, area.Height));
        if (saved is null || !saved.FitsAny(workAreas)) return;
        StartPosition = FormStartPosition.Manual;
        Bounds = new Rectangle(saved.X, saved.Y, saved.Width, saved.Height);
        if (saved.Maximized) WindowState = FormWindowState.Maximized;
        wasMaximized = saved.Maximized;
    }

    private void SavePlacement()
    {
        var bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
        var placement = new WindowPlacement(bounds.X, bounds.Y, bounds.Width, bounds.Height, wasMaximized);
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(WindowPlacement.DefaultPath)!);
            File.WriteAllText(WindowPlacement.DefaultPath, placement.ToJson());
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
    }

    private void ShowVideo(string description)
    {
        var old = pipeline;
        pipeline = null;  // cleared first in case stopping the sink pumps messages and Tick runs
        old?.Dispose();
        pipeline = new VideoPipeline(description, video.Handle);
        pipeline.Play();
        status.Hide();
    }

    private void Wait(string text, TimeSpan now, TimeSpan? retry = null)
    {
        control?.Dispose();
        control = null;
        held.Clear();  // the laptop lets go of everything when a session ends
        var old = pipeline;
        pipeline = null;
        old?.Dispose();
        status.Text = text;
        status.Show();
        status.BringToFront();
        nextConnect = now + (retry ?? RetryEvery);
    }

    private async void Connect()
    {
        connecting = true;
        var (client, wrongCertificate) = await ControlClient.ConnectAsync(
            config.LaptopAddress, config.ControlPort, config.CertificateSha256, Second);
        connecting = false;
        var now = clock.Elapsed;
        if (client is null || IsDisposed)
        {
            client?.Dispose();
            // nothing was sent to whoever answered; said in the window because waiting would never end
            if (wrongCertificate && !IsDisposed)
                Wait("The laptop's certificate is not the one in config.json. Run LaptopRemote.exe --setup again.", now, RetryAfterError);
            else
                nextConnect = now + RetryEvery;
            return;
        }
        control = client;
        pauseGate.Reset();
        lastHeard = lastBeat = now;
        var (width, height) = SizeRules.Normalize(lastSize.Width, lastSize.Height);
        debouncer.MarkSent(width, height);
        control.Send(new Hello(MessageCodec.Version, width, height, DpiScale, config.VideoPort, config.Secret));
    }

    private void Tick(TimeSpan now)
    {
        if (control is null)
        {
            if (!connecting && now >= nextConnect) Connect();
            return;
        }
        while (control.TryRead(out var message))
        {
            lastHeard = now;
            switch (message)
            {
                case Welcome welcome:
                    videoSendPort = welcome.VideoSendPort;
                    // force-aspect-ratio=false: during a resize drag the old picture is stretched to the window
                    try
                    {
                        ShowVideo($"udpsrc name=src port={config.VideoPort} " +
                                  "caps=\"application/x-rtp,media=video,encoding-name=H265,clock-rate=90000,payload=96\" " +
                                  "! rtpjitterbuffer name=jitter latency=10 ! rtph265depay ! h265parse " +
                                  $"! {config.Decoder} ! d3d11videosink name=sink sync=false force-aspect-ratio=false " +
                                  "enable-navigation-events=false");
                    }
                    catch (InvalidOperationException problem)
                    {
                        Wait($"Video problem: {problem.Message}", now);
                        return;
                    }
                    lostSeen = 0;
                    lastPunch = TimeSpan.Zero;
                    keyframes.NeedPicture();
                    clipboardSync.SessionStarted();
                    // a session that starts under a focused window is given the clipboard like a focus gained
                    if (InFront) clipboardDue = true;
                    break;
                case ClipboardText clipboard:
                    SetClipboard(clipboardSync.Received(clipboard.Text));
                    break;
                case Error error:
                    // the agent has already retried; coming straight back would flip the laptop's panel every few seconds
                    Wait($"Laptop reported: {error.Text}", now, RetryAfterError);
                    return;
                case Goodbye:
                    Wait(WaitingText, now);
                    return;
            }
        }
        if (control.Closed || now - lastHeard > Silence)
        {
            Wait(WaitingText, now);
            return;
        }
        if (now - lastBeat >= Second)
        {
            control.Send(new Heartbeat());
            lastBeat = now;
        }
        if (clipboardDue && Live && InFront)
        {
            clipboardDue = false;
            SendClipboard();
        }
        var minimized = WindowState == FormWindowState.Minimized;
        if (pauseGate.Update(minimized) is { } change)
        {
            control.Send(change);
            if (change is Resume) keyframes.NeedPicture();
        }
        if (debouncer.Poll(now) is { } size)
        {
            control.Send(new Resize(size.Width, size.Height, DpiScale));
            // the agent restarts its stream; frames of the old one must not count as the new picture
            keyframes.NeedPicture(now, ResizeHold);
        }
        if (pipeline is not null)
        {
            // the sink puts a window of its own into the panel, some time after it starts; disabled, it lets
            // the mouse through to the panel
            User32.DisableChildren(video.Handle);
            if (lastPunch == TimeSpan.Zero || now - lastPunch >= Second)
            {
                pipeline.Punch(control.RemoteAddress, videoSendPort);
                lastPunch = now;
            }
            if (pipeline.PollError() is { } problem)
            {
                Wait($"Video problem: {problem}", now);
                return;
            }
            if (pipeline.TakeFrameArrived()) keyframes.FrameArrived(now);
            var lost = pipeline.LostPackets();
            if (lost > lostSeen)
            {
                lostSeen = lost;
                keyframes.NeedPicture();
            }
        }
        // while minimized the agent sends nothing, so there is no picture to ask for
        if (!minimized && keyframes.Poll(now)) control.Send(new Keyframe());
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        timer.Stop();
        SystemEvents.SessionSwitch -= OnSessionSwitch;
        grab?.Dispose();
        if (remembersPlacement) SavePlacement();
        control?.Send(new Goodbye());
        control?.Dispose();
        control = null;
        pipeline?.Dispose();
        pipeline = null;
        base.OnFormClosing(e);
    }
}
