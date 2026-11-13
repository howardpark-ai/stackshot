"""Scenario test for the tools' text files (stackshot/web/tools/text/*.md, read by stackshot/web/tools/textfile.py): fixture files in a temp folder, then the real files.
Stdlib and the package only, no store, no network.

Covers: the section format (a header per section, wrapped lines joined by one space, the `lead` and `trail` flags for an edge space, blank lines between sections but
never inside one, only comments before the first section, a bad header, an empty or repeated section); the {{NAME}} placeholders (a value, a piece of the same file, a
late value passed when the text is asked for, a piece of the shared file through the parent, single braces left alone); what fails at load (a placeholder nothing
defines, a value passed and never used, a late name never used, a section the shared file has too, pieces that refer to each other in a circle); what is asked for
and not there; the leftovers report (`unused`, `unused_values`); and the real files: every tool module loads, no section of them is a leftover, no shared value is
unused, and no file carries Hangul, a machine placeholder or the sala name (a fresh install reads them).

    tests/run-suite tool_text_files        → exit 0 / 1"""
import importlib, os, pathlib, re, sys, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, STACK); sys.path.insert(0, SCR); sys.path.insert(0, os.path.join(STACK, "tools"))
import _scratch
BASE = pathlib.Path(_scratch.mkdtemp(prefix="ttfiles-base-")); tempfile.tempdir = str(BASE)     # all scratch under BASE; the last check asserts it is empty again
T = pathlib.Path(_scratch.mkdtemp(prefix="ttfiles-"))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web.tools import textfile as tf


def put(name, text):
    (T / f"{name}.md").write_text(text, encoding="utf-8")


def fails_with(name, text, *args, **kw):
    """The message of the TextFileError loading `name` fixture text raises, or None when it loads."""
    put(name, text)
    try:
        tf.load(name, *args, directory=T, **kw)
    except tf.TextFileError as e:
        return str(e)
    return None


# ================================================================= 1. the section format
put("a", """# a comment before the first section

## description get
Read one item
by id, wrapped at a space.

## param ITEM
The item id.
## text TAIL trail
ends with a space
## text HEAD lead
 starts with a space
""")
a = tf.load("a", directory=T)
check("a description is its lines joined by one space, the header and the comment above the first section are not text", a.description("get") == "Read one item by id, wrapped at a space.", a.description("get"))
check("a param and a piece are asked for by name, and a section may follow the one before it with no blank line", a.param("ITEM") == "The item id.", a.param("ITEM"))
check("`trail` ends a text with one space and `lead` starts it with one (a line cannot show an edge space)", a.piece("TAIL") == "ends with a space " and a.piece("HEAD") == "  starts with a space", (a.piece("TAIL"), a.piece("HEAD")))
for label, text, want in (
        ("a blank line inside a section", "## text X\none\n\ntwo\n", "blank line inside"),
        ("text before the first section", "stray\n## text X\none\n", "before the first section"),
        ("a header with an unknown kind", "## widget X\none\n", "section header reads"),
        ("a header with no name", "## text\none\n", "section header reads"),
        ("an empty section", "## text X\n## text Y\none\n", "is empty"),
        ("a section twice", "## text X\none\n## text X\ntwo\n", "there twice"),
        ("a flag that is not lead or trail", "## text X middle\none\n", "section header reads")):
    m = fails_with("bad", text)
    check(f"{label} does not load", m is not None and want in m, m)

# ================================================================= 2. placeholders
put("p", """## text WORD
one
## text BOTH
{{COUNT}} of {{WORD}} and {{LATE}}; a {single} brace and a {{ lone pair stay
## description tool
{{BOTH}}.
""")
p = tf.load("p", {"COUNT": "3"}, late=("LATE",), directory=T)
check("a placeholder is replaced by a value, by a piece of the same file or by a late value given when the text is asked for", p.description("tool", LATE="now") == "3 of one and now; a {single} brace and a {{ lone pair stay.", p.description("tool", LATE="now"))
check("single braces and a lone `{{` are plain text", "{single}" in p.piece("BOTH", LATE="x") and "{{ lone pair" in p.piece("BOTH", LATE="x"))
check("the same text asked for with another late value is not taken from a cache", p.piece("BOTH", LATE="a") != p.piece("BOTH", LATE="b"))
try:
    p.piece("BOTH")
    got = None
except tf.TextFileError as e:
    got = str(e)
check("a late name left out when the text is asked for fails, naming it", got is not None and "LATE" in got, got)
try:
    p.piece("BOTH", LATE="x", OTHER="y")
    got = None
except tf.TextFileError as e:
    got = str(e)
check("a late value the file does not declare fails", got is not None and "OTHER" in got, got)
for call in (lambda: p.description("nothing"), lambda: p.param("NOTHING"), lambda: p.piece("NOTHING")):
    try:
        call(); got = None
    except tf.TextFileError as e:
        got = str(e)
    check("asking for a section the file does not hold fails", got is not None and "no " in got, got)

# ================================================================= 3. what fails at load
m = fails_with("u1", "## text X\n{{NOWHERE}}\n")
check("a placeholder no value, piece or late name defines fails at load, naming the section and the placeholder", m is not None and "NOWHERE" in m and "text X" in m, m)
m = fails_with("u2", "## text X\none\n", {"UNUSED": "1"})
check("a value that is passed and that no text uses fails at load", m is not None and "UNUSED" in m, m)
m = fails_with("u3", "## text X\none\n", late=("SPARE",))
check("a late name that is declared and that no text uses fails at load", m is not None and "SPARE" in m, m)
m = fails_with("u4", "## text X\n{{Y}}\n## text Y\n{{X}}\n")
check("pieces that refer to each other in a circle fail at load", m is not None and "circle" in m, m)
m = fails_with("u5", "## text X\n{{X}}\n")
check("a piece that names itself fails at load", m is not None and "circle" in m, m)
check("a value used by a placeholder, and a piece used by another piece, load", fails_with("u6", "## text X\n{{V}} {{Y}}\n## text Y\ny\n", {"V": "1"}) is None)

