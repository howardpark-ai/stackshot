"""i18n.py — the board pages' one string table, in English, and the loader for a second language.

What switches: the interface text of the pages (labels, buttons, headings, states, tooltips, dates and ages). What does not: item text (titles, descriptions, steps, history, asks) and the text of the
tools, which stay as written.

The English catalog is `EN`, a plain dict in this file, keyed by dotted names by area (`panel.*`, `home.*`, `state.*`, `date.*`, `age.*`, `js.*`). Every value is a `str.format` template: `{name}` fields are filled
from the keyword arguments of `t`. A page asks `t(key, lang, **fields)`: the string in the person's language, else the English one (so a missing key, a missing file and a bad value are never an
error on a page). English output is what the pages said before this module existed.

A second language is a JSON file `<code>.json` (an object of key -> text, the keys of `EN`) in the folder the instance config names, `[ui] locale_dir`. The folder is off by default: with none, or
with no file that loaded, `available()` is just English and the pages draw no toggle. The code is `ko` (LANGS names the codes a person can pick). A file is read again when it changes; it is validated
when read: a key `EN` does not have is ignored (and counted), a value that is not text or that names a field `EN` does not offer for that key falls back to the English text for that key. One warning line
per file goes to stderr when it is read (missing file or folder, unreadable JSON, how many keys are missing or were refused), never a line per page.

Dates and ages are templates in the catalog too (`date.full`, `date.nohm`, `date.day`, `date.ord.*`, `date.wd.*`, `date.mon.*`, `age.*`), so a language's own forms come out of its file alone.

The language of a request is `current()`: the server sets it for the request from the person's stored choice (uiprefs.lang) with `use`, and a Board draws in it unless it was given one. Stdlib and
stackshot.core.config only; this module imports nothing of the web layer."""
from __future__ import annotations

import contextlib
import contextvars
import datetime
import json
import string
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

from stackshot.core import config as _cfg

DEFAULT = "en"
LANGS: tuple[str, ...] = ("en", "ko")        # the codes a person can pick; the toggle offers the ones whose catalog loaded

# ----------------------------------------------------------------------------- the English catalog
EN: dict[str, str] = {}

# dates and ages: the forms are templates, so a language's own come from its file
EN.update({
    "date.full": "{wd} {month} {day} {hm}",                  # Tue Nov 10th 16:20
    "date.nohm": "{wd} {month} {day}",                       # Tue Nov 10th
    "date.day": "{n}{ord}",                                  # 10th
    "date.ord.1": "st", "date.ord.2": "nd", "date.ord.3": "rd", "date.ord.n": "th",
    "age.now": "just now",
    "age.min": "{n}m ago", "age.hour": "{n}h ago", "age.day": "{n}d ago",
})
for _i, _w in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
    EN[f"date.wd.{_i}"] = _w
for _i, _m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1):
    EN[f"date.mon.{_i}"] = _m

from stackshot.web import i18n_catalog as _cat       # noqa: E402  — the rest of the English catalog, by area (its own file, so this one stays the mechanism)
EN.update(_cat.CATALOG)

# ----------------------------------------------------------------------------- loading a second language
_LOCK = threading.RLock()
_LOADED: dict[str, dict[str, Any]] = {}      # code -> {"stamp": (folder, mtime_ns, size), "strings": {...}}
_WARNED: set[tuple[str, str]] = set()        # (code, reason) already said once


def _warn(code: str, why: str) -> None:
    """One line to the log per (language, reason): a page is never an error and never a line per request."""
    k = (code, why)
    with _LOCK:
        if k in _WARNED:
            return
        _WARNED.add(k)
    print(f"i18n: {code}: {why}; English is used for what is missing", file=sys.stderr, flush=True)


def fields_of(template: str) -> set[str] | None:
    """The field names of a format template, or None when it is not a plain one (an unbalanced brace, a positional `{}`, an attribute or index access, a conversion or a format spec)."""
    out: set[str] = set()
    try:
        for _lit, name, spec, conv in string.Formatter().parse(template):
            if name is None:
                continue
            if not name.isidentifier() or spec or conv:
                return None
            out.add(name)
    except ValueError:
        return None
    return out


