"""project_restore.py — put the project record (or one project of it) back from a past revision of the data repository.

The record file (`<store>/project-record.json`, projects.py) sits in the store's git repository, which the server commits and pushes within seconds of every change, so every
revision the record has had is in that repository's history. `project.py restore` reads one of them and writes it back through the record's own save path (projects._write, under
the record's flock), after keeping an undo copy of the file as it was. The repository is only read, with `git -C <repo> rev-parse`, `rev-list`, `log` and `show REV:<path>`: never a checkout, a
reset, a pull or a write of any kind in it.

    restore(project, rev=…)        a dry run (the default): what would change, and nothing is written
    restore(project, rev=…, apply=True)
                                   writes it; the answer carries the undo file
    restore_list(limit)            the last revisions of the record file, one line each
    restore_undo(file, apply=…)    puts back what a restore replaced

With a PROJECT (an id, a page key, a bare slug, the name or a former name, looked up in the REVISION's record) only that project's entry comes back, merged into the current record:
the entry as saved, its row of the id table, the rows of its page's sub-pages and former keys that the id table lacks now, and its mark. Everything else in the current record stays.
Without one, the whole file comes back as saved, and what was made after the revision is gone from it (the dry run says which projects those are).

Refused, with nothing written (VerbError; the CLI exits 1): a revision git does not know, or one with no record file; a record at that revision that does not read; a PROJECT the revision
does not hold; an entry that would sit on the page key of a live project with another id, or take the name of one; a record that is being written (the lock stays held for the five seconds
the restore waits); for one project, a current record that does not read (restore the whole file then).

Stdlib plus the repo's modules; no network."""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.projects import project_registry as pr
from stackshot.projects import projects as prj

RECORD = "project-record.json"
LIST_LIMIT = 20                       # revisions `--list` shows when no --limit is given
LOCK_WAIT = 5.0                       # seconds an apply waits for the record's lock before it says the record is being written
SHOW = 40                             # lines of one kind in the answer's text (the structured answer holds them all)
GIT_TIMEOUT = 60


def default_run_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "stackshot-runs" / "project-restore"


def _err(status: int, message: str) -> Exception:
    from stackshot.projects.project_verbs import VerbError
    return VerbError(status, message)


# ----------------------------------------------------------------------------- git, read-only
GIT_KEEP = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")     # the GIT_ variables a call keeps: where git reads its own settings from (a test points them at nothing); every other one is dropped


def git_env() -> dict:
    """The environment of a git call: the caller's, without the GIT_ variables that would point git away from the repository named with -C (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE,
    GIT_OBJECT_DIRECTORY, GIT_CEILING_DIRECTORIES, ...) or change what it reads, TZ set to the instance's zone (so a date git reads without an offset is instance-local, as every date here is shown)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in GIT_KEEP}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C", TZ=str(_cfg.tz()))
    return env


def _git(repo: Path, *args: str) -> tuple[int, bytes]:
    env = git_env()
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _err(409, f"git could not be run in {repo}: {e}") from None
    return r.returncode, r.stdout


def where() -> tuple[Path, str]:
    """(the data repository's top folder, the record file's path inside it) for the current store."""
    store = prj.record_path().parent
    rc, out = _git(store, "rev-parse", "--show-toplevel", "--show-prefix")
    lines = out.decode("utf-8", "replace").split("\n")
    if rc != 0 or not lines or not lines[0]:
        raise _err(409, f"the store folder {store} is not inside a git repository, so there is no history to restore from")
    return Path(lines[0]), lines[1].strip() + RECORD


YEARS = (1970, 2099)                  # the years a --before date may name (a date git would take as the past or the future is no date of the record's history)
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def parse_before(text: str) -> dt.datetime:
    """`--before DATE` as an aware time: YYYY-MM-DD, optionally with HH:MM[:SS] and a zone (Z, +0900 or +09:00). With no zone it is the instance's (the zone every date here is shown in);
    a date alone is its midnight. Anything else is refused (400): git reads any text as a date and takes a word it cannot read for now."""
    m = _DATE.match(str(text or "").strip())
    if not m:
        raise _err(400, f"not a date: {text!r} (write YYYY-MM-DD, or YYYY-MM-DD HH:MM, with a zone like +0900 if it is not the instance's {_cfg.tz_abbr()})")
    y, mo, d, h, mi, sec, zone = m.groups()
    bad = lambda why: _err(400, f"not a date: {text!r} ({why})")
    if not YEARS[0] <= int(y) <= YEARS[1]:
        raise bad(f"the year is {YEARS[0]} to {YEARS[1]}")
    try:
        naive = dt.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(sec or 0))
    except ValueError as e:
        raise bad(str(e)) from None
    if not zone:
        when = naive.replace(tzinfo=_cfg.tz())
    elif zone == "Z":
        when = naive.replace(tzinfo=dt.timezone.utc)
    else:
        z = zone.replace(":", "")
        hh, mm = int(z[1:3]), int(z[3:5])
        if mm > 59 or hh * 60 + mm > 840:
            raise bad(f"the zone {zone} is not an offset (+0000 to +1400)")
        off = dt.timedelta(hours=hh, minutes=mm)
        when = naive.replace(tzinfo=dt.timezone(-off if z[0] == "-" else off))
    if not YEARS[0] <= when.astimezone(dt.timezone.utc).year <= YEARS[1]:
        raise bad(f"that moment is outside {YEARS[0]} to {YEARS[1]}")
    return when


def local(when: dt.datetime) -> dt.datetime:
    """The moment in the instance's zone, through UTC (a wall time that does not exist there, in a DST gap, reads as the real moment after it)."""
    return when.astimezone(dt.timezone.utc).astimezone(_cfg.tz())


