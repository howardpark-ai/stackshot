"""Scenario test for the rulebook scan (run once a week, by the audit unit's first run of each week) (tools/rulebook_scan.py step 4c part 5) on fixture files, a fixture tool schema,
fixture `sala --help` and `sala op --help --full` texts and a fixture retired-terms list: no live files, no sala, no server, no network; the
delivery is replaced by a recorder.

Covers: a parameter a tool does not take (the call form, the `tool, name=` form, the codemode object form, a multi-line call in a fenced
block) and a tool the server does not register (stackshot_<tool>(…)); a sala flag its verb does not list, a verb it does not have, a flag
of `sala op <verb>` that verb does not take; the mentions that are valid and must not be flagged (every real parameter, placeholders and
string values with an `=` inside, prose that only says "update" or "sala web", a flag an alias line lists, `sala reboot --go` quoted
in another verb's section, a placeholder verb after `sala op`); the retired-terms list over the same files, tolerated when absent;
the tool names and parameters read from the real server.py by `ast` and the real `sala --help` shape; grouping (one note per file, to
its keeper, the findings of a file together); no repeat (the same unchanged finding is not sent twice, a note carries only what is new
and counts the older ones, a fixed finding that comes back is sent again, a delivery that failed is tried again); the audit's `scan`
verb and the timer unit; the weekly gate (--weekly: one scan a week, a held note does not count, concurrent runs scan once); the CLI.

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

from stackshot.tools import rulebook_scan as rs

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
check("tools: the real server.py's @mcp.tool definitions are read with ast", {"update", "create", "message", "get", "complete", "anchors"} <= set(rs.server_tools(pathlib.Path(STACK, "stackshot/web/server.py"))) and "mover" in rs.server_tools(pathlib.Path(STACK, "stackshot/web/server.py"))["update"])
check("tools: a function's own parameters, never self", all("self" not in v for v in rs.server_tools(pathlib.Path(STACK, "stackshot/web/server.py")).values()))
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

# asking op for its help is no stale mention: no verb table lists --help or --full, and both are right straight after `op`
for label, hh in (("with the op table", h), ("with the main help alone", rs.parse_help(HELP))):
    scan_op = lambda text: rs.scan_text("f.md", text, SCHEMA, hh, [])
    fs = scan_op("`sala op --help` `sala op --help --full` `sala op --full` `salamander op --help [--full]`\n")
    check(f"{label}: --help and --full straight after `op` are not reported", fs == [], [(f.kind, f.text, f.problem) for f in fs])
    fs = scan_op("`sala op --help --full --bogus`\n`sala op retire NAME --full`\n`sala op rename OLD NEW --help`\n`sala spawn --full`\n")
    check(f"{label}: a wrong flag is still reported: beside them, --full or --help anywhere else, --full on another verb",
          [(f.line, f.kind, f.flag) for f in fs] == [(1, "flag", "--bogus"), (2, "flag", "--full"), (3, "flag", "--help"), (4, "flag", "--full")], [(f.line, f.kind, f.problem) for f in fs])

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
check("no repeat: the same unchanged findings at the next scan send nothing", sent == [] and r["sent"] == [] and len(r["quiet"]) == 3, (sent, r["quiet"]))

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
check("…and tried again at the next scan: the finding the failed scan had, with the older one counted", len(sent) == 1 and sent[0][1].count("\nL") == 1 and "1 earlier finding " in sent[0][1] and r["held"] == [], sent)
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

# ---- 4b. an unreadable sala help between two good scans: one send in total
empty = T / "empty.txt"; empty.write_text("")
X = T / "x" / "X.md"; X.parent.mkdir(); X.write_text('a stale flag `sala spawn --nonsense` and a stale param `update(item_id="a", owner="b")`\n', encoding="utf-8")
CX = dict(CFG, files=[{"glob": str(X), "keeper": "heron-engineer"}]); XS = T / "x-sent.json"
sent.clear()
rs.run(CX, deliver=deliver, state=XS, today="Mon Nov 9th", **SRC)
check("help gap: the first good scan sends its one note, with both findings", len(sent) == 1 and sent[0][1].count("\nL") == 2, sent)
sent.clear()
r = rs.run(CX, deliver=deliver, state=XS, today="Tue Nov 10th", **{**SRC, "help_main": empty, "help_op": empty})
st = json.loads(XS.read_text())
check("…a scan with `sala --help` empty sends nothing and keeps the earlier scan's verb and flag keys", sent == [] and any(k.startswith("flag|") for k in st[str(X)]["keys"]) and any(k.startswith("param|") for k in st[str(X)]["keys"]), st)
r = rs.run(CX, deliver=deliver, state=XS, today="Wed Nov 11th", **SRC)
check("…and the next good scan does not send them again: one send in total", sent == [] and len(st[str(X)]["keys"]) == 2 and r["quiet"] == [str(X)], (sent, r["quiet"]))
XO = dict(CX, help_verbs=["op"])
sent.clear()
# only the op help empty (sala op --help --full asked for and not read): nothing is resent either
_real_find_sala = rs.find_sala
rs.find_sala = lambda name: "/fixture/sala"      # a sala exists for the checks that stand in for its help text
_REAL_RUN_HELP = rs.run_help
rs.run_help = lambda sala, verb="", full=False: HELP if not verb else ""
r = rs.run(XO, deliver=deliver, state=XS, today="Thu Nov 12th", schema=T / "schema.json")
check("…and an empty `sala op --help --full` (asked for) sends nothing new and keeps the keys", sent == [] and any("op --help --full gave nothing" in x for x in r["notes"]) and len(json.loads(XS.read_text())[str(X)]["keys"]) == 2, (sent, r["notes"]))
rs.run_help = lambda sala, verb="", full=False: HELP if not verb else OPHELP
r = rs.run(XO, deliver=deliver, state=XS, today="Fri Nov 13th", schema=T / "schema.json")
check("…then a good scan with both helps read: still nothing new", sent == [] and r["quiet"] == [str(X)], (sent, r["quiet"]))
rs.find_sala = _real_find_sala
rs.run_help = _REAL_RUN_HELP

# ---- 4b2. no sala command on the machine: its checks are skipped with one line and no error; a present one is run
import io, contextlib, stat
BIN = T / "bin"; BIN.mkdir()
FAKE = BIN / "fakesala"
(T / "shortop.txt").write_text('  salamander op <verb> [args…] --from NAME --words "<the owner\'s words>"   queue one operation\nverbs: recycle retire rename lane\n', encoding="utf-8")
FAKE.write_text('#!/bin/sh\ncase "$*" in\n'
                f'  "--help") cat "{T / "help.txt"}";;\n'
                f'  "op --help --full") cat "{T / "ophelp.txt"}";;\n'
                f'  "op --help") cat "{T / "shortop.txt"}";;\n'
                '  *) exit 2;;\nesac\n', encoding="utf-8"); FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
sent.clear(); XM = T / "x-missing.json"
CM = dict(CX, sala=str(T / "bin" / "no-such-sala"), help_verbs=["op"])
err = io.StringIO()
with contextlib.redirect_stderr(err):
    rm = rs.run(CM, deliver=deliver, state=XM, today="Sat Nov 14th", schema=T / "schema.json")
skipped = [n for n in rm["notes"] if "sala" in n]
check("4b2 no sala on the machine: one line says the sala checks were skipped, no error is printed, and the sala finding is not sent (the other finding is)",
      len(skipped) == 1 and "skipped" in skipped[0] and "No such file" not in err.getvalue() and err.getvalue() == "" and len(sent) == 1 and "--nonsense" not in sent[0][1] and "owner" in sent[0][1], (rm["notes"], err.getvalue(), sent))
check("4b2 …and a dry-run report prints that one line", sum(1 for l in rs.report(rs.run(CM, dry=True, schema=T / "schema.json"), True).splitlines() if "skipped" in l) == 1, None)
check("4b2 find_sala: a name with a slash is taken as written, a missing or non-executable one is empty",
      rs.find_sala(str(FAKE)) == str(FAKE) and rs.find_sala(str(T / "bin" / "no-such-sala")) == "" and rs.find_sala(str(T / "help.txt")) == "" and rs.find_sala("sala-never-run-xyz") == "", None)
sent.clear(); XP = T / "x-present.json"
CP = dict(CX, sala=str(FAKE), help_verbs=["op"])
rp = rs.run(CP, deliver=deliver, state=XP, today="Sun Nov 15th", schema=T / "schema.json")
check("4b2 a sala that exists is run: its help is read, the stale flag is found and sent, and no sala line is skipped", not any("skipped" in n for n in rp["notes"]) and len(sent) == 1 and "--nonsense" in sent[0][1], (rp["notes"], sent))
sent.clear()
OPF = T / "op" / "OP.md"; OPF.parent.mkdir(); OPF.write_text('`sala op frobnicate X --from me`\n', encoding="utf-8")
rp = rs.run(dict(CP, files=[{"glob": str(OPF), "keeper": "heron-engineer"}]), dry=True, deliver=deliver, state=T / "op.json", schema=T / "schema.json")
check("4b2 …the real run_help asks for `op --help --full`: a verb `sala op` does not have is found",
      [(f.kind, f.text) for v in rp["found"].values() for f in v] == [("verb", "sala op frobnicate")] and not any("not checked" in n for n in rp["notes"]), (rp["found"], rp["notes"]))

# ---- 4c. the first failed delivery ends the sending; the rest hold for the next scan
Y1 = T / "y" / "Y1.md"; Y2 = T / "y" / "Y2.md"; Y1.parent.mkdir()
Y1.write_text('`update(item_id="a", owner="b")`\n', encoding="utf-8"); Y2.write_text('`update(item_id="a", owner="c")`\n', encoding="utf-8")
CY = dict(CFG, files=[{"glob": str(T / "y" / "*.md"), "keeper": "heron-engineer"}]); YS = T / "y-sent.json"
sent.clear(); ok[0] = False
r = rs.run(CY, deliver=deliver, state=YS, today="Mon Nov 23rd", **SRC)
check("a failed delivery ends the scan's sending: one attempt, the other file held and not tried", len(sent) == 1 and sorted(map(os.path.basename, r["held"])) == ["Y1.md", "Y2.md"], (sent, r["held"]))
check("…and said so", any("held for the next scan" in x for x in r["notes"]), r["notes"])
sent.clear(); ok[0] = True
r = rs.run(CY, deliver=deliver, state=YS, today="Tue Nov 24th", **SRC)
check("…the next scan sends both", len(sent) == 2 and r["held"] == [], sent)

# ---- 4d. a dry run makes no directory
check("no state directory is made by asking for the state file's path or by a dry run", not (T / "state" / "rulebook-scan").exists() and rs.state_file().parent == T / "state" / "rulebook-scan")

# ---- 4e. the op help is read with `--full`: a short help (its verbs on one `verbs:` line, no table) is loud, and only op's own checks are off
SHORTOP = """  salamander op <verb> [args…] --from NAME --words "<the owner's words>" queue one operation (the verbs below)
  salamander op --list                                                  the queue
