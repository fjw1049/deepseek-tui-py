#!/usr/bin/env python3
"""Generate dock-icon assets: rest PNG + largest ↔ smallest diagonal swap frames.

macOS Dock expects ~80% artwork on a transparent canvas so the icon matches
other apps optically. Cell layout is the app-icon.svg design, mapped into that
content box.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'src/asset/img/app-icon-anim'
REST_PNG = ROOT / 'src/asset/img/deepseek.png'

# Dock / Finder optical size (Apple-style inset ≈ 80% of canvas).
CONTENT = 0.80
FRAME_COUNT = 24
# Match in-app timing: hold ~18%, ease across, hold, ease back.
HOLD = 0.18
CROSS_END = 0.50
HOLD_B_END = 0.68

# Original design plate was inset 64/1024 (87.5% fill). Cell centers/sizes are
# expressed as fractions of that plate, then placed in the 80% content box.
_PLATE0 = 896.0
_TL_F = ((382.0 - 64.0) / _PLATE0, (382.0 - 64.0) / _PLATE0)
_BR_F = ((681.661 - 64.0) / _PLATE0, (681.661 - 64.0) / _PLATE0)
_LARGE_F = 260.0 / _PLATE0
_MID_F = 180.678 / _PLATE0
_SMALL_F = 127.797 / _PLATE0
RX_RATIO = 0.24


def ease(t: str | float) -> float:
    """cubic-bezier(0.65, 0, 0.35, 1) approx via smootherstep on clipped t."""
    t = max(0.0, min(1.0, float(t)))
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def progress(frame: int) -> float:
    """0 → TL-large/BR-small, 1 → TL-small-dark/BR-large-white (roles via lerp)."""
    u = frame / FRAME_COUNT
    if u <= HOLD:
        return 0.0
    if u < CROSS_END:
        return ease((u - HOLD) / (CROSS_END - HOLD))
    if u <= HOLD_B_END:
        return 1.0
    return 1.0 - ease((u - HOLD_B_END) / (1.0 - HOLD_B_END))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def layout(canvas: int) -> tuple[tuple[float, float], tuple[float, float], float, float, float, int, float]:
    margin = canvas * (1.0 - CONTENT) / 2.0
    plate = canvas * CONTENT
    tl = (margin + _TL_F[0] * plate, margin + _TL_F[1] * plate)
    br = (margin + _BR_F[0] * plate, margin + _BR_F[1] * plate)
    return tl, br, _LARGE_F * plate, _MID_F * plate, _SMALL_F * plate, int(round(margin)), plate


def draw_squircle(draw: ImageDraw.ImageDraw, canvas: int, margin: int, plate: float) -> None:
    # Corner radius ≈ original SVG squircle feel on the content box.
    radius = int(round(plate * 0.257))  # ~225/896 of plate
    draw.rounded_rectangle(
        [margin, margin, canvas - margin - 1, canvas - margin - 1],
        radius=radius,
        fill=(0, 0, 0, 255),
    )


def draw_cell(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    size: float,
    fill: tuple[int, int, int],
) -> None:
    half = size / 2.0
    rx = size * RX_RATIO
    draw.rounded_rectangle(
        [cx - half, cy - half, cx + half, cy + half],
        radius=rx,
        fill=(*fill, 255),
    )


def render_frame(canvas: int, t: float) -> Image.Image:
    tl, br, large, mid, small, margin, plate = layout(canvas)
    img = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_squircle(draw, canvas, margin, plate)

    draw_cell(draw, br[0], tl[1], mid, (170, 170, 170))
    draw_cell(draw, tl[0], br[1], mid, (170, 170, 170))

    ax = lerp(tl[0], br[0], t)
    ay = lerp(tl[1], br[1], t)
    asize = lerp(large, small, t)
    draw_cell(draw, ax, ay, asize, (255, 255, 255))

    bx = lerp(br[0], tl[0], t)
    by = lerp(br[1], tl[1], t)
    bsize = lerp(small, large, t)
    draw_cell(draw, bx, by, bsize, (100, 100, 100))

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob('frame-*.png'):
        old.unlink()

    # Rest pose for Dock / electron-builder (1024 master).
    rest = render_frame(1024, 0.0)
    rest.save(REST_PNG, 'PNG')
    print(f'Wrote {REST_PNG} (80% content box)')

    for i in range(FRAME_COUNT):
        t = progress(i)
        path = OUT_DIR / f'frame-{i:02d}.png'
        render_frame(256, t).save(path, 'PNG')
        print(f'Wrote {path} (t={t:.3f})')

    print(f'Done: rest PNG + {FRAME_COUNT} frames → {OUT_DIR}')


if __name__ == '__main__':
    main()
