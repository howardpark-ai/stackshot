"""tools/rulebook_scan.py — the nightly scan of the instruction files sessions read for stale mentions of stackshot's tools and
sala's commands. Why: a rulebook line can keep saying `owner` after the
tools moved to `mover`, and nothing would catch it. Tokenless: no model call, no network but the one message per file it sends.

    rulebook_scan.py run [--dry-run] [--terms PATH] [--schema JSON] [--sala-help FILE] [--op-help FILE]
    audit.py scan [--dry-run]                          the same, from the audit's own entry point (the timer's unit runs this one)

What it reads ([rulebook_scan] in stackshot.toml; every path and every keeper is a config value; with no `files` table nothing is scanned):
    files           [[rulebook_scan.files]] glob + keeper, one table per set of files (a rulebook, the role briefs, the skills of a plugin's
                    source repo; not the copies under ~/.claude/plugins/cache); the keeper is the session its note goes to, [rulebook_scan] keeper when the
                    table names none. There is no default set: with no table, nothing is scanned and the run says so in one line. A set of
                    files whose text another project keeps takes another keeper by another [[rulebook_scan.files]] table.
    keeper          the session a set of files with no keeper of its own goes to (default "my-keeper")
    server          the server's own source (default: stackshot/web/server.py in this checkout). The tools' names and parameters are read with `ast`
                    from its `@mcp.tool` definitions and from the modules of the tools/ folder beside it, where each tool is registered with
                    `mcp.tool(...)(function)`, never by importing it: an import wants fastmcp and a store, and the server
                    refuses to start outside the production checkout without a config. `--schema JSON` ({"tool": ["param", …]}) replaces it.
    sala            the command (default `sala`): `sala --help` is read once. `sala op --help` is read too (it prints its verbs and
                    flags). Any other verb's `--help` is NOT run: the dispatcher hands a verb its arguments, and most verbs take
                    `--help` as a name (`sala retire --help` would try to retire a session). `[rulebook_scan] help_verbs` lists the
                    verbs known to print help (default ["op"]). Never a verb that acts.
    terms           the retired-terms list of part 1 (default tests/retired_terms.toml in the checkout); absent
                    → that check is skipped. Read tolerantly (see `load_terms`): arrays of tables `[[term]]`/`[[terms]]`/`[[retired]]`
                    with `pattern` (a regex) or `text`/`term`/`word`/`phrase` (literal) and an optional `use`/`instead`/`say`.

What it finds, only inside code (an inline `code span` or a fenced block), so prose that merely says "update" or "sala web" is never read:
    stackshot_<tool>(…) · mcp__stackshot__<tool>(…) · codemode.<x>_stackshot_<tool>({…})     a tool the server does not register
    <tool>(…) and `<tool>, name=…`                    for a tool the server registers: a parameter it does not take (`name=` or `{name:`)
    sala|salamander <verb> … --flag                   a verb sala does not list, or a flag its help does not list for that verb
    a term of the retired-terms list                  anywhere in the file, with what to say instead

Delivery: one note per file, to its keeper, through client.py's `message` (this box's token: a script's message, which the receiver is
told cannot be answered), the way the audit's findings reach an owner (message to the session). A finding already sent and still there
is not sent again: <paths.state>/rulebook-scan/sent.json keeps, per file, the keys of what was sent; a note carries only what is new
and says how many older ones are still open; a finding that was fixed drops out, so it is sent again if it comes back. A note that
fails to deliver is not recorded and goes again the next night.
Stdlib only."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import ast
import difflib
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
from stackshot.core import config as _cfg  # noqa: E402

KEEPER = "my-keeper"
NO_FILES_NOTE = "no [[rulebook_scan.files]] table in [rulebook_scan]: nothing is scanned"
DEFAULT_HELP_VERBS = ["op"]
SALA_LIB = "~/salamander/lib"          # sala's code: lib/<verb>.sh holds each verb; a flag found there is a help-text gap, not a stale mention
SALA_KEEPER = "my-sala-keeper"
SENDER = "stackshot rulebook scan"
MSG_MAX = 4000            # server.py's cap on a message
NOTE_MAX = 3600           # what a note keeps of it: the list is cut with a count, never the framing
LINE_CAP = 300            # a finding's stale text, shortened


@dataclass
class Finding:
    file: str
    line: int
    kind: str             # tool | param | verb | flag | term
    text: str             # the stale text as written
    problem: str          # what is wrong
    exists: str           # what exists instead
    verb: str = ""        # a sala finding: the verb (not an `op` verb), and the flag, for the help-gap check against sala's code
    flag: str = ""

    @property
    def key(self) -> str:
        """What "the same finding" means across runs: the file's own text of it, not its line (an edit above moves the line)."""
        return f"{self.kind}|{self.text}|{self.problem}"