def git_date(when: dt.datetime) -> str:
    """The moment as git reads it without any zone arithmetic of its own: UTC, written with +0000."""
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")


def resolve_rev(repo: Path, rel: str, rev: str = "", before: str = "") -> str:
    """The full commit id a revision names: any git revision (a sha, HEAD~5, a branch, a tag), or with `before` the last commit that changed the record file before that date."""
    if bool(rev) == bool(before):
        raise _err(400, "name one revision: --from-git REV, or --before DATE")
    if before:
        when = parse_before(before)
        rc, out = _git(repo, "rev-list", "-1", f"--before={git_date(when)}", "HEAD", "--", rel)
        sha = out.decode().strip()
        if rc != 0 or not sha:
            raise _err(404, f"no revision of {rel} from before {before!r} ({local(when):%Y-%m-%d %H:%M} {_cfg.tz_abbr(when)}) in the history")
        return sha
    if rev.startswith("-"):
        raise _err(400, f"not a git revision: {rev!r}")
    rc, out = _git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}")
    sha = out.decode().strip()
    if rc != 0 or not sha:
        raise _err(404, f"git does not know the revision {rev!r} in {repo}")
    return sha


def _when(repo: Path, sha: str) -> dt.datetime:
    rc, out = _git(repo, "log", "-1", "--format=%ct", sha)
    try:
        return dt.datetime.fromtimestamp(int(out.decode().strip()), _cfg.tz())
    except ValueError:
        return dt.datetime.fromtimestamp(0, _cfg.tz())


def _words(when: dt.datetime) -> str:
    from stackshot.web.whatschanged import day_words
    return f"{day_words(when.date())} {when:%H:%M} {_cfg.tz_abbr(when)}"


def _show(repo: Path, sha: str, rel: str) -> bytes | None:
    rc, out = _git(repo, "show", f"{sha}:{rel}")
    return out if rc == 0 else None


# ----------------------------------------------------------------------------- the record as a table of parts
def shape(doc: Any) -> dict:
    """A parsed record file in the shape projects._read gives (ids, pending_agents, marks, extra), checked as _read checks it, and its projects section as project_registry.parse
    checks it. Raises ValueError naming the first problem."""
    bad = lambda why: ValueError(why)
    if not isinstance(doc, dict):
        raise bad("the record is not an object")
    if doc.get("schema", prj.SCHEMA) != prj.SCHEMA:
        raise bad(f"schema {doc.get('schema')!r}, this code reads {prj.SCHEMA}")
    ids, pend, marks = doc.get("ids", {}), doc.get("pending_agents", {}), doc.get("marks", {})
    if not isinstance(ids, dict):
        raise bad("ids is not an object")
    for i, k in ids.items():
        if not prj.is_id(i) or not isinstance(k, str) or not k:
            raise bad(f"ids entry {i!r}")
    if not isinstance(pend, dict):
        raise bad("pending_agents is not an object")
    for i, m in pend.items():
        if not prj.is_id(i) or not isinstance(m, dict) or not all(isinstance(a, dict) for a in m.values()):
            raise bad(f"pending_agents entry {i!r}")
    if not isinstance(marks, dict):
        raise bad("marks is not an object")
    for i, m in marks.items():
        if not prj.is_id(i) or not isinstance(m, dict):
            raise bad(f"marks entry {i!r}")
    pr.parse({pr.SECTION: doc.get(pr.SECTION, {}), pr.VERSION: doc.get(pr.VERSION, pr.SCHEMA)})
    return {"schema": prj.SCHEMA, "ids": dict(ids), "pending_agents": {i: dict(m) for i, m in pend.items()}, "marks": {i: dict(m) for i, m in marks.items()},
            "extra": {k: v for k, v in doc.items() if k not in ("schema", "ids", "pending_agents", "marks")}}


