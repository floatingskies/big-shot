# Big Shot — Cinnamon Port

Enhanced screenshot annotation and screencast recording for the **Cinnamon** desktop
environment (Linux Mint 21+, 22+, and compatible distros running Cinnamon 5.x / 6.x).

---

## What Changed (GNOME Shell → Cinnamon)

| Area | GNOME Shell (original) | Cinnamon (this port) |
|---|---|---|
| **Module imports** | `import X from 'gi://X'` (ES modules) | `const X = imports.gi.X` (CommonJS) |
| **Extension entry** | `export default class … extends Extension` | `function enable()` / `function disable()` / `function init()` |
| **Panel button** | `PanelMenu.Button` + `Main.panel.addToStatusArea` | `Main.panel._rightBox.insert_child_at_index` |
| **Screenshot UI** | Injects into GNOME's native `ScreenshotUI` overlay | Launches `gnome-screenshot --interactive` or a standalone `big-shot-ui` binary |
| **Print Screen override** | GNOME Keybindings (not needed — extension IS the UI) | `Main.keybindingManager.addHotkey` (Cinnamon 6) or `Meta` fallback (Cinnamon 5) |
| **Screencast proxy** | `org.gnome.Shell.Screencast` D-Bus + monkey-patch | D-Bus proxy (if present) OR direct `gst-launch-1.0` subprocess |
| **Monitor geometry** | `global.display.get_monitor_geometry` | `global.screen.get_monitor_geometry` (Cin 5) / `global.display` (Cin 6) |
| **Notifications** | `MessageTray.Source` + GNOME Shell API | Cinnamon `MessageTray.Source` + `source.notify()` |

---

## Installation

### 1. Copy the extension

```bash
mkdir -p ~/.local/share/cinnamon/extensions/big-shot@bigcommunity.org
cp -r . ~/.local/share/cinnamon/extensions/big-shot@bigcommunity.org/
```

### 2. Restart Cinnamon

```
Ctrl + Alt + Esc   (or run: cinnamon --replace &)
```

### 3. Enable the extension

Open **System Settings → Extensions**, find *Big Shot*, and toggle it on.

---

## Keybinding — Print Screen Override

When the extension is enabled it registers two hotkeys:

| Key | Action |
|---|---|
| `Print` | Launch Big Shot screenshot (interactive mode) |
| `Shift + Print` | Launch Big Shot area screenshot |

These are registered via `Main.keybindingManager` (Cinnamon 6.x) or Muffin's
`Meta.KeyBindingFlags` API (Cinnamon 5.x).  The original `gnome-screenshot`
shortcut values are saved and restored when the extension is disabled.

> **Note:** If you have a custom Print Screen shortcut set in System Settings →
> Keyboard, Big Shot's hotkey will take precedence while the extension is active,
> and your original shortcut will be restored when you disable it.

---

## Screenshot UI — Choosing a Backend

Big Shot looks for a `big-shot-ui` executable in the following locations (in order):

1. `~/.local/bin/big-shot-ui`
2. `/usr/local/bin/big-shot-ui`
3. `/usr/bin/big-shot-ui`
4. `<extension-dir>/big-shot-ui`

If none is found, it falls back to `gnome-screenshot --interactive`, which ships
by default with Linux Mint and most Cinnamon-based distributions.

---

## Screencast Backend

Big Shot tries the following backends for screen recording, in order:

1. **org.gnome.Shell.Screencast D-Bus service** — if you have the GNOME Shell
   screencast daemon installed.
2. **Direct `gst-launch-1.0` subprocess** — available on any system with
   GStreamer 1.x installed.

The same hardware-accelerated pipeline selection (NVIDIA NVENC, VAAPI, software
VP9/H.264) is used in both cases.

### Required GStreamer packages (Ubuntu / Mint)

```bash
# Core
sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base \
                 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
                 gstreamer1.0-plugins-ugly

# Software encoders
sudo apt install gstreamer1.0-libav         # H.264 via openh264
sudo apt install gstreamer1.0-fdkaac        # AAC audio (optional)

# Hardware acceleration (pick one)
sudo apt install gstreamer1.0-vaapi         # AMD / Intel VAAPI
# NVIDIA: install nvidia-gstreamer (proprietary repo)
```

---

## Pause / Resume Recording

While recording, a **timer label + pause icon** appears in the Cinnamon panel
(right side, next to the clock).  Click it to pause; click again to resume.

Pause/resume works by sending `SIGSTOP` / `SIGCONT` to the active GStreamer
pipeline process — the same mechanism as the GNOME version.

---

## Cinnamon Version Compatibility

| Cinnamon | Linux Mint | Status |
|---|---|---|
| 6.4 | Mint 22.x | ✅ Fully tested |
| 6.2 | Mint 22 | ✅ Fully tested |
| 6.0 | Mint 21.3 | ✅ |
| 5.8 | Mint 21.2 | ✅ |
| 5.6 | Mint 21.1 | ✅ |
| 5.4 | Mint 21   | ✅ |
| 5.2 | Mint 20.3 | ⚠️ keybindingManager may not exist; Meta fallback used |
| 5.0 | Mint 20.2 | ⚠️ Same as above; test keybindings manually |

---

## File Structure

```
big-shot@bigcommunity.org/
├── metadata.json          # Cinnamon extension manifest
├── extension.js           # Main entry (enable/disable/init)
├── stylesheet.css         # St widget styles for panel indicator
├── gradients.js           # Cairo gradient helpers (CommonJS)
└── parts/
    ├── partbase.js        # PartBase / PartUI / PartPopupSelect
    ├── partaudio.js       # Desktop + mic audio via Gvc
    ├── partindicator.js   # Panel timer + pause button
    ├── partframerate.js   # FPS selector (value only, no UI widget)
    └── partdownsize.js    # Resolution selector (value only)
```

Parts that require the GNOME Shell ScreenshotUI (`partannotation.js`,
`parttoolbar.js`, `partcrop.js`, `partgradient.js`, `partwebcam.js`,
`partquickstop.js`) are not included in this Cinnamon port because Cinnamon
does not expose an injectable screenshot overlay.  These features are intended
to be implemented in the standalone `big-shot-ui` GTK application.
