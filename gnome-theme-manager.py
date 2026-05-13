#!/usr/bin/env python3
"""
Gnome Theme Manager - Entry Point
Browse, download and install GNOME themes from gnome-look.org
"""
import sys
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
