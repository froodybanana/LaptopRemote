using System.Text.Json;

namespace LaptopRemote.Viewer.Core;

/// <summary>Where the window was left: its restored bounds in screen pixels and whether it was maximized.</summary>
public sealed record WindowPlacement(int X, int Y, int Width, int Height, bool Maximized)
{
    private const int MinWidth = 200, MinHeight = 150, MinVisible = 100, FrameOverhang = 8;

    public static string DefaultPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "LaptopRemote", "window.json");

    /// <summary>Null for anything that is not a complete placement; a broken file must not stop the viewer.</summary>
    public static WindowPlacement? Parse(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return null;
            int? Int(string name) =>
                root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
                    ? number : null;
            if (Int("x") is not { } x || Int("y") is not { } y || Int("width") is not { } width || Int("height") is not { } height)
                return null;
            if (!root.TryGetProperty("maximized", out var maximized) || maximized.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                return null;
            return new WindowPlacement(x, y, width, height, maximized.GetBoolean());
        }
        catch (JsonException)
        {
            return null;
        }
    }

    public string ToJson()
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream))
        {
            writer.WriteStartObject();
            writer.WriteNumber("x", X);
            writer.WriteNumber("y", Y);
            writer.WriteNumber("width", Width);
            writer.WriteNumber("height", Height);
            writer.WriteBoolean("maximized", Maximized);
            writer.WriteEndObject();
        }
        return System.Text.Encoding.UTF8.GetString(stream.ToArray());
    }

    /// <summary>True when enough of the window, title bar included, lies on one of the monitors' work areas.</summary>
    public bool FitsAny(IEnumerable<(int X, int Y, int Width, int Height)> workAreas)
    {
        if (Width < MinWidth || Height < MinHeight) return false;
        foreach (var area in workAreas)
        {
            var overlapWidth = Math.Min(X + Width, area.X + area.Width) - Math.Max(X, area.X);
            var overlapHeight = Math.Min(Y + Height, area.Y + area.Height) - Math.Max(Y, area.Y);
            if (overlapWidth >= MinVisible && overlapHeight >= MinVisible && Y >= area.Y - FrameOverhang) return true;
        }
        return false;
    }
}
