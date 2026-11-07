"""Scenario test for the nightly rulebook scan (tools/rulebook_scan.py step 4c part 5) on fixture files, a fixture tool schema,
fixture `sala --help` and `sala op --help` texts and a fixture retired-terms list: no live files, no sala, no server, no network; the
delivery is replaced by a recorder.

Covers: a parameter a tool does not take (the call form, the `tool, name=` form, the codemode object form, a multi-line call in a fenced
block) and a tool the server does not register (stackshot_<tool>(…)); a sala flag its verb does not list, a verb it does not have, a flag
of `sala op <verb>` that verb does not take; the mentions that are valid and must not be flagged (every real parameter, placeholders and
string values with an `=` inside, prose that only says "update" or "sala web", a flag an alias line lists, `sala reboot --go` quoted
in another verb's section, a placeholder verb after `sala op`); the retired-terms list over the same files, tolerated when absent;
the tool names and parameters read from the real server.py by `ast` and the real `sala --help` shape; grouping (one note per file, to
its keeper, the findings of a file together); no repeat (the same unchanged finding is not sent twice, a note carries only what is new
and counts the older ones, a fixed finding that comes back is sent again, a delivery that failed is tried again); the audit's `scan`
verb and the timer unit; the CLI.

    tests/run-suite rulebook_scan        → exit 0 / 1"""
import atexit, json, os, re, shutil, subprocess, sys, pathlib, tempfile

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="rulescan-"); T = pathlib.Path(tmp)
atexit.register(shutil.rmtree, tmp, ignore_errors=True)      # the scratch folder goes however the run ends
(T / "state").mkdir()
(T / "stackshot.toml").write_text(f'[instance]\ntimezone = "Asia/Dubai"\n[paths]\nstate = "{tmp}/state"\nsecrets = "{tmp}/secrets"\nstore = "{tmp}/store"\n', encoding="utf-8")
os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

import rulebook_scan as rs

# ---- fixtures: what exists
SCHEMA = {"update": ["item_id", "subject", "next", "needs", "mover", "sender", "hold", "wake"], "create": ["subject", "description", "project", "mover", "sender"],
          "message": ["to", "text", "sender"], "get": ["item_id"], "anchors": ["project", "sender"]}
