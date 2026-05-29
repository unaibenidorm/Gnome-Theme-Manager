import shutil
import subprocess

def get_distro_install_command(packages):
    """Returns the correct install command for the given packages based on the current distro."""
    try:
        with open("/etc/os-release") as f:
            os_release = f.read().lower()
    except Exception:
        os_release = ""
        
    if "ubuntu" in os_release or "debian" in os_release or "linuxmint" in os_release or "pop" in os_release:
        return f"sudo apt install -y {' '.join(packages)}"
    elif "fedora" in os_release or "rhel" in os_release or "centos" in os_release:
        return f"sudo dnf install -y {' '.join(packages)}"
    elif "arch" in os_release or "manjaro" in os_release or "endeavour" in os_release:
        return f"sudo pacman -S --noconfirm {' '.join(packages)}"
    elif "opensuse" in os_release or "suse" in os_release:
        return f"sudo zypper in -y {' '.join(packages)}"
    else:
        return f"sudo apt install {' '.join(packages)} # (or your distro's equivalent)"

def check_dependencies():
    """Returns a list of missing dependencies and the command to install them."""
    missing = []
    packages_to_install = []
    
    if not shutil.which("git"):
        missing.append("Git (Required for cloning themes)")
        packages_to_install.append("git")
        
    if not shutil.which("ffmpeg"):
        missing.append("FFmpeg (Required for video Plymouth themes)")
        packages_to_install.append("ffmpeg")
        
    # Check imagemagick (convert or magick)
    if not shutil.which("convert") and not shutil.which("magick"):
        missing.append("ImageMagick (Required for GIF Plymouth themes)")
        # In Arch it's imagemagick, in Ubuntu it's imagemagick, in Fedora it's ImageMagick
        packages_to_install.append("imagemagick")
        
    if not shutil.which("plymouth"):
        missing.append("Plymouth (Required for testing splash screens)")
        packages_to_install.append("plymouth")
        
    if not missing:
        return [], ""
        
    return missing, get_distro_install_command(packages_to_install)

def get_all_dependencies_status():
    """Returns a dictionary of all dependencies and whether they are installed."""
    return {
        "git": shutil.which("git") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "imagemagick": (shutil.which("convert") is not None) or (shutil.which("magick") is not None),
        "plymouth": shutil.which("plymouth") is not None,
        "pkexec": shutil.which("pkexec") is not None,
        "tar": shutil.which("tar") is not None
    }
