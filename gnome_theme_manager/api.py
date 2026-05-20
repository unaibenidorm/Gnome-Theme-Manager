"""
OCS API Client for gnome-look.org (Pling/OpenDesktop)
"""
import json, os, hashlib, threading, re, html, collections, time
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
    "cursors":  {"id": "107", "title": "Cursor Themes",       "icon": "input-mouse-symbolic",                   "count": 780,  "system_only": False},
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

# LRU-bounded image cache to prevent unbounded memory growth
_MAX_CACHE_ENTRIES = 200
IMAGE_CACHE = collections.OrderedDict()
CACHE_LOCK = threading.Lock()
API_SEMAPHORE = threading.Semaphore(3)  # Max 3 concurrent requests to avoid rate-limiting

THEME_CACHE_FILE = Path.home() / ".config" / "gnome-theme-manager" / "themes_cache.json"

def load_theme_cache():
    if THEME_CACHE_FILE.exists():
        try:
            with open(THEME_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_theme_cache(cache_data):
    THEME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(THEME_CACHE_FILE, "w") as f:
            json.dump(cache_data, f)
    except Exception:
        pass

def _make_request(url, timeout=30, retries=3):
    try: url = quote(url, safe=':/?&=#+%@')
    except Exception: pass
    
    with CACHE_LOCK:
        if url in IMAGE_CACHE:
            IMAGE_CACHE.move_to_end(url)
            return IMAGE_CACHE[url]
    
    user_agents = [
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]
    
    last_error = None
    # Wrap in semaphore to avoid rate-limiting from parallel card image loads
    with API_SEMAPHORE:
        for attempt in range(retries):
            req = Request(url)
            req.add_header("User-Agent", user_agents[attempt % len(user_agents)])
            req.add_header("Accept", "application/json, text/html, */*")
            req.add_header("Accept-Language", "en-US,en;q=0.9")
            req.add_header("Connection", "keep-alive")
            try:
                with urlopen(req, timeout=timeout) as r:
                    data = r.read()
                    if len(data) < 5_000_000:
                        with CACHE_LOCK:
                            IMAGE_CACHE[url] = data
                            while len(IMAGE_CACHE) > _MAX_CACHE_ENTRIES:
                                IMAGE_CACHE.popitem(last=False)
                    return data
            except (URLError, HTTPError, TimeoutError, OSError) as e:
                last_error = e
                if attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                continue
    if last_error:
        print(f"[API] {last_error}")
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

def _is_github_archive_url(url):
    """Check if a URL is a direct GitHub/GitLab archive download (not a repo page)."""
    lower = url.lower()
    # Direct archive download patterns
    archive_patterns = [
        "/archive/refs/",       # github.com/user/repo/archive/refs/heads/main.zip
        "/archive/master",      # github.com/user/repo/archive/master.zip
        "/archive/main",        # github.com/user/repo/archive/main.zip
        "/archive/v",           # github.com/user/repo/archive/v1.0.zip (tags)
        "/-/archive/",          # gitlab.com/user/repo/-/archive/main/repo-main.zip
        "/releases/download/",  # github.com/user/repo/releases/download/v1.0/file.zip
    ]
    for pattern in archive_patterns:
        if pattern in lower:
            return True
    # Also check if the URL ends in a known archive extension
    for ext in (".zip", ".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".tar"):
        if lower.endswith(ext):
            return True
    return False

def _is_git_repo_url(url):
    """Check if a URL points to a GitHub/GitLab repository page (not a download)."""
    lower = url.lower()
    if "github.com" not in lower and "gitlab.com" not in lower:
        return False
    # If it's an archive/release download, it's NOT a repo URL
    if _is_github_archive_url(lower):
        return False
    return True

def download_theme_file(download_url, dest_path, progress_callback=None):
    try:
        req = Request(download_url)
        req.add_header("User-Agent", "GnomeThemeManager/2.0")
        with urlopen(req, timeout=120) as response:
            final_url = response.url
            
            # Check if we got redirected to a GitHub/GitLab repo page
            # (not an archive download)
            if _is_git_repo_url(final_url):
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
