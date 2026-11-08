"""connectors.py — one name for every call to this instance's own connectors, whichever way it came in.

A Claude Code session reaches the owner's own servers two ways: the direct claude.ai connector, one tool per upstream
tool (`mcp__claude_ai_Stackshot__update`), or the MCP portal's Code Mode, one tool for everything
(`mcp__claude_ai_<portal>__portal_codemode_execute`) with the upstream calls inside its JavaScript
(`codemode.stackshot_update({...})`). Every hook that cares which server and tool a call reaches asks this module and writes
its rule as a `server.tool` pattern (`stackshot.update`, `gbrain.*`, `*.send_gmail_message`), never as a connector name.

    resolve(tool_name, tool_input, mcp_server=None)
        → Resolution(route, calls=[Call(server, tool, args, …)], ok, why), or None when this box has no catalog
    matches(calls, patterns)  → the calls whose `server.tool` matches one of the fnmatch patterns

Nothing in the catalog is typed in. `connectors.py build` (portal-sync.sh runs it after every sync) reads the portal's
entries from the Cloudflare API ([portal] account_id, token_file; the portals that carry this instance's server_id): their
ids, upstream URLs and tool lists; and the CLI's own connector list (`claude mcp list`: a name and a URL per connector);
and joins the two on the upstream host. The portal entry id is the server's one name (stackshot, gbrain, notes, …). The
direct tool prefix is derived as the CLI derives it: `mcp__` + the connector name with every character outside
[A-Za-z0-9_-] turned into `_` (for a `claude.ai ` name the runs collapse and the ends are trimmed) + `__` — the CLI's own
function, read from claude 2.1.296.

A server can carry more than one name on a box: the claude.ai connector, and the same URL configured again as a CLI server
(an API-key session's local `mcp-portal`). `claude mcp list` runs in a fresh empty directory, so only
user-scope servers and claude.ai connectors appear and no folder's local server hides a claude.ai one; of a host's names the
`claude.ai ` one is the primary ("connector", "prefix", as before), and every other name, from that list and from every
server with a URL in ~/.claude.json (user scope and each project's), is an alias ("aliases": [{connector, prefix}]). resolve
matches a server or the portal by any of its names and any of its prefixes.

The catalog goes to [portal] catalog_file (default <paths.state>/connectors.json); with [portal] catalog_commit = true and
the file inside a git checkout, build commits and pushes it, which is how an instance's config repo carries it to every box. A hook on a box without a catalog gets None and keeps its old behaviour.

A portal script is read, never run: `codemode.<entry>_<tool>(<args>)`, the entry being the longest catalog id that prefixes
the name. The args are read as a literal (object, array, string, number, true/false/null); any other value (a variable, a
call, a template with ${…}) is DYNAMIC, a placeholder that is truthy and not a str. A script the reader cannot vouch for
leaves `ok` false and says why: `codemode` used other than as `codemode.<name>(…)` (an alias, `codemode[…]`, a bare
reference, a call inside a template), a spread or a computed key in the args, an argument that is not an object literal,
eval / Function, or an entry the catalog does not know. The calls it did read are still returned, so a page hook can count
them; a call to an unknown entry comes back with server None.

CLI:  connectors.py build [--quiet]        regenerate the catalog (one summary line; the token is never printed)
      connectors.py resolve  < hook.json   the Resolution of a hook's JSON (a probe)
      connectors.py prefix <server>        a server's direct tool prefix (`mcp__claude_ai_<Name>__`), for shell scripts
      connectors.py prefixes <server>      every prefix of a server, the primary first, then its aliases', one per line
      connectors.py servers                the catalog's server ids, one per line
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from stackshot.core import config as _cfg  # noqa: E402  (stackshot.toml: [portal] and the state dir; stdlib tomllib)

EXECUTE = "portal_codemode_execute"
PORTAL = "portal"                                   # the server id of the portal's own meta-tools (search, list, toggle)
CF_API = "https://api.cloudflare.com/client/v4"
CLAUDE_JSON = "~/.claude.json"                      # the CLI's own config: user-scope and per-project MCP servers (aliases)


class _Dynamic:
    """The value of an argument the script computes: truthy, never a str, printed as <dynamic>."""
    __slots__ = ()

    def __bool__(self):
        return True

    def __repr__(self):
        return "DYNAMIC"

    def __str__(self):
        return "<dynamic>"


DYNAMIC = _Dynamic()


# ---------------------------------------------------------------------------------------------------------- names
def cli_name(connector: str) -> str:
    """What a server's display name becomes inside `mcp__<here>__<tool>`: the CLI's own rule (claude 2.1.296, In())."""
    r = re.sub(r"[^a-zA-Z0-9_-]", "_", connector)
    if connector.startswith("claude.ai "):
        r = re.sub(r"_+", "_", r)
        r = re.sub(r"^_|_$", "", r)
    return r


def prefix_of(connector: str) -> str:
    return f"mcp__{cli_name(connector)}__"


def host_of(url: str) -> str:
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    return (urllib.parse.urlsplit(u).hostname or "").lower()


# -------------------------------------------------------------------------------------------------------- catalog
def catalog_path() -> str:
    v = _cfg.get("portal", "catalog_file")
    return os.path.expanduser(str(v)) if v else str(_cfg.state("connectors.json"))


def load_catalog(path: str | None = None) -> dict | None:
    try:
        with open(path or catalog_path(), encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    return d if isinstance(d, dict) and isinstance(d.get("servers"), dict) else None


def names_of(entry: dict | None) -> list[tuple[str, str]]:
    """[(connector, prefix)] of a catalog entry (a server or the portal): the primary first, then its aliases."""
    e = entry if isinstance(entry, dict) else {}
    out = []
    if e.get("connector"):
        out.append((str(e["connector"]), str(e.get("prefix") or "")))
    for a in e.get("aliases") or []:
        if isinstance(a, dict) and a.get("connector"):
            out.append((str(a["connector"]), str(a.get("prefix") or "")))
    return out


def _strip(name: str, entry: dict) -> str | None:
    """The tool name with the longest of the entry's prefixes it starts with taken off; None when it starts with none."""
    pres = sorted((p for _, p in names_of(entry) if p and name.startswith(p)), key=len, reverse=True)
    return name[len(pres[0]):] if pres else None


