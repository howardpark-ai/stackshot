#!/usr/bin/env python3
"""tools/tool_text.py — the tool-text gates (the owner's rule: a tool's text changes in the same release as the tool).

What a session learns a stackshot tool from is its name, its parameters, its description and the fixed labels of the lines it returns. This file keeps
that text in one committed snapshot, tests/tool_text.snapshot.json, and holds three gates over it:

    python3 tools/tool_text.py dump                    print the live text (what the server registers, as a snapshot)
    python3 tools/tool_text.py check                   exit 1, with a readable diff, when the live text differs from the snapshot
    python3 tools/tool_text.py update                  write the snapshot from the live text (the refresh command; commit the result)
    python3 tools/tool_text.py touched --base SHA --head SHA [--body-file F]
                                                       exit 1 when a tool function or an output helper has a changed body between the two commits
                                                       while the snapshot is unchanged, unless the PR body has a line `tool-text: unchanged: <reason>`
    python3 tools/tool_text.py summary [--base REV]    the line the brief will carry for the change from REV (default origin/main) to the working copy
    python3 tools/tool_text.py record                  the server's own release mark by hand (whatschanged.record): normally the server's start does it

The snapshot (a JSON, sorted keys, whitespace normalised): for the connector its `instructions` and its resources; for every tool the server registers its
`description` as served, its `parameters` (type, required, default, description, by name), and, for get, brief, create, update, message and complete,
the `labels` of the lines it returns.

HOW THE LABELS ARE TAKEN (the most robust method, and what it does not do). A label is the fixed prefix of a returned line, `mover:` or `then:`.
They are read from the SOURCE of the output helpers (HELPERS below, function by function) with an AST scan, not by rendering fixture items: a rendered
item only shows the lines its fields reach, so a label behind a rarely true condition (`wait failed:`, `undelivered notices:`) would go unseen until an
item with that field was a fixture, while the scan sees every branch the code has. What counts as a label: the text a string literal or an f-string
STARTS with (and each line start inside a literal with newlines; a literal inside an f-string's {placeholder} is the middle of a line), when it is one to four lowercase words ending in a colon followed by a space, a newline or
the end (so `mover: {who}` and `"next:\\n" + …` count, a sentence does not). A format `f"{k}: …"` over a loop variable expands to the loop's string
constants (`for k in ("project", "needs", …)`), except one an enclosing `x if k == "owner" else f"{k}: …"` takes out. Never counted: docstrings, a print to
stderr, a `raise` (the refusals are prose, not lines), and a label the code builds at run time (`f"{e['tag']}: …"`). A line whose label is new or gone changes the
snapshot; one whose label is dynamic cannot, which is the method's one blind spot: its words are still read by the retired-terms lint (tests/retired_terms.toml).

The live text is read from an in-process import of server.py on a throwaway config made from stackshot.example.toml, so it is the code's own text, the
same on every machine, whatever the instance's config says; it never touches a store. dump, check and update need fastmcp: run bare, the file re-executes
itself through the tests' uv environment (tests/run-suite's), so `python3 tools/tool_text.py update` works on a checkout with uv and nothing else.
`touched`, `summary` and `record` are stdlib only."""
from __future__ import annotations

import argparse
import ast
import asyncio
import difflib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_REL = "tests/tool_text.snapshot.json"
SNAPSHOT = ROOT / SNAPSHOT_REL
FORMAT = 1
REFRESH = "python3 tools/tool_text.py update"
LABELLED = ("get", "brief", "create", "update", "message", "complete")     # the tools whose returned lines have labels in the snapshot

SERVER_REL = "stackshot/web/server.py"
# The tools are registered in these modules (each `register` adds its own with `mcp.tool(...)(function)`); until the server was split a revision has them in server.py,
# which stays watched for that reason.
TOOL_FILES = tuple(f"stackshot/web/tools/{m}.py" for m in ("brief", "get", "create", "update", "complete", "sessions", "message", "route", "anchors", "rules"))
# Where each watched file stood before the code moved into the package (Sun Nov 8th 2026): a base revision from before the move has the file there, so the move itself is not a change of every watched function.
_BEFORE_PACKAGE = {
    "stackshot/model/model.py": "model.py",
    "stackshot/model/model_guards.py": "model_guards.py",
    "stackshot/model/states.py": "states.py",
    "stackshot/model/work.py": "work.py",
    "stackshot/waits/handoff.py": "handoff.py",
    "stackshot/waits/waiting.py": "waiting.py",
    "stackshot/waits/watchers.py": "watchers.py",
    "stackshot/web/server.py": "server.py",
    "stackshot/web/whatschanged.py": "whatschanged.py",
}