def _ents(d: dict) -> dict:
    return dict(d["extra"].get(pr.SECTION) or {})


def _set_ents(d: dict, ents: dict) -> None:
    if ents:
        d["extra"][pr.SECTION] = ents; d["extra"][pr.VERSION] = pr.SCHEMA
    else:
        d["extra"].pop(pr.SECTION, None); d["extra"].pop(pr.VERSION, None)


def _other(d: dict) -> dict:
    return {k: v for k, v in d["extra"].items() if k not in (pr.SECTION, pr.VERSION)}


def load_rev(repo: Path, rel: str, sha: str) -> dict:
    data = _show(repo, sha, rel)
    if data is None:
        raise _err(404, f"revision {sha[:10]} has no {rel}")
    try:
        return shape(json.loads(data.decode("utf-8")))
    except ValueError as e:                                 # UnicodeDecodeError and JSONDecodeError are ValueErrors
        raise _err(422, f"the record at revision {sha[:10]} does not read: {e}") from None


def _current() -> tuple[dict | None, str, bytes | None]:
    """(the current record's parts, why it cannot be read or "", its file's bytes or None when there is no file)."""
    p = prj.record_path()
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return {"schema": prj.SCHEMA, "ids": {}, "pending_agents": {}, "marks": {}, "extra": {}}, "", None
    try:
        return shape(json.loads(raw.decode("utf-8"))), "", raw
    except ValueError as e:
        return None, str(e), raw


def _sha(data: bytes | None) -> str:
    return "" if data is None else hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------------- finding the project in the revision
def find(project: str, ents: dict, ids: dict) -> str:
    """The id of the project `project` names in a record's entries: an id, a page key (a current one, a bare slug through [registries.projects] match, a former key), the name or a former name. "" when none."""
    x = str(project or "").strip()
    if not x:
        return ""
    if prj.is_id(x):
        return x if x in ents else ""
    k = pr._norm_key(x)
    pats = (_cfg.CFG.get("registries", {}).get("projects", {}) or {}).get("match") or ["{value}"]
    cands = list(dict.fromkeys([k] + [p.format(value=k) for p in pats]))
    cur, old = pr.by_page(ents), pr.by_former_key(ents)
    for c in cands:
        if c in cur:
            return cur[c]
    for c in cands:
        if c in old:
            return old[c]
    for pid, e in sorted(ents.items()):
        if str(e.get("name") or "").casefold() == x.casefold():
            return pid
    for pid, e in sorted(ents.items()):
        if k and k in (e.get("former_names") or []):
            return pid
    for c in cands:                                          # a key an id of the id table holds that has an entry: the project's own page
        for i, key in sorted(ids.items()):
            if key == c and i in ents:
                return i
    return ""


# ----------------------------------------------------------------------------- the change, as a plan
def _label(pid: str, e: dict | None) -> str:
    e = e or {}
    n = e.get("name") or pr.page_key(e) or e.get("title") or ""
    return f"{pid} ({n})" if n else pid


def _short(v: Any) -> str:
    if v is None:
        return "(none)"
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v)
    return s if len(s) <= 70 else s[:67] + "..."


def _agents_change(a: dict, b: dict) -> str:
    parts = []
    gone, new = [n for n in a if n not in b], [n for n in b if n not in a]
    if new:
        parts.append("back: " + ", ".join(new))
    if gone:
        parts.append("off: " + ", ".join(gone))
    mand = [n for n in a if n in b and a[n].get("mandate_line") != b[n].get("mandate_line")]
    if mand:
        parts.append("mandate line changed: " + ", ".join(mand))
    side = [n for n in a if n in b and a[n].get("front") != b[n].get("front")]
    if side:
        parts.append("front/background changed: " + ", ".join(side))
    other = [n for n in a if n in b and a[n] != b[n] and n not in mand and n not in side]
    if other:
        parts.append("other fields of: " + ", ".join(other))
    ca, cb = [n for n in a if n in b], [n for n in b if n in a]
    if ca != cb:
        parts.append(f"order (the first builder listed is the builder): {', '.join(a)} -> {', '.join(b)}")
    return "agents: " + "; ".join(parts)