(T / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
HELP = """salamander — the operator for Claude Code (fixture)

  salamander spawn  [NAME] [--mandate FILE|TEXT] [--lane L]
                                     (--brief FILE and --prompt TEXT: the mandate's older names, kept as aliases)
  salamander spawn  --suggest-name
  salamander spawn  --list
  salamander retire NAME [--keep-web] [--force]   end a session for good
  salamander reboot --go   clean reboot
  salamander note "<next step>" | --clear | --list     leave this pane its next step
  salamander op <verb> [args…] --from NAME --words "<Oliver's words>"   queue a fleet operation: recycle [--update] [--force] · retire NAME [--keep-web] [--force]
                                     (a reboot is not queued: Oliver runs `sala reboot --go`;
  salamander reauth NAME             the sign-in link
"""
OPHELP = """  salamander op <verb> [args…] --from NAME --words "<Oliver's words>"   queue one operation (the verbs below)
  salamander op --plan <verb> [args…]                                   the plan alone
  salamander op --list                                                  the queue
verbs:
  recycle [--update] [--force]              "recycle claude"
  retire NAME [--keep-web] [--force]
  rename OLD NEW
  lane <lane> <session>… | <lane> --all | default <lane>
"""
(T / "help.txt").write_text(HELP, encoding="utf-8"); (T / "ophelp.txt").write_text(OPHELP, encoding="utf-8")
(T / "terms.toml").write_text('[[term]]\ntext = "steward role"\nuse = "the back agents"\n\n[[term]]\npattern = "\\\\bpane owner\\\\b"\nuse = "mover"\n', encoding="utf-8")

# ---- the pieces
h = rs.parse_help(HELP, OPHELP)
check("help: the verbs are the lines that open with `salamander <verb>`", set(h.verbs) >= {"spawn", "retire", "reboot", "note", "op", "reauth"} and "web" not in h.verbs, sorted(h.verbs))
check("help: a verb's flags are its line's and its continuations'", {"--mandate", "--brief", "--list", "--suggest-name"} <= h.verbs["spawn"] and "--force" not in h.verbs["spawn"], h.verbs["spawn"])
check("help: a flag quoted inside another section counts for its verb", "--go" in h.verbs["reboot"])
check("op help: its own flags, then each verb's", {"--from", "--words", "--plan", "--list"} <= h.op_general and h.op_verbs["retire"] == {"--keep-web", "--force"} and set(h.op_verbs) == {"recycle", "retire", "rename", "lane"}, (h.op_general, h.op_verbs))
check("tools: the real server.py's @mcp.tool definitions are read with ast", {"update", "create", "message", "get", "complete", "anchors"} <= set(rs.server_tools(pathlib.Path(STACK, "server.py"))) and "mover" in rs.server_tools(pathlib.Path(STACK, "server.py"))["update"])
check("tools: a function's own parameters, never self", all("self" not in v for v in rs.server_tools(pathlib.Path(STACK, "server.py")).values()))
check("params: name= at the top level only; values, strings, placeholders and nested objects are not read",
      rs._top_params('item_id="board#1", needs=["a", "b=c"], work={"x": 1, y=2}, mover=<the mover=x>, sender="a, owner=b"') == ["item_id", "needs", "work", "mover", "sender"],
      rs._top_params('item_id="board#1", needs=["a", "b=c"], work={"x": 1, y=2}, mover=<the mover=x>, sender="a, owner=b"'))
check("params: the codemode object form's keys, quoted or not", rs._top_params('{item_id: "board#1", "owner": "x", next: {a: 1}}') == ["item_id", "owner", "next"], rs._top_params('{item_id: "board#1", "owner": "x", next: {a: 1}}'))

# ---- 1. a stale tool parameter, the other tool shapes, and what must not be flagged
STALE = """# Rules

A call: `update(item_id="board#9", owner="ops-x", sender="me")` moves it.
The `tool, name=` form: `update, owner=<session>` and the tool `create(subject="s", description="d", project="p", mover="m", sender="me")` is fine.
Through the portal: `codemode.stackshot_update({item_id: "board#9", "owner": "x", next: "n"})` and `stackshot_gone(item_id="board#9")`.
A `stackshot_update(item_id="board#9", mover="a")` is current, so is `message(to="projects/<slug>", text="a, owner=b", sender="me")`.

```
update(item_id="board#9",
       needs=["decision"],
       reason="x",
       sender="me")
```
"""
sc = lambda text, terms=None: rs.scan_text("f.md", text, SCHEMA, h, terms or [])
fs = sc(STALE)
by = {(f.kind, f.text) for f in fs}
check("a stale tool parameter: update(…owner=…) is a finding naming the parameter and what update takes",
      any(f.kind == "param" and f.line == 3 and "owner" in f.problem and "mover" in f.exists and "item_id" in f.exists for f in fs), [(f.line, f.text) for f in fs])
check("…the `tool, name=` form: `update, owner=<session>`", any(f.kind == "param" and f.line == 4 and f.text == "update, …owner=…" for f in fs), [(f.line, f.text) for f in fs])
check("…the codemode object form: a key the tool does not take, and not the ones it takes", any(f.line == 5 and f.kind == "param" and "owner" in f.problem for f in fs)
      and not any(f.line == 5 and f.kind == "param" and ("item_id" in f.problem or "next" in f.problem) for f in fs), [(f.line, f.problem) for f in fs])
check("…a tool the server does not register: stackshot_gone( names it and lists the tools", any(f.kind == "tool" and f.line == 5 and "gone" in f.problem and "update" in f.exists for f in fs), [(f.line, f.problem) for f in fs])
check("…a multi-line call in a fenced block: `reason=` is no parameter of update", any(f.kind == "param" and f.line == 9 and "reason" in f.problem for f in fs), [(f.line, f.problem) for f in fs])
check("every valid mention is left alone: real parameters, a string with `owner=` inside, a placeholder, the prefixed call, create(…mover=…)",
      not any(f.line in (4,) and "create" in f.text for f in fs) and not any(f.line == 6 for f in fs) and len([f for f in fs if f.line == 3]) == 1, [(f.line, f.text) for f in fs])
check("…and nothing else is found: exactly the five stale mentions", len(fs) == 5, [(f.line, f.kind, f.problem) for f in fs])
check("prose that says update, message or get with no code around it is not read", sc("Please update the page and get the message; the update tool takes owner and next.\n") == [])
check("a line is a finding by its text, not its place: the key has no line number", all(str(f.line) not in f.key.split("|")[0] for f in fs) and fs[0].key == f"{fs[0].kind}|{fs[0].text}|{fs[0].problem}")
check("no schema at all (the server unreadable): nothing about tools is said", rs.scan_text("f.md", STALE, {}, h) == [])

# ---- 2. sala: a missing flag, a missing verb, op's flags; the valid ones
SALA = """Run `sala spawn --nonsense` or `sala spawn --list` or `sala spawn NAME --brief f.md` (an alias the help lists).
`sala retire NAME --keep-web --bogus`, and `salamander note --done 3` which the help does not list.
Queue it: `sala op retire NAME --from me --words "w" --keep-web`, `sala op rename OLD NEW --force` and `sala op <verb> … --from <you> --words "<his words>"`.
`sala op frobnicate X --from me` and `sala web --go` and `sala reboot --go` and `sala --help`.
```
$ sala spawn NAME --mandate m.md \\
      --lane max --typo
sala op --plan lane max s1
```
Prose: the sala web UI shows sessions; run sala spawn --list in a pane.
"""
fs = sc(SALA)
P = [(f.line, f.kind, f.problem) for f in fs]
check("a missing sala flag: `sala spawn --nonsense` is a finding naming the flag and the flags the help lists", any(f.kind == "flag" and f.line == 1 and f.text == "sala spawn --nonsense" and "--mandate" in f.exists for f in fs), P)
check("…the valid flags of the same line are not flagged (--list, --brief, an alias the help lists)", not any(f.line == 1 and ("--list" in f.text or "--brief" in f.text) for f in fs), P)
check("…`sala retire … --bogus` flagged, --keep-web not", any(f.line == 2 and f.kind == "flag" and "--bogus" in f.text for f in fs) and not any("--keep-web" in f.text and f.line == 2 and f.kind == "flag" and "--bogus" not in f.text for f in fs), P)
check("…a flag the help does not list but the verb has (note --done) is a finding: the help is what exists", any(f.line == 2 and "--done" in f.text for f in fs), P)
check("sala op: --from, --words and the verb's own flags are fine; a flag of another op verb is not (rename takes no --force)",
      not any(f.line == 3 and "retire" in f.text for f in fs) and any(f.line == 3 and f.kind == "flag" and "rename" in f.text and "--force" in f.text for f in fs), P)
check("sala op with a placeholder verb: the generic form passes", not any(f.line == 3 and "<verb>" in f.text for f in fs) and len([f for f in fs if f.line == 3]) == 1, P)
check("a verb sala does not have, at the start of a command, or followed by a flag", any(f.line == 4 and f.kind == "verb" and "frobnicate" in f.text for f in fs) and any(f.line == 4 and f.kind == "verb" and "'web'" in f.problem for f in fs), P)
check("…`sala reboot --go` (listed under reboot) and `sala --help` are fine", not any(f.line == 4 and "reboot" in f.text for f in fs), P)
check("a fenced command with a trailing backslash is one command: --typo found, --mandate and --lane not", any(f.line == 6 and "--typo" in f.text for f in fs) and not any(f.line == 6 and "--lane" in f.text for f in fs), P)
check("`sala op --plan lane max s1` is fine", not any(f.line == 8 for f in fs), P)
check("prose outside code (the sala web UI, run sala spawn --list in a pane) is not read", not any(f.line == 10 for f in fs), P)

# a bare `--` ends sala's flags: what follows is the wrapped command's own arguments, which sala passes through
hl = rs.parse_help(HELP + "  salamander lane exec <lane> [--dry-run] -- <command…>   run a command in a lane\n", OPHELP)
sl = lambda text: rs.scan_text("f.md", text, SCHEMA, hl, [])
fs = sl('`sala lane exec lane-example -- claude --permission-mode auto --cloud "<brief>"`\n')
check("a bare `--` ends sala's flags: `sala lane exec <lane> -- claude --permission-mode auto --cloud …` gives no finding", fs == [], [(f.kind, f.text) for f in fs])
fs = sl("`sala lane --bogus`\n")
check("…a flag before any `--` is still read: `sala lane --bogus` is a finding", [(f.kind, f.text) for f in fs] == [("flag", "sala lane --bogus")], [(f.kind, f.text) for f in fs])
fs = sl("`sala lane exec x -- claude --cloud`\n")
check("…`sala lane exec x -- claude --cloud` gives none", fs == [], [(f.kind, f.text) for f in fs])

# ---- 3. the retired terms
terms = rs.load_terms(T / "terms.toml")
check("terms: [[term]] tables, literal and pattern, with what to say", [t[1] for t in terms] == ["steward role", "\\bpane owner\\b"] and terms[0][2] == "the back agents", terms)
fs = rs.scan_text("f.md", "Ask the Steward Role.\nThe pane owner decides; the panes owners do not.\nClean line.\n", SCHEMA, h, terms)
check("terms: a retired term in a file is a finding with the line and the replacement, whatever the case", [(f.line, f.kind) for f in fs] == [(1, "term"), (2, "term")] and fs[1].exists == "mover", [(f.line, f.problem, f.exists) for f in fs])
check("terms: a file that is absent reads as no terms", rs.load_terms(T / "nope.toml") == [])

# ---- 4. the run: grouping, keepers, no repeat
RULES = T / "hub" / "RULES.md"; ROLE = T / "hub" / "roles" / "CLAUDE.md"; SKILL = T / "skills" / "x" / "SKILL.md"; CLEAN = T / "hub" / "roles" / "clean.md"
for p, body in ((RULES, 'one `update(item_id="board#9", owner="x")` two `sala spawn --nonsense` three `stackshot_gone(a=1)`\n'),
                (ROLE, 'a role: `message(to="p", text="t", sender="s", owner="x")`\n'),
                (SKILL, 'a skill: `sala op retire NAME --from me --words "w"` and `sala note --done 1`\n'),
                (CLEAN, 'all fine: `update(item_id="board#9", mover="x")` and `sala spawn --list`\n')):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body, encoding="utf-8")
