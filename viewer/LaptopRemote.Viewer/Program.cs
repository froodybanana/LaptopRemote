using LaptopRemote.Viewer.Core;
using LaptopRemote.Viewer.Native;

namespace LaptopRemote.Viewer;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        try
        {
            // --test-pipeline "<gst-launch text ending in an element named sink>" shows that pipeline instead of the laptop
            var testPipeline = args is ["--test-pipeline", var text] ? text : null;
            // one viewer at a time: a second start only brings the first one's window to the front
            using var single = new Mutex(false, @"Local\LaptopRemote.Viewer");
            if (testPipeline is null && !Claim(single))
            {
                User32.Activate(ViewerForm.Title);
                return;
            }
            ViewerConfig config;
            if (testPipeline is not null)
            {
                config = new ViewerConfig("", 0, 0, null, ViewerConfig.DefaultDecoder, null, "", "");
            }
            else
            {
                // no config.json, or one that does not parse, or --setup: the dialog pairs with the laptop and writes it
                var existing = ViewerConfig.TryParse(File.Exists(ViewerConfig.DefaultPath) ? File.ReadAllText(ViewerConfig.DefaultPath) : null, out var problem);
                if (existing is null || args.Contains("--setup"))
                {
                    using var setup = new SetupForm(existing, problem);
                    if (setup.ShowDialog() != DialogResult.OK || setup.Result is null) return;
                    config = setup.Result;
                }
                else
                {
                    config = existing;
                }
            }
            var gstreamerBin = config.ResolveGStreamerBin(Environment.GetEnvironmentVariable);
            if (!Directory.Exists(gstreamerBin))
                throw new DirectoryNotFoundException($"GStreamer runtime not found at {gstreamerBin}. Install the MSVC x86_64 runtime from https://gstreamer.freedesktop.org/download/ or set gstreamerBin in config.json.");
            VideoPipeline.Initialize(gstreamerBin);
            if (testPipeline is null && !VideoPipeline.HasElement(config.Decoder))
                throw new InvalidOperationException($"GStreamer has no element named {config.Decoder}. Install the matching plugin or set decoder in config.json.");
            Application.Run(new ViewerForm(config, testPipeline));
        }
        catch (Exception error) when (error is IOException or FormatException or DirectoryNotFoundException or InvalidOperationException)
        {
            MessageBox.Show(error.Message, "LaptopRemote", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static bool Claim(Mutex mutex)
    {
        try { return mutex.WaitOne(0); }
        catch (AbandonedMutexException) { return true; }  // the previous viewer was killed; the mutex is ours now
    }
}
