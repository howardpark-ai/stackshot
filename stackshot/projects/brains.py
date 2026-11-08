"""brains.py — which notes brain holds a project page, and how stackshot reads and writes it.

Every project page used to live in one brain: the server read it from the local git copy at `[paths] brain` and wrote it
through the gbrain CLI. An instance may now name more brains in `[[brains]]` (stackshot.example.toml). Each one is reached the
same two ways as the first: a local git copy of its own (read only for stackshot: another process keeps it in sync) and the
gbrain CLI run with that brain's home folder (environment GBRAIN_HOME=<home>, which carries the CLI's own sign-in).

    for_key("projects/acme-x")   → the Brain that holds the page (the default brain when no [[brains]] entry names it)
    file("projects/acme-x")      → <that brain's copy>/projects/acme-x.md
    problem(brain)               → "" when its copy can be read; else why not (missing, not a usable git copy, or not synced for stale_hours)
    cli_refusal(slug)            → "" when a gbrain CLI call (read or write) for the slug may run; else why not (a second brain with no `home`)
    prepare(slug, env, brain)    → (the child environment, the refusal or ""): one secret_file read decides both; the parent's client secret never passes
    gbrain_env(slug, env)        → env with GBRAIN_HOME (and, for a brain with a `secret_file`, GBRAIN_REMOTE_CLIENT_SECRET) set for the slug's brain
                                   (a copy: the server's own environment is never touched; unchanged for the default brain without a home)
    redact(text, env)            → text with the secret of that environment replaced, for any output a CLI call hands back
    mirror(key)                  → the page's mirror link from its brain's template ("" when none)
    shared_refusal(key)          → "" when stackshot may write the page; else why not (its brain is marked `shared`: see below)
    looked_in(key)               → for a page reported missing: "" for the default brain, else which second brain's copy was looked in and what routed it there
    warn_once(brain, why, what)  → one stderr line per outage, naming the brain (fail open: the caller carries on); the state is per brain
    clear(brain, what)           → a read works again; when no read of the brain fails any more, one stderr line says it is back

With no `[[brains]]` every slug resolves to the default brain, whose copy is `[paths] brain`, whose home is `[gbrain] home` (unset:
the CLI's own default, so its environment is not touched) and whose mirror is `[gbrain] mirror_url`: exactly the behavior from
before. The default brain never fails open here: its checks stay as they were. A second brain whose copy is missing or stale, or
whose CLI call fails, never blocks the board: the readers skip its pages for the run and say so. The state is per brain, in the memory of each
process: the first failed read of an outage prints one warning (warn_once), every further failure of that brain stays silent, and when the last
failing read works again (clear) one line says the brain is back. A long-lived process such as the server says it once per outage; the page hook
starts a new process for every prompt, so it says so at each prompt while the outage lasts.
A copy that exists but is not a usable copy (no `.git`, or no page in any page folder: an unmounted mount point, a clone in progress) is
as good as missing. A second brain with no `home` is not reached through the CLI at all: a read or a write for its slugs is refused (the CLI would run on the
default brain's home and return or take that brain's page), see cli_refusal; a refused read is a page that could not be read.

A brain marked `shared = true` (a `[[brains]]` entry's own key; `[gbrain] shared = true` for the default brain) holds pages of people other than the board's owner:
stackshot writes nothing of its board onto them. Every write the page store makes for such a page (a Current-state edit, a timeline line, a new page, the
project lines' copy of the record) is refused with a line that names the mark (shared_refusal), and a page of it owes no page update to a session. Reads are not touched.

A remote brain's CLI also needs its OAuth client secret (GBRAIN_REMOTE_CLIENT_SECRET). The entry's optional `secret_file` is a path (~ allowed)
to a file holding it: a JSON file with a `client_secret` key, or a plain file whose first line is the secret. The server reads it at each
CLI call for that brain and sets the variable in the child's environment only: never in its own, never in a log, a note, an error message
or the client config (the path may be named, the value and the file's content never). A file readable by group or others (mode & 0o077)
is refused, by config.notes at load and again at the call; a file that cannot be read, is empty, has no `client_secret` or holds an unusable one
(shorter than 16 characters, or with a control character) refuses the CLI call for that brain (cli_refusal: a note naming the path and the reason,
once per outage), which fails open as any other outage. The child's environment never inherits the variable from the server's: prepare() removes it
first and sets it only from the brain's own file, in the one read that also decides the refusal.

A slug belongs to a [[brains]] entry when it is one of its `slugs` (a page key, or a bare slug read in the first [pages] dir) or a
page under one of them, or when it starts with one of its `prefixes` (plain string prefixes of the page key, e.g. "projects/beta-").
The first entry that matches wins. Read at each use (config.get), so a reload applies it.

A page that exists in no brain yet starts in the default brain unless a [[brains]] entry says otherwise, with two optional keys:
`new_prefixes` (plain string prefixes of the page key, e.g. "projects/beta-"; end each in "-" or "/") and `keep` (fragments: a page key that
contains one of them stays in the default brain; `keep` wins over `new_prefixes`). A page key that starts with a `new_prefixes` entry, matches
no `slugs` or `prefixes` entry, contains none of that entry's `keep` fragments and exists in no brain's local copy (neither the page nor a page
it is a sub-page of) is routed to that entry's brain: the page is created there, and every later read and write on the server box finds it there (a client box gets no `new_prefixes`). A page that
exists elsewhere is routed exactly as before (a page of the default brain stays in it; a page seen in the entry's own copy is found there).
The first entry whose `new_prefixes` match wins. `new_prefixes` never moves a page, it only decides where an absent one starts. The default brain's copy must be usable (there, a git copy holding pages), or every page stays with the default brain.
Stdlib only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

DEFAULT = "default"
SECRET_ENV = "GBRAIN_REMOTE_CLIENT_SECRET"      # the variable the gbrain CLI reads a remote brain's OAuth client secret from
SECRET_MIN = 16             # a client secret shorter than this is not used: redact() of a very short value would corrupt page text
STALE_HOURS = 24.0          # a second brain's copy not synced for this long is stale ([[brains]] stale_hours; 0 = never stale)


@dataclass(frozen=True)
class Brain:
    name: str
    path: Path
    home: str = ""                       # GBRAIN_HOME for its writes (default brain: "" = the CLI's own home; a second brain with none is not reached through the CLI, see cli_refusal)
    mirror_url: str = ""                 # a link template with {key}
    slugs: tuple[str, ...] = field(default_factory=tuple)
    prefixes: tuple[str, ...] = field(default_factory=tuple)
    new_prefixes: tuple[str, ...] = field(default_factory=tuple)   # a page key with one of these prefixes that exists in no brain yet is created in THIS brain
    keep: tuple[str, ...] = field(default_factory=tuple)           # a page key containing one of these stays in the default brain, whatever new_prefixes says
    stale_hours: float = 0.0
    default: bool = False
    shared: bool = False                 # holds pages other people read and write: stackshot writes nothing of its board onto them (see shared_refusal)
    secret_file: str = field(default="", repr=False)    # path of the file holding the CLI's OAuth client secret (never its content; see secret())


def _norm(v: Any) -> str:
    v = str(v or "").strip().strip("/")
    if v.endswith(".md"):
        v = v[:-3]
    if v and "/" not in v:
        v = _cfg.page_dirs()[0] + "/" + v
    return v


def _exp(v: Any) -> str:
    v = str(v or "").strip()
    return os.path.expanduser(v) if v else ""


def _flag(v: Any) -> bool:
    """A config boolean: only a real true counts (a string such as "false" is no mark; config.notes names it)."""
    return v is True


def default() -> Brain:
    return Brain(name=DEFAULT, path=Path(_exp(_cfg.get("paths", "brain")) or os.path.expanduser("~/brain")),
                 home=_exp(_cfg.get("gbrain", "home")), mirror_url=str(_cfg.get("gbrain", "mirror_url") or ""), default=True,
                 shared=_flag(_cfg.get("gbrain", "shared")))


def _strs(v: Any, strip_slash: bool = False) -> tuple[str, ...]:
    """A config list of strings (or one string) as a tuple of non-empty stripped strings (`strip_slash`: without a leading "/", as a page key
    has none); anything else in it is ignored (config.notes names it)."""
    v = [v] if isinstance(v, str) else v
    if not isinstance(v, (list, tuple)):
        return ()
    out = [x.strip().lstrip("/") if strip_slash else x.strip() for x in v if isinstance(x, str)]
    return tuple(x for x in out if x)


def extra() -> list[Brain]:
    """The [[brains]] entries, in order; an entry without a name or a path is skipped (config.notes names it)."""
    out: list[Brain] = []
    raw = _cfg.get("brains")
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict):
            continue
        name, path = str(b.get("name") or "").strip(), _exp(b.get("path"))
        if not name or not path or name == DEFAULT:
            continue
        slugs = b.get("slugs") or []
        prefixes = b.get("prefixes") or []
        slugs = [slugs] if isinstance(slugs, str) else slugs
        prefixes = [prefixes] if isinstance(prefixes, str) else prefixes
        try:
            stale = float(b.get("stale_hours", STALE_HOURS))
        except (TypeError, ValueError):
            stale = STALE_HOURS
        out.append(Brain(name=name, path=Path(path), home=_exp(b.get("home")), mirror_url=str(b.get("mirror_url") or ""),
                         secret_file=_exp(b.get("secret_file")) if isinstance(b.get("secret_file"), str) else "",
                         slugs=tuple(s for s in (_norm(x) for x in slugs if isinstance(x, str)) if s),
                         prefixes=tuple(str(p).strip().lstrip("/") for p in prefixes if isinstance(p, str) and str(p).strip()),
                         new_prefixes=_strs(b.get("new_prefixes"), strip_slash=True), keep=_strs(b.get("keep")),
                         stale_hours=max(stale, 0.0), shared=_flag(b.get("shared"))))
    return out


def all_brains() -> list[Brain]:
    """The default brain first, then the [[brains]] entries."""
    return [default(), *extra()]


def client_entries() -> list[dict[str, Any]]:
    """What a client box needs of each second brain, and nothing secret: its name, its mirror link template and its page rules (slugs and
    prefixes), so the client's page links and its warnings name the right brain. `new_prefixes` and `keep` are not sent on purpose: a client has
    no local copy to tell an existing page from a new one, so applying them there would route every existing default-brain page that matches
    a prefix to the second brain. A client box links a page the server created by `new_prefixes` to the default mirror unless its slug is in `slugs`. The copy's path is the server box's own (a client has no
    such copy, so it reads nothing there, as with paths.brain) and the gbrain home and the secret file stay on the server: a client writes no page."""
    return [{"name": b.name, "path": str(b.path), "mirror_url": b.mirror_url, "slugs": list(b.slugs), "prefixes": list(b.prefixes)} for b in extra()]


def configured() -> bool:
    """True when the instance names a second brain at all."""
    return bool(extra())


def _owns(b: Brain, key: str) -> bool:
    return any(key == s or key.startswith(s + "/") for s in b.slugs) or any(key.startswith(p) for p in b.prefixes)


def _page_exists(key: str) -> list[Brain]:
    """The brains whose local copy holds the page, or a page it is a sub-page of (`projects/a/b` is held by a copy with `projects/a/b.md`, a
    folder `projects/a/b/` (the full key only: a folder above it is no page) or `projects/a.md`): a plain stat of the copy, no git and no CLI.
    A copy that is missing holds nothing."""
    found: list[Brain] = []
    parts = key.split("/")
    parents = ["/".join(parts[:i]) for i in range(len(parts) - 1, 1, -1)]      # the pages above it, below the page folder
    for b in all_brains():
        try:
            if (b.path / (key + ".md")).exists() or (b.path / key).is_dir() or any((b.path / (k + ".md")).exists() for k in parents):
                found.append(b)
        except OSError:
            pass
    return found


def _copy_usable(b: Brain) -> bool:
    """True when the brain's local copy is a copy that can say whether a page exists: the folder is there, it is a git copy and it holds a page
    (the test unusable() applies to a second brain, applied here to the default brain, which unusable() never judges)."""
    return b.path.is_dir() and (b.path / ".git").exists() and _has_pages(b.path)


def _new_page_brain(k: str) -> Brain | None:
    """The brain a page that no `slugs` or `prefixes` entry names starts in, by `new_prefixes` and `keep`: None (the default brain) unless
    the key starts with an entry's `new_prefixes`, contains none of that entry's `keep` fragments and exists in no other brain's copy. The
    stat runs only for a key that matches a `new_prefixes` entry. When the default brain's copy cannot be trusted (missing, no `.git`, no
    page in it) "exists in no copy" proves nothing, so the page stays with the default brain: never a new page in a second brain on a doubt."""
    for b in extra():
        if not any(k.startswith(p) for p in b.new_prefixes):
            continue
        if any(f in k for f in b.keep):
            return None                     # keep wins over new_prefixes
        if not _copy_usable(default()):
            return None                     # the default copy cannot say the page exists: fail to the default brain
        held = _page_exists(k)
        if held and not any(h.name == b.name for h in held):
            return None                     # the page exists in other brains' copies only: it stays where it was (routed as before)
        return b
    return None


def for_key(key: Any) -> Brain:
    """The brain that holds this page (a page key or a bare slug): the first [[brains]] entry whose `slugs` or `prefixes` name it; else, for a
    page that exists in no brain yet, the entry whose `new_prefixes` start it (see the module text); else the default brain."""
    k = _norm(key)
    if k:
        for b in extra():
            if _owns(b, k):
                return b
        return _new_page_brain(k) or default()
    return default()


def by_name(name: str) -> Brain | None:
    return next((b for b in all_brains() if b.name == name), None)


def file(key: Any) -> str:
    """The page's file in its brain's local copy."""
    return str(for_key(key).path / (_norm(key) + ".md"))


def shared_refusal(key: Any) -> str:
    """"" when stackshot may write the page `key`; else the line that says why not, naming the mark: the page's brain is marked shared. Never raises
    (a config that cannot be read answers "": a write is then not refused here, and the page store's own checks stand)."""
    try:
        b = for_key(key)
    except Exception:  # noqa: BLE001
        # Fails open on purpose: a config fault must not block every write of the board, and the config loader already refuses a malformed mark at load
        # (`shared` counts only as a real boolean true; config.notes names any other value), so what reaches here is a fault of the brain list itself.
        return ""
    if not b.shared:
        return ""
    mark = "[gbrain] shared = true" if b.default else f"[[brains]] {b.name} shared = true"
    return (f"brain {b.name!r} is marked shared ({mark}): stackshot writes nothing of its board onto a shared brain's pages "
            f"(no Current-state edit, timeline line, new page or project-lines copy); the page is kept by its own people")


def mirror(key: Any) -> str:
    """The page's mirror link from its brain's template; "" when that brain has none."""
    b = for_key(key)
    return b.mirror_url.format(key=_norm(key)) if b.mirror_url else ""


def _git_dirs(path: Path) -> list[Path]:
    """The git directories whose stamps say when the copy was synced: `.git` itself, and for a linked worktree (`.git` is a file reading
    `gitdir: <dir>`) that directory and the common one it names in `commondir`, where FETCH_HEAD lives."""
    g = path / ".git"
    if g.is_dir():
        return [g]
    out: list[Path] = []
    try:
        if g.is_file():
            d = Path(g.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip().splitlines()[0].strip())
            d = d if d.is_absolute() else (path / d)
            out.append(d)
            c = d / "commondir"
            if c.is_file():
                cd = Path(c.read_text(encoding="utf-8").strip())
                out.append(cd if cd.is_absolute() else (d / cd))
    except (OSError, IndexError, ValueError):
        pass
    return out


def _synced_at(path: Path) -> float | None:
    """When the copy was last brought up to date: the newest of git's fetch and HEAD stamps and the last commit's time (a plain clone or a
    linked worktree)."""
    best: float | None = None
    for g in _git_dirs(path):
        for f in (g / "FETCH_HEAD", g / "HEAD", g / "ORIG_HEAD"):
            try:
                best = max(best or 0.0, f.stat().st_mtime)
            except OSError:
                pass
    try:
        out = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%ct"], capture_output=True, text=True, timeout=10).stdout.strip()
        if out:
            best = max(best or 0.0, float(out))
    except Exception:  # noqa: BLE001
        pass
    return best


def _has_pages(path: Path) -> bool:
    """True when any page folder of the copy holds a markdown file (a mount point with nothing mounted, or a clone still being checked out, does not)."""
    for sub in _cfg.page_dirs():
        try:
            if next((path / sub).rglob("*.md"), None) is not None:
                return True
        except OSError:
            pass
    return False


def unusable(b: Brain) -> str:
    """"" when the second brain's copy is a copy that can be read; else why not: the folder is missing, it is no git copy (no `.git`: an
    unmounted mount point, a folder nobody cloned into) or it holds no page yet (a clone in progress). The default brain is never judged here."""
    if b.default:
        return ""
    if not b.path.is_dir():
        return f"its local copy {b.path} is missing"
    if not (b.path / ".git").exists():
        return f"its local copy {b.path} is not a git copy (no .git: not mounted, or not cloned yet)"
    if not _has_pages(b.path):
        return f"its local copy {b.path} holds no pages (not mounted, or a clone still in progress)"
    return ""


def stale(b: Brain, now: float | None = None) -> str:
    """"" when the copy was synced within stale_hours (or the brain never goes stale); else how long ago. A usable copy is assumed."""
    if b.default or b.stale_hours <= 0:
        return ""
    t = _synced_at(b.path)
    now = time.time() if now is None else now
    if t is not None and now - t > b.stale_hours * 3600:
        return f"its local copy {b.path} has not been synced for {int((now - t) // 3600)} h (stale_hours {b.stale_hours:g})"
    return ""


def problem(b: Brain, now: float | None = None) -> str:
    """"" when the brain's copy can be read; else why not, in a few words (unusable, or stale). The default brain is never judged here (its
    readers keep their own checks, as before); only a second brain fails open."""
    return unusable(b) or stale(b, now)


def key_problem(key: Any) -> tuple[Brain, str]:
    """(the page's brain, why its copy cannot be read or "")."""
    b = for_key(key)
    return b, problem(b)


def secret(b: Brain) -> tuple[str, str]:
    """(the brain's CLI client secret, "") from its `secret_file`; ("", why) when it cannot be used; ("", "") when the entry has no secret_file.
    `why` names the path and the reason and never a value or any of the file's content. The file is read at each call (a rotated secret applies
    at once); one that group or others can read is refused. JSON (a file starting with { or [) with a `client_secret` key, else a plain file whose first non-empty line is the secret.
    A value with a control or other non-printable character (a NUL or a lone surrogate would make the child process fail to start) or shorter than SECRET_MIN characters is unusable."""
    if not b.secret_file:
        return "", ""
    p = b.secret_file
    bad = _cfg.secret_file_mode_problem(p)
    if bad:
        return "", f"secret_file {p} {bad}"
    try:
        raw = Path(p).read_text(encoding="utf-8")
    except OSError as e:
        return "", f"secret_file {p} cannot be read: {e.strerror or type(e).__name__}"
    except ValueError:
        return "", f"secret_file {p} cannot be read: not text"
    if raw.lstrip().startswith(("{", "[")):
        try:
            d = json.loads(raw)
        except ValueError:
            return "", f"secret_file {p} is not valid JSON"
        v = d.get("client_secret") if isinstance(d, dict) else None
        if not isinstance(v, str) or not v.strip():
            return "", f"secret_file {p} has no client_secret key"
        v = v.strip()
    else:
        v = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
        if not v:
            return "", f"secret_file {p} is empty"
    if not v.isprintable():
        return "", f"secret_file {p} has an unusable client_secret (a control or other non-printable character)"
    if len(v) < SECRET_MIN:
        return "", f"secret_file {p} has an unusable client_secret (shorter than {SECRET_MIN} characters)"
    return v, ""


def prepare(slug: Any = "", env: dict[str, str] | None = None, brain: Brain | None = None) -> tuple[dict[str, str], str]:
    """(the environment a gbrain CLI call for this slug runs with, the refusal's text or ""): one read of the brain's secret_file decides both, so
    a file that turns unusable between a check and the call cannot let the call run on another value. The environment is a copy of `env` (default:
    the server's) with the client secret variable removed first, whatever the parent holds, and set only from this brain's own secret_file;
    GBRAIN_HOME is set to the brain's home when it has one. A refusal (see cli_refusal) comes with an environment without the secret: the call must not run."""
    out = dict(os.environ if env is None else env)
    out.pop(SECRET_ENV, None)
    b = brain or for_key(slug)
    if b.home:
        out["GBRAIN_HOME"] = b.home
    if b.default:
        return out, ""
    if not b.home:
        return out, (f"refused: second brain {b.name!r} has no home in its [[brains]] entry, so the CLI for {_norm(slug)} would use the default brain; "
                     f"set home = \"<its GBRAIN_HOME folder>\" on that entry")
    v, why = secret(b)
    if why:
        warn_once(b, why, "its gbrain CLI calls are refused")
        return out, f"refused: second brain {b.name!r}: {why}"
    clear(b, "its gbrain CLI calls are refused")
    if v:
        out[SECRET_ENV] = v
    return out, ""


def gbrain_env(slug: Any = "", env: dict[str, str] | None = None, brain: Brain | None = None) -> dict[str, str]:
    """The environment a gbrain CLI call for this slug runs with (prepare's first part): a copy of `env` (default: the server's) without any
    client secret of the parent, GBRAIN_HOME=<home> of the slug's brain when it has one, and the secret from the brain's own secret_file when
    it has one that can be used (an unusable one leaves the variable out: the call is refused, see cli_refusal)."""
    return prepare(slug, env, brain)[0]


def redact(text: str, env: dict[str, str]) -> str:
    """`text` with the client secret of this child environment replaced by [redacted]: whatever a CLI call prints back (an error that echoes its
    environment, say) never carries it on into a note, a log or a reply."""
    v = env.get(SECRET_ENV) or ""
    return text.replace(v, "[redacted]") if v and text else text


def cli_refusal(slug: Any) -> str:
    """"" when a gbrain CLI call (a read or a write) for this slug may run; else the refusal's text. A second brain with no `home` has no
    gbrain home of its own: the CLI would run with the default one, so a read would return the default brain's page for the slug (or none)
    and a write would put the page into the default brain; both are refused until the entry names its home. A second brain whose
    `secret_file` cannot be used (unreadable, empty, no client_secret, or readable by group or others) is refused too, with a line naming the
    path and the reason and said once per outage: the CLI would fail without its secret. The caller treats a refused read as a page that
    could not be read (skipped, said once per outage). The default brain is never refused here."""
    return prepare(slug)[1]


_WARNED: set[tuple[str, str]] = set()      # (brain name, channel): the reads of a brain that fail now; a brain with any entry here is in an outage
_WARN_LOCK = threading.Lock()


def warn_once(b: Brain, why: str, what: str, channel: str | None = None) -> bool:
    """Record that a read of this brain failed and say so once per outage: one stderr line naming the brain, printed only when no other read
    of it is failing already. That is one warning per outage per brain: a second kind of failure (another reader, another page) on a brain
    that is already in an outage stays silent until it recovers, and clear() ends the outage when the last failing read works again. The state
    is per brain, in this process; another process keeps its own. `channel` names the failing read (default `what`); clear(brain, channel) is
    how it reports that it reads again. → True when it printed. The line is printed under the lock, so a warning and the "is back" line of the
    same brain come out in the order they happened."""
    k = (b.name, channel or what)
    with _WARN_LOCK:
        first = not any(n == b.name for n, _c in _WARNED)
        _WARNED.add(k)
        if first:
            print(f"brains: second brain {b.name!r}: {why}; {what}", file=sys.stderr, flush=True)
    return first


def _back(name: str) -> None:
    print(f"brains: second brain {name!r} is back", file=sys.stderr, flush=True)


def clear(b: Brain, what: str | None = None) -> bool:
    """A read of this brain worked again (`what` given: the read that failed under that channel; none: every read). When that leaves no failing
    read, the outage is over: one stderr line says the brain is back, and the next outage is reported afresh. A read that never failed changes
    nothing and prints nothing. → True when it printed."""
    with _WARN_LOCK:
        had = any(n == b.name for n, _c in _WARNED)
        for k in [k for k in _WARNED if k[0] == b.name and (what is None or k[1] == what)]:
            _WARNED.discard(k)
        over = had and not any(n == b.name for n, _c in _WARNED)
        if over:
            _back(b.name)
    return over


def clear_unvisited(prefix: str, keep: set[str]) -> None:
    """Drop the failing reads whose channel is `prefix` + a name not in `keep`: a reader that no longer visits a page (its debts are settled, the
    page was renamed or deleted) never reports that page as read again, and its channel would hold the brain in an outage for good. A brain left
    with no failing read gets its "is back" line, as in clear()."""
    with _WARN_LOCK:
        before = {n for n, _c in _WARNED}
        for k in [k for k in _WARNED if k[1].startswith(prefix) and k[1][len(prefix):] not in keep]:
            _WARNED.discard(k)
        for n in sorted(before - {n for n, _c in _WARNED}):
            _back(n)


def looked_in(key: Any) -> str:
    """For a page reported missing: "" when the page key belongs to the default brain, else one sentence naming the second brain it was looked up
    in and the prefix or slug that routed it there, and the cause to check when every page under that prefix reads as missing (a prefix
    that names no folder in the copy)."""
    k = _norm(key)
    b = for_key(k)
    if b.default:
        return ""
    pre = next((p for p in b.prefixes if k.startswith(p)), None)
    slug = next((s for s in b.slugs if k == s or k.startswith(s + "/")), None)
    newp = next((p for p in b.new_prefixes if k.startswith(p)), None) if pre is None and slug is None else None
    if newp is not None:
        return (f"{k} is routed to second brain {b.name!r} by its new_prefixes entry {newp!r} (a page that exists in no brain starts there), so it was "
                f"looked up in that brain and not in the default brain; if it is an existing page of the default brain, it reads there once its local copy holds it")
    if pre is not None:
        via, kind = f"prefix {pre!r}", "prefix"
    elif slug is not None:
        via, kind = f"slug {slug!r}", "slug"
    else:
        return (f"{k} is routed to second brain {b.name!r} by its [[brains]] entry, so it was looked up in that brain and not in the default brain; "
                f"if every page of that brain reads as missing, check the entry's prefixes and slugs")
    return (f"{k} is routed to second brain {b.name!r} by its {via}, so it was looked up in that brain and not in the default brain; "
            f"if every page under that {kind} reads as missing, check that it names a folder in that brain's copy ([[brains]] {b.name})")


def skip(key: Any, what: str) -> str:
    """Fail open for one page: "" when its brain can be read (the caller goes on), else the brain's name after one warning
    for `what` (the caller skips the page for this run)."""
    b, why = key_problem(key)
    if not why:
        if not b.default:
            clear(b, what)
        return ""
    warn_once(b, why, what)
    return b.name
