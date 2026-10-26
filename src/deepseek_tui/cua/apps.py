"""Installed macOS app identities and icons for the permission picker."""
from __future__ import annotations

import base64
import io
import plistlib
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
                      Path('/System/Applications'), Path.home() / 'Applications'):
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
