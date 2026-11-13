"""Scenario test for the gate that keeps the owner's own action out of needs=decision (server._gate_own_action) — fixture data, no live
store, no network, no server process (the server module is imported and called in-process, on a temporary config).

A decision is a choice the owner makes; a step is something he does (step=<his action>, which stores the your-step state and which the board ticks when
he says it is done). An ask that only confirms his own action reads his Yes as consent, not as the step done, so it is refused.

Covers: on create and on update, a needs=decision ask that only confirms his own action is refused with the message that names
step="<his action>" and says a real choice stays a decision: "have you done …", "did you run …", "has <owner> set …",
"is it done", "are they done", Yes/No (or Done/Not yet) options over a single `<owner>:` line of next, and a Decide part that names his own
action ("Decide: install the apps and delete the test repo?") with Yes/No over one or more of his next lines that are that action; nothing is written. Real
decisions are accepted: Approve/Decline over a go-ahead, options that name alternatives (even with a "have you …" ask), an open question
("which …", "should we …"), Yes/No options with no own line in next. A your-step with step=<his action> is accepted, and so is an update
that turns a refused shape into one. The rule is to refuse only when the ask's question is his own action, read from his own next lines:
Yes/No over one own line that the ask does not name ("whether to merge the patch" over "<owner>: review the patch") is a decision, and so is a
judgement or an alternative ("have you decided …", "have you changed your mind …", "is it complete enough to send", "has he run into the bug himself", "… and does it work for you", "… or may I pick …", "is the plan complete enough …"); Approve/Decline or no options
over his own line that the Decide part names ("Decide: delete the test repo?") is refused; a write that only changes next refuses an
unchanged ask only when a new line of his is the action the ask confirms.

    tests/run-suite own_step_decision        → exit 0 / 1"""
