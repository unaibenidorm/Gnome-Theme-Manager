"""
Theme Installer — automatic installation with pkexec for system ops.
Also handles applying themes via gsettings (like gnome-tweaks).
"""
import os, shutil, subprocess, tarfile, zipfile, tempfile, re, configparser, json, shlex
from pathlib import Path
SECURE_CACHE = {}

def check_dependencies():
    """Returns a dictionary of dependency statuses."""
    deps = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "imagemagick": shutil.which("convert") is not None or shutil.which("magick") is not None,
        "plymouth": shutil.which("plymouth-set-default-theme") is not None or shutil.which("plymouth") is not None,
        "git": shutil.which("git") is not None,
        "pkexec": shutil.which("pkexec") is not None
    }
    return deps

def get_install_command_for_distro():
    """Returns the package manager install command based on distro."""
    if shutil.which("dnf"):
        return "sudo dnf install ffmpeg imagemagick plymouth git polkit"
    elif shutil.which("apt-get"):
        return "sudo apt-get install ffmpeg imagemagick plymouth git polkitd"
    elif shutil.which("pacman"):
        return "sudo pacman -S ffmpeg imagemagick plymouth git polkit"
    elif shutil.which("zypper"):
        return "sudo zypper install ffmpeg imagemagick plymouth git polkit"
    else:
        return "Install dependencies: ffmpeg, imagemagick, plymouth, git, polkit"

def get_install_paths():
    home = Path.home()
    # Detect GRUB path (Ubuntu: grub, Fedora: grub2)
    grub_path = Path("/boot/grub/themes")
    
    try:
        if Path("/boot/grub2/themes").exists():
            grub_path = Path("/boot/grub2/themes")
        elif Path("/boot/grub/themes").exists():
            grub_path = Path("/boot/grub/themes")
    except PermissionError:
        if shutil.which("grub-mkconfig") or shutil.which("update-grub"):
            grub_path = Path("/boot/grub/themes")
        elif shutil.which("grub2-mkconfig"):
            grub_path = Path("/boot/grub2/themes")
        else:
            try:
                if Path("/boot/grub").exists():
                    grub_path = Path("/boot/grub/themes")
                elif Path("/boot/grub2").exists():
                    grub_path = Path("/boot/grub2/themes")
            except Exception: pass
    except Exception: pass

    return {
        "gtk":      {"local": home / ".themes",                       "system": Path("/usr/share/themes")},
        "shell":    {"local": home / ".themes",                       "system": Path("/usr/share/themes")},
        "icons":    {"local": home / ".icons",                        "system": Path("/usr/share/icons")},
        "cursors":  {"local": home / ".icons",                        "system": Path("/usr/share/icons")},
        "gdm":      {"local": home / ".themes",                       "system": Path("/usr/share/themes")},
        "grub":     {"system": grub_path},
        "plymouth": {"system": Path("/usr/share/plymouth/themes")},
    }

def get_installed_themes(theme_type, scope="local"):
    paths = get_install_paths()
    if theme_type not in paths or scope not in paths[theme_type]:
        return []
    d = paths[theme_type][scope]
    
    if scope == "system" and theme_type in SECURE_CACHE:
        return SECURE_CACHE[theme_type]

    # Check for permission BEFORE calling .exists() on some systems
    try:
        # We try to list it as the ultimate existence and permission check
        d_list = list(d.iterdir())
    except PermissionError:
        return "PERMISSION_DENIED"
    except FileNotFoundError:
        return []
    except Exception:
        return []

    try:
        if theme_type == "plymouth":
            themes = []
            for td in sorted(d_list):
                if td.is_dir() and td.name != ".git":
                    pfs = list(td.rglob("*.plymouth"))
                    if pfs:
                        for pf in pfs:
                            rel = pf.parent.relative_to(d)
                            themes.append((str(rel), str(pf.parent)))
                    else:
                        themes.append((td.name, str(td)))
            return themes
        elif theme_type == "grub":
            themes = []
            seen_dirs = set()
            for td in sorted(d_list):
                if td.is_dir() and td.name != ".git":
                    gts = list(td.rglob("theme*.txt"))
                    if gts:
                        for gt in gts:
                            parent_str = str(gt.parent)
                            if parent_str not in seen_dirs:
                                seen_dirs.add(parent_str)
                                rel = gt.parent.relative_to(d)
                                themes.append((str(rel), parent_str))
                    else:
                        themes.append((td.name, str(td)))
            return themes
        
        # Differentiate between gtk, shell, gdm, icons, cursors by directory contents
        if theme_type == "cursors":
            return [(e.name, str(e)) for e in sorted(d_list) if e.is_dir() and (e / "cursors").is_dir()]
        elif theme_type == "icons":
            return [(e.name, str(e)) for e in sorted(d_list) if e.is_dir() and not (e / "cursors").is_dir()]
        elif theme_type == "gtk":
            return [(e.name, str(e)) for e in sorted(d_list) if e.is_dir() and ((e / "gtk-3.0").is_dir() or (e / "gtk-4.0").is_dir())]
        elif theme_type == "shell":
            return [(e.name, str(e)) for e in sorted(d_list) if e.is_dir() and (e / "gnome-shell").is_dir()]
        elif theme_type == "gdm":
            return [(e.name, str(e)) for e in sorted(d_list) if e.is_dir() and ((e / "gnome-shell").is_dir() or (e / "gtk-3.0").is_dir())]
            
        return [(e.name, str(e)) for e in sorted(d_list) if e.is_dir()]
    except Exception:
        return []

