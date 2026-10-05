# Floating Windows controls

Small WPF desktop panel for the existing Home Strip Linux controller. Four outlet buttons show reported state; commands use the controller's confirmation API. Unreachable or stale devices disable controls. The first connected device in the server's list is displayed.

Drag the window to your second display. Its position, size, server URL, and always-on-top choice are saved in `%LOCALAPPDATA%\HomeStrip\settings.json` when hidden or closed. If the saved display is unavailable, the window returns to the primary work area.

**On top** keeps it above other windows. **To tray**, or the window close button, hides it. Double-click the tray icon to restore it; use the tray menu's **Exit** to quit. Settings contains the controller URL and optional **Start with Windows**. Startup uses the current user's registry Run key; keep the executable in a permanent location after enabling this.

## Build

Use the .NET 8 SDK on Windows:

```powershell
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true --source https://api.nuget.org/v3/index.json -o publish
```

Keep the published files together. No separately installed runtime is needed. The owner's build is at `C:\Users\shree\HomeStrip\HomeStrip.exe`.

## Checks

Windows release publishing passed, and a six-second startup smoke check confirmed a running process and a titled window. The controller API returned HTTP 200 from Windows. Physical switching was not triggered during verification; check one safe outlet through the panel. Multi-monitor placement, tray interactions, and login startup still require interactive verification.
