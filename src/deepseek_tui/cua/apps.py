"""Installed macOS app identities and icons for the permission picker."""
from __future__ import annotations

import base64
import io
import plistlib
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

from .approval import HOST_APP_IDS

# These identities are refused by the runtime before an approval can help.
BLOCKED = HOST_APP_IDS | {
    "com.apple.terminal", "com.googlecode.iterm2", "com.openai.codex",
    "com.apple.usernotificationcenter",
}


def installed_apps() -> dict[str, tuple[str, Path, str]]:
    apps = {}
    for directory in (Path('/Applications'), Path('/Applications/Utilities'),
                      Path('/System/Applications'), Path('/System/Applications/Utilities'),
                      Path.home() / 'Applications'):
        for bundle in sorted(directory.glob('*.app')):
            try:
                info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
                identifier = info.get('CFBundleIdentifier')
                if not isinstance(identifier, str) or not identifier or identifier.startswith('-'):
                    continue
                name = info.get('CFBundleDisplayName') or info.get('CFBundleName') or bundle.stem
                apps.setdefault(identifier, (name, bundle, info.get('CFBundleIconFile', '')))
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
    return apps


def app_icon(bundle: Path, filename: str) -> str | None:
    if not filename:
        return None
    resources = (bundle / 'Contents/Resources').resolve()
    path = (resources / (filename if filename.endswith('.icns') else filename + '.icns')).resolve()
    if not path.is_relative_to(resources):
        return None
    try:
        with Image.open(path) as image:
            image.thumbnail((64, 64))
            out = io.BytesIO()
            image.convert('RGBA').save(out, 'PNG')
            return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')
    except (OSError, ValueError):
        return None


def available_apps() -> list[dict]:
    return [
        {'name': name, 'bundleId': identifier, 'icon': app_icon(bundle, icon),
         'blocked': identifier.lower() in BLOCKED}
        for identifier, (name, bundle, icon) in installed_apps().items()
    ]


def approved_app_icons(apps: list[dict]) -> list[dict]:
    installed = installed_apps()
    for app in apps:
        entry = installed.get(app.get('bundleId'))
        if entry:
            app['icon'] = app_icon(entry[1], entry[2])
    return apps


_BUNDLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
# Read-only and permission-free: window bounds need no screen-recording grant (titles would).
# On-screen layer-0 windows of at least 100x100, as the Workbench preview counts them, but only
# substantially opaque ones: windows fading in or out (opening, closing, sheets) stay listed
# at near-zero alpha for a moment and would be counted twice.
_COUNT_WINDOWS = """ObjC.import('AppKit')
ObjC.import('CoreGraphics')
function run(argv) {
  const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(argv[0])
  const pids = []
  for (let i = 0; i < apps.count; i++) pids.push(apps.objectAtIndex(i).processIdentifier)
  if (!pids.length) return '0'
  const all = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(17, 0))) || []
  return String(all.filter(w => pids.includes(w.kCGWindowOwnerPID) && w.kCGWindowLayer === 0
    && w.kCGWindowAlpha >= 0.5 && w.kCGWindowBounds.Width >= 100
    && w.kCGWindowBounds.Height >= 100).length)
}"""


def open_window_count(bundle_id: str) -> int | None:
    """How many standard windows a running macOS app shows on screen; None when unknown."""
    if sys.platform != "darwin" or not _BUNDLE_ID.fullmatch(bundle_id):
        return None
    try:
        out = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", _COUNT_WINDOWS,
                              bundle_id], capture_output=True, text=True, timeout=3)
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
