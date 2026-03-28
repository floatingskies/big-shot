/**
 * Big Shot — Enhanced Screenshot & Screencast for Cinnamon
 *
 * Ported from GNOME Shell to Cinnamon desktop environment.
 * Supports Cinnamon 5.x and 6.x (Linux Mint 21+, 22+).
 *
 * Key differences from GNOME Shell port:
 *  - Uses imports.gi.* instead of gi:// (Cinnamon uses GJS without ESM by default)
 *  - Hooks into Cinnamon's media-keys / keybinding system for Print Screen override
 *  - Launches big-shot-ui (a standalone GTK window) instead of patching ScreenshotUI
 *  - GStreamer pipeline selection works identically to the GNOME version
 *  - Screencast proxy is accessed via DBus (org.cinnamon.ScreenSaver / gnome-shell compat)
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const APP_VERSION = '26.5.0';

// ── GI imports (Cinnamon / older GJS style) ──────────────────────────────────
const GLib        = imports.gi.GLib;
const Gio         = imports.gi.Gio;
const St          = imports.gi.St;
const Clutter     = imports.gi.Clutter;
const GdkPixbuf   = imports.gi.GdkPixbuf;
const cairo       = imports.gi.cairo;
const Meta        = imports.gi.Meta;
const Cinnamon    = imports.gi.Cinnamon;

// ── Cinnamon Shell UI modules ─────────────────────────────────────────────────
const Main        = imports.ui.main;
const MessageTray = imports.ui.messageTray;
const Settings    = imports.ui.settings;

// ── Extension helpers ─────────────────────────────────────────────────────────
const ExtensionSystem = imports.ui.extensionSystem;

// ── Parts (sub-modules) ───────────────────────────────────────────────────────
// Each part is a self-contained class that manages one feature area.
// They are loaded lazily to gracefully handle missing optional dependencies.

let PartToolbar, PartAudio, PartIndicator, PartWebcam;
let PartFramerate, PartDownsize;

try { ({ PartToolbar }   = require('./parts/parttoolbar');   } catch(e) { log(`[Big Shot] parttoolbar missing: ${e}`); }
try { ({ PartAudio }     = require('./parts/partaudio');     } catch(e) { log(`[Big Shot] partaudio missing: ${e}`); }
try { ({ PartIndicator } = require('./parts/partindicator'); } catch(e) { log(`[Big Shot] partindicator missing: ${e}`); }
try { ({ PartWebcam }    = require('./parts/partwebcam');    } catch(e) { log(`[Big Shot] partwebcam missing: ${e}`); }
try { ({ PartFramerate } = require('./parts/partframerate'); } catch(e) { log(`[Big Shot] partframerate missing: ${e}`); }
try { ({ PartDownsize }  = require('./parts/partdownsize');  } catch(e) { log(`[Big Shot] partdownsize missing: ${e}`); }

// =============================================================================
// GPU DETECTION
// =============================================================================

const GpuVendor = {
    NVIDIA:  'nvidia',
    AMD:     'amd',
    INTEL:   'intel',
    UNKNOWN: 'unknown',
};

function detectGpuVendors() {
    try {
        let [ok, stdout] = GLib.spawn_command_line_sync('lspci');
        if (!ok || !stdout) return [GpuVendor.UNKNOWN];

        const lines = imports.byteArray.toString(stdout).toLowerCase();
        const vendors = [];

        if (/(?:vga|display controller|3d).*nvidia/.test(lines))
            vendors.push(GpuVendor.NVIDIA);
        if (/(?:vga|display controller).*(?:\bamd\b|\bati\b)/.test(lines))
            vendors.push(GpuVendor.AMD);
        if (/(?:vga|display controller).*intel/.test(lines))
            vendors.push(GpuVendor.INTEL);

        return vendors.length > 0 ? vendors : [GpuVendor.UNKNOWN];
    } catch (e) {
        return [GpuVendor.UNKNOWN];
    }
}

// =============================================================================
// GSTREAMER PIPELINE CONFIGURATIONS (identical logic to GNOME version)
// =============================================================================

const QUALITY_PRESETS = {
    high:   { qp: 18, qp_i: 18, qp_p: 20, qp_b: 22, openh264_br: 8000000, vp9_cq: 13, vp9_minq: 10, vp9_maxq: 50 },
    medium: { qp: 24, qp_i: 24, qp_p: 26, qp_b: 28, openh264_br: 4000000, vp9_cq: 24, vp9_minq: 15, vp9_maxq: 55 },
    low:    { qp: 27, qp_i: 27, qp_p: 29, qp_b: 31, openh264_br: 2000000, vp9_cq: 31, vp9_minq: 20, vp9_maxq: 58 },
};

const VIDEO_PIPELINES = [
    {
        id: 'nvidia-raw-h264-nvenc',
        label: 'NVIDIA H.264',
        vendors: [GpuVendor.NVIDIA],
        src: 'videoconvert chroma-mode=none dither=none matrix-mode=output-only n-threads=4 ! queue',
        enc: (p) => `nvh264enc rc-mode=cqp qp-const=${p.qp} ! h264parse`,
        elements: ['videoconvert', 'nvh264enc'],
        ext: 'mp4',
    },
    {
        id: 'va-raw-h264-lp',
        label: 'VA H.264 Low-Power',
        vendors: [GpuVendor.AMD, GpuVendor.INTEL],
        src: 'videoconvert chroma-mode=none dither=none matrix-mode=output-only n-threads=4 ! queue',
        enc: (p) => `vah264lpenc rate-control=cqp qpi=${p.qp_i} qpp=${p.qp_p} qpb=${p.qp_b} ! h264parse`,
        elements: ['videoconvert', 'vah264lpenc'],
        ext: 'mp4',
    },
    {
        id: 'va-raw-h264',
        label: 'VA H.264',
        vendors: [GpuVendor.AMD, GpuVendor.INTEL],
        src: 'videoconvert chroma-mode=none dither=none matrix-mode=output-only n-threads=4 ! queue',
        enc: (p) => `vah264enc rate-control=cqp qpi=${p.qp_i} qpp=${p.qp_p} qpb=${p.qp_b} ! h264parse`,
        elements: ['videoconvert', 'vah264enc'],
        ext: 'mp4',
    },
    {
        id: 'vaapi-raw-h264',
        label: 'VAAPI H.264',
        vendors: [GpuVendor.AMD, GpuVendor.INTEL],
        src: 'videoconvert chroma-mode=none dither=none matrix-mode=output-only n-threads=4 ! queue',
        enc: (p) => `vaapih264enc rate-control=cqp init-qp=${p.qp} ! h264parse`,
        elements: ['videoconvert', 'vaapih264enc'],
        ext: 'mp4',
    },
    {
        id: 'sw-memfd-h264-openh264',
        label: 'Software H.264',
        vendors: [],
        src: 'videoconvert chroma-mode=none dither=none matrix-mode=output-only n-threads=4 ! queue',
        enc: (p) => `openh264enc complexity=high bitrate=${p.openh264_br} multi-thread=4 ! h264parse`,
        elements: ['videoconvert', 'openh264enc'],
        ext: 'mp4',
    },
    {
        id: 'sw-memfd-vp9',
        label: 'Software VP9',
        vendors: [],
        src: 'videoconvert chroma-mode=none dither=none matrix-mode=output-only n-threads=4 ! queue',
        enc: (p) => `vp9enc min_quantizer=${p.vp9_minq} max_quantizer=${p.vp9_maxq} cq_level=${p.vp9_cq} cpu-used=5 threads=4 deadline=1 static-threshold=1000 buffer-size=20000 row-mt=1 ! queue`,
        elements: ['videoconvert', 'vp9enc'],
        ext: 'webm',
    },
];

const AUDIO_PIPELINE = {
    vorbis: 'vorbisenc ! queue',
    aac:    'fdkaacenc ! queue',
};

const MUXERS = {
    mp4:  'mp4mux fragment-duration=500',
    webm: 'webmmux',
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function checkElement(name) {
    try {
        let [ok] = GLib.spawn_command_line_sync(`gst-inspect-1.0 --exists ${name}`);
        return ok;
    } catch (e) {
        return false;
    }
}

function checkPipeline(config) {
    return config.elements.every(el => checkElement(el));
}

function fixFilePath(filePath, ext) {
    if (!filePath || !ext) return;
    const file = Gio.File.new_for_path(filePath);
    if (!file.query_exists(null)) return;
    const newPath = filePath.replace(/\.[^.]+$/, `.${ext}`);
    if (newPath !== filePath) {
        const newFile = Gio.File.new_for_path(newPath);
        try {
            file.move(newFile, Gio.FileCopyFlags.NONE, null, null);
        } catch (e) {
            log(`[Big Shot] Failed to rename file: ${e.message}`);
        }
    }
}

// =============================================================================
// CINNAMON KEYBINDING — Override Print Screen with Big Shot
// =============================================================================

/**
 * Cinnamon stores the screenshot keybinding in:
 *   org.cinnamon.desktop.keybindings.media-keys  key: screenshot
 *
 * We save the original handler, replace it with Big Shot, and restore on disable.
 *
 * For Cinnamon 5.x: uses Meta.KeyBindingFlags and global.display.add_keybinding
 * For Cinnamon 6.x: same API, slightly different flags enum path
 */

