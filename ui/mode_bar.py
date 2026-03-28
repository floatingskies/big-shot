#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — Mode Bar

Bottom-centered pill with Screenshot / Area / Window mode buttons,
mirroring the GNOME Shell screenshot UI's _typeButtonContainer.

SPDX-License-Identifier: GPL-2.0-or-later
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GObject


class ModeBar(Gtk.Box):
    """
    Horizontal pill at the bottom of the screenshot overlay.
    Emits 'mode-changed' with the new mode string when the user switches.
    """

    __gsignals__ = {
        'mode-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    MODES = [
        ('screenshot', 'camera-photo-symbolic',      'Screenshot'),
        ('area',       'select-rectangle-symbolic',  'Selection'),
        ('window',     'window-symbolic',             'Window'),
    ]

    def __init__(self, current_mode='screenshot'):
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
        )
        self._current_mode = current_mode
        self._buttons = {}

        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_margin_bottom(24)

        self.add_css_class('bigshot-modebar')
        self._apply_style()
        self._build()

    def _build(self):
        for mode_id, icon_name, label in self.MODES:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(22)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class('bigshot-mode-label')
            box.append(img)
            box.append(lbl)

            btn = Gtk.ToggleButton()
            btn.set_child(box)
            btn.add_css_class('bigshot-mode-btn')
            btn.set_active(mode_id == self._current_mode)
            btn.connect('toggled', self._on_toggled, mode_id)
            self.append(btn)
            self._buttons[mode_id] = btn

    def _on_toggled(self, btn, mode_id):
        if btn.get_active():
            for mid, b in self._buttons.items():
                if mid != mode_id and b.get_active():
                    b.set_active(False)
            self._current_mode = mode_id
            self.emit('mode-changed', mode_id)
        else:
            # Prevent deselecting the current mode by clicking it again
            if self._current_mode == mode_id:
                btn.set_active(True)

    def _apply_style(self):
        css = b"""
        .bigshot-modebar {
            background: rgba(24, 24, 24, 0.88);
            border-radius: 18px;
            border: 1px solid rgba(255,255,255,0.09);
            padding: 6px 14px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.6);
        }
        .bigshot-mode-btn {
            border-radius: 12px;
            padding: 6px 14px;
            background: transparent;
            border: none;
            color: white;
            min-width: 70px;
        }
        .bigshot-mode-btn:hover {
            background: rgba(255,255,255,0.10);
        }
        .bigshot-mode-btn:checked {
            background: rgba(53, 132, 228, 0.55);
            border: 1px solid rgba(53, 132, 228, 0.8);
        }
        .bigshot-mode-label {
            font-size: 11px;
            color: rgba(255,255,255,0.85);
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
