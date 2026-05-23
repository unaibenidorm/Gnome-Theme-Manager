"""
GRUB Customizer engine and UI for Gnome Theme Manager.
A complete pythonic native replica of Grub Customizer following Libadwaita styling guidelines.
"""
import gi, re, os, tempfile, subprocess, threading, shlex
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GObject
from pathlib import Path
from . import installer
from .widgets import CommandDialog

# ── Safe path helpers ─────────────────────────────────────────────────────────
# On Fedora, /boot/grub2/** is root-only. Python 3.11+ raises PermissionError
# on Path.exists() / .is_dir() / .iterdir() instead of returning False/[].
# These wrappers never raise — they always return a safe value.

def _safe_exists(p):
    try:
        return p.exists()
    except OSError:
        return False

def _safe_is_dir(p):
    try:
        return p.is_dir()
    except OSError:
        return False

def _safe_iterdir(p):
    try:
        return list(p.iterdir())
    except OSError:
        return []

def _safe_is_file(p):
    try:
        return p.is_file()
    except OSError:
        return False


# ── Robust dialog presentation ────────────────────────────────────────────────
def safe_present(dialog, parent):
    if hasattr(dialog, "set_transient_for"):
        try:
            dialog.set_transient_for(parent)
        except Exception:
            pass
        try:
            dialog.present()
        except TypeError:
            dialog.present(parent)
    else:
        try:
            dialog.present(parent)
        except Exception:
            try:
                dialog.present()
            except Exception:
                pass


# ── pkexec via temp file (avoids SELinux inline-script block on Fedora) ───────
def _run_pkexec_script(py_script):
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(py_script)
        os.chmod(tmp_path, 0o644)
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        clean_env.pop("LD_LIBRARY_PATH", None)
        clean_env.pop("APPIMAGE", None)
        prep_cmd = "rm -rf /tmp/gtm_themes; mkdir -p /tmp/gtm_themes; cp -r /boot/grub/themes/* /tmp/gtm_themes/ 2>/dev/null; cp -r /boot/grub2/themes/* /tmp/gtm_themes/ 2>/dev/null; chmod -R 777 /tmp/gtm_themes 2>/dev/null;"
        full_sh = f"{prep_cmd} /usr/bin/python3 {tmp_path}"
        cmd = f"pkexec bash -c {shlex.quote(full_sh)}"
        res = subprocess.run(
            shlex.split(cmd),
            capture_output=True, text=True, timeout=60, env=clean_env
        )
        if res.returncode in (126, 127):   # cancelled / not found
            return None
        return res.stdout if res.returncode == 0 else None
    except Exception as e:
        import sys; sys.stderr.write(f"[GTM Debug] pkexec failed: {e}\n")
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Unified GRUB info loader ──────────────────────────────────────────────────
def load_all_grub_info():
    py_script = (
        "import sys\n"
        "from pathlib import Path\n"
        "paths = ['/boot/grub2/grub.cfg', '/boot/grub/grub.cfg', '/boot/EFI/fedora/grub.cfg']\n"
        "grub_cfg = ''\n"
        "for p in paths:\n"
        "    try:\n"
        "        with open(p, 'r', encoding='utf-8', errors='ignore') as f:\n"
        "            grub_cfg = f.read(); break\n"
        "    except: pass\n"
        "sys.stdout.write(grub_cfg)\n"
        "sys.stdout.write('\\n===END_OF_GRUB_CFG===\\n')\n"
        "bls_dir = Path('/boot/loader/entries')\n"
        "if bls_dir.exists() and bls_dir.is_dir():\n"
        "    try:\n"
        "        for child in sorted(bls_dir.iterdir()):\n"
        "            if child.is_file() and child.suffix == '.conf':\n"
        "                try:\n"
        "                    with open(child, 'r', encoding='utf-8', errors='ignore') as f:\n"
        "                        sys.stdout.write(f'===BLS_FILE:{child}===\\n' + f.read() + '\\n')\n"
        "                except: pass\n"
        "    except: pass\n"
        "sys.stdout.write('\\n===GRUB_THEMES===\\n')\n"
        "for tp in [Path('/boot/grub/themes'), Path('/boot/grub2/themes')]:\n"
        "    if tp.exists() and tp.is_dir():\n"
        "        try:\n"
        "            for child in tp.iterdir():\n"
        "                if child.is_dir(): sys.stdout.write(child.name + '\\n')\n"
        "        except: pass\n"
        "sys.stdout.write('\\n===GRUB_THEMES_CONTENT===\\n')\n"
        "for tp in [Path('/boot/grub/themes'), Path('/boot/grub2/themes')]:\n"
        "    if tp.exists() and tp.is_dir():\n"
        "        try:\n"
        "            for child in tp.iterdir():\n"
        "                if child.is_dir():\n"
        "                    theme_txt = child / 'theme.txt'\n"
        "                    if theme_txt.exists():\n"
        "                        try:\n"
        "                            with open(theme_txt, 'r', encoding='utf-8', errors='ignore') as f:\n"
        "                                sys.stdout.write(f'===THEME_FILE:{child.name}/theme.txt===\\n' + f.read() + '\\n')\n"
        "                        except: pass\n"
        "        except: pass\n"
        "sys.stdout.write('\\n===BTRFS_CFG===\\n')\n"
        "for bp in ['/boot/grub2/grub-btrfs.cfg','/boot/grub/grub-btrfs.cfg','/boot/EFI/fedora/grub-btrfs.cfg']:\n"
        "    try:\n"
        "        with open(bp, 'r', encoding='utf-8', errors='ignore') as f:\n"
        "            sys.stdout.write(f.read()); break\n"
        "    except: pass\n"
    )

    # ── 1. Try local read first (works if user already has rights, e.g. Ubuntu) ─
    local_output = ""
    for p in ["/boot/grub2/grub.cfg", "/boot/grub/grub.cfg", "/boot/EFI/fedora/grub.cfg"]:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                local_output = f.read(); break
        except Exception:
            continue

    for bp in ["/boot/grub2/grub-btrfs.cfg", "/boot/grub/grub-btrfs.cfg", "/boot/EFI/fedora/grub-btrfs.cfg"]:
        try:
            with open(bp, "r", encoding="utf-8", errors="ignore") as f:
                btrfs_cfg = f.read()
                if btrfs_cfg and local_output:
                    local_output = re.sub(
                        r'configfile\s+["\']?([^"\']*(?:grub-btrfs\.cfg|btrfs)[^"\']*)["\']?',
                        btrfs_cfg, local_output)
                break
        except Exception:
            pass

    local_output += "\n===END_OF_GRUB_CFG===\n"

    # BLS entries
    bls_dir = Path("/boot/loader/entries")
    if _safe_exists(bls_dir) and _safe_is_dir(bls_dir):
        for child in sorted(_safe_iterdir(bls_dir)):
            try:
                if _safe_is_file(child) and child.suffix == ".conf":
                    with open(child, "r", encoding="utf-8", errors="ignore") as f:
                        local_output += f"===BLS_FILE:{child}===\n" + f.read() + "\n"
            except Exception:
                pass

    local_output += "\n===GRUB_THEMES===\n"
    for tp in [Path("/boot/grub/themes"), Path("/boot/grub2/themes")]:
        if _safe_exists(tp) and _safe_is_dir(tp):
            for child in _safe_iterdir(tp):
                try:
                    if _safe_is_dir(child):
                        local_output += child.name + "\n"
                except Exception:
                    pass

    # If we already have useful data, skip pkexec entirely
    if "menuentry" in local_output or "===BLS_FILE:" in local_output:
        return local_output

    # ── 2. Need elevation — pkexec via temp file ──────────────────────────────
    pkexec_output = _run_pkexec_script(py_script)
    if pkexec_output:
        output = pkexec_output
        btrfs_str = ""
        if "===BTRFS_CFG===" in output:
            parts = output.split("===BTRFS_CFG===")
            output = parts[0]
            if len(parts) > 1:
                btrfs_str = parts[1].strip()
        if btrfs_str and output:
            output = re.sub(
                r'configfile\s+["\']?([^"\']*(?:grub-btrfs\.cfg|btrfs)[^"\']*)["\']?',
                btrfs_str, output)
        return output

    import sys
    sys.stderr.write("[GTM Debug] pkexec unavailable or cancelled.\n")
    if "menuentry" not in local_output and "===BLS_FILE:" not in local_output:
        raise PermissionError("Autenticación cancelada o fallida")
    return local_output


# ── Theme root resolver ───────────────────────────────────────────────────────
def find_theme_root(base_dir):
    base_path = Path(base_dir)
    if not _safe_exists(base_path):
        return base_path
    if _safe_exists(base_path / "theme.txt"):
        return base_path
    try:
        for p in base_path.glob("**/theme.txt"):
            if _safe_exists(p):
                return p.parent
    except Exception:
        pass
    try:
        for p in base_path.glob("**/*.txt"):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if "desktop-image" in content or "boot_menu" in content:
                        return p.parent
            except Exception:
                continue
    except Exception:
        pass
    return base_path


