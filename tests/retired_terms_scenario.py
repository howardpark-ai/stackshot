"""Scenario test for the retired-terms lint (the board item gate 2, tools/retired_terms.py with tests/retired_terms.toml) — fixture files in a temp dir, then the
repository itself. Stdlib only, no store, no network.

Covers: a retired word in a string literal is a hit that names the file, the line, the term and what to say instead; matching is whole-word and
case-insensitive (owner_name, ownership are other words); an allow phrase excuses a hit inside it and no other occurrence in the same text; comments,
docstrings, string statements, stderr prints and a lone identifier (a stored key) are not text; a json file is read by its values, minus skip_keys, and a
hit there carries the line; any other file is read by line; globs keep to one directory unless `**`; the command's exit codes (0 clean, 1 a hit, 2 a bad
config). Then the real list over the real repository: clean on main, with the snapshot of the tools' text in the scan, and both owner and steward listed
with their replacement.

    tests/run-suite retired_terms        → exit 0 / 1"""
import contextlib, io, json, os, pathlib, sys, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, os.path.join(STACK, "tools"))
import retired_terms as rt

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

import _scratch
BASE = pathlib.Path(_scratch.mkdtemp(prefix="retiredtest-base-")); tempfile.tempdir = str(BASE)   # all scratch under BASE; the last check asserts it is empty again
T = pathlib.Path(_scratch.mkdtemp(prefix="retiredtest-"))
CONF = T / "terms.toml"
CONF.write_text('''
[[term]]
retired = "owner"
use = "mover or keeper of record"
allow = ["the owner", "metadata.owner", "=whole owner"]
[[term]]
retired = "steward"
use = "the router"
[[scan]]
files = ["*.py", "data.json"]
skip_keys = ["name"]
[[scan]]
files = ["hooks/*"]
[[scan]]
files = ["tool"]
kind = "python"
[[scan]]
files = ["pkg/*.py"]
[[scan]]
files = ["docs/*.md"]
skip_terms = ["owner"]
''')
(T / "hooks").mkdir(); (T / "sub").mkdir(); (T / "pkg").mkdir(); (T / "docs").mkdir()
(T / "a.py").write_text('''"""The owner of a module docstring is not text a session reads."""
import sys
x = "stored: " + "owner"                                # a lone identifier is a key
y = "tell the owner and the Steward"                    # line 4: the owner is allowed, the Steward is not
z = f"keeper {x} of OWNER session {x}"                  # line 5: a hit, upper case
w = "owner_name and ownership and co-owner-ish"         # line 6: owner_name, ownership are other words; co-owner-ish has owner as a word
v = "the owner and then an owner again"                 # line 7: the first is allowed, the second is not
# a comment about the owner is not text
print("owner log line", file=sys.stderr)                # a log line is not read by a session
def f():
    """The owner in a function docstring."""
    """a string statement under it, about the owner"""
    return "metadata.owner is a stored key, and an Owner is not: owner"      # line 13: the second and third are hits
g = "whole owner"                                       # line 14: an `=` entry excuses the whole literal
h = "a whole owner here"                                # line 15: ... and not the same words inside a sentence
''')
(T / "data.json").write_text(json.dumps({"tools": {"get": {"description": "reads the item and its owner"}, "params": [{"name": "owner", "description": "ok"}]}}, indent=2) + "\n")
(T / "hooks" / "h.sh").write_text("echo hello\necho the steward says hi\n")
(T / "sub" / "deep.py").write_text('q = "owner out of the glob"\n')
(T / "pkg" / "m.py").write_text('p = "the owner and then an owner step"\nq = "a steward"\n')   # the package scan carries no skip_terms: the second owner and the steward are hits
(T / "docs" / "g.md").write_text("The owner answers.\nThe steward does not.\n")             # the docs scan skips owner only: the steward is a hit
(T / "tool").write_text('print("steward in a script with no suffix"); r = "a steward"\n')
hits = rt.lint(T, CONF)
key = lambda h: (h.file, h.line, h.term)
got = sorted(key(h) for h in hits)
want = sorted([("a.py", 4, "steward"), ("a.py", 5, "owner"), ("a.py", 6, "owner"), ("a.py", 7, "owner"), ("a.py", 13, "owner"), ("a.py", 13, "owner"), ("a.py", 15, "owner"),
               ("data.json", 4, "owner"), ("hooks/h.sh", 2, "steward"), ("tool", 1, "steward"), ("tool", 1, "steward"),
               ("pkg/m.py", 1, "owner"), ("pkg/m.py", 2, "steward"), ("docs/g.md", 2, "steward")])
