"""Scenario test for two write-time rules on a decision's ask (decision_gates._second_question, _gate_one_decision, _gate_design_link) — fixture data, no live store, no network,
no server socket.

  1  one question per ask: a Decide part that joins a second question to the first ("approve the design, and say if a member may be read-only") is refused on a create and on an update
     that writes the ask, the refusal names the two questions and says to ask the first now and put the other on its own item (or fold it into the options), nothing is written, and the weekly
     refusal count files it under its own kind. Each join pattern has its own check (say / tell me / let me know / decide / confirm … with every joiner and word form, whether, a question word
     after ", and", "and, if so" when the clause ends there, "as well as", two question marks, the older `; and`), and so has each fine ask that must pass (a noun list with "and", whether A or B,
     a Recommend or Stakes part that says "and say if", quoted words, URLs, words that only start like a verb, "and also allow / accept / approve" as a bundled action, "and, if so, start Monday",
     "and confirm when it is live")
  2  a design is linked in the ask: a Decide part that approves or picks a design, plan, proposal, draft, spec, package or options document ("the six-part design") while the ask line holds no
     link is refused on a create and on an update; a link only in the description (or only in next or an option) does not satisfy it; a markdown link or a bare http(s) URL anywhere in the ask does;
     an ask that names no such thing, "plan-A-only", "plan A", a noun that is the first word of a compound ("the design system rollout", "the spec change", "the package update"), a plan that is a
     subscription or a payment ("the hosting plan renewal"), options that name real alternatives, an item that is no decision and an ask stored before the rule pass;
     the ask line with a link still fits the 240 characters
  3  the tool text: create and update say it

    uv run tests/decision_ask_form_scenario.py        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="askform-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite's writes replace next wholesale; the checklist has its own suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-stew")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * 86400, "seen": {}, "reported": []}))

DESC = "- A decision on the home-brain work\n- Done when decided"
LINK = "https://example.test/projects/home-brain/design"
MD = f"[design]({LINK})"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def item(i, status="open", desc=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] home-brain work {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H,
                                                      "state_updated": now0 - 3 * H, "confirmed": now0 - 3 * H,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "Oliver: answer the ask", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
raw = lambda i: (T / f"store/a/{i}.json").read_text()
nfiles = lambda: len(list((T / "store/a").glob("*.json")))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web import home
from stackshot.service import update as _update_svc
from stackshot.core import config as _cfg
from stackshot.core import call_log as _cl
from stackshot.model import decision_gates as _dg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
from stackshot.web import render as _rmod
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: _update_svc._update(f"a{i}", sender=sender, **kw)
ask_of = lambda decide, rec="approve", stakes="a day either way": f"Decide: {decide} · Recommend: {rec} · Stakes: {stakes} · By: no date"
mk = lambda **kw: _wt_create._create(**{"subject": "[home] decide the home-brain work", "description": DESC, "project": "projects/alpha", "owner": "home-front",
                                    "next": "Oliver: answer the ask", "needs": ["decision"], "ask": ask_of("ship the fix"), **kw})
created = lambda out: bool(re.match(r"created \w\d+", str(out)))
OPT_A = [{"label": "Fast rollout", "line": "Roll out in one week.", "recommended": True}, {"label": "Slow rollout", "line": "Roll out over a month.", "recommended": False}]
OPT_YN = [{"label": "Approve", "line": "Approve it as written.", "recommended": True}, {"label": "Decline", "line": "Keep things as they are.", "recommended": False}]
sq = lambda decide: _dg._second_question(decide)[0] != ""
SECOND_WANT = ("Refused", "puts two questions in its Decide part", "ask the first one now", "its own item", "fold it into the options")

# ================================================================ 1. one question per ask
# (decide text, the join pattern it exercises). Each is a second question joined to a first one: refused as an ask, caught by the matcher.
SECOND = {
    "the real ask: approve the design, and say if a member may be read-only": "approve the six-part home-brain design in the description, and say if a board member may be read-only",
    ", and say if": "ship the fix, and say if members may be read-only",
    "and say whether, no comma": "ship the fix and say whether members may be read-only",
    "and saying (word form)": "ship the fix and saying whether members may be read-only",
    ", and tell me whether": "ship the fix, and tell me whether to rename the repo",
    "and telling me (word form)": "ship the fix and telling me whether to rename the repo",
    "and tell us": "ship the fix and tell us whether to rename the repo",
    ", and decide whether": "ship the fix, and decide whether it has an owner",
    "and deciding whether (word form)": "ship the fix and deciding whether it has an owner",
    "and then decide whether": "ship the fix and then decide whether it has an owner",
    ", plus confirm whether": "ship the fix, plus confirm whether the date holds",
    "and confirming whether (word form)": "ship the fix and confirming whether the date holds",
    "and state whether": "ship the fix and state whether the lane runs first",
    "and advise whether": "ship the fix and advise whether to wait",
    "and specify if": "ship the fix and specify if it ships",
    "and clarify whether": "ship the fix and clarify whether members may read",
    "and indicate whether": "ship the fix and indicate whether someone owns it",
    "then say if": "ship the fix, then say if members may be read-only",
    "but say whether": "ship the fix, but say whether members may be read-only",
    "and also say if": "ship the fix and also say if members may be read-only",
    "plus say if": "ship the fix plus say if members may be read-only",
    "and whether": "ship the fix and whether to rename the repo",
    "plus whether": "ship the fix plus whether to rename the repo",
    "and also whether": "ship the fix and also whether to rename the repo",
    "as well as whether": "approve the plan as well as whether to ship it",
    ", and which": "approve the plan, and which lane runs first",
    "and, if so,": "approve it and, if so, when to ship",
    "and if so": "approve it and if so when to ship",
    "and if not": "approve it and if not what then",
    "and if yes": "approve it and if yes who ships",
    "two question marks": "ship the fix? and may members be read-only?",
    "two question marks, no joiner": "ship the fix? may members be read-only?",
    "a semicolon (the older rule)": "ship the fix; and rename the repo",
}
for why, decide in SECOND.items():
    ask = ask_of(decide)
    kind, text = _dg._one_decision_kind({"ask": ask}, "")
    check(f"1 matcher: {why} is a packed ask", kind in ("second", "many") and bool(text), (kind, text))
    if "semicolon" not in why:
        check(f"1 matcher: {why} is a second question (the new rule)", kind == "second" and sq(decide), (kind, text))
# every joiner with every request, every question word, every verb of "and also"
for j in ("and", "plus", "then", "but", "also"):
    check(f"1 matcher: the joiner `{j}` before `say if`", sq(f"ship the fix {j} say if members may be read-only"), j)
QW = ("whether", "if", "which", "what", "how", "when", "who", "whom", "whose", "where", "why")
for w in QW:
    check(f"1 matcher: `say {w}` after a joiner is a second question only for whether and if (the others are a message or a follow-up)", sq(f"ship the fix and say {w} it holds") == (w in ("whether", "if")), w)
    check(f"1 matcher: `decide {w}` after a joiner is a second question only for whether and if", sq(f"ship the fix and decide {w} it holds") == (w in ("whether", "if")), w)
for w in ("which", "who", "whom"):
    check(f"1 matcher: `, and {w}`", sq(f"ship the fix, and {w} it holds"), w)
    check(f"1 matcher: `, plus {w}`", sq(f"ship the fix, plus {w} it holds"), w)
    check(f"1 matcher: `, and also {w}`", sq(f"ship the fix, and also {w} it holds"), w)
    check(f"1 narrow: `and {w}` with no comma is one question", not sq(f"ship the fix and {w} it holds"), w)
for w in ("if", "what", "how", "when", "whose", "where", "why"):
    check(f"1 narrow: `, and {w}` is a conditional or a clause, not a second question", not sq(f"ship the fix, and {w} it fails roll back"), w)
    check(f"1 narrow: `and, {w}` is a conditional or a clause, not a second question", not sq(f"merge now and, {w} the run is green, release tomorrow"), w)
    check(f"1 narrow: `as well as {w}` is not refused", not sq(f"ship the fix as well as {w} it holds"), w)
for j in ("and", "plus", "as well as"):
    check(f"1 matcher: `{j} whether`", sq(f"ship the fix {j} whether to rename the repo"), j)
    check(f"1 matcher: `{j} also whether`", sq(f"ship the fix {j} also whether to rename the repo"), j)
for v in ("say if", "say whether", "tell me whether", "tell us if", "decide whether", "confirm whether", "state whether", "advise whether", "specify whether", "clarify whether",
          "indicate whether", "saying whether", "telling me whether", "telling us if", "deciding whether", "confirming whether", "stating whether", "advising whether",
          "specifying whether", "clarifying whether", "indicating whether", "decides whether", "says if", "confirm if", "decide if", "state whether", "then decide whether"):
    check(f"1 matcher: `and {v}` is a second question", sq(f"ship the fix and {v} it holds"), v)
for v in ("decide", "decide on the rollout", "confirm", "state", "advise", "specify", "clarify", "indicate", "choose which", "pick whether", "choosing", "tell", "say", "let"):
    check(f"1 narrow: `and {v}` with no question word is not a second question", not sq(f"ship the fix and {v} it holds"), v)
# a decide / confirm / state / advise / specify / clarify / indicate with a question word other than whether and if is an action or a report, not a second question
for v in ("decide", "confirm", "state", "advise", "specify", "clarify", "indicate", "decides", "confirming", "stating"):
    for w in ("which", "what", "how", "when", "who", "whom", "whose", "where", "why"):
        check(f"1 narrow: `and {v} {w}` is one decision", not sq(f"ship the fix and {v} {w} it holds"), (v, w))
        check(f"1 narrow: `and then {v} {w}` is one decision", not sq(f"ship the fix and then {v} {w} it holds"), (v, w))
# M2: a bundled action aimed at a third party, or a plain follow-up, is no second question (the known limit: `and say whether` to a third party is still read as one)
M2_FINE = ("reply to Acme and say how long the fix takes", "email the customer and say what changed", "approve the spend and let me know when it lands", "ship it and tell me when it is done",
           "ship the fix and let me know the date", "ship the fix and let us know the date", "ship the fix and letting me know the date", "ship the fix and please tell me the date",
           "ship the fix and tell us the date", "ship the fix, and say which lane runs first", "ship the fix and say who owns it", "post the notice and tell me when", "ship the fix and say when it is live",
           "ship the fix, then tell me what changed", "ship the fix and say why", "ship the fix and say where it went", "ship the fix and say how it went", "ship the fix and say whose it is",
           "ship the fix and say whom to thank", "ship the fix plus say which date")
for t in M2_FINE:
    check(f"1 M2: `{t}` is one decision", not sq(t) and _dg._one_decision_kind({"ask": ask_of(t)}, "")[0] == "", t)
for t in ("reply to Acme and say whether the fix is live", "ship it and tell me whether it is done", "approve the spend, and say if it lands", "ship it and, say if x", "ship it, and, say whether x"):
    check(f"1 M2: `{t}` is still a second question (say / tell me with whether or if)", sq(t), t)
for t in ("ship the fix and say how long it takes", "email the customer and say what changed", "approve the spend and let me know when it lands"):
    out = mk(ask=ask_of(t))
    check(f"1 M2 create: `{t}` is accepted", created(out), out)
    item(70, needs=["decision"], ask=ask_of("ship the fix"), mover="Oliver", then="team-back")
    upd(70, ask=ask_of(t))
    check(f"1 M2 update: `{t}` is accepted on an update that writes the ask", rd(70)["metadata"]["ask"] == ask_of(t), rd(70)["metadata"].get("ask"))
# the comma after the joiner is read (`and, say if`), and a curly or straight quote masks a join
for t in ("ship the fix and, say if members may read", "ship the fix and, tell me whether to wait", "ship the fix, and, say whether it holds", "ship the fix;and, say if x"):
    check(f"1 comma: `{t}` is a second question", sq(t), t)
for t in ("ship the fix and \u201csay if members may read\u201d", "whether to ship \u201cthe fix and say if it holds\u201d now", "ship the fix and \u201ctell me whether\u201d now",
          'ship the fix and "say if it holds"', "ship \u201ca b\u201d and \u201cc d\u201d"):
    check(f"1 curly quote: `{t}` hides its join", not sq(t), t)
check("1 curly quote: a join outside the quotes is still read", sq("ship \u201ca b\u201d now and say if it holds"), "")
check("1 curly quote: the cut falls at the joiner after the quote", _dg._second_question("ship \u201ca b\u201d now, and say if it holds") == ("ship \u201ca b\u201d now", "say if it holds"), _dg._second_question("ship \u201ca b\u201d now, and say if it holds"))
# "and also" + a verb is a bundled action, whatever the verb
for v in ("approve", "accept", "decline", "reject", "allow", "permit", "let me decide", "let us decide", "approves", "allowing"):
    check(f"1 narrow: `and also {v}` is a bundled action, not a second question", not sq(f"ship the fix and also {v} the docs"), v)
    check(f"1 narrow: `, and also {v}` is a bundled action, not a second question", not sq(f"ship the fix, and also {v} the docs"), v)
for v in ("add", "keep", "use", "make", "move", "publish", "send", "switch", "ship", "merge", "rename", "remove", "drop", "change", "release", "let", "turn on", "retire", "archive"):
    check(f"1 narrow: `and also {v}` is a bundled single action, not a second question", not sq(f"ship the fix and also {v} the docs"), v)
for tail in ("so", "yes", "not", "no"):
    check(f"1 matcher: `and, if {tail}, <question word>` is a second question", sq(f"approve it and, if {tail}, when to ship"), tail)
    check(f"1 matcher: `and if {tail}` with a question word", sq(f"approve it and if {tail} when to ship"), tail)
    check(f"1 matcher: `and if {tail}` at the end", sq(f"approve it and if {tail}"), tail)
    for end in ("?", ".", ";", " ?", " ."):
        check(f"1 matcher: `and if {tail}{end}` ends its clause", sq(f"approve it and if {tail}{end}"), (tail, end))
        check(f"1 matcher: `and, if {tail}{end}` ends its clause", sq(f"approve it and, if {tail}{end}"), (tail, end))
    for after in ("ship it", "start Monday", "announce it Friday", "wait for CI", "release", "close the item", "pay it", "roll back"):
        check(f"1 narrow: `and, if {tail}, {after}` is a condition on one decision", not sq(f"approve it and, if {tail}, {after}"), (tail, after))
        check(f"1 narrow: `and if {tail}, {after}` is a condition on one decision", not sq(f"approve it and if {tail}, {after}"), (tail, after))
for tail in ("not possible", "no one objects", "so desired", "yes votes carry", "not needed"):
    check(f"1 narrow: `and if {tail}` is a condition, not a second question", not sq(f"approve it and if {tail} ship it"), tail)

# the refusal: the two questions named, the way out, nothing written; create and update
n_ = nfiles()
out = ""
try: mk(ask=ask_of(SECOND["the real ask: approve the design, and say if a member may be read-only"]))
except Exception as ex: out = str(ex)
check("1 create: the real ask is refused, naming both questions and the way out", all(w in out for w in SECOND_WANT) and "approve the six-part home-brain design in the description" in out
      and "say if a board member may be read-only" in out and nfiles() == n_, out)
e = ""
try: mk(ask=ask_of("ship the fix, and tell me whether to rename the repo"))
except Exception as ex: e = str(ex)
check("1 create: the refusal quotes the first question and the second, without the joiner", "“ship the fix” and “tell me whether to rename the repo”" in e and "One decision per item" not in e, e)
check("1 create: …and asks Oliver one question whose answers are the options", "A decision asks one question, and its answers are the options" in e and "Oliver" in e, e)
for why in ("and say whether, no comma", ", and which", "and, if so,", "as well as whether", "and also say if", "two question marks", "and tell us", "and whether", "as well as whether"):
    n_ = nfiles()
    refused(f"1 create: {why} is refused", lambda: mk(ask=ask_of(SECOND[why])), *SECOND_WANT)
    check(f"1 create: {why} writes nothing", nfiles() == n_)
refused("1 create: a `;` split is still the several-decisions refusal, not the new one", lambda: mk(ask=ask_of(SECOND["a semicolon (the older rule)"])), "Refused", "split by", "One decision per item")
item(1, needs=["decision"], ask=ask_of("ship the fix"), mover="Oliver", then="team-back")
refused_nw("1 update: an ask with a second question is refused, the ask stays", 1, lambda: upd(1, ask=ask_of(SECOND[", and say if"])), *SECOND_WANT)
check("1 update: …the stored ask is the old one", rd(1)["metadata"]["ask"] == ask_of("ship the fix"), rd(1)["metadata"])
refused_nw("1 update: …one lifted from the first line of next says so", 1, lambda: upd(1, next=ask_of(SECOND[", and tell me whether"]) + "\nOliver: answer the ask"), "puts two questions", "lifted from next")
out = upd(1, ask=ask_of("whether to ship the fix and the docs"))
check("1 update: a one-question ask is accepted", rd(1)["metadata"]["ask"] == ask_of("whether to ship the fix and the docs"), out)
# an item stored before the rule keeps its ask; only a write that sets the ask is read
item(2, needs=["decision"], ask=ask_of(SECOND[", and say if"]), mover="Oliver", then="team-back")
out = upd(2, priority="p3")
check("1 update: an old item's other-field update is not held", rd(2)["metadata"]["priority"] == "p3", out)
out = upd(2, description="- A decision on the home-brain work\n- Done when decided, in two lines")
check("1 update: …nor an update of the description", rd(2)["description"].endswith("two lines"), out)

# the weekly count files each refusal under its own kind
check("1 kind: a second question is counted under its own kind", _cl.kind_of(e) == "an ask with a second question in its Decide part", _cl.kind_of(e))
check("1 kind: …also inside a refusal of several faults", _cl.kind_of("Refused: 2 problems in this call, fix them together\n(1) " + e[len("Refused: "):] + "\n(2) Refused: x") == "an ask with a second question in its Decide part",
      _cl.kind_of("Refused: 2 problems in this call, fix them together\n(1) " + e[len("Refused: "):] + "\n(2) Refused: x"))

# fine asks: one question, whatever it says about "and"
FINE = {
    "a noun list with and": "ship the login and signup pages now",
    "whether A or B": "whether the tool is plan-A-only or open to all lanes",
    "whether to ship A or B": "whether to ship A or B",
    "and between options": "A and B together, or C",
    "no join at all": "restart the server tonight",
    "approve and ship": "whether to approve and ship the fix",
    "tell the team": "whether to tell the team and ship",
    "say nothing": "ship the build and say nothing",
    "two nouns": "whether the retry and the timeout stay as they are",
    "also-ran": "use the also-ran list",
    "release notes": "merge the fix and release notes",
    "a URL with a question mark": "ship https://example.test/a?b=1 and https://example.test/c?d=2",
    "quoted words": 'whether to use "say if" and "tell me" wording',
    "a quoted join": 'whether to use the words "ship it and say if members may read" in the docs',
    "then wait": "ship the fix, then wait a week",
    "a decision noun": "whether the decision and the rollout stay as they are",
    "one question mark": "ship the fix?",
    "and also a noun": "ship the login and also the signup pages",
    "words that only start like a verb": "ship the fix and decision records",
    "pickles": "ship the fix and pickles",
    "statement": "ship the fix and the statement of work",
    "sayings": "ship the fix and sayings of the week",
    "decided as an adjective": "ship the fix and decided cases",
    "and plus as arithmetic": "ship 2 plus 3 builds",
    "and if as a condition in one clause": "ship the fix and if needed a rollback",
    "an entity": "whether &lt;b&gt; and &amp; stay",
    "a markdown link": f"approve the {MD} and the docs",
    # the single decisions a review found falsely refused (a bundled action, a conditional, a later decision)
    "bundled: ship and add a test": "whether to ship the fix and also add the regression test",
    "bundled: retire and move": "retire the old queue and also move its jobs",
    "bundled: archive and keep": "archive the board and also keep the export",
    "bundled: merge and publish": "merge the change and also publish the release notes",
    "bundled: flag and default": "turn on the flag and also make it the default",
    "bundled: switch and use": "switch the model and also use the cheaper lane",
    "bundled: ship and keep the flag": "ship the change and also keep the old flag for a week",
    "bundled: rename and send": "rename the repo and also send the notice",
    "bundled: remove and drop": "remove the flag and also drop the old table",
    "bundled: change and release": "change the default and also release the update",
    "conditional: merge, if green, release": "merge now and, if the run is green, release tomorrow",
    "conditional: approve and, if it matches, pay": "approve the invoice and, if it matches the order, pay it",
    "conditional: ship, and if it fails roll back": "ship the fix, and if it fails roll back",
    "conditional: ship Friday, and when needed hotfix": "ship on Friday, and when needed hotfix on Saturday",
    "conditional: a clause that starts with what": "start the migration at 2 am, and what to do if it fails is already in the runbook",
    "conditional: and if not possible": "ship the fix and if not possible wait a week",
    "later decision: wait then decide": "wait a day and then decide",
    "later decision: review and decide on small PRs": "the agent may review and decide on small pull requests alone",
    "later decision: dry run, then decide on rollout": "run the dry run, then decide on the rollout from its result",
    "later decision: keep and decide on removal": "keep the old lane and decide on its removal in June",
    "later decision: and decide on": "ship the fix and decide on the date from the result",
    "no question word after confirm": "ship the fix and confirm the date in the doc",
    "as well as without whether": "ship the fix as well as the docs",
    "as well as saying (a known limit, narrowed)": "ship the fix as well as saying who owns it",
    "as well as deciding (a known limit, narrowed)": "ship the fix as well as deciding the date",
    # the re-review: an action after "and, if so" and a bundled "and also <verb>"
    "if so: approve then start Monday": f"approve the proposal {MD} and, if so, start Monday",
    "if so: approve it, announce Friday": "approve it and, if so, announce it Friday",
    "if so: merge PR 8, release": "merge PR 8 and, if so, release",
    "if not: merge it now, wait for CI": "merge it now and if not, wait for CI",
    "if yes: approve the rollout, start Monday": "approve the rollout and if yes, start Monday",
    "if no: approve the rollout, close the item": "approve the rollout and if no, close the item",
    "also allow: retire the queue": "retire the old queue and also allow its jobs to drain",
    "also accept: close the PR": "close the PR and also accept the follow-up",
    "also allow: reject the PR": "reject the PR and also allow a resubmission",
    "also approve: merge the fix": "merge the fix and also approve the follow-up PR",
    "also accept: decline the vendor": "decline the vendor and also accept the second bid",
    "also allow: disable the flag": "disable the flag and also allow admins to override it",
    "confirm when it is live": "let the builder merge and confirm when it is live",
    "then state which version": "ship the fix and then state which version went out",
    "then decide when to ship": "wait a day and then decide when to ship",
}
for why, decide in FINE.items():
    check(f"1 matcher: {why} is one question", not sq(decide) and _dg._one_decision_kind({"ask": ask_of(decide)}, "")[0] in ("",), (why, _dg._second_question(decide)))
for why in ("a noun list with and", "whether A or B", "and between options", "approve and ship", "quoted words", "two nouns") + tuple(k for k in FINE if k.split(":")[0] in ("bundled", "conditional", "later decision", "no question word after confirm", "as well as without whether", "if so", "if not", "if yes", "if no", "also allow", "also accept", "also approve", "confirm when it is live", "then state which version", "then decide when to ship")):
    out = mk(ask=ask_of(FINE[why]))
    check(f"1 create: {why} is accepted", created(out), out)
for k, why in enumerate(("conditional: merge, if green, release", "later decision: wait then decide", "bundled: retire and move", "if so: approve then start Monday", "if not: merge it now, wait for CI",
                         "also allow: retire the queue", "also approve: merge the fix", "then decide when to ship")):
    item(60 + k, needs=["decision"], ask=ask_of("ship the fix"), mover="Oliver", then="team-back")
    upd(60 + k, ask=ask_of(FINE[why]))
    check(f"1 update: {why} is accepted on an update that writes the ask", rd(60 + k)["metadata"]["ask"] == ask_of(FINE[why]), rd(60 + k)["metadata"].get("ask"))
# two question marks need a word between them: "??" and "? ?" are one emphasized question, "? x ?" are two
for why, decide in (("a doubled mark", "ship the fix?? members may read"), ("a mark, a space, a mark", "ship the fix? ? members may read"), ("three in a row", "ship the fix??? now"),
                    ("a mark and spaces", "ship the fix?   ? members may read"), ("two marks at the end", "ship the fix??")):
    check(f"1 matcher: {why} is not a second question", not sq(decide), (why, _dg._second_question(decide)))
for why, decide in (("a word between", "ship the fix? may members read?"), ("a single character between", "ship the fix? x?"), ("a mark right after a word", "ship the fix?? may members read?")):
    check(f"1 matcher: {why} is a second question", sq(decide), why)
check("1 matcher: the three marks of '? x ?' cut at the first", _dg._second_question("ship the fix? x ?")[0] == "ship the fix?", _dg._second_question("ship the fix? x ?"))
# M1: "A? Or B?" is one question and its alternative; a mark counts only before whitespace or the end of the text
ALT_FINE = ("Merge PR 5 now? Or wait for CI?", "Use Postgres? Or SQLite?", "Ship the fix tonight? Or hold until Monday?", "Merge the fix? Yes/No?", "Merge the fix? Yes or no?", "Merge the fix? Yes, no or later?",
            "Merge the fix? Yes / No?", "Pick a lane? A, B or C?", "Merge it?  or wait?", "Merge it? OR wait?", "Merge it? Or? Or?", "Use A? Or B? Or C?", "Merge it? Approve/Decline?", "Merge the fix? Yes, No?")
for t in ALT_FINE:
    check(f"1 M1: `{t}` is one question with its alternatives", not sq(t) and _dg._one_decision_kind({"ask": ask_of(t)}, "")[0] == "", (t, _dg._second_question(t)))
for t in ("approve foo?.py or bar?.py", "match the regex ^a?b? now", "rename a?b and c?d", "ship foo?.py? or bar?.py?", "ship the x?y? now", "what is a?b?c?d"):
    check(f"1 M1: `{t}` holds no real question mark pair", not sq(t), (t, _dg._second_question(t)))
for t in ("Merge it? Also should we rename the repo?", "Ship the fix? And may members read?", "Merge it? Should we rename the repo or keep it?", "Merge it? May members read it?", "Use Postgres? Rename the repo?",
          "Merge it? Yes, and may members read?", "Merge it? Is it Friday or Monday for the date?", "Merge it? Then should we rename the repo?",
          "Merge it? Or wait?  Also should we rename the repo?", "Merge it? Yes/No? Should we rename the repo?"):
    check(f"1 M1: `{t}` is two separate questions", sq(t), (t, _dg._second_question(t)))
check("1 M1: the cut of `Merge it? Or wait? And rename?` falls at the first mark that has a new question after it", _dg._second_question("Merge it? Or wait? And rename it?") == ("Merge it? Or wait?", "rename it?"),
      _dg._second_question("Merge it? Or wait? And rename it?"))
for t in ("Merge PR 5 now? Or wait for CI?", "Merge the fix? Yes/No?", "foo?.py or bar?.py"):
    out = mk(ask=ask_of(t))
    check(f"1 M1 create: `{t}` is accepted", created(out), out)
item(71, needs=["decision"], ask=ask_of("ship the fix"), mover="Oliver", then="team-back")
upd(71, ask=ask_of("Use Postgres? Or SQLite?"))
check("1 M1 update: `Use Postgres? Or SQLite?` is accepted on an update that writes the ask", rd(71)["metadata"]["ask"] == ask_of("Use Postgres? Or SQLite?"), rd(71)["metadata"].get("ask"))
# a word that only starts with "or" is no alternative; an empty option is none; the earlier of a joiner and a second question mark cuts
for t_ in ("Merge it? Order a pizza and rename the repo?", "Merge it? Orange?", "Merge it? Ordering a pizza?", "Merge it? /rename?", "Merge it? , /rename?"):
    check(f"1 M1: `{t_}` is a second question", sq(t_), (t_, _dg._second_question(t_)))
check("1 M1: a joiner before two marks cuts at the joiner", _dg._second_question("ship the fix, and say if it holds? may members read?") == ("ship the fix", "say if it holds? may members read?"),
      _dg._second_question("ship the fix, and say if it holds? may members read?"))
check("1 M1: two marks before a joiner cut at the first mark", _dg._second_question("ship it? may we, and say if x?") == ("ship it?", "may we, and say if x?"), _dg._second_question("ship it? may we, and say if x?"))
check("1 M1: two marks and a joiner after them cut at the first mark", _dg._second_question("ship it? may we? and say if x") == ("ship it?", "may we? and say if x"), _dg._second_question("ship it? may we? and say if x"))
refused("1 M1 create: two separate questions are still refused", lambda: mk(ask=ask_of("Merge it? Also should we rename the repo?")), *SECOND_WANT)
# a URL, an entity or quoted words are masked IN PLACE: nothing is cut out, so no join is made by closing a gap and the cut falls where the text says
for why, decide in (("a URL between the joiner and the request", "ship the fix and https://example.test/a say if it holds"), ("a quote between them", 'ship the fix and "x" say if it holds'),
                    ("an entity between them", "ship the fix and &amp; say if it holds"), ("a curly quote between them", "ship the fix and \u201cx\u201d say if it holds"),
                    ("a URL after the joiner of whether", "ship the fix and https://example.test/a whether to rename")):
    check(f"1 mask: {why} does not make a join", not sq(decide), (why, _dg._second_question(decide)))
check("1 mask: the cut falls at the joiner after a URL", _dg._second_question("ship https://example.test/a?b=1 now, and say if it holds") == ("ship https://example.test/a?b=1 now", "say if it holds"),
      _dg._second_question("ship https://example.test/a?b=1 now, and say if it holds"))
check("1 mask: the cut falls at the joiner after quoted words and an entity", _dg._second_question('ship "a b" &amp; c, and tell me whether') == ('ship "a b" &amp; c', "tell me whether"), _dg._second_question('ship "a b" &amp; c, and tell me whether'))
check("1 mask: …and the second question of two marks after a URL is cut at the first mark", _dg._second_question("approve https://example.test/a?b=1 now? may members read?") == ("approve https://example.test/a?b=1 now?", "may members read?"),
      _dg._second_question("approve https://example.test/a?b=1 now? may members read?"))
check("1 mask: a mark inside the URL is no question mark", _dg._second_question("approve https://example.test/a?b=1? may members read?") == ("", ""), _dg._second_question("approve https://example.test/a?b=1? may members read?"))
# only the Decide part is judged
for part, ask in (("Recommend", "Decide: ship the fix · Recommend: yes, and say if members may be read-only · Stakes: a day · By: no date"),
                  ("Stakes", "Decide: ship the fix · Recommend: yes · Stakes: a day, and tell me whether to wait · By: no date"),
                  ("By", "Decide: ship the fix · Recommend: yes · Stakes: a day · By: Mon Jun 8th 2099 and decide the lane")):
    out = mk(ask=ask)
    check(f"1 create: a {part} part that says 'and say if' is not judged", created(out), out)

# ================================================================ 2. a design is linked in the ask
DESIGN_WANT = ("Refused", "carries no link to it", "Link the ", " in the ask: a page Oliver can open, not a path on a machine or a summary", "[", "](<the page's link>)")
UNLINKED = {
    "the real ask (design in the description)": ("approve the six-part home-brain design in the description", "design"),
    "approve the design": ("whether to approve the design", "design"),
    "a plan": ("approve the rollout plan", "plan"),
    "plural plans": ("approve the two plans", "plan"),
    "a proposal": ("pick the proposal", "proposal"),
    "sign off on our plan": ("sign off on our rollout plan", "plan"),
    "a draft": ("accept the draft", "draft"),
    "a spec": ("whether to adopt the spec", "spec"),
    "a specification": ("approve the specification", "specification"),
    "a package": ("go ahead with the migration package", "migration package"),
    "a decision package": ("approve the decision package", "decision package"),
    "an options package": ("choose the options package", "options package"),
    "an options document": ("choose the options document", "options document"),
    "an rfc": ("approve the RFC", "rfc"),
    "the six-part rollout": ("approve the six-part rollout", "six-part rollout"),
    "modifiers before the noun": ("approve the Q3 hiring and onboarding plan", "plan"),
    "go with the plan": ("go with the plan", "plan"),
    "decide on the design": ("decide on the new design", "design"),
    "review the draft": ("review the draft", "draft"),
    "confirm the plan": ("whether to confirm the plan", "plan"),
    "select a proposal": ("select a proposal", "proposal"),
    "upper case": ("APPROVE THE DESIGN", "design"),
}
for why, (decide, noun) in UNLINKED.items():
    ask = ask_of(decide)
    got = _dg._design_unlinked({"needs": ["decision"], "ask": ask})
    check(f"2 matcher: {why} names a {noun} with no link", got == noun, got)
for why in ("the real ask (design in the description)", "a plan", "a spec", "the six-part rollout", "an options document", "plural plans"):
    n_ = nfiles()
    refused(f"2 create: {why} with no link in the ask is refused", lambda: mk(ask=ask_of(UNLINKED[why][0])), *DESIGN_WANT, UNLINKED[why][1])
    check(f"2 create: {why} writes nothing", nfiles() == n_)
out = ""
try: mk(ask=ask_of("approve the six-part home-brain design in the description"))
except Exception as ex: out = str(ex)
check("2 create: the refusal reads: Link the design in the ask, then the shape and the limit", "Link the design in the ask: a page Oliver can open, not a path on a machine or a summary" in out
      and "ask=\"Decide: whether to approve the design [design](<the page's link>) · Recommend: … · Stakes: … · By: …\"" in out and "240 characters" in out
      and "a link only in the description does not count" in out, out)
# a link in the description, in next or in an option is not the ask's link
DESC_LINK = f"- The home-brain design: {MD}\n- Done when decided"
refused("2 create: a link only in the description does not satisfy it", lambda: mk(ask=ask_of("approve the home-brain design"), description=DESC_LINK), *DESIGN_WANT)
refused("2 create: …a bare URL in a description bullet that names the design", lambda: mk(ask=ask_of("approve the home-brain design"), description=f"- The design lives at {LINK}\n- Done when decided"), *DESIGN_WANT)
refused("2 create: …a link in next", lambda: mk(ask=ask_of("approve the home-brain design"), next=f"Oliver: answer the ask, see {LINK}"), *DESIGN_WANT)
refused("2 create: …a link in the Approve/Decline options (and that is refused for its own reason too)", lambda: mk(ask=ask_of("approve the home-brain design"), options=OPT_YN, description=DESC_LINK), *DESIGN_WANT)
# the link in the ask satisfies it, wherever in the ask
LINKED = {
    "a markdown link in the Decide part": ask_of(f"approve the six-part home-brain {MD}"),
    "a bare https URL in the Decide part": ask_of(f"approve the home-brain design at {LINK}"),
    "a bare http URL": ask_of("approve the home-brain design at http://example.test/d"),
    "a link in the Recommend part": ask_of("approve the home-brain design", rec=f"approve, see {MD}"),
    "a link in the Stakes part": ask_of("approve the home-brain design", stakes=f"see {MD}"),
    "a link text of one word": ask_of("approve the plan [x](https://example.test/p)"),
}
for why, ask in LINKED.items():
    check(f"2 matcher: {why} satisfies it", _dg._design_unlinked({"needs": ["decision"], "ask": ask}) == "", ask)
    out = mk(ask=ask)
    check(f"2 create: {why} is accepted", created(out), out)
long_ask = ask_of(f"approve the six-part home-brain [design](https://github.com/example-org/example-brain/blob/main/projects/home-brain/design.md)", rec="approve as written", stakes="a week of rework either way")
check("2 limit: the real ask with a 70-character link and a short link text fits the ask limit", len(long_ask) <= _rmod.ASK_MAX and _rmod.parse_ask(long_ask) is not None, (len(long_ask), long_ask))
out = mk(ask=long_ask)
check("2 limit: …and is accepted", created(out), out)
# narrow: what is not a design asked about
FINE_D = {
    "restart the server": "restart the server tonight",
    "a noun list": "ship the login and signup pages now",
    "plan-A-only": "whether to ship Widget plan-A-only",
    "plan A": "whether to approve plan A",
    "a plan with no approving verb": "ship the plan",
    "the package manager": "pick the package manager",
    "a budget": "approve the budget",
    "a build": "whether to ship the 2GB build",
    "hyphenated design": "approve the design-system rename",
    "planning": "approve the planning meeting",
    "special": "approve the special case",
    "preview is no approval": "preview the design",
    "a past tense asks about his own step": "have you reviewed the draft and is it fine to send",
    "approved as a past tense": "whether you approved the design",
    "no determiner": "pick proposal B",
    "an open noun": "whether to ship the fix",
    "a decision about a version": "whether to move to v3",
    "plan names in options": "whether the tool is plan-A-only or open to all lanes",
    # a review found these falsely refused: a subscription plan, a package file, a draft of a thing
    "the Pro plan": "pick the Pro plan for the API account",
    "the Max plan": "choose the Max plan",
    "the billing plan": "confirm the billing plan change",
    "the free plan's limits": "accept the free plan's limits",
    "the team plan": "choose the team plan",
    "the API plan": "pick the API plan",
    "the enterprise plan": "approve the enterprise plan",
    "the paid plan": "go with the paid plan",
    "the subscription plan": "review the subscription plan",
    "the pricing plan": "decide on the pricing plan",
    "the price plan": "select the price plan",
    "package.json": "whether to approve the package.json change",
    "package-lock": "whether to accept the package-lock update",
    "package lock": "accept the package lock",
    "a draft PR": "whether to review the draft PR",
    "a draft pull request": "approve the draft pull request",
    "a draft release": "confirm the draft release",
    "a draft email": "review the draft email",
    "a draft message": "accept the draft message",
    "a draft e-mail": "review the draft e-mail",
    # the re-review: a design noun as the first word of a compound
    "design system rollout": "approve the design system rollout",
    "design tool": "pick the design tool for the team",
    "design tokens": "approve the design tokens update",
    "spec change": "approve the spec change in the config",
    "spec sheet": "approve the spec sheet for the monitor",
    "proposal deadline": "choose the proposal deadline",
    "draft deadline": "pick the draft deadline",
    "draft status": "accept the draft status of the item",
    # the package as software
    "package update": "approve the package update",
    "package bump": "accept the package bump for requests",
    "package changes": "review the package changes before release",
    "package for JSON parsing": "pick the package for JSON parsing",
    "package that handles retries": "choose the package that handles retries",
    # a plan that is a service or a payment
    "hosting plan renewal": "approve the hosting plan renewal",
    "data plan": "choose the data plan for the SIM",
    "payment plan": "approve the payment plan with the vendor",
    "support plan": "approve the support plan for next year",
    "storage plan upgrade": "approve the storage plan upgrade",
    "plan upgrade": "approve the plan upgrade",
    "backup plan cost": "approve the cost of $40 a month for the backup plan",
}
for why, decide in (("a plan for a tier word later is still a plan", "pick the plan for the Pro account"), ("a plain draft is still a draft", "review the draft"),
                    ("a draft of a design is a draft", "review the draft design"), ("a package is still a package", "approve the migration package")):
    check(f"2 narrow: {why}", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of(decide)}) in ("plan", "draft", "design", "migration package"), _dg._design_unlinked({"needs": ["decision"], "ask": ask_of(decide)}))
check("2 narrow: a Pro plan beside a real design still names the design", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of("pick the Pro plan and approve the rollout plan")}) == "plan", "")
check("2 narrow: …and a draft PR beside a real draft names the draft", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of("review the draft PR and approve the draft")}) == "draft", "")
for t in ("pro", "max", "free", "team", "enterprise", "billing", "api", "paid", "subscription", "pricing", "price", "Pro", "API"):
    check(f"2 narrow: `the {t} plan` is a subscription, not a design", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of(f"pick the {t} plan")}) == "", t)
for why in ("the Pro plan", "package.json", "a draft PR", "the billing plan", "a draft email"):
    out = mk(ask=ask_of(FINE_D[why]))
    check(f"2 create: {why} needs no link and is accepted", created(out), out)
# a script's question is never refused for a missing link (a script cannot add one); the same ask through the create tool is
from stackshot.service import writes
writes.QUESTION.on = True
try:
    out = mk(ask=ask_of("approve the six-part home-brain design"))
finally:
    writes.QUESTION.on = False
check("2 question route: a script's question about a design files without a link", created(out), out)
refused("2 question route: …while the same ask through the create tool is refused", lambda: mk(ask=ask_of("approve the six-part home-brain design")), *DESIGN_WANT)
writes.QUESTION.on = True
try:
    refused("2 question route: …a second question on a script's question is still refused", lambda: mk(ask=ask_of("ship the fix, and say if members may be read-only")), *SECOND_WANT)
finally:
    writes.QUESTION.on = False
for why, decide in FINE_D.items():
    check(f"2 matcher: {why} names no design", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of(decide)}) == "", (why, _dg._design_unlinked({"needs": ["decision"], "ask": ask_of(decide)})))
dm = lambda decide, ask=None, **meta: _dg._design_unlinked({"needs": ["decision"], "ask": ask if ask is not None else ask_of(decide), **meta})
for junk in (None, 5, 1.5, [], ["approve the design"], ["ship the fix, and say if members may read"], ("ship the fix", "and tell me whether"), {"a": 1}, b"approve the design", True):
    try: r1 = _dg._second_question(junk)
    except Exception as ex: r1 = repr(ex)
    check(f"3 junk: _second_question({junk!r}) does not raise", r1 == ("", ""), r1)
    try: r2 = _dg._design_unlinked({"needs": ["decision"], "ask": junk})
    except Exception as ex: r2 = repr(ex)
    check(f"3 junk: _design_unlinked with ask {junk!r} does not raise", isinstance(r2, str) and "Error" not in r2, r2)
for junk in (None, 5, "ask", [], ["decision"]):
    try: r3 = _dg._design_unlinked(junk)
    except Exception as ex: r3 = repr(ex)
    check(f"3 junk: _design_unlinked({junk!r}) does not raise", r3 == "", r3)
# a design noun followed by a plain word is a compound; one followed by a preposition, conjunction, determiner, auxiliary or adverb (or nothing) is still the design
for w in ("system", "tool", "tokens", "change", "sheet", "deadline", "status", "renewal", "meeting", "template", "library", "owner", "work", "rollout", "process", "budget"):
    for n in ("design", "plan", "proposal", "draft", "spec", "specification"):
        check(f"2 compound: `approve the {n} {w}` is no design asked about", dm(f"approve the {n} {w}") == "", (n, w))
for w in ("in the link text", "below", "above", "for Q3", "of the lane", "that we wrote", "which holds", "is ready", "was sent", "and ship it", "or the other", "today", "now", "first", "then ship",
          "with the team", "before Friday", "after review", "to the owner", "on the page", "by Friday", "as written", "please", "again", "here", "there", "attached", "linked", "will do", "should hold",
          "has landed", "not yet", "instead", "only", "still", "if it holds", "so far", "when ready", "but not the other"):
    check(f"2 compound: `approve the design {w}` is still a design asked about", dm(f"approve the design {w}") == "design", w)
    check(f"2 compound: `approve the plan {w}` is still a plan asked about", dm(f"approve the plan {w}") == "plan", w)
for p_ in (",", ".", "?", ";", "!"):
    check(f"2 compound: `approve the design{p_}` is still a design asked about", dm(f"approve the design{p_}", ask="Decide: approve the design" + p_ + " · Recommend: yes · Stakes: low · By: no date") == "design", p_)
# every word that leaves the noun a design (listed here on purpose: a word dropped from the rule must fail a check)
AFTER_WORDS = ("for to of in on at by with from that which who whom whose below above here there is are was were be been being and or nor as if so then but before after until because when while since "
               "via per into onto over under about within without across through against between among around during than today tonight tomorrow now soon first again please asap too also alone together "
               "attached linked outlined described proposed next last this these those the a an our my your their his her its it we you they i will would can could may might should must shall has have had "
               "does do did not no yet instead anyway either only just still already up out down off back upon toward towards except unless whether how what where why").split()
for w in AFTER_WORDS:
    check(f"2 compound: `approve the design {w} it` is still a design asked about", dm(f"approve the design {w} it") == "design", w)
    check(f"2 compound: `APPROVE THE PLAN {w.upper()} IT` in capitals", dm(f"APPROVE THE PLAN {w.upper()} IT") == "plan", w)
# …and a word that is not in that list makes a compound, whatever its letter
for w in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
          "victor", "whiskey", "xray", "yankee", "zulu", "x", "z"):
    check(f"2 compound: `approve the design {w}` is a compound", dm(f"approve the design {w}") == "", w)
for q in ("decision", "option", "options", "proposal", "design", "migration", "rollout", "launch"):
    check(f"2 package: `approve the {q} package` is a package asked about", dm(f"approve the {q} package") == f"{q} package", q)
    check(f"2 package: `approve the {q} package update` is a compound", dm(f"approve the {q} package update") == "", q)
check("2 package: a bare package, a package for a thing and a package that does a thing need no link", all(dm(t) == "" for t in ("approve the package", "pick the package for JSON parsing", "choose the package that handles retries",
      "approve the package update", "accept the package bump for requests", "review the package changes before release")), "")
# a file name is no design (the noun followed by a dot and a word), a sentence end is
for t in ("approve the spec.json", "approve the design.md", "accept the plan.yaml", "pick the draft.txt", "review the proposal.pdf", "approve the rfc.md"):
    check(f"2 file: `{t}` is a file name, no design asked about", dm(t) == "", t)
for t, n in (("approve the design.", "design"), ("approve the plan. Then ship", "plan"), ("pick the draft.", "draft")):
    check(f"2 file: `{t}` ends a sentence, a design asked about", dm(t) == n, t)
# a draft of a thing is a compound (the draft PR, the draft e-mail ...), so it needs no rule of its own
for t in ("review the draft PR", "approve the draft pull request", "confirm the draft release", "review the draft email", "accept the draft message", "review the draft e-mail",
          "approve the draft reply", "pick the draft title"):
    check(f"2 draft: `{t}` is a draft of a thing, no design asked about", dm(t) == "", t)
check("2 draft: a draft of a design is a draft", dm("review the draft design") == "design" and dm("review the draft") == "draft" and dm("review the draft design draft") == "draft", "")
# the end of a clause after "if so" is the end of the text, a question mark, a full stop or a semicolon (a "!" is not one: a known limit)
check("1 narrow: `and if so!` is not read as the end of a clause", not sq("approve it and if so! ship it") and not sq("approve it and, if so!"), "")
check("2 compound: the noun at the very end of the Decide part", dm("approve the design") == "design" and dm("approve the proposal") == "proposal", "")
# the tier words skip only a plan: the same word before any other noun leaves it a design (a surviving mutant skipped every noun)
TIER = ("pro", "max", "free", "team", "enterprise", "billing", "api", "paid", "subscription", "pricing", "price", "data", "hosting", "payment", "support", "storage", "backup", "phone", "mobile",
        "insurance", "savings", "retirement", "service", "cloud", "monthly", "annual", "yearly", "usage", "credit", "loan")
for t in TIER:
    check(f"2 tier: `the {t} plan` is a subscription or a payment, not a design", dm(f"approve the {t} plan") == "", t)
    check(f"2 tier: `the {t} plan` in capitals", dm(f"APPROVE THE {t.upper()} PLAN") == "", t)
    for n in ("design", "proposal", "spec", "specification", "rfc"):
        check(f"2 tier: `the {t} {n}` is still a {n} asked about", dm(f"approve the {t} {n}") == n, (t, n))
check("2 tier: the API design with no link is refused", dm("approve the API design") == "design" and dm("approve the Pro design") == "design", dm("approve the API design"))
check("2 tier: a tier word after the plan does not skip it", dm("pick the plan for the Pro account") == "plan", "")
check("2 matcher: a `https://` with no host is no link", dm("approve the design at https://") == "design", dm("approve the design at https://"))
check("2 matcher: an item that is no decision is never judged", _dg._design_unlinked({"needs": ["team-back"], "ask": ask_of("approve the design")}) == "", "")
check("2 matcher: an item with no needs is never judged", _dg._design_unlinked({"ask": ask_of("approve the design")}) == "", "")
check("2 matcher: options that name alternatives are read instead", dm("pick the rollout plan", options=OPT_A) == "", "")
check("2 matcher: Approve/Decline options do not excuse the link", dm("approve the design", options=OPT_YN) == "design", "")
OPT_YN_LINK = [{"label": "Approve", "line": f"Approve it as written, see {MD}.", "recommended": True}, {"label": "Decline", "line": f"Keep things as they are, see {MD}.", "recommended": False}]
check("2 matcher: a link in an option's text is no link in the ask", dm("approve the design", options=OPT_YN_LINK) == "design", dm("approve the design", options=OPT_YN_LINK))
WATCH_ASK = "Decide: approve the design · Options: ask again in a week, two weeks or a month"
check("2 matcher: a watcher's ask (relay) is never judged", _dg._design_unlinked({"needs": ["decision"], "ask": WATCH_ASK, "watch": {"asked": "relay"}}) == "", "")
check("2 matcher: a watcher's ask (dropit) is never judged", _dg._design_unlinked({"needs": ["decision"], "ask": WATCH_ASK, "watch": {"asked": "dropit"}}) == "", "")
check("2 matcher: the same words with no watcher asking are judged", _dg._design_unlinked({"needs": ["decision"], "ask": WATCH_ASK}) == "design", _dg._design_unlinked({"needs": ["decision"], "ask": WATCH_ASK}))
check("2 matcher: a watcher mark that names no ask shape is judged", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of("approve the design"), "watch": {"asked": "relay"}}) == "design", "")
check("1 matcher: two question marks cut the first question at its own mark", _dg._second_question("approve the design? may a member be read-only?") == ("approve the design?", "may a member be read-only?"), _dg._second_question("approve the design? may a member be read-only?"))
check("1 matcher: a joiner cuts the first question before it", _dg._second_question("approve the design, and say if a member may be read-only")[0] == "approve the design", _dg._second_question("approve the design, and say if a member may be read-only"))
for w in ("doc", "document", "page", "paper", "memo"):
    for o in ("option", "options"):
        check(f"2 matcher: `{o} {w}` is a design asked about", dm(f"choose the {o} {w}") == f"{o} {w}", dm(f"choose the {o} {w}"))
for v in ("approve", "approves", "approving", "accept", "accepts", "accepting", "adopt", "adopts", "adopting", "sign off on", "signs off on", "signing off on", "sign off", "ratify", "ratifies", "ratifying",
          "endorse", "endorses", "endorsing", "green-light", "greenlight", "green-lights", "green-lighting", "pick", "picks", "picking", "choose", "chooses", "choosing", "select", "selects", "selecting",
          "decide", "decide on", "decides", "deciding", "settle on", "settles on", "settling on", "go with", "goes with", "going with", "go ahead with", "going ahead with", "review", "reviews", "reviewing",
          "confirm", "confirms", "confirming"):
    check(f"2 matcher: the verb `{v}` asks to approve a design", dm(f"whether to {v} the design") == "design" or dm(f"{v} the design") == "design", v)
for d in ("the", "this", "that", "these", "those", "our", "my", "its", "his", "her", "their", "a", "an"):
    check(f"2 matcher: the determiner `{d}` before the noun", dm(f"approve {d} design") == "design", d)
for n in ("1", "6", "12", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"):
    check(f"2 matcher: `the {n}-part rollout` is a thing named", dm(f"approve the {n}-part rollout") == f"{n}-part rollout", dm(f"approve the {n}-part rollout"))
for w in ("manager", "lock", "json", "registry", "index", "name", "version", "install"):
    check(f"2 matcher: `the package {w}` is no package asked about", dm(f"pick the package {w}") == "", w)
check("2 matcher: five words between the verb and the determiner are read", dm("approve now quickly soon fully really the design") == "design", "")
check("2 matcher: six are not", dm("approve now quickly soon fully really again the design") == "", "")
check("2 matcher: five modifiers between the determiner and the noun are read", dm("approve the very big new six-part home-brain design") == "design", "")
check("2 matcher: six are not", dm("approve the very big new fresh six-part home-brain design") == "", dm("approve the very big new fresh six-part home-brain design"))
check("2 matcher: a verb inside another word is not the verb", dm("preview the design") == "" and dm("reaccept the design") == "", "")
check("2 matcher: a plural s is read", dm("approve the designs") == "design" and dm("approve the proposals") == "proposal", "")
check("2 matcher: the noun's boundary is read (planning, special, designer, drafting, packaged)", all(dm(f"approve the {w} meeting") == "" for w in ("planning", "special", "designer", "drafting", "packaged", "plan-b")), "")
# M4: a design noun followed by a document-type word is still a design (the link is asked for); any other plain word keeps the compound exemption
DOC_WORDS = ("doc", "docs", "document", "documents", "page", "pages", "file", "files", "text", "notes", "note", "summary", "summaries", "outline", "outlines", "diagram", "diagrams", "mockup", "mockups",
             "review", "reviews", "writeup", "write-up", "writeups", "sketch", "sketches", "overview", "overviews", "section", "sections", "update", "updates", "version", "versions", "revision", "revisions")
for n in ("design", "plan", "proposal", "spec", "draft"):
    for w in DOC_WORDS:
        check(f"2 M4: `approve the {n} {w}` is still a {n} asked about", dm(f"approve the {n} {w}") == n, (n, w, dm(f"approve the {n} {w}")))
        check(f"2 M4: `APPROVE THE {n.upper()} {w.upper()}` in capitals", dm(f"APPROVE THE {n.upper()} {w.upper()}") == n, (n, w))
for t, n in (("approve the design doc", "design"), ("approve the plan update", "plan"), ("approve the proposal text", "proposal"), ("approve the spec file", "spec"), ("approve the design review", "design"),
             ("approve the design page", "design"), ("approve the design notes", "design"), ("approve the design summary", "design"), ("approve the design outline", "design"),
             ("approve the design diagram", "design"), ("approve the design mockup", "design"), ("review the draft notes", "draft"), ("approve the design doc below", "design"), ("approve the design doc.", "design")):
    check(f"2 M4: the issue's `{t}` needs a link", dm(t) == n, (t, dm(t)))
    check(f"2 M4: `{t}` with a link in the ask passes", dm(t, ask=ask_of(f"{t} {MD}")) == "", t)
for t in ("approve the design system rollout", "approve the spec change", "approve the proposal deadline", "approve the design sheet", "approve the plan rollout", "approve the draft change",
          "approve the plan renewal", "approve the spec sheet", "approve the design tokens update", "approve the design system doc", "approve the design tool page"):
    check(f"2 M4: `{t}` keeps the compound exemption", dm(t) == "", (t, dm(t)))
check("2 M4: a tier plan with a document word stays a plan of a service", dm("approve the Pro plan update") == "" and dm("approve the hosting plan page") == "", "")
check("2 M4: the `rfc doc` is an rfc", dm("approve the RFC doc") == "rfc" and dm("approve the options doc") == "options doc", "")
refused("2 M4 create: `approve the design doc` with no link is refused", lambda: mk(ask=ask_of("approve the design doc")), *DESIGN_WANT, "design")
out = mk(ask=ask_of(f"approve the design doc {MD}"))
check("2 M4 create: …and with a link is accepted", created(out), out)
out = mk(ask=ask_of("approve the design system rollout"))
check("2 M4 create: a compound is accepted", created(out), out)
# M3: a subscription or tier plan with a word beyond the first list, "plan:" with options and "plan for the lane" are a service, not a design
M3_WORDS = ("ultra", "teams", "starter", "basic", "standard", "individual", "personal", "student", "unlimited", "prepaid", "growth", "developer", "hobby", "plus", "flat-rate", "metered", "pay-as-you-go",
            "20x", "5x", "cheaper", "cheapest", "cheap", "premium", "lite")
for t in M3_WORDS:
    check(f"2 M3: `the {t} plan` is a subscription, not a design", dm(f"approve the {t} plan") == "", t)
    check(f"2 M3: `the {t.upper()} plan` in capitals", dm(f"APPROVE THE {t.upper()} PLAN") == "", t)
    for n in ("design", "proposal", "spec"):
        check(f"2 M3: `the {t} {n}` is still a {n} asked about", dm(f"approve the {t} {n}") == n, (t, n))
for t in ("approve the Ultra plan for the lane", "pick a plan: Pro or Max", "pick a plan: pro/max", "choose the plan: Pro, Max or Ultra", "pick the plan: Free or Pro", "approve the cheaper plan",
          "approve the plan for the lane", "approve the plan for this account", "approve the plan for the seat", "approve the plan for our team", "approve the plan for each machine",
          "pick a plan for my account"):
    check(f"2 M3: `{t}` is a service plan", dm(t) == "", (t, dm(t)))
for t in ("approve the migration plan", "approve the plan below", "approve the plan", "approve the rollout plan for Q3", "approve the plan: migrate in two steps", "approve the plan: stage it, then ship",
          "approve the plan: phase one, phase two", "approve the plan: see below", "pick the plan for the Pro account", "approve the plan for the migration", "approve the plan for lane work", "approve the plan for lanes", "approve the plan for teamwork",
          "approve the plan: A or B", "approve the plan:"):
    check(f"2 M3: `{t}` is a design plan and needs a link", dm(t) == "plan", (t, dm(t)))
for t in ("approve the Ultra plan for the lane", "pick a plan: Pro or Max", "approve the 20x plan", "approve the cheaper plan"):
    out = mk(ask=ask_of(t))
    check(f"2 M3 create: `{t}` needs no link and is accepted", created(out), out)
for t_ in ("approve the plan for a lane", "approve the plan for an account", "approve the plan for one seat", "approve the plan for every machine", "approve the plan for his team", "approve the plan for her seat",
           "approve the plan for their lane", "approve the plan for that account", "approve the plan for my machine"):
    check(f"2 M3: `{t_}` is a service plan", dm(t_) == "", t_)
refused("2 M3 create: `approve the migration plan` is still refused for a missing link", lambda: mk(ask=ask_of("approve the migration plan")), *DESIGN_WANT, "plan")
refused("2 M3 create: `approve the plan below` is still refused for a missing link", lambda: mk(ask=ask_of("approve the plan below")), *DESIGN_WANT, "plan")
# the refusal text reads a / an by the sound of the next word
for decide, art in (("approve the RFC", "an rfc"), ("choose the options document", "an options document"), ("choose the options page", "an options page"), ("choose the option package", "an option package"),
                    ("approve the design", "a design"), ("approve the plan", "a plan"), ("approve the spec", "a spec"), ("approve the specification", "a specification"), ("pick the proposal", "a proposal"),
                    ("accept the draft", "a draft"), ("approve the decision package", "a decision package"), ("approve the six-part rollout", "a six-part rollout"), ("choose the options memo", "an options memo")):
    try: _dg._gate_design_link({"needs": ["decision"], "ask": ask_of(decide)}); msg_ = ""
    except Exception as ex: msg_ = str(ex)
    check(f"2 grammar: `{decide}` is refused as {art}", f"this ask names {art} to approve or pick" in msg_ and f"Link the {art.split(' ', 1)[1]} in the ask" in msg_, msg_[:200])
# the guards of _design_unlinked: an item that is no decision, a watcher's ask, options that name alternatives, a link, no ask
ASK_D = ask_of("approve the home-brain design")
for why, meta in (("needs team-back", {"needs": ["team-back"]}), ("needs external", {"needs": ["external"]}), ("needs empty", {"needs": []}), ("no needs", {}), ("needs None", {"needs": None})):
    check(f"2 guard: an item with {why} is never judged", _dg._design_unlinked({**meta, "ask": ASK_D}) == "", why)
check("2 guard: the same ask on a decision is judged", _dg._design_unlinked({"needs": ["decision"], "ask": ASK_D}) == "design", "")
check("2 guard: a decision among other needs is judged", _dg._design_unlinked({"needs": ["external", "decision"], "ask": ASK_D}) == "design", "")
for mark in ("relay", "dropit"):
    check(f"2 guard: a watcher's ask (`{mark}`) is never judged", _dg._design_unlinked({"needs": ["decision"], "ask": WATCH_ASK, "watch": {"asked": mark}}) == "", mark)
check("2 guard: options that name alternatives skip the item", _dg._design_unlinked({"needs": ["decision"], "ask": ASK_D, "options": OPT_A}) == "", "")
check("2 guard: a link in the ask skips the item", _dg._design_unlinked({"needs": ["decision"], "ask": ask_of(f"approve the home-brain {MD}")}) == "", "")
check("2 guard: an empty ask names no design", _dg._design_unlinked({"needs": ["decision"], "ask": ""}) == "" and _dg._design_unlinked({"needs": ["decision"]}) == "", "")
check("2 matcher: only the Decide part is read", dm("ship the fix", ask="Decide: ship the fix · Recommend: approve the design · Stakes: the plan slips · By: no date") == "", "")
for why in ("restart the server", "a noun list", "plan-A-only", "plan A", "the package manager", "a budget"):
    out = mk(ask=ask_of(FINE_D[why]))
    check(f"2 create: {why} is accepted", created(out), out)
out = mk(ask=ask_of("pick the rollout plan", rec="Fast rollout"), options=OPT_A)
check("2 create: options that name real alternatives are read instead (no link asked)", created(out), out)
refused("2 create: Approve/Decline options do not excuse a missing link", lambda: mk(ask=ask_of("approve the home-brain design"), options=OPT_YN), *DESIGN_WANT)
out = mk(ask="Decide: ship the fix · Recommend: approve the design · Stakes: the plan slips a week · By: no date")
check("2 create: a Recommend or Stakes part that names a design is not judged", created(out), out)
out = _wt_create._create(subject="[home] review the home-brain design", description=DESC, project="projects/alpha", owner="home-front", next="team-back: review the design", needs=["team-back"])
check("2 create: an item that is no decision is never judged", created(out), out)
# an update
item(3, needs=["decision"], ask=ask_of("ship the fix"), mover="Oliver", then="team-back")
refused_nw("2 update: an ask that approves a design with no link is refused, the ask stays", 3, lambda: upd(3, ask=ask_of("approve the six-part home-brain design in the description")), *DESIGN_WANT)
refused_nw("2 update: …even with the link in the description", 3, lambda: upd(3, ask=ask_of("approve the home-brain design"), description=DESC_LINK), *DESIGN_WANT)
refused_nw("2 update: …one lifted from the first line of next", 3, lambda: upd(3, next=ask_of("approve the home-brain design") + "\nOliver: answer the ask"), *DESIGN_WANT)
out = upd(3, ask=ask_of(f"approve the six-part home-brain {MD}"))
check("2 update: the ask with the link in it is accepted", rd(3)["metadata"]["ask"] == ask_of(f"approve the six-part home-brain {MD}"), out)
item(4, needs=["team-back"], next="team-back: build it", mover="team-back")
refused_nw("2 update: putting an item on his call with an unlinked design ask is refused", 4, lambda: upd(4, needs=["decision"], ask=ask_of("approve the home-brain design"), mover="Oliver", then="team-back"), *DESIGN_WANT)
item(6, needs=["team-back"], ask=ask_of("approve the home-brain design"), next="team-back: build it", mover="team-back")
refused_nw("2 update: putting an item that already carries an unlinked design ask on his call is refused", 6, lambda: upd(6, needs=["decision"], mover="Oliver", then="team-back"), *DESIGN_WANT)
item(5, needs=["decision"], ask=ask_of("approve the home-brain design"), mover="Oliver", then="team-back")   # stored before the rule: the ask it carries stays
out = upd(5, priority="p3")
check("2 update: an old item's other-field update is not held", rd(5)["metadata"]["priority"] == "p3", out)
out = upd(5, description=DESC_LINK)
check("2 update: …nor an update of the description", rd(5)["description"] == DESC_LINK, out)
out = upd(5, next="Oliver: answer the ask\nteam-back: wait")
check("2 update: …nor an update of next", "wait" in str(rd(5)["metadata"].get("next")), out)
msg = ""
try: _dg._gate_design_link({"needs": ["decision"], "ask": ask_of("approve the home-brain design")})
except Exception as ex: msg = str(ex)
check("2 kind: a design with no link is counted under its own kind", _cl.kind_of(msg) == "an ask that approves a design or plan with no link in the ask", _cl.kind_of(msg))
# both defects in one write are refused once, with both
out = ""
try: mk(ask=ask_of("approve the six-part home-brain design in the description, and say if a board member may be read-only", rec="approve as written"))
except Exception as ex: out = str(ex)
check("2 create: the real ask has both defects and is refused once with both", "puts two questions" in out and "carries no link to it" in out and "2 problems" in out, out)

# ================================================================ 4. the gates read a bounded text in linear time
# A 1 MB (or 3 MB) body of whitespace, question marks, unclosed quotes or repeated verbs costs milliseconds: the text is collapsed and cut before it is matched, the quote patterns are bounded.
import signal, time


class _Slow(Exception):
    pass


def _timed(fn, limit=3.0):
    """(CPU seconds of this thread, result), or (None, None) when fn is still running after `limit` seconds (the regex engine checks signals, so the alarm interrupts it). CPU time: what is bounded is the
    pattern's work, and the time a busy machine leaves the thread waiting for a core is no part of it."""
    def _stop(*_a):
        raise _Slow()
    old = signal.signal(signal.SIGALRM, _stop)
    signal.setitimer(signal.ITIMER_REAL, limit)
    t0 = time.thread_time()
    try:
        r = fn()
        return time.thread_time() - t0, r
    except _Slow:
        return None, None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