# ------------------------------------------------------------------------------------------------------- resolve
@dataclass
class Call:
    server: str | None       # a catalog id; PORTAL for the portal's own meta-tools; None for an entry the catalog lacks
    tool: str
    args: dict
    route: str               # "direct" | "portal"
    known: bool = True       # the server is in the catalog
    clean: bool = True       # the args were read in full: an object literal with plain keys, no spread
    note: str = ""           # why not clean

    @property
    def name(self) -> str:
        return f"{self.server or '?'}.{self.tool}"


@dataclass
class Resolution:
    route: str | None        # "direct" | "portal" | None: not a tool of ours
    calls: list[Call] = field(default_factory=list)
    ok: bool = False         # every call known and every script read with confidence
    why: str = ""

    @property
    def own(self) -> bool:
        """At least one call, every one to a server of the catalog (the portal's own meta-tools included), nothing in doubt."""
        return self.route is not None and self.ok and bool(self.calls) and all(c.known for c in self.calls)

    def to_json(self) -> dict:
        return {"route": self.route, "ok": self.ok, "why": self.why, "own": self.own,
                "calls": [{"server": c.server, "tool": c.tool, "args": plain(c.args), "known": c.known, "clean": c.clean, "note": c.note}
                          for c in self.calls]}


def plain(v):
    """A value with DYNAMIC rendered as "<dynamic>", for JSON."""
    if v is DYNAMIC:
        return "<dynamic>"
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