# ── GRUB config parser ────────────────────────────────────────────────────────
def parse_menu_entries_unified(raw_output):
    if not raw_output:
        return []

    parts = raw_output.split("===END_OF_GRUB_CFG===")
    grub_cfg_content = parts[0]
    bls_part = parts[1] if len(parts) > 1 else ""
    entries = []

    # 1. BLS entries
    for block in bls_part.split("===BLS_FILE:"):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        file_lines = lines[1:] if lines else []
        title = options = linux_img = initrd_img = ""
        for line in file_lines:
            subparts = line.strip().split(None, 1)
            if len(subparts) == 2:
                k, v = subparts[0].lower(), subparts[1]
                if k == "title": title = v
                elif k == "options": options = v
                elif k == "linux": linux_img = v
                elif k == "initrd": initrd_img = v
        if title:
            code = f"menuentry '{title}' {{\n"
            if linux_img: code += f"\tlinux {linux_img} {options}\n"
            if initrd_img: code += f"\tinitrd {initrd_img}\n"
            code += "}"
            entries.append({"title": title, "type": "linux", "code": code, "is_submenu_item": False})

    # 2. grub.cfg entries
    lines = grub_cfg_content.splitlines()
    i = n = 0
    n = len(lines)
    stack = []
    while i < n:
        line = lines[i]
        stripped = line.strip()
        match_s = re.search(r'submenu\s+[\'"]([^\'"]+)[\'"]', stripped)
        if match_s:
            title = match_s.group(1)
            depth = len(stack)
            if not any(e["title"] == title for e in entries):
                entries.append({"title": title, "type": "submenu", "code": line,
                                 "is_submenu_item": depth > 0, "submenu_depth": depth, "collapsed": False})
            stack.append("submenu"); i += 1; continue
        match_m = re.search(r'menuentry\s+[\'"]([^\'"]+)[\'"]', stripped)
        if match_m:
            title = match_m.group(1)
            block_lines = [line]
            brace_count = line.count("{") - line.count("}")
            j = i + 1
            while j < n and brace_count > 0:
                l = lines[j]; block_lines.append(l)
                brace_count += l.count("{") - l.count("}"); j += 1
            code = "\n".join(block_lines)
            t_type = "linux"
            if "windows" in title.lower(): t_type = "windows"
            elif "settings" in title.lower() or "firmware" in title.lower(): t_type = "script"
            elif "memtest" in title.lower() or "memory" in title.lower(): t_type = "script"
            depth = len(stack)
            if not any(e["title"] == title for e in entries):
                entries.append({"title": title, "type": t_type, "code": code,
                                 "is_submenu_item": depth > 0, "submenu_depth": depth})
            i = j; continue
        if "{" in stripped:
            for _ in range(stripped.count("{") - stripped.count("}")): stack.append("generic")
        elif "}" in stripped:
            for _ in range(stripped.count("}") - stripped.count("{")): 
                if stack: stack.pop()
        i += 1
    return entries


def read_grub_defaults(path="/etc/default/grub"):
    defaults = {
        "GRUB_DEFAULT": {"value": "0", "active": True},
        "GRUB_TIMEOUT": {"value": "5", "active": True},
        "GRUB_TIMEOUT_STYLE": {"value": "menu", "active": True},
        "GRUB_DISABLE_RECOVERY": {"value": "false", "active": False},
        "GRUB_DISABLE_OS_PROBER": {"value": "false", "active": False},
        "GRUB_CMDLINE_LINUX_DEFAULT": {"value": "quiet splash", "active": True},
        "GRUB_CMDLINE_LINUX": {"value": "", "active": True},
        "GRUB_BACKGROUND": {"value": "", "active": False},
        "GRUB_THEME": {"value": "", "active": False},
        "GRUB_GFXMODE": {"value": "auto", "active": False},
    }
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    is_commented = line.startswith("#")
                    temp_line = line[1:].strip() if is_commented else line
                    if "=" in temp_line:
                        parts = temp_line.split("=", 1)
                        key = parts[0].strip()
                        if re.match(r'^[A-Za-z0-9_]+$', key):
                            val = parts[1].strip().strip('"').strip("'")
                            defaults[key] = {"value": val, "active": not is_commented}
        except Exception:
            pass
    return defaults


def get_installed_grub_themes(raw_info=None):
    themes = ["(None/Default)"]
    if raw_info and "===GRUB_THEMES===" in raw_info:
        parts = raw_info.split("===GRUB_THEMES===")
        if len(parts) > 1:
            theme_block = parts[1].split("===GRUB_THEMES_CONTENT===")[0]
            for line in theme_block.split("\n"):
                line = line.strip()
                if line and not line.startswith("==="): themes.append(line)
    for p in [Path("/boot/grub/themes"), Path("/boot/grub2/themes")]:
        if _safe_exists(p) and _safe_is_dir(p):
            for child in _safe_iterdir(p):
                try:
                    if _safe_is_dir(child): themes.append(child.name)
                except Exception: pass
    return sorted(list(set(themes)))


def parse_coordinate(val, max_px):
    val = str(val).strip().strip('"').strip("'")
    if not val: return 0.0
    if val.endswith("%"):
        try: return float(val[:-1]) / 100.0 * max_px
        except ValueError: return 0.0
    if "%" in val:
        parts = val.split("%")
        try:
            pct = float(parts[0]) / 100.0 * max_px
            offset = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
            return pct + offset
        except ValueError: pass
    try: return float(val)
    except ValueError: return 0.0


def scale_font_desc(font_str, scale_factor):
    font_str = str(font_str).strip().strip('"').strip("'")
    if not font_str: return "Sans 10"
    match = re.search(r'^(.*?)\s+(\d+)$', font_str)
    if match:
        family = match.group(1).strip()
        try:
            size = float(match.group(2))
            return f"{family} {max(7, int(size * scale_factor))}"
        except ValueError: pass
    return "Sans 10"


def find_grub_entry_icon(theme_dir, entry):
    if not theme_dir: return None
    theme_path = Path(theme_dir)
    if not _safe_exists(theme_path): return None
    title = entry.get("title", "").lower()
    t = entry.get("type", "")
    candidates = []
    if "ubuntu" in title: candidates.extend(["ubuntu", "linux"])
    elif "windows" in title or "win10" in title or "win11" in title:
        candidates.extend(["windows", "windows7", "windows8", "win", "microsoft"])
    elif "fedora" in title: candidates.extend(["fedora", "linux"])
    elif "debian" in title: candidates.extend(["debian", "linux"])
    elif "arch" in title: candidates.extend(["arch", "linux"])
    elif "manjaro" in title: candidates.extend(["manjaro", "linux"])
    elif "mint" in title: candidates.extend(["mint", "linux"])
    elif "gentoo" in title: candidates.extend(["gentoo", "linux"])
    elif t == "submenu" or "advanced" in title or "opciones avanzadas" in title:
        candidates.extend(["submenu", "folder", "sub"])
    else: candidates.extend(["linux", "gnu-linux", "unknown"])
    folders = [theme_path / "icons", theme_path / "icon", theme_path]
    for folder in folders:
        if _safe_exists(folder) and _safe_is_dir(folder):
            for cand in candidates:
                for ext in [".png", ".jpg", ".jpeg"]:
                    p = folder / f"{cand}{ext}"
                    if _safe_exists(p): return str(p)
    for folder in folders:
        if _safe_exists(folder) and _safe_is_dir(folder):
            for child in _safe_iterdir(folder):
                try:
                    if _safe_is_file(child) and child.suffix.lower() == ".png":
                        cname = child.stem.lower()
                        for cand in candidates:
                            if cand in cname or cname in cand: return str(child)
                except Exception: pass
    return None


def parse_theme_style(theme_dir, active_variant="theme.txt", cached_contents=None):
    config = {
        "desktop-image": "background.png", "title-text": "GRUB Bootloader Menu",
        "title-color": "#ffffff", "title-left": "10%", "title-top": "10%",
        "title-width": "80%", "title-height": "40", "title-font": "Sans Bold 16",
        "item-color": "#cccccc", "selected-item-color": "#ffffff",
        "item-font": "Sans 14", "selected-item-font": "Sans Bold 14",
        "menu-left": "15%", "menu-top": "20%", "menu-width": "70%", "menu-height": "60%",
        "timeout-text": "Booting in %d seconds...",
        "timeout-left": "10%", "timeout-top": "85%",
        "timeout-width": "80%", "timeout-height": "30",
        "timeout-font": "Sans 12", "timeout-color": "#aaaaaa",
    }
    if not theme_dir: return config

    content = None
    if cached_contents:
        theme_name = Path(theme_dir).name
        key = f"{theme_name}/{active_variant}"
        content = cached_contents.get(key)
    
    if content is None:
        try:
            path = Path(theme_dir) / active_variant
            if not path.exists(): return config
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return config
            
    if not content: return config

    try:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#") or not line: continue
            sep = "=" if "=" in line else (":" if ":" in line else None)
            if sep:
                parts = line.split(sep, 1)
                k = parts[0].strip().lower().replace("_", "-")
                v = parts[1].strip().strip('"').strip("'")
                if k in ["desktop-image", "title-text", "title-color"]: config[k] = v
        blocks = re.findall(r'\+\s*([a-zA-Z0-9_]+)\s*\{([^}]+)\}', content, re.DOTALL)
        for bname, bcontent in blocks:
            bname = bname.strip().lower()
            attrs = {}
            for bline in bcontent.splitlines():
                bline = bline.strip()
                bsep = "=" if "=" in bline else (":" if ":" in bline else None)
                if bsep:
                    bparts = bline.split(bsep, 1)
                    bk = bparts[0].strip().lower().replace("_", "-")
                    bv = bparts[1].strip().strip('"').strip("'")
                    attrs[bk] = bv
            if bname in ["boot-menu", "boot_menu", "menu"]:
                for k in ["left", "top", "width", "height"]:
                    if k in attrs: config[f"menu-{k}"] = attrs[k]
                for k in ["item-color", "selected-item-color", "item-font", "selected-item-font"]:
                    if k in attrs: config[k] = attrs[k]
                    elif k.replace("-", "_") in attrs: config[k] = attrs[k.replace("-", "_")]
            elif bname == "label":
                label_id = attrs.get("id", "").strip().lower()
                is_timeout = (label_id == "__timeout__") or ("timeout" in attrs.get("text", "").lower())
                prefix = "timeout-" if is_timeout else "title-"
                if "text" in attrs: config[prefix + "text"] = attrs["text"]
                if "color" in attrs: config[prefix + "color"] = attrs["color"]
                if "font" in attrs: config[prefix + "font"] = attrs["font"]
                for k in ["left", "top", "width", "height"]:
                    if k in attrs: config[prefix + k] = attrs[k]
    except Exception as e:
        print("Error parsing theme style:", e)
    return config


# ─────────────────────────────────────────────────────────────────────────────
# UI Classes
# ─────────────────────────────────────────────────────────────────────────────

