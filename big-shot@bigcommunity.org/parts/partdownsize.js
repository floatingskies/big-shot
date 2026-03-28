/**
 * Big Shot — Resolution downsize selector (Cinnamon port)
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

const { PartPopupSelect } = require('./partbase');

var PartDownsize = class PartDownsize extends PartPopupSelect {
    constructor(screenshotUI, extension) {
        super(
            screenshotUI,
            extension,
            [1.00, 0.75, 0.50, 0.33],
            1.00,
            (v) => `${Math.round(v * 100)}%`,
            'Recording resolution'
        );
    }
};
