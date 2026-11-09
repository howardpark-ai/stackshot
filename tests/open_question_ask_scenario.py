"""Scenario test for the gate that keeps the item page's Yes / No fallback from being asked an open question (server._gate_open_question) and the Recommend note beside it — fixture
data, no live store, no network, no server socket.

  1  the open-question gate on a create: a needs=decision item with no options is refused when the Decide part of its ask opens with what, which, how, who, whom, whose, when, where or why (each of the nine),
     also behind a quote or bracket, in capitals and as "What's"; the refusal names the Decide wording, says the page would show Yes / No, gives the options form and the yes/no rewording, keeps the relaunch
     hint, and nothing is written. Passes: whether / should / is / do / can / if frames, a Decide part that holds "what" later, "whoever", the same open question with options, an item that is no
     decision; "ship X now or hold" names no interrogative and passes; a list of alternatives is the alternatives gate's
  2  the same on an update: a changed ask, an options=none or clear_options that leaves an open ask without options, a move to needs=decision with an open ask already stored; an update that
     writes none of ask, options or needs (a priority, a description, a next, the same needs re-sent) is not refused for a stored open-ended ask
  3  the Recommend part: an ask whose Recommend part does not name the recommended option's label is accepted with the reply note (case-insensitive substring), never refused: scripts file asks of
     their own wording; naming the label ends the note
  4  the asks the server writes itself pass: the watcher questions (relay, drop) and the post-wake question, built with their options; a cold call's ask_owner answer is written through the update
  4  also: the question route (the script marker) skips the gate
  5  the tool text: create and update say an open question lists options or is a yes/no, no longer say an open question gets Yes and No beside a box, and say the Recommend names the label

    uv run tests/open_question_ask_scenario.py        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="openq-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
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

DESC = "- Which layout the settings page gets\n- Done when the layout is picked"
tail = " · Stakes: low · By: Fri"
YN = "Decide: whether to ship the new layout · Recommend: yes" + tail            # a yes/no frame
OPEN = lambda decide, rec="Alpha": f"Decide: {decide} · Recommend: {rec}{tail}"
A = {"label": "Alpha", "line": "The wide layout.", "recommended": True}; B = {"label": "Beta", "line": "The narrow layout.", "recommended": False}
OPTS = [A, B]
WORDS = ("what", "which", "how", "who", "whom", "whose", "when", "where", "why")
PHRASES = {"what": "what to ship", "which": "which layout to ship", "how": "how the layout is shipped", "who": "who ships the layout", "whom": "whom to ask about the layout",
           "whose": "whose layout ships", "when": "when to ship the layout", "where": "where the layout ships", "why": "why the layout ships"}
assert set(PHRASES) == set(WORDS)


def item(i, status="open", desc=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] settings layout {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H,
                                                      "state_updated": now0 - 3 * H, "confirmed": now0 - 3 * H,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "Oliver: answer the ask", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
raw = lambda i: (T / f"store/a/{i}.json").read_text()
def count(): return len(list((T / "store/a").glob("*.json")))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def err(f):
    try: return "", f()
    except Exception as e: return str(e), None
def refused(name, f, *want):
    e, out = err(f); check(name, bool(e) and all(w in e for w in want), e or out)
    return e
def refused_nw(name, i, f, *want):
    was = raw(i); e = refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None); return e
def refused_nc(name, f, *want):
    n = count(); e = refused(name, f, *want); check(name + " (nothing created)", count() == n, None); return e
def passes(name, f):
    e, out = err(f); check(name, not e, e); return out
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web import home; from stackshot.waits import watchers as wk
from stackshot.web.ui import render as r2
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: server._update(f"a{i}", sender=sender, **kw)
mk = lambda **kw: server._create(**{"subject": "[home] pick the settings layout", "description": DESC, "project": "projects/alpha", "owner": "home-front",
                                    "next": "Oliver: answer the ask", "needs": ["decision"], "ask": YN, **kw})
OQ = ("Refused", "lists no options", "open question", "Yes / No", "Decide: whether to", "options=[", "exactly one recommended", "cached tool list")

# ================================================================ 1. the open-question gate on a create
for w in WORDS:
    e = refused_nc(f"1 create: a Decide part opening with “{w}” and no options is refused", lambda w=w: mk(ask=OPEN(PHRASES[w])), *OQ, PHRASES[w])
check("1 create: the refusal names the Decide wording that triggered it, then the page's Yes / No, then the way out", e.startswith("Refused: this needs=decision item lists no options and its Decide part is an open question (“why the layout ships”)")
      and e.index("Yes / No") < e.index("options=[") < e.index("Decide: whether to"), e)
check("1 create: …and the Recommend part names the label of the option", "name the recommended option's label in the ask's Recommend part" in e, e)
for name, lead in (("a double quote", '"which layout to ship"'), ("curly quotes", "“which layout to ship”"), ("a bracket", "[which layout to ship]"), ("a parenthesis", "(which layout to ship)"),
                   ("a backtick", "`which layout to ship`"), ("a single quote", "'which layout to ship'"), ("capitals", "WHICH layout to ship"), ("a contraction", "What's the layout to ship"),
                   ("a lowercase head", "which layout to ship")):
    refused_nc(f"1 create: {name} before the interrogative is still an open question", lambda lead=lead: mk(ask=f"Decide: {lead} · Recommend: Alpha{tail}"), *OQ)
e = refused_nc("1 create: options=\"none\" on an open question is the same as none", lambda: mk(ask=OPEN("which layout to ship"), options="none"), *OQ)
e = refused_nc("1 create: an empty options list is none too", lambda: mk(ask=OPEN("which layout to ship"), options=[]), *OQ)
for name, decide in (("whether", "whether to ship the new layout"), ("should", "should we ship the new layout"), ("is", "is the new layout ready to ship"), ("do", "do we ship the new layout"),
                     ("can", "can we ship the new layout"), ("if", "if the new layout ships now"), ("a verb", "ship the new layout"),
                     ("whether, with what later", "whether what we shipped is enough"), ("should, with which later", "should we ship the layout which Alpha drew"),
                     ("what later in the sentence", "ship what we built"), ("whoever is a different word", "whoever answers first ships the layout"), ("however", "however the layout ships, ship it"),
                     ("whatever", "whatever layout is ready ships now"), ("a quoted whether", '"whether to ship the layout"')):
    out = passes(f"1 create: a yes/no or other frame passes with no options: {name}", lambda decide=decide: mk(ask=OPEN(decide, "yes")))
    check(f"1 create: …{name} is stored", bool(re.match(r"created \w\d+", out or "")), out)
for w in WORDS:
    out = passes(f"1 create: “{w}” with its options listed passes", lambda w=w: mk(ask=OPEN(PHRASES[w]), options=OPTS))
    check(f"1 create: …“{w}” with options is stored", bool(re.match(r"created \w\d+", out or "")), out)
e = refused_nc("1 create: a list of alternatives is the alternatives gate's, not this one's", lambda: mk(ask=OPEN("ship the wide, narrow or tall layout", "wide")), "names alternatives")
check("1 create: …and the alternatives refusal no longer says an open question gets Yes / No and a box", "box to write in" not in e and "open question" in e, e)
passes("1 create: an item that is no decision is not judged (the ask is read only on a decision)", lambda: server._create(subject="[home] build the layout", description=DESC, project="projects/alpha", owner="home-front",
                                                                                                                      next="team-back: build it", needs=["team-back"], ask=OPEN("which layout to ship")))

out = passes("1 create: “ship X now or hold” names no interrogative and no list: this gate leaves it alone", lambda: mk(ask=OPEN("ship the layout now or hold", "yes")))
check("1 create: …it is stored", bool(re.match(r"created \w\d+", out or "")), out)

# ================================================================ 2. the open-question gate on an update
item(1, needs=["decision"], ask=YN, mover="Oliver", then="team-back")
for w in WORDS:
    refused_nw(f"2 update: a changed ask opening with “{w}”, no options listed, is refused", 1, lambda w=w: upd(1, ask=OPEN(PHRASES[w])), *OQ, PHRASES[w])
refused_nw("2 update: …behind a quote", 1, lambda: upd(1, ask=OPEN('"which layout to ship"')), *OQ)
refused_nw("2 update: …behind a bracket", 1, lambda: upd(1, ask=OPEN("[how to ship the layout]")), *OQ)
upd(1, ask=OPEN("which layout to ship"), options=OPTS)
check("2 update: the same ask with its options in the same call is accepted", rd(1)["metadata"]["ask"] == OPEN("which layout to ship") and rd(1)["metadata"]["options"] == OPTS, rd(1)["metadata"])
refused_nw("2 update: options=\"none\" under an open ask is refused (the options would leave an open question to Yes / No)", 1, lambda: upd(1, options="none"), *OQ)
refused_nw("2 update: …so is options=[]", 1, lambda: upd(1, options=[]), *OQ)
refused_nw("2 update: …and clear_options=true", 1, lambda: upd(1, clear_options=True), *OQ)
upd(1, ask=YN, options="none")
check("2 update: options=\"none\" with a yes/no ask in the same call is accepted", "options" not in rd(1)["metadata"] and rd(1)["metadata"]["ask"] == YN, rd(1)["metadata"])
item(2, needs=["decision"], ask=YN, options=OPTS, mover="Oliver", then="team-back")
refused_nw("2 update: a new open ask over listed options that the call clears is refused", 2, lambda: upd(2, ask=OPEN("what to ship"), options="none"), *OQ)
upd(2, ask=OPEN("what to ship"))
check("2 update: a new open ask over the options already listed is accepted", rd(2)["metadata"]["ask"] == OPEN("what to ship") and rd(2)["metadata"]["options"] == OPTS, rd(2)["metadata"])
# a move to his call with an open ask already stored
item(3, needs=["team-back"], ask=OPEN("which layout to ship"), next="team-back: build it", mover="team-back")
refused_nw("2 update: a move to needs=decision with an open ask stored and no options is refused", 3, lambda: upd(3, needs=["decision"], mover="Oliver", then="team-back"), *OQ)
upd(3, needs=["decision"], options=OPTS, mover="Oliver", then="team-back")
check("2 update: …accepted with the options in the same call", rd(3)["metadata"]["needs"] == ["decision"] and rd(3)["metadata"]["options"] == OPTS, rd(3)["metadata"])
# an unrelated write on an item stored with an open ask and no options is not held
item(5, needs=["decision"], ask=OPEN("which layout to ship"), mover="Oliver", then="team-back", state="your-call")
was = rd(5)["metadata"]["ask"]
upd(5, priority="p3")
check("2 update: a priority on an item stored with an open ask is not refused", rd(5)["metadata"]["priority"] == "p3" and rd(5)["metadata"]["ask"] == was, rd(5)["metadata"])
upd(5, description="- Which layout the settings page gets, said again\n- Done when the layout is picked")
check("2 update: …nor a description", "said again" in rd(5)["description"], rd(5)["description"])
upd(5, next="Oliver: answer the ask on the item")
check("2 update: …nor a next", rd(5)["metadata"]["next"].startswith("Oliver: answer"), rd(5)["metadata"].get("next"))
upd(5, needs=["decision"])
check("2 update: …nor the same needs sent again", rd(5)["metadata"]["needs"] == ["decision"], rd(5)["metadata"])
upd(5, needs=["decision", "team-back"])
check("2 update: …nor a session added beside the decision", "team-back" in rd(5)["metadata"]["needs"] and rd(5)["metadata"]["needs"][0] == "decision", rd(5)["metadata"])
upd(5, subject="[home] settings layout five, renamed")
check("2 update: …nor a rename", rd(5)["subject"].endswith("renamed"), rd(5)["subject"])
check("2 update: …and the stored ask is as it was", rd(5)["metadata"]["ask"] == was and "options" not in rd(5)["metadata"], rd(5)["metadata"])
# an item that closes, or is no decision, is not judged
item(6, needs=["team-back"], ask=OPEN("which layout to ship"), next="team-back: build it", mover="team-back")
passes("2 update: an item that is no decision may carry an open ask", lambda: upd(6, priority="p2"))
item(7, needs=["decision"], ask=OPEN("which layout to ship"), mover="Oliver", then="team-back")
passes("2 update: a close of an item with an open ask and no options is not judged", lambda: upd(7, status="completed", outcome="done", reason="the layout was picked in a call", outcome_text="- The layout was picked in a call"))

# ================================================================ 3. the Recommend part is a note, never a refusal
NOTE = "(note: the ask's Recommend part does not name the recommended option, "
out = passes("3 create: a Recommend part that does not name the recommended label is accepted, with a note naming the label", lambda: mk(ask=OPEN("whether to ship the wide layout", "none, your call"), options=OPTS))
check("3 create: …the note names “Alpha”", NOTE + "\u201cAlpha\u201d" in (out or ""), out)
out = passes("3 create: naming the label (any case) ends the note", lambda: mk(ask=OPEN("whether to ship the wide layout", "ALPHA"), options=OPTS))
check("3 create: …no note", "(note: the ask's Recommend" not in (out or ""), out)
yn = [{"label": "Approve", "line": "Ship it.", "recommended": True}, {"label": "Decline", "line": "Hold it.", "recommended": False}]
out = passes("3 create: Approve / Decline with a Recommend of “yes” is accepted (a script's wording), with the note", lambda: mk(ask=YN, options=yn))
check("3 create: …the note names “Approve”", NOTE + "\u201cApprove\u201d" in (out or ""), out)
item(10, needs=["decision"], ask=OPEN("whether to ship the wide layout", "ship it"), mover="Oliver", then="team-back")
out = passes("3 update: options set under a Recommend that skips the label are accepted, with the note", lambda: upd(10, options=OPTS))
check("3 update: …stored, and the note is in the reply", rd(10)["metadata"]["options"] == OPTS and NOTE in (out or ""), out)
out = passes("3 update: a priority on the same item carries no note", lambda: upd(10, priority="p3"))
check("3 update: …no note", "(note: the ask's Recommend" not in (out or ""), out)

# ================================================================ 4. the asks the server writes itself
ev = {"wait_event": "countersigned NDA"}
for what, ask, opts in (("the relay question", wk.relay_ask(ev), wk.relay_options()), ("the drop question", wk.drop_ask(ev), wk.drop_options())):
    m = {"needs": ["decision"], "ask": ask, "options": opts, "watch": {"asked": "relay" if "relay" in what else "dropit"}}
    check(f"4 watcher: {what} is no open question and its Recommend part is not judged", server._open_question(m) == "" and server._recommend_missing(m) == "", (ask, server._open_question(m)))
    passes(f"4 watcher: {what} passes the open-question gate and names its recommended label", lambda m=m: (server._gate_open_question(m), server._recommend_missing(m)))
    m2 = {**m, "options": None}
    passes(f"4 watcher: {what} without its options is still the watcher's own and passes the open-question gate", lambda m2=m2: server._gate_open_question(m2))
wm = {"needs": ["decision"], "ask": "Decide: what has arrived? · Options: arrived / not yet, ask again on <date> / drop", "watch": {"asked": "relay"}}
check("4 watcher: a watcher's own ask that happens to open with an interrogative word is read as the watcher's and not refused", server._open_question(wm) != "" and server._watch.asked_of(wm) == "relay", wm)
passes("4 watcher: …the open-question gate lets it stand with no options", lambda: server._gate_open_question(wm))
refused("4 watcher: …while the same words with no watcher mark on the item are refused", lambda: server._gate_open_question({k: v for k, v in wm.items() if k != "watch"}), *OQ[:3])
ask, opts = server._watch_ask("a1", {}, "its wait ended")
m = {"needs": ["decision"], "ask": ask, "options": opts}
check("4 post-wake: the question the server builds opens with “what” and lists two options, which name the recommended label", server._open_question(m) != "" and len(opts) == 2, (ask, opts))
passes("4 post-wake: …and passes the open-question gate and names its recommended label", lambda: (server._gate_open_question(m), server._recommend_missing(m)))
# a cold call's ask_owner answer is written through the update, so the gates read it
item(20, needs=["team-back"], mover="team-back", next="team-back: look at it")
cold = server._ho.COLD
refused_nw("4 cold call: an ask_owner whose question is open and whose options are missing is refused", 20,
           lambda: server._update("a20", needs=["decision"], ask=OPEN("which layout to ship"), next="Oliver: answer the ask on the item", clear_next=True, sender=cold, clear_mover=True), *OQ)
passes("4 cold call: …with two to four options naming the recommended label it is written", lambda: server._update("a20", needs=["decision"], ask=OPEN("which layout to ship"), options=OPTS,
                                                                                                              next="Oliver: answer the ask on the item", clear_next=True, sender=cold, clear_mover=True))
check("4 cold call: …and stored", rd(20)["metadata"]["ask"] == OPEN("which layout to ship") and rd(20)["metadata"]["options"] == OPTS, rd(20)["metadata"])
from stackshot.model import cold_call as cc
ok, why = cc.validate({"action": "ask_owner", "ask": OPEN("which layout to ship"), "options": OPTS}, set())
check("4 cold call: the answer's own validation is unchanged: an ask and two to six options", ok is not None and not why, (ok, why))

# a script's question (client.py post question) is never lost on its wording: the marker the question route sets skips the open-question gate
server._QUESTION.on = True
try:
    out = passes("4 question route: an open question with no options still files an item", lambda: mk(ask=OPEN("which layout to ship", "none, your call")))
finally:
    server._QUESTION.on = False
check("4 question route: …it is stored", bool(re.match(r"created \w\d+", out or "")), out)
refused_nc("4 question route: …while the same ask through the create tool is refused", lambda: mk(ask=OPEN("which layout to ship", "none, your call")), *OQ)

# ================================================================ 5. the tool text
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
for tool in ("create", "update"):
    d = snap[tool]["description"]
    check(f"5 text: {tool} says a Decide part opening with what, which, how, who, when, where or why is refused with no options, and what to do", "whose Decide part opens with what, which, how, who, when, where or why is refused" in d
          and "since Yes / No cannot answer it" in d and "list its answers as options or reword it as a yes/no" in d, d[:200])
    check(f"5 text: {tool} no longer says an open question gets Yes and No beside a box to write in", "box to write in" not in d and "lists none and gets" not in d and "Yes (recommended)" not in d, d[:200])
    check(f"5 text: {tool} says the Recommend names the recommended option's label, and promises no refusal for it", "the ask's Recommend names the recommended one's label." in d and "Recommend part does not name" not in d, d[:200])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": open question ask scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