def get_theme_dir(theme_type, scope="local"):
    """Get the install directory path for a theme type+scope."""
    paths = get_install_paths()
    if theme_type not in paths or scope not in paths[theme_type]:
        return None
    return paths[theme_type][scope]

def extract_archive(archive_path, dest_dir):
    archive_path, dest_dir = Path(archive_path), Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()
    
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif name.endswith(".rar"):
        if shutil.which("unrar"):
            r = subprocess.run(["unrar", "x", "-y", str(archive_path), str(dest_dir)], capture_output=True)
            if r.returncode != 0: raise ValueError(f"Error unrar: {r.stderr.decode('utf-8', errors='ignore')}")
        elif shutil.which("7z"):
            r = subprocess.run(["7z", "x", "-y", f"-o{dest_dir}", str(archive_path)], capture_output=True)
            if r.returncode != 0: raise ValueError(f"Error 7z: {r.stderr.decode('utf-8', errors='ignore')}")
        else:
            raise ValueError("Install 'unrar' or 'p7zip' to extract RAR files.")
    elif name.endswith(".7z"):
        if shutil.which("7z"):
            r = subprocess.run(["7z", "x", "-y", f"-o{dest_dir}", str(archive_path)], capture_output=True)
            if r.returncode != 0: raise ValueError(f"Error 7z: {r.stderr.decode('utf-8', errors='ignore')}")
        else:
            raise ValueError("Install 'p7zip' to extract 7Z files.")
    elif any(name.endswith(e) for e in (".tar.gz",".tgz",".tar.xz",".tar.bz2",".tar",".tar.zst")):
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                for m in tf.getmembers():
                    if not str((dest_dir / m.name).resolve()).startswith(str(dest_dir.resolve())):
                        raise ValueError(f"Path traversal: {m.name}")
                tf.extractall(dest_dir)
        except Exception:
            if shutil.which("tar"):
                r = subprocess.run(["tar", "-xf", str(archive_path), "-C", str(dest_dir)], capture_output=True)
                if r.returncode != 0: raise ValueError("The file is corrupt, or the download failed (possibly requires login on pling).")
            else:
                raise ValueError("Could not extract the archive.")
    else:
        if shutil.which("7z"):
            r = subprocess.run(["7z", "x", "-y", f"-o{dest_dir}", str(archive_path)], capture_output=True)
            if r.returncode != 0: raise ValueError(f"Unsupported format or corrupt file: {archive_path.name}")
        else:
            raise ValueError(f"Unsupported format: {archive_path.name}")

def _find_theme_root(extracted_dir, theme_type):
    """Find the actual theme directory inside extracted archive."""
    root = Path(extracted_dir)
    
    def check_dir(d, t_type):
        if t_type == "grub":
            try: return bool(list(d.glob("theme*.txt")))
            except Exception: return False
        elif t_type == "plymouth":
            try: return bool(list(d.glob("*.plymouth")))
            except Exception: return False
        elif t_type == "cursors":
            return (d / "cursors").is_dir()
        elif t_type == "icons":
            return (d / "index.theme").exists() and not (d / "cursors").is_dir()
        elif t_type == "gtk":
            return (d / "gtk-3.0").is_dir() or (d / "gtk-4.0").is_dir()
        elif t_type == "shell":
            return (d / "gnome-shell").is_dir()
        elif t_type == "gdm":
            return (d / "gnome-shell").is_dir() or (d / "gtk-3.0").is_dir()
        return False

    # Check if root itself is the theme
    if check_dir(root, theme_type):
        return [root]
    
    # Check first-level children
    candidates = []
    for entry in root.iterdir():
        if entry.is_dir() and entry.name != ".git":
            if check_dir(entry, theme_type):
                candidates.append(entry)
    if candidates:
        return candidates
    
    # Check second-level children
    for entry in root.iterdir():
        if entry.is_dir() and entry.name != ".git":
            try:
                for sub in entry.iterdir():
                    if sub.is_dir() and sub.name != ".git":
                        if check_dir(sub, theme_type):
                            candidates.append(sub)
            except PermissionError:
                continue
    if candidates:
        return candidates
    
    # Fallback: return all first-level dirs
    return [e for e in root.iterdir() if e.is_dir() and e.name != ".git"] or [root]