def show_at(root: Path, rev: str, rel: str) -> str | None:
    """The text of `rel` at `rev`; at a revision from before the package move, of the file it was then."""
    got = git(root, "show", f"{rev}:{rel}")
    if got is None and rel in _BEFORE_PACKAGE:
        got = git(root, "show", f"{rev}:{_BEFORE_PACKAGE[rel]}")
    return got


# The output helpers: the functions the lines a tool returns come from, (file, function name) by tool. The labels of a tool are the labels found in its helpers; the
# `touched` gate watches every one of them (and every function registered with @mcp.tool, found by itself) for a changed body. A new helper that builds a returned line
# goes in here, in the same PR: this is the one list.
_ITEM_LINES = [   # the item as get shows it, which create, update and complete return after their own first line, and the brief returns one per open item
    ("stackshot/web/server.py", "_fmt"), ("stackshot/web/server.py", "_mover_lines"), ("stackshot/web/server.py", "_model_lines"), ("stackshot/web/server.py", "_handoff_lines"),
    ("stackshot/web/server.py", "_state_check_notes"), ("stackshot/web/server.py", "_next_names_lines"), ("stackshot/web/server.py", "_check_words"), ("stackshot/web/answers.py", "_answer_words"), ("stackshot/web/page_debts.py", "_nag"),
    ("stackshot/model/states.py", "words"), ("stackshot/model/states.py", "carry_of"), ("stackshot/model/model.py", "words"), ("stackshot/waits/handoff.py", "words"), ("stackshot/waits/watchers.py", "woke_line"),
    ("stackshot/waits/watchers.py", "chases_line"), ("stackshot/model/work.py", "words"),
]
_WRITE_NOTES = [   # the notes a create or an update reply ends with
    ("stackshot/web/server.py", "_form_notes"), ("stackshot/web/server.py", "_said_note"), ("stackshot/web/decision_gates.py", "_options_note"), ("stackshot/web/tools/notes.py", "_owner_param"),
    ("stackshot/web/server.py", "_owner_then_default"),
]
_GET_ONLY = [("stackshot/web/tools/get.py", "stackshot_get"), ("stackshot/web/server.py", "_notice_report")]     # lines only get returns: a notice's ruling (get with a notice id)
HELPERS: dict[str, list[tuple[str, str]]] = {
    "get": _GET_ONLY + _ITEM_LINES,
    "brief": [("stackshot/web/tools/brief.py", "stackshot_brief"), ("stackshot/web/server.py", "_model_report_line"), ("stackshot/web/tools/brief.py", "_world_waits_text"),
              ("stackshot/web/server.py", "_handoff_brief"), ("stackshot/web/whatschanged.py", "lines"), ("stackshot/model/model_guards.py", "brief_line"), ("stackshot/waits/handoff.py", "brief_lines")] + _ITEM_LINES,
    "create": [("stackshot/web/tools/create.py", "stackshot_create"), ("stackshot/web/tools/create.py", "_create"), ("stackshot/service/create.py", "create_item"), ("stackshot/web/similar.py", "_similar_note")] + _WRITE_NOTES + _ITEM_LINES,
    "update": [("stackshot/web/tools/update.py", "stackshot_update"), ("stackshot/service/update.py", "update_item"), ("stackshot/service/update.py", "update_unlocked"), ("stackshot/web/server.py", "_report_note"),
               ("stackshot/web/server.py", "_command_note"), ("stackshot/web/server.py", "_watch_on_write"), ("stackshot/service/telling.py", "mentions_reply")] + _WRITE_NOTES + _ITEM_LINES,
    "message": [("stackshot/web/tools/message.py", "stackshot_message"), ("stackshot/web/server.py", "_message")],
    "confirm": [("stackshot/web/tools/complete.py", "stackshot_confirm"), ("stackshot/service/update.py", "confirm_item")],      # not labelled in the snapshot (its reply has no label), but watched: the gate sees a changed body
    "complete": [("stackshot/web/tools/complete.py", "stackshot_complete"), ("stackshot/service/update.py", "complete_item"), ("stackshot/service/update.py", "_completion_anchor_prompt"), ("stackshot/service/update.py", "update_item"), ("stackshot/service/update.py", "update_unlocked"), ("stackshot/service/telling.py", "mentions_reply")]
                + _WRITE_NOTES + _ITEM_LINES,
}
ALL_HELPERS = sorted({h for hs in HELPERS.values() for h in hs})

