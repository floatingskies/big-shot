/**
 * Big Shot — Base classes for extension modules (Parts)
 * Cinnamon port: uses imports.gi.* instead of gi:// ESM imports.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const Clutter = imports.gi.Clutter;
const GLib    = imports.gi.GLib;
const St      = imports.gi.St;

// =============================================================================
// PartBase — Simplest base class
// =============================================================================

var PartBase = class PartBase {
    constructor() {
        this._destroyed = false;
    }

    destroy() {
        this._destroyed = true;
    }
};

// =============================================================================
// PartUI — Base with optional ScreenshotUI awareness
//
// On Cinnamon there is no ScreenshotUI object to inject into, so screenshotUI
// may be null.  All subclasses must handle this gracefully.
// =============================================================================

var PartUI = class PartUI extends PartBase {
    constructor(screenshotUI, extension) {
        super();
        this._ui      = screenshotUI; // may be null on Cinnamon
        this._ext     = extension;
        this._signals = [];
        this._isCastMode = false;

        // On GNOME Shell we detect mode from _shotButton.  On Cinnamon we skip
        // this because there is no native ScreenshotUI to introspect.
        if (this._ui) {
            const shotBtn = this._ui._shotButton;
            if (shotBtn) {
                this._isCastMode = !shotBtn.checked;
                this._connectSignal(shotBtn, 'notify::checked', () => {
                    this._isCastMode = !shotBtn.checked;
                    this._onModeChanged(this._isCastMode);
                });
            }
        }
    }

    _connectSignal(obj, signal, callback) {
        const id = obj.connect(signal, callback);
        this._signals.push({ obj, id });
        return id;
    }

    _onModeChanged(_isCast) {
        // Override in subclasses
    }

    destroy() {
        for (const { obj, id } of this._signals) {
            try { obj.disconnect(id); } catch (_e) { /* Already disconnected */ }
        }
        this._signals = [];
        super.destroy();
    }
};

// =============================================================================
// PartPopupSelect — Button with popup menu for value selection
// Cinnamon port: same logic, but inserts into extension's own panel if no
// native screenshotUI is available.
// =============================================================================

var PartPopupSelect = class PartPopupSelect extends PartUI {
    constructor(screenshotUI, extension, options, defaultValue, labelFn, tooltipText) {
        super(screenshotUI, extension);

        this._options  = options;
        this._value    = defaultValue;
        this._labelFn  = labelFn;

        // On Cinnamon we expose the value via a simple GSettings or in-memory
        // property; no UI widget is created if there is no screenshotUI host.
        if (!this._ui) return;

        this._button = new St.Button({
            style_class: 'screenshot-ui-show-pointer-button',
            toggle_mode: false,
            can_focus:   true,
            child: new St.Label({
                text:    this._labelFn(this._value),
                y_align: Clutter.ActorAlign.CENTER,
            }),
        });

        this._button.connect('clicked', () => this._showPopup());

        this._popup = new St.BoxLayout({
            style_class: 'screenshot-ui-type-button-container',
            vertical:    true,
            visible:     false,
            reactive:    true,
        });
        this._popup.set_style(
            'background: rgba(30,30,30,0.95); border-radius: 12px; padding: 4px;'
        );

        for (const opt of this._options) {
            const item = new St.Button({
                style_class: 'screenshot-ui-show-pointer-button',
                label:       this._labelFn(opt),
                can_focus:   true,
            });
            item.connect('clicked', () => {
                this._value = opt;
                this._button.child.text = this._labelFn(opt);
                this._popup.visible = false;
            });
            this._popup.add_child(item);
        }

        const showPointerContainer = this._ui._showPointerButtonContainer;
        if (showPointerContainer) {
            showPointerContainer.insert_child_at_index(this._button, 0);
        } else {
            const bottomGroup = this._ui._panel
                || this._ui._bottomAreaGroup
                || this._ui._content;
            if (bottomGroup) bottomGroup.add_child(this._button);
        }
        this._ui.add_child(this._popup);

        this._button.visible = false;
        this._popup.visible  = false;
    }

    get value() {
        return this._value;
    }

    _showPopup() {
        this._popup.visible = !this._popup.visible;
        if (this._popup.visible) {
            const [bx, by] = this._button.get_transformed_position();
            this._popup.set_position(bx, by - this._popup.height - 8);
        }
    }

    _onModeChanged(isCast) {
        if (this._button) this._button.visible = isCast;
        if (!isCast && this._popup) this._popup.visible = false;
    }

    destroy() {
        if (this._popup) {
            const p = this._popup.get_parent();
            if (p) p.remove_child(this._popup);
            this._popup.destroy();
            this._popup = null;
        }
        if (this._button) {
            const p = this._button.get_parent();
            if (p) p.remove_child(this._button);
            this._button.destroy();
            this._button = null;
        }
        super.destroy();
    }
};