def resolve(tool_name, tool_input=None, mcp_server=None, catalog: dict | None = None) -> Resolution | None:
    """The calls a Claude Code tool call makes to this instance's own servers, by either route; None without a catalog.
    `mcp_server` is the hook input's {name, source} of the server (claude 2.1.274+); the name wins over the prefix table."""
    cat = load_catalog() if catalog is None else catalog
    if not cat:
        return None
    name = str(tool_name or "")
    inp = tool_input if isinstance(tool_input, dict) else {}
    if not name.startswith("mcp__"):
        return Resolution(None, [], False, "not an MCP tool")
    srv = str((mcp_server or {}).get("name") or "") if isinstance(mcp_server, dict) else ""
    servers = cat.get("servers") or {}
    hit = None                                          # a server by its primary connector name or any alias
    for sid, s in servers.items():
        if srv and any(srv == n for n, _ in names_of(s)):
            hit = (sid, "")
            break
    if hit is None:                                     # else by prefix, the primary's or an alias's: the longest wins
        for sid, s in servers.items():
            for _, pre in names_of(s):
                if pre and name.startswith(pre) and (hit is None or len(pre) > len(hit[1])):
                    hit = (sid, pre)
    if hit:
        sid = hit[0]
        tool = _strip(name, servers[sid])
        return Resolution("direct", [Call(sid, tool if tool is not None else name.rsplit("__", 1)[-1], inp, "direct")], True)
    portal = cat.get("portal") or {}
    tool = _strip(name, portal)
    if not ((srv and any(srv == n for n, _ in names_of(portal))) or tool is not None):
        return Resolution(None, [], False, "not one of ours")
    if tool is None:
        tool = name.rsplit("__", 1)[-1]
    if tool != EXECUTE:
        return Resolution("portal", [Call(PORTAL, tool, inp, "portal")], True)
    calls, problems = read_script(str(inp.get("code") or ""), cat)
    return Resolution("portal", calls, not problems, "; ".join(problems))


def matches(calls, patterns) -> list[Call]:
    """The calls whose `server.tool` matches one of the patterns (fnmatch: `stackshot.update`, `gbrain.*`, `*.send_gmail_message`)."""
    pats = [patterns] if isinstance(patterns, str) else list(patterns or ())
    return [c for c in calls if c.known and any(fnmatch.fnmatchcase(c.name, p) for p in pats)]


# --------------------------------------------------------------------------------------------- the script reader
_CALL = re.compile(r"\s*\.\s*([A-Za-z_$][\w$]*)\s*\(")
_NUM = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_KW = re.compile(r"(?:true|false|null|undefined)(?![\w$])")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def read_script(code: str, cat: dict) -> tuple[list[Call], list[str]]:
    """Every `codemode.<entry>_<tool>(<args>)` of a Code Mode script → ([Call], [what keeps it from being read with confidence])."""
    entries = sorted(cat.get("servers") or {}, key=len, reverse=True)
    masked, spans = mask(code)
    problems: list[str] = []
    if re.search(r"(?<![\w$.])(?:eval|Function)\s*\(", masked) or re.search(r"\bnew\s+Function\b", masked):
        problems.append("eval/Function")
    if any(re.search(r"(?<![\w$])codemode(?![\w$])", code[a:b]) for a, b in spans):
        problems.append("codemode inside a template literal")
    calls: list[Call] = []
    for m in re.finditer(r"(?<![\w$.])codemode(?![\w$])", masked):
        mm = _CALL.match(masked, m.end())
        if not mm:
            problems.append("codemode used other than as codemode.<name>(…)")
            continue
        ident = mm.group(1)
        open_at = mm.end() - 1
        close_at = close_of(masked, open_at)
        if close_at < 0:
            problems.append(f"codemode.{ident}: unbalanced call")
            continue
        args, clean, note = read_args(code[open_at + 1:close_at])
        server, tool = split_entry(ident, entries)
        calls.append(Call(server, tool, args, "portal", known=server is not None, clean=clean, note=note))
        if server is None:
            problems.append(f"codemode.{ident}: unknown entry")
        elif not clean:
            problems.append(f"codemode.{ident}: {note}")
    return calls, list(dict.fromkeys(problems))