(T / "lib").mkdir(); (T / "lib" / "note.sh").write_text('#   salamander note --done <id>\\n#   salamander note --list [--archived]\\n', encoding="utf-8")      # sala's code takes --done; its spawn.sh has no --nonsense
(T / "lib" / "spawn.sh").write_text('# salamander spawn [--list] [--mandate F]\\n', encoding="utf-8")
(T / "hub" / "RULES.md.bak").write_text('`update(owner="x")`', encoding="utf-8")
CFG = {"files": [{"glob": f"{T}/hub/RULES.md", "keeper": "heron-engineer"}, {"glob": f"{T}/hub/roles/**/*.md", "keeper": "heron-engineer"},
                 {"glob": f"{T}/hub/*", "keeper": "nobody"}, {"glob": f"{T}/skills/**/SKILL.md", "keeper": "tern-keeper"}],
       "terms": T / "terms.toml", "server": T / "none.py", "sala": "sala-never-run", "help_verbs": [], "sender": "stackshot rulebook scan", "enabled": True,
       "sala_lib": T / "lib", "sala_keeper": "plover-engineer"}
SRC = dict(schema=T / "schema.json", help_main=T / "help.txt", help_op=T / "ophelp.txt")
sent = []; ok = [True]
def deliver(to, text, sender): sent.append((to, text, sender)); return ok[0], "[200] delivered" if ok[0] else "[503] down"
ST = T / "sent.json"
files = rs.collect(CFG["files"])
check("collect: each file once, by the first table that names it; a .bak is never read",
      sorted((p.name, k) for p, k in files) == sorted([("RULES.md", "heron-engineer"), ("CLAUDE.md", "heron-engineer"), ("clean.md", "heron-engineer"), ("SKILL.md", "tern-keeper")]), [(p.name, k) for p, k in files])