def detect_theme_type(extracted_dir):
    """Auto-detect the type of theme(s) in an extracted directory.
    Returns a list of (theme_type, theme_dir) tuples found."""
    root = Path(extracted_dir)
    results = []
    
    # Priority order: specific types first
    type_indicators = [
        ("grub",     lambda d: bool(list(d.glob("theme*.txt")))),
        ("plymouth", lambda d: bool(list(d.glob("*.plymouth")))),
        ("cursors",  lambda d: (d / "cursors").is_dir()),
        ("shell",    lambda d: (d / "gnome-shell").is_dir() and not (d / "gtk-3.0").is_dir()),
        ("gtk",      lambda d: (d / "gtk-3.0").is_dir() or (d / "gtk-4.0").is_dir()),
        ("icons",    lambda d: (d / "index.theme").exists() and not (d / "cursors").is_dir()),
    ]
    
    def _check_dir(d):
        for ttype, check_fn in type_indicators:
            try:
                if check_fn(d):
                    return ttype
            except (PermissionError, OSError):
                continue
        return None
    
    # Check root
    t = _check_dir(root)
    if t:
        results.append((t, root))
        return results
    
    # Check children (may have multiple types)
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and entry.name != ".git":
            t = _check_dir(entry)
            if t:
                results.append((t, entry))
            else:
                # Check one more level deep
                try:
                    for sub in sorted(entry.iterdir()):
                        if sub.is_dir() and sub.name != ".git":
                            t = _check_dir(sub)
                            if t:
                                results.append((t, sub))
                except (PermissionError, OSError):
                    continue
    
    return results

def _validate_cursor_theme(theme_dir):
    """Validate a cursor theme has proper structure to avoid Gtk-WARNING about no directories."""
    cursor_dir = theme_dir / "cursors"
    index_file = theme_dir / "index.theme"
    
    if not cursor_dir.is_dir():
        return False
    
    # Check if cursor dir has actual cursor files
    cursor_files = list(cursor_dir.iterdir())
    if not cursor_files:
        return False
    
    # Create or fix index.theme to prevent Gtk-WARNING 'has no directories'
    try:
        content = ""
        if index_file.exists():
            content = index_file.read_text(errors='ignore')
        
        # If missing the header or Inherits key, Gtk will treat it as a broken icon theme
        if "[Icon Theme]" not in content or "Inherits=" not in content:
            index_file.write_text(
                f"[Icon Theme]\n"
                f"Name={theme_dir.name}\n"
                f"Comment=Cursor theme {theme_dir.name}\n"
                f"Inherits=default\n"
            )
    except Exception:
        pass
    
    return True

def _robust_copytree(src, dest):
    """Robustly copy a directory tree, preserving symlinks and ignoring dangling symlinks."""
    if dest.exists():
        shutil.rmtree(dest)
    try:
        shutil.copytree(src, dest, symlinks=True, ignore_dangling_symlinks=True)
    except TypeError:
        # Fallback for Python versions lacking ignore_dangling_symlinks
        try:
            shutil.copytree(src, dest, symlinks=True)
        except Exception:
            shutil.copytree(src, dest, symlinks=False)

def install_theme(archive_path, theme_type, scope="local", custom_path=None):
    """
    Install a theme. For system scope, uses pkexec automatically.
    Auto-detects actual theme type from content if possible.
    Returns (success, message).
    """
    paths = get_install_paths()
    if theme_type not in paths:
        return False, f"Unknown type: {theme_type}"
    
    if scope not in paths.get(theme_type, {}):
        scope = "system"
    
    try:
        is_dir = Path(archive_path).is_dir()
        tmp_dir_context = tempfile.TemporaryDirectory() if not is_dir else None
        tmp = tmp_dir_context.name if not is_dir else archive_path
        
        try:
            if not is_dir:
                try:
                    extract_archive(archive_path, tmp)
                except (tarfile.ReadError, zipfile.BadZipFile, ValueError) as e:
                    return False, f"The downloaded file is not a valid theme or the link requires login: {e}"
            
            # Auto-detect what types of themes are in the archive
            detected = detect_theme_type(tmp)
            
            installed = []
            
            if detected:
                # Install each detected theme to its correct location
                for det_type, det_dir in detected:
                    actual_scope = scope
                    cat_info_det = {"grub": True, "plymouth": True}.get(det_type, False)
                    if cat_info_det:
                        actual_scope = "system"
                    
                    if actual_scope not in paths.get(det_type, {}):
                        actual_scope = list(paths.get(det_type, {}).keys())[0] if paths.get(det_type) else scope
                    
                    target_dir = Path(custom_path) if custom_path else paths[det_type][actual_scope]
                    name = det_dir.name
                    if name == ".git":
                        continue
                    dest = target_dir / name
                    
                    # Validate cursor themes before install
                    if det_type == "cursors":
                        _validate_cursor_theme(det_dir)
                    
                    if actual_scope == "system":
                        ok, msg = _system_copy(det_dir, dest, det_type)
                        if not ok:
                            return False, msg
                        if det_type in SECURE_CACHE:
                            del SECURE_CACHE[det_type]
                    else:
                        target_dir.mkdir(parents=True, exist_ok=True)
                        _robust_copytree(det_dir, dest)
                    installed.append(name)
            else:
                # Fallback: use the original category-based detection
                target_dir = Path(custom_path) if custom_path else paths[theme_type][scope]
                theme_dirs = _find_theme_root(tmp, theme_type)
                
                for td in theme_dirs:
                    name = td.name
                    if name == ".git": continue
                    dest = target_dir / name
                    
                    if theme_type == "cursors":
                        _validate_cursor_theme(td)
                    
                    if scope == "system":
                        ok, msg = _system_copy(td, dest, theme_type)
                        if not ok:
                            return False, msg
                        if theme_type in SECURE_CACHE:
                            del SECURE_CACHE[theme_type]
                    else:
                        target_dir.mkdir(parents=True, exist_ok=True)
                        _robust_copytree(td, dest)
                    installed.append(name)
            
            if not installed: return False, "No valid themes found."
            return True, f"Installed: {', '.join(installed)}"
        finally:
            if tmp_dir_context: tmp_dir_context.cleanup()
    except Exception as e:
        return False, str(e)