def split_entry(ident: str, entries: list[str]) -> tuple[str | None, str]:
    for e in entries:
        if ident.startswith(e + "_") and len(ident) > len(e) + 1:
            return e, ident[len(e) + 1:]
    return None, ident


def mask(code: str) -> tuple[str, list[tuple[int, int]]]:
    """The code with every string, template and comment blanked (same length, newlines kept), so a scan sees only
    structure; and the spans of the templates' ${…} parts, which are blanked too."""
    out = list(code)
    n = len(code)
    spans: list[tuple[int, int]] = []

    def blank(a, b):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    def string_end(i, q):
        j = i + 1
        while j < n and code[j] != q and code[j] != "\n":
            j += 2 if code[j] == "\\" else 1
        return j

    def template_end(i):
        """The index of the closing backtick of the template starting at i (or n), recording its ${…} spans."""
        j = i + 1
        while j < n:
            c = code[j]
            if c == "\\":
                j += 2
            elif c == "`":
                return j
            elif c == "$" and j + 1 < n and code[j + 1] == "{":
                k, depth = j + 2, 1
                while k < n and depth:
                    ch = code[k]
                    if ch in "'\"":
                        k = string_end(k, ch) + 1
                        continue
                    if ch == "`":
                        k = template_end(k) + 1
                        continue
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                    k += 1
                spans.append((j, k))
                j = k
            else:
                j += 1
        return n

    i = 0
    while i < n:
        c = code[i]
        d = code[i + 1] if i + 1 < n else ""
        if c == "/" and d == "/":
            j = code.find("\n", i)
            j = n if j < 0 else j
            blank(i, j); i = j
        elif c == "/" and d == "*":
            j = code.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j); i = j
        elif c in "'\"":
            j = string_end(i, c)
            blank(i + 1, j); i = j + 1
        elif c == "`":
            j = template_end(i)
            blank(i + 1, j); i = j + 1
        else:
            i += 1
    return "".join(out), spans


def close_of(masked: str, i: int) -> int:
    """The index of the bracket closing the one at i, in masked text (strings blanked), or -1."""
    depth = 0
    for k in range(i, len(masked)):
        ch = masked[k]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return k
    return -1


def read_args(src: str) -> tuple[dict, bool, str]:
    """(args, clean, note) of the text between a call's parentheses: a tool's input is its first argument, an object."""
    p = _Lit(src)
    p.ws()
    if p.at_end():
        return {}, True, ""
    if p.peek() != "{":
        return {}, False, "the argument is not an object literal"
    return p.obj()


