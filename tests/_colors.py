"""tests/_colors.py — colour helpers the suites share (a module, not a suite): WCAG 2.x contrast, a blend, hue/saturation/lightness, the stylesheet's tokens resolved per theme
(a token may be a hex, a `var(--other)` or a `color-mix(in srgb, …)` of those), and a finder of every colour literal in a text.

Used by tests/orange_scenario.py, tests/button_set_scenario.py and tests/ui_kit_scenario.py, so the three read the stylesheet the same way."""
import colorsys, re


def full(h):
    """#fff → #ffffff; a 4-digit or 8-digit hex loses its alpha; always lower case."""
    h = h.lower()
    if len(h) in (4, 5): h = "#" + "".join(c * 2 for c in h[1:])
    return h[:7]


def lum(h):
    h = h.lstrip("#"); ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def ratio(a, b):
    """WCAG 2.x contrast of two hex colours."""
    hi, lo = sorted((lum(a), lum(b)), reverse=True); return (hi + 0.05) / (lo + 0.05)


def mix(top, base, pct):
    """`top` at pct% over `base`, as color-mix(in srgb, …) and a plain opacity both blend."""
    t, b = top.lstrip("#"), base.lstrip("#")
    return "#" + "".join("%02x" % round(int(t[i:i + 2], 16) * pct / 100 + int(b[i:i + 2], 16) * (100 - pct) / 100) for i in (0, 2, 4))


def hsl(h):
    """(hue in degrees, saturation 0..1, lightness 0..1) of a hex colour."""
    h = h.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b); return hue * 360, sat, light


def hsl_of_rgb(r, g, b):
    hue, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255); return hue * 360, sat, light


def hex_of_hsl(hue, sat, light):
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360, light, sat); return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


