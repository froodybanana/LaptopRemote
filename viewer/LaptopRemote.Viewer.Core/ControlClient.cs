using System.Collections.Concurrent;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;

namespace LaptopRemote.Viewer.Core;

/// <summary>
/// The control connection, always under TLS. One background thread reads and one writes; the UI thread polls
/// TryRead and calls Send, which never waits for the laptop.
/// </summary>
public sealed class ControlClient : IDisposable
{
    private static readonly TimeSpan HandshakeTime = TimeSpan.FromSeconds(3), DrainTime = TimeSpan.FromMilliseconds(500);

    private readonly TcpClient client;
    private readonly SslStream stream;
    private readonly ConcurrentQueue<Message> inbox = new();
    private readonly Outbox outbox = new();
    private readonly Thread writer;
    private volatile bool closed;

    public bool Closed => closed;

    /// <summary>The laptop's IP address as text, also when the config names it by host name.</summary>
    public string RemoteAddress { get; }

    private ControlClient(TcpClient client, SslStream stream)
    {
        this.client = client;
        this.stream = stream;
        RemoteAddress = ((IPEndPoint)client.Client.RemoteEndPoint!).Address.MapToIPv4().ToString();
        new Thread(ReadLoop) { IsBackground = true, Name = "control-read" }.Start();
        writer = new Thread(WriteLoop) { IsBackground = true, Name = "control-write" };
        writer.Start();
    }

    /// <summary>
    /// Connects and does the TLS handshake. The laptop's certificate is self-signed, so the usual checks say
    /// nothing; it is accepted only when its SHA-256 is <paramref name="pin"/>. WrongCertificate tells a laptop
    /// that answered with another certificate from one that did not answer.
    /// </summary>
    public static async Task<(ControlClient? Client, bool WrongCertificate)> ConnectAsync(
        string address, int port, string pin, TimeSpan timeout)
    {
        var client = new TcpClient { NoDelay = true };
        SslStream? stream = null;
        var wrongCertificate = false;
        try
        {
            using (var cancel = new CancellationTokenSource(timeout))
                await client.ConnectAsync(address, port, cancel.Token);
            stream = new SslStream(client.GetStream(), leaveInnerStreamOpen: false);
            using var handshake = new CancellationTokenSource(HandshakeTime);
            await stream.AuthenticateAsClientAsync(new SslClientAuthenticationOptions
            {
                TargetHost = address,
                CertificateRevocationCheckMode = X509RevocationMode.NoCheck,
                RemoteCertificateValidationCallback = (_, certificate, _, _) =>
                {
                    var matches = certificate is not null && CertificatePin.Matches(pin, certificate.GetRawCertData());
                    wrongCertificate = !matches;
                    return matches;
                },
            }, handshake.Token);
            return (new ControlClient(client, stream), false);
        }
        catch (Exception error) when (error is SocketException or IOException or AuthenticationException
                                          or OperationCanceledException or ObjectDisposedException)
        {
            stream?.Dispose();
            client.Dispose();
            return (null, wrongCertificate);
        }
    }

    /// <summary>
    /// Queues the message for the writer thread. It is called on the UI thread and inside the keyboard hook,
    /// where waiting for a laptop that has stopped reading would freeze typing on the whole PC.
    /// </summary>
    public void Send(Message message)
    {
        if (closed) return;
        if (!outbox.Add(message)) closed = true;  // nothing has been written for thousands of messages
    }

    public bool TryRead(out Message message) => inbox.TryDequeue(out message!);

    private void WriteLoop()
    {
        try
        {
            while (outbox.Take(out var message)) stream.Write(MessageCodec.Encode(message));
        }
        catch (Exception error) when (error is IOException or ObjectDisposedException or InvalidOperationException) { closed = true; }
    }

    private void ReadLoop()
    {
        var reader = new FrameReader();
        var buffer = new byte[65536];
        try
        {
            while (true)
            {
                var count = stream.Read(buffer);
                if (count == 0) break;
                foreach (var message in reader.Feed(buffer.AsSpan(0, count)))
                    inbox.Enqueue(message);
            }
        }
        catch (Exception error) when (error is IOException or ObjectDisposedException or ProtocolException or InvalidOperationException) { }
        closed = true;
    }

    public void Dispose()
    {
        closed = true;
        // what is queued still leaves, a goodbye above all; a laptop that has stopped reading is not waited for
        outbox.Complete();
        writer.Join(DrainTime);
        stream.Dispose();
        client.Dispose();
    }
}