class _Lit:
    """A reader of a JavaScript literal: objects, arrays, strings, numbers, keywords; anything else is DYNAMIC."""

    def __init__(self, s: str):
        self.s, self.i, self.n = s, 0, len(s)

    def peek(self) -> str:
        return self.s[self.i] if self.i < self.n else ""

    def at_end(self) -> bool:
        return self.i >= self.n

    def ws(self):
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.s.startswith("//", self.i):
                j = self.s.find("\n", self.i)
                self.i = self.n if j < 0 else j
            elif self.s.startswith("/*", self.i):
                j = self.s.find("*/", self.i + 2)
                self.i = self.n if j < 0 else j + 2
            else:
                break

    def obj(self) -> tuple[dict, bool, str]:
        self.i += 1                                   # past {
        out: dict = {}
        clean, notes = True, []
        while True:
            self.ws()
            if self.at_end():
                return out, False, "unterminated object"
            c = self.peek()
            if c == "}":
                self.i += 1
                break
            if c == ",":
                self.i += 1
                continue
            if self.s.startswith("...", self.i):
                clean = False; notes.append("a spread")
                self.i += 3; self.skip_expr()
                continue
            if c == "[":
                clean = False; notes.append("a computed key")
                self.i += 1; self.skip_expr()
                if self.peek() == "]":
                    self.i += 1
                self.ws()
                if self.peek() == ":":
                    self.i += 1; self.value()
                else:
                    self.skip_expr()
                continue
            key = self.key()
            if key is None:
                clean = False; notes.append("an unreadable member")
                self.skip_expr()
                continue
            self.ws()
            c = self.peek()
            if c == ":":
                self.i += 1
                v, vclean, vnote = self.value()
                out[key] = v
                if not vclean:
                    clean = False; notes.append(vnote)
            elif c in (",", "}"):                     # shorthand {id}: the key is plain, the value a variable
                out[key] = DYNAMIC
            else:                                     # a method, async x(){}, get x(){} …
                clean = False; notes.append("a method or an unreadable member")
                self.skip_expr()
        return out, clean, "; ".join(dict.fromkeys(notes))

    def arr(self) -> tuple[list, bool, str]:
        self.i += 1                                   # past [
        out: list = []
        clean, notes = True, []
        while True:
            self.ws()
            if self.at_end():
                return out, False, "unterminated array"
            c = self.peek()
            if c == "]":
                self.i += 1
                break
            if c == ",":
                self.i += 1
                continue
            if self.s.startswith("...", self.i):
                clean = False; notes.append("a spread")
                self.i += 3; self.skip_expr()
                continue
            v, vclean, vnote = self.value()
            out.append(v)
            if not vclean:
                clean = False; notes.append(vnote)
        return out, clean, "; ".join(dict.fromkeys(notes))

    def key(self) -> str | None:
        c = self.peek()
        if c in ("'", '"'):
            return self.string()
        m = _IDENT.match(self.s, self.i) or _NUM.match(self.s, self.i)
        if m:
            self.i = m.end()
            return m.group(0)
        return None

    def value(self) -> tuple[object, bool, str]:
        """One value: a literal when it stands alone, else the whole expression skipped and DYNAMIC."""
        self.ws()
        start = self.i
        c = self.peek()
        val, clean, note, lit = DYNAMIC, True, "", True
        if c == "{":
            val, clean, note = self.obj()
        elif c == "[":
            val, clean, note = self.arr()
        elif c in ("'", '"'):
            val = self.string()
        elif c == "`":
            txt, interp = self.template()
            val = DYNAMIC if interp else txt
        elif (m := _NUM.match(self.s, self.i)):
            self.i = m.end(); val = _num(m.group(0))
        elif (m := _KW.match(self.s, self.i)):
            self.i = m.end(); val = {"true": True, "false": False}.get(m.group(0))
        else:
            lit = False
        if lit:
            self.ws()
            if self.peek() in ("", ",", "}", "]", ")"):
                return val, clean, note
        self.i = start                                # `"a" + b`, `x ? 1 : 2`, `[1].map(f)`, a call, a variable …
        self.skip_expr()
        return DYNAMIC, True, ""

    def string(self) -> str:
        q = self.s[self.i]
        self.i += 1
        out = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == q:
                self.i += 1
                return "".join(out)
            if c == "\n":
                break
            if c == "\\" and self.i + 1 < self.n:
                self.i += 1
                e = self.s[self.i]
                simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0", "\n": ""}
                if e in simple:
                    out.append(simple[e]); self.i += 1
                elif e == "x" and re.match(r"[0-9a-fA-F]{2}", self.s[self.i + 1:self.i + 3]):
                    out.append(chr(int(self.s[self.i + 1:self.i + 3], 16))); self.i += 3
                elif e == "u" and self.s[self.i + 1:self.i + 2] == "{":
                    j = self.s.find("}", self.i)
                    out.append(chr(int(self.s[self.i + 2:j], 16))); self.i = j + 1
                elif e == "u" and re.match(r"[0-9a-fA-F]{4}", self.s[self.i + 1:self.i + 5]):
                    out.append(chr(int(self.s[self.i + 1:self.i + 5], 16))); self.i += 5
                else:
                    out.append(e); self.i += 1
                continue
            out.append(c); self.i += 1
        return "".join(out)                           # unterminated: what was read

    def template(self) -> tuple[str, bool]:
        """→ (text, has ${…}); self.i past the closing backtick."""
        self.i += 1
        out, interp = [], False
        while self.i < self.n:
            c = self.s[self.i]
            if c == "`":
                self.i += 1
                return "".join(out), interp
            if c == "\\" and self.i + 1 < self.n:
                out.append(self.s[self.i + 1]); self.i += 2
                continue
            if c == "$" and self.s[self.i + 1:self.i + 2] == "{":
                interp = True
                self.i += 2
                self.skip_expr()
                if self.peek() == "}":
                    self.i += 1
                continue
            out.append(c); self.i += 1
        return "".join(out), interp

    def skip_expr(self):
        """Past an expression: up to a `,` or a closing bracket at depth 0 (not consumed), strings and templates skipped."""
        depth = 0
        while self.i < self.n:
            c = self.s[self.i]
            if c in ("'", '"'):
                self.string(); continue
            if c == "`":
                self.template(); continue
            if self.s.startswith("//", self.i) or self.s.startswith("/*", self.i):
                self.ws(); continue
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    return
                depth -= 1
            elif c == "," and depth == 0:
                return
            self.i += 1