# ----------------------------------------------------------------------------- the tokens of a stylesheet, resolved
def _split_top(s, sep=","):
    """Split on `sep` outside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        if ch == sep and depth == 0: out.append(cur); cur = ""
        else: cur += ch
    return out + [cur]


def resolve(value, tokens, _depth=0):
    """The hex a token value comes to, or None when it is not a colour this module can compute (transparent, a length, a font stack)."""
    v = value.strip()
    if _depth > 12: return None
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", v): return full(v)
    m = re.fullmatch(r"var\((--[\w-]+)(?:,.*)?\)", v)
    if m: return resolve(tokens[m.group(1)], tokens, _depth + 1) if m.group(1) in tokens else None
    m = re.fullmatch(r"color-mix\(\s*in srgb\s*,(.*)\)", v, re.S)
    if m:
        parts = _split_top(m.group(1))
        if len(parts) != 2: return None
        def side(p):
            q = re.fullmatch(r"\s*(.*?)(?:\s+([\d.]+)%)?\s*", p, re.S); return q.group(1), (float(q.group(2)) if q.group(2) else None)
        (a, pa), (b, pb) = side(parts[0]), side(parts[1])
        if pa is None: pa = 100 - pb if pb is not None else 50
        ca, cb = resolve(a, tokens, _depth + 1), resolve(b, tokens, _depth + 1)
        return mix(ca, cb, pa) if ca and cb else None
    return None


def declarations(block):
    """{--name: raw value} of the custom properties in one rule body."""
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+)", block)}


def themes(css):
    """({token: raw value}, {token: raw value}) for the light and the dark theme as the cascade gives them: the plain `:root{…}` blocks, and over them the `:root[data-theme=dark]{…}` blocks."""
    light, dark = {}, {}
    for blk in re.findall(r"(?:^|[}\s/]):root\{([^}]*)\}", css): light.update(declarations(blk))
    dark.update(light)
    for blk in re.findall(r":root\[data-theme=dark\]\{([^}]*)\}", css): dark.update(declarations(blk))
    return {"light": light, "dark": dark}


def resolved(css):
    """{"light": {token: hex}, "dark": {token: hex}} for every token that comes to a colour."""
    out = {}
    for name, raw in themes(css).items():
        out[name] = {k: h for k in raw if (h := resolve(raw[k], raw))}
    return out


# ----------------------------------------------------------------------------- every colour literal in a text
_HEX = re.compile(r"(?<![&#])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")
_PCT23 = re.compile(r"%23([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")      # a URL-encoded hex (`fill='%23c2601a'` in a data: URI) is a colour wherever it stands
_SHORT_CTX = re.compile(r"[:=(,]\s*[\"']?\s*$")       # a 3- or 4-digit hex right after `:` `=` `(` `,` is a colour
_FRAGMENT = re.compile(r"(?:\b(?:href|src|action|for|id|name|xlink:href)\s*=\s*[\"']?|url\(\s*[\"']?)$", re.I)      # an anchor or a url(#id) reference is not a colour
_FN = re.compile(r"\b(rgba?|hsla?)\(([^)]*)\)", re.I)
_MODERN = re.compile(r"[:,]\s*(oklch|oklab|lch|lab|hwb|color)\(", re.I)      # as a CSS value or a color-mix() side, so a method call like self.lab(x) is not one
# The CSS named colours in or near the orange family. Always a failure where one is used as a colour (none is the board's orange); gold, goldenrod and wheat are amber and left out.
_NAMED = ("orange", "darkorange", "orangered", "coral", "lightcoral", "tomato", "salmon", "darksalmon", "lightsalmon", "sienna", "chocolate", "peru", "sandybrown", "saddlebrown", "burlywood",
          "bisque", "peachpuff", "navajowhite", "tan")
# "Inside CSS text": a name or a short/glued hex counts when it follows `property:` of a property that takes a colour (colour, background, border, outline, shadow, fill, stroke, decoration, gradient, or a
# custom property --x) and only value words since (numbers, border styles, colours, gradient words, commas, parentheses). So "board: orange (" in a comment, or "the update orange" in the README, is prose.
_COLOR_PROP = r"(?:--[\w-]+|[a-z-]*(?:color|background|border|outline|shadow|fill|stroke|decoration|gradient)[a-z-]*)"
_PROP_COLON = re.compile(r"(?:^|[\s\"'(])(" + _COLOR_PROP + r")\s*:", re.I)
_VALUE_WORDS = frozenset(("solid", "dashed", "dotted", "double", "inset", "outset", "ridge", "groove", "none", "transparent", "currentcolor", "inherit", "to", "top", "bottom", "left", "right", "center",
                          "in", "srgb", "red", "white", "black", "blue", "green", "gray", "grey", "!important", "important", "var", *_NAMED))
_FUNCS = frozenset(("linear-gradient", "radial-gradient", "conic-gradient", "repeating-linear-gradient", "repeating-radial-gradient", "rgb", "rgba", "hsl", "hsla", "var", "color-mix", "calc", "drop-shadow"))
_TOKEN = re.compile(r"[\w.%#+-]+\(?|[^\s\w.%#+-]")
def _in_declaration(seg):
    """True when `seg`, the text since the last `;` `{` `}` or newline, ends inside a CSS declaration of a colour property with only value words after the colon."""
    m = None
    for m in _PROP_COLON.finditer(seg): pass
    if not m: return False
    for w in _TOKEN.findall(seg[m.end():]):
        lw = w.lower()
        if w in ",()/!": continue
        if lw.endswith("("):
            if lw[:-1] in _FUNCS: continue
            return False
        if re.fullmatch(r"[-+]?\d*\.?\d+[a-z%]*", lw) or lw in _VALUE_WORDS or lw.startswith(("#", "%23", "--")) or re.fullmatch(r"[0-9a-f]{3,8}", lw): continue
        return False
    return True
def _segment(text, pos):
    return re.split(r"[;{}\n]", text[max(0, pos - 300):pos])[-1]
_NAMED_RE = re.compile(r"(?<![\w.#%-])(" + "|".join(sorted(_NAMED, key=len, reverse=True)) + r")(?![\w-])", re.I)
_NAMED_ATTR = re.compile(r"\b(?:fill|stroke|stop-color|flood-color|color|backgroundColor|background-color)[\"']?\s*[=:]\s*[\"'](" + "|".join(_NAMED) + r")[\"']", re.I)      # fill="orange", style.color = 'coral', {"color": "tomato"}


def literals(text):
    """[(literal as written, (hue, saturation, lightness) or None, kind)] for each colour in `text`: hex (#rgb, #rgba, #rrggbb, #rrggbbaa, also URL-encoded as %23rrggbb, and glued to a word as in `solid#c2601a`),
    rgb()/rgba(), hsl()/hsla() with plain numbers, a CSS named colour of the orange family used as a CSS value (`color:orange`, `border:1px solid orange`, `linear-gradient(orange,#fff)`), and kind "unreadable"
    for a form this module cannot compute (oklch(), lab(), hwb(), color(), percent rgb), which the caller treats as a failure so a colour cannot hide in one."""
    out = []
    for m in _HEX.finditer(text):
        h = m.group(1); pre = text[max(0, m.start() - 300):m.start()]
        if _FRAGMENT.search(pre): continue
        glued = pre[-1:].isalnum() or pre[-1:] == "_"
        if glued:
            if not _in_declaration(_segment(text, m.start())): continue          # `a#d62{`, `page.html#d62`, `https://x#d62` are selectors, paths and anchors
        elif len(h) in (3, 4) and not (_SHORT_CTX.search(pre) or _in_declaration(_segment(text, m.start()))): continue      # "PRs #9" is prose
        out.append((m.group(0), hsl(full("#" + h)), "hex"))
    for m in _PCT23.finditer(text): out.append((m.group(0), hsl(full("#" + m.group(1))), "hex"))
    for m in _FN.finditer(text):
        a = [x.strip() for x in re.split(r"[,\s/]+", m.group(2)) if x.strip()]
        try:
            if m.group(1).lower().startswith("rgb"):
                if any(x.endswith("%") for x in a[:3]): raise ValueError
                out.append((m.group(0), hsl_of_rgb(*(float(x) for x in a[:3])), "rgb"))
            else:
                out.append((m.group(0), (float(re.sub(r"[a-z]+$", "", a[0])) % 360, float(a[1].rstrip("%")) / 100, float(a[2].rstrip("%")) / 100), "hsl"))
        except (ValueError, IndexError):
            out.append((m.group(0), None, "unreadable"))
    for m in _MODERN.finditer(text): out.append((m.group(0).lstrip(":, "), None, "unreadable"))
    for m in _NAMED_RE.finditer(text):
        if _in_declaration(_segment(text, m.start())): out.append((m.group(1), None, "named"))
    for m in _NAMED_ATTR.finditer(text): out.append((m.group(1), None, "named"))
    return out

_COLORTOOL_BLOCKS = (re.compile(r"<script>/\* colortool v\d+ \*/.*?</script>", re.S), re.compile(r"<script>window\.stackshotColors=.*?</script>", re.S), re.compile(r"<script>ColorTool\.init\(.*?</script>", re.S))


def without_colortool(text):
    """A page (or a source file) without the shared color tool's script blocks: the library (shared/colortool.js, inlined once in the head), stackshot's settings for it and its init call.
    The tool carries the presets, whose colors are its own and not the board's, so the orange scan reads pages without it; the checks on a page's head scripts read it too, since the tool watches data-theme."""
    for rx in _COLORTOOL_BLOCKS: text = rx.sub("", text)
    return text