LABEL = re.compile(r"([a-z][a-z']*(?: [a-z][a-z']*){0,3}):(?=[ \n]|$)")     # one to four lowercase words


# ---------------------------------------------------------------- the labels (AST scan of the output helpers)
def functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    out: dict[str, Any] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(n.name, n)
    return out


def _parents(fn: ast.AST) -> dict[int, ast.AST]:
    return {id(c): p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}


def _loop_values(node: ast.AST, var: str, parents: dict[int, ast.AST]) -> list[str]:
    """The string constants `var` runs over where `node` stands in the body of `for var in ("a", "b", …)`; [] when the nearest binding of the name is anything else
    (a comprehension's own `k`, a loop over something computed)."""
    child, p = node, parents.get(id(node))
    while p is not None:
        if isinstance(p, ast.For) and child in p.body and isinstance(p.target, ast.Name) and p.target.id == var:
            it = p.iter
            if isinstance(it, (ast.Tuple, ast.List)) and it.elts and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in it.elts):
                return [e.value for e in it.elts]    # type: ignore[attr-defined]
            return []
        if isinstance(p, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)) and any(var in {x.id for x in ast.walk(g.target) if isinstance(x, ast.Name)} for g in p.generators):
            return []
        child, p = p, parents.get(id(p))
    return []


def _taken_out(node: ast.AST, var: str, parents: dict[int, ast.AST]) -> set[str]:
    """The constants an enclosing `<x> if var == "c" else <node>` keeps out of the expansion of `var`: the helper words that case differently."""
    out: set[str] = set()
    child, p = node, parents.get(id(node))
    while p is not None:
        if isinstance(p, ast.IfExp) and p.orelse is child and isinstance(p.test, ast.Compare) and isinstance(p.test.left, ast.Name) and p.test.left.id == var \
                and len(p.test.ops) == 1 and isinstance(p.test.ops[0], ast.Eq) and isinstance(p.test.comparators[0], ast.Constant):
            out.add(str(p.test.comparators[0].value))
        child, p = p, parents.get(id(p))
    return out


