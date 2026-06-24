#!/usr/bin/env python3
"""Regenerate DeepSeek GUI dock/app icon with macOS-friendly padding."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICON_PATH = ROOT / 'src/asset/img/deepseek.png'
CANVAS = 1024
MARGIN_RATIO = 0.09
CORNER_RADIUS_RATIO = 0.225
LOGO_INNER_RATIO = 0.62


def main() -> None:
    source = Image.open(ICON_PATH).convert('RGBA')
    arr = np.array(source)
    white_mask = (
        (arr[:, :, 3] > 200)
        & (arr[:, :, 0] > 200)
        & (arr[:, :, 1] > 200)
        & (arr[:, :, 2] > 200)
    )
    coords = np.column_stack(np.where(white_mask))
    if coords.size == 0:
        raise SystemExit(f'No logo pixels found in {ICON_PATH}')

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)
    logo = source.crop((x0, y0, x1 + 1, y1 + 1))
    logo_arr = np.array(logo)
    logo_arr[:, :, 3] = white_mask[y0 : y1 + 1, x0 : x1 + 1].astype(np.uint8) * 255
    logo = Image.fromarray(logo_arr)

    canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    margin = int(CANVAS * MARGIN_RATIO)
    radius = int(CANVAS * CORNER_RADIUS_RATIO)
    draw.rounded_rectangle(
        [margin, margin, CANVAS - margin - 1, CANVAS - margin - 1],
        radius=radius,
        fill=(0, 0, 0, 255),
    )

    inner_w = CANVAS - 2 * margin
    target_logo_w = int(inner_w * LOGO_INNER_RATIO)
    scale = target_logo_w / logo.width
    target_logo_h = int(logo.height * scale)
    logo_scaled = logo.resize((target_logo_w, target_logo_h), Image.Resampling.LANCZOS)
    canvas.paste(
        logo_scaled,
        ((CANVAS - target_logo_w) // 2, (CANVAS - target_logo_h) // 2),
        logo_scaled,
    )
    canvas.save(ICON_PATH)
    print(f'Wrote {ICON_PATH} ({CANVAS}x{CANVAS})')


if __name__ == '__main__':
    main()
