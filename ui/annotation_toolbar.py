#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — Annotation Toolbar (GTK4)

Floating, draggable horizontal bar that replicates the GNOME Shell
PartToolbar widget:

  [≡] [tools…] | [color] [fill] [−size+] [font] [intensity] | [↩][↪] | [⎘][💾][⋯] [✕]

Emits GObject signals consumed by ScreenshotWindow.

SPDX-License-Identifier: GPL-2.0-or-later
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GObject, GLib, Pango
import math


# ── Tool definitions (mirrors SCREENSHOT_TOOLS in parttoolbar.js) ─────────────

TOOLS = [
    ('select',         'input-mouse-symbolic',          'Select / Move'),
    ('pen',            'document-edit-symbolic',         'Pen'),
    ('arrow',          'pan-end-symbolic',               'Arrow'),
    ('line',           'draw-line-symbolic',             'Line'),
    ('rect',           'draw-rectangle-symbolic',        'Rectangle'),
    ('circle',         'draw-ellipse-symbolic',          'Oval'),
    ('text',           'insert-text-symbolic',           'Text'),
    ('highlight',      'marker-symbolic',                'Highlighter'),
    ('censor',         'view-grid-symbolic',             'Censor'),
    ('blur',           'zoom-fit-best-symbolic',         'Blur'),
    ('number',         'list-ordered-symbolic',          'Number'),
    ('number-arrow',   'go-next-symbolic',               'Number + Arrow'),
    ('eraser',         'edit-clear-symbolic',            'Eraser'),
]

PALETTE = [
    '#ed333b', '#e01b24', '#c01c28',   # Reds
    '#ff7800', '#e66100', '#c64600',   # Oranges
    '#f6d32d', '#f5c211', '#e5a50a',   # Yellows
    '#57e389', '#33d17a', '#2ec27e',   # Greens
    '#62a0ea', '#3584e4', '#1c71d8',   # Blues
    '#9141ac', '#813d9c', '#613583',   # Purples
    '#ffffff', '#deddda', '#9a9996',
    '#5c5c5c', '#3d3846', '#000000',
]