def labels_of(fn: ast.AST) -> set[str]:
    """The labels of the lines a function builds (see the module docstring for what counts)."""
    parents = _parents(fn)
    skip: set[int] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            skip.add(id(n.value))                                    # a docstring or a string statement
        if isinstance(n, ast.Raise) or (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" and any(k.arg == "file" for k in n.keywords)):
            skip.update(id(c) for c in ast.walk(n))                  # a refusal is prose; a log line to stderr is not returned
    in_f = {id(c) for n in ast.walk(fn) if isinstance(n, ast.JoinedStr) for c in n.values}
    for n in ast.walk(fn):
        if isinstance(n, ast.FormattedValue):
            skip.update(id(c) for c in ast.walk(n))                  # inside a {placeholder} of an f-string a literal is the middle of a line
    found: set[str] = set()

    def take(text: str) -> None:
        for line in text.split("\n"):
            m = LABEL.match(line)
            if m:
                found.add(m.group(1) + ":")

    for n in ast.walk(fn):
        if id(n) in skip:
            continue
        if isinstance(n, ast.JoinedStr) and n.values:
            first = n.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                take(first.value)
            elif isinstance(first, ast.FormattedValue) and isinstance(first.value, ast.Name) and len(n.values) > 1 \
                    and isinstance(n.values[1], ast.Constant) and str(n.values[1].value).startswith(":"):
                gone = _taken_out(n, first.value.id, parents)
                found.update(f"{v}:" for v in _loop_values(n, first.value.id, parents) if v not in gone)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in in_f:
            take(n.value)
    return found


def get_only_labels(root: Path = ROOT) -> set[str]:
    """The labels only get returns (create, update and complete return the item's lines, not these): a notice's
    lines, less every label an item line also has (`project:`, `reason:`), which create, update and complete must keep returning."""
    files = {f for f, _n in _GET_ONLY + _ITEM_LINES}
    tree = {f: functions(ast.parse((root / f).read_text(encoding="utf-8"))) for f in files}
    own = set().union(*(labels_of(tree[f][n]) for f, n in _GET_ONLY))
    return own - set().union(*(labels_of(tree[f][n]) for f, n in _ITEM_LINES))


def labels_by_tool(root: Path = ROOT) -> dict[str, list[str]]:
    trees: dict[str, dict[str, Any]] = {}
    out: dict[str, list[str]] = {}
    for tool, helpers in HELPERS.items():
        labs: set[str] = set()
        for file, name in helpers:
            if file not in trees:
                trees[file] = functions(ast.parse((root / file).read_text(encoding="utf-8")))
            if name not in trees[file]:
                raise SystemExit(f"tool_text: output helper {file}:{name} (listed in HELPERS, tools/tool_text.py) is not defined: a renamed or removed helper is a line in that list")
            labs |= labels_of(trees[file][name])
        out[tool] = sorted(labs)
    return out


# ---------------------------------------------------------------- the live text
def norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def type_of(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "any"
    if "anyOf" in schema:
        return " | ".join(type_of(s) for s in schema["anyOf"])
    t = schema.get("type")
    if t == "array":
        return f"array<{type_of(schema['items'])}>" if "items" in schema else "array"
    return str(t) if t else "any"


def _fixture_config(tmp: Path) -> None:
    """A throwaway config made from the example, as the scenarios make theirs: no live store, no host fleet, nothing outside tmp."""
    toml = (ROOT / "stackshot.example.toml").read_text(encoding="utf-8")
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"),
                     ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "UTC")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml)
        assert n == 1, key
    (tmp / "stackshot.toml").write_text(toml, encoding="utf-8")
    for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "brain/projects"):
        (tmp / d).mkdir(parents=True)
    (tmp / "store/projects.json").write_text('{"pages": {}}')
    (tmp / "store/next-id").write_text("10")
    (tmp / "store/anchors.json").write_text("{}")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
    for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL"):
        os.environ.pop(k, None)


_SCRATCH: list[Path] = []


def cleanup() -> None:
    """Remove the throwaway config directories this process made (os._exit skips atexit, so the commands and the suite call this)."""
    while _SCRATCH:
        shutil.rmtree(_SCRATCH.pop(), ignore_errors=True)


def live_snapshot() -> dict[str, Any]:
    """The snapshot of the code in this checkout: server.py imported in-process on a throwaway config, its registry listed the way a client lists it."""
    import logging
    if "stackshot.web.server" not in sys.modules:
        tmp = Path(tempfile.mkdtemp(prefix="tooltext-"))
        _SCRATCH.append(tmp)
        _fixture_config(tmp)
        sys.path.insert(0, str(ROOT))
        logging.disable(logging.WARNING)
    from stackshot.web import server   # noqa: PLC0415
    labels = labels_by_tool()
    tools: dict[str, Any] = {}
    for t in asyncio.run(server.mcp.list_tools()):
        schema = t.parameters or {}
        req = set(schema.get("required") or [])
        params = {}
        for pname, ps in sorted((schema.get("properties") or {}).items()):
            p: dict[str, Any] = {"type": type_of(ps), "required": pname in req, "description": norm(ps.get("description"))}
            if "default" in ps:
                p["default"] = ps["default"]
            params[pname] = p
        tools[t.name] = {"description": norm(t.description), "parameters": params}
        if t.name in LABELLED:
            tools[t.name]["labels"] = labels[t.name]
    missing = [t for t in LABELLED if t not in tools]
    if missing:
        raise SystemExit(f"tool_text: HELPERS names a tool the server does not register: {', '.join(missing)}")
    res = {str(r.uri): {"name": r.name, "description": norm(r.description), "mime_type": r.mime_type} for r in asyncio.run(server.mcp.list_resources())}
    return {"format": FORMAT, "instructions": norm(server.mcp.instructions), "resources": res, "tools": tools}


