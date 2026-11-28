"""autonomy.py: the one reader of the autonomy profile, the table that says per person and per kind of action how far an agent may go alone.

The file is TOML, `autonomy.toml`, at `[paths] autonomy` (default: `autonomy.toml` in the data repo, beside `[paths] repo`):

    version = 1
    [person.<member name>]
    release = "auto"
    design-choice = "ask-first"
    # one key per kind of KINDS below

A level is one of LEVELS, least to most careful: `auto` (acts without asking), `when-told` (acts when the person's words, or a relayed call carrying them, say so), `ask-first` (proposes
it as a board step with options and a recommendation, and waits for the pick), `hand-on` (does not act and does not ask: passes it to the person who must take it).

The fallback is the most careful level: a missing person, kind or level word, a kind this module does not know and a file that is absent, unreadable or not TOML all read `hand-on`.
`level` and `table` never raise. The file is read by its stamp (`core/filecache.py`), not at start: an edit is seen at the next call, with no restart.

Nothing reads the table yet: a hook, the rules text and the idle-proposal job take it up in later steps. `problems()` lists the gaps (`stackshot doctor` prints them).
Standard library plus core/members.py and core/filecache.py."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from stackshot.core import filecache

LEVELS = ("auto", "when-told", "ask-first", "hand-on")
FALLBACK = "hand-on"        # the most careful level: nothing is permitted by default

KINDS: tuple[tuple[str, str], ...] = (
    ("release", "merge a change that ships, with no design choice, migration, new notice or cost"),
    ("release-migrating", "ship a change with a database migration, which a revert does not undo"),
    ("design-choice", "settle a design choice the person has not made"),
    ("new-notice", "start anything new the person receives (mail, notice, report, a new recurring output)"),
    ("spend", "start a new cost or raise a cap (spending inside a standing cap is no action)"),
    ("message-person", "send a text to another person, which goes out under the person's name"),
    ("email", "send an email: a Gmail draft to the person as a decision, sent on their Send"),
    ("connector-write", "write through a connector (calendar, Notion, Slack)"),
    ("merge", "merge a pull request on green checks where the agent holds the maintainer role"),
    ("delete", "delete anything the session did not create (its own scratch is no action)"),
    ("retire", "retire a session (a throwaway session's end needs a recorded reason)"),
    ("revive", "revive a session found unable to work, with a recorded reason, never as a sweep"),
    ("fleet-op", "a fleet operation: recycle, update, reboot, rename, lane"),
    ("public-repo", "create a public repository"),
)
KIND_NAMES = tuple(k for k, _ in KINDS)


def path() -> Path:
    """Where the file is: `[paths] autonomy`, else `autonomy.toml` in the data repo (`[paths] repo`)."""
    from stackshot.core import config as _cfg
    raw = _cfg.get("paths", "autonomy")
    if isinstance(raw, str) and raw.strip():
        return Path(os.path.expanduser(raw))
    return _cfg.path("paths", "repo") / "autonomy.toml"


def _parse(p: Path) -> tuple[dict[str, Any] | None, str]:
    """(the file's `person` table, "") or (None, why it cannot be read)."""
    try:
        with open(p, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return None, f"{p} does not exist"
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return None, f"{p} cannot be read: {e}"
    people = raw.get("person", {})
    if not isinstance(people, dict):
        return None, f"{p}: person is not a table of tables (write one [person.<name>] table per member)"
    return people, ""


def _load(p: Path | None = None) -> tuple[dict[str, Any] | None, str]:
    p = p or path()
    return filecache.derived(("autonomy", str(p)), [p], str(p), lambda: _parse(p))


def _name(person: Any) -> str:
    """The name a table is kept under for what the caller wrote: the member's name when `person` is a name or alias of one, else the text as given."""
    text = " ".join(str(person or "").split())
    try:
        from stackshot.core import members
        found = members.person_of(text)
        if found is not None:
            return found.name
    except Exception:
        pass
    return text


def _row(people: dict[str, Any] | None, person: Any) -> dict[str, Any]:
    if not people:
        return {}
    want = _name(person).casefold()
    if not want:
        return {}
    for key, row in people.items():
        if str(key).casefold() == want and isinstance(row, dict):
            return row
    return {}


def kind_level(row: dict[str, Any], kind: str) -> str:
    """The level word `row` gives `kind`, or the fallback for a kind this module does not know, a missing key or a word that is no level."""
    if kind not in KIND_NAMES:
        return FALLBACK
    v = row.get(kind)
    return v if isinstance(v, str) and v in LEVELS else FALLBACK


def level(person: Any, kind: Any) -> str:
    """The level of `kind` for `person`: one of LEVELS. Never raises; every gap reads FALLBACK."""
    try:
        people, _ = _load()
        return kind_level(_row(people, person), str(kind or "").strip())
    except Exception:
        return FALLBACK


def table(person: Any) -> dict[str, str]:
    """The person's level for every kind, in KINDS order. Never raises."""
    try:
        people, _ = _load()
        row = _row(people, person)
    except Exception:
        row = {}
    return {k: kind_level(row, k) for k in KIND_NAMES}


def problems() -> list[str]:
    """One line per gap, none when the file is whole: an unreadable file, a member with no table, a kind with no level, a level word that is none, a key that is no kind.
    The members are those of the running config. Reads only; it fixes nothing."""
    try:
        p = path()
        people, why = _parse(p)      # a fresh read: a check wants the file as it is now
        if people is None:
            return [f"{why}: every action reads {FALLBACK} until it is written"]
        from stackshot.core import members
        names = [m.name for m in members.members() if not m.placeholder]
        have = {str(k).casefold(): v for k, v in people.items()}
        out: list[str] = []
        for n in names:
            row = have.get(n.casefold())
            if not isinstance(row, dict):
                out.append(f"member {n} has no [person.{n}] table: every kind reads {FALLBACK}")
                continue
            for k in KIND_NAMES:
                v = row.get(k)
                if k not in row:
                    out.append(f"[person.{n}] has no level for {k}: it reads {FALLBACK}")
                elif not isinstance(v, str) or v not in LEVELS:
                    out.append(f"[person.{n}] {k} = {v!r} is no level (one of {', '.join(LEVELS)}): it reads {FALLBACK}")
            for k in row:
                if k not in KIND_NAMES:
                    out.append(f"[person.{n}] {k} is no kind of action: it is ignored (kinds are added in stackshot/core/autonomy.py)")
        return out
    except Exception as e:
        return [f"autonomy profile could not be checked: {e}"]