check("the lint finds exactly the hits that are retired words in text, with their lines", got == want, (got, want))
check("a hit carries what to say instead", all(h.use for h in hits) and {h.term: h.use for h in hits} == {"owner": "mover or keeper of record", "steward": "the router"}, [h.use for h in hits])
check("matching is case-insensitive (OWNER) and whole-word (owner_name and ownership are not hits)", ("a.py", 5, "owner") in got and sum(1 for h in hits if h.line == 6) == 1, got)
check("an allow phrase excuses its own occurrence only: the second owner of a text is a hit", sum(1 for h in hits if h.line == 7) == 1 and sum(1 for h in hits if h.line == 13) == 2, got)
check("an allow phrase that starts with `=` excuses the whole literal only: `whole owner` alone passes, inside a sentence it is a hit", not any(h.line == 14 for h in hits) and sum(1 for h in hits if h.line == 15) == 1, got)
check("a comment, a docstring, a string statement, a stderr print and a lone identifier are not text", not any(h.line in (1, 3, 8, 9, 11, 12) and h.file == "a.py" for h in hits), got)
check("a parameter called owner (skip_keys: name) is not a hit, its description would be", not any("params" in h.text for h in hits) and any("tools.get.description" in h.text for h in hits), [h.text for h in hits if h.file == "data.json"])
check("`*` stays in one directory: sub/deep.py is not scanned", not any(h.file.startswith("sub/") for h in hits), got)
check("a script with no suffix is read as python by `kind`: both its strings are hits (a print to stdout is text a session reads)", sum(1 for h in hits if h.file == "tool") == 2, got)
check("skip_terms is the docs scan's alone: owner is skipped in docs/g.md (steward is not), and is still a hit in the package scan (pkg/m.py) and in the code scans (a.py)",
      not any(h.file == "docs/g.md" and h.term == "owner" for h in hits) and ("pkg/m.py", 1, "owner") in got and ("a.py", 5, "owner") in got, got)
out = io.StringIO(); err = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    rc = rt.main(["--config", str(CONF), "--root", str(T)])
text = out.getvalue()
check("the command exits 1 on a hit and names file:line, the term and its replacement", rc == 1 and "a.py:5: retired term 'owner': say mover or keeper of record" in text and "hooks/h.sh:2: retired term 'steward': say the router" in text, (rc, text[:400]))
(T / "ok").mkdir()
(T / "ok" / "terms.toml").write_text(CONF.read_text())
(T / "ok" / "x.py").write_text('a = "the owner of the instance"\n')
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    rc_ok = rt.main(["--config", str(T / "ok" / "terms.toml"), "--root", str(T / "ok")])
check("the command exits 0 when nothing is left", rc_ok == 0, rc_ok)
(T / "bad.toml").write_text("[[term]]\nretired = \"x\"\n")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    rc_bad = rt.main(["--config", str(T / "bad.toml"), "--root", str(T)])
check("a config without `use` is exit 2, not a clean pass", rc_bad == 2, rc_bad)

