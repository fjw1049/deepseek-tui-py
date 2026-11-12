"""Installed macOS app identities and icons for the permission picker."""
from __future__ import annotations

import base64
import io
import json
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
_LIST_WINDOWS = """ObjC.import('AppKit')
ObjC.import('CoreGraphics')
function run(argv) {
  const apps = $.NSWorkspace.sharedWorkspace.runningApplications
  const ids = {}
  for (let i = 0; i < apps.count; i++) {
    const app = apps.objectAtIndex(i)
    const id = ObjC.unwrap(app.bundleIdentifier)
    if (id && (!argv.length || id === argv[0])) ids[app.processIdentifier] = id
  }
  const all = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(17, 0))) || []
  const result = {}
  for (const w of all) {
    const id = ids[w.kCGWindowOwnerPID], b = w.kCGWindowBounds
    if (id && w.kCGWindowLayer === 0 && w.kCGWindowAlpha >= 0.5
        && b.Width >= 100 && b.Height >= 100)
      (result[id] ??= []).push([w.kCGWindowNumber, b.X, b.Y, b.Width, b.Height])
  }
  return JSON.stringify(argv.length ? (result[argv[0]] || []) : result)

}"""


# Same reading of a window as above, across all apps, front to back.
_FRONT_APPS = """ObjC.import('AppKit')
ObjC.import('CoreGraphics')
function run() {
  const all = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(17, 0))) || []
  const ids = []
  for (const w of all) {
    if (w.kCGWindowLayer !== 0 || w.kCGWindowAlpha < 0.5 || w.kCGWindowBounds.Width < 100
        || w.kCGWindowBounds.Height < 100) continue
    const app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(w.kCGWindowOwnerPID)
    const id = app.isNil() ? '' : ObjC.unwrap(app.bundleIdentifier) || ''
    if (id && !ids.includes(id)) ids.push(id)
  }
  return JSON.stringify(ids)
}"""


def on_screen_apps(limit: int = 5) -> list[str]:
    """Apps with a standard window on screen, front to back, without ones CUA can never use.

    Resuming from a panel always leaves the Workbench in front, so that app is never listed.
    """
    if sys.platform != "darwin":
        return []
    try:
        out = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", _FRONT_APPS],
                             capture_output=True, text=True, timeout=3)
        ids = json.loads(out.stdout) if out.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    return [app for app in ids if app.lower() not in BLOCKED][:limit]


def open_windows(bundle_id: str) -> list[tuple[int, int, int, int]] | None:
    """A running macOS app's standard on-screen windows, front to back, as (x, y, width,
    height) in points; None when unknown."""
    if sys.platform != "darwin" or not _BUNDLE_ID.fullmatch(bundle_id):
        return None
    try:
        out = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", _LIST_WINDOWS,
                              bundle_id], capture_output=True, text=True, timeout=3)
        return ([tuple(int(v) for v in bounds[1:]) for bounds in json.loads(out.stdout)]
                if out.returncode == 0 else None)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return None
