using System.Diagnostics;
using LaptopRemote.Viewer.Core;

namespace LaptopRemote.Viewer;

/// <summary>First run, or --setup: asks for the laptop and pairs with its agent over ssh. Thin: the rules are in Core.Pairing.</summary>
internal sealed class SetupForm : Form
{
    private readonly ViewerConfig? existing;
    private readonly TextBox address = new() { Width = 260 };
    private readonly TextBox user = new() { Width = 260 };
    private readonly Label status = new() { AutoSize = false, Height = 60, Width = 400, Text = "" };
    private readonly Button pair = new() { Text = "Pair", Width = 100 };
    private readonly Button key = new() { Text = "Install ssh key…", Width = 130, Enabled = false };
    private readonly Button cancel = new() { Text = "Cancel", Width = 100, DialogResult = DialogResult.Cancel };

    public ViewerConfig? Result { get; private set; }

    public SetupForm(ViewerConfig? existing, string? problem = null)
    {
        this.existing = existing;
        Text = $"{ViewerForm.Title} setup";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(440, 230);
        CancelButton = cancel;
        AcceptButton = pair;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(12) };
        layout.Controls.Add(new Label { Text = "Laptop address", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
        layout.Controls.Add(address, 1, 0);
        layout.Controls.Add(new Label { Text = "ssh user on the laptop", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
        layout.Controls.Add(user, 1, 1);
        layout.Controls.Add(status, 0, 2);
        layout.SetColumnSpan(status, 2);
        var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, AutoSize = true };
        buttons.Controls.AddRange([cancel, pair, key]);
        layout.Controls.Add(buttons, 0, 3);
        layout.SetColumnSpan(buttons, 2);
        Controls.Add(layout);
        address.Text = existing?.LaptopAddress ?? "";
        user.Text = existing?.SshTarget is { } target && target.IndexOf('@') is var at && at > 0 ? target[..at] : "";
        status.Text = problem is null
            ? "The laptop needs the agent installed (agent/setup.sh install) and ssh with key auth."
            : $"{problem}. Pairing writes a new config.json; ports, decoder and gstreamerBin go back to their defaults.";
        pair.Click += async (_, _) => await PairAsync();
        key.Click += (_, _) => OpenKeyConsole();
    }

    private async Task PairAsync()
    {
        if (Pairing.Target(user.Text, address.Text) is not { } target)
        {
            status.Text = "Enter the laptop's address and your user name on it.";
            return;
        }
        pair.Enabled = key.Enabled = false;
        status.Text = $"Pairing with {target}…";
        var info = new ProcessStartInfo("ssh") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in Pairing.SshArguments(target)) info.ArgumentList.Add(argument);
        string stdout, stderr;
        int exitCode;
        try
        {
            using var process = Process.Start(info) ?? throw new InvalidOperationException("ssh did not start");
            var outTask = process.StandardOutput.ReadToEndAsync();
            var errTask = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            stdout = await outTask;
            stderr = await errTask;
            exitCode = process.ExitCode;
        }
        catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            status.Text = "ssh.exe was not found. Install Windows' OpenSSH client (Settings, Optional features).";
            pair.Enabled = true;
            return;
        }
        if (exitCode != 0)
        {
            var reason = stderr.Split('\n', StringSplitOptions.RemoveEmptyEntries).LastOrDefault()?.Trim() ?? $"ssh exit code {exitCode}";
            key.Enabled = Pairing.LooksLikeKeyRefused(stderr);
            status.Text = key.Enabled
                ? "The laptop refused the key. Use \"Install ssh key…\", type the laptop password once, then Pair again."
                : $"Pairing failed: {reason}";
            pair.Enabled = true;
            return;
        }
        try
        {
            var config = Pairing.Paired(address.Text, target, Pairing.ParseResult(stdout), existing);
            Directory.CreateDirectory(Path.GetDirectoryName(ViewerConfig.DefaultPath)!);
            File.WriteAllText(ViewerConfig.DefaultPath, config.ToJson());
            Result = config;
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception error) when (error is FormatException or IOException or UnauthorizedAccessException)
        {
            status.Text = $"Pairing failed: {error.Message}";
            pair.Enabled = true;
        }
    }

    private void OpenKeyConsole()
    {
        if (Pairing.Target(user.Text, address.Text) is not { } target) return;
        Process.Start(new ProcessStartInfo("cmd.exe", "/k " + Pairing.KeyCopyCommand(target)) { UseShellExecute = true });
    }
}