def render(snap: dict[str, Any]) -> str:
    return json.dumps(snap, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def stored(path: Path = SNAPSHOT) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the readable diff
def word_diff(old: str, new: str, context: int = 6) -> list[str]:
    """Where two texts differ, as `…context [-old-] {+new+} context…`, one line per place."""
    a, b = old.split(" "), new.split(" ")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        pre, post = " ".join(a[max(0, i1 - context):i1]), " ".join(a[i2:i2 + context])
        gone, came = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        mark = (f"[-{gone}-]" if gone else "") + (" " if gone and came else "") + (f"{{+{came}+}}" if came else "")
        out.append(f"      …{pre + ' ' if pre else ''}{mark}{' ' + post if post else ''}…")
    return out


def diff_lines(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("instructions",):
        if old.get(key) != new.get(key):
            out += [f"the connector's {key} changed:"] + word_diff(str(old.get(key) or ""), str(new.get(key) or ""))
    for r in sorted(set(old.get("resources") or {}) | set(new.get("resources") or {})):
        a, b = (old.get("resources") or {}).get(r), (new.get("resources") or {}).get(r)
        if a != b:
            out.append(f"resource {r}: " + ("added" if a is None else "removed" if b is None else "changed") + f" {json.dumps(b if a is None else a if b is None else {'from': a, 'to': b}, ensure_ascii=False)[:300]}")
    ot, nt = old.get("tools") or {}, new.get("tools") or {}
    for name in sorted(set(ot) | set(nt)):
        o, n = ot.get(name), nt.get(name)
        if o is None:
            out.append(f"tool {name}: ADDED (parameters {', '.join(n.get('parameters') or {}) or 'none'})")
            continue
        if n is None:
            out.append(f"tool {name}: REMOVED")
            continue
        body: list[str] = []
        if o.get("description") != n.get("description"):
            body += ["  description changed:"] + word_diff(o.get("description") or "", n.get("description") or "")
        op, np_ = o.get("parameters") or {}, n.get("parameters") or {}
        for p in sorted(set(op) | set(np_)):
            if p not in op:
                body.append(f"  parameter {p}: ADDED {json.dumps(np_[p], ensure_ascii=False)}")
            elif p not in np_:
                body.append(f"  parameter {p}: REMOVED")
            elif op[p] != np_[p]:
                for k in sorted(set(op[p]) | set(np_[p])):
                    if op[p].get(k) != np_[p].get(k):
                        body.append(f"  parameter {p}: {k} {json.dumps(op[p].get(k), ensure_ascii=False)[:200]} -> {json.dumps(np_[p].get(k), ensure_ascii=False)[:200]}")
        ol, nl = set(o.get("labels") or []), set(n.get("labels") or [])
        if ol - nl:
            body.append("  returned-line labels gone: " + ", ".join(sorted(ol - nl)))
        if nl - ol:
            body.append("  returned-line labels new: " + ", ".join(sorted(nl - ol)))
        if body:
            out += [f"tool {name}:"] + body
    return out


def check_report(live: dict[str, Any], kept: dict[str, Any] | None) -> list[str]:
    """[] when the snapshot is the live text; else what to read and the command that refreshes it."""
    if kept is None:
        return [f"{SNAPSHOT_REL} is missing or not JSON.", f"Create it:  {REFRESH}"]
    if kept == live and render(kept) == render(live):
        return []
    return ["The tools' text differs from tests/tool_text.snapshot.json (a tool's text changes in the same release as the tool):", ""] + diff_lines(kept, live) + [
        "", "If the change is meant (it is what the PR is for), refresh the snapshot and commit it with the change:", f"    {REFRESH}",
        "If it is not, the tool's code or text moved by accident."]


# ---------------------------------------------------------------- the touched-tool check
def git(root: Path, *a: str) -> str | None:
    r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _is_mcp_tool(f: ast.AST) -> bool:
    return isinstance(f, ast.Attribute) and f.attr == "tool" and isinstance(f.value, ast.Name) and f.value.id == "mcp"


def tool_functions(tree: ast.AST) -> set[str]:
    """The functions registered as tools: decorated @mcp.tool(...), or handed to `mcp.tool(...)(function)` as the modules of web/tools/ do in `register`."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if _is_mcp_tool(d.func if isinstance(d, ast.Call) else d):
                    out.add(n.name)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Call) and _is_mcp_tool(n.func.func):
            out.update(a.id for a in n.args if isinstance(a, ast.Name))
    return out


def body_dump(fn: Any) -> str:
    """A function's arguments and body without its docstring (the decorator, the description the snapshot holds, is not in it)."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.dump(ast.Module(body=[ast.FunctionDef(name=fn.name, args=fn.args, body=body or [ast.Pass()], decorator_list=[], returns=fn.returns, type_params=[])], type_ignores=[]))


def watched(src: str | None, file: str) -> dict[str, str] | None:
    """{function name: its body dump} for the functions of one file the gate watches (the tool functions, in web/tools/ (before the split, server.py), and the output helpers); None when it does not parse."""
    if src is None:
        return {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    fns = functions(tree)
    names = {n for f, n in ALL_HELPERS if f == file} | (tool_functions(tree) if file == SERVER_REL or file in TOOL_FILES else set())
    return {n: body_dump(fns[n]) for n in names if n in fns}


def changed_functions(base: dict[str, str | None], head: dict[str, str | None]) -> list[str]:
    """base and head map a file name to its source (None: absent). The watched functions whose body differs, appear or disappear, as `file:function`."""
    out = []
    for file in sorted(set(base) | set(head)):
        b, h = watched(base.get(file), file), watched(head.get(file), file)
        if b is None or h is None:
            out.append(f"{file}: does not parse")
            continue
        out += [f"{file}:{n}" for n in sorted(set(b) | set(h)) if b.get(n) != h.get(n)]
    return out


REASON = re.compile(r"(?im)^[ \t>*\-]*tool-text:[ \t]*unchanged:[ \t]*(\S.*?)[ \t]*$")      # one line: the reason is on it, never the next line's text


PLACEHOLDER = re.compile(r"(?:<[^<>]*>[\s.:;,\-]*)+")      # `<reason>`, `<why no session reads a difference>`, several of them: the template left as it was


def real_reason(reason: str) -> bool:
    """A reason someone wrote: at least 3 characters, and not only angle-bracket placeholders (the PR template's own `<reason>` must not pass)."""
    r = (reason or "").strip()
    return len(r) >= 3 and PLACEHOLDER.fullmatch(r) is None


def changed_since(root: Path, base: str, head: str, exact: bool = False) -> tuple[str, list[str]]:
    """(the fork point of base and head, or base itself when exact; the watched functions changed from it to head as `file:function`). Shared with tools/text_check.py."""
    mb = base if exact else (git(root, "merge-base", base, head) or base).strip()    # the fork point: a main that moved on since is not this PR's change
    files = sorted({f for f, _ in ALL_HELPERS} | {SERVER_REL} | set(TOOL_FILES))
    src = lambda rev: {f: show_at(root, rev, f) for f in files}
    return mb, changed_functions(src(mb), src(head))


def touched(root: Path, base: str, head: str, body: str, exact: bool = False) -> tuple[int, list[str]]:
    mb, changed = changed_since(root, base, head, exact)
    snap_b, snap_h = git(root, "show", f"{mb}:{SNAPSHOT_REL}"), git(root, "show", f"{head}:{SNAPSHOT_REL}")
    if not changed:
        return 0, ["tool-text: this change touches no tool function and no output helper."]
    if snap_b != snap_h:
        return 0, [f"tool-text: {len(changed)} tool function(s) or output helper(s) changed and {SNAPSHOT_REL} changed with them: ok."]
    m = REASON.search(body or "")
    placeholder = bool(m) and not real_reason(m.group(1))
    if m and real_reason(m.group(1)):
        return 0, [f"tool-text: {len(changed)} tool function(s) or output helper(s) changed with the snapshot unchanged, declared by the PR body:",
                   f"    tool-text: unchanged: {m.group(1)}"] + [f"  {c}" for c in changed]
    out = ["tool-text: a tool function or an output helper changed its body and tests/tool_text.snapshot.json did not change with it.", ""]
    if placeholder:
        out += ["The PR body has a `tool-text: unchanged:` line, but its reason is still the template's placeholder; write the reason itself.", ""]
    return 1, out + ["Changed:"] + [f"  {c}" for c in changed] + ["",
               "A tool's text changes in the same release as the tool (the project's rule). Either",
               f"  - the change reaches what a session reads (a parameter, a description, a returned line): run `{REFRESH}` and commit the snapshot with it; or",
               "  - it does not (a refactor, a fix inside the code that leaves every returned label and sentence as it was): add a line to the PR body",
               "        tool-text: unchanged: <why no session reads a difference>",
               "    and re-run this job (it reads the body when it runs)."]


# ---------------------------------------------------------------- the commands
def ensure_env() -> None:
    """dump, check and update import server.py, which needs fastmcp: bare python3 has none, so run again in the tests' uv environment (as tests/run-suite does)."""
    try:
        import fastmcp  # noqa: F401, PLC0415
        return
    except ImportError:
        pass
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    env = dict(os.environ)
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "stackshot" / "test-venv"))
    if not Path(uv).exists():
        raise SystemExit("tool_text: fastmcp is missing and uv was not found: run `tests/run-suite tool_text`, or install uv")
    os.execve(uv, [uv, "run", "--locked", "--project", str(ROOT), "--only-group", "tests", "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the tool-text gates (see this file's docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dump")
    for c in ("check", "update"):
        sub.add_parser(c).add_argument("--snapshot", type=Path, default=SNAPSHOT, help=f"the file to compare with or write (default {SNAPSHOT_REL})")
    t = sub.add_parser("touched")
    t.add_argument("--base", required=True)
    t.add_argument("--head", required=True)
    t.add_argument("--body-file", type=Path)
    t.add_argument("--repo", type=Path, default=ROOT)
    t.add_argument("--exact", action="store_true", help="compare --base itself, not its merge-base with --head")
    s = sub.add_parser("summary")
    s.add_argument("--base", default="origin/main")
    sub.add_parser("record")
    a = ap.parse_args(argv)
    if a.cmd == "touched":
        body = a.body_file.read_text(encoding="utf-8", errors="replace") if a.body_file and a.body_file.exists() else ""
        rc, msg = touched(a.repo, a.base, a.head, body, a.exact)
        print("\n".join(msg))
        return rc
    sys.path.insert(0, str(ROOT))
    if a.cmd == "summary":
        from stackshot.web import whatschanged   # noqa: PLC0415
        old = json.loads(git(ROOT, "show", f"{a.base}:{SNAPSHOT_REL}") or "{}")
        print(whatschanged.summarize(old, stored() or {}) or "(no change in the tools' text)")
        return 0
    if a.cmd == "record":
        from stackshot.web import whatschanged   # noqa: PLC0415
        print(whatschanged.record(SNAPSHOT))
        return 0
    ensure_env()
    live = live_snapshot()
    rc = 0
    if a.cmd == "dump":
        sys.stdout.write(render(live))
    elif a.cmd == "update":
        a.snapshot.write_text(render(live), encoding="utf-8")
        print(f"wrote {a.snapshot}: {len(live['tools'])} tools")
    else:
        rep = check_report(live, stored(a.snapshot))
        print("\n".join(rep) if rep else f"ok: {a.snapshot} is the live text ({len(live['tools'])} tools)")
        rc = 1 if rep else 0
    sys.stdout.flush()
    cleanup()
    os._exit(rc)      # server.py starts threads of its own; the command is done


if __name__ == "__main__":
    sys.exit(main())