class AnnotationToolbar(Gtk.Box):
    """
    Floating horizontal toolbar for screenshot annotation.
    Positioned at the top of the overlay; the user can drag it.
    """

    __gsignals__ = {
        'tool-changed':   (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'color-changed':  (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'fill-changed':   (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'size-changed':   (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'action-copy':    (GObject.SignalFlags.RUN_FIRST, None, ()),
        'action-save':    (GObject.SignalFlags.RUN_FIRST, None, ()),
        'action-save-as': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'action-close':   (GObject.SignalFlags.RUN_FIRST, None, ()),
        'undo':           (GObject.SignalFlags.RUN_FIRST, None, ()),
        'redo':           (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.set_margin_top(8)
        self.set_margin_start(8)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)

        # State
        self.current_tool  = None
        self.stroke_color  = '#ed333b'
        self.fill_color    = None        # None = transparent
        self.brush_size    = 3
        self.intensity     = 3          # for censor/blur
        self._tool_buttons = {}
        self._drag_x       = 0.0
        self._drag_y       = 0.0
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0

        self._build()
        self._apply_style()
        self._setup_drag()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self):
        # Drag handle
        handle_icon = Gtk.Image.new_from_icon_name('open-menu-symbolic')
        handle_icon.set_pixel_size(14)
        handle_icon.add_css_class('bigshot-drag-handle')
        self.append(handle_icon)

        self._add_sep()

        # Tool buttons
        for tool_id, icon_name, label in TOOLS:
            btn = Gtk.ToggleButton()
            btn.set_tooltip_text(label)
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(16)
            btn.set_child(img)
            btn.add_css_class('bigshot-tool-btn')
            btn.connect('toggled', self._on_tool_toggled, tool_id)
            self.append(btn)
            self._tool_buttons[tool_id] = btn

        self._add_sep()

        # Stroke color swatch
        self._color_btn = Gtk.Button()
        self._color_btn.set_tooltip_text('Stroke Color')
        self._color_swatch = Gtk.DrawingArea()
        self._color_swatch.set_content_width(16)
        self._color_swatch.set_content_height(16)
        self._color_swatch.set_draw_func(self._draw_stroke_swatch)
        self._color_btn.set_child(self._color_swatch)
        self._color_btn.add_css_class('bigshot-tool-btn')
        self._color_btn.connect('clicked', self._on_color_clicked)
        self.append(self._color_btn)

        # Fill color swatch
        self._fill_btn = Gtk.Button()
        self._fill_btn.set_tooltip_text('Fill Color')
        self._fill_swatch = Gtk.DrawingArea()
        self._fill_swatch.set_content_width(16)
        self._fill_swatch.set_content_height(16)
        self._fill_swatch.set_draw_func(self._draw_fill_swatch)
        self._fill_btn.set_child(self._fill_swatch)
        self._fill_btn.add_css_class('bigshot-tool-btn')
        self._fill_btn.connect('clicked', self._on_fill_clicked)
        self.append(self._fill_btn)

        # Brush size: − [N] +
        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        dec_btn = Gtk.Button(label='−')
        dec_btn.add_css_class('bigshot-tool-btn')
        dec_btn.connect('clicked', lambda _: self._adjust_size(-1))
        size_box.append(dec_btn)

        self._size_label = Gtk.Label(label=str(self.brush_size))
        self._size_label.set_width_chars(3)
        self._size_label.add_css_class('bigshot-size-label')
        size_box.append(self._size_label)

        inc_btn = Gtk.Button(label='+')
        inc_btn.add_css_class('bigshot-tool-btn')
        inc_btn.connect('clicked', lambda _: self._adjust_size(+1))
        size_box.append(inc_btn)

        self.append(size_box)

        # Font selector (hidden unless text tool is active)
        self._font_btn = Gtk.Button(label='Sans')
        self._font_btn.set_tooltip_text('Font')
        self._font_btn.add_css_class('bigshot-tool-btn')
        self._font_btn.connect('clicked', self._on_font_clicked)
        self._font_btn.set_visible(False)
        self.append(self._font_btn)
        self._current_font = 'Sans'

        # Intensity (hidden unless censor/blur)
        self._intensity_label = Gtk.Label(label=f'⊞ {self.intensity}')
        self._intensity_label.add_css_class('bigshot-size-label')
        self._intensity_btn = Gtk.Button()
        self._intensity_btn.set_child(self._intensity_label)
        self._intensity_btn.set_tooltip_text('Intensity')
        self._intensity_btn.add_css_class('bigshot-tool-btn')
        self._intensity_btn.connect('clicked', self._on_intensity_clicked)
        self._intensity_btn.set_visible(False)
        self.append(self._intensity_btn)

        self._add_sep()

        # Undo / Redo
        undo_btn = self._make_icon_btn('edit-undo-symbolic', 'Undo')
        undo_btn.connect('clicked', lambda _: self.emit('undo'))
        self.append(undo_btn)

        redo_btn = self._make_icon_btn('edit-redo-symbolic', 'Redo')
        redo_btn.connect('clicked', lambda _: self.emit('redo'))
        self.append(redo_btn)

        self._add_sep()

        # Action buttons
        copy_btn = self._make_icon_btn('edit-copy-symbolic', 'Copy to Clipboard')
        copy_btn.connect('clicked', lambda _: self.emit('action-copy'))
        self.append(copy_btn)

        save_btn = self._make_icon_btn('document-save-symbolic', 'Save')
        save_btn.connect('clicked', lambda _: self.emit('action-save'))
        self.append(save_btn)

        saveas_btn = self._make_icon_btn('document-save-as-symbolic', 'Save As…')
        saveas_btn.connect('clicked', lambda _: self.emit('action-save-as'))
        self.append(saveas_btn)

        self._add_sep()

        close_btn = self._make_icon_btn('window-close-symbolic', 'Close')
        close_btn.add_css_class('bigshot-close-btn')
        close_btn.connect('clicked', lambda _: self.emit('action-close'))
        self.append(close_btn)

    def _make_icon_btn(self, icon_name, tooltip):
        btn = Gtk.Button()
        btn.set_tooltip_text(tooltip)
        img = Gtk.Image.new_from_icon_name(icon_name)
        img.set_pixel_size(16)
        btn.set_child(img)
        btn.add_css_class('bigshot-tool-btn')
        return btn

    def _add_sep(self):
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.add_css_class('bigshot-sep')
        self.append(sep)

    # ── Style ─────────────────────────────────────────────────────────────────

    def _apply_style(self):
        css = b"""
        .bigshot-toolbar {
            background: rgba(28, 28, 28, 0.88);
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.09);
            padding: 5px 10px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.55);
        }
        .bigshot-tool-btn {
            border-radius: 8px;
            padding: 3px 5px;
            min-width: 24px;
            min-height: 24px;
            background: transparent;
            border: none;
            color: white;
        }
        .bigshot-tool-btn:hover {
            background: rgba(255,255,255,0.13);
        }
        .bigshot-tool-btn:checked,
        .bigshot-tool-btn:active {
            background: rgba(255,255,255,0.26);
            border: 1px solid rgba(255,255,255,0.32);
        }
        .bigshot-size-label {
            color: white;
            font-size: 12px;
            min-width: 20px;
        }
        .bigshot-drag-handle {
            color: rgba(255,255,255,0.45);
            cursor: grab;
        }
        .bigshot-sep {
            margin: 3px 5px;
            background: rgba(255,255,255,0.14);
            min-width: 1px;
        }
        .bigshot-close-btn {
            color: rgba(255,255,255,0.6);
        }
        .bigshot-toast {
            background: rgba(0,0,0,0.75);
            color: white;
            border-radius: 8px;
            padding: 8px 16px;
            margin-bottom: 40px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.add_css_class('bigshot-toolbar')

    # ── Drag (toolbar repositioning) ──────────────────────────────────────────

    def _setup_drag(self):
        drag = Gtk.GestureDrag()
        drag.connect('drag-begin',  self._on_drag_begin)
        drag.connect('drag-update', self._on_drag_update)
        self.add_controller(drag)

    def _on_drag_begin(self, gesture, x, y):
        alloc = self.get_allocation()
        self._drag_start_x = alloc.x
        self._drag_start_y = alloc.y

    def _on_drag_update(self, gesture, offset_x, offset_y):
        new_x = self._drag_start_x + offset_x
        new_y = self._drag_start_y + offset_y

        parent = self.get_parent()
        if parent and hasattr(parent, 'move_overlay'):
            parent.move_overlay(self, max(0, new_x), max(0, new_y))

    # ── Tool logic ────────────────────────────────────────────────────────────

    def _on_tool_toggled(self, btn, tool_id):
        if btn.get_active():
            # Deactivate all others
            for tid, b in self._tool_buttons.items():
                if tid != tool_id and b.get_active():
                    b.set_active(False)
            self.current_tool = tool_id
        else:
            if self.current_tool == tool_id:
                self.current_tool = None

        # Show/hide context-sensitive controls
        is_text    = self.current_tool == 'text'
        is_effect  = self.current_tool in ('censor', 'blur')
        self._font_btn.set_visible(is_text)
        self._intensity_btn.set_visible(is_effect)

        self.emit('tool-changed', self.current_tool or '')

    def select_tool(self, tool_id):
        """Programmatically select a tool."""
        if tool_id in self._tool_buttons:
            self._tool_buttons[tool_id].set_active(True)
        else:
            for b in self._tool_buttons.values():
                b.set_active(False)
            self.current_tool = None

    # ── Color pickers ──────────────────────────────────────────────────────────

    def _draw_stroke_swatch(self, area, cr, w, h):
        self._draw_color_circle(cr, w, h, self.stroke_color)

    def _draw_fill_swatch(self, area, cr, w, h):
        if self.fill_color:
            self._draw_color_circle(cr, w, h, self.fill_color)
        else:
            # Transparent: dashed circle
            import cairo as _c
            cr.set_source_rgba(1, 1, 1, 0.5)
            cr.set_dash([3, 3])
            cr.set_line_width(1.5)
            r = min(w, h) / 2 - 1
            cr.arc(w/2, h/2, r, 0, 2*math.pi)
            cr.stroke()

    def _draw_color_circle(self, cr, w, h, hex_color):
        r = min(w, h) / 2 - 1
        rgb = self._hex_to_rgb(hex_color)
        cr.set_source_rgb(*rgb)
        cr.arc(w/2, h/2, r, 0, 2*math.pi)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.3)
        cr.set_line_width(1.5)
        cr.arc(w/2, h/2, r, 0, 2*math.pi)
        cr.stroke()

    def _hex_to_rgb(self, hex_color):
        h = hex_color.lstrip('#')
        return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    def _on_color_clicked(self, _btn):
        self._open_color_chooser('stroke')

    def _on_fill_clicked(self, _btn):
        self._open_color_chooser('fill')

    def _open_color_chooser(self, target):
        dialog = Gtk.ColorChooserDialog(
            title='Choose Color',
            transient_for=self.get_root(),
            modal=True,
        )
        dialog.set_use_alpha(target == 'fill')

        # Build a palette from PALETTE
        colors = []
        for hex_c in PALETTE:
            rgba = Gdk.RGBA()
            rgba.parse(hex_c)
            colors.append(rgba)
        dialog.add_palette(Gtk.Orientation.HORIZONTAL, 6, colors)

        # Set current color
        rgba = Gdk.RGBA()
        if target == 'fill' and self.fill_color:
            rgba.parse(self.fill_color)
        elif target == 'stroke':
            rgba.parse(self.stroke_color)
        dialog.set_rgba(rgba)

        dialog.connect('response', self._on_color_response, target)
        dialog.present()

    def _on_color_response(self, dialog, response, target):
        if response == Gtk.ResponseType.OK:
            rgba = dialog.get_rgba()
            if rgba.alpha < 0.05 and target == 'fill':
                # Treat near-transparent as "no fill"
                self.fill_color = None
            else:
                hex_color = '#{:02x}{:02x}{:02x}'.format(
                    int(rgba.red * 255),
                    int(rgba.green * 255),
                    int(rgba.blue * 255),
                )
                if target == 'stroke':
                    self.stroke_color = hex_color
                    self._color_swatch.queue_draw()
                    self.emit('color-changed', hex_color)
                else:
                    self.fill_color = hex_color
                    self._fill_swatch.queue_draw()
                    self.emit('fill-changed', hex_color)
        dialog.destroy()

    # ── Size / Intensity ──────────────────────────────────────────────────────

    def _adjust_size(self, delta):
        self.brush_size = max(1, min(100, self.brush_size + delta))
        self._size_label.set_text(str(self.brush_size))
        self.emit('size-changed', self.brush_size)

    def _on_intensity_clicked(self, _btn):
        self.intensity = (self.intensity % 5) + 1   # cycle 1–5
        self._intensity_label.set_text(f'⊞ {self.intensity}')

    # ── Font ──────────────────────────────────────────────────────────────────

    def _on_font_clicked(self, _btn):
        dialog = Gtk.FontChooserDialog(
            title='Choose Font',
            transient_for=self.get_root(),
            modal=True,
        )
        dialog.set_font(self._current_font)
        dialog.connect('response', self._on_font_response)
        dialog.present()

    def _on_font_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            font_desc = dialog.get_font_desc()
            self._current_font = font_desc.get_family()
            self._font_btn.set_label(self._current_font[:12])
        dialog.destroy()