def describe(old: dict, new: dict) -> list[str]:
    """One line for each field of an entry that differs: `field: old -> new` (the agents map says which agents)."""
    out = []
    for f in list(dict.fromkeys(list(old) + list(new))):
        a, b = old.get(f), new.get(f)
        if a == b and (f != "agents" or list(a) == list(b)):
            continue
        out.append(_agents_change(a or {}, b or {}) if f == "agents" else f"{f}: {_short(a)} -> {_short(b)}")
    return out


def canon_entry(e: dict) -> Any:
    """An entry as a value that compares equal only when it is the same record: its agents map as a list in its order (the first builder listed is the builder), the rest as the dict."""
    return {k: ([[n, v] for n, v in val.items()] if k == "agents" and isinstance(val, dict) else val) for k, val in e.items()}


def _canon_ents(ents: dict) -> dict:
    return {i: canon_entry(e) for i, e in ents.items()}


def _diff(cur: dict, new: dict) -> tuple[list, list, list]:
    return (sorted(k for k in new if k not in cur), sorted(k for k in cur if k not in new), sorted(k for k in cur if k in new and cur[k] != new[k]))


def fingerprint(d: dict) -> str:
    """A hash of what a record holds, independent of how the file is laid out (the agents' order counts): the same for the parts a restore plans to write and for the file read back after it."""
    doc = [d["ids"], d["pending_agents"], d["marks"], _other(d), _canon_ents(_ents(d))]
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def plan(cur: dict | None, why_cur: str, rev: dict, project: str, sha: str) -> dict:
    """What a restore of `project` (or the whole record when "") from the revision `rev` (the parts of its record) would do to the current parts `cur` (None: the file does not read, `why_cur`).
    → {"mode", "project", "new": the parts to write, "changed", "added", "removed", "changed_projects", "status_changes" ({id: [was, now]}, "" for a project that comes back), "ids", "marks", "pending", "other", "lines", "notes"}. Raises VerbError for a refusal."""
    rev_ents = _ents(rev)
    if project:
        if cur is None:
            raise _err(422, f"the current record does not read ({why_cur}): a single project cannot be merged into it; restore the whole record instead (leave PROJECT out)")
        pid = find(project, rev_ents, rev["ids"])
        if not pid:
            raise _err(404, f"{project!r} is not a project in revision {sha[:10]}"
                            + (" (that revision has no project entries at all: the record held none yet)" if not rev_ents else ""))
        new = copy.deepcopy(cur)
        cur_ents = _ents(cur)
        ent = copy.deepcopy(rev_ents[pid])
        key = pr.page_key(ent)
        for q, e in sorted(cur_ents.items()):
            if q == pid:
                continue
            if key and pr.page_key(e) == key:
                raise _err(409, f"{pid} cannot come back: the live project {_label(q, e)} is on the same page key {key}; archive or move one of them first, nothing was changed")
            if ent.get("name") and str(e.get("name") or "").casefold() == str(ent["name"]).casefold():
                raise _err(409, f"{pid} cannot come back: the live project {_label(q, e)} has the same name {ent['name']!r}; rename one of them first, nothing was changed")
        cur_ent = cur_ents.get(pid) or {}
        fresh = ({key} if key and key != pr.page_key(cur_ent) else set()) | {pr._norm_key(k) for k in ent.get("former_keys") or []} - {pr._norm_key(k) for k in cur_ent.get("former_keys") or []}
        if pid in rev["ids"] and rev["ids"][pid] != cur["ids"].get(pid):
            fresh.add(rev["ids"][pid])
        for k in sorted(fresh - {""}):
            for q in sorted(set(cur["ids"]) | set(cur_ents)):
                if q == pid:
                    continue
                e = cur_ents.get(q) or {}
                if cur["ids"].get(q) == k or pr.page_key(e) == k or k in [pr._norm_key(x) for x in e.get("former_keys") or []]:
                    raise _err(409, f"{pid} cannot come back: the page key {k} (its page, a former key or its id row) is already held by the live id {_label(q, e)}; "
                                    f"move or retire that one first, nothing was changed")
        ents = dict(cur_ents); ents[pid] = ent
        _set_ents(new, ents)
        notes = []
        if pid in rev["ids"]:
            new["ids"][pid] = rev["ids"][pid]
        held = {}
        for i, k in sorted(new["ids"].items()):
            held.setdefault(k, i)
        own = {key, *[pr._norm_key(k) for k in ent.get("former_keys") or []]} - {""}
        for i, k in sorted(rev["ids"].items()):
            if i == pid or i in new["ids"]:
                continue
            if k in own or (key and k.startswith(key + "/")):
                if k in held:
                    notes.append(f"the id row {i} -> {k} of that revision is not restored: {held[k]} holds that key now")
                    continue
                new["ids"][i] = k; held[k] = i
        if pid in rev["marks"]:
            new["marks"][pid] = copy.deepcopy(rev["marks"][pid])
    else:
        pid = ""
        new = copy.deepcopy(rev)
        cur_ents = _ents(cur) if cur is not None else {}
        notes = []
        if cur is None:
            notes.append(f"the current record does not read ({why_cur}): the file would be replaced; the damaged file is kept in the undo folder")
    cur_parts = cur if cur is not None else {"ids": {}, "pending_agents": {}, "marks": {}, "extra": {}}
    new_ents = _ents(new)
    added, removed, changed = _diff(_canon_ents(cur_ents), _canon_ents(new_ents))
    if project:
        removed = []
    cp = {i: describe(cur_ents[i], new_ents[i]) for i in changed}
    status_changes = {i: [cur_ents[i].get("status") or "active", new_ents[i].get("status") or "active"] for i in changed
                      if (cur_ents[i].get("status") or "active") != (new_ents[i].get("status") or "active")}
    status_changes.update({i: ["", new_ents[i].get("status") or "active"] for i in added if (new_ents[i].get("status") or "active") == "archived"})
    ids = _diff(cur_parts["ids"], new["ids"]); marks = _diff(cur_parts["marks"], new["marks"]); pend = _diff(cur_parts["pending_agents"], new["pending_agents"])
    other = _diff(_other(cur_parts), _other(new))
    is_changed = cur is None or fingerprint(cur) != fingerprint(new)
    p = {"mode": "project" if project else "record", "project": pid, "new": new, "changed": is_changed, "added": added, "removed": removed, "changed_projects": cp,
         "ids": {"added": ids[0], "removed": ids[1], "changed": ids[2]}, "marks": {"added": marks[0], "removed": marks[1], "changed": marks[2]},
         "pending": {"added": pend[0], "removed": pend[1], "changed": pend[2]}, "other": {"added": other[0], "removed": other[1], "changed": other[2]}, "notes": notes,
         "fingerprint": fingerprint(new), "status_changes": status_changes}
    p["lines"] = _lines(p, cur_ents, new_ents, cur_parts, new, len(cur_ents), len(new_ents))
    return p


