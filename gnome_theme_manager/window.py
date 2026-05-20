"""Main Window for Gnome Theme Manager."""
import gi, threading, webbrowser, json
gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk
from pathlib import Path
from . import api, installer, __version__, __app_name__, __github_url__, __website_url__, __authors__
from .widgets import ThemeCard
from .detail import ThemeDetailView

PAGESIZE = 20
CONFIG_DIR = Path.home() / ".config" / "gnome-theme-manager"
CONFIG_FILE = CONFIG_DIR / "config.json"

def _load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return {}

def _save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(cfg, f)
    except Exception: pass

class GnomeThemeManagerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Gnome Theme Manager", default_width=1100, default_height=750)
        self.cur_cat = "gtk"; self.cur_page = 0; self.cur_sort = "new"
        self.cur_search = ""; self.total = 0; self.loading = False
        self.show_installed_only = False
        
        # Load theme preference
        cfg = _load_config()
        self.is_dark = cfg.get("dark_mode", True)
        self.show_grub_warning = cfg.get("show_grub_warning", True)
        self.low_performance = cfg.get("low_performance", False)
        self.list_view = cfg.get("list_view", False)
        style_mgr = Adw.StyleManager.get_default()
        style_mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK if self.is_dark else Adw.ColorScheme.FORCE_LIGHT)

        self._setup_icons()
        self._build_ui(); self._load_css(); self._load_themes()
        
        # Check first run welcome tutorial
        if cfg.get("first_run", True):
            GLib.idle_add(self._show_welcome_tutorial)
        
        # Check for GRUB2 permissions at startup
        elif self.show_grub_warning:
            GLib.idle_add(self._check_startup_permissions)

    def _check_startup_permissions(self):
        paths = installer.get_install_paths()
        grub_path = paths["grub"]["system"]
        try:
            list(grub_path.iterdir())
        except PermissionError:
            self._show_permission_warning("GRUB")
        except Exception: pass

    def _show_permission_warning(self, type_name):
        d = Adw.MessageDialog(
            heading="Restricted Permissions Detected",
            body=f"The system directory for {type_name} themes is restricted.\n\n"
                 "To see your installed themes in this category, you will need to "
                 "unlock them with your password in the 'Installed Themes' menu.\n"
                 "Installation will still work normally.",
            transient_for=self
        )
        d.add_response("ok", "Got it")
        d.add_response("never", "Don't show again")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        
        def _on_response(diag, res):
            if res == "never":
                cfg = _load_config()
                cfg["show_grub_warning"] = False
                _save_config(cfg)
        
        d.connect("response", _on_response)
        d.present()

    def _setup_icons(self):
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_path = Path(__file__).parent
        icon_theme.add_search_path(str(icon_path))

    def _load_css(self):
        css = Gtk.CssProvider()
        p = Path(__file__).parent / "style.css"
        if p.exists():
            css.load_from_path(str(p))
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build_ui(self):
        self.split = Adw.OverlaySplitView()
        self.split.set_show_sidebar(True)
        self.split.set_min_sidebar_width(260)
        self.split.set_max_sidebar_width(320)

        # Sidebar
        sb = Gtk.Box(orientation=1)
        
        # Sidebar title
        sh = Adw.HeaderBar()
        tl = Gtk.Label(label="Gnome Theme Manager"); tl.add_css_class("sidebar-title")
        sh.set_title_widget(tl); sb.append(sh)
        
        self.cat_list = Gtk.ListBox(); self.cat_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.cat_list.add_css_class("navigation-sidebar")
        self.cat_list.connect("row-selected", self._on_cat)
        for key, cat in api.CATEGORIES.items():
            row = Adw.ActionRow(title=cat["title"], subtitle=f"{cat['count']} themes")
            row.set_icon_name(cat["icon"]); row._cat_key = key
            if cat.get("system_only"): row.add_suffix(Gtk.Image(icon_name="system-lock-screen-symbolic"))
            self.cat_list.append(row)
        
        cs = Gtk.ScrolledWindow(vexpand=True); cs.set_child(self.cat_list); sb.append(cs)

        # Bottom sidebar buttons
        bb = Gtk.Box(orientation=1, spacing=6)
        bb.set_margin_start(8); bb.set_margin_end(8); bb.set_margin_bottom(8); bb.set_margin_top(4)

        ib = Gtk.Button(label="📦 Installed Themes"); ib.connect("clicked", self._show_installed)
        bb.append(ib)
        pb = Gtk.Button(label="⚙ Preferences"); pb.connect("clicked", self._show_prefs)
        bb.append(pb)
        ab = Gtk.Button(label="About"); ab.connect("clicked", self._show_about)
        bb.append(ab)
        sb.append(bb)

        # Content
        cb = Gtk.Box(orientation=1)
        self._build_header(cb)

        self.stack = Gtk.Stack(); self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        # Browse view
        bv = Gtk.Box(orientation=1)
        self.status = Gtk.Label(label="Loading...", xalign=0)
        self.status.set_margin_start(16); self.status.set_margin_top(8); self.status.add_css_class("dim-label")
        bv.append(self.status)

        sw = Gtk.ScrolledWindow(vexpand=True)
        self.flow = Gtk.FlowBox(); self.flow.set_valign(Gtk.Align.START)
        if self.list_view:
            self.flow.set_max_children_per_line(1); self.flow.set_min_children_per_line(1)
            self.flow.set_homogeneous(False)
        else:
            self.flow.set_max_children_per_line(10); self.flow.set_min_children_per_line(2)
            self.flow.set_homogeneous(True)
        self.flow.set_column_spacing(10); self.flow.set_row_spacing(10)
        self.flow.set_margin_start(14); self.flow.set_margin_end(14)
        self.flow.set_margin_top(10); self.flow.set_margin_bottom(10)
        self.flow.connect("child-activated", self._on_theme)
        sw.set_child(self.flow); bv.append(sw)

        pg = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        pg.set_margin_bottom(10); pg.set_margin_top(6)
        self.prev = Gtk.Button(icon_name="go-previous-symbolic"); self.prev.connect("clicked", lambda b: self._page(-1))
        pg.append(self.prev)
        self.pg_lbl = Gtk.Label(label="1/1"); pg.append(self.pg_lbl)
        self.nxt = Gtk.Button(icon_name="go-next-symbolic"); self.nxt.connect("clicked", lambda b: self._page(1))
        pg.append(self.nxt); bv.append(pg)
        self.stack.add_named(bv, "browse")

        self.detail = ThemeDetailView(self)
        self.stack.add_named(self.detail, "detail")
        cb.append(self.stack)

        self.toast = Adw.ToastOverlay(); self.toast.set_child(cb)
        self.split.set_sidebar(sb)
        self.split.set_content(self.toast)
        
        self.main_overlay = Gtk.Overlay()
        self.main_overlay.set_child(self.split)
        self.set_content(self.main_overlay)
        
        key = Gtk.EventControllerKey.new()
        key.connect("key-released", self._on_key)
        self.add_controller(key)
        
        f = self.cat_list.get_row_at_index(0)
        if f:
            self.cat_list.select_row(f)
            self._on_cat(None, f)

    def _on_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if hasattr(self, 'image_viewer') and self.image_viewer is not None:
                self.hide_image_overlay()
                return True
            elif self.stack.get_visible_child_name() == "detail":
                self.show_browse_view()
                return True
        return False

    def _build_header(self, cb):
        ch = Adw.HeaderBar()
        
        # Sidebar manual toggle
        self.toggle_sidebar_btn = Gtk.Button()
        # Find a valid icon name supported by the active icon theme
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        chosen_icon = "sidebar-show-symbolic"
        for name in ["sidebar-show-symbolic", "view-sidebar-left-symbolic", "view-sidebar-symbolic", "open-menu-symbolic"]:
            if icon_theme.has_icon(name):
                chosen_icon = name
                break
        self.toggle_sidebar_btn.set_icon_name(chosen_icon)
        self.toggle_sidebar_btn.set_tooltip_text("Toggle Sidebar")
        self.toggle_sidebar_btn.connect("clicked", lambda b: self._toggle_sidebar())
        ch.pack_start(self.toggle_sidebar_btn)

        self.search = Gtk.SearchEntry(placeholder_text="Search themes...")
        self.search.set_hexpand(True)
        self.search.connect("activate", self._on_search)
        self.search.connect("search-changed", self._on_search_changed)
        ch.set_title_widget(self.search)
        
        pop = Gtk.Popover()
        popbox = Gtk.Box(orientation=1, spacing=10)
        popbox.set_margin_start(12); popbox.set_margin_end(12); popbox.set_margin_top(12); popbox.set_margin_bottom(12)
        
        # Use a ListBox to host ActionRows (required by Adw.ActionRow)
        filter_lb = Gtk.ListBox()
        filter_lb.set_selection_mode(Gtk.SelectionMode.NONE)
        filter_lb.add_css_class("boxed-list")
        
        # Filter toggle
        fr = Adw.ActionRow(title="Installed only")
        self.installed_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.installed_switch.set_active(self.show_installed_only)
        self.installed_switch.connect("notify::active", self._on_filter_installed)
        fr.add_suffix(self.installed_switch)
        fr.set_activatable_widget(self.installed_switch)
        filter_lb.append(fr)
        
        # Sort DropDown
        sr = Adw.ActionRow(title="Sort by")
        sm = Gtk.StringList.new(["Newest","Rating","Downloads","A-Z"])
        self.sort_dd = Gtk.DropDown(model=sm, valign=Gtk.Align.CENTER)
        self.sort_dd.connect("notify::selected", self._on_sort)
        sr.add_suffix(self.sort_dd)
        filter_lb.append(sr)
        
        popbox.append(filter_lb)
        pop.set_child(popbox)
        filter_btn = Gtk.MenuButton(icon_name="view-more-symbolic", popover=pop)
        ch.pack_end(filter_btn)
        
        # View Toggle Button (List vs Grid)
        self.view_toggle_btn = Gtk.Button()
        self.view_toggle_btn.set_icon_name("view-list-symbolic" if not self.list_view else "view-grid-symbolic")
        self.view_toggle_btn.set_tooltip_text("Switch to List View" if not self.list_view else "Switch to Grid View")
        self.view_toggle_btn.connect("clicked", self._on_toggle_view)
        ch.pack_end(self.view_toggle_btn)
        
        reload_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        reload_btn.connect("clicked", lambda b: self._load_themes())
        ch.pack_end(reload_btn)
        cb.append(ch)

    def _toggle_sidebar(self):
        show = not self.split.get_show_sidebar()
        self.split.set_show_sidebar(show)

    def _on_toggle_view(self, btn):
        self.list_view = not self.list_view
        self.view_toggle_btn.set_icon_name("view-list-symbolic" if not self.list_view else "view-grid-symbolic")
        self.view_toggle_btn.set_tooltip_text("Switch to List View" if not self.list_view else "Switch to Grid View")
        
        cfg = _load_config()
        cfg["list_view"] = self.list_view
        _save_config(cfg)
        
        if self.list_view:
            self.flow.set_max_children_per_line(1)
            self.flow.set_min_children_per_line(1)
            self.flow.set_homogeneous(False)
        else:
            self.flow.set_max_children_per_line(10)
            self.flow.set_min_children_per_line(2)
            self.flow.set_homogeneous(True)
            
        self.loading = False
        self._load_themes()

    def show_image_overlay(self, urls, start_idx):
        from .widgets import InAppImageViewer
        self.image_viewer = InAppImageViewer(urls, start_idx, self.hide_image_overlay)
        self.main_overlay.add_overlay(self.image_viewer)
        
    def hide_image_overlay(self):
        if hasattr(self, 'image_viewer') and self.image_viewer is not None:
            self.main_overlay.remove_overlay(self.image_viewer)
            self.image_viewer = None


    def _on_filter_installed(self, sw, param):
        self.show_installed_only = sw.get_active()
        # Reload themes — the _update method will re-check installed status
        self._load_themes()

    def _on_cat(self, lb, row):
        if row and hasattr(row,'_cat_key'):
            self.cur_cat = row._cat_key; self.cur_page = 0
            self.search.set_text("")
            self.cur_search = ""
            self.show_browse_view(); self._load_themes()

    def _on_search(self, e):
        self.cur_search = e.get_text().strip(); self.cur_page = 0; self._load_themes()
        
    def _on_search_changed(self, e):
        self.cur_search = e.get_text().strip()

    def _on_sort(self, dd, _):
        sk = ["new","score","down","alpha"]; i = dd.get_selected()
        if 0 <= i < len(sk): self.cur_sort = sk[i]; self.cur_page = 0; self._load_themes()

    def _on_theme(self, fb, child):
        if hasattr(child, 'data') and hasattr(child, 'category_key'):
            self.detail.show_theme(child.data, child.category_key)
            self.stack.set_visible_child_name("detail")

    def show_browse_view(self): self.stack.set_visible_child_name("browse")

    def _page(self, d):
        mx = max(0,(self.total-1)//PAGESIZE) if self.total>0 else 0
        np = self.cur_page+d
        if 0<=np<=mx: self.cur_page=np; self._load_themes()

    def _load_themes(self):
        if self.loading: return
        self.loading = True; self.status.set_label("Loading themes...")
        cid = api.CATEGORIES[self.cur_cat]["id"]
        threading.Thread(target=self._fetch, args=(cid,self.cur_page,self.cur_sort,self.cur_search,self.cur_cat), daemon=True).start()

    def _fetch(self, cid, pg, so, se, ck):
        if self.show_installed_only:
            all_items = []
            
            # Fetch first 8 pages of 100 items each in parallel for a total of 800 items!
            def fetch_page(p, results_list, idx):
                try:
                    items, tot = api.fetch_content_list(cid, p, 100, so, se)
                    results_list[idx] = items
                except Exception as ex:
                    print(f"Error fetching page {p}: {ex}")
                    results_list[idx] = []

            threads = []
            results = [None] * 8
            for i in range(8):
                t = threading.Thread(target=fetch_page, args=(i, results, i), daemon=True)
                t.start()
                threads.append(t)
                
            for t in threads:
                t.join()
                
            for res in results:
                if res:
                    all_items.extend(res)
            
            # Add items from local installed_database config
            cfg = installer._load_installer_config()
            db = cfg.get("installed_database", {})
            for t_id, entry in db.items():
                if entry.get("category") == ck:
                    if "data" in entry:
                        all_items.append(entry["data"])
            
            # Deduplicate items by ID
            seen = set()
            dedup_items = []
            for it in all_items:
                it_id = it.get("id")
                if it_id not in seen:
                    seen.add(it_id)
                    dedup_items.append(it)
                    
            GLib.idle_add(self._update, dedup_items, len(dedup_items), ck)
        else:
            items, total = api.fetch_content_list(cid, pg, PAGESIZE, so, se)
            GLib.idle_add(self._update, items, total, ck)

    def _update(self, items, total, ck):
        while c := self.flow.get_first_child(): self.flow.remove(c)
        self.total = total; mx = max(0,(total-1)//PAGESIZE) if total>0 else 0
        if not items:
            self.status.set_label("No themes found.")
        else:
            ct = api.CATEGORIES.get(ck,{}).get("title","")
            self.status.set_label(f"{ct} — {total} themes")
            
            # Pre-calculate installed themes
            sys = installer.get_installed_themes(ck, "system")
            loc = installer.get_installed_themes(ck, "local")
            installed_sys = [t[0].lower() for t in sys] if isinstance(sys, list) else []
            installed_loc = [t[0].lower() for t in loc] if isinstance(loc, list) else []
            all_installed = set(installed_sys + installed_loc)
            
            for it in items:
                t_name = it.get("name", "").lower()
                t_id = it.get("id")
                is_inst = installer.is_theme_installed(t_id, t_name, ck, all_installed)
                card = ThemeCard(it, ck, is_inst, low_perf=self.low_performance, list_view=self.list_view)
                if self.show_installed_only and not is_inst:
                    continue
                self.flow.append(card)
        
        if self.show_installed_only:
            n_visible = 0
            c = self.flow.get_first_child()
            while c:
                n_visible += 1
                c = c.get_next_sibling()
            ct = api.CATEGORIES.get(ck,{}).get("title","")
            self.status.set_label(f"{ct} — {n_visible} installed (page {self.cur_page+1}/{mx+1})")
                
        self.pg_lbl.set_label(f"{self.cur_page+1} / {mx+1}")
        self.prev.set_sensitive(self.cur_page>0); self.nxt.set_sensitive(self.cur_page<mx)
        self.loading = False

    def show_toast(self, msg):
        self.toast.add_toast(Adw.Toast(title=msg, timeout=2))

    def _show_installed(self, btn=None):
        if hasattr(self, 'installed_dialog') and self.installed_dialog is not None:
            if self.installed_dialog.get_realized() and self.installed_dialog.get_visible():
                try: self.installed_dialog.close()
                except: pass
            
        self.installed_dialog = Adw.Dialog(); self.installed_dialog.set_title("Installed Themes")
        self.installed_dialog.set_content_width(500); self.installed_dialog.set_content_height(550)
        self.installed_dialog.connect("closed", lambda d: setattr(self, 'installed_dialog', None))
        
        self.installed_toast = Adw.ToastOverlay()
        
        tb = Adw.ToolbarView()
        hdr = Adw.HeaderBar(); tb.add_top_bar(hdr)
        
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search in installed...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", lambda e: self._populate_installed(e.get_text().lower()))
        hdr.set_title_widget(self.search_entry)
        
        self.installed_sw = Gtk.ScrolledWindow(vexpand=True)
        tb.set_content(self.installed_sw)
        
        self.installed_toast.set_child(tb)
        self.installed_dialog.set_child(self.installed_toast)
            
        self._populate_installed("")
        self.installed_dialog.present(self)

    def _populate_installed(self, query):
        vb = Gtk.Box(orientation=1, spacing=10)
        vb.set_margin_start(12); vb.set_margin_end(12); vb.set_margin_top(8); vb.set_margin_bottom(8)

        active_gtk = installer.get_current_gtk_theme()
        active_icons = installer.get_current_icon_theme()
        active_shell = installer.get_current_shell_theme()
        active_cursors = installer.get_current_cursor_theme()
        active_grub = installer.get_active_grub_theme()
        active_plymouth = installer.get_active_plymouth_theme()

        # Collect old expanded states and scroll position
        old_expanded = {}
        old_vadjustment = 0.0
        if getattr(self, 'installed_sw', None):
            adj = self.installed_sw.get_vadjustment()
            if adj:
                old_vadjustment = adj.get_value()
                
            def _find_groups(w, current_scope=None):
                if isinstance(w, Adw.PreferencesGroup):
                    current_scope = w.get_title()
                elif isinstance(w, Adw.ExpanderRow):
                    if current_scope:
                        old_expanded[f"{current_scope}_{w.get_title()}"] = w.get_expanded()
                
                c = w.get_first_child()
                while c:
                    _find_groups(c, current_scope)
                    c = c.get_next_sibling()
            _find_groups(self.installed_sw)

        vb = Gtk.Box(orientation=1, spacing=10)
        vb.set_margin_start(12); vb.set_margin_end(12)
        vb.set_margin_top(12); vb.set_margin_bottom(12)
        
        for scope in ["local", "system"]:
            grp = Adw.PreferencesGroup(title="User Themes" if scope == "local" else "System Themes")
            has_items = False
            
            for key, cat in api.CATEGORIES.items():
                if scope == "local" and cat.get("system_only"):
                    continue
                themes = installer.get_installed_themes(key, scope)
                
                if themes == "PERMISSION_DENIED" and scope == "system":
                    # For restricted system folders like /boot/grub2
                    exp = Adw.ExpanderRow(title=cat['title'], subtitle="🔒 Locked (Click to unlock)")
                    exp.add_css_class("warning")
                    
                    row = Adw.ActionRow(title="Permission Denied", subtitle="Admin privileges required to list these themes")
                    btn = Gtk.Button(label="Unlock with Password", valign=Gtk.Align.CENTER)
                    btn.add_css_class("suggested-action")
                    
                    def _unlock(b, k=key, e=exp, s=scope):
                        s_themes = installer.get_installed_themes_secure(k)
                        if s_themes:
                            # Re-populate the whole view with the new data
                            self._populate_installed(query)
                        else:
                            self.show_toast("Failed to unlock or no themes found.")
                            
                    btn.connect("clicked", _unlock)
                    row.add_suffix(btn)
                    exp.add_row(row)
                    grp.add(exp)
                    has_items = True
                    continue

                if query:
                    # Flat view for search
                    for name, path in themes:
                        is_active = False
                        sub = str(path)
                        
                        if key == "gtk" and name == active_gtk: is_active = True
                        if key == "icons" and name == active_icons: is_active = True
                        if key == "shell" and name == active_shell: is_active = True
                        if key == "cursors" and name == active_cursors: is_active = True
                        if key == "grub" and active_grub and str(path) in active_grub:
                            is_active = True
                            var_name = Path(active_grub).parent.name
                            if var_name != name: sub = f"Variant: {var_name}"
                        if key == "plymouth" and active_plymouth and str(path) in active_plymouth:
                            is_active = True
                            var_name = Path(active_plymouth).name.replace(".plymouth", "")
                            if var_name != name: sub = f"Variant: {var_name}"
                        elif key == "plymouth" and name == active_plymouth: is_active = True

                        q = query.lower()
                        if q not in name.lower() and q not in str(path).lower():
                            if not (is_active and q in ["applied", "apply", "aplicado", "aplicar", "activated", "activado"]):
                                continue
                        
                        if key == "gtk" and name == active_gtk: is_active = True
                        if key == "icons" and name == active_icons: is_active = True
                        if key == "shell" and name == active_shell: is_active = True
                        if key == "grub" and active_grub and str(path) in active_grub:
                            is_active = True
                            var_name = Path(active_grub).parent.name
                            if var_name != name: sub = f"Variant: {var_name}"
                        if key == "plymouth" and name == active_plymouth: is_active = True

                        if is_active: sub = f"✅ Applied - {sub}"
                        sub += f" ({cat['title']})"
                        
                        r = Adw.ActionRow(title=name, subtitle=sub)
                        r.add_css_class("installed-row")
                        if is_active: r.add_css_class("success")

                        if key in ("gtk", "icons", "shell", "cursors", "grub", "plymouth"):
                            ab2 = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
                            ab2.add_css_class("flat")
                            ab2.connect("clicked", lambda b, n=name, k=key: self._apply_installed(n, k))
                            r.add_suffix(ab2)
                            
                        ub = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                        ub.add_css_class("flat"); ub.add_css_class("error")
                        ub.connect("clicked", lambda b, n=name, k=key, s=scope: self._uninstall(n, k, s))
                        r.add_suffix(ub)
                        grp.add(r)
                        has_items = True
                else:
                    # ExpanderRow view
                    tdir = installer.get_theme_dir(key, scope)
                    exp = Adw.ExpanderRow(title=cat['title'], subtitle=f"{len(themes)} installed")
                    scope_title = "User Themes" if scope == "local" else "System Themes"
                    exp_key = f"{scope_title}_{cat['title']}"
                    if exp_key in old_expanded:
                        exp.set_expanded(old_expanded[exp_key])
                    has_exp_items = False
                    
                    try:
                        exists = tdir and tdir.exists()
                    except PermissionError:
                        exists = False
                    
                    if exists:
                        ob = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
                        ob.add_css_class("flat"); ob.set_tooltip_text(str(tdir))
                        ob.connect("clicked", lambda b, p=str(tdir): installer.open_directory(p))
                        exp.add_prefix(ob)

                    if themes:
                        for name, path in themes:
                            is_active = False
                            sub = str(path)
                            
                            if key == "gtk" and name == active_gtk: is_active = True
                            if key == "icons" and name == active_icons: is_active = True
                            if key == "shell" and name == active_shell: is_active = True
                            if key == "cursors" and name == active_cursors: is_active = True
                            if key == "grub" and active_grub and str(path) in active_grub:
                                is_active = True
                                var_name = Path(active_grub).parent.name
                                if var_name != name: sub = f"Variant: {var_name}"
                            if key == "plymouth" and active_plymouth and str(path) in active_plymouth:
                                is_active = True
                                var_name = Path(active_plymouth).name.replace(".plymouth", "")
                                if var_name != name: sub = f"Variant: {var_name}"
                            elif key == "plymouth" and name == active_plymouth: is_active = True

                            if is_active: sub = f"✅ Applied - {sub}"
                            
                            r = Adw.ActionRow(title=name, subtitle=sub)
                            r.add_css_class("installed-row")
                            if is_active: r.add_css_class("success")

                            if key in ("gtk", "icons", "shell", "cursors", "grub", "plymouth"):
                                ab2 = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
                                ab2.add_css_class("flat")
                                ab2.connect("clicked", lambda b, n=name, k=key: self._apply_installed(n, k))
                                r.add_suffix(ab2)
                                
                            ub = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
                            ub.add_css_class("flat"); ub.add_css_class("error")
                            ub.connect("clicked", lambda b, n=name, k=key, s=scope: self._uninstall(n, k, s))
                            r.add_suffix(ub)
                            exp.add_row(r)
                            has_exp_items = True
                    else:
                        exp.add_row(Adw.ActionRow(title="(empty)"))
                        has_exp_items = True
                    
                    if has_exp_items:
                        grp.add(exp)
                        has_items = True

            if has_items:
                vb.append(grp)

        self.installed_sw.set_child(vb)
        
        # Restore scroll position after geometry allocation
        if old_vadjustment > 0:
            def _restore_scroll():
                adj = self.installed_sw.get_vadjustment()
                if adj:
                    adj.set_value(min(old_vadjustment, adj.get_upper() - adj.get_page_size()))
                return False
            GLib.idle_add(_restore_scroll)

    def _apply_installed(self, name, cat_key):
        if cat_key in ("grub", "plymouth"):
            self.detail._apply_system_theme(name, cat_key)
            return

        prev_theme = ""
        if cat_key == "gtk": prev_theme = installer.get_current_gtk_theme()
        elif cat_key == "icons": prev_theme = installer.get_current_icon_theme()
        elif cat_key == "shell": prev_theme = installer.get_current_shell_theme()
        elif cat_key == "cursors": prev_theme = installer.get_current_cursor_theme()

        ok, msg = False, ""
        if cat_key == "gtk": ok, msg = installer.apply_gtk_theme(name)
        elif cat_key == "icons": ok, msg = installer.apply_icon_theme(name)
        elif cat_key == "shell": ok, msg = installer.apply_shell_theme(name)
        elif cat_key == "cursors": ok, msg = installer.apply_cursor_theme(name)
        
        if ok:
            toast = Adw.Toast(title=f"✅ Theme applied: {name}", timeout=2)
            if prev_theme:
                toast.set_button_label("Undo")
                toast.connect("button-clicked", lambda t: self._undo_apply_installed(prev_theme, cat_key))
            if hasattr(self, 'installed_toast'): self.installed_toast.add_toast(toast)
            GLib.idle_add(self._populate_installed, self.search_entry.get_text().lower())
        else: self.show_toast(f"❌ Error applying theme: {msg}")

    def _undo_apply_installed(self, prev_name, cat_key):
        ok = False
        if cat_key == "gtk": ok, _ = installer.apply_gtk_theme(prev_name)
        elif cat_key == "icons": ok, _ = installer.apply_icon_theme(prev_name)
        elif cat_key == "shell": ok, _ = installer.apply_shell_theme(prev_name)
        elif cat_key == "cursors": ok, _ = installer.apply_cursor_theme(prev_name)
        if ok:
            self.show_toast(f"↩ Restored to: {prev_name}")
            GLib.idle_add(self._populate_installed, "")

    def _uninstall(self, name, cat_key, scope):
        variant_dirs = []
        if cat_key == "grub":
            variant_dirs = [v.parent for v in installer.get_grub_variants(name)]
        elif cat_key == "plymouth":
            variant_dirs = [v.parent for v in installer.get_plymouth_variants(name)]
        else:
            base_name = name
            for sep in ['-', '_']:
                if sep in name:
                    parts = name.split(sep)
                    if len(parts[0]) >= 3:
                        base_name = parts[0]
                        break
            
            all_themes = installer.get_installed_themes(cat_key, scope)
            for t_name, t_path in all_themes:
                if t_name == base_name or t_name.startswith(f"{base_name}-") or t_name.startswith(f"{base_name}_"):
                    variant_dirs.append(Path(t_path))
                    
        variant_dirs = list(dict.fromkeys(variant_dirs))
        
        if len(variant_dirs) > 1 or (cat_key in ("grub", "plymouth") and len(variant_dirs) == 1):
            self._show_uninstall_variants_dialog(name, cat_key, scope, variant_dirs)
        else:
            self._do_uninstall(name, cat_key, scope)

    def _do_uninstall(self, name, cat_key, scope):
        ok, msg = installer.uninstall_theme(name, cat_key, scope)
        if ok:
            self.show_toast(f"✅ {msg}")
            GLib.idle_add(self._populate_installed, self.search_entry.get_text().lower() if getattr(self, 'search_entry', None) else "")
        else:
            self.show_toast(f"❌ {msg}")

    def _show_uninstall_variants_dialog(self, name, cat_key, scope, variant_dirs):
        d = Adw.Dialog(title=f"Delete Group: {name}")
        d.set_content_width(450); d.set_content_height(500)
        tb = Adw.ToolbarView(); tb.add_top_bar(Adw.HeaderBar())
        
        box = Gtk.Box(orientation=1, spacing=10)
        box.set_margin_start(12); box.set_margin_end(12); box.set_margin_top(12); box.set_margin_bottom(12)
        
        ab = Gtk.Button(label="Delete All Group", valign=Gtk.Align.CENTER)
        ab.add_css_class("destructive-action")
        
        def _delete_all():
            d.close()
            if cat_key in ("grub", "plymouth"):
                self._do_uninstall(name, cat_key, scope)
            else:
                for vd in variant_dirs:
                    installer.uninstall_variant(vd, scope)
                self.show_toast("✅ Group deleted")
                GLib.idle_add(self._populate_installed, self.search_entry.get_text().lower() if getattr(self, 'search_entry', None) else "")
                
        ab.connect("clicked", lambda b: _delete_all())
        box.append(ab)
        
        lbl = Gtk.Label(label="Or delete a specific variant:", xalign=0)
        lbl.add_css_class("dim-label"); box.append(lbl)
        
        sw = Gtk.ScrolledWindow(vexpand=True)
        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        
        for var_dir in variant_dirs:
            var_name = var_dir.name
            row = Adw.ActionRow(title=var_name, subtitle=str(var_dir))
            btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            btn.add_css_class("flat"); btn.add_css_class("error")
            btn.connect("clicked", lambda b, d=d, p=var_dir: self._do_uninstall_variant(d, p, scope))
            row.add_suffix(btn)
            listbox.append(row)
            
        sw.set_child(listbox)
        box.append(sw); tb.set_content(box); d.set_child(tb)
        d.present(self.installed_dialog if getattr(self, 'installed_dialog', None) else self)

    def _do_uninstall_variant(self, dialog, var_dir, scope):
        ok, msg = installer.uninstall_variant(var_dir, scope)
        if ok:
            self.show_toast("✅ Variant deleted")
            dialog.close()
            GLib.idle_add(self._populate_installed, self.search_entry.get_text().lower() if getattr(self, 'search_entry', None) else "")
        else:
            self.show_toast(f"❌ {msg}")

    def _show_prefs(self, btn):
        d = Adw.Dialog(); d.set_title("Preferences")
        d.set_content_width(450); d.set_content_height(550)
        tb = Adw.ToolbarView(); tb.add_top_bar(Adw.HeaderBar())
        vb = Gtk.Box(orientation=1, spacing=10)
        vb.set_margin_start(12); vb.set_margin_end(12); vb.set_margin_top(8); vb.set_margin_bottom(8)

        # Appearance
        ag = Adw.PreferencesGroup(title="Appearance")
        dr = Adw.ActionRow(title="Dark theme", subtitle="Switch between light and dark theme")
        ds = Gtk.Switch(valign=Gtk.Align.CENTER)
        ds.set_active(self.is_dark)
        
        def _on_dark_toggle(s, _):
            self.is_dark = s.get_active()
            Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if self.is_dark else Adw.ColorScheme.FORCE_LIGHT)
            cfg = _load_config(); cfg["dark_mode"] = self.is_dark; _save_config(cfg)
            
        ds.connect("notify::active", _on_dark_toggle)
        dr.add_suffix(ds); dr.set_activatable_widget(ds); ag.add(dr)
        vb.append(ag)

        # Behavior
        bg = Adw.PreferencesGroup(title="Behavior")
        gr_row = Adw.ActionRow(title="Show GRUB warning", subtitle="Show warning when GRUB directory is locked")
        gr_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        gr_switch.set_active(getattr(self, 'show_grub_warning', True))
        
        def _on_grub_toggle(s, _):
            self.show_grub_warning = s.get_active()
            cfg = _load_config()
            cfg["show_grub_warning"] = self.show_grub_warning
            _save_config(cfg)
            
        gr_switch.connect("notify::active", _on_grub_toggle)
        gr_row.add_suffix(gr_switch); gr_row.set_activatable_widget(gr_switch); bg.add(gr_row)

        # Disclaimer Toggle
        cfg = _load_config()
        disc_row = Adw.ActionRow(title="Show installation disclaimer", subtitle="Show warning disclaimer before theme installation")
        disc_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        disc_switch.set_active(not cfg.get("hide_install_disclaimer", False))
        
        def _on_disc_toggle(s, _):
            c = _load_config()
            c["hide_install_disclaimer"] = not s.get_active()
            _save_config(c)
            
        disc_switch.connect("notify::active", _on_disc_toggle)
        disc_row.add_suffix(disc_switch); disc_row.set_activatable_widget(disc_switch); bg.add(disc_row)
        vb.append(bg)

        # Performance
        pf = Adw.PreferencesGroup(title="Performance")
        lp_row = Adw.ActionRow(title="Low performance mode", subtitle="Only load text. Images load when you click a theme.")
        lp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        lp_switch.set_active(self.low_performance)
        
        def _on_lp_toggle(s, _):
            self.low_performance = s.get_active()
            c = _load_config()
            c["low_performance"] = self.low_performance
            _save_config(c)
            self.loading = False
            self._load_themes()
            
        lp_switch.connect("notify::active", _on_lp_toggle)
        lp_row.add_suffix(lp_switch); lp_row.set_activatable_widget(lp_switch); pf.add(lp_row)
        vb.append(pf)

        # Paths
        pg = Adw.PreferencesGroup(title="Installation paths")
        for key, cat in api.CATEGORIES.items():
            paths = installer.get_install_paths()[key]
            for scope, path in paths.items():
                pg.add(Adw.ActionRow(title=f"{cat['title']} ({scope})", subtitle=str(path)))
        vb.append(pg)

        # Help and Support
        hg = Adw.PreferencesGroup(title="Help and Support")
        t_row = Adw.ActionRow(title="Welcome Tutorial", subtitle="Replay the application onboarding walkthrough")
        t_btn = Gtk.Button(label="Replay", valign=Gtk.Align.CENTER)
        t_btn.connect("clicked", lambda b: (d.close(), self._show_welcome_tutorial()))
        t_row.add_suffix(t_btn)
        hg.add(t_row)
        vb.append(hg)

        sw = Gtk.ScrolledWindow(vexpand=True); sw.set_child(vb)
        tb.set_content(sw); d.set_child(tb); d.present(self)

    def _show_about(self, btn):
        about = Adw.AboutDialog(
            application_name=__app_name__,
            application_icon="gnome-theme-manager",
            version=__version__,
            developer_name=__authors__[0],
            website=__website_url__,
            issue_url=__github_url__,
            license_type=Gtk.License.GPL_3_0,
            developers=[f"{a} <https://github.com/unaibenidorm>" for a in __authors__],
            comments="Download and install GNOME themes from gnome-look.org.\n"
                     "Supports GTK, GNOME Shell, Icons, GDM, GRUB and Plymouth.",
        )
        about.present(self)

    def _show_welcome_tutorial(self):
        d = Adw.Dialog(title="Welcome Assistant")
        d.set_content_width(520); d.set_content_height(480)
        
        tb = Adw.ToolbarView()
        tb.add_top_bar(Adw.HeaderBar())
        
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_transition_duration(300)
        
        # Slide 1: Welcome
        s1 = Gtk.Box(orientation=1, spacing=14)
        s1.set_margin_start(24); s1.set_margin_end(24); s1.set_margin_top(24); s1.set_margin_bottom(24)
        s1.set_valign(Gtk.Align.CENTER)
        
        brush = Gtk.Image(icon_name="preferences-desktop-appearance-symbolic")
        brush.set_pixel_size(64)
        brush.add_css_class("accent")
        s1.append(brush)
        
        l1 = Gtk.Label(label="Gnome Theme Manager"); l1.add_css_class("welcome-title")
        s1.append(l1)
        
        sub1 = Gtk.Label(label="Transform your Linux environment with ease")
        sub1.add_css_class("welcome-subtitle"); sub1.set_wrap(True)
        s1.append(sub1)
        
        desc1 = Gtk.Label(label="Welcome to the ultimate hub for GNOME customization. Browse thousands of gorgeous themes directly from gnome-look.org and install them natively in seconds.")
        desc1.set_wrap(True); desc1.add_css_class("dim-label")
        s1.append(desc1)
        stack.add_named(s1, "welcome")
        
        # Slide 2: Categories
        s2 = Gtk.Box(orientation=1, spacing=12)
        s2.set_margin_start(24); s2.set_margin_end(24); s2.set_margin_top(16); s2.set_margin_bottom(16)
        s2.set_valign(Gtk.Align.CENTER)
        
        l2 = Gtk.Label(label="Rich Theme Support"); l2.add_css_class("welcome-title")
        s2.append(l2)
        
        desc2 = Gtk.Label(label="Discover and safely apply the correct theme types:")
        desc2.set_wrap(True); s2.append(desc2)
        
        cat_grid = Gtk.Box(orientation=1, spacing=8)
        
        c_items = [
            ("preferences-desktop-wallpaper-symbolic", "GTK 3/4 & GNOME Shell Themes", "Visual components and desktop shells"),
            ("folder-symbolic", "Icons & Cursors Themes", "Enrich icons, folder styles, and mouse cursors"),
            ("drive-harddisk-symbolic", "GRUB, Plymouth & GDM Themes", "Beautiful bootloaders, splash screens, and logins")
        ]
        for icon, title, desc in c_items:
            row_box = Gtk.Box(spacing=12)
            row_box.add_css_class("tutorial-step-card")
            img = Gtk.Image(icon_name=icon)
            img.set_pixel_size(24)
            row_box.append(img)
            
            lbl_box = Gtk.Box(orientation=1)
            t_lbl = Gtk.Label(label=title, xalign=0); t_lbl.add_css_class("bold")
            d_lbl = Gtk.Label(label=desc, xalign=0); d_lbl.add_css_class("dim-label")
            lbl_box.append(t_lbl); lbl_box.append(d_lbl)
            row_box.append(lbl_box)
            cat_grid.append(row_box)
            
        s2.append(cat_grid)
        stack.add_named(s2, "categories")
        
        # Slide 3: Performance Config
        s3 = Gtk.Box(orientation=1, spacing=14)
        s3.set_margin_start(24); s3.set_margin_end(24); s3.set_margin_top(24); s3.set_margin_bottom(24)
        s3.set_valign(Gtk.Align.CENTER)
        
        perf_img = Gtk.Image(icon_name="preferences-system-symbolic")
        perf_img.set_pixel_size(64)
        perf_img.add_css_class("success")
        s3.append(perf_img)
        
        l3 = Gtk.Label(label="Maximize Performance"); l3.add_css_class("welcome-title")
        s3.append(l3)
        
        desc3 = Gtk.Label(label="Using a Virtual Machine or a slow internet connection? Toggle Low Performance Mode below to instantly load theme lists without fetching preview images, preventing API timeouts completely!")
        desc3.set_wrap(True); desc3.add_css_class("dim-label")
        s3.append(desc3)
        
        perf_row = Adw.ActionRow(title="Enable Low Performance Mode", subtitle="Skip heavy loading and display compact theme cards")
        perf_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        perf_switch.set_active(self.low_performance)
        
        def _on_switch_toggle(sw, _):
            self.low_performance = sw.get_active()
            c = _load_config()
            c["low_performance"] = self.low_performance
            _save_config(c)
            self.loading = False
            self._load_themes()
            
        perf_switch.connect("notify::active", _on_switch_toggle)
        perf_row.add_suffix(perf_switch)
        perf_row.set_activatable_widget(perf_switch)
        
        perf_group = Adw.PreferencesGroup()
        perf_group.add(perf_row)
        s3.append(perf_group)
        stack.add_named(s3, "perf")
        
        # Slide 4: Safe Admin
        s4 = Gtk.Box(orientation=1, spacing=14)
        s4.set_margin_start(24); s4.set_margin_end(24); s4.set_margin_top(24); s4.set_margin_bottom(24)
        s4.set_valign(Gtk.Align.CENTER)
        
        shield = Gtk.Image(icon_name="security-high-symbolic")
        shield.set_pixel_size(64)
        shield.add_css_class("warning")
        s4.append(shield)
        
        l4 = Gtk.Label(label="Safe System Modding"); l4.add_css_class("welcome-title")
        s4.append(l4)
        
        desc4 = Gtk.Label(label="Installing bootloader (GRUB) or startup splash (Plymouth) themes modifies protected system folders.\n\nThe application will safely prompt for administrative permission using secure policy executors (pkexec) only when necessary, keeping your personal folders fully clean.")
        desc4.set_wrap(True); desc4.add_css_class("dim-label")
        s4.append(desc4)
        stack.add_named(s4, "safe")
        
        # Slide 5: Ready!
        s5 = Gtk.Box(orientation=1, spacing=14)
        s5.set_margin_start(24); s5.set_margin_end(24); s5.set_margin_top(24); s5.set_margin_bottom(24)
        s5.set_valign(Gtk.Align.CENTER)
        
        check_icon = Gtk.Image(icon_name="object-select-symbolic")
        check_icon.set_pixel_size(64)
        check_icon.add_css_class("success")
        s5.append(check_icon)
        
        l5 = Gtk.Label(label="All Set!"); l5.add_css_class("welcome-title")
        s5.append(l5)
        
        desc5 = Gtk.Label(label="Your customized GNOME workspace awaits. Welcome to the elegant desktop experience.")
        desc5.set_wrap(True); desc5.add_css_class("welcome-subtitle")
        s5.append(desc5)
        
        stack.add_named(s5, "ready")
        
        # Controls Box
        controls = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        controls.set_margin_bottom(16)
        
        btn_prev = Gtk.Button(label="Back")
        btn_prev.set_sensitive(False)
        controls.append(btn_prev)
        
        # Slide indicators
        ind_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        slides = ["welcome", "categories", "perf", "safe", "ready"]
        dots = []
        for index, name in enumerate(slides):
            dot = Gtk.Box()
            dot.add_css_class("tutorial-dot")
            if index == 0:
                dot.add_css_class("tutorial-dot-active")
            ind_box.append(dot)
            dots.append(dot)
        controls.append(ind_box)
        
        btn_next = Gtk.Button(label="Next")
        btn_next.add_css_class("suggested-action")
        controls.append(btn_next)
        
        def update_navigation():
            cur = stack.get_visible_child_name()
            idx = slides.index(cur)
            btn_prev.set_sensitive(idx > 0)
            
            if idx == len(slides) - 1:
                btn_next.set_label("Get Started!")
                btn_next.add_css_class("success")
            else:
                btn_next.set_label("Next")
                btn_next.remove_css_class("success")
                btn_next.add_css_class("suggested-action")
                
            for i, dot in enumerate(dots):
                dot.remove_css_class("tutorial-dot-active")
                if i == idx:
                    dot.add_css_class("tutorial-dot-active")
                    
        def _on_next(*args):
            cur = stack.get_visible_child_name()
            idx = slides.index(cur)
            if idx == len(slides) - 1:
                d.close()
                c = _load_config()
                c["first_run"] = False
                _save_config(c)
                # After tutorial finish, if grub warning was deferred, show it
                if self.show_grub_warning:
                    self._check_startup_permissions()
            else:
                stack.set_visible_child_name(slides[idx + 1])
                update_navigation()
                
        def _on_prev(*args):
            cur = stack.get_visible_child_name()
            idx = slides.index(cur)
            if idx > 0:
                stack.set_visible_child_name(slides[idx - 1])
                update_navigation()
                
        btn_next.connect("clicked", _on_next)
        btn_prev.connect("clicked", _on_prev)
        
        tb.set_content(stack)
        tb.add_bottom_bar(controls)
        d.set_child(tb)
        d.present(self)
