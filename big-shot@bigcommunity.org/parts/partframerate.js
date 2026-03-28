/**
 * Big Shot — Framerate selector (Cinnamon port)
 *
 * On Cinnamon the value is stored as a plain property; no UI widget
 * is injected because there is no native ScreenshotUI to inject into.
 * The big-shot-ui GTK process reads this value through the D-Bus
 * settings interface or a shared state file.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const { PartPopupSelect } = require('./partbase');

var PartFramerate = class PartFramerate extends PartPopupSelect {
    constructor(screenshotUI, extension) {
        super(
            screenshotUI,
            extension,
            [15, 24, 30, 60],
            30,
            (v) => `${v} FPS`,
            'Frames per second'
        );
    }
};
