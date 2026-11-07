"""Project anchors (an anchor is a property of a project, never of an item).

An anchor is an external thing anchor-hub watches — a Slack channel or DM, a Drive file or folder, a Gmail thread or
gmail:q: query, a Notion page or database, a GitHub issue/PR or a repo's releases feed. It belongs to a project (the gbrain page,
`projects/<slug>` or `infra/<slug>`), which keeps it, and carries a scope: project-wide, or a list of the items it is about. An anchor counts
for a scoped item from whichever project's page holds it (anchor_scope.py is the one reader of that: the server, the board and the model guards use it).
Sessions are derived, never stored on the anchor: the project's name-line session (the page's `display-name:`; pages.py reads it with
`agent:` and the older `session:` into the registry's `session`) plus the movers of the open items in scope. Completing
an item changes that set and prompts the keeper about the anchors scoped to it;
nothing is dropped by a completion.

Store: board-data/anchors.json  {"<project key>": [{"url": …, "items": [ids] | null, "added": ts, "by": who}, …]},
written only by the stackshot server (this module), read by anchor-hub (bindings) and the board (render).
Stdlib only: imported by server.py and by anchor-hub (anchorhub/core.py).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import Any

import config as _cfg  # noqa: E402  (stackshot.toml; next to this module)
import project_registry as _pr  # noqa: E402  (the project record's entries: read first, the page lines are the fallback)
import item_project as _iproj  # noqa: E402  (an item's project by its permanent id: the page key it reads through the id)
import readonly as _ro  # noqa: E402  (a warm standby copy writes nothing)
import sessions_registry as _sr  # noqa: E402  (the permanent session ids; every lookup is None while there is no registry)

STORE = _cfg.path("paths", "store")
FILE = STORE / "anchors.json"
REGISTRY = STORE / "projects.json"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# ---------- session identity ----------
class _Names(dict):
    """uuid → name of every session the view holds, the identity records of gone sessions included (a retired owner still
    has a name). `by_name` resolves a name the way every reader does (fleet.by_name, present sessions only): a running
    session first, then one gone for less than the grace; a name only a retired session carries resolves to nothing."""
    by_name: dict[str, str] = {}


def names() -> dict[str, str]:
    """transcript uuid → pane name, from the live fleet store of every machine (fleet.py, next to this module), and permanent id → current
    name for every session in the fleet tool's registry (retired ones too: an item still names its owner), so a stored permanent id reads like a
    stored transcript id does."""
    try:
        import fleet
        rows = fleet.sessions()
        out = _Names({k: str(v.get("name") or "") for k, v in rows.items()})
        out.by_name = fleet.by_name(rows, present_only=True)
    except Exception:
        out = _Names()
    try:
        out.update({i: n for i, n in _sr.all_names().items() if i not in out})
    except Exception:  # noqa: BLE001
        pass
    return out


def is_id(session: str) -> bool:
    """A session id rather than a name: a cloud session's cse_… id, a pane's transcript uuid or the permanent session id (also a uuid)."""
    s = str(session or "").strip()
    return s.startswith("cse_") or bool(_UUID.match(s))


def display(session: str, nm: dict[str, str] | None = None) -> str:
    """The name to show for a stored session reference: the registry's current name for the session it resolves to (a rename, an
    alias or an old transcript id all read as the name now in use), else what the fleet view calls it, else the value itself."""
    s = str(session or "").strip()
    if not s:
        return s
    n = _sr.display_name(s)
    if n:
        return n
    if nm is None and _UUID.match(s):
        nm = names()
    return str((nm or {}).get(s) or s)


def _via_fleet(u: str, nm: dict[str, str] | None) -> str | None:
    """A transcript id the registry does not list (a fresh start the registry has not recorded yet) that the fleet view knows as the present
    holder of a pane name the registry resolves: that session's permanent id. None when it is not so."""
    if not _sr.available():
        return None
    nm = names() if nm is None else nm
    bn = getattr(nm, "by_name", None)
    name = str(nm.get(u) or "")
    if not name or not bn or bn.get(name) != u:
        return None
    return _sr.resolve(name)


def canonical(session: str, nm: dict[str, str] | None = None) -> str:
    """One identity per session. Where the fleet tool's registry resolves the reference (a permanent id, a name or alias, a transcript id) it is that
    session's permanent id (step B of the permanent-id work): a rename, a fresh start or a name reused later changes no stored
    value. What the registry cannot tell (no registry, a name two sessions carry, an unknown id) falls to the rule that held before it:
    a pane name that exactly one live session carries becomes that session's transcript uuid.
    The server stores item owners as uuids while a page names its name-line session; without this a pane that is both
    that session and owner was two sessions to the hub and every notice on its project arrived twice.
    cse_ ids, uuids and names no live session carries pass through (a retired session's name included: its identity
    record names the owner of its old items, it binds nothing new)."""
    s = str(session or "").strip()
    if not s or s.startswith("cse_"):
        return s
    sid = _sr.resolve(s)
    if sid:
        return sid
    if is_id(s):
        return _via_fleet(s, nm) or s
    nm = names() if nm is None else nm
    bn = getattr(nm, "by_name", None)
    if bn is None:                                     # a plain uuid → name map (a test's): every entry counts as running
        hits = [u for u, n in nm.items() if n == s]
        return hits[0] if len(hits) == 1 else s
    return bn.get(s, s)

