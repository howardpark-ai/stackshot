#!/usr/bin/env python3
"""tools/text_check.py — the reading pack for a tool-text change (run by hand; no workflow runs it, and it calls no model).

tools/tool_text.py `touched` is mechanical: it sees that a tool function or an output helper changed, and whether the snapshot changed with it. It cannot read
whether the words still say what the code now does. That reading is done before the merge by the maintainer's reviewer subagent (CONTRIBUTING.md, "The tool-text
gates", item 4). This script gathers what it reads, for a pull request that touches a tool function or an output helper: the tools the change reaches, the
functions with a changed body, whether the PR changed tests/tool_text.snapshot.json, the current text of the reached tools (description, parameters, the labels
of the lines they return, all from the snapshot at the PR's head) and the diff of the watched files, the hunks of the changed functions first.

    text_check.py pack --base SHA --head SHA     print the reading pack, or one `nothing to read: <why>` line

Also takes --repo (default: this checkout), --exact (compare --base itself, not its fork point with --head) and, for the size caps, --max-diff-chars and
--max-text-chars. The affected tools are those whose function changed (`@mcp.tool(name=…)`) or that list a changed function among their output helpers
(HELPERS in tool_text.py), the same watch `touched` keeps. The diff is cut to 60,000 characters and the tools' text to 160,000, and the cut is said in the pack.
Standard library only: no dependency, no lock, no network."""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import tool_text as tt   # noqa: E402

MAX_DIFF = 60_000
# The snapshot of every tool together is large. A cap below it would cut a tool's parameters off, and the reader would then
# call them missing (a false alarm). 160,000 holds all tools with room to grow (raised from 150,000 when the update and create tools gained the until parameter, which left no room under the old cap).
MAX_TEXT = 160_000
CONTEXT = 6                                                   # lines of context around each hunk


# ---------------------------------------------------------------- what is affected
def tool_names(src: str | None) -> dict[str, str]:
    """{function name: tool name} for the functions registered as tools: decorated @mcp.tool(name="…"), or handed to `mcp.tool(name="…")(function)` (the function's own name when the registration gives none)."""
    out: dict[str, str] = {}
    try:
        tree = ast.parse(src or "")
    except SyntaxError:
        return out
    def named(call: ast.AST, default: str) -> str:
        if isinstance(call, ast.Call):
            for k in call.keywords:
                if k.arg == "name" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str):
                    return k.value.value
        return default
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if tt._is_mcp_tool(d.func if isinstance(d, ast.Call) else d):
                    out[n.name] = named(d, n.name)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Call) and tt._is_mcp_tool(n.func.func):
            for a in n.args:
                if isinstance(a, ast.Name):
                    out[a.id] = named(n.func, a.id)
    return out


def registry_source(root: Path, rev: str) -> str:
    """The text of the files a tool is registered in at `rev` (server.py and web/tools/*.py), joined: what `affected_tools` reads the tool names from."""
    return "\n".join(tt.show_at(root, rev, f) or "" for f in (tt.SERVER_REL, *tt.TOOL_FILES))


def module_tools(root: Path, rev: str) -> dict[str, set[str]]:
    """{tool module name: the tools its file registers} at `rev`, for `affected_tools` to read a text file's reach from."""
    return {Path(f).stem: set(tool_names(tt.show_at(root, rev, f)).values()) for f in tt.TOOL_FILES}


def affected_tools(changed: list[str], head_server: str | None, base_server: str | None, by_module: dict[str, set[str]] | None = None) -> list[str]:
    """The tools a changed `file:function` list reaches: a changed tool function is its tool; a changed output helper reaches every tool that lists it in HELPERS; a changed
    text file (`file:text`) reaches the tools of its module (`by_module`, from `module_tools`; the tool of the same name without it), the shared file every tool. The two sources are those of `registry_source`."""
    names = {**tool_names(base_server), **tool_names(head_server)}
    out: set[str] = set()
    for c in changed:
        if ":" not in c:
            continue
        file, fn = c.rsplit(":", 1)
        if tt.is_text_file(file):
            if file == tt.TEXT_SHARED:
                out |= set(tt.HELPERS) | set(names.values())
            else:
                stem = Path(file).stem
                out |= (by_module or {}).get(stem) or ({stem} & (set(tt.HELPERS) | set(names.values())))
            continue
        if (file == tt.SERVER_REL or file in tt.TOOL_FILES) and fn in names:
            out.add(names[fn])
        for tool, helpers in tt.HELPERS.items():
            if (file, fn) in helpers:
                out.add(tool)
    return sorted(out)


# ---------------------------------------------------------------- the diff, cut to size
def spans(src: str | None, names: set[str]) -> list[tuple[int, int]]:
    """Line spans (decorators included) of the named functions in a source."""
    try:
        fns = tt.functions(ast.parse(src or ""))
    except SyntaxError:
        return []
    out = []
    for n in names:
        f = fns.get(n)
        if f is not None:
            out.append((min([f.lineno] + [d.lineno for d in f.decorator_list]), f.end_lineno or f.lineno))
    return out