def _encodable(s: str) -> bool:
    """The text can be written out as UTF-8 (a lone surrogate, which JSON's \\ud83d escape gives, cannot: the page would fail when it is sent)."""
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def validate(raw: Any, base: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, int]]:
    """(the usable strings, counts) of a loaded JSON object: only keys the English catalog has, each value text whose fields are a subset of the English value's (a language may leave a field out, never name an
    extra one). counts: unknown (keys ignored), refused (values that fell back to English), missing (English keys the file does not give)."""
    base = EN if base is None else base
    out: dict[str, str] = {}
    unknown = refused = 0
    for k, v in (raw.items() if isinstance(raw, dict) else ()):
        if not isinstance(k, str) or k.startswith("_"):
            continue                                    # "_note" style keys are for the file's writer
        if k not in base:
            unknown += 1
            continue
        f = fields_of(v) if isinstance(v, str) and _encodable(v) else None
        if f is None or not f <= (fields_of(base[k]) or set()):
            refused += 1
            continue
        out[k] = v
    return out, {"unknown": unknown, "refused": refused, "missing": len(base) - len(out)}


def _folder() -> Path | None:
    v = _cfg.get("ui", "locale_dir")
    return Path(str(v)).expanduser() if v else None


def load(code: str, folder: Path | str | None = None) -> dict[str, str] | None:
    """The validated strings of language `code` from `<folder>/<code>.json` (the config's [ui] locale_dir when no folder is given), or None when there are none (no folder set, no file, unreadable or not an
    object). Read again when the file changed. One warning per reason, never an error."""
    if code == DEFAULT or code not in LANGS:
        return None
    d = Path(folder).expanduser() if folder else _folder()
    if d is None:
        _LOADED.pop(code, None)
        return None
    p = d / f"{code}.json"
    try:
        st = p.stat()
    except OSError:
        _LOADED.pop(code, None)
        _warn(code, f"{p} not found" if d.is_dir() else f"locale folder {d} not found")
        return None
    stamp = (str(p), st.st_mtime_ns, st.st_size)
    with _LOCK:
        got = _LOADED.get(code)
        if got and got["stamp"] == stamp:
            return got["strings"] or None
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))      # a file saved with a byte-order mark (some editors do) reads the same
    except (OSError, ValueError) as e:                  # UnicodeDecodeError is a ValueError
        _warn(code, f"{p} cannot be read ({e.__class__.__name__})")
        return None
    if not isinstance(raw, dict):
        _warn(code, f"{p} is not a JSON object")
        return None
    strings, n = validate(raw)
    with _LOCK:
        _LOADED[code] = {"stamp": stamp, "strings": strings}      # kept even when empty, so the file is not read again on every request
    if not strings:
        _warn(code, f"{p.name} has no usable key ({n['unknown']} unknown, {n['refused']} refused), so it is not used")
        return None
    bits = [f"{n[k]} {w}" for k, w in (("missing", "missing"), ("refused", "refused"), ("unknown", "unknown and ignored")) if n[k]]
    if bits:
        _warn(code, f"{p.name}: " + ", ".join(bits) + " of %d keys" % len(EN))
    return strings


def available() -> list[str]:
    """The languages a person can pick: English, then each language whose catalog loaded."""
    return [DEFAULT] + [c for c in LANGS if c != DEFAULT and load(c) is not None]


def signature() -> tuple:
    """What the pages' words depend on: each available language with the stamp of its file. A kept draw of a page is made again when this changes (a catalog added, removed or edited), without waiting for its
    time to run out."""
    out = []
    for c in available():
        got = _LOADED.get(c)
        out.append((c, got["stamp"] if got else None))
    return tuple(out)


def norm(lang: Any) -> str:
    """A language code as the pages take it: one of `available()`, else English."""
    return lang if isinstance(lang, str) and lang in available() else DEFAULT


def raw(key: str, lang: str | None = None) -> str | None:
    """The unfilled template for `key` in `lang` (default: the request's): the language's own when its catalog has the key, else the English one; None when the English catalog lacks the key."""
    lang = current() if lang is None else lang
    if lang != DEFAULT:
        got = load(lang)
        if got and key in got:
            return got[key]
    return EN.get(key)