# ---------- anchor ids (the canonical form anchor-hub keys events by) ----------
_SLACK = re.compile(r"https?://[\w.-]+\.slack\.com/archives/([CDG][A-Z0-9]+)(?:/p\d+)?")
_DRIVE = re.compile(r"https?://(?:drive|docs)\.google\.com/(?:drive/(?:u/\d+/)?folders/|file/d/|document/d/|spreadsheets/d/|presentation/d/|open\?id=)([\w-]{20,})")
_GMAIL = re.compile(r"https?://mail\.google\.com/mail/(?:u/\d+/)?#[\w/]+/([0-9a-f]{16})$")
_GITHUB = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)")
_GHREL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/releases(?:/latest)?/?$")
_GHREPO = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+?)/?(?:#notifications)?$")   # a repo root: what the owner's account is notified of there
_NOTION = re.compile(r"https?://(?:www\.|app\.)?notion\.(?:so|com)/(?:[\w-]+/)*(?:p/)?(?:[\w%-]*?-)?([0-9a-f]{32})(?:[?#].*)?$")


def _canon_gh(a: str) -> str:
    """A github:<owner/repo>(#<n>|@releases|@notifications) id with its repo name through [github.moved] (config.canon_name), so an old and
    a new name of one repository are one anchor; any other id, and a name the table does not know, as given. Matching only: the
    stored URL of an anchor is never rewritten."""
    if not a.startswith("github:"):
        return a
    rest = a[7:]
    i = min((j for j in (rest.find("#"), rest.find("@")) if j >= 0), default=len(rest))
    return "github:" + _cfg.canon_name(rest[:i]) + rest[i:]


_GH_HOST = re.compile(r"(https?://github\.com/)([\w.-]+/[\w.-]+)", re.I)


def same_url_key(u: str) -> str:
    """A stored anchor URL as its identity check reads it: the GitHub repo in it through [github.moved] (config.canon_name), the rest as
    written. With an empty table this is the URL itself, so only an exact URL is "the same"; with a transfer listed, the old and the new
    URL of one repository are. The stored text is never changed."""
    return _GH_HOST.sub(lambda m: m.group(1) + _cfg.canon_name(m.group(2)), str(u or "").strip(), count=1)


def anchor_id(url: str) -> str | None:
    """URL (or raw id) → slack:<channel> | drive:<id> | gmail:<threadIdHex> | gmail:q:<terms> | notion:<pageId32>
    | github:<owner/repo>#<n> | github:<owner/repo>@releases | github:<owner/repo>@notifications (a repo root URL). Unknown shapes → None. A #mention=<text> fragment is
    not part of the id (see split_fragment). A GitHub repo named in [github.moved] is given by its current name, so the id is the same
    for the old and the new URL of a transferred repository (the identity of an anchor; the stored URL is never rewritten)."""
    u = url.strip()
    if u.split(":", 1)[0] in ("slack", "drive", "gmail", "notion", "github"):
        return _canon_gh(u)
    m = _GITHUB.match(u)
    if m:
        return _canon_gh(f"github:{m.group(1)}#{m.group(2)}")
    m = _GHREL.match(u)
    if m:
        return _canon_gh(f"github:{m.group(1)}@releases")
    m = _GHREPO.match(u)
    if m:
        return _canon_gh(f"github:{m.group(1)}@notifications")
    for pat, kind in ((_SLACK, "slack"), (_DRIVE, "drive"), (_GMAIL, "gmail"), (_NOTION, "notion")):
        m = pat.match(u)
        if m:
            return f"{kind}:{m.group(1)}"
    return None


def split_fragment(url: str) -> tuple[str, str]:
    """→ (url, fragment) where only a trailing `#mention=<text>` counts as a fragment. Everything else stays part of the
    URL: a Gmail thread URL carries its id after `#` (…/mail/u/0/#all/<id>), and splitting on the first `#` would
    drop every Gmail anchor."""
    u = str(url)
    i = u.rfind("#mention=")
    return (u[:i], u[i + 1:]) if i >= 0 else (u, "")


# ---------- store ----------
def load() -> dict[str, list[dict[str, Any]]]:
    try:
        d = json.load(open(FILE, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(d: dict[str, list[dict[str, Any]]]) -> None:
    _ro.guard("anchors write")
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_name(".anchors.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in sorted(d.items()) if v}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


def registry() -> dict[str, dict[str, Any]]:
    try:
        return _pr.apply(json.load(open(REGISTRY, encoding="utf-8")).get("pages", {}) or {})
    except Exception:
        return {}


def items() -> list[dict[str, Any]]:
    """Every board item with its gid (letter + id) — open and completed."""
    out = []
    for f in glob.glob(str(STORE / "?" / "*.json")):
        name = os.path.basename(f)
        if name in ("machine.json", "sessions.json"):
            continue
        try:
            t = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(t, dict) or "id" not in t:
            continue
        t["gid"] = f"{os.path.basename(os.path.dirname(f))}{t['id']}"
        out.append(t)
    return out


def mover_of(t: dict[str, Any]) -> str:
    """the session an item's notices and anchors go to, the item's mover: the first session its needs name, else its stored mover; when the owner is the mover, its `then`; when it
    names none, the project's stand-in (its builder, else its -main agent). Never the creator (metadata.owner stays a fact of the History, "created by"). "" when no session can be named.
    Reads the stored fields only (no model, no clock): the model's own default for an item with no mover is this same stand-in."""
    m = t.get("metadata") or {}

    def named(w: Any) -> str:
        w = str(w or "").strip()
        return "" if (not w or w.lower() == str(_cfg.get("instance", "owner") or "").strip().lower()) else w

    needs = m.get("needs")
    parts = needs if isinstance(needs, (list, tuple)) else re.split(r"[,\n]", str(needs or ""))
    for x in parts:
        x = str(x or "").strip()
        if x and x.lower() not in ("decision", "external"):
            return x
    for w in (m.get("mover"), m.get("then")):
        if named(w):
            return named(w)
    try:
        import router_live as _rl                  # lazy: router_live imports this module; anchor-hub, which has no router_live, falls through to the -main agent
        return _rl.stand_in(project_of(t))
    except Exception:  # noqa: BLE001
        try:
            return fallback_main(project_of(t))
        except Exception:  # noqa: BLE001
            return ""


def project_of(t: dict[str, Any]) -> str:
    v = str(_iproj.key_of(t.get("metadata") or {}) or "").strip().strip("/")      # read through the item's project id: a page that moved or was renamed keeps its items
    return v if not v or "/" in v or _pr.is_id(v) else _cfg.page_dirs()[0] + "/" + v   # a bare slug names a page in the first [pages] dir; a project's id (a project with no page) is no slug


def name_line(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    reg = registry() if reg is None else reg
    return str((reg.get(project) or {}).get("session") or "")


def hub_of(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """The hub page a key belongs to: the page named by the `hub:` line of the nearest page in
    its chain that has one (infra/hub → projects/hub: a component that keeps its own key but is part of another
    project), else its top-level page. One hop: the hub's own `hub:` line is not followed, so no chain or loop can form."""
    reg = registry() if reg is None else reg
    parts = str(project or "").strip().strip("/").split("/")
    for n in range(len(parts), 1, -1):
        h = str((reg.get("/".join(parts[:n])) or {}).get("hub") or "")
        if h:
            return h
    return "/".join(parts[:2])


def session_hubs(name: str, reg: dict[str, dict[str, Any]] | None = None, nm: dict[str, str] | None = None) -> list[str]:
    """The hubs a session belongs to: hub_of() of every page that names it as its keeper (`display-name:`, `agent:`) or lists it
    under `agents:`. A session is matched by name or by id (canonical)."""
    reg = registry() if reg is None else reg
    nm = names() if nm is None else nm
    me = canonical(name, nm)
    out = set()
    for k, e in reg.items():
        s = str(e.get("session") or "")
        if (s and (s == name or canonical(s, nm) == me)) or name in (e.get("agents") or {}):
            out.add(hub_of(k, reg))
    return sorted(out)


def off_map(session: str, project: str, reg: dict[str, dict[str, Any]] | None = None, nm: dict[str, str] | None = None, live: set[str] | None = None) -> str:
    """The session's name when it is a session the project's agents map has no line for, else "": one rule for the note a write carries (server.py) and the audit's finding (tools/page_agent_report.py).
    A session is off the map of `project` when no page of that project's hub (`session_hubs`: the page, its parent and the `hub:` page; `agents:` entries of both kinds, a `display-name:` or `agent:` line) lists it AND
    it is either listed on no page at all (a session nobody knows the project of) or named for this project (`<project>-<role>`: it belongs here, the map forgot it). A session listed on another project's map is a
    visitor and is left alone. Never off the map: the owner, a server or audit label (`stackshot…`), a cloud session, and a label that is no session the fleet knows (a script). `live` = the names sala lists now
    (None: a session the fleet tool's registry or the fleet view holds counts as one)."""
    s = str(session or "").strip()
    key = str(project or "").strip().strip("/")
    if key.endswith(".md"):
        key = key[:-3]
    key = project_of({"metadata": {"project": key}})       # a bare slug names a page in the first [pages] dir, as a write reads it
    if not s or not key or s.startswith("cse_") or s.lower().startswith("stackshot") or s.lower() == str(_cfg.get("instance", "owner") or "").strip().lower():
        return ""
    reg = registry() if reg is None else reg
    nm = names() if nm is None else nm
    name = display(s, nm)
    if live is not None:
        if name not in live and s not in live:
            return ""
    elif not (_sr.resolve(s) or s in nm or s in nm.values()):
        return ""
    hubs = sorted({h for n in dict.fromkeys([name, s, *_sr.names_of(s)]) for h in session_hubs(n, reg, nm)})       # a page may still list an old name of the session
    if hub_of(key, reg) in hubs:
        return ""
    if not hubs:
        return name
    import projects as _prj  # noqa: PLC0415
    root = "/".join(key.split("/")[:2])
    return name if _prj.named_for(name, _prj._own_names(root, reg.get(root) or {}, reg, name)) else ""


# The role roles.json carries for the session a page's `display-name:` line names. The value is a contract with readers outside this
# repo (an instance's own scripts); nothing in this repo branches on the word except through
# this constant.
NAME_ROLE = "keeper"
_ROLE_RANK = {"front": 0, "back": 1, NAME_ROLE: 2}


SALA_TIMEOUT = 4.0      # s: how long one read of `sala sessions --json` may take; a slower or failing read leaves the roles without the `live` field


def sala_rows(timeout: float = SALA_TIMEOUT) -> list[dict[str, Any]] | None:
    """The rows of `sala sessions --json` (the live sessions; its --all adds the retired ones), or None when sala cannot be read: no fleet store configured
    ([client] session_links empty: an instance with no sala fleet, and every test), no `sala` on PATH (STACKSHOT_SALA names another executable), a read over
    `timeout`, a non-zero exit or output that is not the sessions list. Never raises. The read runs in its own process group with its output in a temp file,
    so a timeout kills sala and everything it started, and a child that kept the output open cannot hold the read past `timeout`. A caller that needs the
    names, the aliases and the renames reads sala once here and derives each from the rows (live_of, renames_of)."""
    try:
        if _sr._dir() is None:
            return None
        exe = os.environ.get("STACKSHOT_SALA") or shutil.which("sala") or os.path.expanduser("~/.local/bin/sala")
        with tempfile.TemporaryFile() as out:
            p = subprocess.Popen([exe, "sessions", "--json"], stdout=out, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    p.kill()
                p.wait()
                return None
            if p.returncode != 0:
                return None
            out.seek(0)
            rows = json.loads(out.read().decode("utf-8")).get("sessions")
        return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else None
    except Exception:  # noqa: BLE001
        return None


def sessions_of(rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """(names, aliases) of the rows sala_rows gave: the sessions' names, and the names they had before a rename."""
    names: set[str] = set()
    aliases: set[str] = set()
    for x in rows:
        if x.get("name"):
            names.add(str(x["name"]))
            aliases.update(str(a) for a in (x.get("aliases") or []) if a and isinstance(a, str))
    return names, aliases


def sala_sessions(timeout: float = SALA_TIMEOUT) -> tuple[set[str], set[str]] | None:
    """The sessions sala lists now (`sala sessions --json`, which lists the live ones; its --all adds the retired rows) as (their names, their aliases), two sets (an alias is the name a live
    session had before a rename; a roles.json key is often one), or None when sala cannot be read (sala_rows has the cases). Never raises. One call reads sala once; a roles build calls it once
    and hands the set to session_roles / file_roles."""
    rows = sala_rows(timeout)
    return None if rows is None else sessions_of(rows)


def sala_live(timeout: float = SALA_TIMEOUT) -> set[str] | None:
    """The names of the sessions sala lists now and every alias of them, as one set (a roles.json key is often an alias of a live session), or None when sala cannot be read (sala_sessions has the
    cases). The caller reads sala once per build and hands the set to session_roles / file_roles."""
    got = sala_sessions(timeout)
    return None if got is None else got[0] | got[1]


def session_roles(reg: dict[str, dict[str, Any]] | None = None, live: set[str] | None = None, renames: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Every named session's role (a front agent takes a peer's message only with [for <owner>] on its first line, so the
    server and every box must know who is front) → {name: {"role": NAME_ROLE | "front" | "back", "project": <hub key>}}, plus
    `"retired": True` on the name-line session of a page that has user-facing agents, its own or its hub's (those panes are gone
    and the router rules their notices; the router rules every project), and on the name-line session of a finished page (its
    own `status` among projects.retired_statuses: nothing is left to keep). The name-line session of an active page that lists none is the
    one session of a one-session project, the session the owner talks to: it stays unretired (file_roles makes it front). The entry itself stays and keeps NAME_ROLE: an instance's guard script finds the project of a front agent it must guard
    through that entry, and other scripts read the role field; a reader that sends to a session
    checks `retired` first (the server's gates do).
    NAME_ROLE = a page's `display-name:` (the registry's `session`, not an `agent:` keeper nor an inherited one); front = an `agents:`
    entry outside `background:`; back = a `background:` entry (`back_agents`). A name held in several places keeps the more
    restricted role, front over back over the name line, and `project` is the page where that role is held; among equal roles, a
    page that is not finished (a page whose status retires it never outranks an active one), then a page with an `agents:` map, then one with no `hub:` line, then the shallower key, then a page in the first [pages] dir
    (projects/ before infra/, as pages.py places an agent's line), then the key.
    An agent only the project record holds (made through sala's New session form, its page line still owed)
    counts as its project's agent too, front or back by its flag, and its entry carries `"page_owed": True` (additive: a reader that
    wants the page's own agents checks it). A page that lists the name wins over an owed claim, whatever the roles, unless that page is a
    retired project's (its `status`): the claim is on a live project, so it outranks a listing on an archived one.
    `live` = the names and aliases `sala sessions --json` lists (sala_live; the caller reads sala once per build): every entry then carries `"live": true | false`, whether
    sala lists that name as a session, or as an alias of one. None (not given, or sala could not be read) adds no field, never a false for everyone.
    `renames` = {old name: the name the session has now} (renamed_agents.renames_of): an entry whose name is such an old name also carries `"renamed_to": <new name>`, so a
    reader that draws agents (the Projects page) can leave it out although `live` is true for it (an alias reads live). Additive: omitted when not given or empty."""
    import projects as _prj
    ren = {str(k).casefold(): v for k, v in (renames or {}).items()}      # old names compare case-folded
    reg = _prj.with_pending(registry() if reg is None else reg, made=True)
    first = _cfg.page_dirs()[0] + "/"
    best: dict[str, tuple[tuple, str, str]] = {}
    claims: dict[str, tuple[tuple, str, str]] = {}      # the owed claims, ranked among themselves the same way
    dead = lambda k: _prj.page_status(reg.get(k) or {}) in _prj.retired_statuses()
    def offer(name: str, role: str, key: str, e: dict[str, Any], owed: bool = False) -> None:
        rank = (_ROLE_RANK[role], dead(key), not e.get("agents"), bool(e.get("hub")), key.count("/"), not key.startswith(first), key)
        into = claims if owed else best
        if name and (name not in into or rank < into[name][0]):
            into[name] = (rank, role, key)
    for key, e in reg.items():
        back = {str(x) for x in (e.get("back_agents") or {})}
        owed = {str(x) for x in (e.get("owed_agents") or {})}
        for n in [str(x) for x in (e.get("agents") or {})] + sorted(back):
            offer(n, "back" if n in back else "front", key, e, n in owed)
        s = str(e.get("session") or "")
        if s and e.get("role") not in ("agent", "inherited"):
            offer(s, NAME_ROLE, key, e)
    owed_won = {n for n, c in claims.items() if n not in best or dead(best[n][2])}
    best.update({n: claims[n] for n in owed_won})
    served = lambda k: any(front_agents(reg.get(x) or {}) for x in dict.fromkeys(["/".join(k.split("/")[:2]), hub_of(k, reg)]) if x)
    return {n: ({"role": r, "project": k, "retired": True} if r == NAME_ROLE and (served(k) or dead(k)) else {"role": r, "project": k})
               | ({"page_owed": True} if n in owed_won else {})
               | ({"live": n in live} if live is not None else {})
               | ({"renamed_to": ren[n.casefold()]} if n.casefold() in ren else {})
            for n, (_rank, r, k) in sorted(best.items())}


def file_roles(reg: dict[str, dict[str, Any]] | None = None, live: set[str] | None = None, renames: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """The roles as roles.json carries them: session_roles(), except that a pane-named name-line session of an active page, and of no
    page with user-facing agents (an `agents:` entry outside `background:`), is "front", on the same project. The only session of a one-session project is a session he talks to directly, so it is a front session; it
    stays front until its project gets a page that lists user-facing agents. A cloud session (a cse_ id)
    and a name-line session of inactive pages only (pages._active) keep NAME_ROLE. Only the
    file reads this: who a notice goes to, the needs and message gates and the board keep session_roles(), where such a
    session is still its page's name-line session. A session of a project the router is live for keeps NAME_ROLE here and gains
    `"retired": true` (session_roles): the file is read by an instance's own scripts, which rely on
    the role field, and nothing may send to a retired session. `live` and `renames`: as in session_roles (sala_live's set; the fields are additive)."""
    import pages as _pages                          # its _active is the board's own test of a page still in play
    import projects as _prj
    reg = _prj.with_pending(registry() if reg is None else reg, made=True)   # an owed agent is a user-facing agent of its page too (session_roles)
    real, active = set(), set()                      # name-line sessions with user-facing agents on their page; name-line sessions of an active page
    for e in reg.values():
        s = str(e.get("session") or "")
        if not s or e.get("role") in ("agent", "inherited"):
            continue
        if set(e.get("agents") or {}) - set(e.get("back_agents") or {}):
            real.add(s)
        if _pages._active(e):
            active.add(s)
    sole = lambda n, r: r["role"] == NAME_ROLE and not r.get("retired") and n not in real and n in active and not is_id(n)   # a retired entry keeps its role
    return {n: ({**r, "role": "front"} if sole(n, r) else r) for n, r in session_roles(reg, live, renames).items()}


# ---------- the pilot ----------
KINDS = {"slack": "Slack", "notion": "Notion", "gmail": "Gmail", "drive": "Drive", "github": "GitHub"}   # an anchor id's prefix → its type, as shown


def kind_of(anchor: str) -> str:
    """The type of an anchor, from its id ("slack:C…" → "Slack"). The title is the receiver's; the two meet only where a
    notice names the anchor ("Slack #team-news") — never by cutting one out of the other."""
    return KINDS.get(str(anchor or "").split(":", 1)[0], "Link")


_PILOT: dict = {"sig": None, "roots": []}


def pilot_roots() -> list[str]:
    """The top-level page keys the router rules: every page of the registry (the
    [pilot] projects list is gone, a key left in a config is ignored), a sub-page counting for its top-level page. Read from the registry
    file whenever it changed."""
    try:
        st = os.stat(REGISTRY)
        sig: Any = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        sig = None
    if sig is None or sig != _PILOT["sig"]:
        dirs = set(_cfg.page_dirs())
        tops = {"/".join(k.split("/")[:2]) for k in registry() if k.count("/") >= 1 and k.split("/")[0] in dirs}
        _PILOT.update(sig=sig, roots=sorted(tops))
    return list(_PILOT["roots"])


def pilot_root(project: str, roots: list[str] | None = None) -> str:
    """The top-level page this key is, or sits under ("projects/parent/sub" → "projects/parent"); "" for a key that names no page
    of the registry. Every page is the router's now, so this is a page's top-level key (it was a [pilot] projects match)."""
    parts = str(project or "").strip().strip("/").split("/")
    if len(parts) < 2:
        return ""
    top = "/".join(parts[:2])
    return top if top in (pilot_roots() if roots is None else roots) else ""


def notice_name(project: str, reg: dict[str, dict[str, Any]] | None = None, roots: list[str] | None = None) -> str:
    """The name a project's notices are addressed to: its top-level page's `display-name:` line (the registry's `session`), else, for a page that names none, the session its notices fall to (fallback_main). The line stays on every page
    and names the project; the router rules what is addressed to it (router_live.holds), so no one is sent
    to it. "" for a key that names no page, or when no session can be named."""
    r = pilot_root(project, roots)
    return (name_line(r, reg) or fallback_main(r, reg)) if r else ""


# ---------- the keeper of a page with no agents of its own ----------
# A page that lists no user-facing agent has its notices go to: (1) its hub page's -main agent (the `hub:` line), else (2) the general -main
# agent of its scope (derive_scope): [router] general_<scope> for each scope of [project_scopes] (an instance names its own, e.g. general_team = "team-hub-main",
# general_infra = "projects/alpha"; the default scope's agent when the scope's page or agent does not exist). A value with
# a "/" names a page (its -main agent), any other value is an agent's name (found on the page that lists it as a user-facing agent).
# No scope has one by default: an instance that names none has no stand-in, and a notice for such a page is held.
GENERAL_DEFAULTS: dict[str, str] = {}


def front_agents(e: dict[str, Any]) -> list[str]:
    """The user-facing agents a registry entry lists: its `agents:` map minus the `background:` ones."""
    back = {str(k) for k in (e.get("back_agents") or {})}
    return [str(k) for k in (e.get("agents") or {}) if str(k) not in back]


def main_of(e: dict[str, Any]) -> str:
    """The -main agent of a registry entry: the user-facing agent whose name ends in -main, else the first one, else ""."""
    front = front_agents(e)
    return next((n for n in front if n.endswith("-main")), front[0] if front else "")


def _general_value(scope: str) -> str:
    v = str(_cfg.get("router", f"general_{scope}") or "").strip()
    return v or GENERAL_DEFAULTS.get(scope, "")


def _general_resolve(value: str, reg: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """A general_<scope> value → (the agent, the page that lists it); ("", "") when no page lists such an agent. A page key whose page lists no
    front agent but has a `display-name:` line is a one-session page (has_front, session_roles): its agent is that name-line session, the
    same session the rest of this module treats as the one session of such a page."""
    if not value:
        return "", ""
    if "/" in value:
        value = value.strip("/")
        e = reg.get(value) or {}
        one = name_line(value, reg) if e.get("role") not in ("agent", "inherited") else ""
        main = main_of(e) or ("" if is_id(one) else one)
        return (main, value) if main else ("", "")
    hits = sorted((bool(e.get("hub")), k.count("/"), k) for k, e in reg.items() if value in front_agents(e))
    return (value, hits[0][2]) if hits else ("", "")


def general_main(project: str, reg: dict[str, dict[str, Any]] | None = None) -> tuple[str, str]:
    """The general -main agent a page with no agent of its own falls to, and the page that lists it → (agent, page), ("", "") when the scope
    has none. The scope is the one the project picker shows (projects.derive_scope: the key's prefix, the page's org and tags, the names of
    its agents); a scope with no general agent falls back to the default scope's."""
    import projects as _prj
    reg = registry() if reg is None else reg
    root = pilot_root(project) or "/".join(str(project or "").strip("/").split("/")[:2])
    scope = _prj.derive_scope(root, reg.get(root) or {}, reg)
    for sc in dict.fromkeys([scope, _prj.default_scope()]):
        got = _general_resolve(_general_value(sc), reg)
        if got[0]:
            return got
    return "", ""


def has_front(project: str, reg: dict[str, dict[str, Any]] | None = None) -> bool:
    """Does the project's page, or its hub, list a user-facing agent? False for a one-session page (a name line and no agents map) and for a
    page with background agents only: its keeper stays its name-line session, and only the router's passes use the general -main agent."""
    reg = registry() if reg is None else reg
    root = pilot_root(project) or "/".join(str(project or "").strip("/").split("/")[:2])
    return any(main_of(reg.get(k) or {}) for k in dict.fromkeys([root, hub_of(root, reg)]))


def fallback_main(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """The -main agent a project's notices fall to when its page names no session: its own page's, its hub's, else the scope's general one
    (general_main). "" when none can be named."""
    reg = registry() if reg is None else reg
    root = pilot_root(project) or "/".join(str(project or "").strip("/").split("/")[:2])
    for k in dict.fromkeys([root, hub_of(root, reg)]):
        m = main_of(reg.get(k) or {})
        if m:
            return m
    return general_main(root, reg)[0]


# ---------- derived sessions + bindings ----------
def counts_for(entry: dict[str, Any], project: str, t: dict[str, Any]) -> bool:
    """Does the anchor `entry` of page `project` count for item `t` when the receivers are chosen: an anchor scoped to items counts for every one of them, an item
    of any project (an anchor held by one page can be about items of several: a Slack DM has receivers in more than one project); a project-wide anchor counts for
    the open items of its own page's project. The same rule as anchor_scope.py, which reads it for one item from every page; this module cannot import that one."""
    scope = entry.get("items")
    return t["gid"] in scope if scope else project_of(t) == project


def sessions_for(project: str, entry: dict[str, Any], all_items: list[dict[str, Any]], reg: dict[str, dict[str, Any]], nm: dict[str, str] | None = None) -> set[str]:
    """The name-line session plus the movers of the open items the anchor counts for (counts_for: the items in its scope, of any project; all of the page's project's
    open items when it is project-wide), each pane under one identity (canonical)."""
    nm = names() if nm is None else nm
    s = {canonical(x, nm) for x in [name_line(project, reg)] if x}
    for t in all_items:
        if t.get("status") == "completed" or not counts_for(entry, project, t):
            continue
        o = mover_of(t)
        if o:
            s.add(canonical(o, nm))
    return s


def routes(store: dict | None = None, all_items: list | None = None, reg: dict | None = None) -> dict[str, list[dict[str, Any]]]:
    """anchor id → [{project, session, target, pilot, filter}]: who gets a notice on that anchor, and for which project (the page that holds it).
    Outside the pilot: the page's name-line session plus the movers of the open items in scope, of any project (target ""). In the pilot: the
    name-line session alone, and `target` says whom the notice is for — "for <agent>, …" when the anchor is scoped to items of the page's own project (their
    movers), else "project-wide" (every notice goes to that session with its target noted); the movers of scoped items of other projects are not named there."""
    store = load() if store is None else store
    all_items = items() if all_items is None else all_items
    reg = registry() if reg is None else reg
    nm = names(); roots = pilot_roots()
    out: dict[str, list[dict[str, Any]]] = {}
    for project, entries in store.items():
        stew = notice_name(project, reg, roots)
        for e in entries:
            base, frag = split_fragment(e.get("url", ""))
            a = anchor_id(base)
            if not a:
                continue
            flt = frag[8:].strip() if frag.startswith("mention=") else ""
            if stew:
                # `target` names the movers of the scoped items of the holding page's own project only (the router's anchor-item rule reads it and looks the mover up in this page's roster: an item
                # of another project has its mover in another roster, and a notice would reach that project's front agent unmarked); the keeper of the page gets the notice either way
                owners = sorted({nm.get(o, o) for o in (canonical(mover_of(t), nm) for t in all_items
                                 if t.get("status") != "completed" and e.get("items") and counts_for(e, project, t) and project_of(t) == project) if o})
                sess, target = {canonical(stew, nm)}, ("for " + ", ".join(owners)) if owners else "project-wide"
            else:
                sess, target = sessions_for(project, e, all_items, reg, nm), ""
            for s in sorted(sess):
                r = {"project": project, "session": s, "target": target, "pilot": bool(stew), "filter": flt}
                if r not in out.setdefault(a, []):           # two entries of one anchor (an old and a new name of a transferred repo, [github.moved]) route once
                    out[a].append(r)
    return out


def bindings(store: dict | None = None, all_items: list | None = None, reg: dict | None = None) -> tuple[dict[str, set[str]], dict[tuple[str, str], str]]:
    """→ ({anchor id: sessions}, {(anchor id, session): mention filter}) — what anchor-hub delivers on (derived from routes())."""
    b: dict[str, set[str]] = {}
    filters: dict[tuple[str, str], str] = {}
    for a, rs in routes(store, all_items, reg).items():
        for r in rs:
            b.setdefault(a, set()).add(r["session"])
            if r["filter"]:
                filters[(a, r["session"])] = r["filter"]
    return b, filters


# ---------- edits (the server's tool) ----------
def add(store: dict, project: str, urls: list[str], scope: list[str] | None, by: str) -> list[dict[str, Any]]:
    """Add URLs (or widen an existing anchor's scope: adding a URL already present with new items unions the items;
    adding it project-wide makes it project-wide). Returns the project's list."""
    lst = store.setdefault(project, [])
    now = time.time()
    for u in urls:
        u = u.strip()
        cur = next((e for e in lst if e.get("url") == u), None) or next((e for e in lst if same_url_key(e.get("url", "")) == same_url_key(u)), None)   # [github.moved]: the old-name entry of the same PR is the one
        if cur is None:
            lst.append({"url": u, "items": sorted(set(scope)) if scope else None, "added": now, "by": by})
        elif scope and cur.get("items") is not None:
            cur["items"] = sorted(set(cur["items"]) | set(scope))
        elif not scope:
            cur["items"] = None
    return lst


def remove(store: dict, project: str, urls: list[str]) -> list[dict[str, Any]]:
    gone = {same_url_key(u) for u in urls}
    lst = [e for e in store.get(project, []) if e.get("url") not in {u.strip() for u in urls} and same_url_key(e.get("url", "")) not in gone]
    if lst:
        store[project] = lst
    else:
        store.pop(project, None)
    return lst


def fmt(entries: list[dict[str, Any]], status: dict[str, dict[str, Any]] | None = None) -> str:
    """A project's anchors, one per line. With anchor-hub's per-anchor status (status.json "anchors") each line also says
    what the hub made of it: its name there, or that the hub cannot read it and why."""
    def hub(e: dict[str, Any]) -> str:
        st = (status or {}).get(anchor_id(split_fragment(e.get("url", ""))[0]) or "") or {}
        u = st.get("unreadable")
        if u:
            return f" — UNREADABLE by anchor-hub since {u.get('since')} {_cfg.tz_abbr()}: {u.get('why')}" + ("" if u.get("warned") else " (being asked once more before the keeper is warned)")
        return f" — {st['label']}" if st.get("title") else ""
    return "\n".join(f"- {e.get('url')}  [{'project-wide' if not e.get('items') else 'items: ' + ', '.join(e['items'])}]{hub(e)}" for e in entries) or "(none)"


# ---------- one-time migration from item anchors ----------
def migrate() -> str:
    """Move every open item's metadata.anchors to its project, scoped to that item; strip the field from all items."""
    store = load()
    moved = stripped = 0
    for f in glob.glob(str(STORE / "?" / "*.json")):
        if os.path.basename(f) in ("machine.json", "sessions.json"):
            continue
        try:
            t = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        md = t.get("metadata") or {}
        if "anchors" not in md:
            continue
        gid = f"{os.path.basename(os.path.dirname(f))}{t['id']}"
        project = project_of(t)
        if t.get("status") != "completed" and project:
            for u in md.get("anchors") or []:
                add(store, project, [str(u)], [gid], by="migration")
                moved += 1
        md.pop("anchors", None)
        t["metadata"] = md
        st = os.stat(f)
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as out:
            json.dump(t, out, ensure_ascii=False, indent=1)
        os.replace(tmp, f)
        os.utime(f, (st.st_atime, st.st_mtime))   # a migration is not a change of the item
        stripped += 1
    save(store)
    return f"moved {moved} anchors from {stripped} items into {FILE}"


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bindings"
    if cmd == "migrate":
        print(migrate())
    elif cmd == "list":
        for p, es in load().items():
            print(p); print(fmt(es))
    else:
        b, fl = bindings()
        for a, s in sorted(b.items()):
            print(f"{a:24} → {', '.join(sorted(s))}")


def roles_live(path: str | os.PathLike[str] | None = None) -> dict[str, bool]:
    """The `live` flag of every session in roles.json (the file the server keeps from sala_live) as {name: bool}; a name whose entry carries no flag is left
    out, and so is every name when the file is missing, unreadable or was written while sala could not be read (no entry has the field). A reader that hides
    what is not live asks `flags.get(name, True)`: an unknown is shown, never hidden. Never raises."""
    try:
        d = json.load(open(path if path is not None else _cfg.state("roles.json"), encoding="utf-8"))
        return {str(n): r["live"] for n, r in (d.get("sessions") or {}).items() if isinstance(r, dict) and isinstance(r.get("live"), bool)}
    except Exception:  # noqa: BLE001
        return {}


def roles_renamed(path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """The `renamed_to` of every session in roles.json as {old name: new name}: a name sala keeps only as an alias of a renamed session. A reader that draws agents leaves such
    a name out (it reads live, being an alias, but it names nobody now). {} when the file is missing, unreadable or carries none. Never raises."""
    try:
        d = json.load(open(path if path is not None else _cfg.state("roles.json"), encoding="utf-8"))
        return {str(n): r["renamed_to"] for n, r in (d.get("sessions") or {}).items() if isinstance(r, dict) and isinstance(r.get("renamed_to"), str) and r["renamed_to"]}
    except Exception:  # noqa: BLE001
        return {}


def role_ids(sessions: dict[str, Any]) -> dict[str, str]:
    """roles.json's `ids` (step B): the permanent id of each named session in `sessions` (the file's name-keyed map) that the fleet tool's registry
    resolves to one session. Names stay the keys, since hooks on every box read the file by name; a reader that wants the permanent
    id takes it from here. {} while there is no registry or nothing resolves."""
    out = {}
    for n in sorted(sessions):
        sid = _sr.resolve(n)
        if sid:
            out[n] = sid
    return out