def _num(txt: str):
    t = txt.lower()
    if t.startswith(("0x", "-0x")):
        return int(txt, 16)
    return float(txt) if any(ch in t for ch in ".e") else int(txt)


# --------------------------------------------------------------------------------------------------------- build
def cf_get(path: str, token: str):
    req = urllib.request.Request(CF_API + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"connectors: Cloudflare {path}: HTTP {e.code}")
    except Exception as e:
        raise SystemExit(f"connectors: Cloudflare {path}: {type(e).__name__}")
    if not d.get("success"):
        errs = d.get("errors") or []
        raise SystemExit(f"connectors: Cloudflare {path}: " + (str(errs[0].get("message") or errs[0])[:160] if errs else "not successful"))
    return d.get("result")


def cli_connectors() -> tuple[dict[str, list[str]], str]:
    """{upstream host: [connector names, the primary first]} from `claude mcp list` (the CLI's own list, claude.ai connectors
    included), and why it could not be read ("" when it could). It runs in a fresh empty directory, never the caller's: a
    server local to the caller's folder with a claude.ai connector's URL would hide that connector (local config wins), so
    the primary name would depend on where the build ran. Of a host's names the `claude.ai ` one is the primary,
    then the order printed."""
    exe = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not os.path.exists(exe):
        return {}, "claude not found"
    try:
        with tempfile.TemporaryDirectory(prefix="stackshot-mcp-list-") as cwd:
            r = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True, timeout=240, stdin=subprocess.DEVNULL,
                               cwd=cwd, env={**os.environ, "NO_COLOR": "1"})
    except Exception as e:
        return {}, f"claude mcp list: {type(e).__name__}"
    seen: dict[str, list[str]] = {}
    for ln in re.sub(r"\x1b\[[0-9;]*m", "", r.stdout).splitlines():
        m = re.match(r"^(\S.*?):\s+(https?://\S+)", ln.strip())
        if m and m.group(1) not in seen.setdefault(host_of(m.group(2)), []):
            seen[host_of(m.group(2))].append(m.group(1))
    out = {h: sorted(ns, key=lambda n: (not n.startswith("claude.ai "), ns.index(n))) for h, ns in seen.items()}
    return out, ("" if out else f"claude mcp list printed no connector (exit {r.returncode})")


def config_connectors(path: str | None = None) -> tuple[dict[str, set[str]], str]:
    """{upstream host: {server names}} of every MCP server with a URL (http, sse) in the CLI's config (~/.claude.json): the
    user scope's "mcpServers" and every project's; and why it could not be read ("" when it could). The source of aliases:
    a server configured again under a second name, in some folder, is still the same server."""
    try:
        with open(os.path.expanduser(path or CLAUDE_JSON), encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}, "~/.claude.json not found"
    except Exception as e:
        return {}, f"~/.claude.json: {type(e).__name__}"
    if not isinstance(d, dict):
        return {}, "~/.claude.json: not an object"
    projects = d.get("projects") if isinstance(d.get("projects"), dict) else {}
    tables = [d.get("mcpServers")] + [p.get("mcpServers") for _, p in sorted(projects.items()) if isinstance(p, dict)]
    out: dict[str, set[str]] = {}
    for t in tables:
        if not isinstance(t, dict):
            continue
        for name, v in t.items():
            url = v.get("url") if isinstance(v, dict) else None
            if isinstance(url, str) and url.strip() and host_of(url):
                out.setdefault(host_of(url), set()).add(str(name))
    return out, ""