import os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ownsteptest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
import json
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-kiwi", "home-kiwi-main", "home-kiwi-engineer")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/kiwi.md").write_text("---\ntype: project\ntitle: Kiwi\ndisplay-name: home-kiwi\nagents:\n  home-kiwi-main: talks to the owner\n"
                                           "  background:\n    home-kiwi-engineer: builds and merges\nstatus: active\n---\n\n# x\n", encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import ids as _model_ids
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
O = server.OWNER
DESC = "- Goal: The release of the fruit sorter\n- It lives in the sorter repo\n- Done when the release is out"
YESNO = [{"label": "Yes", "line": "The step is done.", "recommended": True}, {"label": "No", "line": "The step is not done yet.", "recommended": False}]
DONE_NOT = [{"label": "Done", "line": "The step is done.", "recommended": True}, {"label": "Not yet", "line": "Still to do.", "recommended": False}]
GO = [{"label": "Approve", "line": "Ship the sorter release tonight.", "recommended": True}, {"label": "Decline", "line": "Hold the release a week.", "recommended": False}]
ALTS = [{"label": "Nightly", "line": "Run the sorter's sync every night.", "recommended": True}, {"label": "Hourly", "line": "Run the sorter's sync every hour.", "recommended": False}]
def ask(decide): return f"Decide: {decide} · Recommend: yes · Stakes: the release waits · By: no date"
def items():
    return sorted(p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit() and p_.stem != "1")
def create(**kw):
    a = dict(subject="[home] Ship the sorter release", description=DESC, project="projects/kiwi", sender="home-kiwi-engineer", then="home-kiwi-engineer",
             needs=["decision"], ask=ask("whether to ship the sorter release tonight"), options=GO)
    a.update(kw)
    try: return _wt_create.stackshot_create(**a), ""
    except server.ToolError as e: return "", str(e)
def gid_of(out):
    m = re.search(r"\bboard#\d+|\b[a-z]\d+\b", out); assert m, out
    return m.group(0)
def update(gid, **kw):
    try: return _wt_update.stackshot_update(item_id=gid, sender="home-kiwi-engineer", **kw), ""
    except server.ToolError as e: return "", str(e)
def says_step(e): return 'step="<his action>"' in e and 'state=' not in e and "real choice" in e and "two items" in e

# ---- 1. create: his own action asked as a decision is refused, nothing written
for name, kw in (("have you done …", dict(ask=ask("have you done the two repo settings steps"), options=YESNO)),
                 ("did you run …", dict(ask=ask("did you run the release script on the sorter box"), options=None)),
                 (f"has {O} set …", dict(ask=ask(f"has {O} set the sorter's secret yet"), options=None)),
                 ("is it done", dict(ask=ask("is it done?"), options=YESNO)),
                 ("did you set a date for the demo", dict(ask=ask("did you set a date for the demo"), options=YESNO)),
                 ("have you done the two GitHub steps", dict(ask=ask("have you done the two GitHub steps"), options=YESNO)),
                 ("are they done", dict(ask=ask("are they all done"), options=DONE_NOT))):
    before = items(); out, e = create(**kw)
    check(f"create refused: {name}", e.startswith("Refused: this needs=decision item") and says_step(e) and items() == before, e or out)
before = items()
out, e = create(ask=ask("whether to turn on the two repo settings for the sorter"), options=YESNO, next=f"{O}: turn on the two repo settings for the sorter\nhome-kiwi-engineer: tag the release")
check("create refused: Yes/No options over a single owner line of next that the Decide part names", "Yes/No over" in e and says_step(e) and items() == before, e or out)
check("…the create refusal says a create has no step (set it by update)", "(a create has no step)" in e, e)
check("…the refusal reads as one sentence (item whose options are …)", e.startswith("Refused: this needs=decision item whose options are Yes/No over"), e)
out, e = create(ask=ask("have you done the two repo settings steps"), options=YESNO)
check("…and the ask variant reads the same way (item whose ask only asks …)", e.startswith("Refused: this needs=decision item whose ask only asks whether"), e)

# ---- 1a. Yes/No over a single owner line with no tie between the ask and that line is a decision
for name, decide, line in (("merge the patch over his review of the patch", "whether to merge the patch", f"{O}: review the patch"),
                           ("send the email over his read of the draft", "Send the email to the vendor now?", f"{O}: read the vendor draft email"),
                           ("ship tonight over his review of the notes", "ship the release tonight?", f"{O}: review the release notes"),
                           ("a release over an unrelated line of his", "whether the sorter release goes out", f"{O}: turn on the two repo settings for the sorter")):
    out, e = create(ask=ask(decide), options=YESNO, next=f"{line}\nhome-kiwi-engineer: tag the release")
    check(f"create accepted: Yes/No, {name}", out and not e, e)

# ---- 1c. a judgement or an alternative is not his own step
for decide in ("Have you decided between A and B?", "Have you decided whether to ship?", "Have you got a view on pricing, flat or tiered?",
               "Have you done the migration yourself or should the builder run it?", "Have you set the date, or may I pick next Monday?",
               "Have you reviewed the draft and is it fine to send?", "Is the plan complete enough to start?", "Is the soak done, so we can merge?",
               "Is the soak finished or extend?",
               "have you changed your mind about the pricing", "have you moved on from the old plan",
               "have you tested the new login flow and does it work for you", "is this done to your liking",
               "is it complete enough to send", "is this finished enough to ship to the vendor", "has he run into the bug himself",
               "have you come up with a name", "is it done and is it fine to send", "is it done, so we can send it?"):
    out, e = create(ask=ask(decide), options=YESNO)
    check(f"create accepted: {decide!r} (Yes/No)", out and not e, e)
    why = server._own_action_ask({"needs": ["decision"], "ask": ask(decide)})   # no options: another gate asks for them when alternatives are named
    check(f"the gate accepts {decide!r} with no options", not why, why)

why = server._own_action_ask({"needs": ["decision"], "ask": ask("have you moved on from option A"), "options": YESNO})   # create has its own gate on a bare option code
check("the gate accepts 'have you moved on from option A' with Yes/No", not why, why)

# ---- 1c2. rule 1 is skipped when the options are Approve/Decline (a go-ahead is a decision)
out, e = create(ask=ask("have you done the two GitHub steps"), options=GO)
check("create accepted: a have-you ask with Approve/Decline options", out and not e, e)
why = server._own_action_ask({"needs": ["decision"], "ask": ask("have you done the two GitHub steps"), "options": GO})
check("the gate skips rule 1 for Approve/Decline", not why, why)
for decide in ("have you done the two GitHub steps", "did you set a date for the demo", "is it done?", "are they done"):
    why = server._own_action_ask({"needs": ["decision"], "ask": ask(decide), "options": YESNO})
    check(f"the gate still refuses {decide!r} with Yes/No", "only asks whether" in why, why)

# ---- 1d. Approve/Decline, or no options, over his own next line that the Decide part names
for name, kw in (("Approve/Decline over his own next line", dict(options=GO)), ("no options over his own next line", dict(options=None))):
    before = items(); out, e = create(ask=ask("delete the test repo?"), next=f"{O}: delete the test repo\nhome-kiwi-engineer: tag the release", **kw)
    check(f"create refused: {name}", e.startswith("Refused: this needs=decision item whose Decide part only names") and says_step(e) and items() == before, e or out)
why = server._own_action_ask({"needs": ["decision"], "ask": "Decide: delete the test repo?", "next": f"{O}: delete the test repo"})
check("the gate refuses a bare Decide: ask with no options over his own next line", "only names" in why, why)
why = server._own_action_ask({"needs": ["decision"], "ask": "Decide: send the email to the vendor now?", "options": GO, "next": f"{O}: read the vendor draft email"})
check("…but not Approve/Decline whose Decide part is not his next line's action", not why, why)

# ---- 1b. create: a Decide part that names his own action, Yes/No over one or more of his next lines that are that action
TWO_OWN = f"{O}: install the two sorter apps from the store\n{O}: delete the test repo\nhome-kiwi-engineer: tag the release"
for name, kw in (("Decide: <his two actions>? over his two next lines", dict(ask=ask("install the apps and delete the test repo?"), options=YESNO, next=TWO_OWN)),
                 ("…with Done/Not yet", dict(ask=ask("install the apps and delete the test repo?"), options=DONE_NOT, next=TWO_OWN)),
                 ("…over one of his next lines among others", dict(ask=ask("delete the test repo?"), options=YESNO,
                                                                     next=f"{O}: delete the test repo\n{O}: water the plants\nhome-kiwi-engineer: tag the release"))):
    before = items(); out, e = create(**kw)
    check(f"create refused: {name}", e.startswith("Refused: this needs=decision item") and says_step(e) and items() == before, e or out)
why = server._own_action_ask({"needs": ["decision"], "ask": "Decide: install the apps and delete the test repo?", "options": YESNO, "next": TWO_OWN})
check("the gate reads a bare Decide: ask (no Recommend, Stakes, By) the same way", "only names" in why, why)
for name, kw in (("a choice between alternatives over his own lines", dict(ask=ask("install the new apps or keep the old ones"), next=TWO_OWN,
                                                                             options=[{"label": "New apps", "line": "Install the two new sorter apps.", "recommended": True},
                                                                                      {"label": "Old apps", "line": "Keep the old sorter apps.", "recommended": False}])),
                 ("Yes/No on a release beside his own lines", dict(ask=ask("whether the sorter release goes out tonight"), options=YESNO, next=TWO_OWN)),
                 ("Approve/Decline go-ahead beside his own lines", dict(ask=ask("whether to ship the sorter release tonight"), options=GO, next=TWO_OWN))):
    out, e = create(**kw)
    check(f"create accepted: {name}", out and not e, e)

# ---- 2. create: real decisions are accepted
for name, kw in (("Approve/Decline over a go-ahead", {}),
                 ("options that name alternatives, even after a have-you ask", dict(ask=ask("have you a preference: run the sync nightly or hourly"), options=ALTS)),
                 ("an open question (which …)", dict(ask=ask("which sync schedule the sorter takes"), options=ALTS)),
                 ("an open question (should we …)", dict(ask=ask("should we ship the sorter release tonight"), options=None)),
                 ("Yes/No with no own line in next", dict(ask=ask("whether the sorter release goes out tonight"), options=YESNO)),
                 ("Yes/No with two own lines in next (not a single step)", dict(ask=ask("whether the sorter release goes out tonight"), options=YESNO,
                                                                                next=f"{O}: turn on the repo setting\n{O}: add the deploy key"))):
    out, e = create(**kw)
    check(f"create accepted: {name}", out and not e, e)

# ---- 3. update: the same gate; your-step is the way
out, e = create(needs="", ask="", options=None, then="", mover="home-kiwi-engineer", next="home-kiwi-engineer: prepare the sorter release")
check("a plain item for the updates", out and not e, e); g = gid_of(out)
out, e = update(g, needs=["decision"], ask=ask("have you done the two repo settings steps"), options=YESNO)
check("update refused: have you done …", says_step(e) and "take decision out of needs" in e, e or out)
check("…nothing written: the item has no decision", "decision" not in (server._load(_model_ids._norm_id(g))["metadata"].get("needs") or []), server._load(_model_ids._norm_id(g))["metadata"])
out, e = update(g, needs=["decision"], ask=ask("whether to turn on the two repo settings for the sorter"), options=YESNO, next=f"home-kiwi-engineer: prepare the sorter release\n{O}: turn on the two repo settings for the sorter")
check("update refused: Yes/No options over his single next line that the Decide part names", "Yes/No over" in e and says_step(e), e or out)
out, e = update(g, needs=["decision"], ask=ask("install the apps and delete the test repo?"), options=YESNO, next=f"home-kiwi-engineer: prepare the sorter release\n{TWO_OWN}")
check("update refused: Decide: <his actions>? with Yes/No over his next lines", says_step(e) and "take decision out of needs" in e, e or out)
out, e = update(g, step="Turn on the two repo settings for the sorter", next=f"home-kiwi-engineer: prepare the sorter release\n{O}: turn on the two repo settings for the sorter")
meta = server._load(_model_ids._norm_id(g))["metadata"]
check("update accepted: step=<his action> (stores your-step)", out and not e and meta.get("state") == "your-step", e or meta)
out2, e2 = create(needs="", ask="", options=None, then="", mover="home-kiwi-engineer", next="home-kiwi-engineer: prepare the sync")
g2 = gid_of(out2)
out, e = update(g2, needs=["decision"], ask=ask("which sync schedule the sorter takes"), options=ALTS)
check("update accepted: a real choice with options that name alternatives", out and not e, e)
out, e = update(g2, ask=ask("did you run the sync by hand"), options=ALTS)
check("…a have-you ask beside options that name alternatives stays a decision", out and not e, e)
out, e = update(g2, options=YESNO, ask=ask("did you run the sync by hand"))
check("…the same ask with Yes/No options is refused", says_step(e), e or out)

out3, e3 = create(needs="", ask="", options=None, then="", mover="home-kiwi-engineer", next="home-kiwi-engineer: prepare the release")
g3 = gid_of(out3)
out, e = update(g3, needs=["decision"], ask=ask("ship the release tonight?"), options=YESNO)
check("update accepted: a Yes/No decision", out and not e, e)
nx = server._load(_model_ids._norm_id(g3))["metadata"].get("next") or ""
out, e = update(g3, next=f"{nx}\n{O}: review the release notes")
check("…a write that only adds his own unrelated next line leaves the decision standing", out and not e, e)
nx = server._load(_model_ids._norm_id(g3))["metadata"].get("next") or ""
out, e = update(g3, next=f"{nx}\n{O}: ship the release tonight")
check("…a write that adds the very action the ask confirms is refused", says_step(e), e or out)

# ---- 4. the tool text says the difference
check("the needs text says decision vs your-step", "decision vs your-step" in _wt_text._NEEDS_FORM and "the board ticks it when he says it is done" in _wt_text._NEEDS_FORM, _wt_text._NEEDS_FORM[:200])
check("the wait text says his call is needs=decision with an ask and his own step is step=", 'needs=[\"decision\"] with an ask; his own step is step=<one line' in _wt_update._WAIT_FORM, "")
check("the ask text says such an ask is refused and names your-step", 'Decide: install the apps and delete the test repo?' in _wt_text._ITEM_FORM and 'use step=\\"<his action>\\" instead' in _wt_text._ITEM_FORM.replace('"', '\\"'), "")
check("the needs text no longer counts doing it himself as a decision", "or do it himself" not in _wt_text._NEEDS_FORM, "")

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