const SCREENSHOT_SCHEMA   = 'org.cinnamon.desktop.keybindings.media-keys';
const SCREENSHOT_KEY      = 'screenshot';
const AREA_SCREENSHOT_KEY = 'area-screenshot';

// =============================================================================
// DBUS SCREENCAST PROXY (Cinnamon / GNOME Screencast compatibility)
// =============================================================================

/**
 * Cinnamon does not ship a dedicated screencast D-Bus service by default.
 * We support two backends:
 *   1. org.gnome.Shell.Screencast  — present if GNOME Shell screencast daemon
 *      is installed (some Mint setups, or when gnome-shell-screencast is pkg'd)
 *   2. Direct GStreamer pipeline    — launched as a subprocess via gst-launch-1.0
 *      This is the primary fallback for pure Cinnamon systems.
 */

const SCREENCAST_DBUS_NAME  = 'org.gnome.Shell.Screencast';
const SCREENCAST_DBUS_PATH  = '/org/gnome/Shell/Screencast';
const SCREENCAST_DBUS_IFACE = 'org.gnome.Shell.Screencast';

const SCREENCAST_IFACE_XML = `
<node>
  <interface name="org.gnome.Shell.Screencast">
    <method name="Screencast">
      <arg type="s" direction="in" name="file_template"/>
      <arg type="a{sv}" direction="in" name="options"/>
      <arg type="b" direction="out" name="success"/>
      <arg type="s" direction="out" name="filename_used"/>
    </method>
    <method name="ScreencastArea">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
      <arg type="i" direction="in" name="width"/>
      <arg type="i" direction="in" name="height"/>
      <arg type="s" direction="in" name="file_template"/>
      <arg type="a{sv}" direction="in" name="options"/>
      <arg type="b" direction="out" name="success"/>
      <arg type="s" direction="out" name="filename_used"/>
    </method>
    <method name="StopScreencast">
      <arg type="b" direction="out" name="success"/>
    </method>
  </interface>
</node>`;

