#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — Drawing Tools

Each tool class:
  - __init__(x, y, **kwargs) — begin a stroke at (x, y)
  - update(x, y)             — extend/reshape the stroke
  - draw(cr)                 — render onto a Cairo context

Cairo colour helper: parse '#rrggbb' → (r, g, b) floats.

SPDX-License-Identifier: GPL-2.0-or-later
"""

import cairo
import math


# ── Colour helper ──────────────────────────────────────────────────────────────

def parse_color(hex_color, alpha=1.0):
    """Return (r, g, b, a) floats from '#rrggbb' string."""
    if not hex_color:
        return (0, 0, 0, 0)
    h = hex_color.lstrip('#')
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b, alpha)


def set_stroke_color(cr, color, alpha=1.0):
    r, g, b, a = parse_color(color, alpha)
    cr.set_source_rgba(r, g, b, a)


def set_fill_color(cr, color, alpha=1.0):
    if color:
        r, g, b, a = parse_color(color, alpha)
        cr.set_source_rgba(r, g, b, a)


# ── Base stroke ───────────────────────────────────────────────────────────────

class BaseStroke:
    tool_id = None

    def __init__(self, x, y, color='#ed333b', fill=None,
                 size=3, intensity=3, **kwargs):
        self.x0        = x
        self.y0        = y
        self.x1        = x
        self.y1        = y
        self.color     = color
        self.fill      = fill
        self.size      = max(1, size)
        self.intensity = max(1, min(5, intensity))

    def update(self, x, y):
        self.x1 = x
        self.y1 = y

    def draw(self, cr):
        raise NotImplementedError

    def _apply_line_style(self, cr, alpha=1.0):
        set_stroke_color(cr, self.color, alpha)
        cr.set_line_width(self.size)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)


# ── Pen (freehand polyline) ───────────────────────────────────────────────────

class PenTool(BaseStroke):
    tool_id = 'pen'

    def __init__(self, x, y, **kwargs):
        super().__init__(x, y, **kwargs)
        self._points = [(x, y)]

    def update(self, x, y):
        super().update(x, y)
        self._points.append((x, y))

    def draw(self, cr):
        if len(self._points) < 2:
            return
        self._apply_line_style(cr)
        cr.move_to(*self._points[0])
        for px, py in self._points[1:]:
            cr.line_to(px, py)
        cr.stroke()


# ── Arrow ──────────────────────────────────────────────────────────────────────

class ArrowTool(BaseStroke):
    tool_id = 'arrow'

    def draw(self, cr):
        dx = self.x1 - self.x0
        dy = self.y1 - self.y0
        length = math.hypot(dx, dy)
        if length < 4:
            return

        self._apply_line_style(cr)

        # Shaft
        cr.move_to(self.x0, self.y0)
        cr.line_to(self.x1, self.y1)
        cr.stroke()

        # Arrowhead
        angle     = math.atan2(dy, dx)
        head_len  = max(12, self.size * 4)
        head_angle = math.pi / 6

        ax1 = self.x1 - head_len * math.cos(angle - head_angle)
        ay1 = self.y1 - head_len * math.sin(angle - head_angle)
        ax2 = self.x1 - head_len * math.cos(angle + head_angle)
        ay2 = self.y1 - head_len * math.sin(angle + head_angle)

        set_stroke_color(cr, self.color)
        cr.move_to(self.x1, self.y1)
        cr.line_to(ax1, ay1)
        cr.line_to(ax2, ay2)
        cr.close_path()
        cr.fill()


# ── Line ──────────────────────────────────────────────────────────────────────

class LineTool(BaseStroke):
    tool_id = 'line'

    def draw(self, cr):
        self._apply_line_style(cr)
        cr.move_to(self.x0, self.y0)
        cr.line_to(self.x1, self.y1)
        cr.stroke()


# ── Rectangle ─────────────────────────────────────────────────────────────────

class RectTool(BaseStroke):
    tool_id = 'rect'

    def draw(self, cr):
        x = min(self.x0, self.x1)
        y = min(self.y0, self.y1)
        w = abs(self.x1 - self.x0)
        h = abs(self.y1 - self.y0)
        if w < 1 or h < 1:
            return

        if self.fill:
            set_fill_color(cr, self.fill, 0.35)
            cr.rectangle(x, y, w, h)
            cr.fill()

        self._apply_line_style(cr)
        cr.rectangle(x, y, w, h)
        cr.stroke()


# ── Circle / Ellipse ─────────────────────────────────────────────────────────

class CircleTool(BaseStroke):
    tool_id = 'circle'

    def draw(self, cr):
        cx = (self.x0 + self.x1) / 2
        cy = (self.y0 + self.y1) / 2
        rx = abs(self.x1 - self.x0) / 2
        ry = abs(self.y1 - self.y0) / 2
        if rx < 1 or ry < 1:
            return

        cr.save()
        cr.translate(cx, cy)
        cr.scale(rx, ry)

        if self.fill:
            set_fill_color(cr, self.fill, 0.35)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.fill()

        self._apply_line_style(cr, 1.0)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()

        # Stroke with correct line-width (undo scale distortion)
        cr.set_line_width(self.size)
        set_stroke_color(cr, self.color)
        cr.stroke()


# ── Text ──────────────────────────────────────────────────────────────────────

class TextTool(BaseStroke):
    tool_id = 'text'

    def __init__(self, x, y, font='Sans', **kwargs):
        super().__init__(x, y, **kwargs)
        self._font = font
        self._text = 'Text'   # placeholder; in production: prompt user

    def draw(self, cr):
        set_stroke_color(cr, self.color)
        cr.select_font_face(self._font,
                            cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(max(12, self.size * 4))
        cr.move_to(self.x0, self.y0)
        cr.show_text(self._text)


# ── Highlighter ───────────────────────────────────────────────────────────────

class HighlightTool(BaseStroke):
    tool_id = 'highlight'

    def __init__(self, x, y, **kwargs):
        super().__init__(x, y, **kwargs)
        self._points = [(x, y)]

    def update(self, x, y):
        super().update(x, y)
        self._points.append((x, y))

    def draw(self, cr):
        if len(self._points) < 2:
            return
        r, g, b, _ = parse_color(self.color)
        cr.set_source_rgba(r, g, b, 0.38)
        cr.set_line_width(max(16, self.size * 6))
        cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        cr.move_to(*self._points[0])
        for px, py in self._points[1:]:
            cr.line_to(px, py)
        cr.stroke()


# ── Censor (pixelate rectangle) ───────────────────────────────────────────────

class CensorTool(BaseStroke):
    tool_id = 'censor'

    def draw(self, cr):
        x = min(self.x0, self.x1)
        y = min(self.y0, self.y1)
        w = abs(self.x1 - self.x0)
        h = abs(self.y1 - self.y0)
        if w < 4 or h < 4:
            return

        # Draw mosaic pattern to simulate pixelation
        block = max(4, self.intensity * 4)
        cols = max(1, int(w / block))
        rows = max(1, int(h / block))
        for row in range(rows):
            for col in range(cols):
                bx = x + col * (w / cols)
                by = y + row * (h / rows)
                bw = w / cols
                bh = h / rows
                shade = ((row + col) % 2) * 0.15 + 0.2
                cr.set_source_rgba(shade, shade, shade, 0.85)
                cr.rectangle(bx, by, bw, bh)
                cr.fill()

        # Border
        cr.set_source_rgba(0, 0, 0, 0.4)
        cr.set_line_width(1)
        cr.rectangle(x, y, w, h)
        cr.stroke()


# ── Blur (frosted-glass rectangle) ───────────────────────────────────────────

class BlurTool(BaseStroke):
    tool_id = 'blur'

    def draw(self, cr):
        x = min(self.x0, self.x1)
        y = min(self.y0, self.y1)
        w = abs(self.x1 - self.x0)
        h = abs(self.y1 - self.y0)
        if w < 4 or h < 4:
            return

        # Simulate blur with layered translucent rectangles
        layers = self.intensity * 2
        step   = 0.4 / layers
        for i in range(layers):
            cr.set_source_rgba(0.8, 0.8, 0.8, step)
            margin = i * 1.0
            cr.rectangle(x + margin, y + margin,
                         w - margin * 2, h - margin * 2)
            cr.fill()

        cr.set_source_rgba(1, 1, 1, 0.15)
        cr.rectangle(x, y, w, h)
        cr.fill()

        cr.set_source_rgba(1, 1, 1, 0.5)
        cr.set_line_width(1.5)
        cr.rectangle(x, y, w, h)
        cr.stroke()


# ── Number ────────────────────────────────────────────────────────────────────

class NumberTool(BaseStroke):
    tool_id = 'number'

    def __init__(self, x, y, number=1, **kwargs):
        super().__init__(x, y, **kwargs)
        self._number = number

    def draw(self, cr):
        r = max(12, self.size * 4)
        # Circle background
        set_stroke_color(cr, self.color)
        cr.arc(self.x0, self.y0, r, 0, 2 * math.pi)
        cr.fill()
        # Number text
        cr.set_source_rgba(1, 1, 1, 1)
        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(r * 0.9)
        label = str(self._number)
        ext   = cr.text_extents(label)
        cr.move_to(self.x0 - ext.width / 2 - ext.x_bearing,
                   self.y0 - ext.height / 2 - ext.y_bearing)
        cr.show_text(label)


# ── Number + Arrow ───────────────────────────────────────────────────────────

class NumberArrowTool(NumberTool):
    tool_id = 'number-arrow'

    def draw(self, cr):
        # Draw the number circle at origin, arrow pointing to target
        super().draw(cr)
        dx = self.x1 - self.x0
        dy = self.y1 - self.y0
        length = math.hypot(dx, dy)
        if length < 8:
            return
        r = max(12, self.size * 4)
        # Arrow from edge of circle to endpoint
        angle = math.atan2(dy, dx)
        sx = self.x0 + r * math.cos(angle)
        sy = self.y0 + r * math.sin(angle)
        set_stroke_color(cr, self.color)
        cr.set_line_width(self.size)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(sx, sy)
        cr.line_to(self.x1, self.y1)
        cr.stroke()

        # Arrowhead
        head_len  = max(10, self.size * 3)
        head_angle = math.pi / 6
        ax1 = self.x1 - head_len * math.cos(angle - head_angle)
        ay1 = self.y1 - head_len * math.sin(angle - head_angle)
        ax2 = self.x1 - head_len * math.cos(angle + head_angle)
        ay2 = self.y1 - head_len * math.sin(angle + head_angle)
        set_stroke_color(cr, self.color)
        cr.move_to(self.x1, self.y1)
        cr.line_to(ax1, ay1)
        cr.line_to(ax2, ay2)
        cr.close_path()
        cr.fill()


# ── Eraser ────────────────────────────────────────────────────────────────────

class EraserTool(BaseStroke):
    tool_id = 'eraser'

    def __init__(self, x, y, **kwargs):
        super().__init__(x, y, **kwargs)
        self._points = [(x, y)]

    def update(self, x, y):
        super().update(x, y)
        self._points.append((x, y))

    def draw(self, cr):
        """
        Erase by painting with OPERATOR_CLEAR (removes alpha channel pixels).
        Works on surfaces with ARGB32 format.
        """
        if len(self._points) < 2:
            return
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.set_line_width(max(10, self.size * 4))
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*self._points[0])
        for px, py in self._points[1:]:
            cr.line_to(px, py)
        cr.stroke()
        cr.restore()


# ── Public tool list ─────────────────────────────────────────────────────────

TOOLS = [
    PenTool, ArrowTool, LineTool, RectTool, CircleTool,
    TextTool, HighlightTool, CensorTool, BlurTool,
    NumberTool, NumberArrowTool, EraserTool,
]