def _system_copy(src, dest, theme_type):
    """Copy files to system location using pkexec."""
    try:
        script = f"""#!/bin/bash
mkdir -p {shlex.quote(str(dest.parent))}
rm -rf {shlex.quote(str(dest))}
cp -r {shlex.quote(str(src))} {shlex.quote(str(dest))}
"""
        tmp_fd = tempfile.NamedTemporaryFile(mode='w', suffix=".sh", delete=False)
        tmp_script = tmp_fd.name
        tmp_fd.write(script)
        tmp_fd.close()
        os.chmod(tmp_script, 0o755)
        
        result = subprocess.run(
            ["pkexec", "bash", tmp_script],
            capture_output=True, text=True, timeout=120
        )
        os.unlink(tmp_script)
        
        if result.returncode != 0:
            return False, f"pkexec error: {result.stderr.strip()}"
        return True, "OK"
    except subprocess.TimeoutExpired:
        return False, "Operation timed out"
    except FileNotFoundError:
        return False, "pkexec not found. Install polkit."
    except Exception as e:
        return False, str(e)

def is_theme_installed_fuzzy(theme_name, installed_names):
    """Accurately checks if a theme name matches one of the installed folder names."""
    t_name = theme_name.strip().lower()
    if not t_name: return False
    
    # Suffixes to strip for normalization
    strip_suffixes = [
        '-theme', '_theme', ' theme',
        '-grub', '_grub', ' grub',
        '-plymouth', '_plymouth', ' plymouth',
        '-cursor', '_cursor', ' cursor',
        '-cursors', '_cursors', ' cursors',
        '-icon', '_icon', ' icon',
        '-icons', '_icons', ' icons',
        '-gtk', '_gtk', ' gtk',
    ]
    
    def clean(s):
        s = s.lower().strip()
        changed = True
        while changed:
            changed = False
            for suf in strip_suffixes:
                if s.endswith(suf):
                    s = s[:-len(suf)].strip()
                    changed = True
        return s
    
    t_clean = clean(t_name)
    if not t_clean: return False
    
    core_system_themes = {"adwaita", "hicolor", "highcontrast", "default", "gnome", "locolor", "pixmaps", "dmz", "dmz-white", "dmz-black"}

    for n in installed_names:
        # If n has a slash, split it to get the base theme folder name (e.g. "marathon" from "marathon/1080p")
        n_base = n.split('/')[0] if '/' in n else n
        n_clean = clean(n_base.lower())
        if not n_clean: continue
        
        # If it is a core system theme, we ONLY allow exact match!
        if n_clean in core_system_themes:
            if t_clean == n_clean:
                return True
            continue
            
        # Exact match after cleaning
        if t_clean == n_clean: return True
        # Prefix matching (e.g. "Mojave" vs "Mojave-Dark")
        for sep in ['-', '_', ' ']:
            if n_clean.startswith(t_clean + sep) or t_clean.startswith(n_clean + sep):
                return True
        # Substring match for short names (>= 4 chars) to catch "Bibata" in "Bibata-Modern-Ice"
        if len(t_clean) >= 4 and (t_clean in n_clean or n_clean in t_clean):
            if t_clean not in core_system_themes:
                return True
    return False

_CONFIG_DIR = Path.home() / ".config" / "gnome-theme-manager"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

def _load_installer_config():
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return {}

def _save_installer_config(cfg):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_CONFIG_FILE, "w") as f: json.dump(cfg, f)
    except Exception: pass

