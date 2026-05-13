# 🎨 Gnome Theme Manager

![Python](https://img.shields.io/badge/Python-3.x-blue?style=for-the-badge&logo=python) ![GTK4](https://img.shields.io/badge/GTK-4.0-green?style=for-the-badge&logo=gtk) ![Libadwaita](https://img.shields.io/badge/Libadwaita-1.x-purple?style=for-the-badge&logo=gnome) ![License](https://img.shields.io/badge/License-GPLv3-blue?style=for-the-badge)

A modern, native GTK4/Libadwaita application designed to seamlessly browse, download, install, and apply GNOME themes and customizations directly from [gnome-look.org](https://www.gnome-look.org/).

> **⚠️ DISCLAIMER: BETA SOFTWARE**  
> This software is currently in **Beta**. It is under active development and you may encounter unexpected bugs, crashes, or incomplete features. Use it at your own risk, especially when applying system-wide themes.

<p align="center">
  <i><img width="1099" height="749" alt="image" src="https://github.com/user-attachments/assets/5b86a963-b28d-4d37-8e9e-792ad65ce8d4" /></i>
</p>

## ✨ Features

- **Browse 6 theme categories**: GTK3/4, GNOME Shell, Icons, GDM, GRUB, and Plymouth.
- **Preview & Explore**: View thumbnail previews loaded directly from gnome-look.org.
- **Search & Filter**: Search across all themes, sort by newest, top-rated, most downloaded, or alphabetical order.
- **Pagination**: Smoothly browse through massive theme catalogs.
- **One-Click Install & Apply**: 
  - Install locally (for the current user) or globally (system-wide using PolicyKit/pkexec).
  - Apply GTK, Shell, and Icon themes dynamically without using GNOME Tweaks.
  - Automatically configure GRUB and Plymouth configurations after installation.
- **Extension Safety**: Automatically checks if the required "User Themes" extension is installed and active.
- **Manage Installed Themes**: Easily review, apply, undo, or uninstall previously downloaded themes.

## 📦 Dependencies

To run Gnome Theme Manager, you need Python 3 and the PyGObject bindings for GTK4 and Libadwaita.

```bash
# Fedora/RHEL
sudo dnf install python3 python3-gobject gtk4 libadwaita polkit

# Ubuntu/Debian
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 polkitd

# Arch Linux
sudo pacman -S python python-gobject gtk4 libadwaita polkit
```

## 🚀 Installation & Running

### Using AppImage (Recommended)
You can download the standalone **AppImage** from the [Releases](../../releases) page. Just download it, make it executable, and run it:
```bash
chmod +x Gnome-Theme-Manager-*.AppImage
./Gnome-Theme-Manager-*.AppImage
```

### Running from source

```bash
git clone https://github.com/yourusername/Gnome-Theme-Manager.git
cd Gnome-Theme-Manager
./Gnome\ Theme\ Manager
# OR
python3 gnome-theme-manager.py
```

## 📂 Project Structure

```text
Gnome-Theme-Manager/
├── gnome-theme-manager.py          # Entry point
├── gnome-theme-manager.desktop     # Desktop file
├── gnome_theme_manager/            # Core Module
│   ├── __init__.py
│   ├── api.py                      # OCS API client (gnome-look.org)
│   ├── installer.py                # Theme installation, pkexec, and apply logic
│   ├── detail.py                   # Theme detail view & variants
│   ├── widgets.py                  # Custom GTK templates and widgets
│   ├── window.py                   # Main GTK4 application window
│   └── style.css                   # Custom CSS styling
└── README.md                       # This file
```

## 🗂️ Theme Installation Paths

The application intelligently detects your system structure to place files where they belong:

| Type | Local (User) | System (Global) |
|------|-------------|-----------------|
| **GTK3/4 / GDM** | `~/.themes/` | `/usr/share/themes/` |
| **GNOME Shell** | `~/.themes/` | `/usr/share/themes/` |
| **Icons & Cursors** | `~/.icons/` | `/usr/share/icons/` |
| **GRUB** | *N/A* | `/boot/grub/themes/` or `/boot/grub2/themes/` |
| **Plymouth** | *N/A* | `/usr/share/plymouth/themes/` |

## 💡 Important Notes

- **GNOME Shell Themes**: Applying custom shell themes requires the **User Themes** extension. The app checks for it automatically. If it says it's missing, install it manually:
  - **Ubuntu/Debian:** `sudo apt install gnome-shell-extension-user-theme`
  - **Fedora:** `sudo dnf install gnome-shell-extension-user-theme`
  - **Arch Linux:** `sudo pacman -S gnome-shell-extensions`
- **System-wide Installations**: Installing Plymouth, GRUB, or system-wide GTK themes will prompt for an administrator password via Polkit (`pkexec`). It will safely extract the files into protected system directories.
- **Bootloader Updates**: GRUB themes automatically trigger `update-grub` / `grub2-mkconfig`. Plymouth themes automatically trigger `update-initramfs -u` or `dracut -f` as appropriate for your distribution.