// =============================================================================
// MAIN EXTENSION CLASS
// =============================================================================

let _extension = null;

function enable() {
    _extension = new BigShotExtension();
    _extension.enable();
}

function disable() {
    if (_extension) {
        _extension.disable();
        _extension = null;
    }
}

function init(metadata) {
    // metadata is passed by Cinnamon's extension loader
    return;
}

class BigShotExtension {
    enable() {
        this._parts              = [];
        this._availableConfigs   = null;
        this._currentConfigIndex = 0;
        this._recordingState     = 'idle'; // 'idle' | 'starting' | 'recording' | 'paused'
        this._recordingContext   = null;
        this._stopWatcherId      = 0;
        this._renameTimerId      = 0;
        this._pendingRename      = null;
        this._gstPipeline        = null;  // subprocess for direct GStreamer recording
        this._screencastProxy    = null;

        // Determine extension directory
        this._dir = this._getExtensionDir();

        // Override Print Screen keybinding → launch Big Shot screenshot UI
        this._installKeybindings();

        // Try to connect to the GNOME Screencast D-Bus service (optional)
        this._connectScreencastProxy();

        // Create UI parts (toolbar, indicator, etc.)
        // On Cinnamon these live in a separate floating window launched on demand,
        // so we just initialise the non-UI parts here.
        this._createParts();

        log('[Big Shot] Enabled on Cinnamon');
    }