class EntryEditorDialog(Adw.Dialog):
    def __init__(self, entry, on_save_callback):
        super().__init__(title="Entry Editor - Grub Customizer")
        self.entry = entry
        self.on_save_callback = on_save_callback
        self.set_content_width(450); self.set_content_height(420)
        self._build_ui()

    def _build_ui(self):
        vb = Gtk.Box(orientation=1, spacing=14)
        vb.set_margin_start(16); vb.set_margin_end(16); vb.set_margin_top(16); vb.set_margin_bottom(16)
        hb_name = Gtk.Box(spacing=8)
        lbl_name = Gtk.Label(label="Name:", xalign=0); lbl_name.set_size_request(80, -1)
        self.name_entry = Gtk.Entry(text=self.entry.get("title", "")); self.name_entry.set_hexpand(True)
        hb_name.append(lbl_name); hb_name.append(self.name_entry); vb.append(hb_name)
        vb.append(Gtk.Label(label="Type:", xalign=0))
        self.type_listbox = Gtk.ListBox(); self.type_listbox.add_css_class("boxed-list")
        types = [("Linux", "linux"), ("Linux (ISO)", "linux_iso"), ("Chainloader", "windows"),
                 ("Memory test", "script"), ("Other", "script"), ("(Script code)", "custom")]
        self.rows_map = {}
        for display_name, internal_value in types:
            row = Adw.ActionRow(title=display_name); row._val = internal_value
            self.type_listbox.append(row); self.rows_map[internal_value] = row
        vb.append(self.type_listbox)
        vb.append(Gtk.Label(label="Script code:", xalign=0))
        self.code_view = Gtk.TextView(monospace=True); self.code_view.set_size_request(-1, 120)
        self.buf = self.code_view.get_buffer(); self.buf.set_text(self.entry.get("code", ""))
        scr = Gtk.ScrolledWindow(vexpand=True); scr.set_child(self.code_view); vb.append(scr)
        active_type = self.entry.get("type", "linux")
        if active_type in self.rows_map: self.type_listbox.select_row(self.rows_map[active_type])
        else: self.type_listbox.select_row(self.rows_map["custom"])
        def _on_type_changed(lb, row):
            if row:
                t = row._val; name = self.name_entry.get_text() or "Custom"
                if t == "linux":
                    self.buf.set_text(f"menuentry '{name}' {{\n\tlinux /boot/vmlinuz root=UUID=xxxx ro quiet splash\n\tinitrd /boot/initrd.img\n}}")
                elif t == "windows":
                    self.buf.set_text(f"menuentry '{name}' {{\n\tinsmod part_gpt\n\tinsmod chain\n\tchainloader +1\n}}")
                elif t == "script":
                    self.buf.set_text(f"menuentry '{name}' {{\n\tlinux16 /boot/memtest86+.bin\n}}")
        self.type_listbox.connect("row-selected", _on_type_changed)
        btn_apply = Gtk.Button(label="Done", valign=Gtk.Align.CENTER); btn_apply.add_css_class("suggested-action")
        def _apply_clicked(*args):
            sel_row = self.type_listbox.get_selected_row()
            t_val = sel_row._val if sel_row else "custom"
            start, end = self.buf.get_bounds()
            self.entry["title"] = self.name_entry.get_text()
            self.entry["type"] = t_val if t_val != "custom" else "linux"
            self.entry["code"] = self.buf.get_text(start, end, True)
            self.on_save_callback(); self.close()
        btn_apply.connect("clicked", _apply_clicked); vb.append(btn_apply)
        self.set_child(vb)


class FullscreenPreviewWindow(Gtk.Window):
    def __init__(self, bg_image_path, menu_entries, seconds, theme_config, hide_menu=False, theme_dir=None):
        super().__init__()
        self.fullscreen(); self.set_title("GRUB Live Preview")
        overlay = Gtk.Overlay()
        pic = Gtk.Picture(); pic.set_content_fit(Gtk.ContentFit.COVER)
        if bg_image_path: pic.set_file(Gio.File.new_for_path(bg_image_path))
        overlay.set_child(pic)
        vbox = Gtk.Box(orientation=1)
        vbox.set_valign(Gtk.Align.CENTER); vbox.set_halign(Gtk.Align.CENTER)
        vbox.set_size_request(800, 520)
        vbox.set_margin_start(40); vbox.set_margin_end(40); vbox.set_margin_top(40); vbox.set_margin_bottom(40)
        vbox.add_css_class("card"); vbox.set_opacity(0.92)
        title_label = GLib.markup_escape_text(theme_config["title-text"])
        title_color = theme_config["title-color"]
        title = Gtk.Label()
        if title_color: title.set_markup(f"<span foreground='{title_color}'>{GLib.markup_escape_text(title_label)}</span>")
        else: title.set_text(title_label)
        title.set_halign(Gtk.Align.START); title.add_css_class("welcome-title"); title.set_margin_bottom(20)
        vbox.append(title)
        sw = Gtk.ScrolledWindow(vexpand=True)
        listbox = Gtk.ListBox(); listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.add_css_class("boxed-list")
        item_color = theme_config["item-color"]; sel_color = theme_config["selected-item-color"]
        collapsed_depths = []
        for entry in menu_entries:
            is_sub = entry.get("is_submenu_item", False)
            depth = entry.get("submenu_depth", 1 if is_sub else 0)
            collapsed_depths = [dep for dep in collapsed_depths if dep < depth]
            if collapsed_depths: continue
            if entry["type"] == "submenu" and entry.get("collapsed", False): collapsed_depths.append(depth)
            title_text = entry["title"].strip(" \u21b3 ")
            if depth > 0: title_text = "   " * depth + "\u21b3 " + title_text
            title_escaped = GLib.markup_escape_text(title_text)
            box = Gtk.Box(spacing=10)
            custom_icon = find_grub_entry_icon(theme_dir, entry)
            if custom_icon: img = Gtk.Image.new_from_file(custom_icon)
            else:
                icon_name = "applications-system-symbolic"; t = entry["type"]
                if t == "submenu": icon_name = "folder-symbolic"
                elif t == "script": icon_name = "preferences-system-symbolic"
                elif t == "windows": icon_name = "computer-symbolic"
                img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(24)
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup(f"<span foreground='{item_color}'>{title_escaped}</span>")
            box.append(img); box.append(lbl)
            row = Gtk.ListBoxRow(); row.set_child(box); row._lbl = lbl; row._txt = title_escaped
            listbox.append(row)
        def _on_sel(lb, row):
            for r in lb:
                if hasattr(r, '_lbl'):
                    escaped_txt = GLib.markup_escape_text(r._txt)
                    if r == row: r._lbl.set_markup(f"<span foreground='{sel_color}'><b>{escaped_txt}</b></span>")
                    else: r._lbl.set_markup(f"<span foreground='{item_color}'>{escaped_txt}</span>")
        listbox.connect("row-selected", _on_sel)
        first = listbox.get_row_at_index(0)
        if first: listbox.select_row(first)
        sw.set_child(listbox); vbox.append(sw)
        timeout_lbl = Gtk.Label(label=f"El arranque automático comenzará en {seconds} segundos...")
        timeout_lbl.add_css_class("dim-label"); timeout_lbl.set_margin_top(20); vbox.append(timeout_lbl)
        vbox.set_visible(False); overlay.add_overlay(vbox)
        hint_lbl = Gtk.Label(label="Presiona ESC o haz click en cualquier sitio para cerrar")
        hint_lbl.set_halign(Gtk.Align.CENTER); hint_lbl.set_valign(Gtk.Align.END)
        hint_lbl.set_margin_bottom(30); hint_lbl.add_css_class("dim-label"); hint_lbl.set_visible(False)
        overlay.add_overlay(hint_lbl)
        ev = Gtk.EventControllerKey()
        def _on_key(controller, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape: self.close(); return True
            return False
        ev.connect("key-pressed", _on_key); self.add_controller(ev)
        click_ev = Gtk.GestureClick()
        click_ev.connect("pressed", lambda *a: self.close()); self.add_controller(click_ev)
        self.set_child(overlay)


class ThemeTextEditDialog(Adw.Dialog):
    def __init__(self, file_path, parent_window):
        super().__init__(title=f"Edit: {file_path.name}")
        self.file_path = file_path; self.parent_window = parent_window
        self.set_content_width(650); self.set_content_height(500); self._build_ui()

    def _build_ui(self):
        tb = Adw.ToolbarView(); header = Adw.HeaderBar()
        lbl = Gtk.Label(label=self.file_path.name); lbl.add_css_class("bold")
        header.set_title_widget(lbl)
        save_btn = Gtk.Button(label="Save File", valign=Gtk.Align.CENTER)
        save_btn.add_css_class("suggested-action"); save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn); tb.add_top_bar(header)
        self.tv = Gtk.TextView(monospace=True); self.tv.set_wrap_mode(Gtk.WrapMode.NONE)
        self.tv.set_margin_start(10); self.tv.set_margin_end(10)
        self.tv.set_margin_top(10); self.tv.set_margin_bottom(10)
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f: content = f.read()
        except Exception as e:
            content = f"Error reading file: {str(e)}"; self.tv.set_editable(False)
        self.tv.get_buffer().set_text(content)
        sw = Gtk.ScrolledWindow(vexpand=True); sw.set_child(self.tv)
        tb.set_content(sw); self.set_child(tb)

    def _on_save(self, btn):
        buf = self.tv.get_buffer(); start, end = buf.get_bounds()
        text = buf.get_text(start, end, True)
        temp_fd, temp_path = tempfile.mkstemp()
        try:
            with open(temp_path, "w", encoding="utf-8") as f: f.write(text)
        finally:
            os.close(temp_fd)
        res = os.system(f"pkexec cp -f {temp_path} {self.file_path} && rm -f {temp_path}")
        if res == 0: self.parent_window.show_toast(f"Changes saved in {self.file_path.name}!"); self.close()
        else: self.parent_window.show_toast("Could not save (Permission required)")