r = rs.run(CFG, deliver=deliver, state=ST, today="Tue Oct 27th", **SRC)
check("run: 4 files read, findings in 3, a clean file says nothing", r["files"] == 4 and set(map(os.path.basename, r["sent"])) == {"RULES.md", "CLAUDE.md", "SKILL.md"} and r["held"] == [], r)
check("grouping: one note per file, never one per finding", len(sent) == 3 and sorted(os.path.basename(x) for x in r["sent"]) == ["CLAUDE.md", "RULES.md", "SKILL.md"], [(s[0], s[1][:80]) for s in sent])
notes = {re.search(r"(\S+\.md) names", s[1]).group(1): s for s in sent}
n = notes[str(RULES)]
check("…the three findings of RULES.md are in its one note, each with its line, text, problem and what exists", n[1].count("\nL1 · ") == 3 and "owner" in n[1] and "stackshot_gone(" in n[1] and "--nonsense" in n[1] and "takes:" in n[1], n[1])
check("…addressed to the file's keeper, from the scan, with the date as Oliver reads it", n[0] == "heron-engineer" and n[2] == "stackshot rulebook scan" and "(Tue Oct 27th)" in n[1], n[:1])
check("…a sala flag the keeper's file names gets the advice that sala's help can be behind: check lib/<verb>.sh first, the fix may be sala's help (keeper plover-engineer)",
      "may be right" in n[1] and "~/salamander/lib/<verb>.sh" in n[1] and CFG["sala_keeper"] in n[1], n[1])
