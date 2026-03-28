#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — Screenshot Window

A fullscreen translucent overlay that:
  1. Takes a screenshot of all monitors via the XDG Screenshot portal or
     gnome-screenshot fallback.
  2. Displays it as the window background (the "frozen screen" effect).
  3. In 'area' mode shows a rubber-band selection box.
  4. In 'window' mode highlights clickable windows.
  5. Provides a floating annotation toolbar (pen, arrow, rect, circle,
     text, highlight, censor/blur, number, eraser, undo/redo).
  6. Action buttons: Copy to Clipboard, Save, Save As.

Annotation rendering is done directly onto a Cairo surface that overlays
the captured screenshot using a Gtk.DrawingArea.

SPDX-License-Identifier: GPL-2.0-or-later
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('cairo', '1.0')

from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio
import cairo
import math
import os
import time
import subprocess
import tempfile
import threading

from ui.annotation_toolbar import AnnotationToolbar
from ui.mode_bar import ModeBar
from drawing.canvas import DrawingCanvas
from drawing.tools import TOOLS


# ── Constants ──────────────────────────────────────────────────────────────────

HANDLE_SIZE   = 10       # px — crop handle radius
MIN_SELECTION = 16       # px — minimum rubber-band area
ANIM_DURATION = 150      # ms — fade-in duration


