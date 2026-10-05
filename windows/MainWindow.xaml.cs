using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using Microsoft.Win32;
using Forms = System.Windows.Forms;

namespace HomeStrip;

public sealed class Preferences {
    public string Server { get; set; } = "http://192.168.1.220:8080";
    public double Left { get; set; } = 100;
    public double Top { get; set; } = 100;
    public double Width { get; set; } = 340;
    public double Height { get; set; } = 310;
    public bool Pinned { get; set; }
    public bool Startup { get; set; }
}
public sealed record Outlet(int Number, bool? On, [property: JsonPropertyName("power_w")] double? Power);
public sealed record Device(string Id, bool Ready, bool Busy, List<Outlet> Outlets, [property: JsonPropertyName("power_w")] double? Power);
public sealed record Snapshot(List<Device> Devices);

public partial class MainWindow : Window {
    private static readonly string SettingsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HomeStrip", "settings.json");
    private readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(10) };
    private readonly JsonSerializerOptions json = new() { PropertyNameCaseInsensitive = true };
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(2) };
    private readonly Forms.NotifyIcon tray = new();
    private readonly List<Button> buttons = new();
    private Preferences preferences = new();
    private Device? device;
    private bool refreshing, pending, exiting;
    private string? commandNotice;

    public MainWindow() {
        InitializeComponent();
        LoadPreferences();
        Left = preferences.Left; Top = preferences.Top;
        Width = Math.Clamp(preferences.Width, 310, 900); Height = Math.Clamp(preferences.Height, 290, 900);
        Pin.IsChecked = preferences.Pinned;
        for (int number = 1; number <= 4; number++) {
            int channel = number;
            var button = new Button { Margin = new Thickness(4), FontSize = 16, IsEnabled = false, Content = $"Outlet {number}\nUnknown" };
            button.Click += async (_, _) => await SetPower(channel);
            buttons.Add(button); Outlets.Children.Add(button);
        }
        tray.Icon = System.Drawing.SystemIcons.Application; tray.Text = "Home Strip"; tray.Visible = true;
        tray.DoubleClick += (_, _) => Restore();
        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add("Show", null, (_, _) => Restore());
        menu.Items.Add("Exit", null, (_, _) => { exiting = true; Close(); });
        tray.ContextMenuStrip = menu;
        timer.Tick += async (_, _) => await Refresh();
        Loaded += async (_, _) => { KeepOnScreen(); timer.Start(); await Refresh(); };
    }

    private void LoadPreferences() {
        try { if (File.Exists(SettingsPath)) preferences = JsonSerializer.Deserialize<Preferences>(File.ReadAllText(SettingsPath)) ?? new(); }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException) { Status.Text = "Could not load settings; using defaults."; }
    }
    private void SavePreferences() {
        if (WindowState == WindowState.Normal) { preferences.Left = Left; preferences.Top = Top; preferences.Width = Width; preferences.Height = Height; }
        preferences.Pinned = Topmost;
        try { Directory.CreateDirectory(Path.GetDirectoryName(SettingsPath)!); File.WriteAllText(SettingsPath, JsonSerializer.Serialize(preferences)); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { Status.Text = "Settings could not be saved."; }
    }
    private void KeepOnScreen() {
        var candidate = new System.Drawing.Rectangle((int)(Left * VisualTreeHelper.GetDpi(this).DpiScaleX), (int)(Top * VisualTreeHelper.GetDpi(this).DpiScaleY), 100, 100);
        if (!Forms.Screen.AllScreens.Any(screen => screen.WorkingArea.IntersectsWith(candidate))) { Left = SystemParameters.WorkArea.Left + 40; Top = SystemParameters.WorkArea.Top + 40; }
    }
    private async Task Refresh() {
        if (refreshing || pending) return;
        refreshing = true;
        try {
            var snapshot = await http.GetFromJsonAsync<Snapshot>(preferences.Server + "/api/state", json);
            device = snapshot?.Devices.FirstOrDefault();
            Render();
        } catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException) {
            device = null; Disable(); Status.Text = "Server unreachable · retrying automatically";
        } finally { refreshing = false; }
    }
    private void Disable() { foreach (var button in buttons) button.IsEnabled = false; }
    private void Render() {
        Status.Text = device is null ? "No strip connected" : !device.Ready ? "Strip offline or readings stale" : commandNotice ?? "Connected · confirmed readings";
        Power.Text = device?.Power is double watts ? $"{watts:0.#} W" : "— W";
        foreach (var button in buttons.Select((button, index) => (button, index))) {
            var outlet = device?.Outlets.FirstOrDefault(o => o.Number == button.index + 1);
            button.button.Content = $"Outlet {button.index + 1}\n{(outlet?.On is null ? "Unknown" : outlet.On.Value ? "On" : "Off")}";
            button.button.Background = new SolidColorBrush(outlet?.On == true ? Color.FromRgb(233,244,238) : Colors.White);
            button.button.IsEnabled = !pending && device?.Ready == true && !device.Busy && outlet?.On is not null;
        }
    }
    private async Task SetPower(int channel) {
        if (pending || device?.Ready != true) return;
        var outlet = device.Outlets.First(o => o.Number == channel);
        if (outlet.On is null) return;
        pending = true; commandNotice = null; Disable(); Status.Text = $"Outlet {channel} · waiting for confirmation…";
        try {
            using var response = await http.PostAsJsonAsync(preferences.Server + "/api/power", new { device_id = device.Id, outlet = channel, on = !outlet.On.Value });
            using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            commandNotice = response.IsSuccessStatusCode ? $"Outlet {channel} · confirmed" : body.RootElement.GetProperty("error").GetString();
        } catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or KeyNotFoundException) {
            commandNotice = "Command unconfirmed · check current readings before retrying";
        } finally { pending = false; await Refresh(); }
    }
    private void Restore() { Show(); WindowState = WindowState.Normal; Activate(); }
    private void ToTray(object sender, RoutedEventArgs e) { SavePreferences(); Hide(); }
    private void PinChanged(object sender, RoutedEventArgs e) { Topmost = Pin.IsChecked == true; }
    private void OnClosing(object? sender, CancelEventArgs e) {
        SavePreferences();
        if (!exiting) { e.Cancel = true; Hide(); return; }
        timer.Stop(); tray.Dispose(); http.Dispose();
    }
    private void OpenSettings(object sender, RoutedEventArgs e) {
        var window = new Window { Title = "Home Strip settings", Owner = this, Width = 370, Height = 240, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        var panel = new StackPanel { Margin = new Thickness(20) };
        panel.Children.Add(new TextBlock { Text = "Controller URL" });
        var address = new TextBox { Text = preferences.Server, Margin = new Thickness(0,8,0,16) }; panel.Children.Add(address);
        var startup = new CheckBox { Content = "Start with Windows", IsChecked = preferences.Startup }; panel.Children.Add(startup);
        var save = new Button { Content = "Save", Margin = new Thickness(0,16,0,0), Padding = new Thickness(8) }; panel.Children.Add(save);
        save.Click += async (_, _) => {
            if (!Uri.TryCreate(address.Text.Trim(), UriKind.Absolute, out var uri) || uri.Scheme != "http" || !string.IsNullOrEmpty(uri.UserInfo) || uri.AbsolutePath != "/") { MessageBox.Show(window, "Enter an HTTP controller URL, such as http://192.168.1.220:8080"); return; }
            try {
                using var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
                if (startup.IsChecked == true) key.SetValue("HomeStrip", $"\"{Environment.ProcessPath}\""); else key.DeleteValue("HomeStrip", false);
            } catch (Exception error) when (error is UnauthorizedAccessException or System.Security.SecurityException or IOException) { MessageBox.Show(window, "Could not update Windows startup settings."); return; }
            preferences.Server = address.Text.Trim().TrimEnd('/'); preferences.Startup = startup.IsChecked == true;
            commandNotice = null; SavePreferences(); window.Close(); await Refresh();
        };
        window.Content = panel; window.ShowDialog();
    }
}