check("…a note with no sala finding does not carry that advice", "~/salamander/lib" not in notes[str(ROLE)][1], notes[str(ROLE)][1])
check("…`sala note --done` is in sala's code (lib/note.sh) and not in the help: a help-text gap, addressed to the sala engineer instead of the file's keeper, saying the mention is right",
      notes[str(SKILL)][0] == "plover-engineer" and "help text is behind" in notes[str(SKILL)][1] and "--done" in notes[str(SKILL)][1] and "--clear, --list" in notes[str(SKILL)][1], notes[str(SKILL)])
check("…and `sala spawn --nonsense`, which lib/spawn.sh does not take, stays with the file's keeper", "--nonsense" in n[1] and n[0] == "heron-engineer", n)
check("…a note is within the server's cap", all(len(s[1]) < rs.MSG_MAX for s in sent))
st = json.loads(ST.read_text()); check("the state file keeps, per file, the keys sent (no clean file)", set(map(os.path.basename, st)) == {"RULES.md", "CLAUDE.md", "SKILL.md#help-gap"} and len(st[str(RULES)]["keys"]) == 3, st)

sent.clear()
r = rs.run(CFG, deliver=deliver, state=ST, today="Wed Oct 28th", **SRC)
check("no repeat: the same unchanged findings the next night send nothing", sent == [] and r["sent"] == [] and len(r["quiet"]) == 3, (sent, r["quiet"]))

RULES.write_text(RULES.read_text() + 'four `get(item_id="x", wake="y")`\n', encoding="utf-8")        # one new stale mention, on a new line
r = rs.run(CFG, deliver=deliver, state=ST, today="Thu Oct 29th", **SRC)
check("a new finding is sent alone, in its file's note, with the count of the older ones still open", len(sent) == 1 and sent[0][1].count("\nL") == 1 and "wake" in sent[0][1] and "3 earlier findings" in sent[0][1], sent)
sent.clear()
RULES.write_text(RULES.read_text().replace('three `stackshot_gone(a=1)`', 'three `stackshot_gone(a=1)` '), encoding="utf-8")                # an edit that moves nothing a finding is made of
r = rs.run(CFG, deliver=deliver, state=ST, today="Fri Oct 30th", **SRC)
check("a change elsewhere in the file (nothing a finding is made of) sends nothing", sent == [], sent)
RULES.write_text('pushed down\n\n' + RULES.read_text(), encoding="utf-8")
r = rs.run(CFG, deliver=deliver, state=ST, today="Sat Oct 31st", **SRC)
check("…and a finding that only moved to another line is the same finding: nothing sent", sent == [], sent)