# ---- the real list over the real repository
live = rt.lint(pathlib.Path(STACK), pathlib.Path(SCR, "retired_terms.toml"))
check("the repository carries no retired term the list does not excuse (owner, steward)", not live, [str(h) for h in live][:10])
terms, scans = rt.load(pathlib.Path(SCR, "retired_terms.toml"))
byname = {t.retired: t for t in terms}
check("the live list names owner (mover), keeper of record (mover, then, created by) and steward (the router), each with its replacement", {"owner", "keeper of record", "steward"} <= set(byname) and "mover" in byname["owner"].use and "created by" in byname["keeper of record"].use and "router" in byname["steward"].use, [(t.retired, t.use) for t in terms])
scanned = " ".join(f for sc in scans for f in sc.get("files", []))
check("the live scan reads the tools' text snapshot, the root scripts' strings, the package's modules (stackshot/**/*.py) and the guides (docs/*.md)", "tests/tool_text.snapshot.json" in scanned and "*.py" in scanned and "stackshot/**/*.py" in scanned and "docs/*.md" in scanned, scanned)
planted = T / "plant"; planted.mkdir()
for f in ("pages.py", "client.py", "server.py", "whatschanged.py"):
    (planted / f).write_text('LINE = "hello steward"\n')
(planted / "tests").mkdir(); (planted / "tests" / "tool_text.snapshot.json").write_text(json.dumps({"tools": {"create": {"description": "the steward"}}}, indent=2) + "\n")
planted_hits = rt.lint(planted, pathlib.Path(SCR, "retired_terms.toml"))
check("the live list, run on a tree that plants a retired word in pages.py, client.py, server.py, whatschanged.py and the snapshot, finds all five",
      sorted(h.file for h in planted_hits) == ["client.py", "pages.py", "server.py", "tests/tool_text.snapshot.json", "whatschanged.py"], [str(h) for h in planted_hits])

# the paths the REAL repository keeps its text in: a fixture that plants into a path the repository lacks passes while the real scan has a gap, so every planted
# file here is a path that exists in the repository (asserted), and the live list must reach it
REAL = ("stackshot/cli.py", "stackshot/web/server.py", "stackshot/web/ui/render.py", "stackshot/tools/migrate_model.py", "docs/item-model.md", "docs/router.md")
check("the files the scenario plants into are files of the real repository", all((pathlib.Path(STACK) / f).is_file() for f in REAL), [f for f in REAL if not (pathlib.Path(STACK) / f).is_file()])
PHRASES = ("steward", "Send with an empty box finishes the step.", "the stuck state")
for rel in REAL:
    real_plant = T / ("real-" + rel.replace("/", "_")); (real_plant / rel).parent.mkdir(parents=True)
    for phrase in PHRASES:
        (real_plant / rel).write_text(f'LINE = "a line that says {phrase} here"\nOK = "a stuck item is a failed wait"\n' if rel.endswith(".py") else f"A line that says {phrase} in a guide.\nA stuck item is a failed wait.\n")
        got = rt.lint(real_plant, pathlib.Path(SCR, "retired_terms.toml"))
        check(f"the live list finds \"{phrase}\" planted in {rel} (the real path), and only that", len(got) == 1 and got[0].file == rel and got[0].line == 1, [str(h) for h in got])
# `owner` is skipped in docs/*.md only: the same retired sense planted in a code path of the real repository is a hit (a skip_terms leaking to a code scan, or onto the package scan, would pass it)
for rel in ("stackshot/web/server.py", "stackshot/cli.py", "stackshot/tools/migrate_model.py", "server.py", "pages.py", "tests/tool_text.snapshot.json", "client/hooks/project-page.sh"):
    own = T / ("owner-" + rel.replace("/", "_")); (own / rel).parent.mkdir(parents=True)
    (own / rel).write_text(json.dumps({"tools": {"create": {"description": "the item waits on an owner step here"}}}, indent=2) + "\n" if rel.endswith(".json") else 'LINE = "the item waits on an owner step here"\nOK = "a stuck item is a failed wait"\n')
    got = rt.lint(own, pathlib.Path(SCR, "retired_terms.toml"))
    check(f"the live list reports `owner` in its retired sense planted in {rel} (the real path): it is skipped in docs only", len(got) == 1 and got[0].file == rel and got[0].term == "owner" and got[0].line in (1, 4), [str(h) for h in got])