    disable() {
        // Restore keybindings
        this._removeKeybindings();

        // Stop any active recording
        if (this._recordingState !== 'idle') {
            try { this._stopGstPipeline(); } catch(_e) { /* best-effort */ }
        }

        // Cancel timers
        if (this._stopWatcherId) {
            GLib.source_remove(this._stopWatcherId);
            this._stopWatcherId = 0;
        }
        if (this._renameTimerId) {
            GLib.source_remove(this._renameTimerId);
            this._renameTimerId = 0;
        }

        // Destroy parts
        for (const part of this._parts) {
            try { part.destroy(); } catch(e) { log(`[Big Shot] Part destroy error: ${e.message}`); }
        }
        this._parts = [];

        this._screencastProxy = null;
        log('[Big Shot] Disabled');
    }

    // =========================================================================
    // EXTENSION DIRECTORY DETECTION
    // =========================================================================

    _getExtensionDir() {
        // Cinnamon passes metadata.path for the extension directory.
        // When running via imports.ui.extensionSystem the UUID can be used
        // to look up the path from the loaded extensions map.
        try {
            const uuid = 'big-shot@bigcommunity.org';
            const extObj = imports.ui.extensionSystem.extensions[uuid];
            if (extObj && extObj.path)
                return Gio.File.new_for_path(extObj.path);
        } catch (_e) { /* fall through */ }

        // Fallback: look in standard Cinnamon extension paths
        const candidates = [
            GLib.build_filenamev([GLib.get_home_dir(), '.local', 'share', 'cinnamon', 'extensions', 'big-shot@bigcommunity.org']),
            '/usr/share/cinnamon/extensions/big-shot@bigcommunity.org',
        ];
        for (const p of candidates) {
            const f = Gio.File.new_for_path(p);
            if (f.query_exists(null)) return f;
        }
        return Gio.File.new_for_path(GLib.get_current_dir());
    }

    // =========================================================================
    // KEYBINDING — Override Print Screen
    // =========================================================================

    _installKeybindings() {
        // Save the current Print Screen binding values so we can restore them
        try {
            const schema = new Gio.Settings({ schema_id: SCREENSHOT_SCHEMA });
            this._origScreenshotBinding   = schema.get_strv(SCREENSHOT_KEY);
            this._origAreaBinding         = schema.get_strv(AREA_SCREENSHOT_KEY);
        } catch (e) {
            log(`[Big Shot] Could not read keybinding schema: ${e.message}`);
            this._origScreenshotBinding = null;
            this._origAreaBinding       = null;
        }

        // Register our own handler with Cinnamon's keybinding system.
        // Cinnamon 5/6: Main.keybindingManager.addHotkey / global.display methods
        this._bindPrintScreen();
    }

    _bindPrintScreen() {
        try {
            // Cinnamon 6.x approach: use Main.keybindingManager
            if (Main.keybindingManager) {
                Main.keybindingManager.addHotkey(
                    'big-shot-screenshot',
                    'Print',
                    () => this._launchBigShot('screenshot')
                );
                Main.keybindingManager.addHotkey(
                    'big-shot-area-screenshot',
                    '<Shift>Print',
                    () => this._launchBigShot('area')
                );
                this._usingKeybindingManager = true;
                log('[Big Shot] Keybindings registered via keybindingManager');
                return;
            }
        } catch (e) {
            log(`[Big Shot] keybindingManager approach failed: ${e.message}`);
        }

        // Cinnamon 5.x / Meta fallback: add_keybinding on global.display or global.window_manager
        try {
            const flags = Meta.KeyBindingFlags.NONE;
            const modes = Shell.ActionMode
                ? Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW
                : Meta.KeyBindingAction.NONE; // used as placeholder; flags differ by version

            global.display.add_keybinding(
                'big-shot-screenshot',
                new Gio.Settings({ schema_id: 'org.cinnamon.muffin.keybindings' }),
                flags,
                () => this._launchBigShot('screenshot')
            );
            this._usingDisplayKeybinding = true;
        } catch (e) {
            log(`[Big Shot] Meta keybinding approach failed: ${e.message}`);
        }
    }

