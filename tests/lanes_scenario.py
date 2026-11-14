#!/usr/bin/env python3
"""Scenario test for lanes.py: the fleet tool's lane names, read from its lane-names file and never spelled in stackshot.
Fixture data only: made-up lanes in a scratch folder, named by STACKSHOT_LANE_NAMES (and, for the default place, by a scratch HOME); no tool is run,
no network, no server.

  1  the file: a lane word is resolved by its code or by an alias (case and spaces folded) to the code; a word the file does not list is the word as written; the display name is the file's,
     the code when the lane has none; `shown` puts the code and its display name together, only the code when they are the same word; codes() keeps the file's order
  2  the fixed words: the old codes of the renames made so far read as their current ones while the file is missing and while it does not list them; the floor is read before the file, so a file that lists an old code as a lane, or as an alias of another lane, does not split one lane in two
  3  the cache: the file is parsed once while its modification time and size stand, again when either changes (a rewrite, a rewrite to the same size with a later mtime), and an edit is seen at the next call
  4  no data: a missing file, a directory in its place, text that is not JSON, JSON of another shape (no "lanes", a lane with no code, aliases that are not words) each show the code, resolve by the fixed words,
     and print one line to standard error for that state, not one for each call; a file that reads again and then breaks again says so again
  4b a malformed row (no code, aliases that are not words, not an object) is left out with one line on standard error, the other rows are kept; a file with no "lanes" list gives no data
  5  where: STACKSHOT_LANE_NAMES wins when set and not empty; otherwise the tool's own place under HOME
  6  the tool's other lane files (the usage-limit watch's json with its per-pane lane, the sign-in watch's state with its `<lane>.seen` keys) are read by no code of stackshot: a reader added later must
     read each lane word through lanes.code (a first code and its current one are one lane), and this check then says so (the lane record, lanes.tsv and lane-default, is read by service/checks.py's lane_record: tests/check_scenario.py)

    python3 tests/lanes_scenario.py        → exit 0 / 1"""
import contextlib, io, json, os, pathlib, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, STACK); sys.path.insert(0, SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="lanes-"); T = pathlib.Path(tmp)
from stackshot.core import lanes

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

F = T / "lane-names.json"
os.environ[lanes.ENV] = str(F)
_n = [0]
def write(obj, text=None):
    """The file, written whole, with an mtime that is always later than the last one's (a rewrite inside one clock tick would otherwise look unchanged)."""
    F.write_text(text if text is not None else json.dumps(obj), encoding="utf-8")
    _n[0] += 10; os.utime(F, (1_000_000_000 + _n[0], 1_000_000_000 + _n[0]))
def err(f):
    """(f's result, what it printed to standard error)."""
    b = io.StringIO()
    with contextlib.redirect_stderr(b):
        r = f()
    return r, b.getvalue()
def fresh():
    lanes._said.clear(); lanes._cache.update(path=None, sig=None, lanes=None)

MADE_UP = {"lanes": [{"code": "gold-1", "display": "Gilded", "aliases": ["old-gold", "Gold"]},
                     {"code": "silver", "display": "Argent", "aliases": []},
                     {"code": "plain", "display": "", "aliases": []},
                     {"code": "aws-platform", "display": "Cloud", "aliases": ["awsplatform"]}]}

# ---- 1. the file
fresh(); write(MADE_UP)
check("1 file: a code is its own word", lanes.code("gold-1") == "gold-1" and lanes.code("silver") == "silver")
check("1 file: an alias reads as the code of its lane, case and spaces folded", lanes.code("old-gold") == "gold-1" and lanes.code("  GOLD ") == "gold-1" and lanes.code("Old-Gold") == "gold-1")
check("1 file: a word the file does not list is the word as written (stripped)", lanes.code(" nothing-here ") == "nothing-here" and lanes.code("") == "" and lanes.code(None) == "")
check("1 file: the display name is the file's, whichever word names the lane", lanes.display_name("gold-1") == "Gilded" and lanes.display_name("old-gold") == "Gilded" and lanes.display_name("silver") == "Argent")
check("1 file: a lane with no display name shows its code; an unlisted word shows itself", lanes.display_name("plain") == "plain" and lanes.display_name("nothing-here") == "nothing-here")
check("1 file: shown = code (display), the code alone when they are the same word",
      lanes.shown("old-gold") == "gold-1 (Gilded)" and lanes.shown("plain") == "plain" and lanes.shown("nothing-here") == "nothing-here", (lanes.shown("old-gold"), lanes.shown("plain")))
check("1 file: codes() are the file's, in its order", lanes.codes() == ["gold-1", "silver", "plain", "aws-platform"], lanes.codes())
check("1 file: nothing was printed for a good file", err(lambda: lanes.code("silver"))[1] == "")

# ---- 2. the fixed words
fresh(); write(MADE_UP)
check("2 fixed: awsplatform reads as aws-platform (the file lists it here)", lanes.code("awsplatform") == "aws-platform")
check("2 fixed: the first codes of the subscription lanes read as the current ones while the file does not list them",
      lanes.code("max") == "subscription-1" and lanes.code("team") == "subscription-2" and lanes.code("Max") == "subscription-1", (lanes.code("max"), lanes.code("team")))
