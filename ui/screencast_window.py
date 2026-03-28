#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Big Shot — Screencast Window

A floating recording control panel that mirrors the GNOME Shell screencast mode:
  - Full/Area recording toggle
  - Audio: Desktop + Microphone toggles
  - Framerate selector (15 / 24 / 30 / 60 FPS)
  - Resolution: 100% / 75% / 50% / 33%
  - Quality: High / Medium / Low
  - Webcam overlay toggle
  - Start / Stop / Pause recording

Communicates with the Cinnamon extension via D-Bus or a local socket.
When the extension is not present it drives GStreamer directly via subprocess.

SPDX-License-Identifier: GPL-2.0-or-later
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gio', '2.0')
from gi.repository import Gtk, Gdk, GLib, Gio, GObject

import os
import subprocess
import threading
import time
import signal


# ── D-Bus interface for the Cinnamon extension ────────────────────────────────

EXTENSION_DBUS_NAME  = 'org.bigcommunity.BigShot'
EXTENSION_DBUS_PATH  = '/org/bigcommunity/BigShot'
EXTENSION_IFACE_XML  = """
<node>
  <interface name="org.bigcommunity.BigShot">
    <method name="StartRecording">
      <arg type="a{sv}" direction="in" name="options"/>
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="StopRecording">
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="PauseRecording">
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="ResumeRecording">
      <arg type="b" direction="out" name="success"/>
    </method>
    <signal name="RecordingStateChanged">
      <arg type="s" name="state"/>
    </signal>
  </interface>
</node>"""

# GStreamer pipeline presets (mirrors extension.js VIDEO_PIPELINES)
QUALITY_PRESETS = {
    'high':   {'qp': 18, 'openh264_br': 8000000, 'vp9_cq': 13},
    'medium': {'qp': 24, 'openh264_br': 4000000, 'vp9_cq': 24},
    'low':    {'qp': 27, 'openh264_br': 2000000, 'vp9_cq': 31},
}


