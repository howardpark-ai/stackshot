"""Rebuild the installed app's PNG icons in icons/ from the board's mark (_ICON in web/app.py, the same SVG as
<state>/site/favicon.svg). The server serves the committed PNGs as they are and needs no renderer; run this only when
the mark changes, and commit the PNGs with it:

    uv run --locked tools/make_icons.py

Every PNG is full bleed and opaque: the mark's tile colour to the edges, no rounded or transparent corners, and the
check drawn from the mark's own path and stroke, so it matches the favicon. The launcher or iOS rounds the corners itself.

  icon-192.png, icon-512.png   the check at the size and place it has in the favicon's tile: manifest purpose "any"
  apple-touch-icon.png (180)   the same, at 180
  icon-maskable-512.png        the check scaled by MASKABLE_SCALE about the centre, so its whole stroke sits inside the
                               80% safe circle with room to spare: manifest purpose "maskable"
"""
import base64, pathlib, re, sys
import resvg_py

ROOT = pathlib.Path(__file__).resolve().parents[2]
# The check's farthest stroke point from the centre (32, 32) is the round cap at (49, 20): 20.8 + 4 (half the stroke) = 24.8
# units. The maskable safe zone is the circle of radius 25.6 (80% of 64, halved); at 0.8 the cap reaches 19.8, 5.8 inside it.
MASKABLE_SCALE = 0.8

m = re.search(r'^_ICON = "data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)"', (ROOT / "stackshot" / "web" / "app.py").read_text(encoding="utf-8"), re.M)
if not m:
    sys.exit("make_icons: _ICON not found in web/app.py")
MARK = base64.b64decode(m.group(1)).decode("utf-8").strip()
inner = re.fullmatch(r'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">(.*)</svg>', MARK, re.S)
if not inner:
    sys.exit("make_icons: the mark is no longer a 64x64 SVG; update this script with it")
BODY = inner.group(1)
tile = re.search(r'<rect [^>]*fill="(#[0-9a-fA-F]{6})"[^>]*/>', BODY)
if not tile:
    sys.exit("make_icons: the mark has no tile <rect>; update this script with it")
TILE = tile.group(1)                                         # the tile's colour (#1f1f21): every icon's whole background
CHECK = BODY.replace(tile.group(0), "", 1)                   # the mark without its tile: the check's path and stroke


def svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="{TILE}"/>{body}</svg>'


FULL = svg(CHECK)
MASKABLE = svg(f'<g transform="translate(32 32) scale({MASKABLE_SCALE}) translate(-32 -32)">{CHECK}</g>')
ICONS = {
    "icon-192.png": (192, FULL),
    "icon-512.png": (512, FULL),
    "icon-maskable-512.png": (512, MASKABLE),
    "apple-touch-icon.png": (180, FULL),
}

out = ROOT / "icons"
out.mkdir(exist_ok=True)
for name, (px, src) in ICONS.items():
    png = bytes(resvg_py.svg_to_bytes(svg_string=src, width=px, height=px))
    (out / name).write_bytes(png)
    print(f"{name}: {px}x{px}, {len(png)} bytes")
