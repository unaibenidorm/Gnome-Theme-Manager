import os
import shutil
import tempfile
import threading
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Adw, Gdk, GLib, Gio, GdkPixbuf, Pango

class PlymouthCreatorDialog(Adw.Dialog):
    def __init__(self, parent_window):
        super().__init__(title="Plymouth Theme Creator", content_width=750, content_height=700)
        self.parent_window = parent_window
        self.source_path = None
        self.bg_path = None
        self.bg_start = Gdk.RGBA(0, 0, 0, 1.0)
        self.bg_end = Gdk.RGBA(0.1, 0.1, 0.1, 1.0)
        self.source_path_2 = None
        self.os_logo_path = None
        self.created_theme_dir = None
        self._gif_anim = None
        self._gif_timer_id = None
        self._gif_frames = []
        self._gif_frame_idx = 0
        self._anim_preview_id = None
        self._build_ui()
        self._load_system_delay()

    def _load_system_delay(self):
        """Read the current system-level plymouth delay from the systemd override, if present."""
        try:
            conf = Path("/etc/systemd/system/plymouth-quit.service.d/super_long_splash.conf")
            if conf.exists():
                import re
                text = conf.read_text()
                m = re.search(r'ExecStartPre=/usr/bin/sleep\s+(\d+)', text)
                if m:
                    self.delay_spin.set_value(int(m.group(1)))
        except Exception:
            pass

    def _build_ui(self):
        tb = Adw.ToolbarView()
        header = Adw.HeaderBar()
        tb.add_top_bar(header)
        main_box = Gtk.Box(orientation=1, spacing=0)

        # 1. Preview Area
        self.preview_container = Gtk.Box(orientation=1)
        self.preview_container.set_size_request(-1, 280)
        self.preview_container.set_visible(False) # Hidden until interacted with
        self.preview_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.preview_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.media_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.media_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.spinner_css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.spinner_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.preview_overlay = Gtk.Overlay()
        self.preview_overlay.set_vexpand(True)
        self.preview_overlay.set_hexpand(True)

        self.preview_bg = Gtk.Box()
        self.preview_bg.add_css_class("plymouth-preview-bg")
        self.preview_bg.set_vexpand(True)
        self.preview_bg.set_hexpand(True)
        self.preview_overlay.set_child(self.preview_bg)

        # Media preview with clipping frame for roundness
        self.preview_media_frame = Gtk.Frame(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.preview_media_frame.add_css_class("plymouth-media-frame")
        self.preview_media_frame.set_label_align(0)

        self.preview_media_box = Gtk.Box()
        self.preview_media_box.add_css_class("plymouth-media")

        self.preview_img = Gtk.Picture()
        self.preview_img.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.preview_img.set_size_request(320, 200)

        self.preview_media_box.append(self.preview_img)
        self.preview_media_frame.set_child(self.preview_media_box)
        self.preview_overlay.add_overlay(self.preview_media_frame)

        self.preview_msg = Gtk.Label(label="Loading system...", halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self.preview_msg.set_margin_bottom(20)
        self.preview_msg.set_visible(False)
        self.preview_overlay.add_overlay(self.preview_msg)

        self.preview_os = Gtk.Picture(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self.preview_os.set_size_request(-1, 36)
        self.preview_os.set_margin_bottom(60)
        self.preview_os.set_visible(False)
        self.preview_overlay.add_overlay(self.preview_os)

        self.preview_prog = Gtk.ProgressBar(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self.preview_prog.add_css_class("plymouth-progress")
        self.preview_prog.set_margin_bottom(40)
        self.preview_prog.set_size_request(200, -1)
        self.preview_prog.set_fraction(0.5)
        self.preview_prog.set_visible(False)
        self.preview_overlay.add_overlay(self.preview_prog)

        self.preview_spinner = Gtk.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        self.preview_spinner.add_css_class("plymouth-spinner")
        self.preview_spinner.set_margin_bottom(30)
        self.preview_spinner.set_size_request(48, 48)
        self.preview_spinner.set_visible(False)
        self.preview_overlay.add_overlay(self.preview_spinner)

        self.preview_container.append(self.preview_overlay)

        # Preview area is not shown in-app; use Plymouth real preview instead

        # 2. Controls
        sw = Gtk.ScrolledWindow(vexpand=True)
        controls_box = Gtk.Box(orientation=1, spacing=16)
        controls_box.set_margin_start(24); controls_box.set_margin_end(24)
        controls_box.set_margin_top(20); controls_box.set_margin_bottom(24)

        # Theme Details
        group_info = Adw.PreferencesGroup(title="Theme Details")
        self.name_entry = Adw.EntryRow(title="Theme Name")
        self.name_entry.set_text("my-custom-theme")
        group_info.add(self.name_entry)
        controls_box.append(group_info)

        # Media and Colors
        group_media = Adw.PreferencesGroup(title="Media and Colors")

        file_row = Adw.ActionRow(title="Source Media", subtitle="Image, GIF, or video centered on screen")
        file_box = Gtk.Box(orientation=0, spacing=6, valign=Gtk.Align.CENTER)
        self.btn_clear_file = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self.btn_clear_file.connect("clicked", self._on_clear_file)
        self.btn_clear_file.set_sensitive(False)
        self.btn_file = Gtk.Button(label="Choose File", valign=Gtk.Align.CENTER)
        self.btn_file.add_css_class("suggested-action")
        self.btn_file.connect("clicked", self._on_choose_file)
        file_box.append(self.btn_clear_file)
        file_box.append(self.btn_file)
        file_row.add_suffix(file_box)
        group_media.add(file_row)

        file2_row = Adw.ActionRow(title="Secondary Logo (Pulsing)", subtitle="Optional blurred/overlay image for glowing effect")
        file2_box = Gtk.Box(orientation=0, spacing=6, valign=Gtk.Align.CENTER)
        self.btn_clear_file2 = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self.btn_clear_file2.connect("clicked", self._on_clear_file2)
        self.btn_clear_file2.set_sensitive(False)
        self.btn_blur_logo2 = Gtk.Button(label="Auto Blur", valign=Gtk.Align.CENTER, tooltip_text="Generate a blurred copy of the primary logo")
        self.btn_blur_logo2.connect("clicked", self._on_auto_blur_logo2)
        self.btn_file2 = Gtk.Button(label="Choose Image", valign=Gtk.Align.CENTER)
        self.btn_file2.connect("clicked", self._on_choose_file2)
        file2_box.append(self.btn_clear_file2)
        file2_box.append(self.btn_blur_logo2)
        file2_box.append(self.btn_file2)
        file2_row.add_suffix(file2_box)
        group_media.add(file2_row)

        self.pulse_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        pulse_row = Adw.ActionRow(title="Pulse Secondary Logo", subtitle="Animates the opacity of the secondary logo")
        pulse_row.add_suffix(self.pulse_switch)
        group_media.add(pulse_row)

        bg_file_row = Adw.ActionRow(title="Background Image (Optional)", subtitle="Replaces gradient with a wallpaper")
        bg_box = Gtk.Box(orientation=0, spacing=6, valign=Gtk.Align.CENTER)
        self.btn_clear_bg = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self.btn_clear_bg.connect("clicked", self._on_clear_bg)
        self.btn_clear_bg.set_sensitive(False)
        self.btn_bg_file = Gtk.Button(label="Choose Image", valign=Gtk.Align.CENTER)
        self.btn_bg_file.connect("clicked", self._on_choose_bg_file)
        bg_box.append(self.btn_clear_bg)
        bg_box.append(self.btn_bg_file)
        bg_file_row.add_suffix(bg_box)
        group_media.add(bg_file_row)
        
        self.rainbow_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        rainbow_row = Adw.ActionRow(title="Rainbow Color Cycle", subtitle="Animates the background color through a rainbow (overrides gradient)")
        rainbow_row.add_suffix(self.rainbow_switch)
        group_media.add(rainbow_row)
        blur_row = Adw.ActionRow(title="Background Blur Radius", subtitle="Applies blur to the selected background image")
        self.blur_spin = Gtk.SpinButton.new_with_range(0, 50, 2)
        self.blur_spin.set_value(0)
        self.blur_spin.set_valign(Gtk.Align.CENTER)
        self.blur_spin.connect("value-changed", lambda _: self._update_preview_bg())
        blur_row.add_suffix(self.blur_spin)
        group_media.add(blur_row)
        color_start_row = Adw.ActionRow(title="Gradient Start Color (Top)")
        self.btn_col_start = Gtk.ColorDialogButton(valign=Gtk.Align.CENTER)
        self.btn_col_start.set_dialog(Gtk.ColorDialog(title="Select Start Color"))
        self.btn_col_start.set_rgba(self.bg_start)
        self.btn_col_start.connect("notify::rgba", self._on_color_changed)
        color_start_row.add_suffix(self.btn_col_start)
        group_media.add(color_start_row)

        color_end_row = Adw.ActionRow(title="Gradient End Color (Bottom)")
        self.btn_col_end = Gtk.ColorDialogButton(valign=Gtk.Align.CENTER)
        self.btn_col_end.set_dialog(Gtk.ColorDialog(title="Select End Color"))
        self.btn_col_end.set_rgba(self.bg_end)
        self.btn_col_end.connect("notify::rgba", self._on_color_changed)
        color_end_row.add_suffix(self.btn_col_end)
        group_media.add(color_end_row)
        controls_box.append(group_media)

        # Animation and Layout
        group_anim = Adw.PreferencesGroup(title="Animation and Layout")

        fps_row = Adw.ActionRow(title="Animation Speed (FPS)", subtitle="Frames per second for GIF/video")
        self.fps_spin = Gtk.SpinButton.new_with_range(5, 60, 1)
        self.fps_spin.set_value(24)
        self.fps_spin.set_valign(Gtk.Align.CENTER)
        fps_row.add_suffix(self.fps_spin)
        group_anim.add(fps_row)

        scale_row = Adw.ActionRow(title="Media Scale (%)", subtitle="Scale the animation relative to screen")
        self.scale_spin = Gtk.SpinButton.new_with_range(10, 100, 5)
        self.scale_spin.set_value(50)
        self.scale_spin.set_valign(Gtk.Align.CENTER)
        self.scale_spin.connect("value-changed", self._update_preview_media_scale)
        scale_row.add_suffix(self.scale_spin)
        group_anim.add(scale_row)

        round_row = Adw.ActionRow(title="Border Roundness (%)", subtitle="Make media circular/rounded")
        self.round_spin = Gtk.SpinButton.new_with_range(0, 50, 5)
        self.round_spin.set_value(0)
        self.round_spin.set_valign(Gtk.Align.CENTER)
        self.round_spin.connect("value-changed", self._update_preview_media_scale)
        round_row.add_suffix(self.round_spin)
        group_anim.add(round_row)

        valign_row = Adw.ActionRow(title="Vertical Position")
        self.valign_dd = Gtk.DropDown(model=Gtk.StringList.new(["Center", "Top", "Bottom"]), valign=Gtk.Align.CENTER)
        self.valign_dd.set_selected(0)
        self.valign_dd.connect("notify::selected", self._update_preview_valign)
        valign_row.add_suffix(self.valign_dd)
        group_anim.add(valign_row)

        entrance_row = Adw.ActionRow(title="Entrance Animation")
        self.entrance_anim_dd = Gtk.DropDown(model=Gtk.StringList.new(["None", "Fade In", "Slide Up", "Slide Down", "Scale Up", "Bounce", "Rotate In"]), valign=Gtk.Align.CENTER)
        self.entrance_anim_dd.connect("notify::selected", self._preview_entrance_anim)
        entrance_row.add_suffix(self.entrance_anim_dd)
        group_anim.add(entrance_row)

        controls_box.append(group_anim)

        # Extras and Progress
        group_msg = Adw.PreferencesGroup(title="Extras and Progress Bar")

        delay_row = Adw.ActionRow(title="Plymouth Duration (s)", subtitle="Extends how long the splash stays visible before GDM (applies globally to all themes)")
        self.delay_spin = Gtk.SpinButton.new_with_range(0, 60, 1)
        self.delay_spin.set_value(0)
        self.delay_spin.set_valign(Gtk.Align.CENTER)
        delay_row.add_suffix(self.delay_spin)
        group_msg.add(delay_row)

        os_row = Adw.ActionRow(title="Show OS Logo", subtitle="Displays a logo at a fixed position")
        os_box = Gtk.Box(orientation=0, spacing=6, valign=Gtk.Align.CENTER)
        self.btn_clear_os_logo = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self.btn_clear_os_logo.connect("clicked", self._on_clear_os_logo)
        self.btn_clear_os_logo.set_sensitive(False)
        self.btn_os_logo = Gtk.Button(label="Custom Logo", valign=Gtk.Align.CENTER)
        self.btn_os_logo.connect("clicked", self._on_choose_os_logo)
        self.os_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.os_switch.set_active(False)
        os_box.append(self.btn_clear_os_logo)
        os_box.append(self.btn_os_logo)
        os_box.append(self.os_switch)
        os_row.add_suffix(os_box)
        os_row.set_activatable_widget(self.os_switch)
        group_msg.add(os_row)

        os_pos_row = Adw.ActionRow(title="OS Logo Position")
        self.os_valign_dd = Gtk.DropDown(model=Gtk.StringList.new(["Bottom", "Top", "Center"]), valign=Gtk.Align.CENTER)
        os_pos_row.add_suffix(self.os_valign_dd)
        group_msg.add(os_pos_row)

        prog_row = Adw.ActionRow(title="Show Progress Bar")
        self.prog_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.prog_switch.set_active(False)
        prog_row.add_suffix(self.prog_switch)
        prog_row.set_activatable_widget(self.prog_switch)
        group_msg.add(prog_row)

        style_row = Adw.ActionRow(title="Progress Bar Style")
        self.prog_style_dd = Gtk.DropDown(model=Gtk.StringList.new(["Classic", "Thin", "Spinner"]), valign=Gtk.Align.CENTER)
        style_row.add_suffix(self.prog_style_dd)
        group_msg.add(style_row)

        progcolor_row = Adw.ActionRow(title="Progress Bar Color")
        self.btn_prog_color = Gtk.ColorDialogButton(valign=Gtk.Align.CENTER)
        self.btn_prog_color.set_dialog(Gtk.ColorDialog(title="Select Progress Color"))
        prog_blue = Gdk.RGBA(0.2, 0.5, 1.0, 1.0)
        self.btn_prog_color.set_rgba(prog_blue)
        progcolor_row.add_suffix(self.btn_prog_color)
        group_msg.add(progcolor_row)

        bgrt_row = Adw.ActionRow(title="Show OEM Logo (BGRT)", subtitle="Displays the manufacturer logo if supported")
        self.bgrt_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bgrt_switch.set_active(False)
        bgrt_row.add_suffix(self.bgrt_switch)
        bgrt_row.set_activatable_widget(self.bgrt_switch)
        group_msg.add(bgrt_row)

        self.prog_switch.connect("notify::active", self._update_preview_msg_prog)
        self.prog_style_dd.connect("notify::selected", self._update_preview_msg_prog)
        self.btn_prog_color.connect("notify::rgba", self._update_preview_msg_prog)
        self.os_switch.connect("notify::active", self._update_preview_msg_prog)
        self.os_valign_dd.connect("notify::selected", self._update_preview_msg_prog)
        
        controls_box.append(group_msg)

        # Action Buttons
        bbox = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        bbox.set_margin_top(16)

        self.btn_edit = Gtk.Button(label="Edit Existing Theme")
        self.btn_edit.set_size_request(150, 48)
        self.btn_edit.connect("clicked", self._on_edit_existing)
        bbox.append(self.btn_edit)

        self.btn_create = Gtk.Button(label="Create Theme")
        self.btn_create.add_css_class("suggested-action")
        self.btn_create.add_css_class("pill")
        self.btn_create.set_size_request(150, 48)
        self.btn_create.connect("clicked", self._on_create)
        bbox.append(self.btn_create)

        self.btn_install = Gtk.Button(label="Install to System")
        self.btn_install.add_css_class("destructive-action")
        self.btn_install.add_css_class("pill")
        self.btn_install.set_size_request(150, 48)
        self.btn_install.set_sensitive(False)
        self.btn_install.connect("clicked", self._on_install)
        bbox.append(self.btn_install)

        self.btn_preview_ply = Gtk.Button(label="Preview")
        self.btn_preview_ply.add_css_class("pill")
        self.btn_preview_ply.set_size_request(120, 48)
        self.btn_preview_ply.set_sensitive(False)
        self.btn_preview_ply.set_tooltip_text("Preview the generated theme using Plymouth")
        self.btn_preview_ply.connect("clicked", self._on_preview_plymouth)
        bbox.append(self.btn_preview_ply)
        controls_box.append(bbox)

        sw.set_child(controls_box)
        main_box.append(sw)
        tb.set_content(main_box)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(tb)
        self.set_child(self.toast_overlay)
        self._update_preview_msg_prog()

    def show_toast(self, msg):
        self.toast_overlay.add_toast(Adw.Toast(title=msg, timeout=2))

    def _update_preview_bg(self):
        blur_val = self.blur_spin.get_value() if hasattr(self, 'blur_spin') else 0
        if self.bg_path:
            bg_display_path = self.bg_path
            ext = os.path.splitext(self.bg_path)[1].lower()
            if ext in ['.mp4', '.mkv', '.webm']:
                import tempfile
                thumb_path = os.path.join(tempfile.gettempdir(), f"gtm_bg_thumb_{hash(self.bg_path)}.png")
                if not os.path.exists(thumb_path):
                    import subprocess
                    subprocess.run(["ffmpeg", "-y", "-i", self.bg_path, "-vframes", "1", thumb_path], capture_output=True)
                if os.path.exists(thumb_path):
                    bg_display_path = thumb_path
                    
            css = f""".plymouth-preview-bg {{
                background-image: url('file://{bg_display_path}');
                background-size: cover; background-position: center;
                filter: blur({blur_val}px);
            }}"""
        else:
            c1 = self.btn_col_start.get_rgba() if hasattr(self, 'btn_col_start') else self.bg_start
            c2 = self.btn_col_end.get_rgba() if hasattr(self, 'btn_col_end') else self.bg_end
            css = f""".plymouth-preview-bg {{
                background: linear-gradient(to bottom, {c1.to_string()}, {c2.to_string()});
            }}"""
        if hasattr(self.preview_css_provider, "load_from_string"):
            self.preview_css_provider.load_from_string(css)
        else:
            self.preview_css_provider.load_from_data(css.encode('utf-8'))

    def _update_preview_media_scale(self, *args):
        val = self.scale_spin.get_value()
        rad = self.round_spin.get_value()
        s = val / 50.0
        rad_px = int(rad * 3.2)  # Scale % to px for preview
        css = f""".plymouth-media-frame {{ transform: scale({s:.2f}); border-radius: {rad_px}px; border: none; background: transparent; padding: 0; }}"""
        if hasattr(self.media_css_provider, "load_from_string"):
            self.media_css_provider.load_from_string(css)
        else:
            self.media_css_provider.load_from_data(css.encode('utf-8'))

    def _update_preview_valign(self, *args):
        idx = self.valign_dd.get_selected()
        if idx == 1: # Top
            mt, mb = 20, 0
        elif idx == 2: # Bottom
            mt, mb = 0, 80
        else: # Center
            mt, mb = 0, 0
        
        self.preview_media_frame.set_margin_top(mt)
        self.preview_media_frame.set_margin_bottom(mb)

    def _update_preview_msg_prog(self, *args):
        self.preview_msg.set_visible(False)

        if hasattr(self, 'os_switch') and self.os_switch.get_active():
            self.preview_os.set_visible(True)
            logo_paths = [
                "/usr/share/plymouth/ubuntu-logo.png",
                "/usr/share/plymouth/fedora-logo.png",
                "/usr/share/plymouth/themes/spinner/watermark.png",
                "/usr/share/plymouth/themes/bgrt/watermark.png",
                "/usr/share/pixmaps/system-logo-white.png"
            ]
            for p in logo_paths:
                if Path(p).exists():
                    self.preview_os.set_file(Gio.File.new_for_path(p))
                    break
            
            if hasattr(self, 'os_valign_dd'):
                idx = self.os_valign_dd.get_selected()
                self.preview_os.set_margin_bottom(60 if idx == 0 else 0)
                self.preview_os.set_margin_top(60 if idx == 1 else 0)
                self.preview_os.set_valign(Gtk.Align.END if idx == 0 else (Gtk.Align.START if idx == 1 else Gtk.Align.CENTER))
        else:
            if hasattr(self, 'preview_os'): self.preview_os.set_visible(False)

        # Update Progress/Spinner color + style
        prog_col = self.btn_prog_color.get_rgba()
        prog_hex = f"#{int(prog_col.red*255):02x}{int(prog_col.green*255):02x}{int(prog_col.blue*255):02x}"
        spinner_css = f".plymouth-spinner {{ color: {prog_hex}; }}"
        prog_css = f".plymouth-progress progress {{ background-color: {prog_hex}; min-height: 6px; }}"

        if self.prog_switch.get_active():
            style = self.prog_style_dd.get_selected()
            if style >= 2: # Spinner
                self.preview_prog.set_visible(False)
                self.preview_spinner.set_visible(True)
                self.preview_spinner.start()
                if hasattr(self.spinner_css_provider, "load_from_string"):
                    self.spinner_css_provider.load_from_string(spinner_css)
                else:
                    self.spinner_css_provider.load_from_data(spinner_css.encode('utf-8'))
            else:
                self.preview_spinner.set_visible(False)
                self.preview_spinner.stop()
                self.preview_prog.set_visible(True)
                if style == 1: # Thin
                    self.preview_prog.set_size_request(300, -1)
                    prog_css = f".plymouth-progress progress {{ background-color: {prog_hex}; min-height: 2px; }} .plymouth-progress trough {{ min-height: 2px; }}"
                else: # Classic
                    self.preview_prog.set_size_request(200, -1)
                    prog_css = f".plymouth-progress progress {{ background-color: {prog_hex}; min-height: 6px; }} .plymouth-progress trough {{ min-height: 6px; }}"
                if hasattr(self.spinner_css_provider, "load_from_string"):
                    self.spinner_css_provider.load_from_string(prog_css)
                else:
                    self.spinner_css_provider.load_from_data(prog_css.encode('utf-8'))
        else:
            self.preview_prog.set_visible(False)
            self.preview_spinner.set_visible(False)
            self.preview_spinner.stop()

    def _preview_entrance_anim(self, *args):
        """Play a quick CSS animation preview when the entrance animation changes."""
        idx = self.entrance_anim_dd.get_selected()
        if idx == 0:  # None
            return
        if self._anim_preview_id:
            GLib.source_remove(self._anim_preview_id)
            self._anim_preview_id = None
        
        target = self.preview_media_frame
        target.set_opacity(0)
        self._anim_step = 0
        anim_type = idx  # 1=fade, 2=slide_up, 3=slide_down, 4=scale, 5=bounce, 6=rotate
        
        def _step():
            self._anim_step += 1
            t = min(self._anim_step / 20.0, 1.0)  # 20 steps
            if anim_type == 1:  # Fade In
                target.set_opacity(t)
            elif anim_type == 2:  # Slide Up
                target.set_opacity(t)
                target.set_margin_top(int((1.0 - t) * 60))
            elif anim_type == 3:  # Slide Down
                target.set_opacity(t)
                target.set_margin_top(int(t * 0 + (1.0 - t) * -60))
            elif anim_type == 4:  # Scale Up
                target.set_opacity(t)
            elif anim_type == 5:  # Bounce
                if t < 0.5:
                    target.set_opacity(t * 2)
                    target.set_margin_top(int((1.0 - t * 2) * 40))
                else:
                    target.set_opacity(1.0)
                    bounce = abs(1.0 - (t - 0.5) * 4) * 10 if t < 0.75 else 0
                    target.set_margin_top(int(bounce))
            elif anim_type == 6:  # Rotate In
                target.set_opacity(t)
            
            if t >= 1.0:
                target.set_opacity(1.0)
                target.set_margin_top(0)
                self._update_preview_valign()  # restore valign
                self._anim_preview_id = None
                return False
            return True
        
        self._anim_preview_id = GLib.timeout_add(25, _step)

    def _on_color_changed(self, *args):
        self.preview_container.set_visible(True)
        self.bg_path = None
        if hasattr(self, 'btn_bg_file'):
            self.btn_bg_file.set_label("Choose Image")
        self._update_preview_bg()

    def _on_edit_existing(self, btn):
        dialog = Adw.Dialog(title="Select Installed Theme")
        dialog.set_content_width(500); dialog.set_content_height(500)
        tb = Adw.ToolbarView()
        tb.add_top_bar(Adw.HeaderBar())
        sw = Gtk.ScrolledWindow(vexpand=True)
        box = Gtk.Box(orientation=1, spacing=10)
        box.set_margin_start(12); box.set_margin_end(12); box.set_margin_top(12); box.set_margin_bottom(12)
        group = Adw.PreferencesGroup(title="Installed Plymouth Themes")
        
        themes = []
        for p in [Path("/usr/share/plymouth/themes"), Path.home() / ".local/share/plymouth/themes"]:
            if p.exists():
                for d in p.iterdir():
                    if d.is_dir():
                        pf = list(d.glob("*.plymouth"))
                        if pf:
                            try:
                                with open(pf[0], 'r', encoding='utf-8') as f:
                                    if "Gnome Theme Manager" in f.read():
                                        themes.append((d.name, pf[0]))
                            except Exception:
                                pass
        
        if not themes:
            box.append(Gtk.Label(label="No themes found."))
        else:
            for name, ply_path in sorted(themes):
                row = Adw.ActionRow(title=name, subtitle=str(ply_path))
                b = Gtk.Button(label="Select", valign=Gtk.Align.CENTER)
                b.add_css_class("suggested-action")
                b.connect("clicked", lambda btn, p=ply_path, d=dialog: self._on_existing_theme_selected(p, d))
                row.add_suffix(b)
                group.add(row)
            box.append(group)
        
        sw.set_child(box)
        tb.set_content(sw)
        dialog.set_child(tb)
        dialog.present(self.parent_window)

    def _on_existing_theme_selected(self, plymouth_file, dialog):
        dialog.close()
        try:
            image_dir = plymouth_file.parent
            try:
                for line in plymouth_file.read_text().splitlines():
                    if line.startswith("ImageDir="):
                        p = line.split("=", 1)[1].strip()
                        if Path(p).exists(): image_dir = Path(p)
            except Exception: pass
            
            theme_name = plymouth_file.stem
            msg = Adw.MessageDialog(heading=f"Edit Theme: {theme_name}", 
                                    body="Do you want to edit the original theme directly, or create a copy to edit?",
                                    transient_for=self.parent_window)
            msg.add_response("cancel", "Cancel")
            msg.add_response("copy", "Create Copy")
            msg.add_response("original", "Edit Original")
            msg.set_response_appearance("original", Adw.ResponseAppearance.DESTRUCTIVE)
            msg.set_response_appearance("copy", Adw.ResponseAppearance.SUGGESTED)
            
            def _on_response(d, response):
                if response == "cancel": return
                if response == "copy":
                    self._ask_new_name_and_copy(image_dir, theme_name)
                elif response == "original":
                    self._setup_editing_env(image_dir, theme_name, True)
            msg.connect("response", _on_response)
            msg.present()
        except Exception: pass

    def _ask_new_name_and_copy(self, image_dir, orig_name):
        d = Adw.MessageDialog(heading="Create Copy", body="Enter a name for the copied theme:", transient_for=self.parent_window)
        entry = Gtk.Entry(placeholder_text="e.g. My-Custom-Theme", hexpand=True, margin_top=10, margin_bottom=10)
        d.set_extra_child(entry)
        d.add_response("cancel", "Cancel")
        d.add_response("ok", "Create")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        def _on_res(diag, res):
            if res == "ok" and entry.get_text().strip():
                self._setup_editing_env(image_dir, entry.get_text().strip(), False)
        d.connect("response", _on_res)
        d.present()

    def _setup_editing_env(self, source_dir, theme_name, is_original):
        work_dir = Path.home() / ".config" / "gnome-theme-manager" / "plymouth_work" / theme_name
        if work_dir.exists(): shutil.rmtree(work_dir, ignore_errors=True)
        shutil.copytree(source_dir, work_dir, ignore=shutil.ignore_patterns("debug.log", "*.gtm_backup"))
        
        self.preview_container.set_visible(True)
        self.editing_existing_dir = work_dir
        self.name_entry.set_text(theme_name)
        
        bg_png = work_dir / "background.png"
        throbber = work_dir / "throbber-0000.png"
        if not throbber.exists(): throbber = work_dir / "animation-0000.png"
        if bg_png.exists():
            self.bg_path = str(bg_png)
            if hasattr(self, 'btn_bg_file'): self.btn_bg_file.set_label("Existing Background")
            if hasattr(self, 'btn_clear_bg'): self.btn_clear_bg.set_sensitive(True)
            self._update_preview_bg()
        if throbber.exists():
            self.preview_img.set_file(Gio.File.new_for_path(str(throbber)))
            self.preview_img.set_visible(True)
            self.btn_file.set_label("Existing Animation")
            if hasattr(self, 'btn_clear_file'): self.btn_clear_file.set_sensitive(True)
            self.source_path = str(throbber) # spoof it to bypass validation

        # Restore saved config if available
        config_file = work_dir / ".gtm-config.json"
        if config_file.exists():
            try:
                import json
                with open(config_file, "r", encoding="utf-8") as f:
                    opts = json.load(f)
                
                if "fps" in opts: self.fps_spin.set_value(opts["fps"])
                if "scale_pct" in opts: self.scale_spin.set_value(opts["scale_pct"])
                if "roundness" in opts: self.round_spin.set_value(opts["roundness"])
                if "blur_radius" in opts: getattr(self, "blur_spin").set_value(opts["blur_radius"])
                if "valign" in opts:
                    idx = ["center", "top", "bottom"].index(opts["valign"]) if opts["valign"] in ["center", "top", "bottom"] else 0
                    self.valign_dd.set_selected(idx)
                if "entrance_anim" in opts:
                    anim_list = ["none", "fade_in", "slide_up", "slide_down", "scale_up", "bounce", "rotate_in"]
                    idx = anim_list.index(opts["entrance_anim"]) if opts["entrance_anim"] in anim_list else 0
                    self.entrance_anim_dd.set_selected(idx)
                if "show_delay" in opts: getattr(self, "delay_spin").set_value(opts["show_delay"])
                if "show_os" in opts: getattr(self, "os_switch").set_active(opts["show_os"])
                if "os_valign" in opts and hasattr(self, "os_valign_dd"):
                    idx = ["bottom", "top", "center"].index(opts["os_valign"]) if opts["os_valign"] in ["bottom", "top", "center"] else 0
                    self.os_valign_dd.set_selected(idx)
                if "show_progress" in opts: self.prog_switch.set_active(opts["show_progress"])
                if "prog_style" in opts:
                    prog_style = opts["prog_style"]
                    if prog_style.startswith("spinner"): prog_style = "spinner"
                    idx = ["classic", "thin", "spinner"].index(prog_style) if prog_style in ["classic", "thin", "spinner"] else 0
                    self.prog_style_dd.set_selected(idx)
                if "show_bgrt" in opts: self.bgrt_switch.set_active(opts["show_bgrt"])
                if "pulse_secondary" in opts: self.pulse_switch.set_active(opts["pulse_secondary"])
                if "rainbow_bg" in opts: self.rainbow_switch.set_active(opts["rainbow_bg"])

                if "prog_color" in opts:
                    color = Gdk.RGBA()
                    if color.parse(opts["prog_color"]): self.btn_prog_color.set_rgba(color)
                
                self._update_preview_msg_prog()
            except Exception as e:
                print("Failed to load theme config:", e)

    def _on_clear_bg(self, btn):
        self.bg_path = None
        self.btn_bg_file.set_label("Choose Image")
        self.btn_clear_bg.set_sensitive(False)
        self._update_preview_bg()

    def _on_choose_os_logo(self, btn):
        dialog = Gtk.FileDialog(title="Select OS Logo")
        f_filter = Gtk.FileFilter()
        f_filter.set_name("Images")
        for mt in ["image/png", "image/jpeg", "image/svg+xml"]:
            f_filter.add_mime_type(mt)
        dialog.set_default_filter(f_filter)
        dialog.open(self.parent_window, None, self._on_os_logo_chosen)

    def _on_os_logo_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if not file: return
            self.os_logo_path = file.get_path()
            self.btn_os_logo.set_label(os.path.basename(self.os_logo_path))
            self.btn_clear_os_logo.set_sensitive(True)
            self.os_switch.set_active(True)
        except Exception:
            pass

    def _on_clear_os_logo(self, btn):
        self.os_logo_path = None
        self.btn_os_logo.set_label("Custom Logo")
        self.btn_clear_os_logo.set_sensitive(False)

    def _on_choose_bg_file(self, btn):
        dialog = Gtk.FileDialog(title="Select Background Image or Video")
        f_filter = Gtk.FileFilter()
        f_filter.set_name("Media (Images and Videos)")
        for mt in ["image/png", "image/jpeg", "image/gif", "video/mp4", "video/x-matroska"]:
            f_filter.add_mime_type(mt)
        for p in ["*.mp4", "*.mkv", "*.webm"]:
            f_filter.add_pattern(p)
        dialog.set_default_filter(f_filter)
        dialog.open(self.parent_window, None, self._on_bg_file_chosen)

    def _on_bg_file_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self.preview_container.set_visible(True)
                self.bg_path = file.get_path()
                self.btn_bg_file.set_label(os.path.basename(self.bg_path))
                self.btn_clear_bg.set_sensitive(True)
                self._update_preview_bg()
        except Exception:
            pass

    def _on_choose_file(self, btn):
        dialog = Gtk.FileDialog(title="Select Media File")
        f_filter = Gtk.FileFilter()
        f_filter.set_name("Media (Images and Videos)")
        for mt in ["image/png", "image/jpeg", "image/gif", "video/mp4", "video/x-matroska"]:
            f_filter.add_mime_type(mt)
        for p in ["*.mp4", "*.mkv", "*.webm"]:
            f_filter.add_pattern(p)
        dialog.set_default_filter(f_filter)
        dialog.open(self.parent_window, None, self._on_file_chosen)

    def _on_choose_file2(self, btn):
        dialog = Gtk.FileDialog(title="Select Secondary Logo")
        f_filter = Gtk.FileFilter()
        f_filter.set_name("Images")
        for mt in ["image/png", "image/jpeg", "image/gif"]:
            f_filter.add_mime_type(mt)
        dialog.set_default_filter(f_filter)
        dialog.open(self.parent_window, None, self._on_file2_chosen)

    def _on_clear_file2(self, btn):
        self.source_path_2 = None
        self.btn_file2.set_label("Choose Image")
        self.btn_clear_file2.set_sensitive(False)
        self.pulse_switch.set_active(False)

    def _on_file2_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if not file: return
            self.source_path_2 = file.get_path()
            self.btn_file2.set_label(os.path.basename(self.source_path_2))
            self.btn_clear_file2.set_sensitive(True)
            self.pulse_switch.set_active(True)
        except Exception:
            pass

    def _on_clear_file(self, btn):
        self.source_path = None
        self.btn_file.set_label("Choose File")
        self.btn_clear_file.set_sensitive(False)
        self._stop_gif_timer()
        self.preview_img.set_visible(False)
        self.preview_img.set_paintable(None)
        self.preview_img.set_file(None)
        if not self.bg_path and not self.os_switch.get_active() and not self.bgrt_switch.get_active():
            self.preview_container.set_visible(False)

    def _stop_gif_timer(self):
        if self._gif_timer_id:
            GLib.source_remove(self._gif_timer_id)
            self._gif_timer_id = None
        self._gif_frames = []
        self._gif_frame_idx = 0

    def _on_file_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if not file:
                return
            self.preview_container.set_visible(True)
            self.source_path = file.get_path()
            self.btn_file.set_label(os.path.basename(self.source_path))
            self.btn_clear_file.set_sensitive(True)
            self._stop_gif_timer()
            
            # Reset both previews
            if self._gif_timer_id:
                GLib.source_remove(self._gif_timer_id)
                self._gif_timer_id = None
            self._gif_frames = []

            ext = self.source_path.lower()
            if ext.endswith((".mp4", ".mkv", ".avi", ".webm")):
                self.preview_img.set_visible(True)
                self.preview_img.set_paintable(None)
                self._start_video_preview(self.source_path)
            elif ext.endswith(".gif"):
                self.preview_img.set_visible(True)
                self._start_gif_preview(self.source_path)
            else:
                self.preview_img.set_visible(True)
                self.preview_img.set_file(Gio.File.new_for_path(self.source_path))
        except Exception as e:
            print(f"Error loading preview: {e}")
            self.show_toast(f"Error loading media: {e}")

    def _start_video_preview(self, path):
        import subprocess
        import threading
        import tempfile
        import shutil

        def _extract_and_load():
            try:
                td = tempfile.mkdtemp(prefix="gtm_vid_preview_")
                # Extract 45 frames at 15fps (~3s of video)
                subprocess.run(["ffmpeg", "-y", "-i", path, "-vframes", "45", "-r", "15", "-s", "320x200", f"{td}/frame_%03d.png"], capture_output=True)
                frames = []
                for p in sorted(Path(td).glob("frame_*.png")):
                    pb = GdkPixbuf.Pixbuf.new_from_file(str(p))
                    tex = Gdk.Texture.new_for_pixbuf(pb)
                    frames.append((tex, 66)) # 66ms delay ~ 15fps
                shutil.rmtree(td, ignore_errors=True)
                if frames:
                    GLib.idle_add(self._on_video_frames_loaded, frames)
            except Exception as e:
                print("Error extracting video frames:", e)

        threading.Thread(target=_extract_and_load, daemon=True).start()

    def _on_video_frames_loaded(self, frames):
        if self._gif_timer_id:
            GLib.source_remove(self._gif_timer_id)
            self._gif_timer_id = None
        self._gif_frames = frames
        self._gif_frame_idx = 0
        self.preview_img.set_paintable(frames[0][0])
        self._gif_timer_id = GLib.timeout_add(frames[0][1], self._advance_gif_frame)

    def _start_gif_preview(self, path):
        """Load GIF frames via GdkPixbuf.PixbufAnimation and cycle them with a timer."""
        try:
            anim = GdkPixbuf.PixbufAnimation.new_from_file(path)
            if anim.is_static_image():
                self.preview_img.set_file(Gio.File.new_for_path(path))
                return
            it = anim.get_iter(None)
            frames = []
            seen = set()
            for _ in range(500):
                pb = it.get_pixbuf()
                key = id(pb)
                if key in seen:
                    break
                seen.add(key)
                tex = Gdk.Texture.new_for_pixbuf(pb)
                delay = max(it.get_delay_time(), 20)
                frames.append((tex, delay))
                it.advance(None)
            if not frames:
                self.preview_img.set_file(Gio.File.new_for_path(path))
                return
            self._gif_frames = frames
            self._gif_frame_idx = 0
            self.preview_img.set_paintable(frames[0][0])
            self._gif_timer_id = GLib.timeout_add(frames[0][1], self._advance_gif_frame)
        except Exception:
            self.preview_img.set_file(Gio.File.new_for_path(path))

    def _advance_gif_frame(self):
        if not self._gif_frames:
            return False
        self._gif_frame_idx = (self._gif_frame_idx + 1) % len(self._gif_frames)
        tex, delay = self._gif_frames[self._gif_frame_idx]
        self.preview_img.set_paintable(tex)
        self._gif_timer_id = GLib.timeout_add(delay, self._advance_gif_frame)
        return False

    def _on_create(self, btn):
        if not self.source_path and not self.bg_path and not self.bgrt_switch.get_active() and not self.os_switch.get_active():
            self.show_toast("Please select at least a logo, background, OS logo, or BGRT to create a theme.")
            return
        name = self.name_entry.get_text().strip()
        if not name:
            self.show_toast("Theme name cannot be empty.")
            return

        # Block creation if theme already exists in system, unless we are editing an existing one
        theme_exists = False
        for p in [Path("/usr/share/plymouth/themes"), Path.home() / ".local/share/plymouth/themes"]:
            if (p / name).exists() and (p / name).is_dir():
                theme_exists = True
                break

        if theme_exists:
            if hasattr(self, 'editing_existing_dir') and self.editing_existing_dir:
                dlg = Adw.MessageDialog(
                    transient_for=self.parent_window,
                    heading="Overwrite Theme?",
                    body=f"You are editing a theme and the name '{name}' already exists in the system. Do you want to overwrite it?",
                )
                dlg.add_response("cancel", "Cancel")
                dlg.add_response("overwrite", "Overwrite")
                dlg.set_response_appearance("overwrite", Adw.ResponseAppearance.DESTRUCTIVE)
                
                def on_response(dialog, response):
                    if response == "overwrite":
                        self._do_create(btn, name)
                        
                dlg.connect("response", on_response)
                dlg.present()
                return
            else:
                self.show_toast(f"⚠️ A theme named '{name}' already exists. Choose a different name or edit the existing theme.")
                return

        self._do_create(btn, name)

    def _do_create(self, btn, name):
        btn.set_sensitive(False)
        self.btn_install.set_sensitive(False)
        self.show_toast("Generating Plymouth theme...")

        c1 = self.btn_col_start.get_rgba()
        c2 = self.btn_col_end.get_rgba()
        hex_start = f"0x{int(c1.red*255):02x}{int(c1.green*255):02x}{int(c1.blue*255):02x}"
        hex_end = f"0x{int(c2.red*255):02x}{int(c2.green*255):02x}{int(c2.blue*255):02x}"

        opts = {
            "fps": int(self.fps_spin.get_value()),
            "scale_pct": int(self.scale_spin.get_value()),
            "roundness": int(self.round_spin.get_value()),
            "valign": ["center", "top", "bottom"][self.valign_dd.get_selected()],
            "entrance_anim": ["none", "fade_in", "slide_up", "slide_down", "scale_up", "bounce", "rotate_in"][self.entrance_anim_dd.get_selected()],
            "show_delay": int(getattr(self, "delay_spin").get_value()) if hasattr(self, "delay_spin") else 0,
            "show_os": getattr(self, "os_switch").get_active() if hasattr(self, "os_switch") else False,
            "os_valign": ["bottom", "top", "center"][getattr(self, "os_valign_dd").get_selected()] if hasattr(self, "os_valign_dd") else "bottom",
            "blur_radius": int(getattr(self, "blur_spin").get_value()) if hasattr(self, "blur_spin") else 0,
            "show_progress": self.prog_switch.get_active(),
            "prog_style": ["classic", "thin", "spinner"][self.prog_style_dd.get_selected()],
            "prog_color": self.btn_prog_color.get_rgba().to_string(),
            "show_bgrt": self.bgrt_switch.get_active(),
            "bg_s": hex_start,
            "bg_e": hex_end,
            "pulse_secondary": self.pulse_switch.get_active(),
            "rainbow_bg": self.rainbow_switch.get_active()
        }
        threading.Thread(target=self._generate, args=(name, self.source_path, self.bg_path, hex_start, hex_end, opts), daemon=True).start()

    def _generate(self, name, source, bg_source, bg_s, bg_e, opts):
        try:
            export_dir = os.path.expanduser("~/.config/gnome-theme-manager/plymouth_exports")
            os.makedirs(export_dir, exist_ok=True)
            theme_dir = os.path.join(export_dir, name)
            if os.path.exists(theme_dir):
                shutil.rmtree(theme_dir)
            os.makedirs(theme_dir)

            if hasattr(self, 'editing_existing_dir') and self.editing_existing_dir:
                for f in self.editing_existing_dir.iterdir():
                    if f.is_file(): shutil.copy2(f, theme_dir)
                
                # Fix old broken themes that started at 0001
                if not os.path.exists(os.path.join(theme_dir, "throbber-0000.png")) and os.path.exists(os.path.join(theme_dir, "throbber-0001.png")):
                    for p in sorted(Path(theme_dir).glob("throbber-*.png")):
                        try:
                            idx = int(p.stem.split("-")[-1])
                            p.rename(os.path.join(theme_dir, f"throbber-{idx-1:04d}.png"))
                        except: pass
                        
                if not os.path.exists(os.path.join(theme_dir, "bg-0000.png")) and os.path.exists(os.path.join(theme_dir, "bg-0001.png")):
                    for p in sorted(Path(theme_dir).glob("bg-*.png")):
                        try:
                            if p.stem.startswith("bg-"):
                                idx = int(p.stem.split("-")[-1])
                                p.rename(os.path.join(theme_dir, f"bg-{idx-1:04d}.png"))
                        except: pass
            elif source:
                ext = source.lower()
                if ext.endswith(".gif"):
                    import subprocess
                    cmd = ["convert", source, "-coalesce", os.path.join(theme_dir, "throbber-%04d.png")]
                    subprocess.run(cmd, check=True)
                elif ext.endswith((".mp4", ".mkv", ".avi", ".webm")):
                    import subprocess
                    fps = opts.get("fps", 24)
                    cmd = ["ffmpeg", "-i", source, "-vf", f"fps={fps}", "-start_number", "0", os.path.join(theme_dir, "throbber-%04d.png")]
                    subprocess.run(cmd, check=True)
                else:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(source)
                    pixbuf.savev(os.path.join(theme_dir, "header-image.png"), "png", [], [])

            import json
            with open(os.path.join(theme_dir, ".gtm-config.json"), "w", encoding="utf-8") as f:
                json.dump(opts, f, indent=4)

            if opts.get("roundness", 0) > 0:
                import subprocess
                pct = opts.get("roundness")
                for frame in list(Path(theme_dir).glob("throbber-*.png")) + list(Path(theme_dir).glob("header-image.png")):
                    try:
                        pb = GdkPixbuf.Pixbuf.new_from_file(str(frame))
                        w, h = pb.get_width(), pb.get_height()
                        rx = int(w * (pct / 100.0))
                        ry = int(h * (pct / 100.0))
                        mask_path = os.path.join(theme_dir, "mask.png")
                        subprocess.run(["convert", "-size", f"{w}x{h}", "xc:none", "-draw", f"roundrectangle 0,0,{w},{h},{rx},{ry}", mask_path], check=True)
                        subprocess.run(["convert", str(frame), "-alpha", "set", mask_path, "-compose", "DstIn", "-composite", str(frame)], check=True)
                    except: pass
                mask_path = os.path.join(theme_dir, "mask.png")
                if os.path.exists(mask_path): os.remove(mask_path)

            if bg_source:
                try:
                    ext = bg_source.lower()
                    if ext.endswith((".mp4", ".mkv", ".webm", ".avi", ".gif")):
                        import subprocess
                        subprocess.run(["ffmpeg", "-i", bg_source, "-vf", "fps=10,scale=1920:1080", "-start_number", "0", "-vframes", "30", os.path.join(theme_dir, "bg-%04d.png")], check=True)
                        has_animated_bg = True
                        if opts.get("blur_radius", 0) > 0:
                            for frame in Path(theme_dir).glob("bg-*.png"):
                                subprocess.run(["convert", str(frame), "-blur", f"0x{opts.get('blur_radius')}", str(frame)], check=True)
                    else:
                        pb = GdkPixbuf.Pixbuf.new_from_file(bg_source)
                        pb.savev(os.path.join(theme_dir, "background.png"), "png", [], [])
                        if opts.get("blur_radius", 0) > 0:
                            import subprocess
                            subprocess.run(["convert", os.path.join(theme_dir, "background.png"), "-blur", f"0x{opts.get('blur_radius')}", os.path.join(theme_dir, "background.png")], check=True)
                except Exception as e:
                    print("BG error:", e)

            if opts.get("pulse_secondary") and self.source_path_2:
                try:
                    pb2 = GdkPixbuf.Pixbuf.new_from_file(self.source_path_2)
                    pb2.savev(os.path.join(theme_dir, "logo2.png"), "png", [], [])
                except Exception as e:
                    print("Logo2 error:", e)

            # Build script
            scale = opts.get("scale_pct", 50) / 100.0
            valign_map = {"center": "0.5", "top": "0.2", "bottom": "0.8"}
            valign_val = valign_map.get(opts.get("valign", "center"), "0.5")

            rainbow_script_init = ""
            rainbow_script = ""
            if opts.get("rainbow_bg"):
                rainbow_script_init = "global.duration = 100;\nglobal.jiffies = 1;\nglobal.r = 0.78;\nglobal.g = 0.0;\nglobal.b = 0.0;\n"
                rainbow_script = """
    if (global.jiffies >= (global.duration * 6)){
        global.jiffies = 0;
        global.r = 0.78; global.g = 0.0; global.b = 0.0;
    }
    global.jiffies++;
    if (global.jiffies > 0 && global.jiffies <= global.duration){
        global.r = Math.Clamp((global.r - 0.0 / global.duration), 0, 1);
        global.g = Math.Clamp((global.g + 0.78 / global.duration), 0, 1);
    } else if (global.jiffies > global.duration && global.jiffies <= (global.duration * 2)){
        global.r = Math.Clamp((global.r - 0.78 / global.duration), 0, 1);
        global.g = Math.Clamp((global.g - 0.23 / global.duration), 0, 1);
    } else if (global.jiffies > (global.duration * 2) && global.jiffies <= (global.duration * 3)){
        global.g = Math.Clamp((global.g + 0.16 / global.duration), 0, 1);
        global.b = Math.Clamp((global.b + 0.70 / global.duration), 0, 1);
    } else if (global.jiffies > (global.duration * 3) && global.jiffies <= (global.duration * 4)){
        global.g = Math.Clamp((global.g - 0.71 / global.duration), 0, 1);
        global.b = Math.Clamp((global.b + 0.30 / global.duration), 0, 1);
    } else if (global.jiffies > (global.duration * 4) && global.jiffies <= (global.duration * 5)){
        global.b = Math.Clamp((global.b - 0.22 / global.duration), 0, 1);
        global.r = Math.Clamp((global.r + 0.78 / global.duration), 0, 1);
    } else if (global.jiffies > (global.duration * 5) && global.jiffies <= (global.duration * 6)){
        global.b = Math.Clamp((global.b - 0.78 / global.duration), 0, 1);
        global.r = Math.Clamp((global.r + 0.00 / global.duration), 0, 1);
    }
    Window.SetBackgroundTopColor (global.b, global.r, global.g);
    Window.SetBackgroundBottomColor (global.r, global.g, global.b);
"""
            
            pulse_script_init = ""
            pulse_script = ""
            if opts.get("pulse_secondary") and self.source_path_2:
                pulse_script_init = """
global.logo2_image = Image("logo2.png");
if (global.logo2_image) {
    global.logo2_sprite = Sprite();
    global.logo2_opacity_angle = Math.Pi;
}
"""
                pulse_script = f"""
    if (global.logo2_sprite) {{
        scaled_logo2 = global.logo2_image.Scale(new_w, new_h);
        global.logo2_sprite.SetImage(scaled_logo2);
        global.logo2_sprite.SetX(sw / 2 - new_w / 2);
        global.logo2_sprite.SetY(sh * {valign_val} - new_h / 2);
        global.logo2_opacity_angle += ((2 * Math.Pi) / 50) * 0.4;
        opacity_blurred = ( Math.Cos (global.logo2_opacity_angle) + 1) / 2;
        global.logo2_sprite.SetOpacity (opacity_blurred * anim_p);
    }}
"""
            
            pc_val = opts.get("prog_color", Gdk.RGBA(0.2, 0.5, 1.0, 1))
            pc = Gdk.RGBA()
            if isinstance(pc_val, str): pc.parse(pc_val)
            else: pc = pc_val
            prog_r, prog_g, prog_b = pc.red, pc.green, pc.blue

            bg_script = ""
            if bg_source:
                ext = bg_source.lower()
                if ext.endswith((".mp4", ".mkv", ".webm", ".avi", ".gif")):
                    bg_script = """
Window.SetBackgroundTopColor(0, 0, 0);
Window.SetBackgroundBottomColor(0, 0, 0);
global.bg_sprite = Sprite();
global.bg_images = [];
screen_width = Window.GetWidth();
screen_height = Window.GetHeight();
for (i = 0; i < 30; i++) {
    index_str = i;
    if (i < 10) index_str = "000" + i;
    else if (i < 100) index_str = "00" + i;
    else if (i < 1000) index_str = "0" + i;
    img = Image("bg-" + index_str + ".png");
    if (!img) break;
    global.bg_images[i] = img.Scale(screen_width, screen_height);
}
global.num_bg_frames = 0;
while (global.bg_images[global.num_bg_frames]) global.num_bg_frames++;
if (global.num_bg_frames > 0) {
    global.bg_sprite.SetImage(global.bg_images[0]);
    global.bg_sprite.SetPosition(0, 0, -10000);
}
"""
                else:
                    bg_script = """
Window.SetBackgroundTopColor(0, 0, 0);
Window.SetBackgroundBottomColor(0, 0, 0);
bg_image = Image("background.png");
if (bg_image) {
    screen_width = Window.GetWidth();
    screen_height = Window.GetHeight();
    resized_bg = bg_image.Scale(screen_width, screen_height);
    global.bg_sprite = Sprite(resized_bg);
    global.bg_sprite.SetPosition(0, 0, -10000);
}
"""
            else:
                r1 = (int(bg_s.replace("0x",""), 16) >> 16 & 0xFF) / 255.0 if "0x" in bg_s else 0
                g1 = (int(bg_s.replace("0x",""), 16) >> 8 & 0xFF) / 255.0 if "0x" in bg_s else 0
                b1 = (int(bg_s.replace("0x",""), 16) & 0xFF) / 255.0 if "0x" in bg_s else 0
                r2 = (int(bg_e.replace("0x",""), 16) >> 16 & 0xFF) / 255.0 if "0x" in bg_e else 0
                g2 = (int(bg_e.replace("0x",""), 16) >> 8 & 0xFF) / 255.0 if "0x" in bg_e else 0
                b2 = (int(bg_e.replace("0x",""), 16) & 0xFF) / 255.0 if "0x" in bg_e else 0
                bg_script = f"""
Window.SetBackgroundTopColor({r1:.3f}, {g1:.3f}, {b1:.3f});
Window.SetBackgroundBottomColor({r2:.3f}, {g2:.3f}, {b2:.3f});
"""



            bgrt_script = ""
            if opts.get("show_bgrt"):
                bgrt_bmp = Path("/sys/firmware/acpi/bgrt/image")
                if bgrt_bmp.exists():
                    try:
                        pix = GdkPixbuf.Pixbuf.new_from_file(str(bgrt_bmp))
                        pix.savev(os.path.join(theme_dir, "bgrt.png"), "png", [], [])
                        bgrt_script = f"""
bgrt_image = Image("bgrt.png");
if (bgrt_image) {{
    global.bgrt_sprite = Sprite(bgrt_image);
    global.bgrt_sprite.SetPosition(Window.GetWidth() / 2 - bgrt_image.GetWidth() / 2, Window.GetHeight() * 0.2, -50);
}}
"""
                    except Exception as e:
                        print("BGRT conversion failed:", e)

            prog_script = ""
            if opts.get("show_progress"):
                def create_color_png(path, r, g, b, a):
                    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
                    pixbuf.fill((int(r*255) << 24) | (int(g*255) << 16) | (int(b*255) << 8) | int(a*255))
                    pixbuf.savev(path, "png", [], [])
                
                create_color_png(os.path.join(theme_dir, "box.png"), 1.0, 1.0, 1.0, 0.2)
                create_color_png(os.path.join(theme_dir, "bar.png"), prog_r, prog_g, prog_b, 1.0)
                
                style = opts.get("prog_style", "classic")
                
                if style.startswith("spinner"):
                    import subprocess
                    import math
                    # Generate 12 rotated spinner frame PNGs for smooth stepping
                    num_sp_frames = 12
                    sp_size = 64
                    for frame_idx in range(num_sp_frames):
                        sp_path = os.path.join(theme_dir, f"spinner-{frame_idx:04d}.png")
                        pixels = bytearray(sp_size * sp_size * 4)
                        cx, cy = sp_size / 2, sp_size / 2
                        radius = 12
                        thickness = 10
                        rot_offset = math.radians(frame_idx * 30)
                        
                        for y in range(sp_size):
                            for x in range(sp_size):
                                dx = x - cx + 0.5
                                dy = y - cy + 0.5
                                dist = math.hypot(dx, dy)
                                pixel_angle = math.atan2(dy, dx)
                                
                                max_alpha = 0.0
                                
                                # Process each of the 3 comets
                                for i in range(3):
                                    base_angle = rot_offset + math.radians(i * 120)
                                    # Get theta in degrees [0, 360)
                                    theta = math.degrees((pixel_angle - base_angle) % (2 * math.pi))
                                    
                                    alpha = 0.0
                                    if 0 <= theta <= 110:
                                        dist_to_shape = abs(dist - radius)
                                        if dist_to_shape <= thickness / 2 + 0.5:
                                            base_alpha = theta / 110.0
                                            edge_aa = min(max(thickness/2 - dist_to_shape + 0.5, 0.0), 1.0)
                                            alpha = base_alpha * edge_aa
                                    elif 110 < theta < 180:
                                        head_angle = base_angle + math.radians(110)
                                        head_x = radius * math.cos(head_angle)
                                        head_y = radius * math.sin(head_angle)
                                        dist_to_head = math.hypot(dx - head_x, dy - head_y)
                                        if dist_to_head <= thickness / 2 + 0.5:
                                            edge_aa = min(max(thickness/2 - dist_to_head + 0.5, 0.0), 1.0)
                                            alpha = 1.0 * edge_aa
                                            
                                    if alpha > max_alpha:
                                        max_alpha = alpha
                                        
                                if max_alpha > 0:
                                    idx = (y * sp_size + x) * 4
                                    pixels[idx] = int(prog_r * 255)
                                    pixels[idx+1] = int(prog_g * 255)
                                    pixels[idx+2] = int(prog_b * 255)
                                    pixels[idx+3] = int(max_alpha * 255)
                                        
                        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB, True, 8, sp_size, sp_size, sp_size * 4)
                        pb.savev(sp_path, "png", [], [])
                    
                    prog_script = f"""
global.spinner_images = [];
for (i = 0; i < {num_sp_frames}; i++) {{
    index_str = i;
    if (i < 10) index_str = "000" + i;
    else if (i < 100) index_str = "00" + i;
    global.spinner_images[i] = Image("spinner-" + index_str + ".png");
}}
global.spinner_sprite = Sprite();
global.spinner_frame = 0;
fun progress_callback(duration, progress) {{
    if (global.spinner_images[0]) {{
        global.spinner_frame = Math.Int(duration * 12) % {num_sp_frames};
        cur_img = global.spinner_images[global.spinner_frame];
        global.spinner_sprite.SetImage(cur_img);
        global.spinner_sprite.SetPosition(Window.GetWidth() / 2 - cur_img.GetWidth() / 2, Window.GetHeight() * 0.76, 10);
    }}
}}
Plymouth.SetBootProgressFunction(progress_callback);
"""
                else:
                    bw = "200"
                    bh = "6"
                    if style == "thin":
                        bw = "300"
                        bh = "2"
                    
                    prog_script = f"""
progress_box = Image("box.png");
progress_bar = Image("bar.png");
progress_box_sprite = Sprite();
progress_bar_sprite = Sprite();

fun progress_callback(duration, progress) {{
    bar_w = {bw};
    bar_h = {bh};
    box_x = Window.GetWidth() / 2 - bar_w / 2;
    box_y = Window.GetHeight() * 0.76;
    
    scaled_box = progress_box.Scale(bar_w, bar_h);
    progress_box_sprite.SetImage(scaled_box);
    progress_box_sprite.SetPosition(box_x, box_y, 10);
    
    fill_w = bar_w * progress;
    if (fill_w > 0) {{
        scaled_bar = progress_bar.Scale(fill_w, bar_h);
        progress_bar_sprite.SetImage(scaled_bar);
        progress_bar_sprite.SetPosition(box_x, box_y, 11);
    }}
}}
Plymouth.SetBootProgressFunction(progress_callback);
"""

            fade_script = "            anim_p = 1.0;\n"
            anim_type = opts.get("entrance_anim", "none")
            fps_val = opts.get("fps", 24)
            if anim_type != "none":
                fade_script = f"anim_p = progress / {fps_val:.2f};\n            if (anim_p > 1.0) anim_p = 1.0;\n"
                if anim_type == "fade_in":
                    fade_script += "            global.anim_sprite.SetOpacity(anim_p);\n"
                elif anim_type == "slide_up":
                    fade_script += f"            global.anim_sprite.SetOpacity(anim_p);\n            global.anim_sprite.SetY(sh * {valign_val} - new_h / 2 + (1.0 - anim_p) * 100);\n"
                elif anim_type == "slide_down":
                    fade_script += f"            global.anim_sprite.SetOpacity(anim_p);\n            global.anim_sprite.SetY(sh * {valign_val} - new_h / 2 - (1.0 - anim_p) * 100);\n"
                elif anim_type == "scale_up":
                    fade_script += f"            s_w = Math.Int(new_w * (0.5 + 0.5 * anim_p));\n            s_h = Math.Int(new_h * (0.5 + 0.5 * anim_p));\n"
                    fade_script += f"            global.anim_sprite.SetImage(cur.Scale(s_w, s_h));\n"
                    fade_script += f"            global.anim_sprite.SetX(sw / 2 - s_w / 2);\n            global.anim_sprite.SetY(sh * {valign_val} - s_h / 2);\n            global.anim_sprite.SetOpacity(anim_p);\n"
                elif anim_type == "bounce":
                    fade_script += f"            if (anim_p < 0.5) {{\n"
                    fade_script += f"                global.anim_sprite.SetOpacity(anim_p * 2);\n"
                    fade_script += f"                global.anim_sprite.SetY(sh * {valign_val} - new_h / 2 + (1.0 - anim_p * 2) * 80);\n"
                    fade_script += f"            }} else {{\n"
                    fade_script += f"                global.anim_sprite.SetOpacity(1.0);\n"
                    fade_script += f"                bounce_t = (anim_p - 0.5) * 4;\n"
                    fade_script += f"                if (bounce_t > 1.0) bounce_t = 1.0;\n"
                    fade_script += f"                bounce_off = Math.Int((1.0 - bounce_t) * 20);\n"
                    fade_script += f"                global.anim_sprite.SetY(sh * {valign_val} - new_h / 2 - bounce_off);\n"
                    fade_script += f"            }}\n"
                elif anim_type == "rotate_in":
                    fade_script += f"            global.anim_sprite.SetOpacity(anim_p);\n"
                    fade_script += f"            rot_angle = (1.0 - anim_p) * 6.28318;\n"
                    fade_script += f"            rot_img = cur.Rotate(rot_angle);\n"
                    fade_script += f"            global.anim_sprite.SetImage(rot_img);\n"
                    fade_script += f"            global.anim_sprite.SetX(sw / 2 - rot_img.GetWidth() / 2);\n"
                    fade_script += f"            global.anim_sprite.SetY(sh * {valign_val} - rot_img.GetHeight() / 2);\n"
                
                if bg_source: fade_script += "            if (global.bg_sprite) global.bg_sprite.SetOpacity(anim_p);\n"
                if opts.get("show_bgrt"): fade_script += "            if (global.bgrt_sprite) global.bgrt_sprite.SetOpacity(anim_p);\n"

            os_script = ""
            if opts.get("show_os"):
                found_logo = None
                if self.os_logo_path and os.path.exists(self.os_logo_path):
                    found_logo = self.os_logo_path
                else:
                    logo_paths = [
                        "/usr/share/plymouth/ubuntu-logo.png",
                        "/usr/share/plymouth/fedora-logo.png",
                        "/usr/share/plymouth/themes/spinner/watermark.png",
                        "/usr/share/plymouth/themes/bgrt/watermark.png",
                        "/usr/share/pixmaps/system-logo-white.png"
                    ]
                    for p in logo_paths:
                        if Path(p).exists():
                            found_logo = p
                            break
                if found_logo:
                    shutil.copy2(found_logo, os.path.join(theme_dir, "os-logo.png"))
                    os_v_map = {"bottom": "0.86", "top": "0.1", "center": "0.5"}
                    os_v = os_v_map.get(opts.get("os_valign", "bottom"), "0.86")
                    os_script = f"""
global.os_image = Image("os-logo.png");
if (global.os_image) {{
    global.os_sprite = Sprite(global.os_image);
    global.os_sprite.SetPosition(Window.GetWidth() / 2 - global.os_image.GetWidth() / 2, Window.GetHeight() * {os_v}, 10);
}}
"""

            quit_script = ""
            wait_check = ""
            if opts.get("wait_video"):
                quit_script = """
global.is_quitting = 0;
fun quit_callback() {
    global.is_quitting = 1;
}
Plymouth.SetQuitFunction(quit_callback);
"""
                wait_check = """
    if (global.is_quitting) {
        if (num_frames > 0 && Math.Int(progress) >= num_frames - 1) Plymouth.Quit();
        else if (num_frames == 0 && global.num_bg_frames > 0 && Math.Int(global.bg_progress) >= global.num_bg_frames - 1) Plymouth.Quit();
        else if (num_frames == 0 && global.num_bg_frames == 0) Plymouth.Quit();
    }
"""

            script_content = f"""{bg_script}
{rainbow_script_init}
{pulse_script_init}
anim_images = [];
for (i = 0; i < 500; i++) {{
    index_str = i;
    if (i < 10) index_str = "000" + i;
    else if (i < 100) index_str = "00" + i;
    else if (i < 1000) index_str = "0" + i;
    img = Image("throbber-" + index_str + ".png");
    if (!img) break;
    anim_images[i] = img;
}}

if (!anim_images[0]) {{
    anim_images[0] = Image("header-image.png");
}}

if (anim_images[0]) {{
    global.anim_sprite = Sprite();
    sw = Window.GetWidth();
    sh = Window.GetHeight();
    iw = anim_images[0].GetWidth();
    ih = anim_images[0].GetHeight();
    scale_factor = {scale:.2f};
    new_w = Math.Int(sw * scale_factor);
    new_h = Math.Int(ih * (new_w / iw));
    global.anim_sprite.SetX(sw / 2 - new_w / 2);
    global.anim_sprite.SetY(sh * {valign_val} - new_h / 2);
}}

progress = 0;
global.bg_progress = 0;
num_frames = 0;
while (anim_images[num_frames]) num_frames++;

fun refresh_callback() {{
    if (num_frames > 0) {{
        cur = anim_images[Math.Int(progress) % num_frames];
        scaled = cur.Scale(new_w, new_h);
        global.anim_sprite.SetImage(scaled);
        {fade_script}
        {pulse_script}
    }}
{wait_check}
{rainbow_script}
    progress += {opts.get("fps", 24) / 50.0:.3f};
    if (global.num_bg_frames > 0) {{
        global.bg_sprite.SetImage(global.bg_images[Math.Int(global.bg_progress) % global.num_bg_frames]);
        global.bg_progress += 0.2;
    }}
}}
Plymouth.SetRefreshFunction(refresh_callback);
{bgrt_script}
{os_script}
{prog_script}
{quit_script}
"""
            with open(os.path.join(theme_dir, f"{name}.script"), "w") as f:
                f.write(script_content)

            cfg = f"""[Plymouth Theme]
Name={name}
Description=Created by Gnome Theme Manager
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/{name}
ScriptFile=/usr/share/plymouth/themes/{name}/{name}.script
"""
            with open(os.path.join(theme_dir, f"{name}.plymouth"), "w") as f:
                f.write(cfg)

            import json
            with open(os.path.join(theme_dir, ".gtm-config.json"), "w", encoding="utf-8") as f:
                json.dump(opts, f, indent=4)

            self.created_theme_dir = theme_dir
            self.created_theme_name = name
            GLib.idle_add(self._generate_success)
        except Exception as e:
            GLib.idle_add(self._generate_error, str(e))

    def _generate_success(self):
        self.btn_create.set_sensitive(True)
        self.btn_install.set_sensitive(True)
        self.btn_preview_ply.set_sensitive(True)
        self.show_toast("✨ Theme created locally! Ready to install or preview.")

    def _generate_error(self, msg):
        self.btn_create.set_sensitive(True)
        self.show_toast(f"Error creating theme: {msg}")

    def _on_auto_blur_logo2(self, btn):
        """Generate a blurred copy of the primary source media as the secondary logo."""
        if not self.source_path:
            self.show_toast("Select a primary source media first.")
            return
        try:
            import subprocess
            blur_dir = os.path.expanduser("~/.config/gnome-theme-manager/tmp")
            os.makedirs(blur_dir, exist_ok=True)
            base = os.path.basename(self.source_path)
            name_no_ext = os.path.splitext(base)[0]
            blurred_path = os.path.join(blur_dir, f"{name_no_ext}_blurred.png")

            # Use ImageMagick if available, else use GdkPixbuf scaling trick
            if shutil.which("convert"):
                subprocess.run(["convert", self.source_path, "-blur", "0x12", blurred_path], check=True)
            elif shutil.which("magick"):
                subprocess.run(["magick", self.source_path, "-blur", "0x12", blurred_path], check=True)
            else:
                # Software fallback: downscale then upscale for a pseudo-blur
                pb = GdkPixbuf.Pixbuf.new_from_file(self.source_path)
                w, h = pb.get_width(), pb.get_height()
                tiny = pb.scale_simple(max(w // 8, 1), max(h // 8, 1), GdkPixbuf.InterpType.BILINEAR)
                blurred = tiny.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
                blurred.savev(blurred_path, "png", [], [])

            self.source_path_2 = blurred_path
            self.btn_file2.set_label(f"{name_no_ext}_blurred.png")
            self.btn_clear_file2.set_sensitive(True)
            self.pulse_switch.set_active(True)
            self.show_toast("✅ Blurred secondary logo generated.")
        except Exception as e:
            self.show_toast(f"Error generating blur: {e}")

    def _on_preview_plymouth(self, btn):
        """Preview the generated theme using plymouthd + plymouth --show-splash."""
        if not self.created_theme_dir:
            self.show_toast("Create a theme first before previewing.")
            return

        name = self.created_theme_name
        theme_dir = self.created_theme_dir
        delay = int(self.delay_spin.get_value()) if hasattr(self, 'delay_spin') else 10
        preview_secs = max(delay, 10)  # At least 10 seconds preview

        dlg = Adw.MessageDialog(
            transient_for=self.parent_window,
            heading="Preview Plymouth Theme",
            body=f"This will run a {preview_secs}-second live preview of your theme using Plymouth.\nYou will need to enter your password (sudo).",
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("preview", "Preview")
        dlg.set_response_appearance("preview", Adw.ResponseAppearance.SUGGESTED)

        def _on_response(dialog, response):
            if response != "preview":
                return
            self._run_plymouth_preview(theme_dir, name, preview_secs)
        dlg.connect("response", _on_response)
        dlg.present()

    def _run_plymouth_preview(self, theme_dir, name, secs):
        """Execute the plymouthd preview in a subprocess."""
        try:
            from .widgets import CommandDialog
            debug_log = f"/tmp/plymouth_debug_{name}.log"
            script = f"""#!/bin/bash
export PATH=$PATH:/usr/sbin:/usr/bin:/sbin:/bin

# Copy theme files for preview
mkdir -p /usr/share/plymouth/themes/{name}
cp -r "{theme_dir}/"* /usr/share/plymouth/themes/{name}/

# Save and override the default theme in plymouthd.conf
PLY_CONF="/etc/plymouth/plymouthd.conf"
if [ -f "$PLY_CONF" ]; then
    cp "$PLY_CONF" "$PLY_CONF.gtm_backup"
fi
mkdir -p /etc/plymouth
cat > "$PLY_CONF" << EOFCONF
[Daemon]
Theme={name}
ShowDelay=0
EOFCONF

# Launch plymouthd and show splash
plymouthd --debug --debug-file={debug_log}
plymouth --show-splash

echo "Plymouth preview running... Press any key to stop."

# Loop with key detection: press any key to quit early
for ((I=0; I<{secs}; I++)); do
    if read -t 1 -n 1 2>/dev/null; then
        break
    fi
    plymouth --update=test$I 2>/dev/null || true
done

# Quit plymouth
plymouth --quit

# Restore original plymouthd.conf
if [ -f "$PLY_CONF.gtm_backup" ]; then
    mv "$PLY_CONF.gtm_backup" "$PLY_CONF"
fi

echo "Preview complete."
"""
            dlg = CommandDialog(title="Plymouth Preview", script_content=script, parent_window=self.parent_window)
            dlg.present(self.parent_window)
        except Exception as e:
            self.show_toast(f"Preview error: {e}")

    def _on_install(self, btn):
        if not self.created_theme_dir:
            return
        btn.set_sensitive(False)
        self.show_toast("Installing to system...")
        self._install_to_system()

    def _install_to_system(self):
        try:
            from .widgets import CommandDialog
            delay_val = int(self.delay_spin.get_value()) if hasattr(self, 'delay_spin') else 0
            
            script = f"""#!/bin/bash
export PATH=$PATH:/usr/sbin:/usr/bin:/sbin:/bin
mkdir -p /usr/share/plymouth/themes/
cp -r "{self.created_theme_dir}" /usr/share/plymouth/themes/

# Configure ShowDelay via systemd override
if [ {delay_val} -gt 0 ]; then
    mkdir -p /etc/systemd/system/plymouth-quit.service.d
    cat << 'EOF' > /etc/systemd/system/plymouth-quit.service.d/super_long_splash.conf
[Unit]
Description=Make Plymouth Boot Screen to last longer

[Service]
ExecStartPre=/usr/bin/sleep {delay_val}
EOF
    systemctl daemon-reload
else
    rm -f /etc/systemd/system/plymouth-quit.service.d/super_long_splash.conf
    systemctl daemon-reload
fi

if command -v plymouth-set-default-theme >/dev/null 2>&1; then
    plymouth-set-default-theme -R "{self.created_theme_name}"
elif command -v update-alternatives >/dev/null 2>&1; then
    variant_path="/usr/share/plymouth/themes/{self.created_theme_name}/{self.created_theme_name}.plymouth"
    update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$variant_path" 200
    update-alternatives --set default.plymouth "$variant_path"
    if command -v update-initramfs >/dev/null 2>&1; then
        update-initramfs -u
    elif command -v dracut >/dev/null 2>&1; then
        dracut -f
    fi
fi
"""
            dlg = CommandDialog(title="Installing Plymouth theme", script_content=script, parent_window=self.parent_window)
            dlg.present(self.parent_window)
            self.close()
        except Exception as e:
            self.btn_install.set_sensitive(True)
            self.show_toast(f"Error installing theme: {e}")
