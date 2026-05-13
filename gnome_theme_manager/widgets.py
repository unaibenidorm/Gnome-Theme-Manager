"""Reusable widgets: ThemeCard and ImageViewer."""
import gi, threading
gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); gi.require_version('GdkPixbuf','2.0')
from gi.repository import Gtk, Adw, GLib, GdkPixbuf, Gdk
from . import api

class ThemeCard(Gtk.FlowBoxChild):
    def __init__(self, data, cat_key, is_installed=False):
        super().__init__()
        self.data, self.category_key = data, cat_key
        self.is_installed = is_installed
        self.set_size_request(210, 240)
        box = Gtk.Box(orientation=1, spacing=0)
        box.add_css_class("card"); box.add_css_class("theme-card")
        self.pic = Gtk.Picture()
        self.pic.set_size_request(210, 148)
        self.pic.set_content_fit(Gtk.ContentFit.COVER)
        
        fr = Gtk.Frame(); fr.set_child(self.pic); fr.add_css_class("theme-thumb-frame")
        box.append(fr)
        
        info = Gtk.Box(orientation=1, spacing=2)
        info.set_margin_start(8); info.set_margin_end(8); info.set_margin_top(6); info.set_margin_bottom(6)
        
        title_box = Gtk.Box(spacing=4)
        t = Gtk.Label(label=data.get("name","?")[:32], hexpand=True, xalign=0)
        t.set_ellipsize(3); t.add_css_class("theme-title")
        title_box.append(t)
        if is_installed:
            tick = Gtk.Image(icon_name="object-select-symbolic", valign=Gtk.Align.CENTER)
            tick.add_css_class("success")
            title_box.append(tick)
        info.append(title_box)
        
        m = Gtk.Box(spacing=6)
        cat_t = api.CATEGORIES.get(cat_key, {}).get("title", cat_key.upper())
        cat_lbl = Gtk.Label(label=cat_t)
        cat_lbl.add_css_class("dim-label"); cat_lbl.add_css_class("theme-meta")
        m.append(cat_lbl)
        dl = Gtk.Label(label=f"⬇ {data.get('downloads','0')}")
        dl.add_css_class("dim-label"); dl.add_css_class("theme-meta"); m.append(dl)
        sc = Gtk.Label(label=f"★ {data.get('score','0')}")
        sc.add_css_class("dim-label"); sc.add_css_class("theme-meta"); m.append(sc)
        info.append(m); box.append(info); self.set_child(box)
        img = data.get("previewpic1", data.get("smallpreviewpic1",""))
        if img:
            threading.Thread(target=self._load, args=(img,), daemon=True).start()

    def _load(self, url):
        d = api._make_request(url, timeout=15)
        if d: GLib.idle_add(self._set, d)

    def _set(self, d):
        try:
            lo = GdkPixbuf.PixbufLoader(); lo.write(d); lo.close()
            pb = lo.get_pixbuf()
            if pb: self.pic.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
        except Exception: pass


class InAppImageViewer(Gtk.Box):
    """In-app overlay image zoom viewer with gallery."""
    def __init__(self, urls, start=0, close_cb=None):
        super().__init__(orientation=1)
        self.urls, self.idx, self.close_cb = urls, start, close_cb
        self.scale = 1.0
        self.add_css_class("zoom-overlay")
        self.set_hexpand(True); self.set_vexpand(True)
        
        self.sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        
        # Click background to close
        bg_click = Gtk.GestureClick()
        bg_click.connect("released", lambda *args: self.close_cb() if self.close_cb else None)
        self.sw.add_controller(bg_click)
        
        # Scroll to zoom
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.sw.add_controller(scroll)
        


        self.overlay = Gtk.Overlay()
        
        self.pic_box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.pic = Gtk.Picture(); self.pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        
        self.pic_box.append(self.pic)
        self.sw.set_child(self.pic_box)
        self.overlay.set_child(self.sw)

        self.append(self.overlay)
        self.set_can_focus(True)
        self._show_img()
        GLib.idle_add(self.grab_focus)



    def _on_scroll(self, ctrl, dx, dy):
        if dy > 0: self.scale *= 0.9
        elif dy < 0: self.scale *= 1.1
        self.scale = max(0.2, min(self.scale, 5.0))
        self._update_zoom()
        return True

    def _update_zoom(self):
        if hasattr(self, 'pb') and self.pb:
            self.pic.set_size_request(int(self.pb.get_width() * self.scale), int(self.pb.get_height() * self.scale))

    def _nav(self, d):
        self.idx = (self.idx + d) % len(self.urls)
        self._show_img()

    def _show_img(self):
        self.pic.set_paintable(None)
        threading.Thread(target=self._dl, args=(self.urls[self.idx],), daemon=True).start()

    def _dl(self, url):
        d = api._make_request(url, timeout=20)
        if d: GLib.idle_add(self._apply, d)

    def _apply(self, d):
        try:
            lo = GdkPixbuf.PixbufLoader(); lo.write(d); lo.close()
            self.pb = lo.get_pixbuf()
            if self.pb:
                self.pic.set_paintable(Gdk.Texture.new_for_pixbuf(self.pb))
                self.scale = 1.0
                ww = self.get_allocated_width() or 800
                wh = self.get_allocated_height() or 600
                iw = self.pb.get_width()
                ih = self.pb.get_height()
                if iw > 0 and ih > 0:
                    r1 = ww / iw if iw > ww else 1.0
                    r2 = wh / ih if ih > wh else 1.0
                    self.scale = min(r1, r2) * 0.9
                    self.base_scale = self.scale
                    self._update_zoom()
        except Exception: pass

class CommandDialog(Adw.Dialog):
    def __init__(self, title, script_content):
        super().__init__(title=title, content_width=550, content_height=400)
        tb = Adw.ToolbarView()
        tb.add_top_bar(Adw.HeaderBar())
        
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.tv = Gtk.TextView(editable=False, monospace=True)
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.tv.set_margin_start(10); self.tv.set_margin_end(10)
        self.tv.set_margin_top(10); self.tv.set_margin_bottom(10)
        
        sw.set_child(self.tv)
        tb.set_content(sw)
        self.set_child(tb)
        
        self.script_content = script_content
        GLib.idle_add(self._run)

    def _run(self):
        threading.Thread(target=self._exec, daemon=True).start()

    def _exec(self):
        import subprocess, fcntl, os, time
        try:
            p = subprocess.Popen(["pkexec", "bash", "-c", self.script_content], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            fl = fcntl.fcntl(p.stdout, fcntl.F_GETFL)
            fcntl.fcntl(p.stdout, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            while True:
                try:
                    line = p.stdout.readline()
                    if line: GLib.idle_add(self._append, line)
                    elif p.poll() is not None: break
                except Exception: pass
                time.sleep(0.05)
                
            GLib.idle_add(self._append, f"\nProcess finished with code {p.returncode}\n")
        except Exception as e:
            GLib.idle_add(self._append, f"\nError: {str(e)}\n")

    def _append(self, text):
        buf = self.tv.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        sw = self.tv.get_parent()
        if sw:
            adj = sw.get_vadjustment()
            if adj: adj.set_value(adj.get_upper() - adj.get_page_size())
