"""Scenario test for the audit's delivery of a finding about how an item is written or filed, on an item the owner moves: it asks nothing of him, so it is never marked for him and starts no front turn.
Fixture items, messages replaced by recorders, no live store, no network, no model call.

  1  the classification: every category the audit can raise is either one that needs nothing of the owner (audit_checks.NO_PERSON_NEED), or one the table below names as its own (stale: his wake; stuck-elsewhere
     and event-missing carry their own recipient); a category named nowhere keeps the marked path
  2  a finding that needs nothing of him, on an item he moves: in a project with a builder it goes to that builder as a plain unmarked message; in a project with no builder it is held for the -main agent's next turn
     (an fyi, no mark, no turn); a held note the front agent cannot be given goes unmarked to the project's page key; a finding with no project is held for the -main agent too
  3  what is kept: a finding that needs him (stale, or a category named nowhere) goes to the -main agent marked as before; a finding for a background agent, and one on an item another session moves, are unchanged
  4  the ten-minute pass: an ask-options finding on an item the owner moves is held once and is not sent again, however long the item stays unwritten; a write to the item sends it afresh; a finding that is
     not about the owner's item is still reminded; the daily run's delivery (deliver_findings) routes the same way

    tests/run-suite filing_held        -> exit 0 / 1"""
import datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="filing-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
for key, val in (("agent", "falcon-audit"), ("builder", "falcon-engineer"), ("main", "falcon-main")):
    toml, n = re.subn(rf"(?m)^{key} = \"my-[a-z]+\"", f"{key} = \"{val}\"", toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR
H = 3600; now = time.time()
OWNER = "00000000-0000-4000-8000-000000000001"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

ROLES = {"demo-main": {"role": "front"}, "demo-builder": {"role": "background"}, "demo-writer": {"role": "background"}, "gone-agent": {"role": "background", "retired": True}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(front_only=False, **kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
    return AR.Env(roles=ROLES, fallback=kw.pop("fallback", lambda p: "demo-main"), builder=kw.pop("builder", lambda p: "demo-builder"), page_of=lambda p: ("", None), front_only=lambda p: front_only,
                  deliver=kw.pop("deliver", deliver), sessions=lambda: None, **kw)
shown = lambda n: "board" + chr(35) + str(n)      # an item as the audit shows it, built here so no id-shaped literal sits in the file
def finding(category, to="", mover="Oliver", project="projects/demo", i=9107, detail="the ask does not name the recommended option"):
    return {"id": shown(i), "project": project, "owner": mover, "mover": mover, "category": category, "detail": detail, "fix": "reword it", "source": "code", **({"to": to} if to else {})}
def send(fs, **kw):
    sent.clear()
    out = AR.deliver_findings(env(**kw), fs, "Filing check 2099-03-03 10:00 UTC")
    return out
msgs = lambda: [(to, t.startswith("[for Oliver]"), fy) for to, t, fy in sent]

# ---- 1. the classification
named = set(AC.CHECKS_CODE) | set(AC.CHECKS_FILING) | set(AR.CHECKS_MODEL) | {"proof-wait", "older-than-page"}
own = {"stale": "his wake", "stuck-elsewhere": "its own recipient", "event-missing": "its own recipient"}
no_need = getattr(AC, "NO_PERSON_NEED", frozenset())
check("1 every category the audit can raise is classified: needs nothing of him, or named as its own", all(c in no_need or c in own for c in named), sorted(c for c in named if c not in no_need and c not in own))
check("1 the three the table keeps back are not in the quiet set", not (set(own) & set(no_need)), set(own) & set(no_need))
check("1 a category named nowhere needs him (the marked path)", getattr(AC, "needs_person", lambda c: False)("a-new-check") is True)

# ---- 2. a finding that needs nothing of him, on an item he moves
for cat in ("ask-options", "ask-missing", "board checks", "reads-as-wait", "next rules"):
    sent.clear(); _, reached, _ = send([finding(cat)])
    check(f"2 {cat} in a project with a builder: one plain message to the builder, unmarked, not an fyi, nothing to the -main agent", msgs() == [("demo-builder", False, False)] and len(reached) == 1, sent)
sent.clear(); _, reached, _ = send([finding("ask-options")], front_only=True)
check("2 ask-options in a project with no builder (the live case: the -main agent writes the item): held for the -main agent, as an fyi, no mark", msgs() == [("demo-main", False, True)] and len(reached) == 1, sent)
check("2 …and the held note carries the finding whole, under its label line", sent[0][1].splitlines()[0] == "[stackshot] Filing check 2099-03-03 10:00 UTC:" and shown(9107) + " · ask-options · the ask does not name the recommended option · reword it" in sent[0][1], sent)
sent.clear(); send([finding("ask-options", i=9107), finding("reads-as-wait", i=9108)], front_only=True)
check("2 two findings for the front agent are two held notes, one line each", [(to, fy) for to, _m, fy in msgs()] == [("demo-main", True), ("demo-main", True)] and all(t.count("board#") == 1 for _to, t, _f in sent), sent)
sent.clear(); _, reached, _ = send([finding("ask-options")], front_only=True, deliver=lambda to, t, fy=False: (sent.append((to, t, fy)), (False, "[400] Refused: demo-main is a front agent whose hook cannot fetch held lines") if to == "demo-main" else (True, "[200] ok"))[1])
check("2 a held note the front agent cannot be given goes unmarked to the project's page key, never marked for the owner, and counts as reached", [(to, m) for to, m, _f in msgs()] == [("demo-main", False), ("projects/demo", False)] and len(reached) == 1, (sent, reached))
sent.clear(); _, reached, _ = send([finding("ask-options", project="")], front_only=True)
check("2 a finding with no project is held for the -main agent, unmarked", msgs() == [("demo-main", False, True)] and len(reached) == 1, sent)
sent.clear(); _, reached, _ = send([finding("ask-options")], front_only=True, fallback=lambda p: "someone-unknown")
check("2 a -main agent the role map does not know as a front agent: the page key, unmarked", msgs() == [("projects/demo", False, False)], sent)

recs, _r, _s = send([finding("ask-options")], front_only=True)
check("2 the record of the send says it was held", [m.get("kind") for m in recs] == ["held"], recs)
sent.clear(); send([finding("ask-options")], builder=lambda p: "gone-agent")
check("2 a retired builder is no builder: the finding is held for the -main agent", msgs() == [("demo-main", False, True)], sent)
sent.clear(); send([finding("ask-options")], builder=lambda p: "demo-main")
check("2 a front agent named as the builder is no builder either: held for the -main agent", msgs() == [("demo-main", False, True)], sent)
def unreadable(p): raise RuntimeError("registry unreadable")
sent.clear(); send([finding("ask-options")], front_only=unreadable)
check("2 a registry that cannot be read counts as no builder: held, never marked", msgs() == [("demo-main", False, True)], sent)
longf = finding("ask-missing", detail="stored needs: decision but carries no ask, and its next line names three sessions that each wait on the others to answer first, so nothing here can move")
longf["fix"] = "write the ask Oliver is to decide, or take needs: decision off the item, and say in the same write which session moves it next"
sent.clear(); send([longf], front_only=True)
note = sent[0][1].splitlines()
check("2 a long finding whose fix says needs: decision is still held (the phrase is written without the colon), on one short line that keeps its id and check", msgs() == [("demo-main", False, True)]
      and not re.search(r"needs:\s*decision", sent[0][1], re.I) and len(note) == 2 and len(note[1]) <= 145 and note[1].startswith(shown(9107) + " \u00b7 ask-missing"), (sent, [len(x) for x in note]))
sent.clear(); _, reached, _ = send([finding("ask-options")], front_only=True, deliver=lambda to, t, fy=False: (sent.append((to, t, fy)), (False, "[400] down"))[1])
check("2 when the held send and the page-key send both fail, the finding has reached no one (it is tried again next pass)", [to for to, _m, _f in msgs()] == ["demo-main", "projects/demo"] and reached == [], (sent, reached))

ROLES["other-main"] = {"role": "front"}
def flaky(to, text, fyi=False):
    sent.append((to, text, fyi))
    return (False, "[404] no such session") if to in ("demo-builder", "other-main") else (True, "[200] ok")
pair = [finding("ask-options", mover="demo-builder", to="demo-builder", project="projects/one", i=9201), finding("ask-options", mover="demo-builder", to="demo-builder", project="projects/two", i=9202)]
sent.clear(); _o = AR.deliver_findings(env(deliver=flaky, fallback=lambda p: "other-main" if p.endswith("two") else "demo-main"), pair, "Filing check 2099-03-03 10:00 UTC")
check("2 two projects share an unreachable builder and only one project's fallback lands: only that finding counts as delivered, the other is tried again next pass",
      [f["id"] for f in _o[1]] == [shown(9201)] and [m["delivered"] for m in _o[0] if m.get("kind") == "fallback"] == [True, False], (_o[1], _o[0]))
sent.clear(); _o = AR.deliver_findings(env(deliver=flaky, fallback=lambda p: "demo-main"), pair, "Filing check 2099-03-03 10:00 UTC")
check("2 when every fallback lands, every finding of the group counts as delivered", [f["id"] for f in _o[1]] == [shown(9201), shown(9202)], _o[1])
sent.clear(); _o = AR.deliver_findings(env(deliver=flaky, fallback=lambda p: "demo-builder" if p.endswith("one") else "demo-main"), pair, "Filing check 2099-03-03 10:00 UTC")
check("2 a finding whose project has no one else to tell (its -main agent is the unreachable builder itself) is not counted as delivered when another project's fallback lands: it is tried again",
      [f["id"] for f in _o[1]] == [shown(9202)], _o[1])
def mixed(down):
    def dl(to, text, fyi=False):
        sent.append((to, text, fyi))
        return (False, "[404] gone") if to in ("demo-builder", down) else (True, "[200] ok")
    return dl
quiet = finding("ask-options", mover="Oliver", to="Oliver", project="projects/one", i=9301)       # the owner's item: its fallback is the page key, unmarked
loud = finding("ask-options", mover="demo-builder", to="demo-builder", project="projects/two", i=9302)       # a session's item: its fallback is the -main agent
for down, want in (("projects/one", [shown(9302)]), ("demo-main", [shown(9301)])):
    sent.clear(); _o = AR.deliver_findings(env(deliver=mixed(down), builder=lambda p: "demo-builder", fallback=lambda p: "demo-main"), [quiet, loud], "Filing check 2099-03-03 10:00 UTC")
    check(f"2 one group with a page-key fallback and a -main fallback, the {'page-key' if down.startswith('projects') else '-main'} send failing: only the other send's finding counts as delivered",
          [f["id"] for f in _o[1]] == want and sorted(to for to, _t, _f in sent) == sorted(["demo-builder", "projects/one", "demo-main"]), (_o[1], [(to, fy) for to, _t, fy in sent]))
def same_name(to, text, fyi=False):       # the page key and the -main agent read alike; the unmarked page-key message is refused, the marked -main one lands
    sent.append((to, text, fyi))
    return (False, "[404] gone") if to == "demo-builder" or (to == "projects/one" and not text.startswith("[for Oliver]")) else (True, "[200] ok")
quiet1 = finding("ask-options", mover="Oliver", to="Oliver", project="projects/one", i=9303); loud1 = finding("ask-options", mover="demo-builder", to="demo-builder", project="projects/one", i=9304)
sent.clear(); _o = AR.deliver_findings(env(deliver=same_name, builder=lambda p: "demo-builder", fallback=lambda p: "projects/one"), [quiet1, loud1], "Filing check 2099-03-03 10:00 UTC")
check("2 a page-key fallback and a -main fallback that read alike are two sends: when only the marked -main one lands, only its finding counts as delivered", [f["id"] for f in _o[1]] == [shown(9304)], (_o[1], [(to, t[:24]) for to, t, _f in sent]))
fo = env(front_only=True, builder=lambda p: "")
check("2 the unmoved digest of a quiet finding on an item the owner moves, in a project with no builder, goes to the page key unmarked, never to the -main agent marked for him", AR.chase_to(fo, "projects/demo", "Oliver") == ("projects/demo", False), AR.chase_to(fo, "projects/demo", "Oliver"))
check("2 in a project with a builder it goes to the builder, unmarked", AR.chase_to(env(), "projects/demo", "Oliver") == ("demo-builder", False), AR.chase_to(env(), "projects/demo", "Oliver"))

# ---- 3. what stays
sent.clear(); send([finding("stale", detail="past its wake")])
check("3 a finding that needs him (stale) keeps the marked path: the -main agent, [for Oliver] first, a real message", msgs() == [("demo-main", True, False)], sent)
sent.clear(); send([finding("a-new-check")])
check("3 a category named nowhere keeps it too, until it is classified", msgs() == [("demo-main", True, False)], sent)
sent.clear(); send([finding("ask-options", mover="demo-writer")])
check("3 a finding on an item a background agent moves goes to that agent, plain, as before", msgs() == [("demo-writer", False, False)], sent)
sent.clear(); send([finding("stuck-elsewhere", to="demo-writer", mover="demo-builder")])
check("3 a finding with its own recipient (stuck-elsewhere) goes there, as before", msgs() == [("demo-writer", False, False)], sent)
sent.clear(); send([finding("ask-options", to="Oliver", mover="demo-writer")])
check("3 a finding addressed to the owner on an item another session moves follows that mover, as before", msgs() == [("demo-writer", False, False)], sent)
check("3 recipient() itself is unchanged for the marked path: the owner on his own item goes to the -main agent, marked", AR.recipient("Oliver", "projects/demo", env(), "Oliver") == ("demo-main", True))

# ---- 4. the ten-minute pass
def asking(i, rec, options=None, **kw):
    ask = f"Decide: which database · Recommend: {rec} · Stakes: a day either way · By: no date"
    d = {"id": str(i), "subject": f"[demo] item a{i}", "description": "- Goal: a database is chosen", "status": "open", "updated": now - H, "state_updated": now - H, "confirmed": now - H,
         "written_at": now - H, "written_by": "demo-main", "metadata": {"owner": OWNER, "project": "projects/demo", "state": "your-call", "needs": ["decision"], "mover": "Oliver", "ask": ask, "next": "Oliver: decide",
                                                                     **({"options": options} if options else {}), **kw}}
    return f"a{i}", d
opts = lambda *labels: [{"label": l, "line": f"Go with {l}.", "recommended": False} for l in labels]
one = dict([asking(9101, "Gamma", opts("Alpha", "Beta"))])
check("4 the fixture is a real ask-options finding", AC.check_ask_options(one["a9101"]["metadata"]) != "", AC.check_ask_options(one["a9101"]["metadata"]))
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
clear_state()
r1 = AR.filing_pass(now=now, items=one, anchors={}, env=env(front_only=True))
check("4 the pass holds the finding once: one fyi to the -main agent, no mark, no other message", [(to, m, fy) for to, m, fy in msgs()] == [("demo-main", False, True)] and shown(9101) + " · ask-options" in sent[0][1] and r1["fresh"] == 1, (r1, sent))
sent.clear()
r2 = AR.filing_pass(now=now + 600, items=one, anchors={}, env=env(front_only=True))
check("4 ten minutes on it is not sent again", sent == [] and r2["repeats"] == 1, (r2, sent))
sent.clear()
r3 = AR.filing_pass(now=now + 40 * H, items=one, anchors={}, env=env(front_only=True))
check("4 …nor after the reminder time, nor escalated, however long the item stays unwritten: nothing further is held for the front agent and nothing is marked for the owner", sent == [] and r3["fresh"] == 0, (r3, sent))
rec = json.loads((T / "state/audit/filing.json").read_text())
check("4 …and the record keeps it as sent once", [f["id"] for f in rec["findings"]] == [shown(9101)] and rec["findings"][0].get("sent") and rec["findings"][0].get("tries", 1) == 1, rec["findings"])
fresher = {"a9101": {**one["a9101"], "written_at": time.time() + 60}}
sent.clear(); r4 = AR.filing_pass(now=now + 41 * H, items=fresher, anchors={}, env=env(front_only=True))
check("4 a write to the item sends the finding afresh, held again", [(to, fy) for to, _m, fy in msgs()] == [("demo-main", True)] and r4["fresh"] == 1, (r4, sent))
clear_state()
reads = dict([("a9102", {"id": "9102", "subject": "[demo] item a9102", "description": "- Goal: x", "status": "open", "updated": now - H, "state_updated": now - H, "confirmed": now - H, "written_at": now - H, "written_by": "demo-writer",
                      "metadata": {"owner": OWNER, "project": "projects/demo", "state": "doing", "needs": ["demo-writer"], "next": "demo-writer: waiting for the build"}})])
AR.filing_pass(now=now, items=reads, anchors={}, env=env())
sent.clear(); r = AR.filing_pass(now=now + 7 * H, items=reads, anchors={}, env=env())
check("4 control: a finding on a background agent's item is still reminded after the reminder time (the clock is live in this fixture)", [(to, fy) for to, _m, fy in msgs()] == [("demo-writer", False)] and "second try" in sent[0][1], (r, sent))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
