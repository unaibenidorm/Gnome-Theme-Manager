"""
Theme Installer — automatic installation with pkexec for system ops.
Also handles applying themes via gsettings (like gnome-tweaks).
"""
import os, shutil, subprocess, tarfile, zipfile, tempfile, re, configparser, json
from pathlib import Path
SECURE_CACHE = {}

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
                    for pf in pfs:
                        rel = pf.parent.relative_to(d)
                        themes.append((str(rel), str(pf.parent)))
            return themes or [(e.name, str(e)) for e in sorted(d_list) if e.is_dir()]
        elif theme_type == "grub":
            themes = []
            for td in sorted(d_list):
                if td.is_dir() and td.name != ".git":
                    gts = list(td.rglob("theme.txt"))
                    for gt in gts:
                        rel = gt.parent.relative_to(d)
                        themes.append((str(rel), str(gt.parent)))
            return themes or [(e.name, str(e)) for e in sorted(d_list) if e.is_dir()]
            
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
    indicators = {
        "gtk":   ["gtk-3.0", "gtk-4.0"],
        "shell": ["gnome-shell"],
        "gdm":   ["gnome-shell", "gtk-3.0"],
        "icons": ["index.theme"],
        "grub":  ["theme.txt"],
        "plymouth": [],
    }
    checks = indicators.get(theme_type, [])
    
    # Check if root itself is the theme
    for c in checks:
        if (root / c).exists():
            return [root]
    
    # Check first-level children
    candidates = []
    for entry in root.iterdir():
        if entry.is_dir() and entry.name != ".git":
            for c in checks:
                if (entry / c).exists():
                    candidates.append(entry)
                    break
    if candidates:
        return candidates
    
    # For plymouth, check for .plymouth files
    if theme_type == "plymouth":
        for entry in root.iterdir():
            if entry.is_dir() and entry.name != ".git":
                if list(entry.glob("*.plymouth")):
                    candidates.append(entry)
        if candidates:
            return candidates
    
    # Fallback: return all first-level dirs
    return [e for e in root.iterdir() if e.is_dir() and e.name != ".git"] or [root]

def install_theme(archive_path, theme_type, scope="local", custom_path=None):
    """
    Install a theme. For system scope, uses pkexec automatically.
    Returns (success, message).
    """
    paths = get_install_paths()
    if theme_type not in paths:
        return False, f"Unknown type: {theme_type}"
    
    if scope not in paths.get(theme_type, {}):
        scope = "system"
    
    target_dir = Path(custom_path) if custom_path else paths[theme_type][scope]
    
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
            
            theme_dirs = _find_theme_root(tmp, theme_type)
            
            installed = []
            for td in theme_dirs:
                name = td.name
                if name == ".git": continue
                dest = target_dir / name
                
                if scope == "system":
                    # Use pkexec for system installs
                    ok, msg = _system_copy(td, dest, theme_type)
                    if not ok:
                        return False, msg
                    # Invalidate cache so it refreshes next time
                    if theme_type in SECURE_CACHE:
                        del SECURE_CACHE[theme_type]
                else:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(td, dest)
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
mkdir -p "{dest.parent}"
rm -rf "{dest}"
cp -r "{src}" "{dest}"
"""
        tmp_script = tempfile.mktemp(suffix=".sh")
        Path(tmp_script).write_text(script)
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
    
    def clean(s):
        for suf in ['-theme', '_theme', ' theme', '-grub', '_grub', ' grub', '-plymouth', '_plymouth', ' plymouth']:
            s = s.replace(suf, '')
        return s.strip()
    
    t_clean = clean(t_name)
    if not t_clean: return False
    
    for n in installed_names:
        n_clean = clean(n.lower())
        if t_clean == n_clean: return True
        # Prefix matching (e.g. "Mojave" vs "Mojave-Dark")
        for sep in ['-', '_', ' ']:
            if n_clean.startswith(t_clean + sep) or t_clean.startswith(n_clean + sep):
                return True
    return False

def get_installed_themes_secure(theme_type):
    """Get system themes using pkexec to bypass permission errors."""
    paths = get_install_paths()
    if theme_type not in paths or "system" not in paths[theme_type]:
        return []
    
    d = paths[theme_type]["system"]
    try:
        # Use a python script via pkexec to list the directory securely
        # It returns a JSON string of (name, path) tuples
        py_script = f"""
