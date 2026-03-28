#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — Drawing Canvas

Manages annotation state:
  - Active stroke in progress
  - History list (undo / redo)
  - Renders all completed strokes + current stroke onto a Cairo context

Tools implemented here:
  select, pen, arrow, line, rect, circle, text, highlight,
  censor, blur, number, number-arrow, eraser

SPDX-License-Identifier: GPL-2.0-or-later
"""

import cairo
import math
import time
from drawing.tools import (
    PenTool, ArrowTool, LineTool, RectTool, CircleTool,
    TextTool, HighlightTool, CensorTool, BlurTool,
    NumberTool, NumberArrowTool, EraserTool,
)


# Map tool IDs to classes
TOOL_MAP = {
    'pen':           PenTool,
    'arrow':         ArrowTool,
    'line':          LineTool,
    'rect':          RectTool,
    'circle':        CircleTool,
    'text':          TextTool,
    'highlight':     HighlightTool,
    'censor':        CensorTool,
    'blur':          BlurTool,
    'number':        NumberTool,
    'number-arrow':  NumberArrowTool,
    'eraser':        EraserTool,
}


class DrawingCanvas:
    """
    Stateful annotation manager. Not a GTK widget — it is called by
    ScreenshotWindow._on_draw() to render onto an existing Cairo context.
    """

    def __init__(self):
        self._actions       = []      # completed strokes
        self._redo_stack    = []
        self._current       = None    # active Stroke object
        self._number_seq    = 1       # auto-increment for number tools

    # ── Stroke lifecycle ──────────────────────────────────────────────────────

    def begin_stroke(self, x, y, tool_id, stroke_color, fill_color,
                     brush_size, intensity):
        """Start a new stroke."""
        if not tool_id or tool_id == 'select':
            return

        cls = TOOL_MAP.get(tool_id)
        if cls is None:
            return

        kwargs = {
            'color':     stroke_color or '#ed333b',
            'fill':      fill_color,
            'size':      brush_size,
            'intensity': intensity,
        }
        if tool_id in ('number', 'number-arrow'):
            kwargs['number'] = self._number_seq

        self._current = cls(x, y, **kwargs)
        self._redo_stack.clear()

    def update_stroke(self, x, y):
        if self._current:
            self._current.update(x, y)

    def end_stroke(self):
        if self._current:
            if tool_id := self._current.tool_id:
                if tool_id in ('number', 'number-arrow'):
                    self._number_seq += 1
            self._actions.append(self._current)
            self._current = None

    # ── Undo / Redo ───────────────────────────────────────────────────────────

    def undo(self):
        if self._actions:
            action = self._actions.pop()
            self._redo_stack.append(action)
            # Recalculate number sequence
            self._number_seq = 1
            for a in self._actions:
                if hasattr(a, '_number'):
                    self._number_seq = a._number + 1

    def redo(self):
        if self._redo_stack:
            action = self._redo_stack.pop()
            self._actions.append(action)
            if hasattr(action, '_number'):
                self._number_seq = action._number + 1

    # ── Rendering ────────────────────────────────────────────────────────────

    def draw_all(self, cr):
        """Draw all completed actions + the current in-progress stroke."""
        for action in self._actions:
            cr.save()
            action.draw(cr)
            cr.restore()

        if self._current:
            cr.save()
            self._current.draw(cr)
            cr.restore()
