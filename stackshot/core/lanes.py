"""lanes.py — the names of the fleet tool's lanes, read from the tool's own setting and never spelled in stackshot.

The fleet tool (sala) names each lane by a code (`subscription-1`, `api`, `aws-platform`) and shows it by a display name; it renames a lane by
changing the display name or by giving the lane a new code and keeping the old code as an alias. stackshot never writes either the plan name of a
lane or its display name in its own text: it reads them from the tool's lane-names file, so a rename on the tool's side reaches the board with no change here.

The file (written atomically by the tool; the same text comes from `sala lane names --json`, which stackshot never runs on a request path):

    ~/.local/state/salamander/lane-names.json       (STACKSHOT_LANE_NAMES in the environment names another file)
    {"lanes": [{"code": "<code>", "display": "<display name>", "aliases": ["<an old code>"]}, {"code": "api", "display": "<display name>", "aliases": []}, ...]}

Every lane is listed, `aliases` is [] for a lane with none. The file is read again when its modification time or size changes, never otherwise (no
read per call). A file that is missing, not JSON or not that shape is no data: a lane word is then taken as the code it is (after the fixed words
below), a display name is the code, and one line on standard error says so, once for each state (a file that becomes readable and breaks again says so again).

`code(word)` is the one comparison: the lane's code for a word that is its code or one of its aliases, else the word as written. Every comparison of
two lane words goes through it, so an old word and the new one are one lane. `display_name(word)` is the name to show. `shown(word)` is the code with
its display name beside it, for a line that names the lane to a reader who may not know the code.

FIXED_ALIASES is a floor of old lane words, and it is read BEFORE the file: each old word with the code it became. So a stored lane check or a lane record written before a rename reads right while the file is missing (the
tool's release and its file arrive separately) or older than the rename, and a file that still lists an old code as a lane does not split one lane in two: that row is
read as the lane the floor names (listed under the new code, its display name kept). The floor holds codes only, never a display name; the file alone says what a lane is
called. A word the floor does not name is the file's to resolve (its codes and aliases), else it is the word as written. FALLBACK_CODES is the floor's codes and the plain
codes the tool has always had, for a message that must name valid lanes while the file is missing. Pure of the server and the store."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

ENV = "STACKSHOT_LANE_NAMES"
DEFAULT_PATH = "~/.local/state/salamander/lane-names.json"
DEFAULT_CODE = "subscription-1"        # the lane a pane is on when the lane record has neither a row for it nor a default: the tool's own fallback, by code
FIXED_ALIASES = {"awsplatform": "aws-platform", "max": "subscription-1", "team": "subscription-2"}
FALLBACK_CODES = tuple(dict.fromkeys([*FIXED_ALIASES.values(), "api", "sdk"]))    # lane codes a refusal can name with no file: the floor's targets, then the plain ones

_lock = threading.Lock()
_cache: dict[str, Any] = {"path": None, "sig": None, "lanes": None}    # lanes: {code: display}, and _alias: {word: code}
_alias: dict[str, str] = {}
_said: set[tuple[str, str]] = set()     # (path, reason) of the lines already logged; emptied when the file reads well again


def path() -> Path:
    """The lane-names file: STACKSHOT_LANE_NAMES when set and not empty, else the tool's own location. Read at each call (the environment is live)."""
    v = (os.environ.get(ENV) or "").strip()
    return Path(os.path.expanduser(v or DEFAULT_PATH))


def _say(p: Path, reason: str, skipped: bool = False) -> None:
    """One line on standard error for a (file, reason) not said before: the file gives no lane names, or (skipped) one of its rows was left out."""
    if (str(p), reason) in _said:
        return
    _said.add((str(p), reason))
    if skipped:
        print(f"lanes: {p}: a lane row was skipped ({reason}); the other rows are read", file=sys.stderr)
    else:
        print(f"lanes: no lane names from {p}: {reason}; lanes are shown by their code", file=sys.stderr)


def _parse(raw: Any) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """The file's JSON → ({code: display}, {word: code} for the codes and their aliases, why each row left out was). ValueError when it has no "lanes" list.
    A malformed row (not an object, no code, aliases that are not words) is left out and the rest are kept. A row whose code is an old one the floor renames
    is read as the lane the floor names: listed under the new code, its display name used unless a row of the new code itself gives one, its aliases the new code's."""
    rows = raw.get("lanes") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise ValueError('no "lanes" list')
    lanes: dict[str, str] = {}
    alias: dict[str, str] = {}
    skipped: list[str] = []
    for n, r in enumerate(rows, 1):
        if not isinstance(r, dict) or not isinstance(r.get("code"), str) or not r["code"].strip():
            skipped.append(f"row {n} has no code"); continue
        als = r.get("aliases") or []
        if not isinstance(als, list) or not all(isinstance(a, str) for a in als):
            skipped.append(f"row {n} ({r['code'].strip()}) has aliases that are not a list of words"); continue
        raw_code = r["code"].strip().lower()
        c = FIXED_ALIASES.get(raw_code, raw_code)
        d = r.get("display")
        name = d.strip() if isinstance(d, str) and d.strip() else c
        if c == raw_code or c not in lanes:      # the row of the new code itself wins; an old-code row only fills a lane no row of the new code has given
            lanes[c] = name
        for a in als:
            if a.strip():
                alias[a.strip().lower()] = c
    for c in lanes:                      # a code is its own word before any alias of another lane
        alias[c] = c
    return lanes, alias, skipped


def _read() -> tuple[dict[str, str], dict[str, str]]:
    """The lanes and the word table, from the file as it is now (cached on its mtime and size); ({}, {}) when it gives none."""
    global _alias
    p = path()
    try:
        st = p.stat()
    except OSError as e:
        with _lock:
            _cache.update(path=str(p), sig=None, lanes={}); _alias = {}
            _say(p, "missing" if isinstance(e, FileNotFoundError) else f"not readable ({e.strerror or e})")
        return {}, {}
    sig = (st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["path"] == str(p) and _cache["sig"] == sig and _cache["lanes"] is not None:
            return _cache["lanes"], _alias
    try:
        lanes, alias, skipped = _parse(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:       # JSONDecodeError and UnicodeDecodeError are ValueErrors
        with _lock:
            _cache.update(path=str(p), sig=sig, lanes={}); _alias = {}
            _say(p, f"not readable ({e})" if isinstance(e, OSError) else f"not the lane-names shape ({e})")
        return {}, {}
    with _lock:
        _cache.update(path=str(p), sig=sig, lanes=lanes); _alias = alias
        _said.clear()
        for why in skipped:
            _say(p, why, skipped=True)
    return lanes, alias


def code(word: Any) -> str:
    """The code of the lane a word names: the fixed old words first (the floor), then the file's codes and aliases, else the word as written
    (stripped; a lane the file does not list is shown and compared as it is)."""
    s = str(word or "").strip()
    if not s:
        return ""
    low = s.lower()
    _, alias = _read()
    return FIXED_ALIASES.get(low) or alias.get(low) or s


def display_name(word: Any) -> str:
    """The name to show for a lane word: its display name from the file, else its code (the file missing, unreadable, or not listing the lane)."""
    c = code(word)
    lanes, _ = _read()
    return lanes.get(c.lower()) or c


def shown(word: Any) -> str:
    """`<code> (<display>)` when the display name is another word than the code, else the code."""
    c = code(word)
    d = display_name(c)
    return c if not d or d.lower() == c.lower() else f"{c} ({d})"


def codes() -> list[str]:
    """The codes the file lists, in its order; [] when it gives none."""
    return list(_read()[0])
