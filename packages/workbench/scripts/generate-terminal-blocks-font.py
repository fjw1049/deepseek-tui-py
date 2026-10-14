"""Generate the terminal block-elements font (U+2580-259F, minus shades).

The bundled JetBrains Mono subsets have no block elements, so xterm's DOM
renderer falls back to a font whose glyphs don't fill the cell and leaves
background stripes (e.g. around Claude Code's mascot). These glyphs are plain
rectangles on JetBrains Mono's exact metrics, so they span the full cell.

Usage: python3 scripts/generate-terminal-blocks-font.py  (needs fonttools)
"""

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

# JetBrains Mono metrics (hhea/typo): advance 600, ascent 1020, descent -300.
UPEM, WIDTH, ASCENT, DESCENT = 1000, 600, 1020, -300
# Edges on the cell boundary overshoot by ~0.15px at 13px so anti-aliased
# neighbours overlap instead of leaving hairline seams.
BLEED = 12
OUT = Path(__file__).resolve().parent.parent / 'src/renderer/src/assets/fonts/terminal-blocks.woff'


def x(frac: float) -> int:
    return round(WIDTH * frac) + (-BLEED if frac == 0 else BLEED if frac == 1 else 0)


def y(frac: float) -> int:
    return round(DESCENT + (ASCENT - DESCENT) * frac) + (-BLEED if frac == 0 else BLEED if frac == 1 else 0)


# Rectangles as (left, bottom, right, top) fractions of the cell.
R, T = (0.5, 0, 1, 1), (0, 0.5, 1, 1)
UL, UR, LL, LR = (0, 0.5, 0.5, 1), (0.5, 0.5, 1, 1), (0, 0, 0.5, 0.5), (0.5, 0, 1, 0.5)
BLOCKS: dict[int, list[tuple[float, float, float, float]]] = {
    0x2580: [T],
    **{0x2580 + n: [(0, 0, 1, n / 8)] for n in range(1, 9)},  # ▁..█ lower eighths
    **{0x2588 + n: [(0, 0, (8 - n) / 8, 1)] for n in range(1, 8)},  # ▉..▏ left eighths
    0x2590: [R],
    0x2594: [(0, 7 / 8, 1, 1)],
    0x2595: [(7 / 8, 0, 1, 1)],
    0x2596: [LL],
    0x2597: [LR],
    0x2598: [UL],
    0x2599: [UL, LL, LR],
    0x259A: [UL, LR],
    0x259B: [UL, UR, LL],
    0x259C: [UL, UR, LR],
    0x259D: [UR],
    0x259E: [UR, LL],
    0x259F: [UR, LL, LR],
}


def glyph(rects):
    pen = TTGlyphPen(None)
    for left, bottom, right, top in rects:
        pen.moveTo((x(left), y(bottom)))
        pen.lineTo((x(left), y(top)))
        pen.lineTo((x(right), y(top)))
        pen.lineTo((x(right), y(bottom)))
        pen.closePath()
    return pen.glyph()


def main() -> None:
    names = ['.notdef'] + [f'uni{code:04X}' for code in BLOCKS]
    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({code: f'uni{code:04X}' for code in BLOCKS})
    fb.setupGlyf({'.notdef': TTGlyphPen(None).glyph(), **{f'uni{c:04X}': glyph(r) for c, r in BLOCKS.items()}})
    # lsb must equal each glyph's xMin or renderers shift right-side blocks left.
    fb.setupHorizontalMetrics({
        '.notdef': (WIDTH, 0),
        **{f'uni{c:04X}': (WIDTH, min(x(rect[0]) for rect in r)) for c, r in BLOCKS.items()},
    })
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT, lineGap=0)
    fb.setupNameTable({'familyName': 'DS Terminal Blocks', 'styleName': 'Regular'})
    fb.setupOS2(version=4, sTypoAscender=ASCENT, sTypoDescender=DESCENT, sTypoLineGap=0,
                usWinAscent=ASCENT, usWinDescent=-DESCENT, fsSelection=0x40 | 0x80)
    fb.setupPost(isFixedPitch=1)
    fb.font.flavor = 'woff'
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(OUT))
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes, {len(BLOCKS)} glyphs)')


if __name__ == '__main__':
    main()