MB = 1_000_000
BIG = {
    "a 1 MB run of spaces": "approve the design" + " " * MB + "and say if a member may be read-only",
    "a 1 MB run of tabs and newlines": "approve the design" + "\t\n" * (MB // 2) + "and say if a member may be read-only",
    "a question mark and 1 MB of spaces": "?" + " " * MB,
    "a million question marks and spaces": "? " * (MB // 2),
    "an unclosed curly quote and 1 MB": "\u201c" + "a" * MB,
    "a half million unclosed curly quotes": "\u201ca" * (MB // 2),
    "an unclosed straight quote and 1 MB": '"' + "a " * (MB // 2),
    "a half million unclosed straight quotes": '"a' * (MB // 2),
    "1 MB of an ampersand and letters": "&" + "a" * MB,
    "repeated `approve a `": "approve a " * (3 * MB // 10),
    "repeated `decide `": "decide " * (3 * MB // 7),
    "repeated `approve the `": "approve the " * (3 * MB // 12),
    "repeated `and `": "and " * (MB // 2),
    "repeated `, and `": ", and " * (MB // 3),
    "repeated `a? or `": "a? or " * (MB // 5),
    "repeated `Yes/No? `": "Yes/No? " * (MB // 8),
    "repeated `a?b? `": "a?b? " * (MB // 5),
    "repeated `? a`": "? a" * (MB // 3),
    "repeated `or, / `": " or, / " * (MB // 6) + "?",
}
LIMIT = 0.25
for why, body in BIG.items():
    sec, res = _timed(lambda: _dg._second_question(body))
    check(f"4 time: _second_question on {why} stays under {LIMIT} s", sec is not None and sec < LIMIT, sec)
    sec, res = _timed(lambda: _dg._design_unlinked({"needs": ["decision"], "ask": "Decide: " + body}))
    check(f"4 time: _design_unlinked on {why} stays under {LIMIT} s", sec is not None and sec < LIMIT, sec)
    sec, res = _timed(lambda: _dg._URL_ENTITY_RX.sub("", body))
    check(f"4 time: the quote and entity pattern on {why} stays under {LIMIT} s", sec is not None and sec < LIMIT, sec)
    sec, res = _timed(lambda: _dg._one_decision_kind({"ask": "Decide: " + body + " · Recommend: yes · Stakes: x · By: no date"}, ""))
    check(f"4 time: the whole decision check on {why} stays under {LIMIT} s", sec is not None and sec < LIMIT, sec)
# the answer on the whitespace body is still right (a second question after a long gap is found: the gap is one space)
first, second = _dg._second_question(BIG["a 1 MB run of spaces"])
check("4 time: …and a second question after a run of spaces is found", (first, second) == ("approve the design", "say if a member may be read-only"), (first, second))
# a growth check: 4x the text takes well under 8x the time (both fast; a quadratic pattern fails the bound above first)
t1, _r = _timed(lambda: _dg._second_question("approve the design" + " " * (MB // 4) + "and say if x"))
t4, _r = _timed(lambda: _dg._second_question("approve the design" + " " * MB + "and say if x"))
check("4 time: four times the whitespace costs less than eight times the time (plus a floor)", t1 is not None and t4 is not None and t4 < max(8 * t1, 0.05), (t1, t4))

# ================================================================ 3. the tool text
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
for tool in ("create", "update"):
    d = json.dumps(snap[tool], ensure_ascii=False)
    check(f"3 text: {tool} says one question per ask, whose answers are the options", "one question per ask, whose answers are the options" in d, d[:200])
    check(f"3 text: {tool} names the second-question joins", "and say if" in d and "and tell me whether" in d and "and, if so" in d and "when the clause ends there" in d and "and also approve …" not in d
          and "a bundled action" in d and "a conditional" in d, d[:200])
    check(f"3 text: {tool} says a compound, a subscription plan and a software package need no link", "design system rollout" in d and "subscription" in d and "package" in d, d[:200])
    check(f"3 text: {tool} says a design the ask approves is linked in the ask, with a short link text", "links it in the ask" in d and "[design](https://" in d and "short link text" in d, d[:200])
    check(f"3 text: {tool} says a link only in the description does not count", "a link only in the description" in d and "a path on a machine" in d, d[:200])
check("3 text: the ask parameter of create and update says the same", all("one question per ask" in json.dumps(snap[t]["parameters"]["ask"]) and "links it in the ask" in json.dumps(snap[t]["parameters"]["ask"]) for t in ("create", "update")),
      json.dumps(snap["create"]["parameters"].get("ask"))[:300])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": decision ask form scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
