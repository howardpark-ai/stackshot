#!/usr/bin/env python3
"""tools/retired_terms.py — the retired-terms lint. Stdlib only (Python 3.11+), no stackshot import: sala copies this file
and its tests/retired_terms.toml shape as they are.

A word the owner retired (owner → mover, keeper of record → mover, steward → router and keepers) must not come back in text a session reads. The words
are listed in a TOML file; the lint scans the text the code emits and fails naming the file, the line, the term and what to say instead.

    python3 tools/retired_terms.py [--config tests/retired_terms.toml] [--root .]      → exit 0 (clean) / 1 (a hit) / 2 (the config is wrong)

The config (see tests/retired_terms.toml for the live one, with every allow entry justified):

    [[term]]
    retired = "owner"                    # a whole word, matched case-insensitively (owner_name, ownership and OWNER_X are other words)
    use     = "mover (who acts next); the stored creator is only 'created by'"     # what to write instead; printed with every hit
    allow   = ["metadata.owner", "=the owner"]   # literal phrases (case-insensitive): a hit INSIDE an occurrence of one is a legitimate use;
                                                 # a phrase that starts with `=` must be the WHOLE string literal (or JSON value, or line), so a
                                                 # default such as `or "the owner"` is excused without excusing the same words in a sentence

    [[scan]]
    files   = ["*.py", "tests/tool_text.snapshot.json"]   # globs from the root (`*` stays in one directory, `**` crosses them); a Python file is read by its string literals (never its comments,
                                                          # docstrings, stderr prints, or a literal that is one bare identifier or path: a stored
                                                          # key), a .json file by its string values, anything else as plain text
    exclude = ["tests/*"]                # optional globs left out
    skip_keys = ["name", "type"]         # optional, json only: keys whose values are names, not text (a parameter called owner)
    kind    = "python"                   # optional: read the files as python | json | text whatever their suffix (a script with no .py)

Any other file is scanned line by line. A hit inside an allow phrase is excused; there is no other escape, so every new
legitimate use is a reviewed line in the config."""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

BARE = re.compile(r"[\w.\-/]+")        # a literal that is one identifier, a dotted key or a path: a name the code uses, not text a session reads


@dataclass(frozen=True)
class Term:
    retired: str
    use: str
    allow: tuple[str, ...]
    rx: re.Pattern[str]


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    term: str
    use: str
    text: str            # the stretch of text around the hit

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: retired term {self.term!r}: say {self.use}  ...{self.text}..."


def load(config: Path) -> tuple[list[Term], list[dict]]:
    with open(config, "rb") as f:
        data = tomllib.load(f)
    terms = []
    for t in data.get("term", []):
        word, use = str(t.get("retired", "")).strip(), str(t.get("use", "")).strip()
        if not word or not use:
            raise ValueError(f"{config}: every [[term]] needs `retired` and `use`")
        terms.append(Term(word, use, tuple(str(a) for a in t.get("allow", [])), re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.I)))
    scans = data.get("scan", [])
    if not terms or not scans:
        raise ValueError(f"{config}: needs at least one [[term]] and one [[scan]]")
    return terms, scans


def excused(text: str, start: int, end: int, term: Term) -> bool:
    low = text.lower()
    for phrase in term.allow:
        p = phrase.lower()
        if p.startswith("="):                           # the whole literal, nothing around it
            if low.strip() == p[1:]:
                return True
            continue
        i = low.find(p)
        while i != -1:
            if i <= start and end <= i + len(p):
                return True
            i = low.find(p, i + 1)
    return False


def find(text: str, terms: list[Term]) -> Iterator[tuple[Term, int, str]]:
    """(term, offset, context) for each hit in `text` that no allow phrase covers."""
    for t in terms:
        for m in t.rx.finditer(text):
            if not excused(text, m.start(), m.end(), t):
                yield t, m.start(), text[max(0, m.start() - 30):m.end() + 30].replace("\n", "\\n")