RULES.write_text(RULES.read_text().replace('owner="x")` two', 'mover="x")` two'), encoding="utf-8")             # fixed: that finding is gone
r = rs.run(CFG, deliver=deliver, state=ST, today="Sun Nov 1st", **SRC)
st = json.loads(ST.read_text())
check("a fixed finding drops out of the state, and sends nothing", sent == [] and len(st[str(RULES)]["keys"]) == 3, st[str(RULES)])
RULES.write_text(RULES.read_text().replace('mover="x")` two', 'owner="x")` two'), encoding="utf-8")             # it comes back
r = rs.run(CFG, deliver=deliver, state=ST, today="Mon Nov 2nd", **SRC)
check("…and sent again when it comes back", len(sent) == 1 and "owner" in sent[0][1] and "3 earlier" in sent[0][1] and "Mon Nov 2nd" in sent[0][1], sent)
sent.clear()

ROLE.write_text(ROLE.read_text() + 'again `update(item_id="a", owner="b")`\n', encoding="utf-8")
ok[0] = False
r = rs.run(CFG, deliver=deliver, state=ST, today="Tue Nov 3rd", **SRC)
check("a delivery that fails is not recorded: it is reported and not counted as sent", len(sent) == 1 and r["held"] == [str(ROLE)] and any("not delivered to heron-engineer" in x for x in r["notes"]), (r["held"], r["notes"]))
ok[0] = True; sent.clear()
r = rs.run(CFG, deliver=deliver, state=ST, today="Wed Nov 4th", **SRC)
check("…and tried again the next night: the finding the failed night had, with the older one counted", len(sent) == 1 and sent[0][1].count("\nL") == 1 and "1 earlier finding " in sent[0][1] and r["held"] == [], sent)
sent.clear()

r = rs.run(CFG, dry=True, deliver=deliver, state=T / "dry.json", **SRC); ROLE.write_text('clean\n', encoding="utf-8")
check("a dry run sends nothing and writes no state", sent == [] and not (T / "dry.json").exists())
rep = rs.report(r, True).split("\n")
skill_i = rep.index(str(SKILL))
skill_rows = [l for l in rep[skill_i + 1:] if l.startswith("  L")]
check("a dry run labels what a real run would send to sala's keeper: `sala note --done` (in lib/note.sh, not in the help) carries (help-text gap → plover-engineer)",
      any("--done" in l and l.endswith("(help-text gap → plover-engineer)") for l in skill_rows), skill_rows)
rules_rows = [l for l in rep[rep.index(str(RULES)) + 1:] if l.startswith("  L")][:3]
check("…and a finding that stays with the file's keeper (`sala spawn --nonsense`) is not labelled", any("--nonsense" in l for l in rules_rows) and not any("help-text gap" in l for l in rules_rows), rules_rows)
os.remove(ST)
r = rs.run(CFG, deliver=deliver, state=ST, today="Thu Nov 5th", **SRC)
check("with no state file everything is new: notes for the files with findings", len(sent) == 2 and not any("earlier" in s[1] for s in sent), [s[1][:60] for s in sent])
sent.clear()

