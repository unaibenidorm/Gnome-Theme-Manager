"""
OCS API Client for gnome-look.org (Pling/OpenDesktop)
"""
import json, os, hashlib, threading, re, html
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import URLError, HTTPError

API_BASE = "https://api.gnome-look.org/ocs/v1"
STORE_BASE = "https://www.gnome-look.org"

CATEGORIES = {
    "gtk":      {"id": "135", "title": "GTK3/4 Themes",      "icon": "preferences-desktop-wallpaper-symbolic", "count": 1613, "system_only": False},
    "shell":    {"id": "134", "title": "GNOME Shell Themes",  "icon": "preferences-desktop-appearance-symbolic", "count": 490,  "system_only": False},
    "icons":    {"id": "132", "title": "Icon Themes",         "icon": "folder-symbolic",                        "count": 1826, "system_only": False},
    "gdm":      {"id": "131", "title": "GDM Themes",          "icon": "system-users-symbolic",                  "count": 2074, "system_only": False},
    "grub":     {"id": "109", "title": "GRUB Themes",         "icon": "drive-harddisk-symbolic",                "count": 558,  "system_only": True},
    "plymouth": {"id": "108", "title": "Plymouth Themes",     "icon": "video-display-symbolic",                 "count": 572,  "system_only": True},
}

SORT_MODES = {"newest": "new", "rating": "score", "downloads": "down", "alphabetical": "alpha"}

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gnome-theme-manager"
THUMBNAIL_CACHE = CACHE_DIR / "thumbnails"

def ensure_cache_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_CACHE.mkdir(parents=True, exist_ok=True)

IMAGE_CACHE = {}
CACHE_LOCK = threading.Lock()

def _make_request(url, timeout=15):
    try: url = quote(url, safe=':/?&=#+%@')
    except Exception: pass
    
    with CACHE_LOCK:
        if url in IMAGE_CACHE: return IMAGE_CACHE[url]
    req = Request(url)
    req.add_header("User-Agent", "GnomeThemeManager/2.0")
    try:
        with urlopen(req, timeout=timeout) as r:
            data = r.read()
            if len(data) < 5_000_000:
                with CACHE_LOCK: IMAGE_CACHE[url] = data
            return data
    except (URLError, HTTPError) as e:
        print(f"[API] {e}")
        return None

def strip_html(text):
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def fetch_content_list(category_id, page=0, pagesize=20, sort_mode="new", search=""):
    params = {"categories": category_id, "page": page, "pagesize": pagesize, "sortmode": sort_mode, "format": "json"}
    if search:
        params["search"] = search
    url = f"{API_BASE}/content/data?{urlencode(params)}"
    data = _make_request(url)
    if not data:
        return [], 0
    try:
        result = json.loads(data)
        total = int(result.get("totalitems", 0))
        items = result.get("data", [])
        if isinstance(items, dict):
            items = [items]
        return items, total
    except Exception as e:
        print(f"[Parse] {e}")
        return [], 0

def fetch_content_detail(content_id):
    url = f"{API_BASE}/content/data/{content_id}?format=json"
    data = _make_request(url)
    if not data:
        return None
    try:
        result = json.loads(data)
        items = result.get("data", [])
        if isinstance(items, list) and items:
            return items[0]
        return items if isinstance(items, dict) else None
    except Exception:
        return None

def get_preview_urls(item):
    """Get all preview image URLs from a theme item."""
    urls = []
    for i in range(1, 7):
        url = item.get(f"previewpic{i}", "")
        if url:
            urls.append(url)
    return urls

def download_theme_file(download_url, dest_path, progress_callback=None):
    try:
        req = Request(download_url)
        req.add_header("User-Agent", "GnomeThemeManager/2.0")
        with urlopen(req, timeout=120) as response:
            final_url = response.url
            if ("github.com" in final_url or "gitlab.com" in final_url) and "releases/download" not in final_url and "archive" not in final_url and not any(final_url.endswith(e) for e in (".zip", ".tar.gz", ".tar.xz", ".tar.bz2")):
                return final_url
                
            total = int(response.headers.get("Content-Length", 0))
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)
        return True
    except Exception as e:
        print(f"[DL] {e}")
        return False

def get_theme_web_url(content_id):
    return f"{STORE_BASE}/p/{content_id}"