import os, json, pathlib
path = pathlib.Path('{d}')
items = []
if path.exists():
    for e in sorted(path.iterdir()):
        if e.is_dir() and e.name != '.git':
            if '{theme_type}' == 'plymouth':
                pfs = list(e.rglob('*.plymouth'))
                for pf in pfs:
                    rel = pf.parent.relative_to(path)
                    items.append((str(rel), str(pf.parent)))
            elif '{theme_type}' == 'grub':
                gts = list(e.rglob('theme.txt'))
                for gt in gts:
                    rel = gt.parent.relative_to(path)
                    items.append((str(rel), str(gt.parent)))
            else:
                items.append((e.name, str(e)))
if not items and path.exists():
    items = [(e.name, str(e)) for e in sorted(path.iterdir()) if e.is_dir()]
print(json.dumps(items))
"""
        result = subprocess.run(
            ["pkexec", "python3", "-c", py_script],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout.strip())
            SECURE_CACHE[theme_type] = data
            return data
        return []
    except Exception:
        return []

def get_grub_post_install_script(theme_txt_path):
    """Generate GRUB post-install commands."""
    grub_cfg = "/etc/default/grub"
    cmds = f"""#!/bin/bash
sed -i "/^GRUB_THEME=/d" {grub_cfg}
echo 'GRUB_THEME="{theme_txt_path}"' >> {grub_cfg}
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
# Ensure the theme is recognized by Plymouth
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
    # We use the filename (stem) as it's the standard identifier
    plymouth-set-default-theme "{theme_id}"
elif command -v update-alternatives >/dev/null 2>&1; then
    update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "{variant_path}" 200
    update-alternatives --set default.plymouth "{variant_path}"
fi

# Regenerate initramfs
if command -v update-initramfs >/dev/null 2>&1; then
    update-initramfs -u
elif command -v dracut >/dev/null 2>&1; then
    dracut -f
fi
"""

def get_grub_variants(theme_name):
    paths = get_install_paths()
    base_dir = paths["grub"]["system"]
    
    # If we already unlocked this category via pkexec, we should have the paths in cache
    if "grub" in SECURE_CACHE:
        # SECURE_CACHE['grub'] is a list of (display_name, full_path_to_parent_of_theme_txt)
        matches = []
        for dname, fpath in SECURE_CACHE["grub"]:
            # Match by name or if the path matches the search
            if theme_name.lower() in dname.lower() or theme_name.lower() in Path(fpath).name.lower():
                matches.append(Path(fpath) / "theme.txt")
        if matches: return matches

    try:
        if "/" in theme_name:
            td_name, p_name = theme_name.split("/", 1)
            base = base_dir / td_name
            if base.exists():
                return [p for p in base.rglob("theme.txt") if p.parent.name == p_name]
        
        # Exact match
        base = base_dir / theme_name
        if base.exists():
            res = [p for p in base.rglob("theme.txt")]
            if res: return res
        
        # Normalize search: remove suffixes like -grub, -theme and common separators
        search_term = theme_name.lower()
        for s in ["-grub", "_grub", " grub", "-theme", "_theme", " theme"]:
            search_term = search_term.replace(s, "")
        search_term = search_term.strip()

        # If exact match fails, look for folders containing the normalized name
        for d in base_dir.iterdir():
            if d.is_dir():
                d_low = d.name.lower()
                if search_term in d_low or d_low in search_term:
                    res = [p for p in d.rglob("theme.txt")]
                    if res: return res
    except (PermissionError, FileNotFoundError):
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
        
        # If no folder match, look for ANY .plymouth file matching the name
        if not candidates:
            candidates = list(base_dir.rglob(f"*{theme_name}*.plymouth"))
            
        return candidates
    except PermissionError:
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
            script = f"#!/bin/bash\nrm -rf '{var_dir}'\n"
            tmp_script = tempfile.mktemp(suffix=".sh")
            Path(tmp_script).write_text(script)
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
            script = f'rm -rf "{theme_dir}"\n'
            if theme_type == "grub":
                script += f'sed -i "/GRUB_THEME.*{theme_name}/d" /etc/default/grub\n'
                if shutil.which("update-grub"):
                    script += "update-grub\n"
            tmp = tempfile.mktemp(suffix=".sh")
            Path(tmp).write_text(script)
            os.chmod(tmp, 0o755)
            r = subprocess.run(["pkexec", "bash", tmp], capture_output=True, text=True, timeout=60)
            os.unlink(tmp)
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

def _gsettings_set(schema, key, value):
    try:
        r = subprocess.run(["gsettings", "set", schema, key, value], capture_output=True, text=True, timeout=5)
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
        r = subprocess.run(["gsettings", "get", schema, key], capture_output=True, text=True, timeout=5)
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