check("2 fixed: …and show as the code, never as a display name the file does not give", lanes.display_name("max") == "subscription-1" and lanes.shown("max") == "subscription-1")
write({"lanes": [{"code": "sub-x", "display": "Made Up", "aliases": []}]})
check("2 fixed: awsplatform reads as aws-platform when the file does not list it", lanes.code("awsplatform") == "aws-platform")
write({"lanes": [{"code": "sub-x", "display": "Made Up", "aliases": ["max"]}]})
check("2 fixed: the floor is read before the file: a file alias of an old word does not take the word from the floor", lanes.code("max") == "subscription-1" and lanes.code("sub-x") == "sub-x", (lanes.code("max"), lanes.code("sub-x")))
for old, new in (("max", "subscription-1"), ("team", "subscription-2")):
    write({"lanes": [{"code": "api", "display": "Plain", "aliases": []}, {"code": old, "display": "Old Row", "aliases": ["older"]}]})
    check(f"2 fixed: a file that still lists {old} as a code: one lane with {new}, not two", lanes.code(old) == lanes.code(new) == new, (lanes.code(old), lanes.code(new)))
    check(f"2 fixed: …listed under the new code, with the old row's display name and aliases", lanes.codes() == ["api", new] and lanes.display_name(old) == lanes.display_name(new) == "Old Row" and lanes.code("older") == new, (lanes.codes(), lanes.display_name(new)))
    write({"lanes": [{"code": old, "display": "Old Row", "aliases": []}, {"code": new, "display": "New Row", "aliases": [old]}]})
    check(f"2 fixed: …and when the file lists both, the new code's row gives the display name", lanes.codes() == [new] and lanes.display_name(old) == "New Row", (lanes.codes(), lanes.display_name(old)))
    write({"lanes": [{"code": new, "display": "New Row", "aliases": []}, {"code": old, "display": "Old Row", "aliases": []}]})
    check(f"2 fixed: …the same with the old row second", lanes.codes() == [new] and lanes.display_name(old) == "New Row", (lanes.codes(), lanes.display_name(old)))
check("2 fixed: the codes a refusal can name with no file are the floor's targets and the plain ones, each once",
      lanes.FALLBACK_CODES == ("aws-platform", "subscription-1", "subscription-2", "api", "sdk") and len(set(lanes.FALLBACK_CODES)) == len(lanes.FALLBACK_CODES), lanes.FALLBACK_CODES)
check("2 fixed: the default lane is a code, not a display name", lanes.DEFAULT_CODE == "subscription-1")

# ---- 3. the cache
fresh(); write(MADE_UP)
parsed = [0]; _real_parse = lanes._parse
def counting(raw): parsed[0] += 1; return _real_parse(raw)
lanes._parse = counting
try:
    for w in ("gold-1", "old-gold", "silver", "nothing-here"): lanes.display_name(w); lanes.code(w); lanes.codes()
    check("3 cache: twelve reads while the file stands, one parse", parsed[0] == 1, parsed[0])
    write({"lanes": [{"code": "gold-1", "display": "Gilded", "aliases": ["old-gold", "Gold"]}, {"code": "silver", "display": "Argent", "aliases": []}, {"code": "plain", "display": "", "aliases": []}, {"code": "aws-platform", "display": "Cloud", "aliases": []}]})
    check("3 cache: a rewrite is read at the next call", lanes.code("awsplatform") == "aws-platform" and parsed[0] == 2 and lanes.display_name("aws-platform") == "Cloud", parsed[0])
    write(json.loads(F.read_text()), text=F.read_text())   # the same bytes, a later mtime
    lanes.codes()
    check("3 cache: a later mtime alone makes the file be read again", parsed[0] == 3, parsed[0])
    renamed = F.read_text().replace("Argent", "Silver")                       # another text of the same size, written at a later mtime
    write(None, text=renamed)
    check("3 cache: a changed display name shows at the next call", lanes.display_name("silver") == "Silver" and parsed[0] == 4, (lanes.display_name("silver"), parsed[0]))
finally:
    lanes._parse = _real_parse

# ---- 4. no data
def no_data(label, setup):
    """setup() puts the file in the state; the code is the word, the display is the code, a fixed word still resolves, one line on stderr for any number of calls."""
    fresh(); setup()
    out = []
    r, e1 = err(lambda: [lanes.code("gold-1"), lanes.display_name("gold-1"), lanes.shown("gold-1"), lanes.code("max"), lanes.display_name("max"), lanes.codes()])
    for _ in range(5): out.append(err(lambda: (lanes.code("old-gold"), lanes.display_name("silver")))[1])
    check(f"4 no data ({label}): the word is the code, shown as the code, a fixed word still resolves, no lane listed",
          r == ["gold-1", "gold-1", "gold-1", "subscription-1", "subscription-1", []], r)
    check(f"4 no data ({label}): one line on standard error, naming the file and that lanes show as their code, and nothing more for the calls after",
          e1.count("\n") == 1 and str(F) in e1 and "shown by their code" in e1 and not any(out), (e1, out))