def t(key: str, lang: str | None = None, **fields: Any) -> str:
    """The text for `key` in `lang` (default: the request's), with `fields` filled in. A language without the key, or without any catalog, gives the English text; a key the English catalog lacks is returned as
    it is (a typo shows). A template that cannot be filled (a field not given) is returned unfilled rather than raising: a page never fails on its words."""
    lang = current() if lang is None else lang
    s = None
    if lang != DEFAULT:
        got = load(lang)
        s = got.get(key) if got else None
    if s is None:
        s = EN.get(key)
        if s is None:
            return key
    try:
        return s.format(**fields) if fields or "{" in s else s
    except (KeyError, IndexError, ValueError):
        base = EN.get(key, key)
        try:
            return base.format(**fields)
        except (KeyError, IndexError, ValueError):
            return base


JS_PREFIXES = ("js.", "age.", "date.", "panel.hide", "panel.show", "panel.pin", "panel.order_", "panel.moved", "panel.move_for", "panel.audit.")      # the keys the page scripts use (SST in the page head): the table a page carries


def js_table(lang: str | None = None) -> dict[str, str]:
    """The strings the page scripts ask for (keys under JS_PREFIXES), by key, in `lang`."""
    return {k: raw(k, lang) for k in EN if k.startswith(JS_PREFIXES)}      # the templates as they are: the script fills the {fields}


def many(prefix: str, lang: str | None = None) -> dict[str, str]:
    """Every string under `prefix` (`prefix` + "." + name), by name, in `lang`: the table a page script gets (`js.*`)."""
    n = len(prefix) + 1
    return {k[n:]: raw(k, lang) for k in EN if k.startswith(prefix + ".")}


# ----------------------------------------------------------------------------- the language of the request
_CUR: contextvars.ContextVar[str] = contextvars.ContextVar("stackshot_ui_lang", default=DEFAULT)


def current() -> str:
    return _CUR.get()


@contextlib.contextmanager
def use(lang: str) -> Iterator[None]:
    """Draw in `lang` for the code run inside (the server wraps a request in it)."""
    tok = _CUR.set(lang if isinstance(lang, str) and lang else DEFAULT)
    try:
        yield
    finally:
        _CUR.reset(tok)


def set_current(lang: str) -> contextvars.Token:
    return _CUR.set(lang if isinstance(lang, str) and lang else DEFAULT)


def reset_current(tok: contextvars.Token) -> None:
    _CUR.reset(tok)


# ----------------------------------------------------------------------------- dates and ages
def _ord(d: int, lang: str) -> str:
    if 11 <= d % 100 <= 13:
        return t("date.ord.n", lang)
    return t({1: "date.ord.1", 2: "date.ord.2", 3: "date.ord.3"}.get(d % 10, "date.ord.n"), lang)


def fmt_date(ts: Any, lang: str | None = None, clock: bool = True, tz: datetime.tzinfo | None = None) -> str:
    """A date a person reads, from the catalog's templates: "Tue Nov 10th 16:20" in English (clock=False: "Tue Nov 10th"). `ts` is a datetime (drawn in its own zone), a date (never has a clock), or epoch seconds (in
    `tz`, else UTC)."""
    if isinstance(ts, datetime.datetime):
        d = ts
    elif isinstance(ts, datetime.date):
        d, clock = ts, False
    else:
        d = datetime.datetime.fromtimestamp(float(ts), tz or datetime.timezone.utc)
    lang = current() if lang is None else lang
    f = dict(wd=t(f"date.wd.{d.weekday()}", lang), month=t(f"date.mon.{d.month}", lang), day=t("date.day", lang, n=d.day, ord=_ord(d.day, lang)))
    if isinstance(d, datetime.datetime) and clock:
        return t("date.full", lang, hm=f"{d:%H:%M}", **f)
    return t("date.nohm", lang, **f)


def fmt_age(seconds: float, lang: str | None = None, quiet: bool = False) -> str:
    """How long ago, the page's one format: "just now", "12m ago", "3h ago" (to 48 h), "5d ago". quiet=True is the form that only marks the start of a silence: ">21h ago" (the mark, then the age, never "just now")."""
    s = max(int(seconds), 0)
    m = s // 60
    if s < 60 and not quiet:
        return t("age.now", lang)
    age = t("age.min", lang, n=m) if m < 60 else t("age.hour", lang, n=m // 60) if m < 48 * 60 else t("age.day", lang, n=m // 1440)
    return (">" + age) if quiet else age