def python_strings(src: str) -> Iterator[tuple[int, int, str]]:
    """(first line, last line, value) of the string literals that are text: no docstring (any string statement), no stderr print, no lone identifier."""
    tree = ast.parse(src)
    skip: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            skip.add(id(n.value))                       # a docstring, or a string statement that documents the line above it
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" and any(k.arg == "file" for k in n.keywords):
            skip.update(id(c) for c in ast.walk(n))      # a log line to stderr is not read by a session
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and not BARE.fullmatch(n.value):
            yield n.lineno, n.end_lineno or n.lineno, n.value


def json_strings(doc: object, skip_keys: set[str], path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(doc, str):
        yield path, doc
    elif isinstance(doc, list):
        for i, x in enumerate(doc):
            yield from json_strings(x, skip_keys, f"{path}[{i}]")
    elif isinstance(doc, dict):
        for k, v in doc.items():
            if k not in skip_keys:
                yield from json_strings(v, skip_keys, f"{path}.{k}" if path else str(k))


def line_in_range(lines: list[str], first: int, last: int, rx: re.Pattern[str]) -> int:
    for ln in range(first, min(last, len(lines)) + 1):
        if rx.search(lines[ln - 1]):
            return ln
    return first


def scan_file(root: Path, rel: str, terms: list[Term], skip_keys: set[str], kind: str = "") -> list[Hit]:
    p = root / rel
    try:
        src = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[Hit] = []
    lines = src.split("\n")
    kind = kind or ("python" if rel.endswith(".py") else "json" if rel.endswith(".json") else "text")
    if kind == "python":
        for first, last, value in python_strings(src):
            for t, off, ctx in find(value, terms):
                out.append(Hit(rel, line_in_range(lines, first, last, t.rx), t.retired, t.use, ctx))
    elif kind == "json":
        for path, value in json_strings(json.loads(src), skip_keys):
            for t, off, ctx in find(value, terms):
                needle = json.dumps(value[max(0, off - 20):off + 20])[1:-1][:30]
                ln = next((i for i, x in enumerate(lines, 1) if needle in x), 1)
                out.append(Hit(rel, ln, t.retired, t.use, f"{path}: {ctx}"))
    else:
        for i, line in enumerate(lines, 1):
            for t, off, ctx in find(line, terms):
                out.append(Hit(rel, i, t.retired, t.use, ctx))
    return out


def glob_rx(pattern: str) -> re.Pattern[str]:
    """A path glob: `*` stays inside one directory, `**` crosses them."""
    return re.compile("".join(".*" if t == "**" else "[^/]*" if t == "*" else "[^/]" if t == "?" else re.escape(t) for t in re.findall(r"\*\*|\*|\?|[^*?]+", pattern)) + r"\Z")


def tracked(root: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout:
        return r.stdout.split("\n")
    return [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def lint(root: Path, config: Path) -> list[Hit]:
    terms, scans = load(config)
    files = [f for f in tracked(root) if f and (root / f).is_file()]
    hits: list[Hit] = []
    seen: set[str] = set()
    for sc in scans:
        pats, excl = [glob_rx(str(x)) for x in sc.get("files", [])], [glob_rx(str(x)) for x in sc.get("exclude", [])]
        skip_keys = {str(k) for k in sc.get("skip_keys", [])}
        for f in files:
            if f in seen or not any(p.match(f) for p in pats) or any(x.match(f) for x in excl):
                continue
            seen.add(f)
            hits.extend(scan_file(root, f, terms, skip_keys, str(sc.get("kind", ""))))
    return sorted(set(hits), key=lambda h: (h.file, h.line, h.term, h.text))


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="the retired-terms lint (see this file's docstring)")
    ap.add_argument("--config", type=Path, default=here / "tests" / "retired_terms.toml")
    ap.add_argument("--root", type=Path, default=here)
    a = ap.parse_args(argv)
    try:
        hits = lint(a.root, a.config)
    except (OSError, ValueError, SyntaxError) as e:
        print(f"retired_terms: {e}", file=sys.stderr)
        return 2
    for h in hits:
        print(h)
    if hits:
        print(f"\n{len(hits)} use(s) of a retired term. Say what the config's `use` says; a use that is right as it stands (a stored key, the instance's owner) "
              f"is an `allow` phrase in {a.config.name}, with its reason beside it.", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
