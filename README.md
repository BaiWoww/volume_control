# VolumeMixer

A lightweight Windows volume mixer assistant that lives in a floating ball on your desktop. It replicates the per-application volume control from Windows Settings → Sound → Volume mixer, and exposes it through a tiny, always-accessible UI.

## Features

- **Floating control ball** – draggable, edge-snapping, auto-hides after a few seconds of inactivity, stays on top by default.
- **Per-application volume mixer** – lists every active audio session, including system sounds, with individual volume sliders and mute toggles.
- **Master volume control** – adjust the system endpoint volume and mute from the same panel.
- **Real-time refresh** – new audio sources appear automatically via `IAudioSessionNotification`; the panel also re-polls every two seconds.
- **Friendly process names** – resolves `FileDescription` from executable resources (e.g. shows "Google Chrome" instead of "chrome").
- **System sounds session** – detected and labelled via `SHLoadIndirectString` on the localized display-name resource.
- **Smooth animations** – `QPropertyAnimation` for hover, click, edge-snap, auto-hide, and panel fade.
- **Single-instance, low overhead** – the application is a tray-less, frameless PyQt5 widget; no background service is installed.

## Screenshots

_Add screenshots here._ A typical layout:

```
+-------------------------------------+
|  Floating ball    Volume panel      |
|    ( )             +-----------+    |
|                   | Master 80 |    |
|                   | Chrome 60 |    |
|                   | Spotify 40 |    |
|                   +-----------+    |
+-------------------------------------+
```

## Requirements

- Windows 10 or Windows 11 (uses the Windows Audio Session API / WASAPI)
- Python 3.7 or later
- A working audio output device

## Installation

```powershell
# 1. Clone the repository
git clone https://github.com/BaiWoww/volume_control.git
cd volume_control

# 2. (Recommended) Create a virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

## Running from source

```powershell
python main.py
```

A floating blue ball will appear on the right edge of your primary screen. Left-click to open the volume panel; right-click for the context menu (toggle always-on-top, exit).

### Windows convenience script

Double-click `start.bat`. It checks for Python, creates a virtual environment on first run, installs dependencies, and launches the application.

## Building a standalone executable

A PyInstaller spec file is provided:

```powershell
pyinstaller volume_mixer.spec
```

The single-file executable will be written to `dist/VolumeMixer.exe`. The `build/`, `dist/`, and `__pycache__/` directories are excluded from version control by `.gitignore`.

## Project structure

```
volume_control/
├── audio_controller.py   # COM / WASAPI wrapper, session enumeration, mute / volume control
├── floating_ball.py      # Frameless circular widget, drag / snap / auto-hide logic
├── volume_panel.py       # Per-session mixer panel with sliders and mute buttons
├── main.py               # Entry point: QApplication, exception hook, wiring
├── requirements.txt      # Pinned Python dependencies
├── start.bat             # Windows launcher that sets up venv and runs main.py
├── volume_mixer.spec     # PyInstaller build configuration
├── .gitignore            # Standard Python + PyInstaller + IDE exclusions
├── LICENSE               # MIT License
└── README.md             # This file
```

## How it works

### `audio_controller.py`

- Initializes COM in the STA apartment, matching PyQt5's threading model.
- Wraps `pycaw.pycaw.AudioUtilities` to enumerate audio sessions through `GetAllSessions()`.
- For each session:
  - Skips `AudioSessionState.Expired` (state = 2) entries to avoid COM errors.
  - Detects the system sounds session via `IsSystemSoundsSession()` and resolves its localized name with `SHLoadIndirectString` (since the raw value is an `@dllpath,-resid` resource reference).
  - Caches a friendly name per PID, preferring `FileDescription` from the executable's version resource.
- Provides a `SessionNotificationSink` COM object that implements `IAudioSessionNotification` and forwards new-session events back to the UI through a Qt signal.
- Exposes `get_master_volume / set_master_volume / get_master_mute / set_master_mute` for the system endpoint.

### `floating_ball.py`

- A frameless, translucent `QWidget` with `Qt.Tool | Qt.WindowStaysOnTopHint`.
- Self-paints a glossy blue ball with a radial-gradient highlight and a hand-drawn speaker glyph.
- Uses `QPropertyAnimation` for hover scale (1.0 → 1.12), press scale (0.92), edge-snap, and idle auto-hide.
- Toggles the `VolumePanel` on left-click; right-click opens a styled context menu.

### `volume_panel.py`

- A frameless popup with a rounded translucent container, painted using Qt stylesheets.
- Holds a `VolumeSlider` for the master endpoint plus one per active session.
- Refreshes the session list every two seconds while visible; on every refresh it incrementally adds / removes / updates slider widgets to avoid flicker.
- Slider color tier (muted / low / mid / high) is applied through a tiered stylesheet to keep repaint cost low.

## Limitations

- Windows only. The `pycaw` and `comtypes` libraries and the underlying WASAPI calls have no portable equivalents.
- A handful of system processes (notably some Windows components running under `PID 0` that are not the system sounds session) are filtered out.
- Some processes refuse to expose `SimpleAudioVolume` even when an audio session is active; those will be invisible in the panel, mirroring the behavior of the built-in Windows volume mixer.

## Contributing

Pull requests are welcome. Please open an issue first to discuss substantial changes. Run any existing tests / smoke-test the panel by hand before submitting.

## License

[MIT](LICENSE) – Copyright (c) 2025 BaiWoww.