class AdvancedSettingsDialog(Adw.Dialog):
    def __init__(self, parent_dialog, variables):
        super().__init__(title="Grub Customizer - Settings")
        self.parent_dialog = parent_dialog; self.variables = variables.copy()
        self.set_content_width(520); self.set_content_height(480); self._build_ui()

    def _build_ui(self):
        tb = Adw.ToolbarView(); header = Adw.HeaderBar()
        lbl = Gtk.Label(label="Advanced Settings"); lbl.add_css_class("bold"); header.set_title_widget(lbl)
        apply_btn = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        apply_btn.add_css_class("suggested-action"); apply_btn.connect("clicked", self._on_apply)
        header.pack_end(apply_btn); tb.add_top_bar(header)
        vbox = Gtk.Box(orientation=1, spacing=10)
        vbox.set_margin_start(16); vbox.set_margin_end(16); vbox.set_margin_top(12); vbox.set_margin_bottom(16)
        action_bar = Gtk.Box(spacing=8)
        add_btn = Gtk.Button(label="+ Add Variable"); add_btn.connect("clicked", self._on_add_variable)
        action_bar.append(add_btn)
        del_btn = Gtk.Button(label="- Remove Selected"); del_btn.connect("clicked", self._on_remove_selected)
        action_bar.append(del_btn); vbox.append(action_bar)
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.listbox = Gtk.ListBox(); self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list"); self.rows_map = {}; self._populate_list()
        sw.set_child(self.listbox); vbox.append(sw); tb.set_content(vbox); self.set_child(tb)

    def _populate_list(self):
        while True:
            row = self.listbox.get_row_at_index(0)
            if not row: break
            self.listbox.remove(row)
        self.rows_map.clear()
        for key in sorted(self.variables.keys()):
            info = self.variables[key]; row = Adw.ActionRow(title=key)
            chk = Gtk.CheckButton(valign=Gtk.Align.CENTER); chk.set_active(info["active"])
            chk.connect("toggled", self._on_checkbox_toggled, key); row.add_prefix(chk)
            entry = Gtk.Entry(text=info["value"], valign=Gtk.Align.CENTER); entry.set_hexpand(True)
            entry.connect("changed", self._on_entry_changed, key); row.add_suffix(entry)
            self.listbox.append(row); self.rows_map[row] = key

    def _on_checkbox_toggled(self, chk, key): self.variables[key]["active"] = chk.get_active()
    def _on_entry_changed(self, entry, key): self.variables[key]["value"] = entry.get_text()

    def _on_add_variable(self, btn):
        d = Adw.Dialog(title="New Variable"); d.set_content_width(320); d.set_content_height(180)
        vb = Gtk.Box(orientation=1, spacing=10)
        vb.set_margin_start(16); vb.set_margin_end(16); vb.set_margin_top(16); vb.set_margin_bottom(16)
        key_entry = Gtk.Entry(placeholder_text="GRUB_VARIABLE_NAME"); vb.append(key_entry)
        val_entry = Gtk.Entry(placeholder_text="value"); vb.append(val_entry)
        ok_btn = Gtk.Button(label="Add", valign=Gtk.Align.CENTER); ok_btn.add_css_class("suggested-action")
        def _add_done(*args):
            k = key_entry.get_text().strip().upper(); v = val_entry.get_text().strip()
            if k: self.variables[k] = {"value": v, "active": True}; self._populate_list(); d.close()
        ok_btn.connect("clicked", _add_done); vb.append(ok_btn); d.set_child(vb); safe_present(d, self)

    def _on_remove_selected(self, btn):
        row = self.listbox.get_selected_row()
        if row and row in self.rows_map: del self.variables[self.rows_map[row]]; self._populate_list()

    def _on_apply(self, btn):
        self.parent_dialog.defaults = self.variables.copy(); self.parent_dialog._update_from_defaults(); self.close()


