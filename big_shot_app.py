#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — GTK4 Application wrapper
Handles lifecycle, argument parsing, and top-level window management.

SPDX-License-Identifier: GPL-2.0-or-later
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gio', '2.0')

from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib
import sys
import os
import argparse

from ui.screenshot_window import ScreenshotWindow
from ui.screencast_window import ScreencastWindow


class BigShotApplication(Gtk.Application):
    """
    Top-level GTK4 Application.

    Modes:
        screenshot  — Full-screen capture with annotation toolbar
        area        — Interactive area selection then annotate
        window      — Window picker then annotate
        screencast  — Video recording control panel
    """

    APP_ID = 'org.bigcommunity.BigShot'

    def __init__(self):
        super().__init__(
            application_id=self.APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._mode = 'screenshot'
        self._window = None

        self.add_main_option(
            'mode', ord('m'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            'Launch mode: screenshot, area, window, screencast',
            'MODE',
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        if options.contains('mode'):
            self._mode = options.lookup_value('mode').get_string()
        self.activate()
        return 0

    def do_activate(self):
        if self._window is not None:
            self._window.present()
            return

        if self._mode == 'screencast':
            self._window = ScreencastWindow(application=self)
        else:
            self._window = ScreenshotWindow(
                application=self,
                mode=self._mode,
            )

        self._window.connect('destroy', self._on_window_destroy)
        self._window.present()

    def _on_window_destroy(self, _win):
        self._window = None
        self.quit()
