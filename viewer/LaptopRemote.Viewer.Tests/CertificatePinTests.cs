using System.Text;
using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class CertificatePinTests
{
    // SHA-256 of the three bytes "abc"
    private const string Abc = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    [Fact]
    public void NormalizeAcceptsColonsSpacesAndCapitals() =>
        Assert.Equal(Abc, CertificatePin.Normalize(
            " BA:78:16:BF 8F:01:CF:EA:41:41:40:DE:5D:AE:22:23:B0:03:61:A3:96:17:7A:9C:B4:10:FF:61:F2:00:15:AD\n"));

    [Theory]
    [InlineData("")]
    [InlineData("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015a")]
    [InlineData("ga7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")]
    [InlineData("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015adad")]
    public void NormalizeRejects(string text) => Assert.Null(CertificatePin.Normalize(text));

    [Fact]
    public void MatchesTheSha256OfTheBytes()
    {
        Assert.True(CertificatePin.Matches(Abc, Encoding.ASCII.GetBytes("abc")));
        Assert.True(CertificatePin.Matches(Abc.ToUpperInvariant(), Encoding.ASCII.GetBytes("abc")));
        Assert.False(CertificatePin.Matches(Abc, Encoding.ASCII.GetBytes("abd")));
    }

    [Fact]
    public void ABrokenPinMatchesNothing() =>
        Assert.False(CertificatePin.Matches("", Encoding.ASCII.GetBytes("abc")));
}
