using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class ControlClientTests
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(3);

    private static X509Certificate2 SelfSigned()
    {
        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var request = new CertificateRequest("CN=laptopremote", key, HashAlgorithmName.SHA256);
        using var made = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));
        // through PKCS#12 so that Windows can use the key on the server side
        return X509CertificateLoader.LoadPkcs12(made.Export(X509ContentType.Pfx), null);
    }

    /// <summary>A TLS server for one connection; the task gives the application bytes it received before the end.</summary>
    private static (int Port, Task<int> Received) Serve(X509Certificate2 certificate)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var received = Task.Run(async () =>
        {
            using var tcp = await listener.AcceptTcpClientAsync();
            listener.Stop();
            using var stream = new SslStream(tcp.GetStream());
            var total = 0;
            try
            {
                await stream.AuthenticateAsServerAsync(certificate);
                var buffer = new byte[4096];
                using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                while (total == 0)
                {
                    var count = await stream.ReadAsync(buffer, cancel.Token);
                    if (count == 0) break;
                    total += count;
                }
            }
            catch (Exception error) when (error is IOException or OperationCanceledException
                                              or System.Security.Authentication.AuthenticationException) { }
            return total;
        });
        return (port, received);
    }

    /// <summary>A TLS server for one connection that hands the stream to <paramref name="body"/> after the handshake.</summary>
    private static (int Port, Task<T> Result) ServeWith<T>(X509Certificate2 certificate, Func<SslStream, Task<T>> body)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        return (port, Task.Run(async () =>
        {
            using var tcp = await listener.AcceptTcpClientAsync();
            listener.Stop();
            using var stream = new SslStream(tcp.GetStream());
            await stream.AuthenticateAsServerAsync(certificate);
            return await body(stream);
        }));
    }

    [Fact]
    public async Task MessagesArriveInOrderAndGoodbyeIsNotLost()
    {
        using var certificate = SelfSigned();
        var (port, received) = ServeWith(certificate, async stream =>
        {
            var reader = new FrameReader();
            var messages = new List<Message>();
            var buffer = new byte[4096];
            try
            {
                while (await stream.ReadAsync(buffer) is > 0 and var count)
                    messages.AddRange(reader.Feed(buffer.AsSpan(0, count)));
            }
            catch (IOException) { }
            return messages;
        });
        var (client, _) = await ControlClient.ConnectAsync("127.0.0.1", port, PinOf(certificate), Timeout);
        Assert.NotNull(client);
        for (var code = 1; code <= 200; code++) client.Send(new Key(code, true));
        client.Send(new Goodbye());
        client.Dispose();  // closing right behind the goodbye must not cut it off
        var messages = await received.WaitAsync(Timeout);
        Assert.Equal(Enumerable.Range(1, 200).Select(code => (Message)new Key(code, true)), messages.Take(200));
        Assert.Equal(new Goodbye(), messages[^1]);
        Assert.Equal(201, messages.Count);
    }

    [Fact]
    public async Task SendNeverWaitsForALaptopThatHasStoppedReading()
    {
        // Send runs on the UI thread and inside the keyboard hook: a wait there would freeze typing on the whole PC
        using var certificate = SelfSigned();
        var release = new TaskCompletionSource();
        var (port, served) = ServeWith(certificate, async _ => { await release.Task; return 0; });
        var (client, _) = await ControlClient.ConnectAsync("127.0.0.1", port, PinOf(certificate), Timeout);
        Assert.NotNull(client);
        var big = new Error(new string('x', 100_000));
        var sending = Task.Run(() => { for (var count = 0; count < 300; count++) client.Send(big); });
        try
        {
            await sending.WaitAsync(Timeout);
            var disposing = Task.Run(client.Dispose);
            await disposing.WaitAsync(Timeout);  // and closing does not wait for it either
        }
        finally
        {
            release.SetResult();
            await served;
        }
    }

    [Fact]
    public async Task APileUpOfUnsentMessagesClosesTheClient()
    {
        using var certificate = SelfSigned();
        var release = new TaskCompletionSource();
        var (port, served) = ServeWith(certificate, async _ => { await release.Task; return 0; });
        var (client, _) = await ControlClient.ConnectAsync("127.0.0.1", port, PinOf(certificate), Timeout);
        Assert.NotNull(client);
        using (client)
        {
            var big = new Error(new string('x', 20_000));
            for (var count = 0; count < Outbox.Limit + 2000 && !client.Closed; count++) client.Send(big);
            Assert.True(client.Closed);
        }
        release.SetResult();
        await served;
    }

    private static string PinOf(X509Certificate2 certificate) =>
        Convert.ToHexStringLower(SHA256.HashData(certificate.GetRawCertData()));

    [Fact]
    public async Task ThePinnedCertificateIsAcceptedAndMessagesFlow()
    {
        using var certificate = SelfSigned();
        var (port, received) = Serve(certificate);
        var (client, wrongCertificate) = await ControlClient.ConnectAsync("127.0.0.1", port, PinOf(certificate), Timeout);
        Assert.NotNull(client);
        Assert.False(wrongCertificate);
        using (client)
        {
            client.Send(new Heartbeat());
            Assert.True(await received > 0);
        }
    }

    [Fact]
    public async Task AnotherCertificateIsRefusedAndNothingIsSent()
    {
        using var certificate = SelfSigned();
        using var other = SelfSigned();
        var (port, received) = Serve(certificate);
        var (client, wrongCertificate) = await ControlClient.ConnectAsync("127.0.0.1", port, PinOf(other), Timeout);
        Assert.Null(client);
        Assert.True(wrongCertificate);
        Assert.Equal(0, await received);
    }

    [Fact]
    public async Task ALaptopThatDoesNotAnswerIsNotAWrongCertificate()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        var (client, wrongCertificate) = await ControlClient.ConnectAsync("127.0.0.1", port, new string('0', 64), Timeout);
        Assert.Null(client);
        Assert.False(wrongCertificate);
    }
}