    _removeKeybindings() {
        try {
            if (this._usingKeybindingManager && Main.keybindingManager) {
                Main.keybindingManager.removeHotkey('big-shot-screenshot');
                Main.keybindingManager.removeHotkey('big-shot-area-screenshot');
            }
        } catch (e) {
            log(`[Big Shot] Error removing keybindings: ${e.message}`);
        }

        try {
            if (this._usingDisplayKeybinding) {
                global.display.remove_keybinding('big-shot-screenshot');
            }
        } catch (e) {
            log(`[Big Shot] Error removing display keybinding: ${e.message}`);
        }

        // Restore original gnome-screenshot keybinding so Print Screen still works
        // after the extension is disabled.
        try {
            if (this._origScreenshotBinding !== null) {
                const schema = new Gio.Settings({ schema_id: SCREENSHOT_SCHEMA });
                schema.set_strv(SCREENSHOT_KEY, this._origScreenshotBinding);
            }
        } catch (e) {
            log(`[Big Shot] Could not restore keybindings: ${e.message}`);
        }
    }

    // =========================================================================
    // LAUNCH BIG SHOT SCREENSHOT UI
    // =========================================================================

    /**
     * Launch the Big Shot screenshot UI.
     * On Cinnamon we launch it as a separate GTK application that renders
     * a fullscreen overlay on the active monitor.  The UI communicates back
     * via a local Unix socket or temp file when the user clicks Save/Copy.
     *
     * If the GTK UI is not installed, we fall back to gnome-screenshot (the
     * Cinnamon default) with the --interactive flag.
     *
     * @param {'screenshot'|'area'|'window'} mode
     */
    _launchBigShot(mode) {
        // Check if big-shot-ui binary exists
        const uiBin = this._findBigShotUI();

        if (uiBin) {
            const argv = [uiBin, `--mode=${mode}`];
            try {
                const proc = Gio.Subprocess.new(argv,
                    Gio.SubprocessFlags.NONE);
                proc.wait_async(null, null);
                log(`[Big Shot] Launched UI: ${uiBin} --mode=${mode}`);
                return;
            } catch (e) {
                log(`[Big Shot] Failed to launch big-shot-ui: ${e.message}`);
            }
        }

        // Fallback: gnome-screenshot (Cinnamon ships this by default)
        this._launchFallbackScreenshot(mode);
    }

