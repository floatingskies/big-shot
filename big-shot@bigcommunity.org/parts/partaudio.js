/**
 * Big Shot — Audio recording (Desktop + Mic) — Cinnamon port
 *
 * Uses PulseAudio via Gvc.MixerControl to detect audio devices.
 * On Cinnamon the UI buttons are not injected into a ScreenshotUI;
 * instead, audio state is managed programmatically and exposed to the
 * external big-shot-ui process through a simple settings/state object.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const GLib    = imports.gi.GLib;
const Gio     = imports.gi.Gio;
const GObject = imports.gi.GObject;
const Gvc     = imports.gi.Gvc;

const { PartUI } = require('./partbase');

var PartAudio = class PartAudio extends PartUI {
    constructor(screenshotUI, extension) {
        super(screenshotUI, extension);

        this._desktopEnabled = false;
        this._micEnabled     = false;
        this._desktopDevice  = null;
        this._micDevice      = null;
        this._selectedMicId  = null;

        // Initialize audio mixer
        this._mixer = new Gvc.MixerControl({ name: 'Big Shot Audio' });
        this._mixer.open();

        this._mixerReadyId = this._mixer.connect('state-changed', () => {
            if (this._mixer.get_state() === Gvc.MixerControlState.READY)
                this._onMixerReady();
        });
    }

    _disconnectMixer() {
        if (this._mixerReadyId) {
            this._mixer && this._mixer.disconnect(this._mixerReadyId);
            this._mixerReadyId = null;
        }
    }

    _onMixerReady() {
        this._disconnectMixer();
        this._updateDevices();
    }

    _updateDevices() {
        const defaultSink = this._mixer.get_default_sink();
        if (defaultSink)
            this._desktopDevice = defaultSink.get_name() + '.monitor';

        const defaultSource = this._mixer.get_default_source();
        if (defaultSource)
            this._micDevice = defaultSource.get_name();
    }

    // Public API used by extension.js ─────────────────────────────────────────

    set desktopEnabled(v) { this._desktopEnabled = !!v; }
    get desktopEnabled()  { return this._desktopEnabled; }

    set micEnabled(v)     { this._micEnabled = !!v; }
    get micEnabled()      { return this._micEnabled; }

    set selectedMicId(id) { this._selectedMicId = id; }

    enumerateMicrophones() {
        try {
            const sources = this._mixer.get_sources();
            const mics    = [];
            for (const src of sources) {
                const name = src.get_name() || '';
                if (name.endsWith('.monitor')) continue;
                mics.push({
                    id:          src.get_id(),
                    name:        src.get_description() || name,
                    pulseDevice: name,
                });
            }
            return mics;
        } catch (_e) {
            return [];
        }
    }

    _resolveMicDevice() {
        if (this._selectedMicId !== null) {
            try {
                const stream = this._mixer.lookup_stream_id(this._selectedMicId);
                if (stream) return stream.get_name();
            } catch (_e) { /* */ }
        }
        return this._micDevice;
    }

    makeAudioInput() {
        this._updateDevices();

        const micDeviceName = this._resolveMicDevice();
        const desktopActive = this._desktopEnabled && this._desktopDevice;
        const micActive     = this._micEnabled && micDeviceName;

        if (!desktopActive && !micActive) return null;

        let desktopSource   = null;
        let desktopChannels = 2;
        if (desktopActive) {
            try {
                const sink = this._mixer.get_default_sink();
                if (sink) {
                    const cm = sink.get_channel_map();
                    if (cm) desktopChannels = cm.get_num_channels();
                }
            } catch (_e) { /* */ }
            desktopSource = [
                `pulsesrc device=${this._desktopDevice} provide-clock=false`,
                `capsfilter caps=audio/x-raw,channels=${desktopChannels}`,
                'audioconvert',
                'queue',
            ].join(' ! ');
        }

        let micSource = null;
        if (micActive) {
            let micChannels = 2;
            try {
                if (this._selectedMicId !== null) {
                    const stream = this._mixer.lookup_stream_id(this._selectedMicId);
                    if (stream) {
                        const cm = stream.get_channel_map();
                        if (cm) micChannels = cm.get_num_channels();
                    }
                } else {
                    const src = this._mixer.get_default_source();
                    if (src) {
                        const cm = src.get_channel_map();
                        if (cm) micChannels = cm.get_num_channels();
                    }
                }
            } catch (_e) { /* */ }

            micSource = [
                `pulsesrc device=${micDeviceName} provide-clock=false`,
                `capsfilter caps=audio/x-raw,channels=${micChannels}`,
                'audioconvert',
                'queue',
            ].join(' ! ');
        }

        if (desktopSource && micSource) {
            return [
                `${desktopSource} ! audiomixer name=am latency=100000000`,
                `${micSource} ! am.`,
                `am. ! capsfilter caps=audio/x-raw,channels=${desktopChannels} ! audioconvert ! queue`,
            ].join(' ');
        }

        return desktopSource || micSource;
    }

    destroy() {
        this._disconnectMixer();
        try { this._mixer && this._mixer.close(); } catch (_e) { /* */ }
        this._mixer = null;
        super.destroy();
    }
};