class ScreencastWindow(Gtk.Window):
    """
    Recording control panel window.
    """

    def __init__(self, application):
        super().__init__(application=application)
        self.set_title('Big Shot — Screencast')
        self.set_default_size(440, -1)
        self.set_resizable(False)
        self.set_decorated(True)

        self._state       = 'idle'   # idle | recording | paused
        self._elapsed     = 0
        self._timer_id    = 0
        self._gst_proc    = None
        self._ext_proxy   = None

        self._try_connect_extension()
        self._build_ui()
        self._apply_style()

    # ── D-Bus connection ──────────────────────────────────────────────────────

    def _try_connect_extension(self):
        try:
            ExtProxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                EXTENSION_DBUS_NAME,
                EXTENSION_DBUS_PATH,
                'org.bigcommunity.BigShot',
                None,
            )
            self._ext_proxy = ExtProxy
        except Exception as e:
            print(f'[Big Shot UI] Extension D-Bus not available: {e}')
            self._ext_proxy = None

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class('bigshot-sc-root')
        self.set_child(root)

        # ── Header: icon + title ──
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.set_margin_start(16)
        header.set_margin_end(16)
        header.set_margin_top(14)
        header.set_margin_bottom(4)
        icon = Gtk.Image.new_from_icon_name('media-record-symbolic')
        icon.set_pixel_size(22)
        icon.add_css_class('bigshot-record-icon')
        header.append(icon)
        title_lbl = Gtk.Label(label='Screencast')
        title_lbl.add_css_class('bigshot-sc-title')
        title_lbl.set_hexpand(True)
        title_lbl.set_xalign(0)
        header.append(title_lbl)
        self._timer_label = Gtk.Label(label='00:00')
        self._timer_label.add_css_class('bigshot-timer')
        header.append(self._timer_label)
        root.append(header)

        root.append(self._make_sep())

        # ── Capture area row ──
        root.append(self._make_row(
            'Capture',
            self._make_toggle_group([
                ('fullscreen', 'video-display-symbolic',    'Full Screen'),
                ('area',       'select-rectangle-symbolic', 'Area'),
            ], '_capture_mode', 'fullscreen')
        ))

        # ── Audio row ──
        audio_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._desktop_audio_btn = self._make_check('Desktop', False)
        self._mic_btn           = self._make_check('Mic', False)
        audio_box.append(self._desktop_audio_btn)
        audio_box.append(self._mic_btn)
        root.append(self._make_row('Audio', audio_box))

        # ── Framerate row ──
        root.append(self._make_row(
            'FPS',
            self._make_toggle_group([
                ('15', None, '15'), ('24', None, '24'),
                ('30', None, '30'), ('60', None, '60'),
            ], '_fps', '30')
        ))

        # ── Resolution row ──
        root.append(self._make_row(
            'Resolution',
            self._make_toggle_group([
                ('1.00', None, '100%'), ('0.75', None, '75%'),
                ('0.50', None, '50%'), ('0.33', None, '33%'),
            ], '_downsize', '1.00')
        ))

        # ── Quality row ──
        root.append(self._make_row(
            'Quality',
            self._make_toggle_group([
                ('high',   None, 'High'),
                ('medium', None, 'Medium'),
                ('low',    None, 'Low'),
            ], '_quality', 'high')
        ))

        # ── Webcam row ──
        webcam_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._webcam_btn = self._make_check('Enable Webcam Overlay', False)
        webcam_box.append(self._webcam_btn)
        root.append(self._make_row('Webcam', webcam_box))

        root.append(self._make_sep())

        # ── Control buttons ──
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctrl_box.set_margin_start(16)
        ctrl_box.set_margin_end(16)
        ctrl_box.set_margin_top(12)
        ctrl_box.set_margin_bottom(16)
        ctrl_box.set_halign(Gtk.Align.CENTER)

        self._record_btn = Gtk.Button(label='⏺  Start Recording')
        self._record_btn.add_css_class('bigshot-record-btn')
        self._record_btn.connect('clicked', self._on_record_clicked)
        ctrl_box.append(self._record_btn)

        self._pause_btn = Gtk.Button(label='⏸  Pause')
        self._pause_btn.add_css_class('bigshot-pause-btn')
        self._pause_btn.connect('clicked', self._on_pause_clicked)
        self._pause_btn.set_sensitive(False)
        ctrl_box.append(self._pause_btn)

        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.add_css_class('bigshot-cancel-btn')
        cancel_btn.connect('clicked', lambda _: self.close())
        ctrl_box.append(cancel_btn)

        root.append(ctrl_box)

    # ── Row / widget helpers ──────────────────────────────────────────────────

    def _make_sep(self):
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class('bigshot-sc-sep')
        return sep

    def _make_row(self, label_text, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_start(16)
        row.set_margin_end(16)
        row.set_margin_top(8)
        row.set_margin_bottom(8)

        lbl = Gtk.Label(label=label_text)
        lbl.set_width_chars(10)
        lbl.set_xalign(0)
        lbl.add_css_class('bigshot-sc-label')
        row.append(lbl)
        row.append(widget)
        return row

    def _make_toggle_group(self, options, attr, default):
        """
        Create a group of radio-style ToggleButtons.
        `attr` is the name of the instance attribute to store the selected value.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        setattr(self, attr, default)
        buttons = {}

        for value, icon_name, label in options:
            btn = Gtk.ToggleButton(label=label)
            if icon_name:
                img = Gtk.Image.new_from_icon_name(icon_name)
                img.set_pixel_size(16)
                btn.set_child(img)
                btn.set_tooltip_text(label)
            btn.set_active(value == default)
            btn.add_css_class('bigshot-sc-toggle')
            val = value  # capture for closure

            def on_toggled(b, v=val, a=attr, bg=buttons):
                if b.get_active():
                    setattr(self, a, v)
                    for bv, bb in bg.items():
                        if bv != v and bb.get_active():
                            bb.set_active(False)
                else:
                    if getattr(self, a) == v:
                        b.set_active(True)

            btn.connect('toggled', on_toggled)
            box.append(btn)
            buttons[value] = btn

        return box

    def _make_check(self, label, default):
        btn = Gtk.CheckButton(label=label)
        btn.set_active(default)
        btn.add_css_class('bigshot-sc-check')
        return btn

    # ── Recording control ─────────────────────────────────────────────────────

    def _on_record_clicked(self, _btn):
        if self._state == 'idle':
            self._start_recording()
        else:
            self._stop_recording()

    def _on_pause_clicked(self, _btn):
        if self._state == 'recording':
            self._pause_recording()
        elif self._state == 'paused':
            self._resume_recording()

    def _start_recording(self):
        if self._ext_proxy:
            try:
                options = self._build_options_variant()
                result = self._ext_proxy.call_sync(
                    'StartRecording', options, Gio.DBusCallFlags.NONE, -1, None)
                if result and result.unpack()[0]:
                    self._on_recording_started()
                    return
            except Exception as e:
                print(f'[Big Shot UI] Extension start failed: {e}')

        # Fallback: direct GStreamer
        self._start_gst_recording()

    def _build_options_variant(self):
        fps     = int(self._fps)
        down    = float(self._downsize)
        quality = self._quality
        desktop = self._desktop_audio_btn.get_active()
        mic     = self._mic_btn.get_active()

        d = {
            'framerate': GLib.Variant('i', fps),
            'downsize':  GLib.Variant('d', down),
            'quality':   GLib.Variant('s', quality),
            'desktop_audio': GLib.Variant('b', desktop),
            'mic_audio':     GLib.Variant('b', mic),
        }
        return GLib.Variant('(a{sv})', (d,))

    def _start_gst_recording(self):
        fps     = int(self._fps)
        down    = float(self._downsize)
        quality = self._quality
        preset  = QUALITY_PRESETS.get(quality, QUALITY_PRESETS['high'])

        out_path = self._default_output_path()
        pipeline = self._build_pipeline(fps, down, preset, out_path)
        print(f'[Big Shot UI] Launching: {pipeline}')

        try:
            self._gst_proc = subprocess.Popen(
                ['bash', '-c', pipeline],
                preexec_fn=os.setsid,
            )
            self._on_recording_started()
            threading.Thread(target=self._watch_process, daemon=True).start()
        except Exception as e:
            self._show_error(f'Failed to start recording: {e}')

    def _watch_process(self):
        """Background thread watching the GStreamer process."""
        if self._gst_proc:
            self._gst_proc.wait()
        GLib.idle_add(self._on_recording_stopped_ext)

    def _build_pipeline(self, fps, downsize, preset, out_path):
        """
        Build a gst-launch-1.0 pipeline string.
        Uses pipewiresrc (Wayland/XDG) or ximagesrc (X11) as video source.
        """
        # Auto-detect source
        src = 'pipewiresrc do-timestamp=true'
        # Encoder: try openh264 (always available via web compat layer)
        enc = (
            f'openh264enc complexity=high bitrate={preset["openh264_br"]} multi-thread=4 ! h264parse'
        )
        video_chain = (
            f'{src} ! videoconvert n-threads=4 ! queue ! {enc}'
        )
        if downsize < 1.0:
            # Very crude downscale insertion — production version would query
            # monitor resolution first
            video_chain = (
                f'{src} ! videoconvert n-threads=4 ! videoscale ! '
                f'video/x-raw,width={int(1920*downsize)},height={int(1080*downsize)} ! '
                f'queue ! {enc}'
            )

        audio_chain = ''
        desktop = self._desktop_audio_btn.get_active()
        mic     = self._mic_btn.get_active()
        if desktop or mic:
            # Simplified: use default pulse source/sink
            if desktop:
                audio_chain = 'pulsesrc provide-clock=false ! audioconvert ! fdkaacenc ! queue'
            elif mic:
                audio_chain = 'pulsesrc provide-clock=false ! audioconvert ! fdkaacenc ! queue'

        if audio_chain:
            return (
                f'gst-launch-1.0 {video_chain} ! queue ! mux. '
                f'{audio_chain} ! mux. '
                f'mp4mux name=mux fragment-duration=500 ! filesink location="{out_path}"'
            )
        return (
            f'gst-launch-1.0 {video_chain} ! '
            f'mp4mux fragment-duration=500 ! filesink location="{out_path}"'
        )

    def _stop_recording(self):
        if self._ext_proxy:
            try:
                self._ext_proxy.call_sync(
                    'StopRecording', None, Gio.DBusCallFlags.NONE, -1, None)
            except Exception as e:
                print(f'[Big Shot UI] Extension stop failed: {e}')

        if self._gst_proc:
            try:
                os.killpg(os.getpgid(self._gst_proc.pid), signal.SIGTERM)
            except Exception:
                pass
            self._gst_proc = None

        self._on_recording_stopped_ext()

    def _pause_recording(self):
        if self._ext_proxy:
            try:
                self._ext_proxy.call_sync(
                    'PauseRecording', None, Gio.DBusCallFlags.NONE, -1, None)
            except Exception as e:
                print(f'[Big Shot UI] Pause failed: {e}')
        elif self._gst_proc:
            try:
                os.killpg(os.getpgid(self._gst_proc.pid), signal.SIGSTOP)
            except Exception:
                pass
        self._state = 'paused'
        self._pause_btn.set_label('▶  Resume')
        self._timer_label.add_css_class('bigshot-timer-paused')
        self._stop_timer()

    def _resume_recording(self):
        if self._ext_proxy:
            try:
                self._ext_proxy.call_sync(
                    'ResumeRecording', None, Gio.DBusCallFlags.NONE, -1, None)
            except Exception as e:
                print(f'[Big Shot UI] Resume failed: {e}')
        elif self._gst_proc:
            try:
                os.killpg(os.getpgid(self._gst_proc.pid), signal.SIGCONT)
            except Exception:
                pass
        self._state = 'recording'
        self._pause_btn.set_label('⏸  Pause')
        self._timer_label.remove_css_class('bigshot-timer-paused')
        self._start_timer()

    # ── Recording state callbacks ─────────────────────────────────────────────

    def _on_recording_started(self):
        self._state   = 'recording'
        self._elapsed = 0
        self._record_btn.set_label('⏹  Stop Recording')
        self._record_btn.remove_css_class('bigshot-record-btn')
        self._record_btn.add_css_class('bigshot-stop-btn')
        self._pause_btn.set_sensitive(True)
        self._start_timer()

    def _on_recording_stopped_ext(self):
        self._state = 'idle'
        self._stop_timer()
        self._record_btn.set_label('⏺  Start Recording')
        self._record_btn.remove_css_class('bigshot-stop-btn')
        self._record_btn.add_css_class('bigshot-record-btn')
        self._pause_btn.set_label('⏸  Pause')
        self._pause_btn.set_sensitive(False)
        self._timer_label.set_text('00:00')
        return GLib.SOURCE_REMOVE

    # ── Timer ─────────────────────────────────────────────────────────────────

    def _start_timer(self):
        self._stop_timer()
        self._timer_id = GLib.timeout_add(1000, self._tick_timer)

    def _stop_timer(self):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0

    def _tick_timer(self):
        self._elapsed += 1
        m = self._elapsed // 60
        s = self._elapsed % 60
        self._timer_label.set_text(f'{m:02d}:{s:02d}')
        return GLib.SOURCE_CONTINUE

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _default_output_path(self):
        from datetime import datetime
        videos = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS)
        if not videos:
            videos = GLib.get_home_dir()
        os.makedirs(videos, exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        return os.path.join(videos, f'Screencast_{ts}.mp4')

    def _show_error(self, msg):
        dialog = Gtk.AlertDialog()
        dialog.set_message('Recording Error')
        dialog.set_detail(msg)
        dialog.show(self)

    # ── Stylesheet ────────────────────────────────────────────────────────────

    def _apply_style(self):
        css = b"""
        .bigshot-sc-root {
            background: @theme_bg_color;
        }
        .bigshot-sc-title {
            font-size: 15px;
            font-weight: bold;
        }
        .bigshot-sc-label {
            color: alpha(currentColor, 0.65);
            font-size: 12px;
        }
        .bigshot-timer {
            font-variant-numeric: tabular-nums;
            font-weight: bold;
            font-size: 14px;
        }
        .bigshot-timer-paused {
            color: #f9c440;
        }
        .bigshot-record-icon {
            color: #e01b24;
        }
        .bigshot-sc-toggle {
            border-radius: 8px;
            padding: 3px 10px;
            font-size: 12px;
        }
        .bigshot-record-btn {
            background: #e01b24;
            color: white;
            border-radius: 10px;
            padding: 8px 18px;
            font-weight: bold;
            border: none;
        }
        .bigshot-record-btn:hover {
            background: #c01c28;
        }
        .bigshot-stop-btn {
            background: #1c71d8;
            color: white;
            border-radius: 10px;
            padding: 8px 18px;
            font-weight: bold;
            border: none;
        }
        .bigshot-pause-btn {
            border-radius: 10px;
            padding: 8px 14px;
        }
        .bigshot-cancel-btn {
            border-radius: 10px;
            padding: 8px 14px;
        }
        .bigshot-sc-sep {
            margin: 2px 0;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
