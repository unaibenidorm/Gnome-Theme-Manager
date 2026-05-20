"""Detail view for a selected theme."""
import gi, threading, os, tempfile, webbrowser, json
gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); gi.require_version('GdkPixbuf','2.0')
from gi.repository import Gtk, Adw, GLib, GdkPixbuf, Gdk
from pathlib import Path
from . import api, installer
from .widgets import InAppImageViewer

_CONFIG_DIR = Path.home() / ".config" / "gnome-theme-manager"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

def _load_detail_config():
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return {}

def _save_detail_config(cfg):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_CONFIG_FILE, "w") as f: json.dump(cfg, f)
    except Exception: pass

class ThemeDetailView(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=1, spacing=12)
        self.window = window; self.theme_data = None; self.cat_key = ""
        self.set_margin_start(20); self.set_margin_end(20)
        self.set_margin_top(12); self.set_margin_bottom(12)
        hdr = Gtk.Box(spacing=10)
        bb = Gtk.Button(icon_name="go-previous-symbolic", label="Back")
        bb.connect("clicked", lambda b: window.show_browse_view()); bb.add_css_class("flat")
        hdr.append(bb)
        self.title_lbl = Gtk.Label(label=""); self.title_lbl.add_css_class("title-2")
        hdr.append(self.title_lbl); self.append(hdr)
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.box = Gtk.Box(orientation=1, spacing=14); self.box.set_margin_bottom(20)
        sw.set_child(self.box); self.append(sw)

    def show_theme(self, data, cat_key):
        self.theme_data = data; self.cat_key = cat_key
        self.prev_theme = ""
        self.title_lbl.set_label(data.get("name",""))
        while c := self.box.get_first_child(): self.box.remove(c)

        # Main preview
        self.preview = Gtk.Picture(); self.preview.set_size_request(-1, 300)
        self.preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        
        self.preview_overlay = Gtk.Overlay()
        self.preview_overlay.set_child(self.preview)
        
        urls = api.get_preview_urls(data)
        self.urls = urls
        self.cur_img_idx = 0
        
        if len(urls) > 1:
            pb = Gtk.Button(icon_name="go-previous-symbolic", halign=Gtk.Align.START, valign=Gtk.Align.CENTER)
            pb.add_css_class("osd"); pb.add_css_class("circular"); pb.set_margin_start(10)
            pb.connect("clicked", lambda b: self._change_main_img(-1))
            self.preview_overlay.add_overlay(pb)
            
            nb = Gtk.Button(icon_name="go-next-symbolic", halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
            nb.add_css_class("osd"); nb.add_css_class("circular"); nb.set_margin_end(10)
            nb.connect("clicked", lambda b: self._change_main_img(1))
            self.preview_overlay.add_overlay(nb)
            
        pf = Gtk.Frame(); pf.set_child(self.preview_overlay); pf.add_css_class("theme-preview-frame")
        
        # Click to zoom (fullscreen overlay inside app)
        click = Gtk.GestureClick()
        click.connect("released", lambda *args: self.window.show_image_overlay(self.urls, self.cur_img_idx))
        pf.add_controller(click)
        self.box.append(pf)

        urls = api.get_preview_urls(data)
        if urls:
            threading.Thread(target=self._load_img, args=(urls[0],), daemon=True).start()

        # Gallery thumbnails
        if len(urls) > 1:
            gbox = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
            gbox.set_margin_top(4)
            for i, u in enumerate(urls):
                btn = Gtk.Button(); btn.add_css_class("flat"); btn.add_css_class("gallery-thumb")
                p = Gtk.Picture(); p.set_size_request(80, 56); p.set_content_fit(Gtk.ContentFit.COVER)
                btn.set_child(p)
                btn.connect("clicked", lambda b, idx=i: self._set_main_img_idx(idx))
                gbox.append(btn)
                threading.Thread(target=self._load_thumb, args=(u, p), daemon=True).start()
            self.box.append(gbox)

        # Info
        ig = Adw.PreferencesGroup(title="Information")
        
        # Check if installed
        is_installed = False
        loc = installer.get_installed_themes(cat_key, "local")
        sys = installer.get_installed_themes(cat_key, "system")
        # Ensure they are lists
        loc_list = loc if isinstance(loc, list) else []
        sys_list = sys if isinstance(sys, list) else []
        installed_list = loc_list + sys_list
        
        t_name = data.get("name", "").lower()
        t_id = data.get("id")
        # Use more strict matching to avoid false positives
        installed_names = [name for name, _ in installed_list]
        is_installed = installer.is_theme_installed(t_id, t_name, cat_key, installed_names)
        
        self.status_row = Adw.ActionRow(title="Status", subtitle="✅ Installed")
        if is_installed:
            ig.add(self.status_row)
        self.info_group = ig
        
        # Calculate and remember variants
        links = []
        for i in range(1, 20):
            l = data.get(f"downloadlink{i}")
            n = data.get(f"downloadname{i}")
            if l and n:
                if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    continue
                links.append((n, l))
        
        has_vars = len(links) > 1
        theme_id = str(data.get("id", ""))
        if theme_id:
            cfg = _load_detail_config()
            if "themes_with_variants" not in cfg:
                cfg["themes_with_variants"] = {}
            cfg["themes_with_variants"][theme_id] = has_vars
            _save_detail_config(cfg)
        
        for lbl, val in [("Author", data.get("personid","")), ("Version", data.get("version","")),
                         ("Downloads", data.get("downloads","0")), ("Rating", str(data.get("score","0"))),
                         ("Updated", str(data.get("changed",""))[:10])]:
            ig.add(Adw.ActionRow(title=lbl, subtitle=val))
        self.box.append(ig)

        # Description (HTML stripped)
        desc = api.strip_html(data.get("description",""))
        if desc:
            dg = Adw.PreferencesGroup(title="Description")
            dl = Gtk.Label(label=desc[:3000], wrap=True, xalign=0, selectable=True)
            dl.set_margin_start(12); dl.set_margin_end(12); dl.set_margin_top(6); dl.set_margin_bottom(6)
            r = Adw.ActionRow(); r.set_child(dl); dg.add(r)
            self.box.append(dg)

        # Shell theme warning
        if cat_key == "shell":
            inst, en, msg = installer.check_user_themes_extension()
            wg = Adw.PreferencesGroup(title="⚠ GNOME Shell Requirement")
            wl = Gtk.Label(label=msg, wrap=True, xalign=0, selectable=True)
            wl.set_margin_start(12); wl.set_margin_end(12); wl.set_margin_top(6); wl.set_margin_bottom(6)
            wr = Adw.ActionRow(); wr.set_child(wl); wg.add(wr); self.box.append(wg)

        # Install actions
        ag = Adw.PreferencesGroup(title="Install")
        cat_info = api.CATEGORIES.get(cat_key, {})

        has_vars = self._has_variants()

        if cat_info.get("system_only"):
            sr = Adw.ActionRow(title="Install system-wide (requires password)", subtitle="pkexec will be used automatically")
            
            label = "Install another variant" if (is_installed and has_vars) else ("Installed" if is_installed else "Install")
            self.install_btn_sys = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            
            if is_installed and not has_vars:
                self.install_btn_sys.set_sensitive(False)
            else:
                self.install_btn_sys.add_css_class("suggested-action")
                
            self.install_btn_sys.connect("clicked", lambda b: self._install("system"))
            sr.add_suffix(self.install_btn_sys); ag.add(sr)
        else:
            lr = Adw.ActionRow(title="Install for current user", subtitle=str(installer.get_theme_dir(cat_key,"local") or ""))
            
            label = "Install another variant" if (is_installed and has_vars) else ("Installed" if is_installed else "Install")
            self.install_btn_loc = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            
            if is_installed and not has_vars:
                self.install_btn_loc.set_sensitive(False)
            else:
                self.install_btn_loc.add_css_class("suggested-action")
                
            self.install_btn_loc.connect("clicked", lambda b: self._install("local"))
            lr.add_suffix(self.install_btn_loc); ag.add(lr)

        # Apply button for applicable types
        if cat_key in ("gtk","shell","icons","cursors","grub","plymouth"):
            self.apply_btn_row = Adw.ActionRow(title="Apply theme" if is_installed else "Apply theme after installing", subtitle="Change active theme like GNOME Tweaks")
            
            bbox = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
            
            self.undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
            self.undo_btn.set_tooltip_text("Restore previous theme")
            self.undo_btn.set_visible(False)
            self.undo_btn.connect("clicked", lambda b: self._undo_apply_btn_clicked())
            bbox.append(self.undo_btn)
            
            self.apply_btn = Gtk.Button(label="Apply" if is_installed else "Install and Apply")
            self.apply_btn.add_css_class("suggested-action")
            self.apply_btn.connect("clicked", self._on_apply_btn_clicked)
            
            # We don't show Apply for GDM as it's not supported in modern GNOME (>= 40)
            if cat_key != "gdm":
                bbox.append(self.apply_btn)
            
            self.apply_btn_row.add_suffix(bbox)
            ag.add(self.apply_btn_row)

        # Web link
        wr2 = Adw.ActionRow(title="View on gnome-look.org", subtitle="Open in browser")
        wb = Gtk.Image(icon_name="web-browser-symbolic")
        cid = data.get("id","")
        wr2.add_suffix(wb)
        wr2.set_activatable(True)
        wr2.connect("activated", lambda r: webbrowser.open(api.get_theme_web_url(cid)))
        ag.add(wr2)
        self.box.append(ag)

    def _load_img(self, url):
        d = api._make_request(url, timeout=20)
        if d: GLib.idle_add(self._set_preview, d)

    def _set_preview(self, d):
        try:
            lo = GdkPixbuf.PixbufLoader(); lo.write(d); lo.close()
            pb = lo.get_pixbuf()
            if pb: self.preview.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
        except Exception: pass

    def _load_thumb(self, url, pic):
        d = api._make_request(url, timeout=15)
        if d: GLib.idle_add(self._set_thumb, d, pic)

    def _set_thumb(self, d, pic):
        try:
            lo = GdkPixbuf.PixbufLoader(); lo.write(d); lo.close()
            pb = lo.get_pixbuf()
            if pb: pic.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
        except Exception: pass

    def _set_main_img_idx(self, idx):
        if self.urls and 0 <= idx < len(self.urls):
            self.cur_img_idx = idx
            threading.Thread(target=self._load_img, args=(self.urls[idx],), daemon=True).start()

    def _change_main_img(self, d):
        if self.urls:
            self._set_main_img_idx((self.cur_img_idx + d) % len(self.urls))

    def _install(self, scope):
        if not self.theme_data: return
        self._check_variants(scope, False)

    def _install_and_apply(self):
        if not self.theme_data: return
        self._check_variants("local", True)

    def _check_variants(self, scope, apply_after):
        links = []
        for i in range(1, 20):
            l = self.theme_data.get(f"downloadlink{i}")
            n = self.theme_data.get(f"downloadname{i}")
            if l and n:
                if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    continue
                links.append((n, l))
        
        if not links:
            self.window.show_toast("❌ No download links found")
            return
            
        if len(links) == 1:
            self._start_install(links[0][0], links[0][1], scope, apply_after)
        else:
            self._show_variants_dialog(links, scope, apply_after)

    def _show_variants_dialog(self, links, scope, apply_after):
        d = Adw.Dialog(title="Available variants")
        d.set_content_width(450); d.set_content_height(500)
        
        tb = Adw.ToolbarView()
        tb.add_top_bar(Adw.HeaderBar())
        
        box = Gtk.Box(orientation=1, spacing=10)
        box.set_margin_start(12); box.set_margin_end(12)
        box.set_margin_top(12); box.set_margin_bottom(12)
        
        ab = Gtk.Button(label="Install All Variants", valign=Gtk.Align.CENTER)
        ab.add_css_class("suggested-action")
        ab.connect("clicked", lambda b: self._install_all_variants(d, links, scope, apply_after))
        box.append(ab)
        
        sw = Gtk.ScrolledWindow(vexpand=True)
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        
        for name, link in links:
            row = Adw.ActionRow(title=name)
            btn = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda b, n=name, l=link: self._start_install_from_dialog(d, n, l, scope, apply_after))
            row.add_suffix(btn)
            listbox.append(row)
            
        sw.set_child(listbox)
        box.append(sw)
        tb.set_content(box)
        d.set_child(tb)
        d.present(self.window)

    def _start_install_from_dialog(self, dialog, name, link, scope, apply_after):
        dialog.close()
        self._start_install(name, link, scope, apply_after)

    def _install_all_variants(self, dialog, links, scope, apply_after):
        dialog.close()
        has_git = any(api._is_git_repo_url(link) for _, link in links)
        cfg = _load_detail_config()
        
        if cfg.get("hide_install_disclaimer", False) and not has_git:
            for name, link in links:
                is_git = api._is_git_repo_url(link)
                self._actual_install(name, link, scope, apply_after, is_git)
            return
            
        body_text = f"You are about to install all {len(links)} variants of this theme.\n\n"
        if has_git:
            body_text += "Some links point to code repositories (GitHub/GitLab). The program will try to download them automatically.\n\n"
        body_text += "Note: Some themes may require additional configuration steps (fonts, dependencies, manual tweaks) described in their description."
        
        md = Adw.MessageDialog(
            heading=f"Install All {len(links)} Variants?",
            body=body_text,
            transient_for=self.window
        )
        md.add_response("cancel", "Cancel")
        md.add_response("ok", "Install All")
        md.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        
        def _on_confirm(d, res):
            if res == "ok":
                for name, link in links:
                    is_git = api._is_git_repo_url(link)
                    self._actual_install(name, link, scope, apply_after, is_git)
        
        md.connect("response", _on_confirm)
        md.present()

    def _start_install(self, name, link, scope, apply_after):
        is_git = api._is_git_repo_url(link)
        
        if is_git:
            md = Adw.MessageDialog(heading="Code Repository", body=f"The link for '{name}' points to a code repository (GitHub/GitLab). The program will try to download and find themes automatically, but this might be experimental. Do you want to continue?")
            md.add_response("cancel", "Cancel")
            md.add_response("ok", "Continue")
            md.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
            def on_res(d, res):
                if res == "ok": self._show_install_disclaimer(name, link, scope, apply_after, is_git)
            md.connect("response", on_res)
            md.set_transient_for(self.window)
            md.present()
        else:
            self._show_install_disclaimer(name, link, scope, apply_after, is_git)

    def _show_install_disclaimer(self, name, link, scope, apply_after, is_git):
        """Show a disclaimer before installing, with option to never show again."""
        cfg = _load_detail_config()
        if cfg.get("hide_install_disclaimer", False):
            self._actual_install(name, link, scope, apply_after, is_git)
            return
        
        md = Adw.MessageDialog(
            heading="⚠ Before installing",
            body="Some themes may require additional configuration steps "
                 "(fonts, dependencies, manual tweaks, etc.) that are described "
                 "in the theme's description or on its web page.\n\n"
                 "Please review the description before applying.",
            transient_for=self.window
        )
        md.add_response("cancel", "Cancel")
        md.add_response("never", "Don't show again")
        md.add_response("ok", "Continue")
        md.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        def _on_disclaimer(d, res):
            if res == "never":
                cfg = _load_detail_config()
                cfg["hide_install_disclaimer"] = True
                _save_detail_config(cfg)
                self._actual_install(name, link, scope, apply_after, is_git)
            elif res == "ok":
                self._actual_install(name, link, scope, apply_after, is_git)
        md.connect("response", _on_disclaimer)
        md.present()

    def _ask_github_redirect(self, name, link, scope, apply_after):
        md = Adw.MessageDialog(heading="Code Repository", body=f"The link for '{name}' redirects to a code repository (GitHub/GitLab). The program will try to clone it to find themes automatically, but it might be experimental. Do you want to continue?")
        md.add_response("cancel", "Cancel")
        md.add_response("ok", "Continue")
        md.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        def on_res(d, res):
            if res == "ok": self._actual_install(name, link, scope, apply_after, True)
        md.connect("response", on_res)
        md.set_transient_for(self.window)
        md.present()

    def _actual_install(self, name, link, scope, apply_after, is_git):
        self.window.show_toast(f"Downloading {name}...")
        threading.Thread(target=self._do_install, args=(name, link, scope, apply_after, is_git), daemon=True).start()

    def _do_install(self, name, link, scope, apply_after, is_git):
        if is_git:
            # Strip /archive/ or /releases/ suffixes to get the actual repo URL
            clean_link = link.split("/archive/")[0] if "/archive/" in link else link
            clean_link = clean_link.split("/releases/download/")[0] if "/releases/download/" in clean_link else clean_link
            # Remove trailing .git if present
            if clean_link.endswith(".git"):
                clean_link = clean_link[:-4]
            # Ensure it ends with .git for cloning
            clone_url = clean_link if clean_link.endswith(".git") else clean_link + ".git"
            import subprocess
            try:
                safe_name = name.replace(" ", "_").replace("/", "_")
                clone_dir = Path(tempfile.mkdtemp()) / safe_name
                r = subprocess.run(["git", "clone", "--depth", "1", clone_url, str(clone_dir)], capture_output=True)
                if r.returncode != 0:
                    # Retry without .git suffix
                    r = subprocess.run(["git", "clone", "--depth", "1", clean_link, str(clone_dir)], capture_output=True)
                    if r.returncode != 0:
                        GLib.idle_add(self.window.show_toast, f"❌ Error cloning repository: {r.stderr.decode('utf-8', errors='ignore')}")
                        return
                ok = True
                tmp = str(clone_dir)
            except FileNotFoundError:
                GLib.idle_add(self.window.show_toast, "❌ Error: Install 'git' to clone themes.")
                return
        else:
            filename = link.split("/")[-1].split("?")[0]
            ext = "".join(Path(filename).suffixes)
            if not ext: ext = ".tar.gz"

            tmp = tempfile.mktemp(suffix=ext)
            ok = api.download_theme_file(link, tmp)
            
            if isinstance(ok, str) and ("github.com" in ok or "gitlab.com" in ok):
                # The download redirected to a git repo page — ask user if they want to clone
                GLib.idle_add(self._ask_github_redirect, name, ok, scope, apply_after)
                return

            if not ok:
                # Cleanup temp file on failure
                try: os.unlink(tmp)
                except OSError: pass
                GLib.idle_add(self.window.show_toast, "❌ Download error")
                return

        cat_info = api.CATEGORIES.get(self.cat_key, {})
        actual_scope = "system" if cat_info.get("system_only") else scope
        success, msg = installer.install_theme(tmp, self.cat_key, actual_scope)

        try:
            import shutil
            if Path(tmp).is_dir(): shutil.rmtree(tmp)
            else: os.unlink(tmp)
        except OSError: pass

        if success:
            names = msg.replace("Installed: ", "").split(", ")
            installed_name = names[0] if names else self.theme_data.get("name","")
            
            # Record in our 100% reliable local database memory
            theme_id = self.theme_data.get("id")
            if theme_id:
                cfg = _load_detail_config()
                if "installed_database" not in cfg:
                    cfg["installed_database"] = {}
                cfg["installed_database"][str(theme_id)] = {
                    "id": str(theme_id),
                    "name": self.theme_data.get("name", ""),
                    "category": self.cat_key,
                    "scope": actual_scope,
                    "folders": names
                }
                _save_detail_config(cfg)
                
            GLib.idle_add(self.window.show_toast, f"✅ {msg}")
            GLib.idle_add(self._mark_installed)
            if apply_after:
                GLib.idle_add(self._apply_theme, installed_name)
        else:
            GLib.idle_add(self.window.show_toast, f"❌ {msg}")

    def _mark_installed(self):
        # Add the installed row if it's not already there
        if not self.status_row.get_parent():
            self.info_group.add(self.status_row)
            
        has_vars = self._has_variants()
        
        if has_vars:
            if hasattr(self, "install_btn_sys"):
                self.install_btn_sys.set_label("Install another variant")
                self.install_btn_sys.set_sensitive(True)
                self.install_btn_sys.remove_css_class("suggested-action")
            if hasattr(self, "install_btn_loc"):
                self.install_btn_loc.set_label("Install another variant")
                self.install_btn_loc.set_sensitive(True)
                self.install_btn_loc.remove_css_class("suggested-action")
        else:
            if hasattr(self, "install_btn_sys"):
                self.install_btn_sys.set_label("Installed")
                self.install_btn_sys.set_sensitive(False)
                self.install_btn_sys.remove_css_class("suggested-action")
            if hasattr(self, "install_btn_loc"):
                self.install_btn_loc.set_label("Installed")
                self.install_btn_loc.set_sensitive(False)
                self.install_btn_loc.remove_css_class("suggested-action")
                
        if hasattr(self, "apply_btn_row"):
            self.apply_btn_row.set_title("Apply theme")
        if hasattr(self, "apply_btn"):
            self.apply_btn.set_label("Apply")
        
        # Hot-update the installed themes screen
        if hasattr(self.window, "_populate_installed") and getattr(self.window, "installed_dialog", None) is not None:
            search_query = self.window.search_entry.get_text().lower() if getattr(self.window, "search_entry", None) else ""
            self.window._populate_installed(search_query)

    def _has_variants(self):
        if not self.theme_data:
            return False
            
        # Check current theme_data links first
        links = []
        for i in range(1, 20):
            l = self.theme_data.get(f"downloadlink{i}")
            n = self.theme_data.get(f"downloadname{i}")
            if l and n:
                if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    continue
                links.append((n, l))
        if len(links) > 1:
            return True
            
        # Fallback to saved config memory
        theme_id = str(self.theme_data.get("id", ""))
        if theme_id:
            cfg = _load_detail_config()
            return cfg.get("themes_with_variants", {}).get(theme_id, False)
            
        return False

    def _on_apply_btn_clicked(self, btn):
        if btn.get_label() == "Apply":
            self._apply_theme(self.theme_data.get("name",""))
        else:
            self._install_and_apply()

    def _apply_theme(self, name):
        if self.cat_key == "grub":
            # Redirect if GRUB2 is blocked
            paths = installer.get_install_paths()
            grub_path = paths["grub"]["system"]
            try:
                list(grub_path.iterdir())
            except PermissionError:
                self.window.show_toast("🔒 GRUB directory is locked. Redirecting to Installed Themes...")
                self.window._show_installed()
                return
                
        if self.cat_key in ("grub", "plymouth"):
            self._apply_system_theme(name, self.cat_key)
            return

        variant_names = []
        base_name = name
        for sep in [' ', '-', '_']:
            if sep in name:
                parts = name.split(sep)
                if len(parts[0]) >= 3:
                    base_name = parts[0]
                    break
                    
        for scope in ["local", "system"]:
            all_themes = installer.get_installed_themes(self.cat_key, scope)
            for t_name, t_path in all_themes:
                if t_name == base_name or t_name.startswith(f"{base_name}-") or t_name.startswith(f"{base_name}_"):
                    variant_names.append(t_name)
                    
        variant_names = list(dict.fromkeys(variant_names))
        
        if len(variant_names) > 1:
            self._show_apply_variants_dialog(name, variant_names)
            return
            
        target_name = variant_names[0] if variant_names else name
        self._execute_user_apply(target_name)

    def _show_apply_variants_dialog(self, original_name, variant_names):
        d = Adw.Dialog(title="Select variant")
        d.set_content_width(450); d.set_content_height(400)
        tb = Adw.ToolbarView(); tb.add_top_bar(Adw.HeaderBar())
        sw = Gtk.ScrolledWindow(vexpand=True)
        lb = Gtk.ListBox(); lb.add_css_class("boxed-list"); lb.set_margin_start(12); lb.set_margin_end(12); lb.set_margin_top(12); lb.set_margin_bottom(12)
        
        for v_name in variant_names:
            r = Adw.ActionRow(title=v_name)
            b = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
            b.add_css_class("suggested-action")
            b.connect("clicked", lambda btn, dlg=d, target=v_name: self._execute_user_apply_from_dialog(dlg, target))
            r.add_suffix(b); lb.append(r)
            
        sw.set_child(lb); tb.set_content(sw); d.set_child(tb)
        d.present(self.window)

    def _execute_user_apply_from_dialog(self, dialog, target_name):
        dialog.close()
        self._execute_user_apply(target_name)

    def _execute_user_apply(self, name):
        if not self.prev_theme:
            if self.cat_key == "gtk": self.prev_theme = installer.get_current_gtk_theme()
            elif self.cat_key == "icons": self.prev_theme = installer.get_current_icon_theme()
            elif self.cat_key == "shell": self.prev_theme = installer.get_current_shell_theme()
            elif self.cat_key == "cursors": self.prev_theme = installer.get_current_cursor_theme()

        ok, msg = False, ""
        if self.cat_key == "gtk":
            ok, msg = installer.apply_gtk_theme(name)
        elif self.cat_key == "icons":
            ok, msg = installer.apply_icon_theme(name)
        elif self.cat_key == "shell":
            ok, msg = installer.apply_shell_theme(name)
        elif self.cat_key == "cursors":
            ok, msg = installer.apply_cursor_theme(name)
            
        if ok:
            toast = Adw.Toast(title=f"✅ Theme applied: {name}", timeout=2)
            self.window.toast.add_toast(toast)
            if hasattr(self, 'undo_btn') and self.prev_theme:
                self.undo_btn.set_visible(True)
        else:
            self.window.show_toast(f"⚠ Installed but could not be applied: {msg}")

    def _undo_apply_btn_clicked(self):
        if not self.prev_theme: return
        self._undo_apply(self.prev_theme)

    def _undo_apply(self, prev_name):
        ok, msg = False, ""
        if self.cat_key == "gtk": ok, msg = installer.apply_gtk_theme(prev_name)
        elif self.cat_key == "icons": ok, msg = installer.apply_icon_theme(prev_name)
        elif self.cat_key == "shell": ok, msg = installer.apply_shell_theme(prev_name)
        elif self.cat_key == "cursors": ok, msg = installer.apply_cursor_theme(prev_name)
        if ok:
            self.window.show_toast(f"↩ Restored to: {prev_name}")
            if hasattr(self, 'undo_btn'): self.undo_btn.set_visible(False)
            self.prev_theme = ""

    def _apply_system_theme(self, name, cat_key):
        from .widgets import CommandDialog
        variants = []
        if cat_key == "grub":
            variants = installer.get_grub_variants(name)
        elif cat_key == "plymouth":
            variants = installer.get_plymouth_variants(name)
            
        if not variants:
            # Fallback to lower case name
            if cat_key == "grub": variants = installer.get_grub_variants(name.lower())
            elif cat_key == "plymouth": variants = installer.get_plymouth_variants(name.lower())
            
            # Second fallback: strip common suffixes like "-grub", "-theme", etc.
            if not variants:
                short_name = name.lower()
                for suffix in ["-grub", "_grub", " grub", "-theme", "_theme", " theme"]:
                    if suffix in short_name:
                        short_name = short_name.split(suffix)[0].strip()
                        if cat_key == "grub": variants = installer.get_grub_variants(short_name)
                        elif cat_key == "plymouth": variants = installer.get_plymouth_variants(short_name)
                        if variants: break

            if not variants:
                self.window.show_toast(f"❌ Error: Theme file not found for {name}")
                return

        if len(variants) == 1:
            self._execute_system_apply(cat_key, variants[0])
        else:
            d = Adw.Dialog(title="Select variant")
            d.set_content_width(450); d.set_content_height(400)
            tb = Adw.ToolbarView(); tb.add_top_bar(Adw.HeaderBar())
            sw = Gtk.ScrolledWindow(vexpand=True)
            lb = Gtk.ListBox(); lb.add_css_class("boxed-list"); lb.set_margin_start(12); lb.set_margin_end(12); lb.set_margin_top(12); lb.set_margin_bottom(12)
            for v in variants:
                if cat_key == "grub":
                    # For GRUB: show resolution variant name from filename
                    # e.g. theme_1080p.txt -> "1080p", theme.txt -> parent folder name
                    stem = v.stem  # "theme_1080p" or "theme"
                    if stem == "theme":
                        display = v.parent.name
                    else:
                        # Strip leading "theme" prefix and separators
                        label = stem
                        for prefix in ["theme_", "theme-", "theme "]:
                            if label.lower().startswith(prefix):
                                label = label[len(prefix):]
                                break
                        display = f"{v.parent.name} — {label}"
                else:
                    display = v.name
                r = Adw.ActionRow(title=display, subtitle=str(v))
                b = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
                b.add_css_class("suggested-action")
                b.connect("clicked", lambda btn, dlg=d, ck=cat_key, var=v: self._execute_system_apply_from_dialog(dlg, ck, var))
                r.add_suffix(b); lb.append(r)
            sw.set_child(lb); tb.set_content(sw); d.set_child(tb)
            d.present(self.window)

    def _execute_system_apply_from_dialog(self, dialog, cat_key, variant_path):
        dialog.close()
        self._execute_system_apply(cat_key, variant_path)

    def _execute_system_apply(self, cat_key, variant_path):
        from .widgets import CommandDialog
        
        if cat_key == "grub":
            # Check gfxterm before applying
            is_gfx, current = installer.check_grub_gfxterm()
            if not is_gfx:
                md = Adw.MessageDialog(
                    heading="GRUB Terminal Not in gfxterm",
                    body=f"GRUB is currently set to '{current}'.\n\n"
                         "GRUB themes require 'gfxterm' to render properly. "
                         "If you continue, the installer will automatically switch GRUB_TERMINAL_OUTPUT to 'gfxterm'.\n\n"
                         "Do you want to continue?",
                    transient_for=self.window
                )
                md.add_response("cancel", "Cancel")
                md.add_response("ok", "Continue and fix")
                md.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
                def _on_gfx_response(d, res):
                    if res == "ok":
                        self._run_system_apply_script(cat_key, variant_path)
                md.connect("response", _on_gfx_response)
                md.present()
                return
            
            script = installer.get_grub_post_install_script(str(variant_path))
        else: 
            script = installer.get_plymouth_post_install_script(str(variant_path))
        
        dlg = CommandDialog(title=f"Applying {cat_key.upper()} theme", script_content=script)
        dlg.present(self.window)

    def _run_system_apply_script(self, cat_key, variant_path):
        from .widgets import CommandDialog
        if cat_key == "grub":
            script = installer.get_grub_post_install_script(str(variant_path))
        else:
            script = installer.get_plymouth_post_install_script(str(variant_path))
        dlg = CommandDialog(title=f"Applying {cat_key.upper()} theme", script_content=script)
        dlg.present(self.window)

