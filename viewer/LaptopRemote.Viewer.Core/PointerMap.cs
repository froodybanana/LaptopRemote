namespace LaptopRemote.Viewer.Core;

/// <summary>From a mouse position in the video area to a pixel of the picture the laptop is sending.</summary>
public static class PointerMap
{
    /// <summary>
    /// The stream is the size last sent to the laptop. Normally that is the area and the mapping is 1:1;
    /// while a resize is in flight the old picture is stretched over the area. Positions outside the
    /// area (a drag that left the window) go to the nearest edge. Null when either size is empty.
    /// </summary>
    public static (int X, int Y)? ToStream(int x, int y, int areaWidth, int areaHeight, int streamWidth, int streamHeight)
    {
        if (areaWidth <= 0 || areaHeight <= 0 || streamWidth <= 0 || streamHeight <= 0) return null;
        return (Scale(x, areaWidth, streamWidth), Scale(y, areaHeight, streamHeight));
    }

    private static int Scale(int position, int area, int stream) =>
        (int)Math.Min((long)Math.Clamp(position, 0, area - 1) * stream / area, stream - 1);
}
