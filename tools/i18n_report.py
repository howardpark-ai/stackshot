#!/usr/bin/env python3
"""tools/i18n_report.py — how much of the board's page text is routed through the string table (stackshot/web/i18n.py, i18n_catalog.py), module by module. A helper, not a gate: it exits 0.

Usage:
  python3 tools/i18n_report.py                 the table for the page modules and the shared render code
  python3 tools/i18n_report.py --list          also each unrouted text, with its file and line
  python3 tools/i18n_report.py --functions N   also the N functions of each module with the most unrouted texts
  python3 tools/i18n_report.py FILE...         only these files (paths relative to the checkout)

What it counts (a heuristic: it reads the Python syntax tree, it does not run the pages):
  routed      calls of the string table with a literal key: t("..."), _t("..."), _i18n.t("..."), i18n.t("..."), and SST('...') inside a script held in a string.
  unrouted    string literals, and the literal parts of f-strings, that read as text a person sees and are not a call's key. A literal that holds markup is split at its tags: the text between
              tags counts, and so does the value of an aria-label, title, placeholder, alt or data-tip attribute. A piece counts when, with its {fields} and entities taken out, it has two or more
              words, or one capitalized word of three letters or more, and none of the characters of code ({ } ; = [ ] # \\ and so on).
  script      in the page-script constants (a module-level name ending _JS), the single-quoted literals that read as text and are not an SST(...) key: the words a script says on its own.
  coverage    routed / (routed + unrouted + script), in percent.

What it skips: docstrings; the operands of a comparison, a subscript or a dict key; the arguments of print, raise, assert and of the calls that only test or cut text (startswith, endswith, split, get, re.*);
module-level CSS, SVG and regular-expression constants (names ending _CSS, _SVG, _RX, _RE, _PATTERN); text under an `# i18n: skip` comment on its line. Item text (titles, descriptions, steps, history, asks) is data, not source, and
the tools' text is not page text: neither is counted. A number is a measure of the work left, not a promise that the rest is missing: a literal the heuristic reads as text may be a log line or a data word, and a word it
misses is not counted. No file here holds text in another language (CONTRIBUTING.md)."""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAGE_MODULES = (            # the page code: one per page, then the shared renderers
    "stackshot/web/itempage.py",
    "stackshot/web/home.py",
    "stackshot/notify/foryou.py",
    "stackshot/notify/landed.py",
    "stackshot/web/ui/groups.py",
    "stackshot/web/ui/releasing.py",
    "stackshot/web/ui/runners.py",
    "stackshot/web/ui/search.py",
    "stackshot/web/ui/colortool.py",
    "stackshot/web/ui/kit.py",
    "stackshot/web/ui/render.py",
)
GROUPS = (                  # the three lines the report is read in
    ("item page", ("stackshot/web/itempage.py",)),
    ("other pages", ("stackshot/web/home.py", "stackshot/notify/foryou.py", "stackshot/notify/landed.py", "stackshot/web/ui/groups.py", "stackshot/web/ui/releasing.py",
                     "stackshot/web/ui/runners.py", "stackshot/web/ui/search.py", "stackshot/web/ui/colortool.py")),
    ("shared render code", ("stackshot/web/ui/kit.py", "stackshot/web/ui/render.py")),
)
T_NAMES = {"t", "_t", "tr"}
T_ATTRS = {"t"}                                     # _i18n.t, i18n.t
SKIP_CALLS = {"print", "getattr", "hasattr", "setattr", "isinstance", "open", "len", "int", "float", "range", "enumerate", "sorted", "set", "frozenset", "tuple", "list", "dict", "type", "super", "repr"}
SKIP_ATTRS = {"startswith", "endswith", "split", "rsplit", "get", "pop", "setdefault", "strip", "lstrip", "rstrip", "partition", "rpartition", "find", "index", "count", "encode", "decode", "match", "search", "sub",
              "subn", "findall", "finditer", "fullmatch", "compile", "escape", "getenv", "environ", "exists", "is_file", "is_dir", "stat", "mkdir", "write_text", "read_text", "add_argument", "getLogger", "warning", "error", "info"}
SKIP_ASSIGN = re.compile(r"(_CSS|_SVG|_RX|_RE|_PATTERN|_PATTERNS|_ICON|_ICONS)$")
ATTR_RX = re.compile(r'(?:aria-label|title|placeholder|alt|data-tip)="([^"]*)"')
TAG_RX = re.compile(r"<[^>]*>")
FIELD_RX = re.compile(r"\{[^{}]*\}")
ENTITY_RX = re.compile(r"&[a-zA-Z]+;|&#\d+;")
CODE_CHARS = re.compile(r"[{};=\[\]#\\|$@^~<>]|::|=>|\bfunction\b|\bvar\b|\breturn\b|document\.|window\.|\.\w+\(")
KEY_RX = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_-]*)+")        # a string table key (or the prefix of one)
WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’-]*")
JS_SQ_RX = re.compile(r"(?<![\w$.])'([^'\\\n]{2,80})'")
SST_RX = re.compile(r"SST\(")


