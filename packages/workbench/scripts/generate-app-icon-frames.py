#!/usr/bin/env python3
"""Generate dock-icon animation frames: largest ↔ smallest diagonal swap."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'src/asset/img/app-icon-anim'
CANVAS = 256  # dock cycles; macOS scales up
FRAME_COUNT = 24
# Match in-app timing: hold ~18%, ease across, hold, ease back.
HOLD = 0.18
CROSS_END = 0.50
HOLD_B_END = 0.68

# Geometry from app-icon.svg, scaled to CANVAS / 1024.
S = CANVAS / 1024.0
TL = (382.0 * S, 382.0 * S)
BR = (681.661 * S, 681.661 * S)
LARGE = 260.0 * S
MID = 180.678 * S
SMALL = 127.797 * S
RX_RATIO = 0.24


def ease(t: str | float) -> float:
    """cubic-bezier(0.65, 0, 0.35, 1) approx via smoothstep on clipped t."""
    t = max(0.0, min(1.0, float(t)))
    # smootherstep
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


def lerp_color(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return (
        int(round(lerp(a[0], b[0], t))),
        int(round(lerp(a[1], b[1], t))),
        int(round(lerp(a[2], b[2], t))),
    )


def draw_squircle(draw: ImageDraw.ImageDraw) -> None:
    # Approximate the SVG squircle with a rounded rect matching deepseek.png.
    margin = int(CANVAS * 0.0625)  # 64/1024
    radius = int(CANVAS * 0.225)
    draw.rounded_rectangle(
        [margin, margin, CANVAS - margin - 1, CANVAS - margin - 1],
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


def render_frame(t: float) -> Image.Image:
    img = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_squircle(draw)

    # Static mid grays
    draw_cell(draw, BR[0], TL[1], MID, (170, 170, 170))
    draw_cell(draw, TL[0], BR[1], MID, (170, 170, 170))

    # Pair A: white large at TL → shrinks to BR
    ax = lerp(TL[0], BR[0], t)
    ay = lerp(TL[1], BR[1], t)
    asize = lerp(LARGE, SMALL, t)
    draw_cell(draw, ax, ay, asize, (255, 255, 255))

    # Pair B: dark small at BR → grows to TL
    bx = lerp(BR[0], TL[0], t)
    by = lerp(BR[1], TL[1], t)
    bsize = lerp(SMALL, LARGE, t)
    draw_cell(draw, bx, by, bsize, (100, 100, 100))

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob('frame-*.png'):
        old.unlink()

    for i in range(FRAME_COUNT):
        t = progress(i)
        path = OUT_DIR / f'frame-{i:02d}.png'
        render_frame(t).save(path, 'PNG')
        print(f'Wrote {path} (t={t:.3f})')

    # Sanity: frame 0 should match rest pose closely
    print(f'Done: {FRAME_COUNT} frames → {OUT_DIR}')


if __name__ == '__main__':
    main()