doc_owner = T / "doc-owner"; (doc_owner / "docs").mkdir(parents=True)
(doc_owner / "docs" / "g.md").write_text("The owner answers the ask.\nThe steward does not.\n")
got = rt.lint(doc_owner, pathlib.Path(SCR, "retired_terms.toml"))
check("a guide in docs/ may say \"the owner\" for the instance's person (the scan skips that term there) and still fails on another retired word", [(h.file, h.line, h.term) for h in got] == [("docs/g.md", 2, "steward")], [str(h) for h in got])

# the stuck state (a hand-off marked stuck and raised with a "Nag again" button, [idle] stuck_to) and the waiting ladder's stuck list are retired: each is a hit in a string a session reads
check("the live list names the stuck state, Nag again and stuck_to, each with what to use instead", {"stuck state", "Nag again", "stuck_to", "stuck list"} <= set(byname) and "fleet" in byname["stuck state"].use and "fleet" in byname["Nag again"].use and "operator_session" in byname["stuck_to"].use, [(t.retired, t.use) for t in terms])
for word in ("stuck state", "Nag again", "stuck_to", "stuck list"):
    plant = T / ("plant-" + word.replace(" ", "_")); (plant / "stackshot" / "web").mkdir(parents=True)
    (plant / "stackshot" / "web" / "server.py").write_text(f'LINE = "the item is in the {word} now"\nOK = "a stuck item is a failed wait"\n')
    got = rt.lint(plant, pathlib.Path(SCR, "retired_terms.toml"))
    check(f"retired: \"{word}\" in a string of stackshot/web/server.py is a hit, and the nearby \"a stuck item\" is not", len(got) == 1 and got[0].file == "stackshot/web/server.py" and got[0].term == word, [str(h) for h in got])

# the step form's one Send (a note box that read "A note, or nothing to finish the step", an empty Send that finished the step, a draft dropped by "his Send on the step") is retired for the two buttons Done and Send note:
# each old phrase is a hit when it comes back in a string a session reads, and the replacement wording is not
STEP_SEND_TERMS = ("A note, or nothing to finish the step", "Send with an empty box finishes the step", "his Send on the step")
check("the live list names the step form's three retired Send phrases, each with the two-button wording to use instead",
      set(STEP_SEND_TERMS) <= set(byname) and all(("Done" in byname[w].use) and ("Send note" in byname[w].use or "Note (optional)" in byname[w].use) for w in STEP_SEND_TERMS), [(w, byname.get(w) and byname[w].use) for w in STEP_SEND_TERMS])
for word in STEP_SEND_TERMS:
    plant = T / ("plant-step-" + str(STEP_SEND_TERMS.index(word))); plant.mkdir()
    (plant / "server.py").write_text(f'LINE = "a close drops it, and {word} again"\nOK = "a close drops it, and so does his Done or Send note on the step"\n')
    (plant / "tests").mkdir(); (plant / "tests" / "tool_text.snapshot.json").write_text(json.dumps({"tools": {"create": {"description": f"text with {word} inside"}}}, indent=2) + "\n")
    got = rt.lint(plant, pathlib.Path(SCR, "retired_terms.toml"))
    check(f"retired: \"{word}\" in a string of server.py and in the tool-text snapshot is a hit (two, one per file), and the two-button wording beside it is not",
          sorted((h.file, h.term) for h in got) == [("server.py", word), ("tests/tool_text.snapshot.json", word)], [str(h) for h in got])

import shutil; shutil.rmtree(T, ignore_errors=True)
left = sorted(p.name for p in BASE.iterdir())
check("a run leaves nothing behind: its scratch folder is removed at exit", not left, left)
shutil.rmtree(BASE, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": retired terms scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
