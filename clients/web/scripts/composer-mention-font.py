"""Writes src/assets/composer-mention.ttf, the font the composer draws its mentions with (components/composer.tsx).

It has one glyph, for U+E000, which the composer's text box holds in place of a mention's @. The glyph draws nothing
and is 1.25em wide, 20px at the composer's 16px: 1px before the 16px logo the composer draws there, and 3px after it.
Its ascent and descent are Geist's, so a line with a mention is as tall as any other.

    uv run --no-project --with fonttools python web/scripts/composer-mention-font.py
"""

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UNITS_PER_EM = 1000
WIDTH = 1250
# Geist's vertical metrics (@fontsource-variable/geist), typographic and Windows.
ASCENT, DESCENT = 1005, -295
WIN_ASCENT, WIN_DESCENT = 1088, 262
USE_TYPO_METRICS, REGULAR = 1 << 7, 1 << 6

font = FontBuilder(UNITS_PER_EM, isTTF=True)
font.setupGlyphOrder([".notdef", "mention"])
font.setupCharacterMap({0xE000: "mention"})
blank = TTGlyphPen(None).glyph()
font.setupGlyf({".notdef": blank, "mention": blank})
font.setupHorizontalMetrics({".notdef": (0, 0), "mention": (WIDTH, 0)})
font.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT, lineGap=0)
font.setupOS2(
    version=4,  # the first to define USE_TYPO_METRICS
    sTypoAscender=ASCENT,
    sTypoDescender=DESCENT,
    sTypoLineGap=0,
    usWinAscent=WIN_ASCENT,
    usWinDescent=WIN_DESCENT,
    fsSelection=USE_TYPO_METRICS | REGULAR,
)
font.setupNameTable({"familyName": "Composer Mention", "styleName": "Regular", "psName": "ComposerMention-Regular"})
font.setupPost()
font.save(Path(__file__).resolve().parent.parent / "src" / "assets" / "composer-mention.ttf")