def is_theme_installed(theme_id, theme_name, category, installed_names):
    """
    Check if a theme is installed, prioritizing the local installed database (ID matching).
    Falls back to fuzzy matching on theme_name against installed_names.
    """
    # 1. Try ID-based matching from local database
    if theme_id:
        cfg = _load_installer_config()
        db = cfg.get("installed_database", {})
        theme_id_str = str(theme_id)
        if theme_id_str in db:
            entry = db[theme_id_str]
            folders = entry.get("folders", [])
            scope = entry.get("scope", "local")
            cat = entry.get("category", category)
            paths = get_install_paths()
            
            if cat in paths:
                still_exists = False
                for f_name in folders:
                    # Resolve to actual full path
                    for s in [scope, "local", "system"]:
                        if s in paths.get(cat, {}):
                            p = paths[cat][s] / f_name
                            if p.exists():
                                still_exists = True
                                break
                    if still_exists:
                        break
                
                if still_exists:
                    return True
                else:
                    # Clean up invalid/deleted entry
                    try:
                        del db[theme_id_str]
                        _save_installer_config(cfg)
                    except Exception:
                        pass

    # 2. Fallback to robust fuzzy name matching
    return is_theme_installed_fuzzy(theme_name, installed_names)

def get_installed_themes_secure(theme_type):
    """Get system themes using pkexec to bypass permission errors."""
    paths = get_install_paths()
    if theme_type not in paths or "system" not in paths[theme_type]:
        return []
    
    d = paths[theme_type]["system"]
    try:
        py_script = f"""
import os, json, pathlib
path = pathlib.Path('{d}')
items = []
if path.exists():
    for e in sorted(path.iterdir()):
        if e.is_dir() and e.name != '.git':
            if '{theme_type}' == 'plymouth':
                pfs = list(e.rglob('*.plymouth'))
                if pfs:
                    for pf in pfs:
                        rel = pf.parent.relative_to(path)
                        items.append((str(rel), str(pf.parent)))
                else:
                    items.append((e.name, str(e)))
            elif '{theme_type}' == 'grub':
                gts = list(e.rglob('theme*.txt'))
                seen_dirs = set()
                if gts:
                    for gt in gts:
                        ps = str(gt.parent)
                        if ps not in seen_dirs:
                            seen_dirs.add(ps)
                            rel = gt.parent.relative_to(path)
                            items.append((str(rel), ps))
                else:
                    items.append((e.name, str(e)))
            elif '{theme_type}' == 'cursors':
                if (e / 'cursors').is_dir():
                    items.append((e.name, str(e)))
            elif '{theme_type}' == 'icons':
                if not (e / 'cursors').is_dir():
                    items.append((e.name, str(e)))
            elif '{theme_type}' == 'gtk':
                if (e / 'gtk-3.0').is_dir() or (e / 'gtk-4.0').is_dir():
                    items.append((e.name, str(e)))
            elif '{theme_type}' == 'shell':
                if (e / 'gnome-shell').is_dir():
                    items.append((e.name, str(e)))
            elif '{theme_type}' == 'gdm':
                if (e / 'gnome-shell').is_dir() or (e / 'gtk-3.0').is_dir():
                    items.append((e.name, str(e)))
            else:
                items.append((e.name, str(e)))
print(json.dumps(items))
"""
        clean_env = os.environ.copy()
        for k in ["LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "APPIMAGE", "APPDIR"]:
            clean_env.pop(k, None)
        if "PATH" in clean_env:
            paths = clean_env["PATH"].split(":")
            clean_paths = [p for p in paths if ".mount_" not in p and "/tmp/" not in p]
            clean_env["PATH"] = ":".join(clean_paths)
            
        result = subprocess.run(
            ["pkexec", "/usr/bin/python3", "-c", py_script],
            capture_output=True, text=True, timeout=30, env=clean_env
        )
        if result.returncode == 0:
            data = json.loads(result.stdout.strip())
            SECURE_CACHE[theme_type] = data
            return data
        return []
    except Exception:
        return []

def check_grub_gfxterm():
    """Check if GRUB is configured with gfxterm (required for themes).
    Returns (is_gfxterm, current_terminal) tuple."""
    try:
        cfg = Path("/etc/default/grub").read_text()
        for line in cfg.splitlines():
            stripped = line.strip()
            if stripped.startswith("GRUB_TERMINAL_OUTPUT="):
                val = stripped.split("=", 1)[1].strip("\"'")
                return val.lower() == "gfxterm", val
            if stripped.startswith("GRUB_TERMINAL="):
                val = stripped.split("=", 1)[1].strip("\"'")
                return val.lower() == "gfxterm", val
        # If not set, GRUB usually defaults to gfxterm on most distros
        return True, "default (gfxterm)"
    except Exception:
        return True, "unknown"

def get_grub_post_install_script(theme_txt_path):
    """Generate GRUB post-install commands."""
    grub_cfg = "/etc/default/grub"
    safe_path = shlex.quote(theme_txt_path)
    cmds = f"""#!/bin/bash
# Ensure gfxterm is set for theme support
sed -i '/^GRUB_TERMINAL_OUTPUT=/d' {grub_cfg}
sed -i '/^GRUB_TERMINAL=/d' {grub_cfg}
echo 'GRUB_TERMINAL_OUTPUT="gfxterm"' >> {grub_cfg}
sed -i '/^GRUB_THEME=/d' {grub_cfg}
echo 'GRUB_THEME={safe_path}' >> {grub_cfg}
if command -v update-grub >/dev/null 2>&1; then
    update-grub
elif command -v grub-mkconfig >/dev/null 2>&1; then
    grub-mkconfig -o /boot/grub/grub.cfg
elif command -v grub2-mkconfig >/dev/null 2>&1; then
    grub2-mkconfig -o /boot/grub2/grub.cfg
fi
"""
    return cmds

def get_plymouth_post_install_script(variant_path):
    # variant_path is the absolute path to the .plymouth file
    # e.g. /usr/share/plymouth/themes/plymouth-polishcow/polishcow.plymouth
    p_file = Path(variant_path)
    # The theme name for plymouth-set-default-theme is usually 
    # the name of the .plymouth file without the extension.
    theme_id = p_file.stem
    
    return f"""#!/bin/bash
export PATH=$PATH:/usr/sbin:/usr/bin:/sbin:/bin

# Ensure the theme is recognized by Plymouth
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
    # We use the filename (stem) as it's the standard identifier
    plymouth-set-default-theme -R "{theme_id}"
elif command -v update-alternatives >/dev/null 2>&1; then
    update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "{variant_path}" 200
    update-alternatives --set default.plymouth "{variant_path}"
    
    # Regenerate initramfs
    if command -v update-initramfs >/dev/null 2>&1; then
        update-initramfs -u
    elif command -v dracut >/dev/null 2>&1; then
        dracut -f
    fi
fi
"""

def get_grub_variants(theme_name):
    paths = get_install_paths()
    base_dir = paths["grub"]["system"]
    
    # If we already unlocked this category via pkexec, we should have the paths in cache
    if "grub" in SECURE_CACHE:
        matches = []
        for dname, fpath in SECURE_CACHE["grub"]:
            if theme_name.lower() in dname.lower() or theme_name.lower() in Path(fpath).name.lower():
                try:
                    matches.extend(list(Path(fpath).glob("theme*.txt")))
                except Exception:
                    pass
        if matches: return matches

    try:
        if "/" in theme_name:
            td_name, p_name = theme_name.split("/", 1)
            base = base_dir / td_name
            if base.exists():
                return [p for p in base.rglob("theme*.txt") if p.parent.name == p_name]
        
        # Exact match
        base = base_dir / theme_name
        if base.exists():
            res = [p for p in base.rglob("theme*.txt")]
            if res: return res
        
        # Normalize search
        search_term = theme_name.lower()
        for s in ["-grub", "_grub", " grub", "-theme", "_theme", " theme"]:
            search_term = search_term.replace(s, "")
        search_term = search_term.strip()

        # If exact match fails, look for folders containing the normalized name
        for d in base_dir.iterdir():
            if d.is_dir():
                d_low = d.name.lower()
                if search_term in d_low or d_low in search_term:
                    res = [p for p in d.rglob("theme*.txt")]
                    if res: return res
    except PermissionError:
        py_script = f"""
import pathlib, json
base = pathlib.Path('{base_dir}')
results = []
theme_name = '{theme_name}'
search_term = theme_name.lower()
for s in ["-grub", "_grub", " grub", "-theme", "_theme", " theme"]:
    search_term = search_term.replace(s, "")
search_term = search_term.strip()

if base.exists():
    b = base / theme_name
    if b.exists():
        results.extend([str(p) for p in b.rglob("theme*.txt")])
    elif "/" in theme_name:
        td, pd = theme_name.split("/", 1)
        b = base / td
        if b.exists():
            results.extend([str(p) for p in b.rglob("theme*.txt") if p.parent.name == pd])
            
    if not results:
        for d in base.iterdir():
            if d.is_dir():
                d_low = d.name.lower()
                if search_term in d_low or d_low in search_term:
                    results.extend([str(p) for p in d.rglob("theme*.txt")])
print(json.dumps(results))
"""
        try:
            r = subprocess.run(["pkexec", "/usr/bin/python3", "-c", py_script], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                paths = json.loads(r.stdout.strip())
                return [Path(p) for p in paths]
        except Exception:
            pass
    except Exception:
        pass
    return []

def get_plymouth_variants(theme_name):
    base_dir = Path("/usr/share/plymouth/themes")
    
    # Try cache first
    if "plymouth" in SECURE_CACHE:
        matches = []
        for dname, fpath in SECURE_CACHE["plymouth"]:
            p_files = list(Path(fpath).glob("*.plymouth"))
            # Check if theme_name is in folder, or folder in theme_name, or in file stem
            if theme_name.lower() in dname.lower() or \
               dname.lower() in theme_name.lower() or \
               (p_files and theme_name.lower() in p_files[0].stem.lower()):
                matches.extend(p_files)
        if matches: return matches

    try:
        if not base_dir.exists(): return []
        
        # Try finding directories that match or contain the name (both ways)
        candidates = []
        for d in base_dir.iterdir():
            if d.is_dir():
                if theme_name.lower() in d.name.lower() or d.name.lower() in theme_name.lower():
                    pfs = list(d.rglob("*.plymouth"))
                    candidates.extend(pfs)
        
        if candidates: return candidates
        
        # If no folder match, look for ANY .plymouth file matching the name
        if not candidates:
            candidates = list(base_dir.rglob(f"*{theme_name}*.plymouth"))
            if candidates: return candidates
    except PermissionError:
        py_script = f"""
import pathlib, json
base = pathlib.Path('{base_dir}')
results = []
theme_name = '{theme_name}'
search_term = theme_name.lower()
for s in ["-plymouth", "_plymouth", " plymouth", "-theme", "_theme", " theme"]:
    search_term = search_term.replace(s, "")
search_term = search_term.strip()

if base.exists():
    b = base / theme_name
    if b.exists():
        results.extend([str(p) for p in b.glob("*.plymouth")])
    if not results:
        for d in base.iterdir():
            if d.is_dir():
                d_low = d.name.lower()
                if search_term in d_low or d_low in search_term:
                    results.extend([str(p) for p in d.glob("*.plymouth")])
print(json.dumps(results))
"""
        try:
            r = subprocess.run(["pkexec", "/usr/bin/python3", "-c", py_script], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                paths = json.loads(r.stdout.strip())
                return [Path(p) for p in paths]
        except Exception:
            pass
    except Exception:
        pass
    return []

def uninstall_variant(var_dir_path, scope="local"):
    var_dir = Path(var_dir_path)
    try:
        if not var_dir.exists():
            return False, "Directory not found"
    except PermissionError:
        pass # We might not have permission to check, proceed with pkexec

    try:
        if scope == "system":
            script = f"#!/bin/bash\nrm -rf {shlex.quote(str(var_dir))}\n"
            tmp_fd = tempfile.NamedTemporaryFile(mode='w', suffix=".sh", delete=False)
            tmp_script = tmp_fd.name
            tmp_fd.write(script)
            tmp_fd.close()
            os.chmod(tmp_script, 0o755)
            r = subprocess.run(["pkexec", "bash", tmp_script], capture_output=True, text=True)
            os.unlink(tmp_script)
            if r.returncode != 0: return False, f"pkexec error: {r.stderr.strip()}"
            
            # Clear appropriate cache if deleted successfully
            for t_type in list(SECURE_CACHE.keys()):
                SECURE_CACHE[t_type] = [
                    item for item in SECURE_CACHE[t_type] 
                    if not Path(item[1]).is_relative_to(var_dir)
                ]
        else:
            shutil.rmtree(var_dir)
        return True, "Removed"
    except Exception as e:
        return False, str(e)

def uninstall_theme(theme_name, theme_type, scope="local"):
    paths = get_install_paths()
    if theme_type not in paths or scope not in paths[theme_type]:
        return False, "Invalid"
    theme_dir = paths[theme_type][scope] / theme_name
    try:
        if not theme_dir.exists():
            return False, f"Not found: {theme_dir}"
    except PermissionError:
        pass # We might not have permission to check, proceed with pkexec

    try:
        if scope == "system":
            script = f'rm -rf {shlex.quote(str(theme_dir))}\n'
            if theme_type == "grub":
                safe_name = re.escape(theme_name)
                script += f'sed -i "/GRUB_THEME.*{safe_name}/d" /etc/default/grub\n'
                if shutil.which("update-grub"):
                    script += "update-grub\n"
            tmp_fd = tempfile.NamedTemporaryFile(mode='w', suffix=".sh", delete=False)
            tmp_path = tmp_fd.name
            tmp_fd.write(script)
            tmp_fd.close()
            os.chmod(tmp_path, 0o755)
            r = subprocess.run(["pkexec", "bash", tmp_path], capture_output=True, text=True, timeout=60)
            os.unlink(tmp_path)
            if r.returncode != 0:
                return False, r.stderr.strip()
                
            if theme_type in SECURE_CACHE:
                SECURE_CACHE[theme_type] = [item for item in SECURE_CACHE[theme_type] if item[0] != theme_name and not Path(item[1]).is_relative_to(theme_dir)]
                
            return True, f"Removed {theme_name}"
        else:
            shutil.rmtree(theme_dir)
            return True, f"Removed {theme_name}"
    except Exception as e:
        return False, str(e)

# ─── Apply themes via gsettings (like gnome-tweaks) ────────────────────────

def apply_gtk_theme(name):
    return _gsettings_set("org.gnome.desktop.interface", "gtk-theme", name)

def apply_icon_theme(name):
    return _gsettings_set("org.gnome.desktop.interface", "icon-theme", name)

def apply_shell_theme(name):
    return _gsettings_set("org.gnome.shell.extensions.user-theme", "name", name)

def apply_cursor_theme(name):
    return _gsettings_set("org.gnome.desktop.interface", "cursor-theme", name)

def get_current_cursor_theme():
    return _gsettings_get("org.gnome.desktop.interface", "cursor-theme")

def get_current_gtk_theme():
    return _gsettings_get("org.gnome.desktop.interface", "gtk-theme")

def get_current_icon_theme():
    return _gsettings_get("org.gnome.desktop.interface", "icon-theme")

def get_current_shell_theme():
    return _gsettings_get("org.gnome.shell.extensions.user-theme", "name")

def get_active_grub_theme():
    try:
        cfg = Path("/etc/default/grub").read_text()
        for line in cfg.splitlines():
            if line.startswith("GRUB_THEME="):
                return line.split("=", 1)[1].strip("\"'")
    except Exception: pass
    return ""

def get_active_plymouth_theme():
    try:
        p = Path("/usr/share/plymouth/themes/default.plymouth")
        if p.exists() or p.is_symlink():
            return str(p.resolve())
            
        if shutil.which("plymouth-set-default-theme"):
            r = subprocess.run(["plymouth-set-default-theme"], capture_output=True, text=True)
            if r.stdout.strip(): return r.stdout.strip()
    except Exception: pass
    return ""

def _get_clean_env():
    """Return a clean environment for gsettings calls.
    Conda/mamba environments can pollute GIO/GSettings paths,
    causing gsettings to write to a different dconf backend
    than the user's actual GNOME session."""
    env = os.environ.copy()
    # Remove conda/mamba vars that can interfere with GSettings/GIO
    for var in ["GSETTINGS_SCHEMA_DIR", "GIO_EXTRA_MODULES",
                "GIO_MODULE_DIR", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"]:
        env.pop(var, None)
    # Ensure LD_LIBRARY_PATH doesn't pull in conda's libgio
    ld = env.get("LD_LIBRARY_PATH", "")
    if ld:
        parts = [p for p in ld.split(":") if "conda" not in p and "mamba" not in p]
        env["LD_LIBRARY_PATH"] = ":".join(parts) if parts else ""
    # Force system XDG schema dir
    env["GSETTINGS_SCHEMA_DIR"] = "/usr/share/glib-2.0/schemas"
    return env

def _gsettings_set(schema, key, value):
    try:
        env = _get_clean_env()
        gsettings_bin = "/usr/bin/gsettings" if os.path.exists("/usr/bin/gsettings") else "gsettings"
        r = subprocess.run([gsettings_bin, "set", schema, key, value],
                           capture_output=True, text=True, timeout=5, env=env)
        if r.returncode != 0:
            err = r.stderr.strip()
            if "No such schema" in err or "No existe el esquema" in err:
                if schema == "org.gnome.shell.extensions.user-theme":
                    return False, "The 'User Themes' extension is missing. Please install it, enable it, and restart your session."
                return False, f"Schema {schema} does not exist."
            return False, err
        return True, "Applied"
    except Exception as e:
        return False, str(e)

def _gsettings_get(schema, key):
    try:
        env = _get_clean_env()
        gsettings_bin = "/usr/bin/gsettings" if os.path.exists("/usr/bin/gsettings") else "gsettings"
        r = subprocess.run([gsettings_bin, "get", schema, key],
                           capture_output=True, text=True, timeout=5, env=env)
        return r.stdout.strip().strip("'") if r.returncode == 0 else ""
    except Exception:
        return ""

def check_user_themes_extension():
    ext = "user-theme@gnome-shell-extensions.gcampax.github.com"
    home = Path.home()
    installed = (Path(f"/usr/share/gnome-shell/extensions/{ext}").exists() or
                 (home / f".local/share/gnome-shell/extensions/{ext}").exists())
    if not installed:
        return False, False, (
            "⚠ User Themes extension is NOT installed.\n"
            "It is required to apply GNOME Shell themes.\n\n"
            "Install it with:\n"
            "  sudo apt install gnome-shell-extension-user-theme\n"
            "  sudo dnf install gnome-shell-extension-user-theme\n"
            "  sudo pacman -S gnome-shell-extensions\n\n"
            "Then enable it in the GNOME Extensions app."
        )
    enabled = False
    try:
        r = subprocess.run(["gnome-extensions", "info", ext], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            enabled = "ACTIVE" in r.stdout or "ENABLED" in r.stdout
    except Exception:
        pass
    if enabled:
        return True, True, "✅ User Themes extension active."
    return True, False, (
        "⚠ User Themes installed but NOT active.\n"
        "Enable it with:\n"
        "  gnome-extensions enable user-theme@gnome-shell-extensions.gcampax.github.com"
    )

def open_directory(path):
    """Open a directory in the file manager."""
    path = Path(path)
    if path.exists():
        subprocess.Popen(["xdg-open", str(path)])
