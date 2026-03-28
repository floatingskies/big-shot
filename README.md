# big-shot-ui

Standalone GTK4 screenshot + screencast UI for the **Big Shot** Cinnamon extension.

Replaces the GNOME Shell `ScreenshotUI` overlay that Big Shot originally injected into.

---

## Architecture

```
big-shot-ui/
├── big-shot-ui          ← executable entry point
├── big_shot_app.py      ← Gtk.Application wrapper, CLI arg parsing
├── install.sh           ← automated installer
│
├── ui/
│   ├── screenshot_window.py   ← fullscreen overlay + area/window selection
│   ├── annotation_toolbar.py  ← floating draggable toolbar (all tools)
│   ├── mode_bar.py            ← Screenshot / Area / Window mode switcher
│   └── screencast_window.py   ← recording control panel
│
└── drawing/
    ├── canvas.py    ← annotation state machine (history, undo/redo)
    └── tools.py     ← all drawing tool classes (pen, arrow, rect, …)
```

---

## Modes

| `--mode` | What it does |
|---|---|
| `screenshot` | Captures full screen, shows it frozen, opens annotation toolbar |
| `area` | Shows rubber-band selection, then annotation toolbar on the crop |
| `window` | (TODO: window picker) Falls back to full screenshot |
| `screencast` | Opens the video recording control panel |

---

## Annotation Tools

Implemented in `drawing/tools.py` as Cairo-rendered classes:

| Tool | Description |
|---|---|
| `pen` | Freehand polyline |
| `arrow` | Line with filled arrowhead |
| `line` | Straight line |
| `rect` | Rectangle with optional fill |
| `circle` | Ellipse with optional fill |
| `text` | Text label (font selector in toolbar) |
| `highlight` | Semi-transparent wide marker stroke |
| `censor` | Mosaic/pixelate rectangle |
| `blur` | Frosted-glass rectangle |
| `number` | Numbered circle badge |
| `number-arrow` | Number badge + arrow to a target point |
| `eraser` | Erase annotations using Cairo OPERATOR_CLEAR |

All tools support:
- **Stroke colour** — colour picker with 24-colour palette
- **Fill colour** — optional, shown for rect/circle
- **Brush size** — 1–100 px, +/− buttons or Ctrl+Scroll
- **Intensity** — 1–5, for censor/blur tools
- **Font** — family picker, for text tool

---

## Screencast Control Panel

`ui/screencast_window.py` provides:

- Capture area: Full Screen / Area
- Audio: Desktop audio + Microphone toggles
- FPS: 15 / 24 / **30** / 60
- Resolution: 100% / 75% / 50% / 33%
- Quality: High / Medium / Low
- Webcam overlay toggle
- Start → Stop / Pause → Resume controls with live timer

### Backend priority

1. **Cinnamon extension D-Bus** (`org.bigcommunity.BigShot`) — preferred; the
   extension handles GStreamer pipeline selection, GPU acceleration, and pause/resume.
2. **Direct `gst-launch-1.0` subprocess** — used when the extension is not running,
   or for standalone use without Cinnamon.

---

## Installation

```bash
chmod +x install.sh
./install.sh        # user install: ~/.local/bin/big-shot-ui
sudo ./install.sh   # system install: /usr/local/bin/big-shot-ui
```

### Dependencies (Ubuntu / Linux Mint)

```bash
sudo apt install \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 \
    gir1.2-gdkpixbuf-2.0 \
    scrot
```

For screencast audio:
```bash
sudo apt install gstreamer1.0-plugins-bad   # fdkaacenc (AAC)
sudo apt install gstreamer1.0-plugins-ugly  # openh264enc
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Esc` | Close / cancel |
| `Enter` | Confirm area selection |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Redo |
| `Ctrl+C` | Copy to clipboard |
| `Ctrl+S` | Save to Pictures/Screenshots/ |
| `Ctrl+Scroll` | Adjust brush size |

---

## Integration with the Cinnamon Extension

The Cinnamon extension (`big-shot@bigcommunity.org`) calls `big-shot-ui` when
the user presses **Print Screen**. The extension searches for the binary in:

1. `~/.local/bin/big-shot-ui`
2. `/usr/local/bin/big-shot-ui`
3. `/usr/bin/big-shot-ui`

If none is found, the extension falls back to `gnome-screenshot --interactive`.
