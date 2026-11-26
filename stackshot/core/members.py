"""members.py: the one reader of who the members of this board are.

Every other module asks here; none reads `[instance] owner`, `[instance] owner_aliases` or `[auth] allowed_emails` for a person's name, aliases or
sign-in addresses. The list is built from, in this order:

1. `[[members]]` in the config: one table per person, `name`, `aliases` (a list) and `emails` (a list of the Google addresses that sign in as that person);
2. else the old keys, as a list of one person: `[instance] owner`, `[instance] owner_aliases` and `[auth] allowed_emails` (all the addresses are that person's);
3. else the placeholder, one person called `the owner` with no alias and no address (the board says so at its start).

A board behind a front door that sets `[behind_frontdoor] members_file` reads none of the above: its people are the members the front door's file lists for it (`core/behind_door.py`),
each named by the identity the file gives it (its key), with the aliases and sign-in addresses the file gives it (a key written like an address is its own address), in the file's order, read at each call; a file that lists nobody for the board, or cannot be read, leaves
the placeholder, which no address matches.

One exception, for naming alone (`naming`, behind `names`, `names_cf`, `person_of` and `opener_person`): on a machine where that members file is not there at all, a line of
text is still read against the configured `[instance] owner` and `owner_aliases`, so the owner's steps are recognized where only the board's text is read. `members`, the
sign-in addresses and everything that decides who may do what stay with the file: absent means nobody.

The answer is built from the config as it stands: a suite or a reload that changes the inputs is read at the next call. The name is the key a person is
stored under (a mover, a tick, a hand-off): unique without regard to case, and a restart-only setting like the old key it replaces.

What this module answers is who the members are, and nothing about a session, a cookie or a role: the sign-in lives in web/auth and only asks
`person_of_email` whether an address belongs to a person. The source of the list is one function (`build`), so it can move from the config to a
shared directory without a caller changing.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any



class _LazyConfig:
    """The config module, imported at first use: config.py reads this module for its refusals while it loads, so neither can import the other at the top."""

    def __getattr__(self, name: str) -> Any:
        from stackshot.core import config
        return getattr(config, name)


_cfg = _LazyConfig()

PLACEHOLDER = "the owner"        # the name of the one person when the config names nobody


@dataclass(frozen=True)
class Person:
    name: str                          # the stored key: the name as the config writes it
    aliases: tuple[str, ...] = ()      # the other names a line of next may open with for this person (never `you`, never the name itself)
    emails: tuple[str, ...] = ()       # the addresses that sign in as this person, as written
    declared: bool = True              # False for the placeholder made when the config names nobody

    @property
    def placeholder(self) -> bool:
        """The name is the generic word: it names no one a line may open with (`the owner:` is not an opener, `the owner's` and "the owner approved" are prose)."""
        return self.name == PLACEHOLDER

    @property
    def names(self) -> tuple[str, ...]:
        """What a line of next may open with for this person, the name first: none for the placeholder, which names no one."""
        return self.aliases if self.placeholder else (self.name, *self.aliases)


def _one_line(text: Any) -> str:
    """A name or an alias as the list keeps it: white space collapsed to single spaces, so `person_of`, `opener_person`, `names()` and the uniqueness check all read the same words."""
    return " ".join(str(text or "").split())


def _alias_list(raw: Any, name: str) -> tuple[str, ...]:
    """The aliases of a person: text on one line, no empty one, none equal to the name or to `you` (a line `you: …` is anyone's own), no repeat; [] when `raw` is no list."""
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for a in raw:
        a = _one_line(a)
        if a and a != name and a not in out and a.lower() != "you":
            out.append(a)
    return tuple(out)


def _address_list(raw: Any) -> tuple[str, ...]:
    return tuple(str(e) for e in raw) if isinstance(raw, list) else ()


def _inputs(cfg: dict[str, Any] | None) -> tuple[Any, Any, Any, Any, Any]:
    """The values the list is built from: the four config values as the file holds them (host words resolved, as every setting is), and the identities the front door lists
    for this board (None unless the board reads its members from a front door; imported at call time: that module reads the config, which reads this one)."""
    from stackshot.core import behind_door as _door
    return (_cfg.get("members", cfg=cfg), _cfg.get("instance", "owner", cfg=cfg),
            _cfg.get("instance", "owner_aliases", default=[], cfg=cfg), _cfg.get("auth", "allowed_emails", default=[], cfg=cfg), _door.people(cfg))


def _build(raw: tuple[Any, Any, Any, Any, Any]) -> list[Person]:
    listed, owner, aliases, emails, door = raw
    if door is not None:
        return [Person(name, _alias_list(list(aliases), name), tuple(addresses)) for name, aliases, addresses in door] or [Person(PLACEHOLDER, declared=False)]
    if isinstance(listed, list) and listed:
        out = []
        for t in listed:
            t = t if isinstance(t, dict) else {}
            name = _one_line(t.get("name"))
            out.append(Person(name, _alias_list(t.get("aliases"), name), _address_list(t.get("emails"))))
        return out
    name = _one_line(owner)
    return [Person(name or PLACEHOLDER, _alias_list(aliases, name or PLACEHOLDER), _address_list(emails), declared=bool(name))]


def build(cfg: dict[str, Any] | None = None) -> list[Person]:
    """The members of the config `cfg` (the running one when None), uncached: for a check that reads a config before it is the running one."""
    return _build(_inputs(cfg))


_seen: tuple[tuple[Any, Any, Any, Any, Any], list[Person]] | None = None


def members() -> list[Person]:
    """The members of the running config, in the order the config lists them; never empty. Rebuilt when one of its inputs differs from the last read."""
    global _seen
    raw = _inputs(None)
    if _seen is None or _seen[0] != raw:
        _seen = (copy.deepcopy(raw), _build(raw))
    return _seen[1]


def first() -> Person:
    """The person a bare `you`, an unnamed step or a notice with no person stands for: the first of the list (the only one while a board serves one person)."""
    return members()[0]


def naming() -> list[Person]:
    """The people a line of text is read against: `members()`, except where the front door's members file the config names is absent (`behind_door.members_file_absent`),
    and then the configured `[instance] owner` with its aliases and no sign-in address, followed by the placeholder (so "the owner" still reads). Never empty. For names
    only: nothing that decides membership, a sign-in or what is recorded asks here."""
    people = members()
    if len(people) != 1 or people[0].declared:
        return people
    from stackshot.core import behind_door as _door
    if not _door.members_file_absent():
        return people
    owner = _one_line(_cfg.get("instance", "owner"))
    aliases = _alias_list(_cfg.get("instance", "owner_aliases", default=[]), owner or PLACEHOLDER)
    if not owner and not aliases:
        return people
    return [Person(owner or PLACEHOLDER, aliases, declared=bool(owner)), *people]


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def person_of(text: Any) -> Person | None:
    """The person `text` names: a name or an alias, in any case, white space collapsed; None for anything else (a session, an outside party, `you`, empty text)."""
    t = _clean(text)
    if not t:
        return None
    for p in naming():
        if t == _clean(p.name) or any(t == _clean(a) for a in p.aliases):          # the configured words get the same white-space collapse as the text asked about
            return p
    return None


def person_of_email(address: Any) -> Person | None:
    """The person a sign-in address belongs to, the address as written (no case folding, as a sign-in has always been checked); None when no person has it."""
    a = str(address or "")
    if not a:
        return None
    for p in members():
        if a in p.emails:
            return p
    return None


def signed_in(address: Any) -> Person:
    """The person a sign-in address stands for when something is recorded under it: the person that has the address, else the first (an address the list does not name is still let in by
    the sign-in's own allow-list, and while the list has one person every address is that person's)."""
    return person_of_email(address) or first()


def recorded_by(rec: Any) -> str:
    """The name a stored record says it was made by: its `by` when it has one, else the first person (a record from before the key was written, a mail tick the server made). A name is the
    key a person is stored under, so a `by` that no list entry carries any more is still shown as it was written."""
    by = " ".join(str(rec.get("by") or "").split()) if isinstance(rec, dict) else ""
    return by or first().name


def stamp(rec: dict[str, Any], name: Any) -> dict[str, Any]:
    """Write `name` on the record `rec` as its `by`, unless it is the first person: a record with no `by` reads as the first person (`recorded_by`), so while the list has one person
    every record is written exactly as it was before the key existed. → `rec`."""
    name = " ".join(str(name or "").split())
    if name and name != first().name:
        rec["by"] = name
    return rec


def emails() -> list[str]:
    """Every address allowed to sign in, the first person's first: what the setup check counts and the portal's own identity falls back to."""
    return [e for p in members() for e in p.emails]


def names() -> list[str]:
    """Every name a line of next may open with, a person's name before its aliases and the placeholder left out: the words the matchers that read free text look for."""
    return [n for p in naming() for n in p.names]


def names_cf() -> set[str]:
    """The names a line of next may start with for a person, casefolded, the placeholder's included (what a mover is stored as when the config names nobody)."""
    return {n.casefold() for p in naming() for n in (p.name, *p.aliases)}


_RX: dict[tuple[tuple[str, ...], bool], Any] = {}


def opener_rx(to: bool = True):
    """A compiled regex for a who-takes-it opener of a line of next that names a person: `<name>:` (a name, an alias, or `you` in any case of its first letter), and with `to` also
    `<name> to …` for the names (never `the owner's`, `ACME-1` or "the owner approved …"). The names are matched as written. Cached per set of names."""
    key = (tuple(names()), to)
    if key not in _RX:
        alt = "|".join(re.escape(n) for n in key[0])
        colon = rf"(?:(?:{alt})|[Yy]ou)\s*:" if alt else r"[Yy]ou\s*:"
        _RX[key] = re.compile(rf"^(?:{colon}" + (rf"|(?:{alt})\s+to\b" if alt and to else "") + ")")
    return _RX[key]


def opener_person(line: Any) -> Person | None:
    """The person a line of next opens with (`<name>:` or `<name> to …`, `you:` for the first person), None when the line opens with no person."""
    s = str(line or "")
    if not opener_rx().match(s):
        return None
    people = naming()
    for p in people:
        for n in p.names:
            if re.match(rf"(?:{re.escape(n)})\s*:|(?:{re.escape(n)})\s+to\b", s):
                return p
    return people[0]        # the only opener left is `you`


def _kind_word(v: Any) -> str:
    """What a value is, in words a config's writer uses (never a Python type name)."""
    if isinstance(v, bool):
        return "true or false"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, dict):
        return "a table"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, str):
        return "text"
    return "another kind of value"