# ---- 4b. an unreadable sala help between two good nights: one send in total
empty = T / "empty.txt"; empty.write_text("")
X = T / "x" / "X.md"; X.parent.mkdir(); X.write_text('a stale flag `sala spawn --nonsense` and a stale param `update(item_id="a", owner="b")`\n', encoding="utf-8")
CX = dict(CFG, files=[{"glob": str(X), "keeper": "heron-engineer"}]); XS = T / "x-sent.json"
sent.clear()
rs.run(CX, deliver=deliver, state=XS, today="Mon Nov 9th", **SRC)
check("help gap: the first good night sends its one note, with both findings", len(sent) == 1 and sent[0][1].count("\nL") == 2, sent)
sent.clear()
r = rs.run(CX, deliver=deliver, state=XS, today="Tue Nov 10th", **{**SRC, "help_main": empty, "help_op": empty})
st = json.loads(XS.read_text())
check("…a night with `sala --help` empty sends nothing and keeps the earlier night's verb and flag keys", sent == [] and any(k.startswith("flag|") for k in st[str(X)]["keys"]) and any(k.startswith("param|") for k in st[str(X)]["keys"]), st)
r = rs.run(CX, deliver=deliver, state=XS, today="Wed Nov 11th", **SRC)
check("…and the next good night does not send them again: one send in total", sent == [] and len(st[str(X)]["keys"]) == 2 and r["quiet"] == [str(X)], (sent, r["quiet"]))
XO = dict(CX, help_verbs=["op"])
sent.clear()
# only the op help empty (sala op --help asked for and not read): the same
rs.run_help = lambda sala, verb="": HELP if not verb else ""
r = rs.run(XO, deliver=deliver, state=XS, today="Thu Nov 12th", schema=T / "schema.json")
check("…and an empty `sala op --help` (asked for) is the same: nothing sent, the keys kept", sent == [] and any("op --help gave nothing" in x for x in r["notes"]) and len(json.loads(XS.read_text())[str(X)]["keys"]) == 2, (sent, r["notes"]))
rs.run_help = lambda sala, verb="": HELP if not verb else OPHELP
r = rs.run(XO, deliver=deliver, state=XS, today="Fri Nov 13th", schema=T / "schema.json")
check("…then a good night with both helps read: still nothing new", sent == [] and r["quiet"] == [str(X)], (sent, r["quiet"]))

# ---- 4c. the first failed delivery ends the sending; the rest hold for the next night
Y1 = T / "y" / "Y1.md"; Y2 = T / "y" / "Y2.md"; Y1.parent.mkdir()
Y1.write_text('`update(item_id="a", owner="b")`\n', encoding="utf-8"); Y2.write_text('`update(item_id="a", owner="c")`\n', encoding="utf-8")
CY = dict(CFG, files=[{"glob": str(T / "y" / "*.md"), "keeper": "heron-engineer"}]); YS = T / "y-sent.json"
sent.clear(); ok[0] = False
r = rs.run(CY, deliver=deliver, state=YS, today="Mon Nov 23rd", **SRC)
check("a failed delivery ends the night's sending: one attempt, the other file held and not tried", len(sent) == 1 and sorted(map(os.path.basename, r["held"])) == ["Y1.md", "Y2.md"], (sent, r["held"]))
check("…and said so", any("held for the next night" in x for x in r["notes"]), r["notes"])
sent.clear(); ok[0] = True
r = rs.run(CY, deliver=deliver, state=YS, today="Tue Nov 24th", **SRC)
check("…the next night sends both", len(sent) == 2 and r["held"] == [], sent)

# ---- 4d. a dry run makes no directory
check("no state directory is made by asking for the state file's path or by a dry run", not (T / "state" / "rulebook-scan").exists() and rs.state_file().parent == T / "state" / "rulebook-scan")

# ---- 5. the terms file absent, an unreadable sala, a file that cannot be read
CFG2 = dict(CFG, terms=T / "no-terms.toml")
r = rs.run(CFG2, dry=True, deliver=deliver, state=T / "x.json", **{**SRC, "terms": None})
check("no retired-terms file: that check is skipped and said so, the rest runs", any("no retired-terms file" in x and "skipped" in x for x in r["notes"]) and r["findings"] > 0, r["notes"])
r = rs.run(CFG2, dry=True, deliver=deliver, state=T / "x.json", **{**SRC, "help_main": empty, "help_op": empty})
check("sala's help unreadable: said once, and no verb or flag is called stale", any("sala --help gave nothing" in x for x in r["notes"]) and all(f.kind not in ("verb", "flag") for v in r["found"].values() for f in v), r["notes"])

# ---- 6. the settings, the CLI, the audit's verb, the unit
cfg = rs.settings()
check("settings: with no [rulebook_scan], off, no set of files (no default glob), the default keeper",
      cfg["enabled"] is False and cfg["files"] == [] and cfg["help_verbs"] == ["op"] and cfg["terms"].name == "retired_terms.toml"
      and cfg["sala_keeper"] == rs.SALA_KEEPER and str(cfg["sala_lib"]).endswith("/salamander/lib"), cfg)
