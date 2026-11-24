"""Regenerate the logo SVGs.

    pip install fonttools brotli
    (cd frontend && npm ci)
    python assets/build_logo.py

The wordmark is Hanken Grotesk (SIL Open Font License) at weight 750, converted
to outlines so the SVGs render the same everywhere.
"""

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "frontend/node_modules/@fontsource-variable/hanken-grotesk/files/hanken-grotesk-latin-wght-normal.woff2"

INK, PAPER = "#1c1a2b", "#f5f3ee"
# Same platform colours the app uses (frontend/src/styles.css).
SEGMENTS = ["#05ce78", "#ffd508", "#d6106b", "#5b4bdb"]

HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} 48" width="{w}" height="48" '
    'role="img" aria-label="crowdtracker">\n  <title>crowdtracker</title>\n'
)


def mark(tile: str, fg: str) -> str:
    """A slip track: promised ring, a bar in platform colours, the latest-estimate dot."""
    parts = [
        f'  <rect width="48" height="48" rx="11" fill="{tile}"/>',
        f'  <circle cx="10.5" cy="24" r="4.5" fill="none" stroke="{fg}" stroke-width="2.5"/>',
    ]
    x = 17.0
    for colour in SEGMENTS:
        parts.append(f'  <rect x="{x:.1f}" y="21" width="3" height="6" rx="1" fill="{colour}"/>')
        x += 3.8
    parts.append(f'  <circle cx="38.5" cy="24" r="6.5" fill="{fg}"/>')
    return "\n".join(parts)


def wordmark(text: str, x0: float, baseline: float, size: float) -> tuple[str, float]:
    font = instantiateVariableFont(TTFont(FONT), {"wght": 750})
    glyphs, cmap, upm = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
    scale, tracking = size / upm, -0.02 * upm
    pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    x = 0.0
    for ch in text:
        name = cmap[ord(ch)]
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x0 + x * scale, baseline)))
        x += font["hmtx"][name][0] + tracking
    return pen.getCommands(), x0 + (x - tracking) * scale


def main() -> None:
    icon = HEAD.format(w=48) + mark(INK, PAPER) + "\n</svg>\n"
    (ROOT / "assets/mark.svg").write_text(icon)
    (ROOT / "frontend/public/favicon.svg").write_text(icon)

    path, right = wordmark("crowdtracker", x0=60, baseline=34.5, size=30)
    width = round(right) + 2
    for name, tile, fg, text in (("logo.svg", INK, PAPER, INK), ("logo-dark.svg", PAPER, INK, PAPER)):
        svg = HEAD.format(w=width) + mark(tile, fg) + f'\n  <path fill="{text}" d="{path}"/>\n</svg>\n'
        (ROOT / "assets" / name).write_text(svg)


if __name__ == "__main__":
    main()