def _names_for(host: str, old: dict, direct: dict, cfg: dict, cfg_err: str, cli_err: str = "") -> tuple[str | None, list[dict]]:
    """(primary, aliases) of one upstream host: the primary from the CLI list (else the previous catalog's), the aliases every
    other name the CLI list printed or ~/.claude.json holds. When either source could not be read, the previous catalog's
    aliases are kept as well, so a failed read never drops a name the hooks match on; the next full read settles them."""
    listed = direct.get(host) or []
    primary = listed[0] if listed else (old.get("connector") or None)
    more = set(listed)
    if cfg_err or cli_err:
        more |= {n for n, _ in names_of(old)[1:]}
    if not cfg_err:
        more |= cfg.get(host, set())
    more.discard(primary)
    return primary, [{"connector": n, "prefix": prefix_of(n)} for n in sorted(more)]


def build(quiet: bool = False) -> str:
    """Regenerate the catalog from the portal and the CLI; write it when it changed; commit it when configured. → the summary."""
    acct = str(_cfg.get("portal", "account_id") or "")
    if not acct:
        raise SystemExit("connectors: [portal] account_id is empty; nothing to build")
    with open(_cfg.path("portal", "token_file"), encoding="utf-8") as f:
        token = f.read().strip()
    sid = str(_cfg.get("portal", "server_id") or "")
    portals = cf_get(f"/accounts/{acct}/access/ai-controls/mcp/portals", token) or []
    mine = [p for p in portals if isinstance(p, dict) and any(isinstance(s, dict) and s.get("id") == sid for s in p.get("servers") or [])]
    if not mine:
        raise SystemExit(f"connectors: no portal of account {acct[:4]}… carries the entry {sid!r}")
    direct, cli_err = cli_connectors()
    cfg, cfg_err = config_connectors()
    old = load_catalog() or {}
    old_servers = old.get("servers") or {}
    servers: dict = {}
    for p in mine:
        for s in p.get("servers") or []:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            host = host_of(s.get("hostname") or "")
            name, aliases = _names_for(host, old_servers.get(s["id"]) or {}, direct, cfg, cfg_err, cli_err)
            tools = {}
            for t in s.get("tools") or []:
                if isinstance(t, dict) and t.get("name"):
                    tools[str(t["name"])] = {"read_only": bool((t.get("annotations") or {}).get("readOnlyHint"))}
            servers[s["id"]] = {"name": s.get("name"), "url": s.get("hostname"), "auth": s.get("auth_type"),
                                "connector": name, "prefix": prefix_of(name) if name else "", "aliases": aliases, "tools": tools}
    p0 = mine[0]
    phost = host_of(p0.get("hostname") or "")
    pname, paliases = _names_for(phost, old.get("portal") or {}, direct, cfg, cfg_err, cli_err)
    cat = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "generated by connectors.py build (stackshot); never edited by hand",
        "instance": sid,
        "sources": {"portal": "Cloudflare MCP portals API, portal " + ", ".join(str(p.get("id")) for p in mine),
                    "direct": "claude mcp list" if not cli_err else f"kept from the previous catalog ({cli_err})",
                    "aliases": "claude mcp list and ~/.claude.json" if not cfg_err else f"claude mcp list and the previous catalog ({cfg_err})"},
        "portal": {"id": p0.get("id"), "name": p0.get("name"), "url": p0.get("hostname"), "connector": pname,
                   "prefix": prefix_of(pname) if pname else "", "aliases": paliases},
        "servers": servers,
    }
    path = catalog_path()
    text = json.dumps(cat, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            same = json.load(f)
    except Exception:
        same = None
    unchanged = isinstance(same, dict) and {k: v for k, v in same.items() if k != "generated"} == {k: v for k, v in cat.items() if k != "generated"}
    state = "unchanged"
    if not unchanged:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        state = "written"
        if _cfg.get("portal", "catalog_commit"):
            state += "; " + commit(path, f"connectors: catalog regenerated by portal-sync ({len(servers)} servers)")
    missing = [k for k, v in servers.items() if not v["connector"]]
    n_alias = sum(len(v["aliases"]) for v in servers.values()) + len(paliases)
    summary = (f"connectors: {len(servers)} servers (" + ", ".join(f"{k} {len(v['tools'])}" for k, v in sorted(servers.items())) + ")"
               + (f", no direct name for {', '.join(missing)}" if missing else "") + (f" [{cli_err}]" if cli_err else "")
               + (f", {n_alias} alias{'es' if n_alias != 1 else ''}" if n_alias else "") + (f" [{cfg_err}]" if cfg_err else "")
               + f", portal {pname!r} → {path} ({state})")
    if not quiet:
        print(summary)
    return summary


def commit(path: str, message: str) -> str:
    """Commit and push one file in the git checkout that holds it (add and commit by pathspec, so nothing else staged
    rides along; push first, pull --rebase only when the push is refused). → one short phrase."""
    d = os.path.dirname(os.path.abspath(path))
    top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        return "not in a git checkout"
    root = top.stdout.strip()
    rel = os.path.relpath(os.path.abspath(path), root)

    def g(*a):
        return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True)

    if g("add", "--", rel).returncode != 0:
        return "git add failed"
    if g("diff", "--cached", "--quiet", "--", rel).returncode == 0:
        return "nothing to commit"
    r = g("commit", "-q", "-m", message, "--", rel)
    if r.returncode != 0:
        g("reset", "-q", "--", rel)
        return "git commit failed: " + (r.stderr.strip() or r.stdout.strip())[:160]
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    if g("push", "-q", "origin", branch).returncode == 0:
        return "committed and pushed"
    g("pull", "--rebase", "--autostash", "-q", "origin", branch)
    if g("push", "-q", "origin", branch).returncode == 0:
        return "committed and pushed (after a rebase)"
    return "committed; the push was refused (the next build retries)"