class GrubCustomizerDialog(Adw.Dialog):
    def __init__(self, parent_window):
        super().__init__(title="Grub Customizer")
        self.parent_window = parent_window
        self.set_content_width(900); self.set_content_height(680)
        self.defaults = read_grub_defaults()
        # Deferred loading — polkit needs a VISIBLE window to show its auth dialog.
        # Loading here in __init__ (before present()) fails on Fedora because
        # the window is not on screen yet when pkexec tries to attach.
        self.raw_grub_info = None
        self.menu_entries = []
        self.installed_themes = ["(None/Default)"]
        self.theme_files_dir = None
        self._build_ui()
        self._show_loading_placeholder()
        # 300ms gives GTK time to map and render the window before pkexec runs
        GLib.timeout_add(300, self._start_grub_load_thread)

    def _show_loading_placeholder(self):
        while True:
            row = self.entry_listbox.get_row_at_index(0)
            if not row: break
            self.entry_listbox.remove(row)
        spinner = Gtk.Spinner(); spinner.start()
        row = Adw.ActionRow(title="Cargando entradas de arranque...")
        row.add_prefix(spinner); self.entry_listbox.append(row)

    def _start_grub_load_thread(self):
        """Called after window is fully on screen."""
        def _worker():
            try:
                raw_info = load_all_grub_info()
                GLib.idle_add(self._on_grub_data_loaded, raw_info, None)
            except Exception as e:
                GLib.idle_add(self._on_grub_data_loaded, None, e)
        threading.Thread(target=_worker, daemon=True).start()
        return False  # don't repeat

    def _on_grub_data_loaded(self, raw_info, error):
        """Runs on the GTK main thread — safe to update UI here."""
        if error is not None:
            while True:
                row = self.entry_listbox.get_row_at_index(0)
                if not row: break
                self.entry_listbox.remove(row)
            row = Adw.ActionRow(title="No se pudo cargar la configuración de GRUB", subtitle=str(error))
            row.set_icon_name("dialog-error-symbolic"); self.entry_listbox.append(row)
            self.parent_window.show_toast(str(error)); return False

        self.raw_grub_info = raw_info
        
        self.theme_contents = {}
        if self.raw_grub_info and "===GRUB_THEMES_CONTENT===" in self.raw_grub_info:
            parts = self.raw_grub_info.split("===GRUB_THEMES_CONTENT===")
            if len(parts) > 1:
                themes_content_block = parts[1].split("===BTRFS_CFG===")[0]
                for file_block in themes_content_block.split("===THEME_FILE:"):
                    if not file_block.strip(): continue
                    file_parts = file_block.split("\n", 1)
                    if len(file_parts) == 2:
                        theme_file = file_parts[0].strip()
                        self.theme_contents[theme_file] = file_parts[1]
                        
        self.menu_entries = parse_menu_entries_unified(self.raw_grub_info)
        self.installed_themes = get_installed_grub_themes(self.raw_grub_info)

        # Rebuild dropdowns with real data
        self.theme_dropdown.set_model(Gtk.StringList.new(self.installed_themes))
        cur_theme_path = self.defaults.get("GRUB_THEME", {}).get("value", "")
        if cur_theme_path:
            theme_name = Path(cur_theme_path).parent.name
            idx = self.installed_themes.index(theme_name) if theme_name in self.installed_themes else 0
            self.theme_dropdown.set_selected(idx)
        else:
            self.theme_dropdown.set_selected(0)

        self.default_os_dd.set_model(
            Gtk.StringList.new([e["title"] for e in self.menu_entries] + ["(Other...)"]))

        self._populate_entries_list()
        self._update_from_defaults()
        try:
            self._on_theme_dropdown_changed(self.theme_dropdown, None)
        except Exception as e:
            import sys; sys.stderr.write(f"[GTM] theme init error (non-fatal): {e}\n")
        return False

    def _build_ui(self):
        tb = Adw.ToolbarView(); header = Adw.HeaderBar()
        save_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save", valign=Gtk.Align.CENTER)
        save_btn.add_css_class("suggested-action"); save_btn.connect("clicked", self._on_save)
        header.pack_start(save_btn)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh", valign=Gtk.Align.CENTER)
        refresh_btn.connect("clicked", self._on_refresh); header.pack_start(refresh_btn)
        adv_btn = Gtk.Button(label="Advanced", tooltip_text="Advanced Settings", valign=Gtk.Align.CENTER)
        adv_btn.connect("clicked", self._on_advanced_settings); header.pack_end(adv_btn)
        tb.add_top_bar(header)
        self.stack = Adw.ViewStack()
        self._build_tab_list()
        self._build_tab_general()
        self._build_tab_appearance()
        switcher = Adw.ViewSwitcher(); switcher.set_stack(self.stack)
        header.set_title_widget(switcher)
        tb.set_content(self.stack); self.set_child(tb)

    def _build_tab_list(self):
        box = Gtk.Box(orientation=1, spacing=8)
        box.set_margin_start(16); box.set_margin_end(16); box.set_margin_top(12); box.set_margin_bottom(16)
        toolbar = Gtk.Box(spacing=6)
        del_btn = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Remove entry")
        del_btn.connect("clicked", self._on_list_remove); toolbar.append(del_btn)
        edit_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit entry")
        edit_btn.connect("clicked", self._on_list_edit); toolbar.append(edit_btn)
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add new entry")
        add_btn.connect("clicked", self._on_list_add); toolbar.append(add_btn)
        toolbar.append(Gtk.Separator(orientation=1))
        up_btn = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Move up")
        up_btn.connect("clicked", self._on_list_move_up); toolbar.append(up_btn)
        down_btn = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Move down")
        down_btn.connect("clicked", self._on_list_move_down); toolbar.append(down_btn)
        box.append(toolbar)
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.entry_listbox = Gtk.ListBox()
        self.entry_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.entry_listbox.add_css_class("boxed-list")
        self.entry_listbox.connect("row-activated", self._on_row_double_click)
        self._build_context_menu_popover()
        click_gesture = Gtk.GestureClick(); click_gesture.set_button(Gdk.BUTTON_SECONDARY)
        click_gesture.connect("pressed", self._on_listbox_right_click)
        self.entry_listbox.add_controller(click_gesture)
        sw.set_child(self.entry_listbox); box.append(sw)
        page = self.stack.add_titled(box, "list_config", "List Configuration")
        page.set_icon_name("view-list-symbolic")

    def _build_context_menu_popover(self):
        self.context_popover = Gtk.Popover(); self.context_popover.set_parent(self.entry_listbox)
        vb = Gtk.Box(orientation=1, spacing=4)
        vb.set_margin_start(4); vb.set_margin_end(4); vb.set_margin_top(4); vb.set_margin_bottom(4)
        actions = [
            ("Rename", self._on_ctx_rename), ("Edit", self._on_list_edit),
            ("Remove", self._on_list_remove), ("Move Up", self._on_list_move_up),
            ("Move Down", self._on_list_move_down), ("Create Submenu", self._on_ctx_create_submenu),
            ("Outdent", self._on_list_outdent), ("About the entry types...", self._on_ctx_about_types)
        ]
        self.popover_buttons = {}
        for name, callback in actions:
            btn = Gtk.Button(label=name); btn.set_has_frame(False); btn.set_halign(Gtk.Align.START)
            btn.connect("clicked", lambda b, cb=callback: (self.context_popover.popdown(), cb(None)))
            vb.append(btn); self.popover_buttons[name] = btn
        self.context_popover.set_child(vb)

    def _on_listbox_right_click(self, gesture, n_press, x, y):
        row = self.entry_listbox.get_row_at_y(y)
        if row:
            self.entry_listbox.select_row(row)
            idx = self._get_real_entry_idx(row.get_index())
            if idx != -1 and "Outdent" in self.popover_buttons:
                self.popover_buttons["Outdent"].set_visible(self.menu_entries[idx].get("is_submenu_item", False))
            rect = Gdk.Rectangle(); rect.x = int(x); rect.y = int(y); rect.width = 1; rect.height = 1
            self.context_popover.set_pointing_to(rect); self.context_popover.popup()

    def _on_ctx_rename(self, btn):
        row = self.entry_listbox.get_selected_row()
        if not row: return
        idx = self._get_real_entry_idx(row.get_index())
        if idx == -1: return
        entry = self.menu_entries[idx]
        d = Adw.Dialog(title="Rename Entry"); d.set_content_width(320); d.set_content_height(140)
        vb = Gtk.Box(orientation=1, spacing=8)
        vb.set_margin_start(16); vb.set_margin_end(16); vb.set_margin_top(16); vb.set_margin_bottom(16)
        entry_val = Gtk.Entry(text=entry["title"]); vb.append(entry_val)
        btn_ok = Gtk.Button(label="Save", valign=Gtk.Align.CENTER); btn_ok.add_css_class("suggested-action")
        def _save(*args):
            t = entry_val.get_text().strip()
            if t: entry["title"] = t; self._populate_entries_list(); self._update_appearance_preview()
            d.close()
        btn_ok.connect("clicked", _save); vb.append(btn_ok); d.set_child(vb); safe_present(d, self)

    def _on_ctx_create_submenu(self, btn):
        d = Adw.Dialog(title="Create Submenu"); d.set_content_width(320); d.set_content_height(140)
        vb = Gtk.Box(orientation=1, spacing=8)
        vb.set_margin_start(16); vb.set_margin_end(16); vb.set_margin_top(16); vb.set_margin_bottom(16)
        entry_val = Gtk.Entry(placeholder_text="Submenu Name"); vb.append(entry_val)
        btn_ok = Gtk.Button(label="Create", valign=Gtk.Align.CENTER); btn_ok.add_css_class("suggested-action")
        def _create(*args):
            t = entry_val.get_text().strip()
            if t:
                self.menu_entries.append({"title": t, "type": "submenu", "code": f"submenu '{t}' {{\n}}",
                                          "is_submenu_item": False, "collapsed": False})
                self._populate_entries_list(); self._update_appearance_preview()
            d.close()
        btn_ok.connect("clicked", _create); vb.append(btn_ok); d.set_child(vb); safe_present(d, self)

    def _on_ctx_about_types(self, btn):
        d = Adw.MessageDialog(
            heading="Acerca de los tipos de entradas",
            body="En GRUB Customizer, puedes catalogar y editar diferentes tipos de entradas de arranque:\n\n"
                 "\u2022 Linux: Carga kernels nativos de GNU/Linux.\n"
                 "\u2022 Cargador en cadena: Lanza otros gestores de arranque (como Windows Boot Manager).\n"
                 "\u2022 Test de memoria: Inicia suites de diagnóstico como memtest86+.\n"
                 "\u2022 Custom: Te da total libertad para escribir scripts manuales en el lenguaje de shell de GRUB.")
        d.add_response("ok", "Entendido"); safe_present(d, self)

    def _get_real_entry_idx(self, vis_idx):
        vis_counter = 0; skip_items = False
        for j, entry in enumerate(self.menu_entries):
            is_sub = entry.get("is_submenu_item", False)
            if is_sub and skip_items: continue
            if not is_sub: skip_items = False
            if entry["type"] == "submenu" and entry.get("collapsed", False): skip_items = True
            if vis_counter == vis_idx: return j
            vis_counter += 1
        return -1

    def _populate_entries_list(self):
        while True:
            row = self.entry_listbox.get_row_at_index(0)
            if not row: break
            self.entry_listbox.remove(row)
        collapsed_depths = []
        for i, entry in enumerate(self.menu_entries):
            is_sub = entry.get("is_submenu_item", False)
            depth = entry.get("submenu_depth", 1 if is_sub else 0)
            collapsed_depths = [dep for dep in collapsed_depths if dep < depth]
            if collapsed_depths: continue
            if entry["type"] == "submenu" and entry.get("collapsed", False): collapsed_depths.append(depth)
            title_text = entry["title"].strip(" \u21b3 ")
            if depth > 0: title_text = "   " * depth + "\u21b3 " + title_text
            row = Adw.ActionRow(title=GLib.markup_escape_text(title_text)); row.set_selectable(True)
            t = entry["type"]; icon_name = "applications-system-symbolic"; desc = "Entrada de arranque"
            if t == "submenu":
                icon_name = "folder-symbolic"; desc = "Submenú"
                arrow_icon = "pan-down-symbolic" if not entry.get("collapsed", False) else "pan-end-symbolic"
                toggle_btn = Gtk.Button(icon_name=arrow_icon); toggle_btn.set_has_frame(False)
                toggle_btn.set_valign(Gtk.Align.CENTER)
                toggle_btn.connect("clicked", self._on_toggle_submenu_collapse, i); row.add_suffix(toggle_btn)
            elif t == "script": icon_name = "preferences-system-symbolic"; desc = "Entrada de script"
            elif t == "windows": icon_name = "computer-symbolic"; desc = "Partición Windows"
            row.set_icon_name(icon_name); row.set_subtitle(desc)
            self.entry_listbox.append(row)

    def _on_toggle_submenu_collapse(self, btn, idx):
        self.menu_entries[idx]["collapsed"] = not self.menu_entries[idx].get("collapsed", False)
        self._populate_entries_list()

    def _on_row_double_click(self, listbox, row):
        if row: self.entry_listbox.select_row(row); self._on_list_edit(None)

    def _on_list_remove(self, btn):
        row = self.entry_listbox.get_selected_row()
        if row:
            idx = self._get_real_entry_idx(row.get_index())
            if idx != -1: del self.menu_entries[idx]; self._populate_entries_list(); self._update_appearance_preview()

    def _on_list_edit(self, btn):
        row = self.entry_listbox.get_selected_row()
        if not row: return
        idx = self._get_real_entry_idx(row.get_index())
        if idx == -1: return
        d = EntryEditorDialog(self.menu_entries[idx],
            lambda: (self._populate_entries_list(), self._update_appearance_preview()))
        safe_present(d, self)

    def _on_list_add(self, btn):
        new_entry = {"title": "Nueva Entrada", "type": "linux", "code": "", "is_submenu_item": False}
        def _on_save():
            self.menu_entries.append(new_entry); self._populate_entries_list(); self._update_appearance_preview()
        safe_present(EntryEditorDialog(new_entry, _on_save), self)

    def _get_entry_block(self, idx):
        if idx < 0 or idx >= len(self.menu_entries): return []
        entry = self.menu_entries[idx]; block = [entry]
        if entry.get("type") == "submenu":
            depth = entry.get("submenu_depth", 0)
            for k in range(idx + 1, len(self.menu_entries)):
                child = self.menu_entries[k]
                child_depth = child.get("submenu_depth", 1 if child.get("is_submenu_item", False) else 0)
                if child_depth > depth: block.append(child)
                else: break
        return block

    def _on_list_move_up(self, btn):
        row = self.entry_listbox.get_selected_row()
        if not row: return
        vis_idx = row.get_index(); idx = self._get_real_entry_idx(vis_idx)
        if idx <= 0: return
        block = self._get_entry_block(idx); entry = block[0]
        depth = entry.get("submenu_depth", 1 if entry.get("is_submenu_item") else 0)
        pred_idx = idx - 1; pred = self.menu_entries[pred_idx]
        pred_depth = pred.get("submenu_depth", 1 if pred.get("is_submenu_item") else 0)
        if pred.get("type") == "submenu" and pred_depth == depth - 1:
            for item in block:
                nd = max(0, item.get("submenu_depth", 0) - 1)
                item["submenu_depth"] = nd; item["is_submenu_item"] = (nd > 0)
            for _ in range(len(block)): self.menu_entries.pop(idx)
            for item in reversed(block): self.menu_entries.insert(pred_idx, item)
        elif pred_depth > depth:
            for item in block:
                nd = item.get("submenu_depth", 0) + 1; item["submenu_depth"] = nd; item["is_submenu_item"] = True
            for _ in range(len(block)): self.menu_entries.pop(idx)
            for item in reversed(block): self.menu_entries.insert(pred_idx, item)
        elif pred.get("type") == "submenu" and pred_depth >= depth:
            for item in block:
                nd = item.get("submenu_depth", 0) + 1; item["submenu_depth"] = nd; item["is_submenu_item"] = True
            for _ in range(len(block)): self.menu_entries.pop(idx)
            for item in reversed(block): self.menu_entries.insert(pred_idx + 1, item)
        else:
            for _ in range(len(block)): self.menu_entries.pop(idx)
            for item in reversed(block): self.menu_entries.insert(idx - 1, item)
        self._populate_entries_list()
        header_title = block[0]["title"]
        for idx_r in range(len(self.menu_entries)):
            r = self.entry_listbox.get_row_at_index(idx_r)
            if r and hasattr(r, 'get_title') and r.get_title().strip(" \u21b3 ") == header_title.strip(" \u21b3 "):
                self.entry_listbox.select_row(r); break
        self._update_appearance_preview()

    def _on_list_move_down(self, btn):
        row = self.entry_listbox.get_selected_row()
        if not row: return
        vis_idx = row.get_index(); idx = self._get_real_entry_idx(vis_idx)
        if idx == -1: return
        block = self._get_entry_block(idx); entry = block[0]
        depth = entry.get("submenu_depth", 1 if entry.get("is_submenu_item") else 0)
        next_idx = idx + len(block)
        if next_idx >= len(self.menu_entries): return
        nxt = self.menu_entries[next_idx]
        nxt_depth = nxt.get("submenu_depth", 1 if nxt.get("is_submenu_item") else 0)
        nxt_block = self._get_entry_block(next_idx)
        if nxt_depth < depth:
            for item in block:
                nd = max(0, item.get("submenu_depth", 0) - 1)
                item["submenu_depth"] = nd; item["is_submenu_item"] = (nd > 0)
            for _ in range(len(block)): self.menu_entries.pop(idx)
            insert_pos = idx + len(nxt_block)
            for item in reversed(block): self.menu_entries.insert(insert_pos, item)
        elif nxt.get("type") == "submenu" and nxt_depth >= depth:
            for item in block:
                nd = item.get("submenu_depth", 0) + 1; item["submenu_depth"] = nd; item["is_submenu_item"] = True
            for _ in range(len(block)): self.menu_entries.pop(idx)
            for item in reversed(block): self.menu_entries.insert(idx + 1, item)
        else:
            for _ in range(len(block)): self.menu_entries.pop(idx)
            insert_pos = idx + len(nxt_block)
            for item in reversed(block): self.menu_entries.insert(insert_pos, item)
        self._populate_entries_list()
        header_title = block[0]["title"]
        for idx_r in range(len(self.menu_entries)):
            r = self.entry_listbox.get_row_at_index(idx_r)
            if r and hasattr(r, 'get_title') and r.get_title().strip(" \u21b3 ") == header_title.strip(" \u21b3 "):
                self.entry_listbox.select_row(r); break
        self._update_appearance_preview()

    def _on_list_indent(self, btn):
        row = self.entry_listbox.get_selected_row()
        if not row: return
        vis_idx = row.get_index(); idx = self._get_real_entry_idx(vis_idx)
        if idx == -1: return
        entry = self.menu_entries[idx]
        entry["is_submenu_item"] = True; entry["submenu_depth"] = entry.get("submenu_depth", 0) + 1
        for item in self._get_entry_block(idx)[1:]:
            item["submenu_depth"] = item.get("submenu_depth", 0) + 1; item["is_submenu_item"] = True
        self._populate_entries_list()
        focus_row = self.entry_listbox.get_row_at_index(vis_idx)
        if focus_row: self.entry_listbox.select_row(focus_row)
        self._update_appearance_preview()

    def _on_list_outdent(self, btn):
        row = self.entry_listbox.get_selected_row()
        if not row: return
        vis_idx = row.get_index(); idx = self._get_real_entry_idx(vis_idx)
        if idx == -1: return
        entry = self.menu_entries[idx]
        nd = max(0, entry.get("submenu_depth", 0) - 1)
        entry["submenu_depth"] = nd; entry["is_submenu_item"] = (nd > 0)
        for item in self._get_entry_block(idx)[1:]:
            cd = max(0, item.get("submenu_depth", 0) - 1)
            item["submenu_depth"] = cd; item["is_submenu_item"] = (cd > 0)
        self._populate_entries_list()
        focus_row = self.entry_listbox.get_row_at_index(vis_idx)
        if focus_row: self.entry_listbox.select_row(focus_row)
        self._update_appearance_preview()

    def _build_tab_general(self):
        vbox = Gtk.Box(orientation=1, spacing=14)
        vbox.set_margin_start(16); vbox.set_margin_end(16); vbox.set_margin_top(16); vbox.set_margin_bottom(16)
        bg_boot = Adw.PreferencesGroup(title="Default Entry")
        self.radio_predef = Gtk.CheckButton(label="Predefined:"); self.radio_predef.set_active(True)
        # Placeholder model — replaced with real data in _on_grub_data_loaded
        self.default_os_dd = Gtk.DropDown.new_from_strings(["(Cargando...)"])
        self.default_os_dd.connect("notify::selected", self._on_default_os_changed)
        self.default_literal_entry = Gtk.Entry(text="0")
        self.default_literal_entry.set_size_request(80, -1); self.default_literal_entry.set_sensitive(False)
        row_predef = Adw.ActionRow()
        row_predef.add_prefix(self.radio_predef); row_predef.add_suffix(self.default_os_dd)
        row_predef.add_suffix(self.default_literal_entry); bg_boot.add(row_predef)
        self.radio_last = Gtk.CheckButton(label="Use last booted entry"); self.radio_last.set_group(self.radio_predef)
        row_last = Adw.ActionRow(); row_last.add_prefix(self.radio_last); bg_boot.add(row_last)
        vbox.append(bg_boot)
        bg_vis = Adw.PreferencesGroup(title="Visibility")
        self.chk_show_menu = Gtk.CheckButton(label="Show boot menu", valign=Gtk.Align.CENTER)
        row_show = Adw.ActionRow(); row_show.add_prefix(self.chk_show_menu); bg_vis.add(row_show)
        self.chk_os_prober = Gtk.CheckButton(label="Look for other operating systems", valign=Gtk.Align.CENTER)
        row_prob = Adw.ActionRow(); row_prob.add_prefix(self.chk_os_prober); bg_vis.add(row_prob)
        self.chk_timeout = Gtk.CheckButton(label="Boot default entry in", valign=Gtk.Align.CENTER)
        self.timeout_spinner = Gtk.SpinButton.new_with_range(0, 99, 1); self.timeout_spinner.set_valign(Gtk.Align.CENTER)
        row_time = Adw.ActionRow(); row_time.add_prefix(self.chk_timeout); row_time.add_suffix(self.timeout_spinner)
        row_time.add_suffix(Gtk.Label(label="seconds", valign=Gtk.Align.CENTER)); bg_vis.add(row_time)
        vbox.append(bg_vis)
        bg_kern = Adw.PreferencesGroup(title="Kernel parameters")
        self.kernel_entry = Gtk.Entry(placeholder_text="quiet splash")
        self.kernel_entry.set_hexpand(True)
        self.kernel_entry.set_valign(Gtk.Align.CENTER)
        row_kern = Adw.ActionRow(title="Parameters:")
        row_kern.set_child(self.kernel_entry)
        bg_kern.add(row_kern)
        vbox.append(bg_kern)
        bg_rec = Adw.PreferencesGroup(title="Recovery")
        self.chk_recovery = Gtk.CheckButton(label="Generate recovery entries", valign=Gtk.Align.CENTER)
        row_rec = Adw.ActionRow(); row_rec.add_prefix(self.chk_recovery); bg_rec.add(row_rec); vbox.append(bg_rec)
        self._update_from_defaults()
        sw = Gtk.ScrolledWindow(vexpand=True); sw.set_child(vbox)
        page = self.stack.add_titled(sw, "general_config", "General Settings")
        page.set_icon_name("preferences-system-symbolic")

    def _on_default_os_changed(self, dd, spec):
        self.default_literal_entry.set_sensitive(dd.get_selected() == len(self.menu_entries))

    def _update_from_defaults(self):
        def_entry = self.defaults.get("GRUB_DEFAULT", {}).get("value", "0")
        if def_entry == "saved":
            self.radio_last.set_active(True)
        else:
            self.radio_predef.set_active(True)
            try:
                idx = int(def_entry)
                if 0 <= idx < len(self.menu_entries):
                    self.default_os_dd.set_selected(idx); self.default_literal_entry.set_text(str(idx))
                else:
                    self.default_os_dd.set_selected(len(self.menu_entries) if self.menu_entries else 0)
                    self.default_literal_entry.set_text(def_entry)
            except ValueError:
                self.default_os_dd.set_selected(len(self.menu_entries) if self.menu_entries else 0)
                self.default_literal_entry.set_text(def_entry)
        timeout = self.defaults.get("GRUB_TIMEOUT", {}).get("value", "5")
        try:
            val = int(timeout); self.timeout_spinner.set_value(val); self.chk_timeout.set_active(val >= 0)
        except ValueError: self.timeout_spinner.set_value(5)
        self.chk_show_menu.set_active(self.defaults.get("GRUB_TIMEOUT_STYLE", {}).get("value", "menu") == "menu")
        prob = self.defaults.get("GRUB_DISABLE_OS_PROBER", {}).get("value", "false")
        self.chk_os_prober.set_active(prob == "false" or not self.defaults.get("GRUB_DISABLE_OS_PROBER", {}).get("active", True))
        rec = self.defaults.get("GRUB_DISABLE_RECOVERY", {}).get("value", "false")
        self.chk_recovery.set_active(rec == "false" or not self.defaults.get("GRUB_DISABLE_RECOVERY", {}).get("active", True))
        self.kernel_entry.set_text(self.defaults.get("GRUB_CMDLINE_LINUX", {}).get("value", ""))

    def _build_tab_appearance(self):
        hbox = Gtk.Box(orientation=0, spacing=12)
        hbox.set_margin_start(16); hbox.set_margin_end(16); hbox.set_margin_top(16); hbox.set_margin_bottom(16)
        left_box = Gtk.Box(orientation=1, spacing=10); left_box.set_size_request(280, -1)
        bg_opt = Adw.PreferencesGroup(title="Screen options")
        self.chk_res = Gtk.CheckButton(label="Custom resolution", valign=Gtk.Align.CENTER)
        self.res_dd = Gtk.DropDown.new_from_strings(["auto", "1920x1080", "1280x720", "1024x768", "800x600"])
        row_res = Adw.ActionRow(); row_res.add_prefix(self.chk_res); row_res.add_suffix(self.res_dd); bg_opt.add(row_res)
        cur_gfx = self.defaults.get("GRUB_GFXMODE", {}).get("value", "auto")
        self.chk_res.set_active(cur_gfx not in ("auto", ""))
        resolutions = ["1920x1080", "1280x720", "1024x768", "800x600"]
        self.res_dd.set_selected(resolutions.index(cur_gfx) + 1 if cur_gfx in resolutions else 0)
        self.theme_variant_row = Adw.ActionRow(title="Theme resolution variant:")
        self.theme_variant_dd = Gtk.DropDown.new_from_strings(["(Default theme.txt)"])
        self.theme_variant_dd.connect("notify::selected", lambda *a: self._update_appearance_preview())
        self.theme_variant_row.add_suffix(self.theme_variant_dd); self.theme_variant_row.set_visible(False)
        bg_opt.add(self.theme_variant_row)
        self.theme_selector_row = Adw.ActionRow(title="Theme:")
        # Placeholder — replaced in _on_grub_data_loaded
        self.theme_dropdown = Gtk.DropDown.new_from_strings(["(None/Default)"])
        self.theme_selector_row.add_suffix(self.theme_dropdown); bg_opt.add(self.theme_selector_row)
        left_box.append(bg_opt)
        bg_files = Adw.PreferencesGroup(title="Theme contents")
        files_control = Gtk.Box(spacing=8)
        files_add = Gtk.Button(label="+ Add"); files_add.connect("clicked", self._on_add_theme_file); files_control.append(files_add)
        files_del = Gtk.Button(label="-"); files_del.connect("clicked", self._on_del_theme_file); files_control.append(files_del)
        if hasattr(bg_files, "set_header_suffix"): bg_files.set_header_suffix(files_control)
        elif hasattr(bg_files, "add_header_suffix"): bg_files.add_header_suffix(files_control)
        sw_files = Gtk.ScrolledWindow(vexpand=True); sw_files.set_size_request(-1, 200)
        self.files_listbox = Gtk.ListBox(); self.files_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.files_listbox.add_css_class("boxed-list"); self.files_listbox.connect("row-selected", self._on_file_selected)
        sw_files.set_child(self.files_listbox); bg_files.add(sw_files); left_box.append(bg_files)
        hbox.append(left_box)
        preview_container = Gtk.Box(orientation=1, spacing=6, hexpand=True, vexpand=True)
        preview_header = Gtk.Box(orientation=0, spacing=6)
        lbl_preview = Gtk.Label(label="Preview", xalign=0); lbl_preview.add_css_class("bold"); preview_header.append(lbl_preview)
        self.chk_hide_menu_preview = Gtk.CheckButton(label="Hide menu", valign=Gtk.Align.CENTER)
        self.chk_hide_menu_preview.connect("toggled", self._on_toggle_menu_preview)
        self.chk_hide_menu_preview.set_margin_end(12); self.chk_hide_menu_preview.set_visible(False)
        preview_header.append(self.chk_hide_menu_preview)
        fs_btn = Gtk.Button(icon_name="view-fullscreen-symbolic", tooltip_text="Fullscreen live preview")
        fs_btn.set_halign(Gtk.Align.END); fs_btn.connect("clicked", self._on_fullscreen_preview)
        preview_header.append(fs_btn); preview_container.append(preview_header)
        preview_frame = Gtk.Frame(hexpand=True, vexpand=True); preview_frame.add_css_class("theme-thumb-frame")
        self.preview_overlay = Gtk.Overlay()
        self.preview_bg_picture = Gtk.Picture(); self.preview_bg_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.preview_overlay.set_child(self.preview_bg_picture)
        self.preview_box = Gtk.Box(orientation=1, spacing=10)
        self.preview_box.set_valign(Gtk.Align.CENTER); self.preview_box.set_halign(Gtk.Align.CENTER)
        self.preview_box.set_size_request(400, 240); self.preview_box.add_css_class("card")
        self.preview_box.set_opacity(0.9); self.preview_box.set_visible(False)
        self.preview_box.set_margin_start(16); self.preview_box.set_margin_end(16)
        self.preview_box.set_margin_top(16); self.preview_box.set_margin_bottom(16)
        self.preview_title = Gtk.Label(label="GRUB Bootloader Menu", xalign=0.5)
        self.preview_title.add_css_class("welcome-title"); self.preview_box.append(self.preview_title)
        self.preview_scroller = Gtk.ScrolledWindow(vexpand=True); self.preview_scroller.set_size_request(380, 140)
        self.preview_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.preview_entries_box = Gtk.ListBox()
        self.preview_entries_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.preview_entries_box.add_css_class("grub-preview-entries")
        css_provider = Gtk.CssProvider()
        css_text = (
            ".grub-preview-entries { background: transparent; background-color: transparent; border: none; box-shadow: none; }"
            ".grub-preview-entries listrow { background: transparent; background-color: transparent; border: none; padding: 4px 8px; }"
            ".grub-preview-entries listrow:selected { background: rgba(255,255,255,0.18); color: #ffffff; border: 1px solid rgba(255,255,255,0.35); border-radius: 4px; }"
        )
        if hasattr(css_provider, "load_from_string"): css_provider.load_from_string(css_text)
        else: css_provider.load_from_data(css_text.encode('utf-8'))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.preview_scroller.set_child(self.preview_entries_box); self.preview_box.append(self.preview_scroller)
        self.preview_timeout_lbl = Gtk.Label(label="Booting in 5 seconds...", xalign=0.5)
        self.preview_box.append(self.preview_timeout_lbl)
        self.preview_overlay.add_overlay(self.preview_box)
        preview_frame.set_child(self.preview_overlay); preview_container.append(preview_frame)
        hbox.append(preview_container)
        page = self.stack.add_titled(hbox, "appearance_config", "Appearance Settings")
        page.set_icon_name("preferences-desktop-appearance-symbolic")
        self.theme_dropdown.connect("notify::selected", self._on_theme_dropdown_changed)

    def _on_toggle_menu_preview(self, chk):
        self.preview_box.set_visible(not chk.get_active())

    def _on_theme_dropdown_changed(self, dd, spec):
        sel = dd.get_selected()
        if sel >= len(self.installed_themes): return
        theme_name = self.installed_themes[sel]
        while True:
            row = self.files_listbox.get_row_at_index(0)
            if not row: break
            self.files_listbox.remove(row)
        self.theme_files_dir = None
        if sel > 0:
            p_tmp = Path(f"/tmp/gtm_themes/{theme_name}")
            p1 = Path(f"/boot/grub/themes/{theme_name}")
            p2 = Path(f"/boot/grub2/themes/{theme_name}")
            theme_base = p_tmp if _safe_exists(p_tmp) else (p1 if _safe_exists(p1) else p2)
            self.theme_files_dir = find_theme_root(theme_base)
        variants = []
        if self.theme_files_dir and _safe_exists(self.theme_files_dir):
            files_to_list = []
            for child in sorted(_safe_iterdir(self.theme_files_dir)):
                try:
                    is_f = _safe_is_file(child); is_d = _safe_is_dir(child)
                except OSError:
                    continue
                if is_f:
                    files_to_list.append((child, child.name))
                    if child.suffix.lower() in [".txt", ".cfg"] and "theme" in child.name.lower():
                        variants.append(child.name)
                elif is_d and child.name.lower() in ["icons", "icon"]:
                    for subchild in sorted(_safe_iterdir(child)):
                        try:
                            if _safe_is_file(subchild):
                                files_to_list.append((subchild, f"{child.name}/{subchild.name}"))
                        except OSError:
                            pass
            for path, display_name in files_to_list:
                row = Adw.ActionRow(title=display_name); row._path = path
                ext = path.suffix.lower()
                if ext in [".png", ".jpg", ".jpeg"]:
                    try: img_widget = Gtk.Image.new_from_file(str(path))
                    except Exception: img_widget = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
                elif ext in [".txt", ".cfg", ".conf"]: img_widget = Gtk.Image.new_from_icon_name("text-x-generic-symbolic")
                elif ext in [".pf2", ".ttf", ".otf"]: img_widget = Gtk.Image.new_from_icon_name("font-x-generic-symbolic")
                else: img_widget = Gtk.Image.new_from_icon_name("document-open-recent-symbolic")
                img_widget.set_pixel_size(18); row.add_prefix(img_widget)
                self.files_listbox.append(row)
        variants = sorted(list(set(variants)))
        if len(variants) > 1:
            self.theme_variant_dd.set_model(Gtk.StringList.new(variants))
            cur_theme_val = self.defaults.get("GRUB_THEME", {}).get("value", "")
            if cur_theme_val:
                act = Path(cur_theme_val).name
                if act in variants: self.theme_variant_dd.set_selected(variants.index(act))
            self.theme_variant_row.set_visible(True)
        else:
            self.theme_variant_row.set_visible(False)
        self._update_appearance_preview()

    def _on_file_selected(self, listbox, row):
        if not row or not hasattr(row, '_path'): return
        path = row._path
        if path.suffix.lower() in [".png", ".jpg", ".jpeg"]: self._load_preview_image(str(path))
        elif path.suffix.lower() in [".txt", ".cfg", ".html", ".sh", ".py", ".theme"]:
            safe_present(ThemeTextEditDialog(path, self.parent_window), self)

    def _on_add_theme_file(self, btn):
        if not self.theme_files_dir:
            self.parent_window.show_toast("Please select an active theme first"); return
        dialog = Gtk.FileDialog(title="Add File to Theme")
        def _on_selected(dialog, result):
            try:
                gfile = dialog.open_finish(result)
                if gfile:
                    src = gfile.get_path()
                    if os.system(f"pkexec cp {src} {self.theme_files_dir / Path(src).name}") == 0:
                        self._on_theme_dropdown_changed(self.theme_dropdown, None)
            except Exception: pass
        dialog.open(self.get_root(), None, _on_selected)

    def _on_del_theme_file(self, btn):
        row = self.files_listbox.get_selected_row()
        if not row or not hasattr(row, '_path') or not self.theme_files_dir: return
        if os.system(f"pkexec rm -f {row._path}") == 0:
            self._on_theme_dropdown_changed(self.theme_dropdown, None)

    def _update_appearance_preview(self):
        active_variant = "theme.txt"
        if self.theme_variant_row.get_visible():
            sel_v = self.theme_variant_dd.get_selected()
            model = self.theme_variant_dd.get_model()
            if model and sel_v < model.get_n_items(): active_variant = model.get_string(sel_v)
        theme_config = parse_theme_style(self.theme_files_dir, active_variant, getattr(self, 'theme_contents', None))
        bg_path = None
        bg_file_name = theme_config.get("desktop-image", "background.png")
        if self.theme_files_dir:
            p_configured = self.theme_files_dir / bg_file_name
            if _safe_exists(p_configured): bg_path = str(p_configured)
            else:
                for ext in [".png", ".jpg", ".jpeg"]:
                    p = self.theme_files_dir / f"background{ext}"
                    if _safe_exists(p): bg_path = str(p); break
        if bg_path: self._load_preview_image(bg_path)
        else: self.preview_bg_picture.set_paintable(None)
        title_font = "Sans Bold 14"; item_font = "Sans 11"; sel_font = "Sans Bold 11"; timeout_font = "Sans 10"
        title_label = GLib.markup_escape_text(theme_config.get("title-text", "GRUB Bootloader Menu"))
        title_color = theme_config.get("title-color", "#ffffff")
        if title_color:
            self.preview_title.set_markup(f"<span font_desc='{title_font}' foreground='{title_color}'>{GLib.markup_escape_text(title_label)}</span>")
        else:
            self.preview_title.set_markup(f"<span font_desc='{title_font}'>{GLib.markup_escape_text(title_label)}</span>")
        while True:
            row = self.preview_entries_box.get_row_at_index(0)
            if not row: break
            self.preview_entries_box.remove(row)
        item_color = theme_config.get("item-color", "#cccccc")
        sel_color = theme_config.get("selected-item-color", "#ffffff")
        skip_items = False
        for i, entry in enumerate(self.menu_entries):
            is_sub = entry.get("is_submenu_item", False)
            if is_sub and skip_items: continue
            if not is_sub: skip_items = False
            if entry["type"] == "submenu" and entry.get("collapsed", False): skip_items = True
            title_text = entry["title"]
            if is_sub: title_text = "   \u21b3 " + title_text.strip(" \u21b3 ")
            title_escaped = GLib.markup_escape_text(title_text)
            box = Gtk.Box(spacing=10)
            custom_icon = find_grub_entry_icon(self.theme_files_dir, entry)
            if custom_icon: img = Gtk.Image.new_from_file(custom_icon)
            else:
                icon_name = "applications-system-symbolic"; t = entry["type"]
                if t == "submenu": icon_name = "folder-symbolic"
                elif t == "script": icon_name = "preferences-system-symbolic"
                elif t == "windows": icon_name = "computer-symbolic"
                img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(16)
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup(f"<span font_desc='{item_font}' foreground='{item_color}'>{title_escaped}</span>")
            box.append(img); box.append(lbl)
            row = Gtk.ListBoxRow(); row.set_child(box); row._lbl = lbl; row._txt = title_escaped
            self.preview_entries_box.append(row)
        def _on_preview_sel(lb, row):
            for r in lb:
                if hasattr(r, '_lbl'):
                    txt_escaped = GLib.markup_escape_text(r._txt)
                    if r == row: r._lbl.set_markup(f"<span font_desc='{sel_font}' foreground='{sel_color}'><b>{txt_escaped}</b></span>")
                    else: r._lbl.set_markup(f"<span font_desc='{item_font}' foreground='{item_color}'>{txt_escaped}</span>")
        self.preview_entries_box.connect("row-selected", _on_preview_sel)
        first = self.preview_entries_box.get_row_at_index(0)
        if first: self.preview_entries_box.select_row(first)
        seconds = int(self.timeout_spinner.get_value()) if hasattr(self, 'timeout_spinner') else 5
        timeout_text = theme_config.get("timeout-text", "Booting in %d seconds...")
        if "%d" in timeout_text:
            try: timeout_text = timeout_text % seconds
            except TypeError: pass
        timeout_color = theme_config.get("timeout-color", "#aaaaaa")
        self.preview_timeout_lbl.set_markup(
            f"<span font_desc='{timeout_font}' foreground='{timeout_color}'>{GLib.markup_escape_text(timeout_text)}</span>")

    def _load_preview_image(self, path):
        try: self.preview_bg_picture.set_file(Gio.File.new_for_path(path))
        except Exception: pass

    def _on_fullscreen_preview(self, btn):
        active_variant = "theme.txt"
        if self.theme_variant_row.get_visible():
            sel_v = self.theme_variant_dd.get_selected()
            model = self.theme_variant_dd.get_model()
            if model and sel_v < model.get_n_items(): active_variant = model.get_string(sel_v)
        theme_config = parse_theme_style(self.theme_files_dir, active_variant, getattr(self, 'theme_contents', None))
        bg_path = None
        bg_file_name = theme_config.get("desktop-image", "background.png")
        if self.theme_files_dir:
            p_configured = self.theme_files_dir / bg_file_name
            if _safe_exists(p_configured): bg_path = str(p_configured)
            else:
                for ext in [".png", ".jpg", ".jpeg"]:
                    p = self.theme_files_dir / f"background{ext}"
                    if _safe_exists(p): bg_path = str(p); break
        seconds = int(self.timeout_spinner.get_value()) if hasattr(self, 'timeout_spinner') else 5
        FullscreenPreviewWindow(bg_path, self.menu_entries, seconds, theme_config, False, self.theme_files_dir).present()

    def _on_advanced_settings(self, btn):
        safe_present(AdvancedSettingsDialog(self, self.defaults), self)

    def _on_refresh(self, btn):
        self.defaults = read_grub_defaults()
        self._show_loading_placeholder()
        GLib.timeout_add(100, self._start_grub_load_thread)
        self.parent_window.show_toast("Recargando configuración de GRUB...")

    def _on_save(self, btn):
        if not self.menu_entries: self.parent_window.show_toast("No hay entradas cargadas todavía."); return
        if self.radio_last.get_active():
            self.defaults["GRUB_DEFAULT"] = {"value": "saved", "active": True}
            self.defaults["GRUB_SAVEDEFAULT"] = {"value": "true", "active": True}
        else:
            sel_idx = self.default_os_dd.get_selected()
            if sel_idx == len(self.menu_entries):
                self.defaults["GRUB_DEFAULT"] = {"value": self.default_literal_entry.get_text(), "active": True}
            else: self.defaults["GRUB_DEFAULT"] = {"value": str(sel_idx), "active": True}
        self.defaults["GRUB_TIMEOUT"] = {"value": str(int(self.timeout_spinner.get_value())) if self.chk_timeout.get_active() else "-1", "active": True}
        self.defaults["GRUB_TIMEOUT_STYLE"] = {"value": "menu" if self.chk_show_menu.get_active() else "hidden", "active": True}
        self.defaults["GRUB_DISABLE_OS_PROBER"] = {"value": "false" if self.chk_os_prober.get_active() else "true", "active": True}
        self.defaults["GRUB_DISABLE_RECOVERY"] = {"value": "false" if self.chk_recovery.get_active() else "true", "active": not self.chk_recovery.get_active()}
        self.defaults["GRUB_CMDLINE_LINUX"] = {"value": self.kernel_entry.get_text(), "active": True}
        theme_sel = self.theme_dropdown.get_selected()
        if 0 < theme_sel < len(self.installed_themes):
            theme_name = self.installed_themes[theme_sel]
            active_variant = "theme.txt"
            if self.theme_variant_row.get_visible():
                sel_v = self.theme_variant_dd.get_selected()
                model = self.theme_variant_dd.get_model()
                if model and sel_v < model.get_n_items(): active_variant = model.get_string(sel_v)
            theme_path = f"/boot/grub/themes/{theme_name}/{active_variant}"
            if not _safe_exists(Path(theme_path)): theme_path = f"/boot/grub2/themes/{theme_name}/{active_variant}"
            self.defaults["GRUB_THEME"] = {"value": theme_path, "active": True}
            self.defaults["GRUB_TERMINAL"] = {"value": "console", "active": False}
            self.defaults["GRUB_TERMINAL_OUTPUT"] = {"value": "gfxterm", "active": True}
        else: self.defaults["GRUB_THEME"] = {"value": "", "active": False}
        if self.chk_res.get_active():
            res_val = ["auto", "1920x1080", "1280x720", "1024x768", "800x600"][self.res_dd.get_selected()]
            self.defaults["GRUB_GFXMODE"] = {"value": res_val, "active": True}
        else: self.defaults["GRUB_GFXMODE"] = {"value": "auto", "active": False}
        temp_lines = []
        for key, info in self.defaults.items():
            val = info["value"]; prefix = "" if info["active"] else "#"
            if val or not info["active"]: temp_lines.append(f'{prefix}{key}="{val}"\n')
        temp_fd, temp_path = tempfile.mkstemp()
        try:
            with open(temp_path, "w") as f: f.writelines(temp_lines)
        finally: os.close(temp_fd)
        menu_text = "#!/bin/sh\nexec tail -n +3 $0\n# GTM Custom GRUB Menu Entries\n"
        open_depth = 0
        for entry in self.menu_entries:
            depth = entry.get("submenu_depth", 1 if entry.get("is_submenu_item") else 0)
            while open_depth > depth: menu_text += "}\n"; open_depth -= 1
            if entry["type"] == "submenu":
                menu_text += f"submenu '{entry['title']}' {{\n"; open_depth = depth + 1
            else:
                code_block = entry.get("code", "") or f"menuentry '{entry['title']}' {{\n\ttrue\n}}"
                ind = "\t" * depth
                menu_text += "\n".join(ind + line for line in code_block.splitlines()) + "\n"
        while open_depth > 0: menu_text += "}\n"; open_depth -= 1
        temp_fd2, temp_menu_path = tempfile.mkstemp()
        try:
            with open(temp_menu_path, "w") as f: f.write(menu_text)
        finally: os.close(temp_fd2)
        self._apply_grub_config(temp_path, temp_menu_path)

    def _apply_grub_config(self, temp_path, temp_menu_path):
        # Only disable grub.d generators on Debian/Ubuntu.
        # On Fedora/RHEL, 10_linux generates BLS entries and must stay enabled.
        script = (
            f"cp -f {temp_path} /etc/default/grub\n"
            f"rm -f {temp_path}\n"
            f"cp -f {temp_menu_path} /etc/grub.d/06_gtm_custom\n"
            f"rm -f {temp_menu_path}\n"
            f"chmod +x /etc/grub.d/06_gtm_custom\n"
            f"if [ -f /etc/debian_version ]; then\n"
            f"    chmod -x /etc/grub.d/10_linux /etc/grub.d/20_memtest86+ "
            f"/etc/grub.d/30_os-prober /etc/grub.d/40_custom "
            f"/etc/grub.d/41_custom 2>/dev/null || true\n"
            f"fi\n"
            f"if command -v update-grub >/dev/null 2>&1; then\n"
            f"    update-grub\n"
            f"elif command -v grub2-mkconfig >/dev/null 2>&1; then\n"
            f"    grub2-mkconfig -o /boot/grub2/grub.cfg\n"
            f"else\n"
            f"    grub-mkconfig -o /boot/grub/grub.cfg\n"
            f"fi\n"
        )
        dlg = CommandDialog(title="Saving GRUB configuration", script_content=script)
        safe_present(dlg, self.parent_window)
        self.close()