r = rs.run(cfg, dry=True, deliver=deliver, state=T / "nofiles.json", **SRC)
check("no [[rulebook_scan.files]] table: nothing is scanned, nothing is sent, and one line says so", r["files"] == 0 and r["findings"] == 0 and r["sent"] == []
      and r["notes"] == [rs.NO_FILES_NOTE] and "nothing is scanned" in rs.report(r, True), r)
conf = T / "stackshot.toml"
conf.write_text(conf.read_text() + f'[rulebook_scan]\nenabled = true\nterms = "{T}/terms.toml"\nsala = "x-sala"\nhelp_verbs = []\n[[rulebook_scan.files]]\nglob = "{T}/hub/RULES.md"\nkeeper = "k1"\n', encoding="utf-8")
import config; config.CFG.update(config.load(config.PATH))
cfg = rs.settings()
check("settings: every path and the keeper are config values", cfg["enabled"] is True and cfg["files"] == [{"glob": f"{T}/hub/RULES.md", "keeper": "k1"}] and cfg["terms"] == T / "terms.toml" and cfg["sala"] == "x-sala" and cfg["help_verbs"] == [], cfg)

def cli(*a, script="tools/rulebook_scan.py", **env):
    r = subprocess.run([sys.executable, os.path.join(STACK, script), *a], capture_output=True, text=True, env={**os.environ, **env}, timeout=120)
    return r.returncode, r.stdout, r.stderr
srcs = ["--schema", str(T / "schema.json"), "--sala-help", str(T / "help.txt"), "--op-help", str(T / "ophelp.txt")]
RULES.write_text('`update(item_id="board#9", owner="x")` and `sala spawn --nonsense`\n', encoding="utf-8")
rc, out, err = cli("run", "--dry-run", *srcs)
check("CLI: --dry-run prints each file's findings with line, text, problem and what exists, sends nothing, exit 0", rc == 0 and f"{RULES}" in out and "L1 · update(…owner=…)" in out and "dry run" in out, (rc, out[:500], err[:300]))
off = T / "off.toml"; off.write_text(re.sub(r"enabled = true", "enabled = false", conf.read_text()), encoding="utf-8")
rc, out, err = cli("run", *srcs, STACKSHOT_CONFIG=str(off))
check("CLI: with [rulebook_scan] enabled = false it says so and does nothing, exit 0", rc == 0 and "not enabled" in out and not (T / "state/rulebook-scan/sent.json").exists(), (rc, out, err[:200]))
rc, out, err = cli("scan", "--dry-run", *srcs, script="audit.py")
check("audit.py scan --dry-run is the same scan", rc == 0 and "L1 · update(…owner=…)" in out, (rc, out[:300], err[:300]))
rc, out, err = cli("run", "--bogus")
check("CLI: an option it does not know: usage, exit 2", rc == 2 and "usage" in err, (rc, err))
rc, out, err = cli("bogus", script="audit.py")
check("audit.py's usage names scan", rc == 2 and "scan [--dry-run]" in err, err)
unit = pathlib.Path(STACK, "units/stackshot-audit.service.in").read_text(encoding="utf-8")
check("the timer's unit runs the scan after the run (ExecStartPost), and a failed scan never fails the unit",
      re.search(r"(?m)^ExecStartPost=-/usr/bin/timeout 300 @UV@ run --locked --script @CHECKOUT@/tools/rulebook_scan\.py run$", unit) and "ExecStart=@UV@ run --locked --script @CHECKOUT@/audit.py cue scheduled" in unit
      and "ExecStartPre" not in re.sub(r"(?m)^#.*$", "", unit) and unit.index("ExecStart=@UV@") < unit.index("ExecStartPost="), unit)
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("the example config documents [rulebook_scan], off by default", re.search(r"(?m)^\[rulebook_scan\][^\n]*\nenabled = false", ex) is not None)

shutil.rmtree(tmp, ignore_errors=True)
check("the suite leaves no scratch folder behind: its own rulescan- folder is gone", not os.path.exists(tmp), tmp)
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
