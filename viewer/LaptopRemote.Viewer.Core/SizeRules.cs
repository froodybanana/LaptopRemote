namespace LaptopRemote.Viewer.Core;

public static class SizeRules
{
    public const int MinWidth = 320, MinHeight = 200, MaxSide = 4096;

    /// <summary>Clamp a window size to what the encoder takes and round down to even numbers.</summary>
    public static (int Width, int Height) Normalize(int width, int height)
    {
        width = Math.Clamp(width, MinWidth, MaxSide);
        height = Math.Clamp(height, MinHeight, MaxSide);
        return (width - width % 2, height - height % 2);
    }
}
