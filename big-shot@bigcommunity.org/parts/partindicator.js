/**
 * Big Shot — Panel indicator during recording (Cinnamon port)
 *
 * Shows a pause/resume button in the Cinnamon panel with elapsed timer.
 * Uses Cinnamon's Applet API for panel integration instead of GNOME Shell's
 * PanelMenu.Button.
 *
 * Cinnamon differences:
 *  - imports.ui.applet replaces imports.ui.panelMenu
 *  - Main.panel.addToStatusArea → applet added via the extension's metadata
 *  - StatusIconDispatcher or panel zones used instead of Main.panel._rightBox
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const Clutter = imports.gi.Clutter;
const GLib    = imports.gi.GLib;
const St      = imports.gi.St;
const Main    = imports.ui.main;

// Try Cinnamon-specific panel APIs
let Applet = null;
try { Applet = imports.ui.applet; } catch (_e) { /* not available in all versions */ }

const { PartUI } = require('./partbase');

var PartIndicator = class PartIndicator extends PartUI {
    constructor(screenshotUI, extension) {
        super(screenshotUI, extension);
        this._isReady       = false;
        this._panelWidget   = null;  // St.Widget added directly to Cinnamon panel
        this._timerId       = 0;
        this._elapsed       = 0;
        this._pausedElapsed = 0;
        this._isPaused      = false;
    }

    onPipelineStarting() {
        this._isReady = false;
    }

    onPipelineReady() {
        this._isReady = true;
    }

    onRecordingStarted() {
        this._elapsed       = 0;
        this._pausedElapsed = 0;
        this._isPaused      = false;
        this._createPanelWidget();
        this._startTimer();
    }

    onPaused() {
        this._isPaused       = true;
        this._pausedElapsed += this._elapsed;
        this._elapsed        = 0;
        this._stopTimer();
        this._updateWidget();
    }

    onResumed() {
        this._isPaused = false;
        this._elapsed  = 0;
        this._startTimer();
        this._updateWidget();
    }

    onRecordingStopped() {
        this._stopTimer();
        this._destroyPanelWidget();
        this._elapsed       = 0;
        this._pausedElapsed = 0;
        this._isPaused      = false;
    }

    // ── Panel widget ──────────────────────────────────────────────────────────

    _createPanelWidget() {
        this._destroyPanelWidget();

        // Build a small St.BoxLayout with timer + icon
        const box = new St.BoxLayout({
            style:    'spacing: 4px;',
            reactive: true,
        });

        this._timerLabel = new St.Label({
            text:    '00:00',
            y_align: Clutter.ActorAlign.CENTER,
            style:   'font-size: 12px; font-variant-numeric: tabular-nums;',
        });
        box.add_child(this._timerLabel);

        this._icon = new St.Icon({
            icon_name:  'media-playback-pause-symbolic',
            icon_size:  16,
            style_class: 'system-status-icon',
        });
        box.add_child(this._icon);

        box.connect('button-press-event', () => {
            this._ext && this._ext.togglePauseRecording
                && this._ext.togglePauseRecording();
            return Clutter.EVENT_STOP;
        });

        this._panelWidget = box;

        // Add to Cinnamon's right panel box.
        // Cinnamon 5/6: Main.panel._rightBox is an St.BoxLayout
        try {
            const rightBox = Main.panel._rightBox
                || Main.panel.actor  // older Cinnamon
                || null;
            if (rightBox && rightBox.add_child) {
                rightBox.insert_child_at_index(box, 0);
                this._panelParent = rightBox;
            } else {
                // Ultimate fallback: add to the stage
                Main.uiGroup.add_child(box);
                box.set_position(
                    global.stage.width - 120,
                    4
                );
                this._panelParent = Main.uiGroup;
            }
        } catch (e) {
            log(`[Big Shot Indicator] Panel insertion failed: ${e.message}`);
        }
    }

    _destroyPanelWidget() {
        if (this._panelWidget) {
            try {
                if (this._panelParent)
                    this._panelParent.remove_child(this._panelWidget);
            } catch (_e) { /* */ }
            this._panelWidget.destroy();
            this._panelWidget  = null;
            this._panelParent  = null;
        }
        this._icon        = null;
        this._timerLabel  = null;
    }

    _updateWidget() {
        if (!this._icon) return;
        if (this._isPaused) {
            this._icon.icon_name = 'media-playback-start-symbolic';
            if (this._timerLabel)
                this._timerLabel.set_style(
                    'font-size: 12px; font-variant-numeric: tabular-nums; color: #f9c440;'
                );
        } else {
            this._icon.icon_name = 'media-playback-pause-symbolic';
            if (this._timerLabel)
                this._timerLabel.set_style(
                    'font-size: 12px; font-variant-numeric: tabular-nums;'
                );
        }
    }

    // ── Timer ─────────────────────────────────────────────────────────────────

    _startTimer() {
        this._stopTimer();
        this._timerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
            this._elapsed++;
            this._updateTimerLabel();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopTimer() {
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
    }

    _updateTimerLabel() {
        if (!this._timerLabel) return;
        const total   = this._pausedElapsed + this._elapsed;
        const minutes = Math.floor(total / 60);
        const seconds = total % 60;
        this._timerLabel.text =
            `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    destroy() {
        this._stopTimer();
        this._destroyPanelWidget();
        super.destroy();
    }
};