    _findBigShotUI() {
        const candidates = [
            GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'big-shot-ui']),
            '/usr/local/bin/big-shot-ui',
            '/usr/bin/big-shot-ui',
            this._dir ? GLib.build_filenamev([this._dir.get_path(), 'big-shot-ui']) : null,
        ].filter(Boolean);

        for (const p of candidates) {
            if (GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE))
                return p;
        }
        return null;
    }

    _launchFallbackScreenshot(mode) {
        let argv;
        switch (mode) {
        case 'area':
            argv = ['gnome-screenshot', '--area'];
            break;
        case 'window':
            argv = ['gnome-screenshot', '--window'];
            break;
        default:
            argv = ['gnome-screenshot', '--interactive'];
            break;
        }

        try {
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
            log(`[Big Shot] Fallback: launched ${argv.join(' ')}`);
        } catch (e) {
            log(`[Big Shot] Could not launch fallback screenshot tool: ${e.message}`);
            // Last resort: Cinnamon's built-in screenshot dbus call
            this._cinnamonScreenshotFallback(mode);
        }
    }

    _cinnamonScreenshotFallback(mode) {
        try {
            // Cinnamon exposes org.gnome.Shell / org.cinnamon on the session bus
            Gio.DBus.session.call(
                'org.cinnamon',
                '/org/cinnamon/Screenshot',
                'org.cinnamon.Screenshot',
                'Screenshot',
                new GLib.Variant('(bbs)', [false, true, '']),
                null,
                Gio.DBusCallFlags.NONE,
                -1,
                null,
                null
            );
        } catch (e) {
            log(`[Big Shot] DBus screenshot fallback failed: ${e.message}`);
        }
    }

    // =========================================================================
    // DBUS SCREENCAST PROXY
    // =========================================================================

    _connectScreencastProxy() {
        try {
            const ScreencastProxy = Gio.DBusProxy.makeProxyWrapper(SCREENCAST_IFACE_XML);
            this._screencastProxy = new ScreencastProxy(
                Gio.DBus.session,
                SCREENCAST_DBUS_NAME,
                SCREENCAST_DBUS_PATH,
                null
            );
            log('[Big Shot] Connected to org.gnome.Shell.Screencast proxy');
        } catch (e) {
            log(`[Big Shot] Screencast D-Bus proxy unavailable (will use direct GStreamer): ${e.message}`);
            this._screencastProxy = null;
        }
    }

    // =========================================================================
    // PARTS CREATION (non-UI parts only on Cinnamon; UI is external)
    // =========================================================================

    _createParts() {
        // Indicator — panel button showing recording timer
        if (PartIndicator) {
            this._indicator = new PartIndicator(null, this);
            this._parts.push(this._indicator);
        }

        // Audio — desktop + mic toggling
        if (PartAudio) {
            this._audio = new PartAudio(null, this);
            this._parts.push(this._audio);
        }

        // Framerate and downsize are settings-only in Cinnamon mode
        // (no native UI to inject into); read from GSettings or use defaults.
        this._framerate = 30;
        this._downsizeValue = 1.0;
        this._videoQuality = 'high';
    }

    // =========================================================================
    // RECORDING — Start / Stop / Pause / Resume
    // =========================================================================

    /**
     * Start a screencast recording.
     * Prefers the GNOME Screencast D-Bus proxy; falls back to a direct
     * gst-launch-1.0 subprocess if the proxy is unavailable.
     *
     * @param {Object} opts  Optional overrides: { framerate, downsize, quality, filePath }
     */
    startRecording(opts) {
        if (this._recordingState !== 'idle') {
            log('[Big Shot] Already recording');
            return;
        }

        this._detectPipelines();

        const framerate   = (opts && opts.framerate)  || this._framerate    || 30;
        const downsize    = (opts && opts.downsize)    || this._downsizeValue || 1.0;
        const quality     = (opts && opts.quality)     || this._videoQuality  || 'high';
        const filePath    = (opts && opts.filePath)    || this._defaultFilePath();

        if (this._availableConfigs.length === 0) {
            log('[Big Shot] No GStreamer pipeline available — cannot record');
            return;
        }

        const config   = this._availableConfigs[0];
        const pipeline = this._makePipelineString(config, `${framerate}/1`, downsize, quality);

        if (this._screencastProxy) {
            this._startViaProxy(filePath, pipeline, framerate, config);
        } else {
            this._startViaGstLaunch(filePath, pipeline, config);
        }
    }

    _startViaProxy(filePath, pipeline, framerate, config) {
        const options = {
            pipeline:  new GLib.Variant('s', pipeline),
            framerate: new GLib.Variant('i', framerate),
        };

        this._recordingState = 'starting';
        this._indicator && this._indicator.onPipelineStarting && this._indicator.onPipelineStarting();

        try {
            this._screencastProxy.ScreencastSync(filePath, options);
            this._recordingState = 'recording';
            this._recordingContext = { config, filePath };
            this._indicator && this._indicator.onPipelineReady && this._indicator.onPipelineReady();
            this._indicator && this._indicator.onRecordingStarted && this._indicator.onRecordingStarted();
            log('[Big Shot] Recording started via D-Bus proxy');
        } catch (e) {
            this._recordingState = 'idle';
            log(`[Big Shot] D-Bus screencast failed: ${e.message}`);
            // Retry with direct GStreamer
            this._startViaGstLaunch(filePath, pipeline, config);
        }
    }

    _startViaGstLaunch(filePath, pipeline, config) {
        const muxer   = MUXERS[config.ext];
        const sink    = `filesink location="${filePath}"`;
        const fullCmd = `gst-launch-1.0 pipewiresrc ! ${pipeline} ! ${muxer} ! ${sink}`;

        log(`[Big Shot] Direct GStreamer: ${fullCmd}`);

        try {
            this._gstPipeline = Gio.Subprocess.new(
                ['bash', '-c', fullCmd],
                Gio.SubprocessFlags.NONE
            );
            this._recordingState = 'recording';
            this._recordingContext = { config, filePath };
            this._indicator && this._indicator.onPipelineReady && this._indicator.onPipelineReady();
            this._indicator && this._indicator.onRecordingStarted && this._indicator.onRecordingStarted();
            this._watchForGstStop();
        } catch (e) {
            this._recordingState = 'idle';
            log(`[Big Shot] gst-launch failed: ${e.message}`);
        }
    }

    _watchForGstStop() {
        if (!this._gstPipeline) return;
        this._gstPipeline.wait_async(null, (_proc, result) => {
            try { this._gstPipeline.wait_finish(result); } catch (_e) { /* */ }
            this._gstPipeline = null;
            this._onFinalStop();
        });
    }

    stopRecording() {
        if (this._recordingState === 'idle') return;

        // Resume if paused before stopping so the file is finalised properly
        if (this._recordingState === 'paused')
            this._signalProcess('CONT');

        if (this._screencastProxy) {
            try { this._screencastProxy.StopScreencastSync(); } catch (_e) { /* */ }
        }
        this._stopGstPipeline();
        this._onFinalStop();
    }

    _stopGstPipeline() {
        if (this._gstPipeline) {
            try {
                this._gstPipeline.send_signal(15); // SIGTERM
            } catch (_e) { /* */ }
            this._gstPipeline = null;
        }
    }

    pauseRecording() {
        if (this._recordingState !== 'recording') return;
        if (this._signalProcess('STOP')) {
            this._recordingState = 'paused';
            this._indicator && this._indicator.onPaused && this._indicator.onPaused();
        }
    }

    resumeRecording() {
        if (this._recordingState !== 'paused') return;
        if (this._signalProcess('CONT')) {
            this._recordingState = 'recording';
            this._indicator && this._indicator.onResumed && this._indicator.onResumed();
        }
    }

    togglePauseRecording() {
        if (this._recordingState === 'recording')   this.pauseRecording();
        else if (this._recordingState === 'paused') this.resumeRecording();
    }

    _onFinalStop() {
        if (this._recordingState === 'idle') return;
        this._recordingState = 'idle';
        this._indicator && this._indicator.onRecordingStopped && this._indicator.onRecordingStopped();
        this._recordingContext = null;
    }

    // =========================================================================
    // PROCESS SIGNALLING (pause/resume via SIGSTOP/SIGCONT)
    // =========================================================================

    _findScreencastPid() {
        try {
            // Try the GNOME screencast service first
            let [, stdout] = GLib.spawn_command_line_sync('pgrep -f org.gnome.Shell.Screencast');
            let pid = parseInt(imports.byteArray.toString(stdout).trim().split('\n')[0], 10);
            if (!isNaN(pid) && pid > 0) return pid;

            // Fall back to gst-launch subprocess
            if (this._gstPipeline) {
                // Gio.Subprocess in Cinnamon's GJS may not expose get_identifier()
                // consistently across versions, so use a pgrep fallback.
                [, stdout] = GLib.spawn_command_line_sync('pgrep -f gst-launch-1.0');
                pid = parseInt(imports.byteArray.toString(stdout).trim().split('\n')[0], 10);
                return isNaN(pid) ? 0 : pid;
            }
        } catch (_e) { /* */ }
        return 0;
    }

    _signalProcess(signal) {
        const pid = this._findScreencastPid();
        if (!pid) {
            log('[Big Shot] Process not found for signal');
            return false;
        }
        try {
            let [ok] = GLib.spawn_command_line_sync(`kill -${signal} ${pid}`);
            return ok;
        } catch (e) {
            log(`[Big Shot] Signal failed: ${e.message}`);
            return false;
        }
    }

    // =========================================================================
    // PIPELINE DETECTION (same logic as GNOME version)
    // =========================================================================

    _detectPipelines() {
        if (this._availableConfigs !== null) return;

        this._gpuVendors = detectGpuVendors();
        const vendorSet  = new Set(this._gpuVendors);

        const gpuConfigs = [];
        const swConfigs  = [];

        for (const config of VIDEO_PIPELINES) {
            if (!checkPipeline(config)) continue;
            if (config.vendors.length === 0) {
                swConfigs.push(config);
            } else if (config.vendors.some(v => vendorSet.has(v))) {
                gpuConfigs.push(config);
            }
        }

        this._availableConfigs = [...gpuConfigs, ...swConfigs];

        if (this._availableConfigs.length === 0)
            log('[Big Shot] No compatible GStreamer pipeline found!');
        else
            log(`[Big Shot] Available pipelines: ${this._availableConfigs.map(c => c.id).join(', ')}`);
    }

    // =========================================================================
    // PIPELINE STRING BUILDER (identical to GNOME version)
    // =========================================================================

    _makePipelineString(config, framerateCaps, downsize, quality) {
        let video = config.src.replace('FRAMERATE_CAPS', framerateCaps);
        const preset = QUALITY_PRESETS[quality] || QUALITY_PRESETS.high;
        video += ` ! ${config.enc(preset)}`;

        if (downsize < 1.0) {
            try {
                const monitor = global.screen.get_current_monitor
                    ? global.screen.get_current_monitor()
                    : global.display.get_current_monitor();
                const geom = global.screen.get_monitor_geometry
                    ? global.screen.get_monitor_geometry(monitor)
                    : global.display.get_monitor_geometry(monitor);
                const targetW = Math.round(geom.width  * downsize);
                const targetH = Math.round(geom.height * downsize);
                video = video.replace(
                    /queue/,
                    `queue ! videoscale ! video/x-raw,width=${targetW},height=${targetH}`
                );
            } catch (e) {
                log(`[Big Shot] Downsize geometry error: ${e.message}`);
            }
        }

        const audioInput = this._audio && this._audio.makeAudioInput
            ? this._audio.makeAudioInput()
            : null;
        const ext   = config.ext;
        const muxer = MUXERS[ext];

        if (audioInput) {
            const audioPipeline = ext === 'mp4' ? AUDIO_PIPELINE.aac : AUDIO_PIPELINE.vorbis;
            const videoSeg = `${video} ! queue ! mux.`;
            const audioSeg = `${audioInput} ! ${audioPipeline} ! mux.`;
            const muxDef   = `${muxer} name=mux`;
            return `${videoSeg} ${audioSeg} ${muxDef}`;
        }

        return `${video} ! ${muxer}`;
    }

    // =========================================================================
    // FILE HELPERS
    // =========================================================================

    _defaultFilePath() {
        const time = GLib.DateTime.new_now_local();
        const stamp = time.format('%Y-%m-%d_%H-%M-%S');
        const dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS)
            || GLib.build_filenamev([GLib.get_home_dir(), 'Videos']);
        GLib.mkdir_with_parents(dir, 0o755);
        return GLib.build_filenamev([dir, `Screencast_${stamp}.mp4`]);
    }

    // =========================================================================
    // NOTIFICATIONS
    // =========================================================================

    _showNotification(title, body) {
        try {
            // Cinnamon notification API
            const source = new MessageTray.Source(title, 'camera-video-symbolic');
            Main.messageTray.add(source);
            const notification = new MessageTray.Notification(source, title, body);
            source.notify(notification);
        } catch (e) {
            log(`[Big Shot] Notification failed: ${e.message}`);
        }
    }
}