# ----------------------------------------------------------------------------------------------------------- CLI
def main(argv: list[str]) -> int:
    a = argv[1:]
    if a[:1] == ["build"]:
        build(quiet="--quiet" in a)
        return 0
    if a == ["resolve"]:
        ev = json.load(sys.stdin)
        res = resolve(ev.get("tool_name"), ev.get("tool_input"), ev.get("mcp_server"))
        print(json.dumps(res.to_json() if res else None, ensure_ascii=False, indent=1))
        return 0
    if a[:1] == ["prefix"] and len(a) == 2:
        cat = load_catalog() or {}
        pre = ((cat.get("servers") or {}).get(a[1]) or {}).get("prefix") or ((cat.get("portal") or {}).get("prefix") if a[1] == PORTAL else "")
        if not pre:
            return 1
        print(pre)
        return 0
    if a[:1] == ["prefixes"] and len(a) == 2:
        cat = load_catalog() or {}
        entry = (cat.get("servers") or {}).get(a[1]) or ((cat.get("portal") or {}) if a[1] == PORTAL else {})
        pres = [p for _, p in names_of(entry) if p]
        if not pres:
            return 1
        print("\n".join(dict.fromkeys(pres)))
        return 0
    if a == ["servers"]:
        cat = load_catalog() or {}
        for k in sorted(cat.get("servers") or {}):
            print(k)
        return 0 if cat else 1
    sys.exit("usage: connectors.py build [--quiet] | resolve < hook.json | prefix <server> | prefixes <server> | servers")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