def reads_as_text(piece: str) -> bool:
    """Whether a piece of a literal (no tags) reads like words a person sees."""
    p = ENTITY_RX.sub(" ", FIELD_RX.sub(" ", piece)).strip()
    if not p or CODE_CHARS.search(p) or KEY_RX.fullmatch(p):
        return False
    words = WORD_RX.findall(p)
    if len(words) >= 2:
        return any(len(w) >= 2 for w in words)
    return len(words) == 1 and len(words[0]) >= 3 and words[0][0].isupper() and bool(re.fullmatch(r"[A-Z][A-Za-z'’-]*[.:!?]?", p))


def pieces(s: str) -> list[str]:
    """The text pieces of a literal: whole when it has no markup, else the text between tags plus the visible attributes."""
    if "<" not in s:
        return [s]
    out = [m for m in ATTR_RX.findall(s)]
    out += [x for x in TAG_RX.split(s)]
    return out


def literal_text(node: ast.AST) -> str | None:
    """A str literal, or an f-string with its {fields} left as `{}`; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}" for v in node.values)
    return None


class Scan(ast.NodeVisitor):
    def __init__(self, src: str):
        self.lines = src.splitlines()
        self.routed = 0
        self.unrouted: list[tuple[int, str, str]] = []      # (line, function, text)
        self.script: list[tuple[int, str, str]] = []
        self.stack: list[str] = []
        self.skip_depth = 0
        self.doc_ids: set[int] = set()

    # --- helpers
    def where(self) -> str:
        return ".".join(self.stack) or "<module>"

    def skipped_line(self, ln: int) -> bool:
        return 0 < ln <= len(self.lines) and "i18n: skip" in self.lines[ln - 1]

    def note(self, node: ast.AST, s: str) -> None:
        if self.skipped_line(node.lineno):
            return
        for p in pieces(s):
            if reads_as_text(p):
                self.unrouted.append((node.lineno, self.where(), " ".join(p.split())[:90]))

    # --- visitors
    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        self.mark_doc(node)
        for d in node.decorator_list:
            self.skip_depth += 1
            self.visit(d)
            self.skip_depth -= 1
        self.generic_visit_body(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.stack.append(node.name)
        self.mark_doc(node)
        self.generic_visit_body(node)
        self.stack.pop()

    def generic_visit_body(self, node):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.arguments):
                self.skip_depth += 1
                self.visit(ch)
                self.skip_depth -= 1
            elif ch not in node.decorator_list if hasattr(node, "decorator_list") else True:
                self.visit(ch)

    def mark_doc(self, node):
        b = getattr(node, "body", [])
        if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
            self.doc_ids.add(id(b[0].value))

    def visit_Module(self, node):
        self.mark_doc(node)
        for st in node.body:
            if isinstance(st, (ast.Assign, ast.AnnAssign)):
                names = [t.id for t in (st.targets if isinstance(st, ast.Assign) else [st.target]) if isinstance(t, ast.Name)]
                val = getattr(st, "value", None)
                if any(SKIP_ASSIGN.search(n) for n in names):
                    continue
                if any(n.endswith("_JS") for n in names) and val is not None:
                    self.scan_script(val, names[0])
                    continue
            self.visit(st)

    def scan_script(self, val: ast.AST, name: str) -> None:
        """A page script held in a module-level string: its SST( uses are routed; its single-quoted literals that read as text are the script's own words."""
        for n in ast.walk(val):
            s = literal_text(n) if isinstance(n, (ast.Constant, ast.JoinedStr)) else None
            if s is None or id(n) in self.doc_ids:
                continue
            if isinstance(n, ast.JoinedStr):
                continue            # the Constant parts inside are walked on their own
            self.routed += len(SST_RX.findall(s))
            for m in JS_SQ_RX.finditer(s):
                after = s[max(0, m.start() - 5):m.start()]
                if SST_RX.search(after) or not reads_as_text(m.group(1)):
                    continue
                if re.search(r"[A-Za-z]\.[A-Za-z]|^[a-z-]+$|^[a-z]+:[a-z]+", m.group(1)):
                    continue        # a dotted key, a lone lowercase name, a selector-like word
                self.script.append((n.lineno, name, m.group(1)[:90]))

    def visit_Constant(self, node):
        if self.skip_depth or id(node) in self.doc_ids or not isinstance(node.value, str):
            return
        self.note(node, node.value)

    def visit_JoinedStr(self, node):
        if self.skip_depth:
            return
        s = literal_text(node)
        if s is not None:
            self.note(node, s)
        for v in node.values:           # a call inside a field is still a call
            if isinstance(v, ast.FormattedValue):
                self.visit(v.value)

    def visit_Call(self, node):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        is_t = (isinstance(f, ast.Name) and f.id in T_NAMES) or (isinstance(f, ast.Attribute) and f.attr in T_ATTRS and isinstance(f.value, ast.Name) and f.value.id in {"_i18n", "i18n"})
        if is_t:
            if node.args and (literal_text(node.args[0]) is not None or isinstance(node.args[0], (ast.IfExp, ast.BinOp))):
                self.routed += 1
            self.skip_depth += 1            # the key expression is a key, whatever its parts look like
            for a in node.args[:1]:
                self.visit(a)
            self.skip_depth -= 1
            for a in node.args[1:]:
                self.visit(a)
            for k in node.keywords:
                self.visit(k.value)
            return
        skip = (isinstance(f, ast.Name) and name in SKIP_CALLS) or (isinstance(f, ast.Attribute) and name in SKIP_ATTRS)
        self.visit(f)
        if skip:
            self.skip_depth += 1
        for a in node.args:
            self.visit(a)
        for k in node.keywords:
            self.visit(k.value)
        if skip:
            self.skip_depth -= 1

    def visit_Compare(self, node):
        self.skip_depth += 1
        self.generic_visit(node)
        self.skip_depth -= 1

    def visit_Subscript(self, node):
        self.visit(node.value)
        self.skip_depth += 1
        self.visit(node.slice)
        self.skip_depth -= 1

    def visit_Dict(self, node):
        for k, v in zip(node.keys, node.values):
            if k is not None:
                self.skip_depth += 1
                self.visit(k)
                self.skip_depth -= 1
            self.visit(v)

    def visit_Raise(self, node):
        self.skip_depth += 1
        self.generic_visit(node)
        self.skip_depth -= 1

    visit_Assert = visit_Raise


def scan_file(path: Path) -> Scan | None:
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    sc = Scan(src)
    sc.visit(tree)
    return sc


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "-"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Page text routed through the string table, by module (see the module docstring).")
    ap.add_argument("files", nargs="*", help="files relative to the checkout (default: the page modules)")
    ap.add_argument("--list", action="store_true", help="list each unrouted text with its file and line")
    ap.add_argument("--functions", type=int, default=0, metavar="N", help="the N functions of each module with the most unrouted texts")
    a = ap.parse_args(argv)
    files = list(a.files) or list(PAGE_MODULES)
    rows: dict[str, Scan] = {}
    for rel in files:
        sc = scan_file(ROOT / rel)
        if sc is None:
            print(f"i18n_report: {rel}: cannot be read or parsed", file=sys.stderr)
            continue
        rows[rel] = sc
    print(f"{'module':<34}{'routed':>8}{'unrouted':>10}{'script':>8}{'coverage':>10}")
    for rel, sc in rows.items():
        r, u, j = sc.routed, len(sc.unrouted), len(sc.script)
        print(f"{rel.removeprefix('stackshot/web/'):<34}{r:>8}{u:>10}{j:>8}{pct(r, r + u + j):>10}")
    if not a.files:
        print()
        print(f"{'group':<34}{'routed':>8}{'unrouted':>10}{'script':>8}{'coverage':>10}")
        for label, mods in GROUPS:
            r = sum(rows[m].routed for m in mods if m in rows)
            u = sum(len(rows[m].unrouted) for m in mods if m in rows)
            j = sum(len(rows[m].script) for m in mods if m in rows)
            print(f"{label:<34}{r:>8}{u:>10}{j:>8}{pct(r, r + u + j):>10}")
    if a.functions:
        for rel, sc in rows.items():
            c = Counter(fn for _ln, fn, _s in sc.unrouted)
            if c:
                print(f"\n{rel}: functions with the most unrouted texts")
                for fn, n in c.most_common(a.functions):
                    print(f"  {n:>4}  {fn}")
    if a.list:
        for rel, sc in rows.items():
            for ln, fn, s in sc.unrouted:
                print(f"{rel}:{ln}: [{fn}] {s}")
            for ln, fn, s in sc.script:
                print(f"{rel}:{ln}: [script {fn}] {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