# ================================================================= 4. the shared file and the parent
put("shared", "## text COMMON\nthe common {{N}} words\n## text SPARE\nused by nobody here\n## param WHO\nwho acts\n")
sh = tf.load("shared", {"N": "7", "NOT_USED_HERE": "x"}, directory=T, common=True)
put("child", "## description tool\n{{COMMON}} and {{OWN}} and {{N}}\n## text OWN\nown\n")
c = tf.load("child", directory=T, parent=sh)
check("a shared value or piece is read through the parent by the child's placeholders, the own piece first", c.description("tool") == "the common 7 words and own and 7", c.description("tool"))
check("a param of the shared file is asked for through the child", c.param("WHO") == "who acts")
check("the shared file may hold values that it does not use itself (`common`)", True)
m = fails_with("dup", "## text COMMON\nagain\n## description tool\nx\n", parent=sh)
check("a section the shared file has too is refused in a child: say it once", m is not None and "shared file too" in m, m)
try:
    tf.load("shared", {"N": "7", "UNUSED": "1"}, directory=T)
    got = None
except tf.TextFileError as e:
    got = str(e)
check("without `common` an unused value in the shared file fails too", got is not None and "UNUSED" in got, got)

# ================================================================= 5. the leftovers report
put("l", "## description a\nuses {{USED}}\n## text USED\nx\n## text DEAD\nnobody names me\n## param NEVER\nnobody asks\n")
lf = tf.load("l", directory=T)
lf.description("a")
check("`unused` lists the sections nothing asks for or names, by kind and name, and not a piece another section names", lf.unused() == ["param NEVER", "text DEAD"], lf.unused())
check("`unused_values` lists the values no text names", tf.load("shared", {"N": "7", "NOT_USED_HERE": "x"}, directory=T, common=True).unused_values([c]) == ["NOT_USED_HERE"])

# ================================================================= 6. the real files
TEXT_DIR = pathlib.Path(STACK, "stackshot", "web", "tools", "text")
mods = ["anchors", "brief", "complete", "create", "get", "message", "route", "rules", "sessions", "update"]
check("there is a text file for each tool module and the shared one, and nothing else in the folder", sorted(p.name for p in TEXT_DIR.iterdir()) == sorted([f"{m}.md" for m in mods] + ["shared.md"]), sorted(p.name for p in TEXT_DIR.iterdir()))
import tool_text as tt
tt.live_snapshot()          # builds the server on a throwaway config, so every module has asked for its text
real = {m: importlib.import_module(f"stackshot.web.tools.{m}")._T for m in mods}
shared = importlib.import_module("stackshot.web.tools.text")._T
check("every tool module loads its own file", all(isinstance(t, tf.Texts) for t in real.values()))
dead = {m: t.unused() for m, t in real.items() if t.unused()}
check("no section of a tool's file is a leftover: each is asked for by its module or named by another section", not dead, dead)
check("no section of the shared file is a leftover", not shared.unused(list(real.values())), shared.unused(list(real.values())))
check("no shared value is unused by every file", not shared.unused_values(list(real.values())), shared.unused_values(list(real.values())))
hangul = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF))) + "]")     # Hangul by code point: the file itself carries none
text_all = {p.name: p.read_text(encoding="utf-8") for p in TEXT_DIR.glob("*.md")}
check("no text file carries Hangul, not even as an escape", not [n for n, t in text_all.items() if hangul.search(t) or re.search(r"\\u(?:[1][1-9a-f][0-9a-f]{2}|3[13][0-9a-f]{2}|[a-d][0-9a-f]{3})", t, re.I)], [n for n, t in text_all.items() if hangul.search(t)])
check("no text file names a machine placeholder or sala (a fresh install reads them)", not [n for n, t in text_all.items() if re.search(r"box-[a-d]\b|salamander|\bsala\b", t, re.I)], [n for n, t in text_all.items() if re.search(r"box-[a-d]\b|salamander|\bsala\b", t, re.I)])
check("every text file ends with one newline and has no trailing space on a line (a space at an edge is a `lead` or `trail` flag)", all(t.endswith("\n") and not t.endswith("\n\n") and not re.search(r"[ \t]+$", t, re.M) for t in text_all.values()), [n for n, t in text_all.items() if not t.endswith("\n") or t.endswith("\n\n") or re.search(r"[ \t]+$", t, re.M)])

DEPLOY = pathlib.Path(STACK, "deploy.sh").read_text(encoding="utf-8")
check("deploy.sh restarts the server for a change of a text file (the files are read at import)", re.search(r"^\s*stackshot/web/tools/text/\*\.md\) server=1 ;;", DEPLOY, re.M) is not None)
check("release.sh names the text files in session_need (nothing: the snapshot carries the notice), apart from the docs", "stackshot/web/tools/text/*.md)" in pathlib.Path(STACK, "release.sh").read_text(encoding="utf-8"))

import shutil; shutil.rmtree(T, ignore_errors=True); tt.cleanup()
left = sorted(p.name for p in BASE.iterdir())
check("a run leaves nothing behind: its scratch folder is removed at exit", not left, left)
shutil.rmtree(BASE, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": tool text files scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