def _cap(lines: list[str], n: int = SHOW) -> list[str]:
    return lines if len(lines) <= n else lines[:n] + [f"  ... and {len(lines) - n} more (--json lists them all)"]


def _lines(p: dict, cur_ents: dict, new_ents: dict, cur: dict, new: dict, n_now: int, n_after: int) -> list[str]:
    out: list[str] = []
    sc = p.get("status_changes") or {}
    if p["mode"] == "project":
        pid = p["project"]
        if pid in sc:
            was, now = sc[pid]
            out.append("THIS " + ("UN-ARCHIVES IT: archived now, active as saved" if (was, now) == ("archived", "active") else "RETIRES IT: active now, archived as saved" if (was, now) == ("active", "archived")
                                   else "BRINGS IT BACK ARCHIVED" if not was else f"CHANGES ITS STATUS: {was} now, {now} as saved"))
        if pid in p["added"]:
            out.append(f"project {_label(pid, new_ents[pid])}: not in the current record, comes back")
        elif pid in p["changed_projects"]:
            out.append(f"project {_label(pid, new_ents[pid])}: in the current record, restored as saved")
            out += [f"  {ln}" for ln in p["changed_projects"][pid]]
        else:
            out.append(f"project {_label(pid, new_ents[pid])}: the current entry is the saved one already")
    else:
        out.append(f"projects: {n_now} now, {n_after} after (+{len(p['added'])} come back, {len(p['changed_projects'])} changed, -{len(p['removed'])} gone)")
        out += _cap([f"  + {_label(i, new_ents[i])} comes back" for i in p["added"]])
        out += _cap([f"  - {_label(i, cur_ents[i])} is not in that revision (made after it): gone from the record" for i in p["removed"]])
        for i in p["changed_projects"]:
            out.append(f"  ~ {_label(i, new_ents[i])}")
            out += [f"      {ln}" for ln in p["changed_projects"][i]]
        out = out[:1] + _cap(out[1:], SHOW * 3)
        groups: dict = {}
        for i, (w, n) in sorted(sc.items()):
            word = ("THIS UN-ARCHIVES" if (w, n) == ("archived", "active") else "THIS RETIRES" if (w, n) == ("active", "archived")
                    else "THIS BRINGS BACK ARCHIVED" if not w else f"THIS CHANGES STATUS ({w} now, {n} as saved)")
            groups.setdefault(word, []).append(_label(i, new_ents[i]))
        for k, (word, names) in enumerate(groups.items()):
            out.insert(1 + k, f"{word}: " + ", ".join(names))
    for name, table, cur_t, new_t in (("ids", p["ids"], cur["ids"], new["ids"]), ("marks", p["marks"], cur["marks"], new["marks"]),
                                       ("pending agents", p["pending"], cur["pending_agents"], new["pending_agents"])):
        if not any(table.values()):
            continue
        out.append(f"{name}: +{len(table['added'])} -{len(table['removed'])} ~{len(table['changed'])}")
        fmt = (lambda v: v) if name == "ids" else (lambda v: _short(v))
        out += _cap([f"  + {i}: {fmt(new_t[i])}" for i in table["added"]] + [f"  - {i}: {fmt(cur_t[i])}" for i in table["removed"]]
                    + [f"  ~ {i}: {fmt(cur_t[i])} -> {fmt(new_t[i])}" for i in table["changed"]])
    if any(p["other"].values()):
        names = sorted(set(p["other"]["added"]) | set(p["other"]["removed"]) | set(p["other"]["changed"]))
        out.append("other top-level fields of the file: " + ", ".join(names))
    out += [f"note: {n}" for n in p["notes"]]
    if not p["changed"]:
        out.append("nothing to restore: the record already holds this as saved")
    return out


