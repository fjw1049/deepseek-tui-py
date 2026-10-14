"""Read only explicitly selected Chrome cookies, in a disposable subprocess.

The parent receives credentials over a private pipe, never a tool result or log.
Only a temporary SQLite snapshot is modified; Chrome's database is read-only.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


def chrome_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Google/Chrome"
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "Google/Chrome/User Data"
        )
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "google-chrome"


def cookie_file(profile: str) -> Path:
    if not profile or Path(profile).name != profile or profile in {".", ".."}:
        raise ValueError("Invalid Chrome profile")
    root = chrome_root().resolve()
    directory = (root / profile).resolve()
    if directory.parent != root:
        raise ValueError("Invalid Chrome profile")
    for relative in ("Network/Cookies", "Cookies"):
        path = directory / relative
        if path.is_file() and path.resolve().is_relative_to(directory):
            return path
    raise FileNotFoundError("Chrome cookies unavailable")


def profiles() -> list[dict[str, str]]:
    root = chrome_root()
    try:
        info = (
            json.loads((root / "Local State").read_text()).get("profile", {}).get("info_cache", {})
        )
    except (OSError, ValueError):
        info = {}
    candidates = {"Default", *info.keys()}
    if root.is_dir():
        candidates.update(p.name for p in root.glob("Profile *") if p.is_dir())
    result = []
    for name in sorted(candidates):
        try:
            cookie_file(name)
        except (OSError, ValueError):
            continue
        result.append({"id": name, "name": str(info.get(name, {}).get("name") or name)})
    return result


def read_chrome(profile: str) -> dict:
    import browser_cookie3

    source = cookie_file(profile)
    with tempfile.TemporaryDirectory(prefix="deepseek-cookie-import-") as temporary:
        snapshot = Path(temporary) / "Cookies"
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=2) as original:
            with sqlite3.connect(snapshot) as copy:
                original.backup(copy)
        with sqlite3.connect(snapshot) as copy:
            copy.row_factory = sqlite3.Row
            rows = copy.execute("SELECT rowid AS cookie_rowid, * FROM cookies").fetchall()
            metadata, skipped = {}, 0
            for row in rows:
                data = dict(row)
                # CookieJar cannot represent partition keys. Never flatten them into
                # ordinary cookies, including when their name/path collide.
                partitioned = bool(data.get("top_frame_site_key"))
                if partitioned:
                    copy.execute("DELETE FROM cookies WHERE rowid=?", (data["cookie_rowid"],))
                    skipped += 1
                else:
                    metadata[(data["host_key"], data["path"], data["name"])] = data
            copy.commit()
        if not metadata:
            return {"cookies": [], "skipped": skipped}
        jar = browser_cookie3.chrome(
            cookie_file=str(snapshot), key_file=str(chrome_root() / "Local State")
        )
        cookies = []
        for cookie in jar:
            if cookie.expires is not None and cookie.expires <= time.time():
                continue
            data = metadata[(cookie.domain, cookie.path, cookie.name)]
            item = {
                "name": cookie.name,
                "value": cookie.value,
                "path": cookie.path,
                "secure": bool(cookie.secure),
                "httpOnly": bool(data.get("is_httponly")),
            }
            if cookie.domain.startswith("."):
                item["domain"] = cookie.domain
            else:
                item["url"] = (
                    ("https" if cookie.secure else "http") + "://" + cookie.domain + cookie.path
                )
            if cookie.expires is not None:
                item["expires"] = cookie.expires
            same_site = {0: "None", 1: "Lax", 2: "Strict"}.get(data.get("samesite"))
            if same_site:
                item["sameSite"] = same_site
            cookies.append(item)
        return {"cookies": cookies, "skipped": skipped}


if __name__ == "__main__":
    try:
        result = read_chrome(sys.argv[1])
    except Exception:
        # Keychain denial, locked database, unsupported encryption and missing
        # dependencies must never echo a credential or database content.
        result = {"error": "unavailable"}
    print(json.dumps(result))
