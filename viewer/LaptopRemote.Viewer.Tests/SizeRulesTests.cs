using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer.Tests;

public class SizeRulesTests
{
    [Theory]
    [InlineData(1600, 900, 1600, 900)]
    [InlineData(333, 201, 332, 200)]
    [InlineData(10, 10, 320, 200)]
    [InlineData(9000, 5000, 4096, 4096)]
    [InlineData(1601, 901, 1600, 900)]
    public void Normalize(int width, int height, int expectedWidth, int expectedHeight) =>
        Assert.Equal((expectedWidth, expectedHeight), SizeRules.Normalize(width, height));
}