def _not_text(i: int, t: dict[str, Any]) -> list[str]:
    """One line per value of entry `i` that is no text: a name that is no string, an `aliases` or `emails` that is no list, an alias or an address in them that is no string. `build` would read such a value as its
    text (a number as digits) or drop it, so the check says so instead."""
    out: list[str] = []
    if "name" in t and not isinstance(t["name"], str):
        out.append(f"[[members]] entry {i}: name is not text ({_kind_word(t['name'])}): write it as a quoted string")
    for key in ("aliases", "emails"):
        if key not in t:
            continue
        if not isinstance(t[key], list):
            out.append(f"[[members]] entry {i}: {key} is not a list ({_kind_word(t[key])}): write it as a list of quoted strings")
            continue
        for n, v in enumerate(t[key], 1):
            if not isinstance(v, str):
                out.append(f"[[members]] entry {i}: {key} item {n} is not text ({_kind_word(v)}): write each as a quoted string")
    return out


def problems(cfg: dict[str, Any] | None = None) -> list[str]:
    """One line per fault of the config's `[[members]]` table (none when it is fine or absent): what the start and a reload refuse and doctor shows."""
    out: list[str] = []
    if _cfg.get("people", cfg=cfg) is not None:      # the table's first name: it is no longer read (no alias, no migration), so a file that still has it is told, not silently served as a board with no member list
        out.append("[[people]] is now [[members]]: rename the table, its keys are the same (the old name is no longer read)")
    listed = _cfg.get("members", cfg=cfg)
    if listed is None:
        return out
    if not isinstance(listed, list) or not all(isinstance(t, dict) for t in listed):
        return out + ["[[members]] is not a list of tables: write one [[members]] table per member, with name, aliases and emails"]
    seen_names: dict[str, int] = {}
    seen_mail: dict[str, int] = {}
    for i, t in enumerate(listed, 1):
        bad = _not_text(i, t)
        if bad:                         # a value that is no text is told, never coerced or dropped; the entry's other checks wait until it is fixed
            out += bad
            continue
        name = _one_line(t.get("name"))
        if not name:
            out.append(f"[[members]] entry {i} has no name")
            continue
        keys = [name, *_alias_list(t.get("aliases"), name)]
        for k in keys:
            if k.casefold() in seen_names and seen_names[k.casefold()] != i:      # the same word twice inside one entry is harmless: it is the same person
                out.append(f'[[members]] entry {i}: "{k}" is already the name or an alias of entry {seen_names[k.casefold()]} (names and aliases are unique without regard to case)')
            else:
                seen_names.setdefault(k.casefold(), i)
        said: set[str] = set()                  # an address written three times in one entry is told once
        for e in _address_list(t.get("emails")):
            if e in seen_mail and seen_mail[e] == i:
                if e not in said:
                    said.add(e)
                    out.append(f'[[members]] entry {i}: the address "{e}" is written twice in its emails (keep it once)')
            elif e in seen_mail:
                out.append(f'[[members]] entry {i}: the address "{e}" is already entry {seen_mail[e]}\'s')
            else:
                seen_mail[e] = i
    return out
