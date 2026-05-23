#!/usr/bin/env python3
"""
Gnome Theme Manager - Entry Point
Browse, download and install GNOME themes from gnome-look.org
"""
import sys
import os
import subprocess
import json
import pwd
from pathlib import Path

# Get real, non-root user's home directory even when running under pkexec/sudo elevation
def get_real_home():
    pkexec_uid = os.environ.get("PKEXEC_UID")
    if pkexec_uid:
        try:
            return Path(pwd.getpwuid(int(pkexec_uid)).pw_dir)
        except Exception:
            pass
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except Exception:
            pass
    return Path(os.path.expanduser("~"))

# Monkeypatch Path.home dynamically so that the entire application automatically preserves user paths
Path.home = staticmethod(get_real_home)

# Check run_as_root setting and relaunch GTM under pkexec if enabled and not already elevated
cfg_file = Path.home() / ".config" / "gnome-theme-manager" / "config.json"
run_as_root = False
if cfg_file.exists():
    try:
        with open(cfg_file, "r") as f:
            cfg = json.load(f)
            run_as_root = cfg.get("run_as_root", False)
    except Exception:
        pass
        
if run_as_root and os.geteuid() != 0:
    try:
        # Preserve GUI display server environment variables so that GTK can initialize under root context
        env_args = []
        for var in ["DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"]:
            if var in os.environ:
                env_args.append(f"{var}={os.environ[var]}")
                
        appimage_path = os.environ.get("APPIMAGE")
        if appimage_path:
            cmd = ["pkexec", "env"] + env_args + [appimage_path] + sys.argv[1:]
        else:
            cmd = ["pkexec", "env"] + env_args + [sys.executable, __file__] + sys.argv[1:]
        res = subprocess.run(cmd)
        sys.exit(res.returncode)
    except Exception:
        pass

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio

from gnome_theme_manager.window import GnomeThemeManagerWindow


class GnomeThemeManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.gnome.ThemeManager",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
    
    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = GnomeThemeManagerWindow(self)
        win.present()


def main():
    app = GnomeThemeManagerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