if F.exists(): F.unlink()
no_data("missing", lambda: None)
check("4 no data (missing): the line says it is missing", "missing" in err(lambda: (fresh(), lanes.code("x")))[1])
def as_dir(): F.mkdir()
no_data("a directory in its place", as_dir)
F.rmdir()
no_data("not JSON", lambda: write(None, text="{not json"))
no_data("no lanes list", lambda: write({"lane": []}))
no_data("a list, not an object", lambda: write([{"code": "a"}]))
fresh(); write(None, text="{")
_, e_a = err(lambda: lanes.code("x"))
write(MADE_UP)
r_ok, e_ok = err(lambda: lanes.display_name("gold-1"))
write(None, text="{")
_, e_b = err(lambda: lanes.code("x"))
check("4 no data: a file that reads again, then breaks again, says so again (a line for each break, none for the good read)", e_a.count("\n") == 1 and r_ok == "Gilded" and e_ok == "" and e_b.count("\n") == 1, (e_a, r_ok, e_ok, e_b))

# ---- 4b. a malformed row is left out, the rest are read
fresh()
write({"lanes": [{"display": "No Code", "aliases": []}, {"code": "good-1", "display": "Good", "aliases": ["g1"]}, "not an object",
                 {"code": "bad-aliases", "display": "Bad", "aliases": [1, 2]}, {"code": "  ", "display": "Blank"}, {"code": "good-2", "display": "Second", "aliases": []}]})
r, e = err(lambda: [lanes.codes(), lanes.display_name("g1"), lanes.code("g1"), lanes.display_name("good-2"), lanes.code("bad-aliases"), lanes.display_name("bad-aliases")])
check("4b rows: the good rows are read, the malformed ones are not lanes", r == [["good-1", "good-2"], "Good", "good-1", "Second", "bad-aliases", "bad-aliases"], r)
check("4b rows: one line on standard error for each skipped row, saying which and that the others are read",
      e.count("\n") == 4 and "row 1 has no code" in e and "row 3 has no code" in e and "row 4 (bad-aliases) has aliases" in e and "row 5 has no code" in e and "the other rows are read" in e and "shown by their code" not in e, e)
check("4b rows: nothing more is said for the calls after", err(lambda: (lanes.codes(), lanes.code("g1")))[1] == "")
write({"lanes": [{"code": "only-good", "display": "Only", "aliases": []}]})
r, e = err(lambda: lanes.codes())
check("4b rows: a clean rewrite reads and says nothing", r == ["only-good"] and e == "", (r, e))
write({"lanes": [{"display": "x"}]})
r, e = err(lambda: [lanes.codes(), lanes.display_name("x")])
check("4b rows: a file whose every row is malformed lists no lane (the code is shown) and names the skipped row", r == [[], "x"] and e.count("\n") == 1 and "row 1 has no code" in e, (r, e))

# ---- 5. where
fresh(); write(MADE_UP)
home = T / "home"; dflt = home / ".local/state/salamander/lane-names.json"; dflt.parent.mkdir(parents=True)
dflt.write_text(json.dumps({"lanes": [{"code": "home-lane", "display": "From Home", "aliases": []}]}), encoding="utf-8")
old_home = os.environ.get("HOME"); os.environ["HOME"] = str(home)
try:
    check("5 where: STACKSHOT_LANE_NAMES wins when it is set", lanes.path() == F and lanes.display_name("gold-1") == "Gilded", lanes.path())
    os.environ[lanes.ENV] = "  "
    check("5 where: an empty value is not set: the tool's place under HOME", lanes.path() == dflt and lanes.display_name("home-lane") == "From Home", lanes.path())
    del os.environ[lanes.ENV]
    check("5 where: unset, the same; and a file changed place is read from the new place", lanes.path() == dflt and lanes.codes() == ["home-lane"], lanes.codes())
    os.environ[lanes.ENV] = f"~/{dflt.relative_to(home)}"
    check("5 where: a ~ in the value is the home folder", lanes.path() == dflt, lanes.path())
finally:
    if old_home is None: os.environ.pop("HOME", None)
    else: os.environ["HOME"] = old_home

# ---- 6. no code of stackshot reads the tool's limit file or sign-in state: when one does, it must compare lane words by lanes.code, and this check is edited with it
src = [f for f in pathlib.Path(STACK).rglob("*.py") if not {".git", ".claude", ".venv", "tests", "__pycache__"} & set(f.relative_to(STACK).parts)]
import re
_str = re.compile(r"""["'][^"'\n]*(?:lane-signin|salamander-limit|limit_file)[^"'\n]*["']|["'][\w-]*\.seen["']|\.seen["']""")      # a string literal naming one of the files or its keys (a comment, a method called seen, are no reader)
readers = sorted(f"{f.relative_to(STACK)}:{n}" for f in src for n, ln in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if _str.search(ln.split("  #", 1)[0]) and not ln.lstrip().startswith("#"))
check("6 other files: no stackshot code reads the limit file or the sign-in state (their lane words are the tool's first and current codes both)", len(src) > 20 and not readers, (len(src), readers))

print(("ok" if not fails else "FAILED") + f": lanes scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