# ======================================================================== settings

def settings() -> dict[str, Any]:
    """[rulebook_scan] from the instance config, defaults filled in."""
    c = _cfg.get("rulebook_scan") or {}
    files = [f for f in (c.get("files") or []) if isinstance(f, dict) and str(f.get("glob") or "").strip()]      # no table: no files, nothing is scanned (scan_all says so)
    keeper = str(c.get("keeper") or "").strip() or KEEPER
    terms = str(c.get("terms") or "").strip() or "tests/retired_terms.toml"
    server = str(c.get("server") or "").strip() or "stackshot/web/server.py"
    if server == "server.py":      # an instance config written before the package: server.py at the root only forwards, the tools are defined in the package's server
        server = "stackshot/web/server.py"
    hv = c.get("help_verbs")
    return {
        "enabled": c.get("enabled") is True or str(c.get("enabled")).strip().lower() in ("true", "1", "yes"),
        "files": [{"glob": str(f["glob"]).strip(), "keeper": str(f.get("keeper") or keeper).strip()} for f in files],
        "terms": _rel(terms), "server": _rel(server),
        "sala": str(c.get("sala") or "").strip() or "sala",
        "help_verbs": [str(v) for v in hv] if isinstance(hv, list) else DEFAULT_HELP_VERBS,
        "sender": str(c.get("sender") or "").strip() or SENDER,
        "sala_lib": Path(os.path.expanduser(str(c.get("sala_lib") or "").strip() or SALA_LIB)),
        "sala_keeper": str(c.get("sala_keeper") or "").strip() or SALA_KEEPER,
    }


def _rel(p: str) -> Path:
    q = Path(os.path.expanduser(p))
    return q if q.is_absolute() else CHECKOUT / q


def state_file() -> Path:
    return _cfg.state("rulebook-scan") / "sent.json"          # the directory is made only when the state is written (a dry run makes nothing)


# ======================================================================== what exists

def _tool_registrations(tree: ast.AST) -> dict[str, list[str]]:
    """{tool name: [parameter names]} for the tools one module registers: `@mcp.tool(name="…")` on a function, or `mcp.tool(name="…")(function)` with the function defined in the module."""
    defs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def is_tool(fn: ast.AST) -> bool:
        return isinstance(fn, ast.Attribute) and fn.attr == "tool" and isinstance(fn.value, ast.Name) and fn.value.id == "mcp"

    def named(call: ast.AST, default: str) -> str:
        if isinstance(call, ast.Call):
            for kw in call.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    return kw.value.value
        return default

    def params(node: ast.AST) -> list[str]:
        a = node.args
        return [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs) if x.arg not in ("self", "cls")]

    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if is_tool(dec.func if isinstance(dec, ast.Call) else dec):
                    out[named(dec, node.name)] = params(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Call) and is_tool(node.func.func):
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in defs:
                    out[named(node.func, arg.id)] = params(defs[arg.id])
    return out


