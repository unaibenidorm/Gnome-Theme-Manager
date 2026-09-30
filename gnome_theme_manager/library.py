"""Persistent, user-owned data for library features."""
import json
import os
import tempfile
import base64
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path.home() / ".config" / "gnome-theme-manager" / "library.json"

def _load():
    try:
        with DATA_FILE.open(encoding="utf-8") as stream:
            data = json.load(stream)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def _save(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=DATA_FILE.parent, prefix=".library-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(name, DATA_FILE)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass

def _key(name, category):
    return f"{category}:{name}".lower()

def favorites():
    return _load().get("favorites", [])

def is_favorite(name, category):
    return any(item.get("key") == _key(name, category) for item in favorites())

def toggle_favorite(theme, category):
    data = _load()
    entries = data.setdefault("favorites", [])
    key = _key(theme.get("name", ""), category)
    for item in entries[:]:
        if item.get("key") == key:
            entries.remove(item)
            _save(data)
            return False
    entries.append({"key": key, "name": theme.get("name", ""), "category": category,
                    "content_id": theme.get("id", ""), "url": theme.get("downloadlink1", ""), "added": _timestamp()})
    _save(data)
    return True

def remove_favorite(name, category):
    data = _load()
    key = _key(name, category)
    entries = data.get("favorites", [])
    data["favorites"] = [item for item in entries if item.get("key") != key]
    _save(data)

def record_install(name, category, source_url, scope, download_path="", content_id=""):
    data = _load()
    item = {"name": name, "category": category, "source_url": source_url,
            "download_path": download_path, "content_id": content_id, "scope": scope, "installed_at": _timestamp()}
    data.setdefault("history", []).insert(0, item)
    data["history"] = data["history"][:100]
    if source_url:
        data.setdefault("sources", {})[_key(name, category)] = source_url
    _save(data)

def history():
    return _load().get("history", [])

def clear_history():
    data = _load()
    data["history"] = []
    _save(data)

def export_share_code(entries):
    """Create a portable code containing only public theme IDs/categories."""
    themes = [{"id": str(item.get("content_id", "")), "category": item.get("category", "")}
              for item in entries if item.get("content_id") and item.get("category")]
    payload = json.dumps({"version": 1, "themes": themes}, separators=(",", ":")).encode()
    return "GTM1-" + base64.urlsafe_b64encode(payload).decode().rstrip("=")

def import_share_code(code):
    code = code.strip()
    if not code.startswith("GTM1-"):
        raise ValueError("Invalid sharing code")
    encoded = code[5:]
    try:
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        themes = data.get("themes", [])
    except (ValueError, json.JSONDecodeError):
        raise ValueError("Invalid sharing code")
    if not isinstance(themes, list) or len(themes) > 50:
        raise ValueError("Invalid sharing code")
    return [item for item in themes if isinstance(item, dict) and item.get("id") and item.get("category")]

def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