verbs: amber birch cedar delta
(sala op --help --full: each verb's shape, the forms that take no words)
"""
VERB_NAMES = ["amber", "birch", "cedar", "delta", "ember", "fjord", "garnet", "harbor", "iris", "juniper", "kestrel", "lumen", "maple", "nectar", "onyx", "pine"]
ROWS = [f"  {v} [--keep] [--force]                    the {v} verb\n" for v in VERB_NAMES]
HEADING = ("  reason path                               a heading for a reason on the record, not a verb\n"      # in the middle of the table, as in the real help
           "                                            `VERB --only NAME --item REF --from YOU`: the heading's continuation line\n")
FULLTAB = ("  salamander op <verb> [args…] --from NAME --words \"<the owner's words>\"   queue one operation (the verbs below)\n"
           "verbs:\n" + "".join(ROWS[:2]) + HEADING + "".join(ROWS[2:]))
check("4e the short op help parses to no op verb, the full table to all sixteen (the reason path heading is not a verb)",
      rs.op_verb_count(SHORTOP) == 0 and rs.op_verb_count(FULLTAB) == 16 and rs.op_verb_count("") == 0
      and "reason" not in rs.parse_help("", FULLTAB).op_verbs, (rs.op_verb_count(SHORTOP), rs.op_verb_count(FULLTAB)))
hf = rs.parse_help(HELP, FULLTAB)
fs = rs.scan_text("f.md", "`sala op birch --only x`\n", SCHEMA, hf, [])
check("4e the flags on the heading's continuation lines belong to no verb: not to the verb above the heading",
      hf.op_verbs["birch"] == {"--keep", "--force"} and [(f.kind, f.flag) for f in fs] == [("flag", "--only")], (hf.op_verbs["birch"], [(f.kind, f.problem) for f in fs]))
Z4 = T / "z4" / "Z4.md"; Z4.parent.mkdir()
Z4.write_text("`sala op nonsense-verb --from YOU`\n`sala op amber --bogus`\n`sala spawn --nonsense`\n`sala frobnicate --x`\n", encoding="utf-8")
CZ4 = dict(CFG, files=[{"glob": str(Z4), "keeper": "heron-engineer"}], help_verbs=["op"], sala="fixture-sala")
_real_find_sala = rs.find_sala; _REAL_RUN_HELP2 = rs.run_help
rs.find_sala = lambda name: "/fixture/sala"
calls4e = []
ops4e = lambda calls: [c for c in calls if c[0] == "op"]      # the main help's call is not the op help's
said4e = lambda r: [(f.kind, f.text) for v in r["found"].values() for f in v]
MAIN_ONLY = [("flag", "sala spawn --nonsense"), ("verb", "sala frobnicate --x")]      # what `sala --help` alone can judge
def _scan4e(full_text, plain_text):
    """One dry scan with a sala that answers `op --help --full` and `op --help` with these texts → (the result, the stderr)."""
    def run_help(sala, verb="", full=False):
        calls4e.append((verb, full))
        return HELP if not verb else (full_text if full else plain_text)
    calls4e.clear(); rs.run_help = run_help
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        r = rs.run(CZ4, dry=True, deliver=deliver, state=T / "z4.json", schema=T / "schema.json")
    return r, err.getvalue()
r4, err4e = _scan4e(SHORTOP, SHORTOP)
check("4e a short op help (both forms tried, neither has a table): loud note, and the line also goes to stderr",
      any("sala op --help --full lists no verb table" in x and "not checked" in x for x in r4["notes"]) and ops4e(calls4e) == [("op", True), ("op", False)]
      and "lists no verb table" in err4e, (r4["notes"], calls4e, err4e))
check("4e …no op verb or op flag is judged, and the checks that need only `sala --help` still run", said4e(r4) == MAIN_ONLY, said4e(r4))
r4, _ = _scan4e("", "")
check("4e …the same when the op help gives nothing", said4e(r4) == MAIN_ONLY and any("sala op --help --full gave nothing" in x for x in r4["notes"]), (said4e(r4), r4["notes"]))
r4, _ = _scan4e(SHORTOP, "")
check("4e a plain help with no table is not taken over the --full answer: the note still says what --full gave",
      any("lists no verb table" in x for x in r4["notes"]) and not any("gave nothing" in x for x in r4["notes"]), r4["notes"])
r4, _ = _scan4e(FULLTAB, SHORTOP)
check("4e the full table is read first and checked: the made-up verb and the wrong flag are found, no loud note",
      ops4e(calls4e) == [("op", True)] and not any("verb table" in x or "gave nothing" in x for x in r4["notes"])
      and said4e(r4) == [("verb", "sala op nonsense-verb"), ("flag", "sala op amber --bogus")] + MAIN_ONLY, (calls4e, said4e(r4), r4["notes"]))
r4, _ = _scan4e(SHORTOP, FULLTAB)      # an older sala: no --full, its plain help is the table
check("4e an older sala with no --full: its plain help is read as the table, and the verb is still checked",
      ops4e(calls4e) == [("op", True), ("op", False)] and ("verb", "sala op nonsense-verb") in said4e(r4) and not any("verb table" in x for x in r4["notes"]), (calls4e, r4["notes"]))
rs.find_sala = _real_find_sala; rs.run_help = _REAL_RUN_HELP2
# a bad --op-help file is named as that file, not as the command
(T / "emptyop.txt").write_text("", encoding="utf-8")
for bad, what in ((T / "emptyop.txt", "gave nothing"), (T / "shortop.txt", "lists no verb table")):
    with contextlib.redirect_stderr(io.StringIO()):
        r4 = rs.run(CZ4, dry=True, deliver=deliver, state=T / "z4.json", **{**SRC, "help_op": bad})
    said = [x for x in r4["notes"] if "not checked" in x]
    check(f"4e a --op-help file that {what}: the note names the file, not `sala op --help --full`",
          len(said) == 1 and f"the --op-help file {bad} {what}" in said[0] and "sala op --help" not in said[0], r4["notes"])
# an unread op table between two good scans: op findings are kept (not resent), the others are judged as usual
W = T / "w" / "W.md"; W.parent.mkdir(); WS = T / "w-sent.json"
CWO = dict(CFG, files=[{"glob": str(W), "keeper": "heron-engineer"}]); NOTABLE = {**SRC, "help_op": T / "shortop.txt"}
OPLINES = "`sala op frobnicate X`\n`sala op rename OLD NEW --force`\n"
keys4e = lambda: sorted(k.split("|")[1] for k in json.loads(WS.read_text())[str(W)]["keys"])
sent.clear(); W.write_text(OPLINES + "`sala spawn --nonsense`\n", encoding="utf-8")
rs.run(CWO, deliver=deliver, state=WS, today="Mon Nov 16th", **SRC)
check("4e kept keys: the good scan sends one note with the two op findings and the spawn flag", len(sent) == 1 and sent[0][1].count("\nL") == 3, sent)
sent.clear(); W.write_text(OPLINES + "`sala spawn --other`\n", encoding="utf-8")
with contextlib.redirect_stderr(io.StringIO()):
    r4 = rs.run(CWO, deliver=deliver, state=WS, today="Tue Nov 17th", **NOTABLE)
check("4e …with no op table, a new non-op finding is sent alone, the fixed one is forgotten and the op keys are kept",
      len(sent) == 1 and sent[0][1].count("\nL") == 1 and "--other" in sent[0][1]
      and keys4e() == ["sala op frobnicate", "sala op rename --force", "sala spawn --other"], (sent, keys4e()))
sent.clear()
r4 = rs.run(CWO, deliver=deliver, state=WS, today="Wed Nov 18th", **SRC)
check("4e …and the next good scan does not send the op findings again", sent == [] and r4["quiet"] == [str(W)], (sent, r4["quiet"]))
sent.clear()

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
from stackshot.core import config; config.CFG.update(config.load(config.PATH))
cfg = rs.settings()
check("settings: every path and the keeper are config values", cfg["enabled"] is True and cfg["files"] == [{"glob": f"{T}/hub/RULES.md", "keeper": "k1"}] and cfg["terms"] == T / "terms.toml" and cfg["sala"] == "x-sala" and cfg["help_verbs"] == [], cfg)

def cli(*a, script="stackshot/tools/rulebook_scan.py", **env):
    r = subprocess.run([sys.executable, os.path.join(STACK, script), *a], capture_output=True, text=True, env={**os.environ, **env}, timeout=120)
    return r.returncode, r.stdout, r.stderr
srcs = ["--schema", str(T / "schema.json"), "--sala-help", str(T / "help.txt"), "--op-help", str(T / "ophelp.txt")]
RULES.write_text('`update(item_id="board#9", owner="x")` and `sala spawn --nonsense`\n', encoding="utf-8")
rc, out, err = cli("run", "--dry-run", *srcs)
check("CLI: --dry-run prints each file's findings with line, text, problem and what exists, sends nothing, exit 0", rc == 0 and f"{RULES}" in out and "L1 · update(…owner=…)" in out and "dry run" in out, (rc, out[:500], err[:300]))
off = T / "off.toml"; off.write_text(re.sub(r"enabled = true", "enabled = false", conf.read_text()), encoding="utf-8")
rc, out, err = cli("run", *srcs, STACKSHOT_CONFIG=str(off))
check("CLI: with [rulebook_scan] enabled = false it says so and does nothing, exit 0", rc == 0 and "not enabled" in out and not (T / "state/rulebook-scan/sent.json").exists(), (rc, out, err[:200]))
rc, out, err = cli("scan", "--dry-run", *srcs, script="stackshot/audit/audit.py")
check("audit.py scan --dry-run is the same scan", rc == 0 and "L1 · update(…owner=…)" in out, (rc, out[:300], err[:300]))
rc, out, err = cli("run", "--bogus")
check("CLI: an option it does not know: usage, exit 2", rc == 2 and "usage" in err, (rc, err))
rc, out, err = cli("bogus", script="stackshot/audit/audit.py")
check("audit.py's usage names scan", rc == 2 and "scan [--weekly] [--dry-run]" in err, err)
# ---- 7. once a week: the unit's runs of one Monday-to-Sunday week scan once
import datetime as _dt, threading
from zoneinfo import ZoneInfo
check("this_week: the Monday-to-Sunday week, ISO form, in the instance timezone",
      rs.this_week(_dt.datetime(2026, 11, 22, 23, 0, tzinfo=ZoneInfo("Asia/Dubai"))) == "2026-W47" and rs.this_week(_dt.datetime(2026, 11, 23, 0, 5, tzinfo=ZoneInfo("Asia/Dubai"))) == "2026-W48"
      and rs.this_week(_dt.datetime(2026, 11, 29, 23, 0, tzinfo=ZoneInfo("Asia/Dubai"))) == "2026-W48")
WD = T / "weekly"; WD.mkdir(); WF = WD / "last-week.json"
CW = dict(CFG, files=[{"glob": f"{T}/hub/roles/clean.md", "keeper": "heron-engineer"}])
r1 = rs.run_weekly(CW, week="2026-W48", wfile=WF, deliver=deliver, state=WD / "s.json", **SRC)
r2 = rs.run_weekly(CW, week="2026-W48", wfile=WF, deliver=deliver, state=WD / "s.json", **SRC)
r3 = rs.run_weekly(CW, week="2026-W49", wfile=WF, deliver=deliver, state=WD / "s.json", **SRC)
check("weekly: the first run of a week scans, the second run of that week skips, the next week scans again",
      r1 is not None and r2 is None and r3 is not None and json.loads(WF.read_text())["week"] == "2026-W49", (r1, r2, r3))
CB = dict(CFG, files=[{"glob": f"{T}/hub/RULES.md", "keeper": "heron-engineer"}]); ok[0] = False
RULES.write_text('one `update(item_id="board#9", owner="x")`\n', encoding="utf-8")
rf = rs.run_weekly(CB, week="2026-W50", wfile=WF, deliver=deliver, state=WD / "s2.json", **SRC)
check("weekly: a scan whose note was not delivered does not record the week, so the next run tries again", rf["held"] and json.loads(WF.read_text())["week"] == "2026-W49", rf["held"])
ok[0] = True
rg = rs.run_weekly(CB, week="2026-W50", wfile=WF, deliver=deliver, state=WD / "s2.json", **SRC)
check("weekly: ...and once delivered the week is recorded", rg is not None and not rg["held"] and json.loads(WF.read_text())["week"] == "2026-W50", rg)
rd = rs.run_weekly(CB, week="2026-W51", wfile=WF, dry=True, deliver=deliver, state=WD / "s3.json", **SRC)
check("weekly: a dry run records nothing", rd is not None and json.loads(WF.read_text())["week"] == "2026-W50")
# concurrent writers: eight runs of one week started together scan once, and the week file stays whole
cnt = []
def _count(to, text, sender): cnt.append(to); return True, "[200] ok"
WF2 = WD / "conc" / "last-week.json"; outs = []
def _go(): outs.append(rs.run_weekly(CB, week="2026-W60", wfile=WF2, deliver=_count, state=WD / "conc-sent.json", **SRC))
ths = [threading.Thread(target=_go) for _ in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("weekly, concurrent runs of one week: exactly one scans and sends, the others skip, the week file is whole JSON",
      sum(x is not None for x in outs) == 1 and len(cnt) == 1 and json.loads(WF2.read_text()) == {"week": "2026-W60"} and not list(WF2.parent.glob("*.tmp")), (len(outs), cnt))
# a scan blind to sala (its help unreadable: the sala checks were skipped) leaves the week open
WF3 = WD / "blind" / "last-week.json"
rb = rs.run_weekly(CW, week="2026-W61", wfile=WF3, deliver=deliver, state=WD / "s4.json", **{**SRC, "help_main": empty, "help_op": empty})
check("weekly: a scan blind to sala (help unreadable) does not record the week", rb is not None and rb["blind"] is True and not WF3.exists(), rb)
rb2 = rs.run_weekly(CW, week="2026-W61", wfile=WF3, deliver=deliver, state=WD / "s4.json", **SRC)
check("weekly: …the next run scans again, and a good read records the week", rb2 is not None and rb2["blind"] is False and json.loads(WF3.read_text()) == {"week": "2026-W61"}, rb2)
WF3o = WD / "blind-op" / "last-week.json"
with contextlib.redirect_stderr(io.StringIO()):
    rbo = rs.run_weekly(CW, week="2026-W61", wfile=WF3o, deliver=deliver, state=WD / "s4o.json", **{**SRC, "help_op": T / "shortop.txt"})
check("weekly: a scan with only op's verb table unread does not record the week either", rbo is not None and rbo["blind"] is True and not WF3o.exists(), rbo)
# a missing or damaged week file reads as no scan this week; the scan then writes a whole one
for label, body in (("damaged", "{not json"), ("empty", ""), ("a list", "[]"), ("a number for the week", '{"week": 5}')):
    WF4 = WD / "dmg" / "last-week.json"; WF4.parent.mkdir(exist_ok=True); WF4.write_text(body, encoding="utf-8")
    rx = rs.run_weekly(CW, week="2026-W62", wfile=WF4, deliver=deliver, state=WD / "s5.json", **SRC)
    check(f"weekly: a week file that is {label} scans, then holds the week", rx is not None and json.loads(WF4.read_text()) == {"week": "2026-W62"}, (label, rx))
WF5 = WD / "fresh" / "last-week.json"
rx = rs.run_weekly(CW, week="2026-W62", wfile=WF5, deliver=deliver, state=WD / "s5.json", **SRC)
check("weekly: no week file (and no folder) scans and makes both", rx is not None and json.loads(WF5.read_text()) == {"week": "2026-W62"})
# the week key: zero-padded, ISO year at the year's end, the instance timezone when none is given
check("this_week: the week number is zero-padded", rs.this_week(_dt.datetime(2026, 1, 29, 12, 0, tzinfo=ZoneInfo("Asia/Dubai"))) == "2026-W05")
check("this_week: the year boundary follows the ISO week (2026 has a week 53; its first Monday of 2027 is week 1)",
      rs.this_week(_dt.datetime(2026, 12, 31, 12, 0, tzinfo=ZoneInfo("Asia/Dubai"))) == "2026-W53" and rs.this_week(_dt.datetime(2027, 1, 3, 23, 59, tzinfo=ZoneInfo("Asia/Dubai"))) == "2026-W53"
      and rs.this_week(_dt.datetime(2027, 1, 4, 0, 0, tzinfo=ZoneInfo("Asia/Dubai"))) == "2027-W01")
rc53 = rs.run_weekly(CW, week="2026-W53", wfile=WF5, deliver=deliver, state=WD / "s5.json", **SRC)
rc01 = rs.run_weekly(CW, week="2027-W01", wfile=WF5, deliver=deliver, state=WD / "s5.json", **SRC)
rc01b = rs.run_weekly(CW, week="2027-W01", wfile=WF5, deliver=deliver, state=WD / "s5.json", **SRC)
check("weekly: the last week of a year and the first of the next are two scans, each once", rc53 is not None and rc01 is not None and rc01b is None and json.loads(WF5.read_text()) == {"week": "2027-W01"})
_tzcalls = []; _real_tz = rs._cfg.tz
rs._cfg.tz = lambda: (_tzcalls.append(1), ZoneInfo("Pacific/Kiritimati"))[1]
try: _wk = rs.this_week()
finally: rs._cfg.tz = _real_tz
check("this_week: with no time given it is now in the instance timezone", _tzcalls == [1] and _wk == rs.this_week(_dt.datetime.now(ZoneInfo("Pacific/Kiritimati"))), (_tzcalls, _wk))
# the CLI: --weekly
RULES.write_text('nothing stale here\n', encoding="utf-8")
rc, out, err = cli("run", "--weekly", *srcs)
check("CLI: --weekly scans in the first run of the week and records it", rc == 0 and "rulebook scan: " in out and "already scanned" not in out and (T / "state/rulebook-scan/last-week.json").is_file(), (rc, out[:300], err[:300]))
rc, out, err = cli("run", "--weekly", *srcs)
check("CLI: --weekly again in the same week skips with one line, exit 0", rc == 0 and "already scanned in week" in out and "files," not in out, (rc, out[:300], err[:300]))
rc, out, err = cli("run", *srcs)
check("CLI: a run without --weekly always scans", rc == 0 and "files," in out, (rc, out[:300], err[:300]))
_lw = T / "state/rulebook-scan/last-week.json"; _before = _lw.read_text()
RULES.write_text('one `update(item_id="board#9", owner="x")`\n', encoding="utf-8")
rc, out, err = cli("run", "--weekly", "--dry-run", *srcs)
check("CLI: --weekly with --dry-run is a real dry scan even in a week already scanned, and records nothing", rc == 0 and "dry run" in out and "L1 · update(" in out and "already scanned" not in out and _lw.read_text() == _before, (rc, out[:300], err[:300]))

unit = pathlib.Path(STACK, "units/stackshot-audit.service.in").read_text(encoding="utf-8")
check("the timer's unit runs the scan after the run (ExecStartPost), once a week (--weekly), and a failed scan never fails the unit",
      re.search(r"(?m)^ExecStartPost=-/usr/bin/timeout 300 @UV@ run --project @CHECKOUT@ --locked python -m stackshot\.tools\.rulebook_scan run --weekly$", unit) and "ExecStart=@UV@ run --project @CHECKOUT@ --locked stackshot audit cue scheduled" in unit
      and "ExecStartPre" not in re.sub(r"(?m)^#.*$", "", unit) and unit.index("ExecStart=@UV@") < unit.index("ExecStartPost="), unit)
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("the example config documents [rulebook_scan], off by default", re.search(r"(?m)^\[rulebook_scan\][^\n]*\nenabled = false", ex) is not None)

shutil.rmtree(tmp, ignore_errors=True)
check("the suite leaves no scratch folder behind: its own rulescan- folder is gone", not os.path.exists(tmp), tmp)
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