class ScreenshotWindow(Gtk.Window):
    """
    Fullscreen screenshot + annotation window.
    """

    def __init__(self, application, mode='screenshot'):
        super().__init__(application=application)
        self._mode         = mode          # 'screenshot' | 'area' | 'window'
        self._screenshot   = None          # GdkPixbuf of captured screen
        self._surface      = None          # Cairo surface of screenshot
        self._canvas       = None          # DrawingCanvas instance
        self._selection    = None          # {x, y, w, h} for area mode
        self._drag_start   = None          # (x, y) drag origin
        self._drag_active  = False
        self._confirmed    = False         # area confirmed by Enter/double-click
        self._cursor_type  = 'crosshair'

        self._setup_window()
        self._capture_screen()

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.set_title('Big Shot')
        self.set_decorated(False)
        self.set_resizable(False)

        # Fullscreen on the current monitor
        display  = Gdk.Display.get_default()
        monitor  = display.get_monitors()[0]   # primary
        geom     = monitor.get_geometry()
        self._monitor_x = geom.x
        self._monitor_y = geom.y
        self._monitor_w = geom.width
        self._monitor_h = geom.height

        self.set_default_size(self._monitor_w, self._monitor_h)

        # Semi-transparent black overlay in area/window mode; opaque in screenshot mode
        if self._mode in ('area', 'window'):
            self.set_opacity(0.0)   # starts transparent, fades in after capture

        # Main overlay: screenshot canvas + toolbar
        self._overlay = Gtk.Overlay()
        self.set_child(self._overlay)

        # Drawing area — renders screenshot + annotations
        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._on_draw)
        self._overlay.set_child(self._drawing_area)

        # Annotation toolbar (floating, draggable)
        self._toolbar = AnnotationToolbar()
        self._toolbar.connect('tool-changed',   self._on_tool_changed)
        self._toolbar.connect('color-changed',  self._on_color_changed)
        self._toolbar.connect('size-changed',   self._on_size_changed)
        self._toolbar.connect('action-copy',    self._on_copy)
        self._toolbar.connect('action-save',    self._on_save)
        self._toolbar.connect('action-save-as', self._on_save_as)
        self._toolbar.connect('action-close',   self._on_close)
        self._toolbar.connect('undo',           self._on_undo)
        self._toolbar.connect('redo',           self._on_redo)
        self._overlay.add_overlay(self._toolbar)
        self._overlay.set_overlay_pass_through(self._toolbar, False)

        # Mode bar (Screenshot / Area / Window buttons at the bottom)
        if self._mode != 'area':
            self._mode_bar = ModeBar(current_mode=self._mode)
            self._mode_bar.connect('mode-changed', self._on_mode_changed)
            self._overlay.add_overlay(self._mode_bar)

        # Drawing canvas (annotation state machine)
        self._canvas = DrawingCanvas()

        # Input controllers
        self._setup_controllers()

        # Keyboard shortcuts
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_ctl)

        # Hide toolbar in area mode until selection is confirmed
        if self._mode == 'area':
            self._toolbar.set_visible(False)

    def _setup_controllers(self):
        """Attach pointer + gesture controllers to the drawing area."""
        # Pointer motion (for rubber-band, cursor changes)
        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        self._drawing_area.add_controller(motion)

        # Click / drag
        drag = Gtk.GestureDrag()
        drag.connect('drag-begin',  self._on_drag_begin)
        drag.connect('drag-update', self._on_drag_update)
        drag.connect('drag-end',    self._on_drag_end)
        self._drawing_area.add_controller(drag)

        # Double-click to confirm area
        click = Gtk.GestureClick()
        click.set_n_points(1)
        click.connect('released', self._on_click)
        self._drawing_area.add_controller(click)

    # ── Screenshot capture ─────────────────────────────────────────────────────

    def _capture_screen(self):
        """Capture the screen asynchronously, then show the window."""
        threading.Thread(target=self._do_capture, daemon=True).start()

    def _do_capture(self):
        """Background thread: capture using scrot / gnome-screenshot."""
        tmp = tempfile.mktemp(suffix='.png', prefix='bigshot-')
        captured = False

        # Try scrot first (lightweight, available on most Mint systems)
        for cmd in [
            ['scrot', '--overwrite', tmp],
            ['gnome-screenshot', '--file', tmp],
            ['import', '-window', 'root', tmp],   # ImageMagick
        ]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.returncode == 0 and os.path.exists(tmp):
                    captured = True
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        GLib.idle_add(self._on_capture_done, tmp if captured else None)

    def _on_capture_done(self, tmp_path):
        """Main thread: load captured PNG and show the window."""
        if tmp_path and os.path.exists(tmp_path):
            try:
                self._screenshot = GdkPixbuf.Pixbuf.new_from_file(tmp_path)
                os.unlink(tmp_path)
            except Exception as e:
                print(f'[Big Shot] Failed to load screenshot: {e}')
                self._screenshot = None
        else:
            # Create a blank pixbuf as fallback
            self._screenshot = GdkPixbuf.Pixbuf.new(
                GdkPixbuf.Colorspace.RGB, False, 8,
                self._monitor_w, self._monitor_h
            )
            self._screenshot.fill(0x222222ff)

        # Build Cairo surface from pixbuf
        self._surface = self._pixbuf_to_surface(self._screenshot)

        # In 'screenshot' mode: immediately show the toolbar and full canvas
        if self._mode == 'screenshot':
            self._confirmed = True
            self._selection = {
                'x': 0, 'y': 0,
                'w': self._monitor_w,
                'h': self._monitor_h,
            }

        self.fullscreen()
        self.present()
        self._drawing_area.queue_draw()
        return GLib.SOURCE_REMOVE

    def _pixbuf_to_surface(self, pixbuf):
        """Convert GdkPixbuf to a Cairo ImageSurface."""
        w = pixbuf.get_width()
        h = pixbuf.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)

        # GdkPixbuf → Cairo: paint via Gdk
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        return surface

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _on_draw(self, _area, cr, w, h):
        """Main draw callback — composes screenshot + dimming + annotations."""
        if self._surface is None:
            cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.paint()
            return

        # 1. Draw the screenshot
        cr.set_source_surface(self._surface, 0, 0)
        cr.paint()

        if self._mode == 'area' and not self._confirmed:
            # 2. Darken everything outside the selection
            cr.set_source_rgba(0, 0, 0, 0.5)
            cr.paint()

            sel = self._selection
            if sel and sel['w'] > 0 and sel['h'] > 0:
                # Cut out the selected region (show it bright)
                cr.set_operator(cairo.OPERATOR_CLEAR)
                cr.rectangle(sel['x'], sel['y'], sel['w'], sel['h'])
                cr.fill()
                cr.set_operator(cairo.OPERATOR_OVER)

                # Re-paint the selected region
                cr.set_source_surface(self._surface, 0, 0)
                cr.rectangle(sel['x'], sel['y'], sel['w'], sel['h'])
                cr.fill()

                # Draw selection border
                cr.set_source_rgba(0.25, 0.62, 1.0, 0.9)
                cr.set_line_width(2)
                cr.rectangle(sel['x'] + 1, sel['y'] + 1,
                             sel['w'] - 2, sel['h'] - 2)
                cr.stroke()

                # Draw corner handles
                self._draw_handles(cr, sel)

                # Size label
                label = f'{int(sel["w"])} × {int(sel["h"])}'
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL,
                                    cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(13)
                ext = cr.text_extents(label)
                lx = sel['x'] + sel['w'] / 2 - ext.width / 2
                ly = sel['y'] - 8
                if ly < 16:
                    ly = sel['y'] + 20
                # Background pill
                cr.set_source_rgba(0, 0, 0, 0.6)
                cr.rectangle(lx - 6, ly - 14, ext.width + 12, 20)
                cr.fill()
                cr.set_source_rgba(1, 1, 1, 0.95)
                cr.move_to(lx, ly)
                cr.show_text(label)

        # 3. Draw annotations
        if self._canvas:
            self._canvas.draw_all(cr)

    def _draw_handles(self, cr, sel):
        """Draw 8 resize handles around the selection."""
        x, y, w, h = sel['x'], sel['y'], sel['w'], sel['h']
        cx, cy = x + w / 2, y + h / 2
        positions = [
            (x, y), (cx, y), (x + w, y),
            (x + w, cy),
            (x + w, y + h), (cx, y + h), (x, y + h),
            (x, cy),
        ]
        r = HANDLE_SIZE / 2
        for hx, hy in positions:
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.arc(hx, hy, r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.15, 0.45, 0.8, 1.0)
            cr.arc(hx, hy, r, 0, 2 * math.pi)
            cr.set_line_width(1.5)
            cr.stroke()

    # ── Input handling ────────────────────────────────────────────────────────

    def _on_drag_begin(self, gesture, start_x, start_y):
        self._drag_active = True
        self._drag_start = (start_x, start_y)

        if self._mode == 'area' and not self._confirmed:
            self._selection = {'x': start_x, 'y': start_y, 'w': 0, 'h': 0}
        elif self._confirmed and self._canvas:
            self._canvas.begin_stroke(start_x, start_y,
                                      self._toolbar.current_tool,
                                      self._toolbar.stroke_color,
                                      self._toolbar.fill_color,
                                      self._toolbar.brush_size,
                                      self._toolbar.intensity)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if not self._drag_active:
            return
        sx, sy = self._drag_start
        cx, cy = sx + offset_x, sy + offset_y

        if self._mode == 'area' and not self._confirmed:
            # Rubber-band: support dragging in any direction
            x = min(sx, cx)
            y = min(sy, cy)
            w = abs(cx - sx)
            h = abs(cy - sy)
            self._selection = {'x': x, 'y': y, 'w': w, 'h': h}
        elif self._confirmed and self._canvas:
            self._canvas.update_stroke(cx, cy)

        self._drawing_area.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        self._drag_active = False
        if self._confirmed and self._canvas:
            self._canvas.end_stroke()
            self._drawing_area.queue_draw()

    def _on_click(self, gesture, n_press, x, y):
        if self._mode == 'area' and not self._confirmed:
            sel = self._selection
            if sel and sel['w'] > MIN_SELECTION and sel['h'] > MIN_SELECTION:
                self._confirmed = True
                self._toolbar.set_visible(True)
                self._drawing_area.queue_draw()

    def _on_motion(self, controller, x, y):
        if self._mode == 'area' and not self._confirmed:
            self._set_cursor('crosshair')
        elif self._confirmed:
            tool = self._toolbar.current_tool
            self._set_cursor('pencil' if tool else 'default')

    def _set_cursor(self, name):
        if name != self._cursor_type:
            self._cursor_type = name
            cursor = Gdk.Cursor.new_from_name(name, None)
            self._drawing_area.set_cursor(cursor)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self._mode == 'area' and not self._confirmed:
                sel = self._selection
                if sel and sel['w'] > MIN_SELECTION and sel['h'] > MIN_SELECTION:
                    self._confirmed = True
                    self._toolbar.set_visible(True)
                    self._drawing_area.queue_draw()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval == Gdk.KEY_z:
                self._on_undo(None)
                return True
            if keyval in (Gdk.KEY_y, Gdk.KEY_Z):
                self._on_redo(None)
                return True
            if keyval == Gdk.KEY_c:
                self._on_copy(None)
                return True
            if keyval == Gdk.KEY_s:
                self._on_save(None)
                return True
        return False

    # ── Toolbar callbacks ──────────────────────────────────────────────────────

    def _on_tool_changed(self, toolbar, tool_id):
        self._drawing_area.queue_draw()

    def _on_color_changed(self, toolbar, color_hex):
        pass  # canvas reads from toolbar on next stroke

    def _on_size_changed(self, toolbar, size):
        pass

    def _on_undo(self, _):
        if self._canvas:
            self._canvas.undo()
            self._drawing_area.queue_draw()

    def _on_redo(self, _):
        if self._canvas:
            self._canvas.redo()
            self._drawing_area.queue_draw()

    def _on_mode_changed(self, bar, new_mode):
        self._mode = new_mode
        self._confirmed = new_mode == 'screenshot'
        self._selection = None if new_mode != 'screenshot' else {
            'x': 0, 'y': 0,
            'w': self._monitor_w, 'h': self._monitor_h,
        }
        self._drawing_area.queue_draw()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _get_annotated_pixbuf(self):
        """Composite screenshot + annotations into a GdkPixbuf."""
        sel = self._selection or {
            'x': 0, 'y': 0,
            'w': self._monitor_w,
            'h': self._monitor_h,
        }
        sw = max(1, int(sel['w']))
        sh = max(1, int(sel['h']))

        # Create output surface
        out_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
        cr = cairo.Context(out_surface)

        # Paint cropped screenshot
        cr.set_source_surface(self._surface, -sel['x'], -sel['y'])
        cr.paint()

        # Paint annotations (offset by selection origin)
        if self._canvas:
            cr.translate(-sel['x'], -sel['y'])
            self._canvas.draw_all(cr)

        # Convert surface → pixbuf via temp file
        tmp = tempfile.mktemp(suffix='.png', prefix='bigshot-out-')
        out_surface.write_to_png(tmp)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(tmp)
        os.unlink(tmp)
        return pixbuf

    def _on_copy(self, _):
        """Copy annotated screenshot to clipboard."""
        try:
            pixbuf = self._get_annotated_pixbuf()
            clipboard = self.get_clipboard()
            # GTK4 clipboard: set via content provider
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            provider = Gdk.ContentProvider.new_for_value(texture)
            clipboard.set_content(provider)
            self._show_toast('Copied to clipboard')
            self.close()
        except Exception as e:
            print(f'[Big Shot] Copy failed: {e}')

    def _on_save(self, _):
        """Save annotated screenshot to ~/Pictures/Screenshots/."""
        try:
            pixbuf = self._get_annotated_pixbuf()
            path   = self._default_save_path()
            pixbuf.savev(path, 'png', [], [])
            self._show_toast(f'Saved: {os.path.basename(path)}')
            self.close()
        except Exception as e:
            print(f'[Big Shot] Save failed: {e}')

    def _on_save_as(self, _):
        """Open a Save As dialog."""
        dialog = Gtk.FileDialog()
        dialog.set_title('Save Screenshot')
        dialog.set_initial_name(self._default_filename())

        # Filter
        f = Gtk.FileFilter()
        f.set_name('PNG Images')
        f.add_pattern('*.png')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)

        dialog.save(self, None, self._on_save_as_done)

    def _on_save_as_done(self, dialog, result):
        try:
            file   = dialog.save_finish(result)
            pixbuf = self._get_annotated_pixbuf()
            path   = file.get_path()
            if not path.endswith('.png'):
                path += '.png'
            pixbuf.savev(path, 'png', [], [])
            self.close()
        except Exception as e:
            print(f'[Big Shot] Save As failed: {e}')

    def _on_close(self, _):
        self.close()

    # ── File helpers ──────────────────────────────────────────────────────────

    def _default_filename(self):
        from datetime import datetime
        ts = datetime.now().strftime('%Y-%m-%d %H-%M-%S')
        return f'Screenshot from {ts}.png'

    def _default_save_path(self):
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        if not pictures:
            pictures = GLib.get_home_dir()
        folder = os.path.join(pictures, 'Screenshots')
        os.makedirs(folder, exist_ok=True)

        base = self._default_filename()
        path = os.path.join(folder, base)
        i = 1
        while os.path.exists(path):
            name, ext = os.path.splitext(base)
            path = os.path.join(folder, f'{name}-{i}{ext}')
            i += 1
        return path

    # ── Toast notification ────────────────────────────────────────────────────

    def _show_toast(self, message):
        """Show a brief floating label as feedback."""
        label = Gtk.Label(label=message)
        label.add_css_class('bigshot-toast')
        self._overlay.add_overlay(label)
        self._overlay.set_overlay_pass_through(label, True)

        def remove_toast():
            self._overlay.remove_overlay(label)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(1800, remove_toast)