def split_diff(diff: str) -> list[tuple[str, str, int, int, int, int]]:
    """[(file, hunk text including its @@ line, old start, old count, new start, new count)] in the diff's order."""
    out, file, cur = [], "", None
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            file = line.rsplit(" b/", 1)[-1]
            cur = None
        elif line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            a, b, c, d = (int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)) if m else (0, 0, 0, 0)
            cur = [file, line + "\n", a, b, c, d]
            out.append(cur)
        elif cur is not None:
            cur[1] += line + "\n"
    return [tuple(h) for h in out]    # type: ignore[misc]


def fit_diff(root: Path, mb: str, head: str, changed: list[str], limit: int) -> str:
    """`git diff` of the watched files from the fork point to head, cut to `limit` characters by hunks: the ones that overlap a changed function first."""
    files = sorted({f for f, _ in tt.ALL_HELPERS} | {tt.SERVER_REL} | set(tt.TOOL_FILES) | set(tt.text_files_at(root, mb)) | set(tt.text_files_at(root, head)))
    r = subprocess.run(["git", "-C", str(root), "diff", "--no-color", f"-U{CONTEXT}", mb, head, "--", *files, *tt._BEFORE_PACKAGE.values()], capture_output=True, text=True, errors="replace")
    diff = r.stdout if r.returncode == 0 else ""
    hunks = split_diff(diff)
    want: dict[str, set[str]] = {}
    for c in changed:
        if ":" in c:
            f, fn = c.rsplit(":", 1)
            want.setdefault(f, set()).add(fn)
    old_sp = {f: spans(tt.show_at(root, mb, f), n) for f, n in want.items()}
    new_sp = {f: spans(tt.show_at(root, head, f), n) for f, n in want.items()}
    hit = lambda sp, a, n: any(a <= e and a + max(n, 1) - 1 >= s for s, e in sp)
    rel = [tt.is_text_file(f) or hit(old_sp.get(f, []), a, b) or hit(new_sp.get(f, []), c, d) for f, _, a, b, c, d in hunks]     # a hunk of a text file is the words themselves: always first
    order = [i for i in range(len(hunks)) if rel[i]] + [i for i in range(len(hunks)) if not rel[i]]
    used, keep = 0, set()
    for i in order:
        size = len(hunks[i][1]) + (len(hunks[i][0]) + 8 if not any(hunks[j][0] == hunks[i][0] for j in keep) else 0)
        if used + size <= limit:
            keep.add(i)
            used += size
    out, last = [], None
    for i in range(len(hunks)):
        if i in keep:
            if hunks[i][0] != last:
                out.append(f"--- {hunks[i][0]}\n")
                last = hunks[i][0]
            out.append(hunks[i][1])
    omitted = len(hunks) - len(keep)
    text = "".join(out)
    if omitted:
        text += f"[{omitted} of {len(hunks)} hunks omitted to fit the size limit; the ones that overlap a changed tool function or output helper come first]\n"
    return text or "[no diff of the watched files]\n"


def fit_text(snapshot: dict[str, Any], tools: list[str], limit: int) -> str:
    """The affected tools' snapshot entries as indented JSON, cut to `limit` characters (the cut is said)."""
    present = {t: (snapshot.get("tools") or {}).get(t, "(not in the snapshot)") for t in tools}
    text = json.dumps(present, indent=1, sort_keys=True, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + f"\n[tool text cut at {limit} characters]"
    return text


def build_pack(root: Path, base: str, head: str, exact: bool, max_diff: int, max_text: int) -> str:
    """The reading pack as text; NothingToRead (with the reason) when the change touches no tool."""
    mb, changed = tt.changed_since(root, base, head, exact)
    if not changed:
        raise NothingToRead("no tool function and no output helper has a changed body")
    head_server, base_server = registry_source(root, head), registry_source(root, mb)
    tools = affected_tools(changed, head_server, base_server, {k: v | module_tools(root, mb).get(k, set()) for k, v in module_tools(root, head).items()})
    if not tools:
        raise NothingToRead("the changed functions reach no tool's text: " + ", ".join(changed))
    try:
        snap = json.loads(tt.git(root, "show", f"{head}:{tt.SNAPSHOT_REL}") or "{}")
    except ValueError:
        snap = {}
    snap_changed = tt.git(root, "show", f"{mb}:{tt.SNAPSHOT_REL}") != tt.git(root, "show", f"{head}:{tt.SNAPSHOT_REL}")
    return (f"Tools the change reaches: {', '.join(tools)}\n"
            f"Functions with a changed body: {', '.join(changed)}\n"
            f"The pull request {'also changed' if snap_changed else 'did not change'} tests/tool_text.snapshot.json.\n\n"
            f"=== tool text (the snapshot at the head) ===\n{fit_text(snap if isinstance(snap, dict) else {}, tools, max_text)}\n\n"
            f"=== diff of the watched files ===\n{fit_diff(root, mb, head, changed, max_diff)}")


class NothingToRead(Exception):
    """The change touches no tool function and no output helper that reaches a tool."""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the reading pack for a tool-text change (see this file's docstring)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--repo", type=Path, default=ROOT)
    p.add_argument("--exact", action="store_true", help="compare --base itself, not its merge-base with --head")
    p.add_argument("--max-diff-chars", type=int, default=MAX_DIFF)
    p.add_argument("--max-text-chars", type=int, default=MAX_TEXT)
    a = ap.parse_args(argv)
    try:
        print(build_pack(a.repo, a.base, a.head, a.exact, a.max_diff_chars, a.max_text_chars))
    except NothingToRead as e:
        print(f"nothing to read: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