def server_tools(server_py: Path) -> dict[str, list[str]]:
    """{tool name: [parameter names]} from the tool definitions in the server's source: the file itself and the modules of the `tools/` folder beside it (web/tools/), where each tool is registered."""
    server_py = Path(server_py)
    files = [server_py, *sorted((server_py.parent / "tools").glob("*.py"))]
    out: dict[str, list[str]] = {}
    for f in files:
        out.update(_tool_registrations(ast.parse(f.read_text(encoding="utf-8"))))
    return out


FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
END_OF_FLAGS = re.compile(r"(?<!\S)--(?!\S)")
SALA_LINE = re.compile(r"^\s{0,4}(?:salamander|sala)\s+([a-z][a-z-]*)\b")


@dataclass
class SalaHelp:
    verbs: dict[str, set[str]] = field(default_factory=dict)       # verb → every flag the help lists under it
    op_general: set[str] = field(default_factory=set)              # flags of `op` itself (--from, --words, --plan, --list …)
    op_verbs: dict[str, set[str]] = field(default_factory=dict)    # `op`'s verbs → their flags, from `sala op --help` (empty when not read)
    op_flags_any: set[str] = field(default_factory=set)            # every flag the main help's op section lists (the fallback)


def parse_help(main: str, op_help: str = "") -> SalaHelp:
    """`sala --help` is a list of lines that open with `salamander <verb>` and continue on deeper-indented lines; the flags of a
    line and its continuations belong to that verb. `sala op --help` has the op's own flags, then a `verbs:` block."""
    h = SalaHelp()
    cur = ""
    for line in main.splitlines():
        m = SALA_LINE.match(line)
        if m:
            cur = m.group(1)
            h.verbs.setdefault(cur, set())
        if cur:
            h.verbs[cur] |= set(FLAG.findall(line))
        # a verb's flag quoted inside another section (`sala reboot --go`, `sala op recycle --force …`) counts for that verb
        for q in re.finditer(r"`(?:salamander|sala)\s+([a-z][a-z-]*)([^`]*)`", line):
            if q.group(1) in h.verbs:
                h.verbs[q.group(1)] |= set(FLAG.findall(q.group(2)))
    h.op_flags_any = set(h.verbs.get("op", set()))
    h.op_general = set(h.op_flags_any)
    if op_help.strip():
        h.op_general = set()
        in_verbs, sub = False, ""
        for line in op_help.splitlines():
            if line.strip() == "verbs:":
                in_verbs = True
                continue
            if not in_verbs:
                h.op_general |= set(FLAG.findall(line))
                continue
            m = re.match(r"^  ([a-z][a-z-]*)\b", line)
            if m:
                sub = m.group(1)
                h.op_verbs.setdefault(sub, set())
            if sub:
                h.op_verbs[sub] |= set(FLAG.findall(line))
        h.verbs.setdefault("op", set()).update(h.op_general)
        for f in h.op_verbs.values():
            h.verbs["op"] |= f
    return h