# ----------------------------------------------------------------------------- the verb
def _probe_lock() -> None:
    """Refuse when another process holds the record's lock for LOCK_WAIT seconds (the server is writing): the same flock file projects.locked takes."""
    lk = _cfg.state("project-record.lock"); lk.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + LOCK_WAIT
    with open(lk, "a") as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(f, fcntl.LOCK_UN)
                return
            except OSError:
                if time.monotonic() >= end:
                    raise _err(409, f"the record is being written (its lock {lk} stayed held for {LOCK_WAIT:g} s): try again in a moment, nothing was changed") from None
                time.sleep(0.1)


def _record_after(meta: dict, undo_file: Path) -> None:
    """Note in the undo file the hash of the record file as written (a crash before this leaves the planned fingerprint, written before the record, for the undo to go by)."""
    meta["after_sha256"] = _sha(prj.record_path().read_bytes())
    prj.write_atomic(undo_file, json.dumps(meta, indent=1, ensure_ascii=False) + "\n")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())


def restore(project: str = "", *, rev: str = "", before: str = "", apply: bool = False, by: str = "", run_dir: Path | str | None = None, now: str | None = None) -> dict:
    """Restore `project` (or the whole record when "") from the git revision `rev` (or the last one before `before`). Dry run unless `apply`."""
    repo, rel = where()
    sha = resolve_rev(repo, rel, rev, before)
    revd = load_rev(repo, rel, sha)
    when = _when(repo, sha)
    head = f"restore {project or 'the whole record'} from {sha[:10]} ({_words(when)})"
    picked = ""
    if before:
        b = local(parse_before(before))
        picked = f"revision picked: the last change to the record before {b:%Y-%m-%d %H:%M} {_cfg.tz_abbr(b)} (read in the instance's zone unless the date names its own)"
    res: dict = {"verb": "restore", "dry": not apply, "rev": sha, "when": when.isoformat(), "repo": str(repo), "path": rel, "undo": None}
    if not apply:
        cur, why, _t = _current()
        p = plan(cur, why, revd, project, sha)
        res.update({k: p[k] for k in ("mode", "project", "changed", "added", "removed", "changed_projects", "status_changes", "ids", "marks", "pending", "other", "notes")})
        res["lines"] = [f"dry run: {head}"] + ([picked] if picked else []) + p["lines"] + ([] if not p["changed"] else ["nothing written (add --apply)"])
        return res
    _probe_lock()
    with prj.locked():
        cur, why, text = _current()
        p = plan(cur, why, revd, project, sha)
        res.update({k: p[k] for k in ("mode", "project", "changed", "added", "removed", "changed_projects", "status_changes", "ids", "marks", "pending", "other", "notes")})
        if not p["changed"]:
            res["lines"] = [head] + p["lines"]
            return res
        stamp = (now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")).replace("-", "").replace(":", "")
        base = Path(run_dir).expanduser() if run_dir else default_run_dir()
        base = base / stamp
        n = 1
        while base.exists():                                  # two restores in one second keep two undo copies
            n += 1; base = base.with_name(f"{stamp}-{n}")
        before_file = base / "project-record.before.json"
        if text is not None:
            _write_bytes(before_file, text)                   # the previous file, whole, before the first write
        cur_ents = _ents(cur) if cur is not None else {}
        pid = p["project"]
        meta: dict = {"schema": 1, "made": stamp, "by": by or "cli", "record": str(prj.record_path()), "before": str(before_file) if text is not None else "",
                      "before_sha256": _sha(text), "after_sha256": "", "planned_fingerprint": p["fingerprint"], "rev": sha, "mode": p["mode"], "project": pid}
        if pid:
            new_ents = _ents(p["new"])
            meta["restored"] = {"entry": new_ents[pid], "ids": {i: p["new"]["ids"][i] for i in p["ids"]["added"] + p["ids"]["changed"]},
                                "marks": {i: p["new"]["marks"][i] for i in p["marks"]["added"] + p["marks"]["changed"]}}
            meta["prior"] = {"entry": cur_ents.get(pid), "ids": {i: cur["ids"].get(i) for i in p["ids"]["added"] + p["ids"]["changed"]},
                             "marks": {i: cur["marks"].get(i) for i in p["marks"]["added"] + p["marks"]["changed"]}}
        undo_file = base / "undo.json"
        prj.write_atomic(undo_file, json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
        prj._write(p["new"])
        try:
            _record_after(meta, undo_file)
        except OSError as e:                                  # the record is right; the undo file keeps the planned fingerprint, which the whole-file undo reads in place of the hash
            res["warning"] = f"the undo file could not be completed ({e})"
    res["undo"] = str(undo_file)
    res["lines"] = [head] + ([picked] if picked else []) + p["lines"] + [f"written. undo file {undo_file}", f"to undo: project.py restore --undo {undo_file} --apply"]
    return res


# ----------------------------------------------------------------------------- --list
def _count_line(doc_new: dict | None, doc_old: dict | None) -> str:
    n = len(_ents(doc_new))
    if doc_old is None:
        return f"{n} projects, {len(doc_new['ids'])} ids"
    added, removed, changed = _diff(_ents(doc_old), _ents(doc_new))
    ia, ir, ic = _diff(doc_old["ids"], doc_new["ids"])
    return f"{n} projects (+{len(added)} -{len(removed)} ~{len(changed)}), {len(doc_new['ids'])} ids (+{len(ia)} -{len(ir)})"


def restore_list(limit: int = LIST_LIMIT, *, rev: str = "") -> dict:
    """The last `limit` revisions of the record file, newest first: {"revisions": [{rev, when, projects, summary}], "lines": [...]}."""
    repo, rel = where()
    limit = max(1, int(limit))
    start = resolve_rev(repo, rel, rev) if rev else "HEAD"
    rc, out = _git(repo, "log", f"-n{limit + 1}", "--format=%H %ct", start, "--", rel)
    if rc != 0:
        raise _err(404, f"git has no history for {rel} from {rev or 'HEAD'} in {repo}")
    revs = [ln.split() for ln in out.decode().splitlines() if ln.strip()]
    if not revs:
        raise _err(404, f"{rel} has no revisions in {repo}")
    docs: list = []
    for sha, _ct in revs:
        try:
            docs.append(load_rev(repo, rel, sha))
        except Exception as e:  # noqa: BLE001 — a revision that does not read is listed as such, not a failure of the list
            docs.append(str(getattr(e, "message", e)))
    rows, lines = [], []
    for i, (sha, ct) in enumerate(revs[:limit]):
        when = dt.datetime.fromtimestamp(int(ct), _cfg.tz())
        d = docs[i]
        if isinstance(d, str):
            summary = "does not read: " + d.split("does not read: ", 1)[-1]; n = None
        else:
            older = docs[i + 1] if i + 1 < len(docs) and not isinstance(docs[i + 1], str) else None
            summary = _count_line(d, older); n = len(_ents(d))
        rows.append({"rev": sha, "when": when.isoformat(), "projects": n, "summary": summary})
        lines.append(f"{sha[:10]}  {_words(when)}  {summary}")
    return {"verb": "restore", "list": True, "repo": str(repo), "path": rel, "revisions": rows,
            "lines": [f"the last {len(rows)} revisions of {rel} (newest first; times in {_cfg.tz_abbr()}):"] + lines
                     + ["to restore one: project.py restore --from-git <rev> [PROJECT] (a dry run until --apply)"]}


# ----------------------------------------------------------------------------- --undo
def restore_undo(path: Path | str, *, apply: bool = False) -> dict:
    """Put back what the restore that wrote the undo file `path` replaced. The file is put back whole when the record is still the one the restore wrote; when something else was written since,
    a restore of one project takes back only its own parts (the entry, the id rows, the marks) and refuses when any of them changed since; a restore of the whole record then refuses."""
    path = Path(path).expanduser()
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        rec = Path(meta["record"]); saved = meta.get("before") or ""; want = meta.get("after_sha256") or ""
        mode = meta.get("mode") or "record"; pid = meta.get("project") or ""; planned = meta.get("planned_fingerprint") or ""
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise _err(422, f"undo file {path}: not readable ({e})") from None
    if rec != prj.record_path():
        raise _err(409, f"the undo file is for the record {rec}, this instance's is {prj.record_path()}: nothing changed")
    res: dict = {"verb": "restore", "undo_of": str(path), "dry": not apply}
    if apply:
        _probe_lock()
    with prj.locked():
        cur_text = _read_bytes(rec)
        before = None
        if saved:
            before = _read_bytes(Path(saved))
            if before is None:
                raise _err(409, f"the saved record file {saved} is missing; nothing changed")
            if cur_text == before:
                res["lines"] = ["the record is the saved file already; nothing to do"]; res["changed"] = False
                return res
        if (want and _sha(cur_text) == want) or (planned and _is_planned(cur_text, planned)):   # still what the restore wrote (its hash, or, when it did not get to note it, what it planned): the file as it was comes back whole
            if apply:
                if saved:
                    _restore_file(rec, before)
                else:
                    rec.unlink()
            res["changed"] = True
            res["lines"] = [("" if apply else "dry run: ") + ("put the record file back as it was before the restore" + (f" ({saved})" if saved else " (it did not exist: removed)")) + ("" if apply else "; nothing written (add --apply)")]
            return res
        if mode != "project" or not pid or "prior" not in meta:
            raise _err(409, f"the record was written after the restore, so the file before it cannot go back whole without losing that; nothing changed. The file as it was is {saved or '(none: there was no file)'}")
        cur = prj._read()
        ents = _ents(cur)
        why = []
        r, prior = meta.get("restored") or {}, meta["prior"]
        if ents.get(pid) != r.get("entry"):
            why.append(f"the entry of {pid} changed since")
        for name in ("ids", "marks"):
            for i, v in (r.get(name) or {}).items():
                if cur[name].get(i) != v:
                    why.append(f"{name[:-1]} row {i} changed since")
        if why:
            raise _err(409, "the restore cannot be taken back part by part: " + "; ".join(why) + "; nothing changed")
        if prior.get("entry") is None:
            ents.pop(pid, None)
        else:
            ents[pid] = prior["entry"]
        for name in ("ids", "marks"):
            for i, old in (prior.get(name) or {}).items():
                if old is None:
                    cur[name].pop(i, None)
                else:
                    cur[name][i] = old
        _set_ents(cur, ents)
        res["changed"] = True
        res["lines"] = [("" if apply else "dry run: ") + f"the record changed after the restore: take back only {pid}'s entry ({'removed' if prior.get('entry') is None else 'as it was'}), "
                        f"{len(prior.get('ids') or {})} id rows and {len(prior.get('marks') or {})} marks; everything else stays" + ("" if apply else "; nothing written (add --apply)")]
        if apply:
            prj._write(cur)
    return res


def _restore_file(rec: Path, data: bytes) -> None:
    """The saved bytes back as the record file, through the same atomic write (the text is the file's, read as UTF-8; a file that was not valid UTF-8 is written byte for byte)."""
    try:
        prj.write_atomic(rec, data.decode("utf-8"))
    except UnicodeDecodeError:
        _write_bytes(rec, data)


def _is_planned(data: bytes | None, planned: str) -> bool:
    if data is None:
        return False
    try:
        return fingerprint(shape(json.loads(data.decode("utf-8")))) == planned
    except ValueError:
        return False


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