def run_help(sala: str, verb: str = "") -> str:
    """`sala --help` or `sala <verb> --help` (for a verb in [rulebook_scan] help_verbs only): the help text, "" when it cannot be read."""
    try:
        r = subprocess.run([sala, *([verb] if verb else []), "--help"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        print(f"rulebook_scan: {sala} {verb} --help not read: {e}", file=sys.stderr)
        return ""


# ======================================================================== the retired terms

TERM_KEYS = ("pattern", "regex", "text", "term", "word", "phrase")
USE_KEYS = ("use", "instead", "say", "replace", "replacement", "now", "note", "reason")


def load_terms(path: Path) -> list[tuple[re.Pattern, str, str]]:
    """The retired-terms file → [(compiled pattern, the term as written, what to say instead)]; [] when the file is absent. Read
    tolerantly: every array of tables whose name is term(s), retired or words, and a plain list of strings under one of those names.
    `pattern`/`regex` is a regular expression; `text`/`term`/`word`/`phrase` a literal, matched whole-word and without case when
    `ignore_case` is not false."""
    p = Path(path)
    if not p.is_file():
        return []
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    rows: list[Any] = []
    for name in ("term", "terms", "retired", "words"):
        v = data.get(name)
        if isinstance(v, list):
            rows += v
        elif isinstance(v, dict):
            rows += [dict(t, text=k) if isinstance(t, dict) else {"text": k, "use": str(t)} for k, t in v.items()]
    out = []
    for r in rows:
        if isinstance(r, str):
            r = {"text": r}
        if not isinstance(r, dict):
            continue
        key = next((k for k in TERM_KEYS if r.get(k)), "")
        if not key:
            continue
        raw = str(r[key])
        flags = re.I if r.get("ignore_case", True) is not False else 0
        try:
            rx = re.compile(raw if key in ("pattern", "regex") else rf"(?<![\w-]){re.escape(raw)}(?![\w-])", flags)
        except re.error:
            continue
        out.append((rx, raw, next((str(r[k]) for k in USE_KEYS if r.get(k)), "")))
    return out


# ======================================================================== reading a file

FENCE = re.compile(r"^\s*(```|~~~)")
SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
TOOL = re.compile(r"(?<![\w.\-/])(?P<pre>(?:mcp__[\w-]*?stackshot[\w-]*__|codemode\.[\w-]*?stackshot[\w-]*?_|stackshot_)?)(?P<tool>[a-z][a-z_]*)(?P<after>\(|,\s)")
SALA = re.compile(r"(?<![\w-])(?:salamander|sala)\s+(?P<verb>[a-z][a-z-]*)\b(?P<rest>[^`|;&\n]*)")
PARAM_EQ = re.compile(r"(?<![\w.\"'-])([a-z_][a-z0-9_]*)\s*=(?!=)")
PARAM_KEY = re.compile(r"""(?<![\w.-])["']?([a-z_][a-z0-9_]*)["']?\s*:(?!:)""")


def regions(text: str) -> list[tuple[int, str]]:
    """The code of a file as (line number, text) pieces: each inline `span`, and each logical line of a fenced block (a trailing
    backslash joins the next line; a call whose parentheses are still open at the end of its line takes the next ones, at most 12)."""
    out: list[tuple[int, str]] = []
    lines = text.split("\n")
    fenced = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if FENCE.match(ln):
            fenced = not fenced
            i += 1
            continue
        if not fenced:
            out += [(i + 1, m.group(1)) for m in SPAN.finditer(ln)]
            i += 1
            continue
        start, buf = i, ln
        while (buf.rstrip().endswith("\\") or buf.count("(") > buf.count(")")) and i + 1 < len(lines) and i - start < 12 and not FENCE.match(lines[i + 1]):
            i += 1
            buf = buf.rstrip().rstrip("\\") + " " + lines[i].strip()
        out.append((start + 1, buf.strip()))
        i += 1
    return out


def _call_args(s: str, at: int) -> str:
    """The text of a call's arguments: from `at` (just after the opening parenthesis) to its matching one, or the end."""
    depth, q = 1, ""
    for j in range(at, len(s)):
        c = s[j]
        if q:
            q = "" if c == q else q
            continue
        if c in "\"'":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return s[at:j]
    return s[at:]


def _top_params(args: str) -> list[str]:
    """The names given at the top level of a call's arguments: `name=value`, and the keys of a single object argument (`{name: value}`,
    `{"name": value}`: the codemode form). Values (strings, nested calls and objects, <placeholders>) are not read."""
    out: list[str] = []
    depth, i, n = 0, 0, len(args)
    obj = 1 if args.lstrip().startswith("{") else 0
    while i < n:
        c = args[i]
        if c in "\"'":
            j = i + 1
            while j < n and args[j] != c:
                j += 2 if args[j] == "\\" else 1
            word, i = args[i + 1:j], j + 1
            if obj and depth == obj and args[i:].lstrip().startswith(":") and re.fullmatch(r"[a-z_][a-z0-9_]*", word):
                out.append(word)
            continue
        if c == "<":
            m = re.match(r"<[^<>\n]{1,60}>", args[i:])
            if m:
                i += m.end()
                continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == obj and (c.isalpha() or c == "_") and (i == 0 or not re.match(r"[\w.-]", args[i - 1])):
            m = re.match(r"([a-z_][a-z0-9_]*)\s*(=(?!=)|:(?!:))", args[i:])
            if m and (m.group(2) == "=" or obj):
                out.append(m.group(1))
                i += m.end()
                continue
            i += re.match(r"[\w.-]+", args[i:]).end()
            continue
        i += 1
    return list(dict.fromkeys(out))


def check_tools(path: str, ln: int, s: str, tools: dict[str, list[str]]) -> list[Finding]:
    out = []
    if not tools:
        return out
    for m in TOOL.finditer(s):
        pre, tool, after = m.group("pre"), m.group("tool"), m.group("after")
        known = tool in tools
        if pre and not known and after == "(":
            near = difflib.get_close_matches(tool, list(tools), n=2, cutoff=0.6)
            out.append(Finding(path, ln, "tool", f"{pre}{tool}(", f"stackshot has no tool {tool!r}",
                               "tools: " + ", ".join(sorted(tools)) + (f" (near: {', '.join(near)})" if near else "")))
            continue
        if not known:
            continue
        args = _call_args(s, m.end()) if after == "(" else s[m.end():]
        if after != "(" and pre:
            continue
        for p in _top_params(args):
            if p not in tools[tool]:
                out.append(Finding(path, ln, "param", f"{pre}{tool}(…{p}=…)" if after == "(" else f"{tool}, …{p}=…",
                                   f"the {tool} tool takes no parameter {p!r}", f"{tool} takes: " + ", ".join(tools[tool])))
    return out


def check_sala(path: str, ln: int, s: str, h: SalaHelp) -> list[Finding]:
    out = []
    for m in SALA.finditer(s):
        verb, rest = m.group("verb"), m.group("rest")
        rest = END_OF_FLAGS.split(rest, 1)[0]             # after a bare `--` come the wrapped command's own arguments (sala passes them through): no sala flag
        flags = list(dict.fromkeys(FLAG.findall(rest)))
        at_start = bool(re.fullmatch(r"\s*(\$\s*)?((sudo|ssh \S+|env \S+=\S+)\s+)*(\S*/)?", s[:m.start()]))
        text = f"sala {verb}{(' ' + ' '.join(flags)) if flags else ''}"
        if verb not in h.verbs:
            if at_start or flags:
                out.append(Finding(path, ln, "verb", text, f"sala has no verb {verb!r}", "verbs: " + ", ".join(sorted(h.verbs)), verb=verb))
            continue
        if verb == "op":
            sub = (rest.split() or [""])[0]
            if h.op_verbs and re.fullmatch(r"[a-z][a-z-]*", sub) and sub not in h.op_verbs:
                out.append(Finding(path, ln, "verb", f"sala op {sub}", f"sala op has no verb {sub!r}", "op verbs: " + ", ".join(sorted(h.op_verbs))))
                continue
            named = sub in h.op_verbs
            for f in flags:
                ok = (f in h.op_general or f in h.op_verbs.get(sub, set()) or (not named and f in h.op_flags_any)
                      or (not named and any(f in v for v in h.op_verbs.values())))
                if not ok:
                    out.append(Finding(path, ln, "flag", f"sala op {sub} {f}".replace("  ", " "), f"sala op {sub} lists no flag {f}".replace("  ", " "),
                                       f"flags: {', '.join(sorted(h.op_general | h.op_verbs.get(sub, set()))) or '(none)'}", verb="op", flag=f))
            continue
        for f in flags:
            if f not in h.verbs[verb]:
                out.append(Finding(path, ln, "flag", f"sala {verb} {f}", f"sala {verb} lists no flag {f}",
                                   f"flags: {', '.join(sorted(h.verbs[verb])) or '(none)'}", verb=verb, flag=f))
    return out


def check_terms(path: str, text: str, terms: list[tuple[re.Pattern, str, str]]) -> list[Finding]:
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        for rx, raw, use in terms:
            m = rx.search(line)
            if m:
                out.append(Finding(path, n, "term", line.strip(), f"retired term {m.group(0)!r}", use or "(see the retired-terms list)"))
    return out


def scan_text(path: str, text: str, tools: dict[str, list[str]], sala: SalaHelp, terms: list[tuple[re.Pattern, str, str]] | None = None) -> list[Finding]:
    out: list[Finding] = []
    for ln, s in regions(text):
        out += check_tools(path, ln, s, tools)
        out += check_sala(path, ln, s, sala)
    out += check_terms(path, text, terms or [])
    seen, uniq = set(), []
    for f in out:
        k = (f.line, f.key)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


# ======================================================================== the run

def collect(files: list[dict[str, str]]) -> list[tuple[Path, str]]:
    """[(file, keeper)] from the globs, each file once (the first table that names it), sorted."""
    seen: dict[Path, str] = {}
    for f in files:
        for p in sorted(glob.glob(os.path.expanduser(f["glob"]), recursive=True)):
            q = Path(p)
            if q.is_file() and q not in seen and not q.name.endswith((".bak", "~")):
                seen[q] = f["keeper"]
    return sorted(seen.items())


def scan_all(cfg: dict[str, Any], *, schema: Path | None = None, help_main: Path | None = None, help_op: Path | None = None,
             terms: Path | None = None) -> tuple[dict[str, list[Finding]], dict[str, str], list[str], bool]:
    """→ ({file: findings}, {file: keeper}, the lines of what could not be read, which the caller prints and never turns into a finding,
    whether sala's help was read: False when `sala --help`, or `sala op --help` where it is asked for, came back empty)."""
    notes: list[str] = []
    if not cfg["files"]:
        return {}, {}, [NO_FILES_NOTE], True
    if schema:
        tools = {k: list(v) for k, v in json.loads(Path(schema).read_text(encoding="utf-8")).items()}
    else:
        tools = server_tools(cfg["server"])
    main_help = Path(help_main).read_text(encoding="utf-8") if help_main else run_help(cfg["sala"])
    op_help = Path(help_op).read_text(encoding="utf-8") if help_op else (run_help(cfg["sala"], "op") if "op" in cfg["help_verbs"] else "")
    op_asked = not help_op and "op" in cfg["help_verbs"]
    help_ok = bool(main_help.strip()) and (not op_asked or bool(op_help.strip()))
    if not main_help.strip():
        notes.append("sala --help gave nothing: the sala verbs and flags were not checked")
    elif not help_ok:
        notes.append("sala op --help gave nothing: the sala verbs and flags were not checked")
        main_help = ""
    sala = parse_help(main_help, op_help)
    tp = Path(terms) if terms else cfg["terms"]
    tl = load_terms(tp)
    if not tp.is_file():
        notes.append(f"no retired-terms file at {tp}: that check was skipped")
    found: dict[str, list[Finding]] = {}
    keepers: dict[str, str] = {}
    for p, keeper in collect(cfg["files"]):
        keepers[str(p)] = keeper
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{p}: not read: {e}")
            continue
        fs = scan_text(str(p), text, tools, sala if main_help.strip() else SalaHelp(), tl)
        if not main_help.strip():
            fs = [f for f in fs if f.kind not in ("verb", "flag")]
        if fs:
            found[str(p)] = fs
    return found, keepers, notes, help_ok


def code_takes(f: Finding, lib: Path) -> bool:
    """A sala finding whose verb has lib/<verb>.sh in sala's code that takes the flag (or, for a verb, exists): the mention is right and sala's
    help is behind."""
    if not f.verb:
        return False
    p = Path(lib) / f"{f.verb}.sh"
    if not p.is_file():
        return False
    if f.kind == "verb":
        return True
    try:
        return re.search(rf"(?<![\w-]){re.escape(f.flag)}(?![\w-])", p.read_text(encoding="utf-8")) is not None
    except Exception:  # noqa: BLE001
        return False


def _short(s: str, n: int = LINE_CAP) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def note_text(path: str, fresh: list[Finding], older: int, today: str, gap: bool = False, sala_keeper: str = SALA_KEEPER) -> str:
    more = f" ({older} earlier finding" + ("s" if older != 1 else "") + " still open, sent before)" if older else ""
    if gap:
        head = (f"[stackshot] Rulebook scan ({today}): {path} names a sala verb or flag that sala's code takes but `sala --help` does not list, "
                f"so the mention is right and sala's help text is behind (each found in ~/salamander/lib/<verb>.sh){more}. The fix is sala's help text. "
                "Each line: line · the text as written · what the help lists.")
    else:
        head = (f"[stackshot] Rulebook scan ({today}): {path} names a stackshot tool, a sala command or a retired term that no longer exists. "
                f"Please fix the text{more}. Each line: line · the text as written · what is wrong · what exists.")
        if any(f.kind in ("verb", "flag") for f in fresh):
            head += (" For a sala verb or flag the reference is sala's help text, which can be behind the code: the mention may be right. Before editing "
                     f"this file, check ~/salamander/lib/<verb>.sh; if the code takes it, the fix is sala's help text (keeper {sala_keeper}), not this file.")
    body, used = [], len(head)
    for i, f in enumerate(fresh):
        row = f"L{f.line} · {_short(f.text)} · {f.problem} · {_short(f.exists, 220)}"
        if used + len(row) + 1 > NOTE_MAX:
            body.append(f"… and {len(fresh) - i} more in the file (run `audit.py scan --dry-run`)")
            break
        body.append(row)
        used += len(row) + 1
    return head + "\n" + "\n".join(body)


def _local_date(d) -> str:
    """The date as the owner reads it (weekday, month, day with an ordinal), in the instance timezone."""
    n = d.day
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{d:%a %b} {n}{suf}"


Deliver = Callable[[str, str, str], tuple[bool, str]]


def deliver_client(to: str, text: str, sender: str) -> tuple[bool, str]:
    """One message to the keeper through client.py (this box's token). → (delivered, the server's answer)."""
    from stackshot.fleet import client as _client  # noqa: PLC0415 — only a real send needs it
    status, said = _client.message(to, text, sender)
    return status == 200, f"[{status}] {said}"


def run(cfg: dict[str, Any] | None = None, *, dry: bool = False, deliver: Deliver = deliver_client, state: Path | None = None, today: str = "",
        **sources: Path | None) -> dict[str, Any]:
    """Scan, group per file, send the new findings of each file to its keeper once (a sala flag or verb that sala's code takes goes, as one more
    note of that file, to sala's keeper as a help-text gap). The first delivery that fails ends the sending: the rest hold for the next night.
    → {"files": n, "findings": n, "sent": [file…], "held": [file…] (not delivered), "quiet": [file…] (nothing new), "notes": [...]}."""
    cfg = cfg or settings()
    found, keepers, notes, help_ok = scan_all(cfg, **sources)
    sf = state or state_file()
    try:
        sent: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
    except Exception:  # noqa: BLE001
        sent = {}
    import datetime as dt  # noqa: PLC0415
    today = today or _local_date(dt.datetime.now(_cfg.tz()))
    lib, sala_keeper = cfg.get("sala_lib") or Path(os.path.expanduser(SALA_LIB)), cfg.get("sala_keeper") or SALA_KEEPER
    res: dict[str, Any] = {"files": len(keepers), "findings": sum(len(v) for v in found.values()), "sent": [], "held": [], "quiet": [], "notes": notes,
                           "found": found, "gap": {path: [f.key for f in fs if code_takes(f, lib)] for path, fs in found.items()}, "gap_to": sala_keeper}
    nstate: dict[str, Any] = {}          # a file with nothing left forgets what it sent
    stopped = False
    for path, fs in found.items():
        gap = [f for f in fs if code_takes(f, lib)]
        groups = [(path, keepers[path], [f for f in fs if f not in gap], False)]
        if gap:
            groups.append((f"{path}#help-gap", sala_keeper, gap, True))
        for sk, to, gfs, is_gap in groups:
            if not gfs:
                continue
            before = set(sent.get(sk, {}).get("keys", []))
            fresh = [f for f in gfs if f.key not in before]
            keys = sorted({f.key for f in gfs})
            if not fresh:
                nstate[sk] = {"keys": keys, "sent": sent.get(sk, {}).get("sent", "")}
                res["quiet"].append(path)
                continue
            if dry:
                res["sent"].append(path)
                continue
            if stopped:
                res["held"].append(path)
                nstate[sk] = {"keys": sorted(before), "sent": sent.get(sk, {}).get("sent", "")}
                continue
            ok, said = deliver(to, note_text(path, fresh, len(gfs) - len(fresh), today, is_gap, sala_keeper), cfg["sender"])
            if ok:
                res["sent"].append(path)
                nstate[sk] = {"keys": keys, "sent": today, "to": to, "digest": hashlib.sha1("\n".join(keys).encode()).hexdigest()[:12]}
            else:
                stopped = True
                res["held"].append(path)
                notes.append(f"{path}: not delivered to {to}: {said}; the rest of tonight's notes are held for the next night")
                nstate[sk] = {"keys": sorted(before), "sent": sent.get(sk, {}).get("sent", "")}      # the new ones go again tomorrow
    if not help_ok:          # sala's help was unreadable tonight: its verb and flag findings are neither judged nor forgotten, so a good night does not resend them
        for sk, v in sent.items():
            ks = [k for k in v.get("keys", []) if k.startswith(("verb|", "flag|"))]
            if ks:
                e = nstate.setdefault(sk, {"keys": [], "sent": v.get("sent", "")})
                e["keys"] = sorted(set(e["keys"]) | set(ks))
    if not dry:
        sf.parent.mkdir(parents=True, exist_ok=True)
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(nstate, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, sf)
    return res


def report(res: dict[str, Any], dry: bool) -> str:
    out = [f"rulebook scan: {res['files']} files, {res['findings']} findings"
           + ("" if not dry else " (dry run: nothing sent, nothing recorded)")]
    for path, fs in res["found"].items():
        out.append(path)
        gap = set(res.get("gap", {}).get(path, []))      # sala's code takes it: a real run sends it to sala's keeper as a help-text gap, not to the file's keeper
        out += [f"  L{f.line} · {_short(f.text, 140)} · {f.problem} · {_short(f.exists, 160)}" + (f" (help-text gap → {res.get('gap_to') or SALA_KEEPER})" if f.key in gap else "")
                for f in fs]
    if not dry:
        out.append(f"sent: {len(res['sent'])} · already sent, unchanged: {len(res['quiet'])} · not delivered: {len(res['held'])}")
    out += [f"note: {n}" for n in res["notes"]]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    a = list(argv)
    if a and a[0] == "run":
        a = a[1:]
    dry = "--dry-run" in a
    a = [x for x in a if x != "--dry-run"]
    opt: dict[str, Path] = {}
    names = {"--terms": "terms", "--schema": "schema", "--sala-help": "help_main", "--op-help": "help_op"}
    while a:
        k = a.pop(0)
        if k not in names or not a:
            print("usage: rulebook_scan.py run [--dry-run] [--terms PATH] [--schema JSON] [--sala-help FILE] [--op-help FILE]", file=sys.stderr)
            return 2
        opt[names[k]] = Path(a.pop(0))
    cfg = settings()
    if not dry and not cfg["enabled"]:
        print("rulebook scan: not enabled on this instance ([rulebook_scan] enabled); --dry-run reads and prints without sending")
        return 0
    res = run(cfg, dry=dry, **opt)
    print(report(res, dry))
    return 1 if res["held"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
