"""Scenario test for the item model's write guards (model_guards.py, step 1, PR 2) — fixture data, no live store, no network, no server socket.

A create or update is refused, with what is wrong and the fix, when it would leave an item wrong by the model (PR 1: dead | alive | waiting):

  1  an alive item whose mover is not the owner, a live session or the project's background agent (the model's defaults fill an unnamed one)
  2  a wait without its input (a time its wake, an anchor the anchor and event, an item its after, a relay its event) or with a post-wake mover that is none of those
  3  a time wait (a hold with a wake) with neither the owner's words (a stored quote that parks, waits, says until or names a date) nor a real date (wait_basis)
  4  filler (TBD, TBC, "?", a dash) in goal, next, ask, wait_event
  5  a wait with no end (an anchor, item or relay wait with neither ask_by nor a backstop wake)
  6  needs decision together with a hold
  6b his state makes him the mover (the agent in then); 6c the way back when his wait ends, the server's own saves, and the start-up migration
  6d the mirror: the owner as mover needs his step (your-step) or his ask (your-call, needs decision); doing or queued with him as mover is refused, a waiting item, a close and a bookkeeping write are not judged
  7  a second mover in needs (two sessions, or decision plus a session); switchable by [model] one_mover
  8  a next line with no `<name>: ` (the owner, a session, the background agent)
  9  a next line that reads as a wait on an alive item (the precise list), with a negation passing and the broad list flagged (read from next; nothing is stored)
 10  the re-park test compares the structured fields only (a next or description edit neither resets nor stands for a change)
 11  an alarming word (leak, breach, exposed, quota, credential, kill) in subject, ask or next, with the everyday word

and the rest of the rule: a guard on a field runs when the write sets that field, the state invariants when it creates the item or sets a field that defines the state or the wait
(an old item's untouched fields never block an unrelated update); a close is never refused; [model] guards = false turns it all off; the report on the existing items counts what the
guards would refuse (read only) and the brief carries one line of it.

An item's old state word (doing, your-step, outside …) is fixture data here: no call sets or clears one any more (tests/retired_inputs_scenario.py); `step=` stores his step (your-step) and
needs=["decision"] with an ask his call, and the guards read the item as stored.

    tests/run-suite model_guards        → exit 0 / 1"""
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, subprocess, sys, pathlib, tempfile, time, logging, hashlib
BID_A = 9166
BID_B = 9167
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="mguardtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True, keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about what the guards judge in the text written, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-peer", "home-lost", "home-beta-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
ZONE_OFFSET = 4 * 3600.0                             # the instance timezone (the config's `timezone` above): UTC+4, no DST
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": "2026-01-01T00:00:00Z"} if n == "home-lost" else {})} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
# alpha: front home-front; background team-back, home-other and home-idle (listed, no pane running); beta: background home-beta-bg (listed, no pane running)
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-idle": "listed, no pane"}, {"team-back": "the back", "home-other": "the other", "home-idle": "listed, no pane"}),
    "projects/beta": proj("home-beta-front", {"home-beta-front": "the front", "home-beta-bg": "listed, no pane"}, {"home-beta-bg": "listed, no pane"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-idle: listed, no pane\n---\n\n# Alpha\n")
(T / "brain/projects/beta.md").write_text("---\ntitle: Beta\ndisplay-name: home-beta-front\nagents:\n  home-beta-front: the front\n  background:\n    home-beta-bg: listed, no pane\n---\n\n# Beta\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    base = {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "home-front: do the thing"}
    base.update(meta)
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want, none=()):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want) and not any(w in str(e) for w in none), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.service import gates; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web.tools import brief as _wt_brief; from stackshot.web.tools import complete as _wt_complete; from stackshot.web.tools import create as _wt_create; from stackshot.web.tools import get as _wt_get; from stackshot.service import writes; from stackshot.waits import waiting as W; from stackshot.model import model; from stackshot.model import model_guards as mg
from stackshot.service import store as _service_store
from stackshot.github import ghsync as _gh
from stackshot.anchors import anchors as _anc
from stackshot.fleet import sessions_registry as _fleet_sessions_registry
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import migrations as migsvc
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False      # kept stubbed: this suite sets a reminder wake on an alive item another session moves, as home-front, to touch a state field; the real front test would refuse it (suite watch covers the rule)
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # an expected_by n hours after the suite started (a time of day)
BACK, OTHER, FRONT, IDLE = "team-back", "home-other", "home-front", "home-idle"
OWN = model.owner_display()
FUT = day(5)
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
mt = lambda i, letter="a": rd(i, letter)["metadata"]
raw = lambda i, letter="a": (T / f"store/{letter}/{i}.json").read_text()
def upd(i, **kw): return server._update(f"a{i}", sender="home-front", **kw)
def refused_nw(name, i, f, *want, none=()):
    was = raw(i); refused(name, f, *want, none=none); check(name + " (nothing written)", raw(i) == was, None)
def set_cfg(**kw):
    _cfg.CFG["model"] = {"rebullet_machines": ["box-a"], **kw}      # the example-owner instance lists box-a (tests/_instance.py); a suite that sets [model] whole keeps it
set_cfg()

# ================================================================ the words (pure)
check("filler: TBD, TBC, tba, a question mark, dashes, dots and \"to be determined\" are placeholders",
      all(mg.is_filler(x) for x in ("TBD", "tbc", "TBA.", "?", "??", "—", "-", "...", "…", "To be determined", "(TBD)")), None)
check("filler: …a sentence that only mentions one, a real word and an empty value are not", not any(mg.is_filler(x) for x in ("TBD by Robin's reply", "Ship it", "a?", "", "tbd-list is built")), None)
check("filler: a next line is judged after its `<name>:`, an ask by its parts, a goal as one value",
      mg.filler_in("next", "home-front: do x\n- Oliver: TBD") == "- Oliver: TBD" and mg.filler_in("next", "home-front: do x") == ""
      and mg.filler_in("ask", "Decide: TBD · Recommend: yes · Stakes: low · By: no date").startswith("Decide") and mg.filler_in("ask", ASK) == ""
      and mg.filler_in("goal", "TBC") == "TBC" and mg.filler_in("wait_event", "?") == "?", None)
check("alarm: each word and its everyday word, any case, word-bounded",
      mg.alarm_in("a leak in the cache") == ("leak", "leftover files") and mg.alarm_in("Credentials rotated") == ("Credentials", "sign-in") and mg.alarm_in("the port is exposed") == ("exposed", "visible")
      and mg.alarm_in("quota hit")[1] == "limit or disk space" and mg.alarm_in("a data breach")[1] == "access problem" and mg.alarm_in("kill the pane") == ("kill", "stop")
      and mg.alarm_in("killed it")[1] == "stopped" and mg.alarm_in("a killer feature") == ("", "") and mg.alarm_in("no problem") == ("", "") and mg.alarm_in("leakage") == ("", ""), None)
check("alarm: a code span and a link are not prose", mg.alarm_in("run `kill -9 12`") == ("", "") and mg.alarm_in("see https://x.example/quota/exposed") == ("", ""), None)
PRECISE = ["home-front: wait for the PR to merge", "home-front: waiting on Robin", "home-front: blocked on board#12", "home-front: blocked by the review", "home-front: do it until 2026-11-02",
           f"home-front: keep going until board#{BID_A}", "home-front: hold it until #12", "home-front: park until Monday", "home-front: once the PR lands, ship", "home-front: once it merges tell Robin",
           "home-front: once Robin replies", "home-front: on hold", "home-front: 返信待機中", "home-front: 返信を待つ予定", "home-front: Wait until the build is done", "home-front: until Nov 12th"]
check("next wait: every line of the precise list is caught", all(mg.wait_lines(x)[0] for x in PRECISE), [x for x in PRECISE if not mg.wait_lines(x)[0]])
NEG = ["home-front: no waiting for a slot", "home-front: not blocked on anything", "home-front: never wait for it", "home-front: there is no need to wait for the build", "home-front: we are not waiting on Robin"]
check("next wait: a negation passes", not any(mg.wait_lines(x)[0] for x in NEG), [x for x in NEG if mg.wait_lines(x)[0]])
h, b = mg.wait_lines("home-front: run it when ready\nhome-front: merge after the review\nhome-front: once done, ship\nhome-front: poll until it passes")
check("next wait: the broad list (when, once, after, until) is not a hit, and is named", not h and b == ["when", "after", "once", "until"], (h, b))
check("next wait: a plain action is neither; a code span and a server note are not read", mg.wait_lines("home-front: ship the fix\n(server: waiting for a recycle)\nhome-front: run `until true; do :; done`") == ([], []), mg.wait_lines("home-front: ship the fix\n(server: waiting for a recycle)\nhome-front: run `until true; do :; done`"))
check("next openers: the name before the colon; a list marker and bold marks are skipped; a sub-line and a note are not lines",
      mg.next_openers("home-front: do x\n- Oliver: run `cmd`\n**Oliver:** go\ndo the thing\n  - sub step\n(a note)\n\nRun the fix now: x") == [("home-front: do x", "home-front"), ("- Oliver: run `cmd`", "Oliver"), ("**Oliver:** go", "Oliver"),
                                                                                                                   ("do the thing", ""), ("Run the fix now: x", "")], mg.next_openers("home-front: do x\n- Oliver: run `cmd`\n**Oliver:** go\ndo the thing\n  - sub step\n(a note)\n\nRun the fix now: x"))
check("next openers: a role in parentheses after the name is not part of the name; a name that is only a label is no actor (write checks); the hint names the label or the missing space",
      mg.next_openers("home-agent (builder): do x\nKim (the vendor): send") == [("home-agent (builder): do x", "home-agent"), ("Kim (the vendor): send", "Kim")]
      and mg.not_actor("Status") and mg.not_actor(" NOTE ") and not mg.not_actor("Kim") and not mg.not_actor("Updates team") and not mg.not_actor("")
      and mg.line_hint("Status: ok").startswith("`Status:` is a label") and mg.line_hint("home-agent:do it").startswith("put a space after the colon") and mg.line_hint("see https://x.org/a") == "" and mg.line_hint("plain words") == "",
      (mg.line_hint("Status: ok"), mg.line_hint("home-agent:do it")))
check("words: a quote that parks, waits, says until or names a date has wait words; \"go ahead\" has none",
      all(mg.has_wait_words(x) for x in ("park it until next week", "wait for Robin", "Jan 9th 2099 is fine", "2026-11-03", "来週まで保留", "postpone it", "tomorrow", "on Mon")) and not any(mg.has_wait_words(x) for x in ("go ahead", "Approve", "yes", "")), None)

# ================================================================ 1. an alive item names a mover who can move it
item(60, needs=[])
refused_nw("1 mover: an unknown session is refused, with the fix", 60, lambda: upd(60, mover="home-nobody"), "Refused:", "a60", "is alive", "home-nobody", "no session the registry or the fleet knows", "mover=<that name>", "live session")
refused_nw("1 mover: a session whose pane is gone is refused", 60, lambda: upd(60, mover="home-lost"), "home-lost", "pane is gone")
upd(60, mover="home-peer")
check("1 mover: a live session that no page names is a mover", mt(60)["mover"] == "home-peer", mt(60))
upd(60, mover="Oliver", step="gh pr merge 241 --squash")
check("1 mover: the owner is a mover (stored as the instance names him), with his step", mt(60)["mover"] == OWN and mt(60)["state"] == "your-step", mt(60))
set_cfg(handoff=False)      # a listed background agent with no pane is a mover for the guards; the hand-off's send-time guard (handoff suite) would refuse it
item(59, needs=[])
upd(59, mover=IDLE)
set_cfg()
check("1 mover: a background agent the project's page lists is a mover though no pane of it runs", mt(59)["mover"] == IDLE, mt(59))
refused_nw("1 mover: …a background agent of another project, with no pane, is not", 60, lambda: upd(60, mover="home-beta-bg"), "home-beta-bg", "no session the registry or the fleet knows")
item(61, owner=U["home-lost"], needs=[])
upd(61, wake=FUT)
check("1 mover: an unnamed mover defaults to the project's builder (never the creator, whose pane is gone here), which passes", wk_(mt(61)) == FUT and "mover" not in mt(61), mt(61))
upd(61, mover=BACK, wake=FUT)
check("1 mover: …naming a valid mover in the same write stores it", mt(61)["mover"] == BACK and wk_(mt(61)) == FUT, mt(61))
item(62, owner=U["home-lost"], needs=[], mover="home-nobody")
refused_nw("1 mover: a stored mover that is no one is refused when a state field is set (a backstop wake)", 62, lambda: upd(62, wake=FUT), "home-nobody")
refused("1 mover: a create with a mover that is no one is refused and writes nothing",
        lambda: _wt_create._create(subject="[home] mover create", description=DESC, project="projects/alpha", owner="home-front", next="home-front: go", mover="home-nobody"), "this item is alive", "home-nobody")
check("1 mover: …nothing was written", not any(json.loads(p.read_text())["subject"] == "[home] mover create" for p in (T / "store").glob("*/*.json")), None)
# the registry: retired and live rows (a fake of sessions_registry, as the fleet tool writes it)
class FakeReg:
    rows = {"s-ret": {"id": "s-ret", "name": "home-ret", "state": "retired"}, "s-live": {"id": "s-live", "name": "home-reglive", "state": "live"}}
    def available(self): return True
    def resolve(self, x): return next((k for k, r in self.rows.items() if x in (k, r["name"])), None)
    def row(self, x): k = self.resolve(x); return dict(self.rows[k]) if k else None
    def display_name(self, x): r = self.row(x); return r["name"] if r else None
    def names_of(self, x): r = self.row(x); return [r["name"]] if r else []
    def all_names(self): return {k: r["name"] for k, r in self.rows.items()}
    def load(self): return type("L", (), {"rows": self.rows})()
real_sr = mg._sr; mg._sr = FakeReg()
c0 = mg.Ctx()
check("1 mover: the registry's retired row is no mover, its live row is (a fleet pane is not needed)", c0.session_state("home-ret") == "retired" and "retired session" in c0.mover_problem("home-ret", "projects/alpha")
      and c0.mover_problem("home-reglive", "projects/alpha") == "" and c0.session_state("home-nobody") == "unknown", (c0.session_state("home-ret"), c0.session_state("home-reglive")))
mg._sr = real_sr
check("1 mover: a cloud session (cse_ id) is accepted, and with no registry and no heartbeat at all nothing can be judged", mg.Ctx().session_state("cse_abc") == "cloud"
      and (lambda c: (setattr(c, "_rows", {}), c.session_state("home-x"))[1])(mg.Ctx()) == "blind", None)

# ================================================================ 2. a wait names its input and its post-wake mover
item(63, needs=[BACK])
refused_nw("2 wait: an anchor wait names its anchor and its event, and has an end", 63, lambda: upd(63, wait_kind="anchor"), "waits on an anchor event", "names its anchor", "wait_anchor=<url>", "the event it expects", "wait_event=")
refused_nw("2 wait: …the event is missing", 63, lambda: upd(63, wait_kind="anchor", wait_anchor="https://github.com/x/y/pull/1", ask_by=FUT), "the event it expects", none=("names its anchor",))
_anc.save({"projects/alpha": [{"url": "https://github.com/x/y/pull/1", "items": None, "added": now0, "by": "x"}]})      # the anchor is on the project's list (a wait on an unlisted one is refused: anchor_wait_refusal)
upd(63, wait_kind="anchor", wait_anchor="https://github.com/x/y/pull/1", wait_event="merged", ask_by=FUT)
check("2 wait: …anchor, event and an end pass; the item reads as waiting on the anchor", model.derive(_service_store._load("a63")).wait.kind == "anchor" and ab_(mt(63)) == FUT, mt(63))
item(64, needs=[BACK])
refused_nw("2 wait: an item wait names the items it waits after", 64, lambda: upd(64, wait_kind="item", ask_by=FUT), "another item's close", "after=[\"board#N\"]")
upd(64, wait_kind="item", after=["a63"], ask_by=FUT)
check("2 wait: …with its after and an end it passes", mt(64)["after"] == ["a63"], mt(64))
item(65, needs=[BACK])
refused_nw("2 wait: a relay wait names the party or event", 65, lambda: upd(65, wait_kind="relay", ask_by=FUT), "news only", "wait_event=<who or what>")
upd(65, wait_kind="relay", wait_event="Robin's reply on the contract", ask_by=FUT)
check("2 wait: …with its event and an ask-by day it passes (the post-wake mover defaults to the owner)", mt(65)["wait_kind"] == "relay" and model.derive(_service_store._load("a65")).wait.post_wake_mover == OWN, mt(65))
item(66, needs=[BACK])
item(166, needs=[BACK])
out = upd(166, wait_kind="time")
check("2 wait: a time wait with no date is not refused: until is taken (tomorrow when nothing gives one) and the reply says so", W.stored_until(mt(166)) and "wait_kind=time came with no date" in out and "set to tomorrow" in out, (out[-300:], mt(166)))
refused_nw("2 post-wake mover: a post-wake mover that is no one is refused, with the fix", 66, lambda: upd(66, wait_kind="relay", wait_event="Robin", ask_by=FUT, post_wake_mover="home-nobody"),
           "post-wake mover, home-nobody", "no session the registry or the fleet knows", "post_wake_mover=<")
refused_nw("2 post-wake mover: …one whose pane is gone is refused too", 66, lambda: upd(66, wait_kind="relay", wait_event="Robin", ask_by=FUT, post_wake_mover="home-lost"), "home-lost", "pane is gone")
upd(66, wait_kind="relay", wait_event="Robin", ask_by=FUT, post_wake_mover="home-peer")
check("2 post-wake mover: …a live session passes", mt(66)["post_wake_mover"] == "home-peer", mt(66))
item(67, owner=U["home-lost"], needs=[])
upd(67, wait_kind="item", after=["a63"], ask_by=FUT)
check("2 post-wake mover: an unnamed one defaults like a mover, to the project's builder, which passes", mt(67)["wait_kind"] == "item" and "post_wake_mover" not in mt(67), mt(67))
upd(67, wait_kind="relay", wait_event="Robin", ask_by=FUT)
check("2 post-wake mover: …a relay's default is the owner, who always passes", mt(67)["wait_kind"] == "relay", mt(67))

# ================================================================ 3. a time wait carries his words or a real date
item(68, needs=[BACK])
refused_nw("3 snooze: a hold with a wake and no reason is refused, saying what counts", 68, lambda: upd(68, hold=True, wake=day(3)), "waits on a time (wake", "no reason", "wait_basis=", "Acked-by", "set no date")
upd(68, hold=True, wake=day(3), wait_basis=f"vendor visit booked for {day(4)}")
check("3 snooze: …a real date (wait_basis) stands for it, at any length (the cap is not what asks)", mt(68)["wait_basis"]["text"].startswith("vendor visit") and hd_(mt(68)) is True, mt(68))
item(69, needs=[BACK], answers=[{"ts": time.time(), "kind": "comment", "text": "park it until next week, nothing to do now", "via": "board"}])
upd(69, hold=True, wake=day(3))
check("3 snooze: …his words on the item (a board comment that parks) stand for it, and the quote is stored with the wake", mt(69)["cap_ok"]["wake"] == day(3) and "park it until next week" in mt(69)["cap_ok"]["quote"], mt(69))
item(70, needs=[BACK], answers=[{"ts": time.time(), "kind": "decision", "text": "go ahead", "via": "board"}])
refused_nw("3 snooze: …his words with no park, wait, until or date word do not", 70, lambda: upd(70, hold=True, wake=day(3)), "no reason")
item(71, needs=[BACK])
upd(71, wake=day(3))
check("3 snooze: a wake alone on an alive item is the mover's backstop, not a wait: not refused", wk_(mt(71)) == day(3) and "hold" not in mt(71), mt(71))
item(72, needs=[BACK], answers=[{"ts": time.time(), "kind": "comment", "text": "park it until Jan 9th 2099", "via": "board"}])
upd(72, hold=True, wake=day(20))
check("3 snooze: a wake past the cap on his words still works and now keeps his quote", mt(72)["cap_ok"]["wake"] == day(20) and "Jan 9th 2099" in mt(72)["cap_ok"]["quote"], mt(72))
item(73, needs=[BACK], hold=True, wake=day(4), cap_ok={"wake": day(4), "by": "a board answer", "quote": "ok", "source": "x"})
refused_nw("3 snooze: a stored quote with no wait words is no reason when the wake is set again", 73, lambda: upd(73, wake=day(5)), "no reason")
item(74, needs=[BACK], hold=True, wake=day(4), cap_ok={"wake": day(4), "by": "a board answer", "quote": "hold it until the 4th", "source": "x"})
upd(74, description="- A thing\n- It lives here, changed\n- Done when done")
check("3 snooze: …a stored reason stands: an unrelated update of the held item passes", wk_(mt(74)) == day(4), mt(74))
set_cfg(guards=False)
item(75, needs=[BACK])
upd(75, hold=True, wake=day(3))
check("3 snooze: with [model] guards = false the same write passes (the switch)", hd_(mt(75)) is True, mt(75))
set_cfg()

# ================================================================ 4. filler
item(76, needs=[BACK])
refused_nw("4 filler: a next line that is TBD", 76, lambda: upd(76, next="home-front: TBD"), "next holds a placeholder", "write the real next")
refused_nw("4 filler: a goal that is TBC", 76, lambda: upd(76, goal="TBC"), "goal holds a placeholder")
refused_nw("4 filler: a wait_event that is a question mark", 76, lambda: upd(76, wait_kind="relay", wait_event="?", ask_by=FUT), "wait_event holds a placeholder")
refused_nw("4 filler: a next line that is a dash", 76, lambda: upd(76, next="home-front: —"), "placeholder")
upd(76, next="home-front: TBD is what the schema doc says, so read it", goal="The thing ships")
check("4 filler: …a sentence that mentions TBD is not a placeholder", mt(76)["goal"] == "The thing ships", mt(76))
refused("4 filler: a create with a placeholder next is refused", lambda: _wt_create._create(subject="[home] filler create", description=DESC, project="projects/alpha", owner="home-front", next="home-front: TBD"), "next holds a placeholder")

# ================================================================ 5. a wait has an end
item(77, needs=[BACK])
item(177, needs=[BACK])
out = upd(177, wait_kind="anchor", wait_anchor="https://github.com/x/y/pull/1", wait_event="merged")
check("5 end: an anchor wait with no date is not refused: until is taken and the reply says so", W.stored_until(mt(177)) and "wait_kind=anchor came with no date" in out and "wake" not in mt(177) and "ask_by" not in mt(177), (out[-300:], mt(177)))
upd(77, wait_kind="anchor", wait_anchor="https://github.com/x/y/pull/1", wait_event="merged", wake=FUT)
check("5 end: …a backstop wake is its end (it stays a wake beside an event wait)", wk_(mt(77)) == FUT and "hold" not in mt(77), mt(77))
item(78, needs=[BACK])
item(178, needs=[BACK])
out = upd(178, wait_kind="item", after=["a77"])
check("5 end: an item wait with no date is not refused: until is taken and the reply says so", W.stored_until(mt(178)) and "wait_kind=item came with no date" in out and mt(178)["after"] == ["a77"], (out[-300:], mt(178)))
item(188, needs=[BACK])
out = upd(188, wait_kind="relay", wait_event="Robin")
check("5 end: a relay wait with no date is not refused: until is its ask-by day and the reply says so", W.stored_until(mt(188)) and "wait_kind=relay came with no date" in out and "ask_by" not in mt(188), (out[-300:], mt(188)))
out = upd(188, wait_kind="item", after=["a77"])
check("5 end: …a date held for one kind moves with the wait to another kind", mt(188)["wait_kind"] == "item" and W.stored_until(mt(188)) and "came with no date" not in out, (out[-300:], mt(188)))
item(79, needs=[BACK], state="outside", party="Acme legal", chase=day(6))
upd(79, wake=FUT)
check("5 end: a legacy outside item's chase day is its ask-by (a write that touches a state field passes)", wk_(mt(79)) == FUT, mt(79))

# ================================================================ 6. decision with a hold
item(80, needs=[BACK])
refused_nw("6 decision + hold: needs decision with a hold is refused, saying an ask for later is a time wait", 80, lambda: upd(80, needs=["decision"], ask=ASK, hold=True, wake=day(3), wait_basis=f"visit on {day(4)}"),
           "needs holds decision together with a hold", "an ask for later is a time wait whose post-wake mover is", "clear_hold=true", "post_wake_mover=")
upd(80, needs=["decision"], ask=ASK)
check("6 decision + hold: …a decision without the hold passes", "decision" in mt(80)["needs"], mt(80))
item(81, needs=["decision"], ask=ASK, hold=True, wake=day(3))
refused_nw("6 decision + hold: an old item that has both is refused when a write touches a field of the state", 81, lambda: upd(81, wake=day(4)), "decision together with a hold")
upd(81, clear_hold=True)
check("6 decision + hold: …clear_hold is the fix", "hold" not in mt(81), mt(81))
item(96, needs=["decision"], ask=ASK, hold=True, wake=day(3))
upd(96, description="- A thing\n- It lives here, changed\n- Done when done")
check("6 decision + hold: …an update that does not touch them passes (and drops the stale hold, as before)", rd(96)["description"].endswith("changed\n- Done when done") and "hold" not in mt(96), mt(96))

# ================================================================ 6b. his state makes him the mover
STEP = "gh pr merge 241 --squash"
item(46, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
out_e = upd(46, step=STEP)
check("6b mover/state: an agent's update to your-step that names no mover makes him the mover and the stored agent the then-mover, with a note in the reply",
      mt(46)["mover"] == OWN and mt(46)["then"] == BACK and mt(46)["state"] == "your-step" and f"mover: {BACK} → {OWN}" in out_e and f"then {BACK} takes it" in out_e, (mt(46), out_e))
g_a = _wt_get.stackshot_get("a46")
check("6b mover/state: …and get reads clean: mover Oliver, then the agent, no model conflict", "model conflict" not in g_a and f"mover: {OWN}" in g_a and f"then: {BACK}" in g_a, g_a)
item(47, needs=[BACK], mover=BACK, then=FRONT)
out_f = upd(47, needs=["decision"], ask=ASK)
check("6b mover/state: needs decision added with no mover named: the same, and a stored then is kept (not replaced by the old mover)",
      mt(47)["mover"] == OWN and mt(47)["then"] == FRONT and "decision" in mt(47)["needs"] and "model conflict" not in _wt_get.stackshot_get("a47"), mt(47))
check("6b mover/state: …when the kept then is not the old mover the note says how to have it come back (then=<you>); when it is, no such hint",
      "set then=<you>" in out_f and "set then=<you>" not in out_e, (out_f, out_e))
item(130, needs=[BACK], state="your-step", step=STEP, mover=BACK, expected_by=day(2))
upd(130, priority="p2")
upd(130, subject="[home] item 130 renamed")
upd(130, project="projects/alpha")
check("6b mover/state: a bookkeeping write (priority, subject, project) on an item already in his state flips nothing", mt(130)["mover"] == BACK and "then" not in mt(130) and mt(130).get("priority") == "p2", mt(130))
upd(130, next="Oliver: run the step")
check("6b mover/state: …the next real write repairs it", mt(130)["mover"] == OWN and mt(130)["then"] == BACK, mt(130))
item(122, needs=[BACK], mover=BACK)
refused_nw("6b mover/state: an agent named as mover beside step=… (his step) is refused: the conflict line and the fix", 122, lambda: upd(122, step=STEP, mover=BACK),
           "Refused:", f"mover={BACK} on an item whose state is your-step, which is {OWN}'s move", f"leave mover out, or set mover={OWN}", f"then={BACK}")
refused_nw("6b mover/state: …and beside needs decision", 122, lambda: upd(122, needs=["decision"], ask=ASK, mover=BACK), f"mover={BACK} on an item whose state is your-call", "leave mover out")
upd(122, step=STEP, mover=OWN, then=BACK)
check("6b mover/state: …mover Oliver with the agent in then passes, as written", mt(122)["mover"] == OWN and mt(122)["then"] == BACK, mt(122))
item(48, needs=[BACK], state="your-step", step=STEP, mover=OWN, then=BACK)
upd(48, next="Oliver: run the step", step=STEP + "\ngh pr view 241")
upd(48, description="- A thing\n- It lives here, changed\n- Done when done")
check("6b mover/state: a step item whose then is an agent stays writable (next, step, description): mover Oliver and the then-mover untouched",
      mt(48)["mover"] == OWN and mt(48)["then"] == BACK and mt(48)["state"] == "your-step" and "model conflict" not in _wt_get.stackshot_get("a48"), mt(48))
item(124, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(124, step=STEP, then=FRONT)
check("6b mover/state: a then the write names is kept too", mt(124)["mover"] == OWN and mt(124)["then"] == FRONT, mt(124))
item(25, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(25, step=STEP, mover="none")
check("6b mover/state: mover=none (a dropped mover) is no agent mover: nothing stored, the item reads as his", "mover" not in mt(25) and "model conflict" not in _wt_get.stackshot_get("a25"), mt(25))
item(126, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(126, next=f"{BACK}: keep going")
check("6b mover/state: an agent's item that stays the agent's is not touched", mt(126)["mover"] == BACK and "then" not in mt(126), mt(126))
item(26, needs=[BACK], state="doing", mover=OWN, expected_by=day(2))
upd(26, next=f"{BACK}: keep going")
check("6b mover/state: the reverse (mover Oliver on a doing item, stored before the 6d guard) is not refused for a write that sets no state field, and the conflict note stays", mt(26)["mover"] == OWN and f"model conflict: mover={OWN} on an item whose state is doing, which is an agent's move" in _wt_get.stackshot_get("a26"), _wt_get.stackshot_get("a26"))
set_cfg(guards=False)
item(27, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(27, step=STEP, mover=BACK)
check("6b mover/state: [model] guards = false skips the refusal (the conflict is stored and get shows it) and the fix",
      mt(27)["mover"] == BACK and f"model conflict: mover={BACK} on an item whose state is your-step" in _wt_get.stackshot_get("a27"), mt(27))
item(129, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(129, step=STEP)
check("6b mover/state: …and with the guards off an unnamed mover is left as stored, as before", mt(129)["mover"] == BACK, mt(129))
set_cfg()
refused("6b mover/state: a create naming an agent as mover beside needs decision is refused", lambda: _wt_create._create(subject="[home] agent mover on his call", description=DESC, project="projects/alpha", owner="home-front",
        next="Oliver: decide", needs=["decision"], ask=ASK, mover=BACK), f"mover={BACK} on an item whose state is your-call", "leave mover out")
out_c = _wt_create._create(subject="[home] his call, agent in then", description=DESC, project="projects/alpha", owner="home-front", next="Oliver: decide", needs=["decision"], ask=ASK, mover=OWN, then=BACK)
check("6b mover/state: …mover Oliver with the agent in then creates", "created" in out_c and "model conflict" not in out_c, out_c)
for n in (*range(46, 131), 25, 26, 27): (T / f"store/a/{n}.json").unlink(missing_ok=True)          # the report below counts the fixtures of the sections before this one
for p in (T / "store").glob("*/*.json"):
    if p.name != "projects.json" and json.loads(p.read_text()).get("subject") == "[home] his call, agent in then": p.unlink()

# ================================================================ 6d. the mirror of 6b: the owner as mover needs his step or his ask (mover Oliver, state doing, no Your step, nothing to act on)
HM = ("Refused:", "would be left with", "as its mover but nothing for him to do", "no Your step and no ask", "step=<one line", "needs=[\"decision\"]", "ask=", "mover=<session>", "clear_mover=true", f"a next line that starts `{OWN}:`")
HMC = ("Refused:", "would be left with", "as its mover but nothing for him to do", "needs=[\"decision\"]", "ask=", "mover=<session>", f"a next line that starts `{OWN}:`")      # a create: no state, no clear_mover
item(170, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
refused_nw("6d owner mover: mover Oliver on a doing item is refused, with the three fixes", 170, lambda: upd(170, mover=OWN, next=f"{OWN}: look at it"), *HM, "its state is doing")
refused_nw("6d owner mover: …Oliver named in a mover with a next line that opens with him changes nothing: the state is still doing", 170, lambda: upd(170, mover="Oliver", next=f"{OWN}: review the PR"), *HM)
item(171, needs=[BACK])
refused_nw("6d owner mover: …an item with no stored state (it reads as doing) is the same", 171, lambda: upd(171, mover=OWN), *HM, "its state is doing")
refused("6d owner mover: a create with him as mover and no decision is refused", lambda: _wt_create._create(subject="[home] owner mover, nothing to do", description=DESC, project="projects/alpha", owner="home-front",
        next=f"{OWN}: do it", needs=[BACK], mover=OWN), *HMC)
refused("6d owner mover: …also with no needs at all", lambda: _wt_create._create(subject="[home] owner mover, no needs", description=DESC, project="projects/alpha", owner="home-front",
        next=f"{OWN}: do it", mover=OWN), *HMC)
def _cre(**kw):
    try:
        _wt_create._create(subject="[home] owner mover, wording", description=DESC, project="projects/alpha", owner="home-front", next=f"{OWN}: do it", needs=[BACK], mover=OWN, **kw); return ""
    except Exception as e: return str(e)
r_cre, r_upd = _cre(), ""
try: upd(171, mover=OWN)
except Exception as e: r_upd = str(e)
check("6d owner mover: a create's refusal offers only what a create can pass (needs=decision with ask, or mover=<session> with his next line): no state, no step, no clear_mover",
      "needs=[\"decision\"]" in r_cre and "ask=" in r_cre and "mover=<session>" in r_cre and f"a next line that starts `{OWN}:`" in r_cre
      and not any(w in r_cre for w in ("state=", "step=", "clear_mover", "your-call", "your-step")), r_cre)
check("6d owner mover: …an update's keeps the three fixes (step, needs=decision + ask, mover=<session> / clear_mover=true) and names no state to set",
      all(w in r_upd for w in ("step=<one line", "needs=[\"decision\"]", "ask=", "mover=<session>", "clear_mover=true")) and "state=" not in r_upd, r_upd)
writes.TERMINAL_ROW.on = True
try: out_t = _wt_create._create(subject="[home] terminal row, owner mover", description=DESC, project="projects/alpha", owner="home-front", next=f"{OWN}: answer in the pane", mover=OWN)
finally: writes.TERMINAL_ROW.on = False
check("6d owner mover: the terminal-prompt route's own create (mover the owner, state your-step set in its second write) is not refused", "created" in out_t, out_t)
for pth in (T / "store").glob("*/*.json"):
    if pth.name != "projects.json" and json.loads(pth.read_text()).get("subject") == "[home] terminal row, owner mover": pth.unlink()
check("6d owner mover: the refusal is one of the guards' keys, counted by the report's labels", "owner_mover" in mg.GUARDS and mg.LABELS["owner_mover"], None)
# allowed: his three states
item(173, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(173, mover=OWN, step=STEP, then=BACK)
check("6d owner mover: his step (step=…, stored as your-step) passes", mt(173)["mover"] == OWN and mt(173)["state"] == "your-step" and mt(173)["step"] == STEP, mt(173))
item(174, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(174, mover=OWN, needs=["decision"], ask=ASK, then=BACK)
check("6d owner mover: needs decision with an ask passes on an item that stores doing: his ask wins over the stored word", mt(174)["mover"] == OWN and "decision" in mt(174)["needs"] and mt(174)["ask"] == ASK, mt(174))
item(175, needs=[BACK])
upd(175, mover=OWN, needs=["decision"], ask=ASK, then=BACK)
check("6d owner mover: needs decision with an ask passes (the state is derived)", mt(175)["mover"] == OWN and "decision" in mt(175)["needs"] and "state" not in mt(175), mt(175))
out_c = _wt_create._create(subject="[home] owner mover with an ask", description=DESC, project="projects/alpha", owner="home-front", next=f"{OWN}: decide", needs=["decision"], ask=ASK, mover=OWN, then=BACK)
check("6d owner mover: a create with him as mover and needs decision with an ask passes", "created" in out_c, out_c)
# the step carried by the state
item(176, needs=[BACK], state="your-step", mover=OWN, then=BACK)          # stored before the step was required: no step
refused_nw("6d owner mover: state your-step stored with no step and him as mover is refused when the write sets the state or the mover", 176, lambda: upd(176, then=FRONT), *HM[:3], "state your-step carries no step")
upd(176, step=STEP)
check("6d owner mover: …the step is the fix", mt(176)["step"] == STEP and mt(176)["mover"] == OWN, mt(176))
# an item already in the bad shape can still be fixed: with his state and a step, with his ask, or by handing it to a session
for i in range(177, 183):
    item(i, needs=[BACK], state="doing", mover=OWN, expected_by=day(2), next=f"{OWN}: take a look")
upd(177, step=STEP)
check("6d owner mover: fix 1: an item already in the bad shape takes step=… (his step, stored as your-step)", mt(177)["state"] == "your-step" and mt(177)["mover"] == OWN, mt(177))
upd(178, mover=BACK)
check("6d owner mover: fix 2: …or mover=<session>", mt(178)["mover"] == BACK, mt(178))
upd(179, clear_mover=True)
check("6d owner mover: fix 3: …or clear_mover=true (the session in needs moves it)", "mover" not in mt(179) and model.derive(rd(179)).mover == BACK, mt(179))
upd(180, needs=["decision"], ask=ASK)
check("6d owner mover: fix 4: …or needs=decision with an ask (on an item that stores doing)", mt(180)["mover"] == OWN and "decision" in mt(180)["needs"] and mt(180)["ask"] == ASK, mt(180))
upd(181, mover=FRONT, next=f"{FRONT}: look at the draft\n{OWN}: take a look")
check("6d owner mover: fix 5: …or mover=<session> with his part in a `Oliver:` next line", mt(181)["mover"] == FRONT and mt(181)["next"].endswith(f"{OWN}: take a look"), mt(181))
refused_nw("6d owner mover: a fix that leaves him as mover and adds no step or ask is no fix", 182, lambda: upd(182, expected_by=hrs(3), then=BACK), *HM)
check("6d owner mover: …(the refused fix wrote nothing)", mt(182)["expected_by"] == day(2), mt(182))
# a write that touches no state field is judged by what it touches (no [model] switchover): the old item stays writable
item(183, needs=[BACK], state="doing", mover=OWN, expected_by=day(2), next=f"{BACK}: keep going")
upd(183, priority="p2"); upd(183, subject="[home] item 183 renamed"); upd(183, project="projects/alpha"); upd(183, next=f"{BACK}: keep going, still")
check("6d owner mover: bookkeeping and text writes (priority, subject, project, next) on such an item pass: only a write that sets a state field is judged", mt(183).get("priority") == "p2" and mt(183)["next"].endswith("still"), mt(183))
# exemptions: a waiting item, a close
item(184, needs=[BACK], hold=True, wake=day(3), mover=OWN, wait_basis={"text": f"visit on {day(4)}", "wake": day(3), "by": "x", "at": 1.0})
upd(184, then=BACK)
check("6d owner mover: a waiting item (parked) has no mover to judge: it passes even with a mover stored", mt(184)["then"] == BACK, mt(184))
check("6d owner mover: …the pure reading agrees: only an alive item with him as mover has a gap",
      mg.owner_mover_gap(mt(184), model.derive(rd(184))) == "" and mg.owner_mover_gap(mt(183), model.derive(rd(183))).startswith("its state is doing")
      and mg.owner_mover_gap(mt(173), model.derive(rd(173))) == "" and mg.owner_mover_gap(mt(175), model.derive(rd(175))) == "", None)
item(41, needs=[BACK], state="doing", mover=OWN, expected_by=day(2))
server._update("a41", sender="home-front", status="completed", outcome="done", reason="finished", description="- The thing is done and closed")
check("6d owner mover: a close is never judged", rd(41)["status"] == "completed" and "mover" not in mt(41), rd(41))
# [model] guards = false skips it
set_cfg(guards=False)
item(186, needs=[BACK], state="doing", mover=BACK, expected_by=day(2))
upd(186, mover=OWN)
check("6d owner mover: [model] guards = false skips it", mt(186)["mover"] == OWN, mt(186))
set_cfg()
# the switchover judges every write whole, and a bookkeeping write still passes
set_cfg(switchover=True, handoff=False)
item(187, needs=[BACK], state="doing", mover=OWN, expected_by=day(2), next=f"{BACK}: keep going")
refused_nw("6d owner mover: switchover on: any write that is not bookkeeping is judged whole (an unrelated next edit is refused until the item is fixed)", 187, lambda: upd(187, next=f"{BACK}: keep going, again"), *HM)
upd(187, priority="p2"); upd(187, subject="[home] item 187 renamed"); upd(187, project="projects/alpha")
check("6d owner mover: …a rename, a priority and a project write still pass", mt(187).get("priority") == "p2" and rd(187)["subject"].endswith("renamed"), mt(187))
item(42, needs=[BACK], state="doing", mover=OWN, expected_by=day(2), next=f"{BACK}: keep going", desc="- The thing is a long one with a long first line and another thing after it\n- It lives here and a lot more of it\n- Done when it is done")
d_rb = rd(42)["description"]
r_rb = server._rebullet_write({"item": "a42", "sender": "rebullet-pass", "old": d_rb, "description": "- The thing is a long one\n- It has a long first line and another thing after it\n- It lives here and a lot more of it\n- Done when it is done"}, "box-a")
check("6d owner mover: …and the re-bullet route (it sets no state)", r_rb["action"] == "set" and rd(42)["description"] != d_rb and mt(42)["mover"] == OWN, (r_rb, rd(42)["description"]))
upd(187, step=STEP)
check("6d owner mover: …and with the switchover on the fix still goes through", mt(187)["state"] == "your-step", mt(187))
set_cfg()
for n in range(170, 190):
    pth = T / f"store/a/{n}.json"
    if pth.exists(): pth.unlink()
for pth in (T / "store").glob("*/*.json"):
    if pth.name != "projects.json" and json.loads(pth.read_text()).get("subject") in ("[home] owner mover with an ask",): pth.unlink()

# ================================================================ 6c. the way back, the server's own saves, the migration
item(28, needs=[BACK], mover=BACK)
upd(28, needs=["decision"], ask=ASK)
check("6c mover: (setup) an item the agent moved is his now, the agent in then", mt(28)["mover"] == OWN and mt(28)["then"] == BACK, mt(28))
out_g = upd(28, needs=[BACK], next=f"{BACK}: carry on")
check("6c mover: his decision out of needs (a session relaying his answer): the mover he held goes back to then, and then goes; the reply says so",
      mt(28)["mover"] == BACK and "then" not in mt(28) and f"(mover: {OWN} → {BACK}" in out_g and "model conflict" not in _wt_get.stackshot_get("a28"), (mt(28), out_g))
item(142, needs=[BACK], mover=BACK)
upd(142, needs=["decision"], ask=ASK, then=FRONT)
upd(142, needs=[BACK], next=f"{BACK}: carry on")
check("6c mover: …the mover it goes back to is the then stored (a then the writer named), not the agent that held it", mt(142)["mover"] == FRONT and "then" not in mt(142), mt(142))
item(143, needs=[BACK], mover=OWN, then=BACK)
upd(143, next=f"{BACK}: carry on")
check("6c mover: an item that never stood in his state keeps a mover Oliver a writer stored (the conflict note stays; no hand-back from nothing)", mt(143)["mover"] == OWN, mt(143))
# the server's own saves: an idle raise adds decision to needs and saves, with no update behind it
item(29, needs=[BACK], mover=BACK)
it_b = _service_store._load("a29"); it_b["metadata"]["needs"] = ["decision", BACK]; it_b["metadata"]["ask"] = ASK
writes.save("a29", it_b)
check("6c mover: a save the server makes itself on an item that waits on him settles it too: he is the mover, the agent in then", mt(29)["mover"] == OWN and mt(29)["then"] == BACK, mt(29))
it_b = _service_store._load("a29"); it_b["metadata"]["needs"] = [BACK]; it_b["metadata"].pop("ask")
writes.save("a29", it_b)
check("6c mover: …and when his wait ends in the server's own save, the agent has it back", mt(29)["mover"] == BACK and "then" not in mt(29), mt(29))
# his answer on the board
item(30, needs=[BACK], mover=BACK)
upd(30, needs=["decision"], ask=ASK)
check("6c mover: his decision on the board (a save with an author) is taken", server._answer("a30", "Yes", "", "answer") == "decision", mt(30))
check("6c mover: …and leaves the agent as the mover again, no stored then, no model conflict", mt(30)["mover"] == BACK and "then" not in mt(30) and "model conflict" not in _wt_get.stackshot_get("a30"), mt(30))
# a create
out_c2 = _wt_create._create(subject="[home] his call, no mover named", description=DESC, project="projects/alpha", owner="home-front", next="Oliver: decide", needs=["decision"], ask=ASK)
gc2 = out_c2
check("6c mover: a create that leaves an item waiting on him and names no mover has him as mover", "created" in out_c2 and f"mover: {OWN}" in gc2 and "model conflict" not in gc2, (out_c2, gc2))
# a wait that replaces his state: the agent he named in then picks it up
item(31, needs=[BACK], mover=BACK)
upd(31, needs=["decision"], ask=ASK)
upd(31, needs=[BACK], hold=True, wake=day(3), wait_basis="the vendor ships on " + day(3), next=f"{BACK}: waiting")
check("6c mover: a wait that replaces his state hands the agent in then the pick-up: mover := then, then gone, no model conflict", mt(31).get("mover") == BACK and "then" not in mt(31) and "model conflict" not in _wt_get.stackshot_get("a31"), (mt(31), _wt_get.stackshot_get("a31")))
# the guards off: nothing is flipped by the backstop
set_cfg(guards=False)
item(32, needs=[BACK], mover=BACK)
it_c = _service_store._load("a32"); it_c["metadata"]["needs"] = ["decision", BACK]; it_c["metadata"]["ask"] = ASK
writes.save("a32", it_c)
check("6c mover: [model] guards = false: the save leaves the stored mover as it is", mt(32)["mover"] == BACK and "then" not in mt(32), mt(32))
set_cfg()
item(33, needs=["decision", BACK], mover=BACK, ask=ASK)
_wt_complete.stackshot_confirm("a33", sender="home-front")
check("6c mover: a confirm changes nothing but its clock: a stored agent mover on a legacy item is not flipped by it", mt(33)["mover"] == BACK and "then" not in mt(33), mt(33))
upd(33, next="Oliver: decide")
check("6c mover: …the next real write settles it", mt(33)["mover"] == OWN and mt(33)["then"] == BACK, mt(33))
item(149, needs=["decision", BACK], mover=BACK, ask=ASK)
upd(149, status="completed", outcome="done", reason="finished", description="- A thing\n- It shipped\n- Done")
check("6c mover: a close settles no mover: the closed item keeps no mover and no then", "mover" not in mt(149) and "then" not in mt(149) and rd(149)["status"] == "completed", mt(149))
# the migration: items stored before the rules
HO = {"to": OWN, "from": BACK, "at": now0 - 7200, "delivered_at": None, "taken_at": None, "no_clock": True}
item(49, needs=["decision", BACK], mover=BACK, ask=ASK)                                   # waits on him, an agent stored as mover
item(50, needs=[BACK], mover=OWN, then=BACK, handoff=dict(HO), answers=[{"ts": now0 - 3600, "kind": "decision", "choice": "Yes", "via": "board"}])      # stored as his, in an agent's state, with the agent in then and his answer on it (a decision answered after the first rule)
item(152, needs=[BACK], mover=OWN)                                                         # mover Oliver a writer stored, no then: not a hand-back, left (the conflict note shows it)
item(34, needs=["decision", BACK], ask=ASK, handoff=dict(HO), answers=[{"ts": now0 - 3600, "kind": "decision", "choice": "Yes", "via": "board"}])    # he answered after the hand-off, the record still reads not taken
item(35, needs=[BACK], mover=BACK, handoff=dict(HO))                                      # the item is no longer his to move
item(155, needs=["decision", BACK], ask=ASK, handoff=dict(HO), answers=[{"ts": now0 - 9000, "kind": "comment", "text": "an older word", "via": "github"}])      # his comment is older than the hand-off, and the item is still his: stays
item(156, needs=[BACK], mover=BACK, status="completed", handoff=dict(HO))                  # closed: untouched
OLD = [{"ts": now0 - 3 * DAY, "kind": "decision", "choice": "Yes", "via": "board"}]
item(158, needs=[BACK], mover=OWN, then=BACK, handoff=dict(HO), answers=list(OLD))         # an old answer, then a later deliberate mover=Oliver with then set and no needs (a record newer than the answer): left
item(159, su=now0 - 3600, needs=[BACK], mover=OWN, then=BACK, answers=list(OLD))           # the same with no record: the item's last write is newer than the answer: left
item(36, needs=[BACK], mover=OWN, then=OWN, wait_kind="relay", wait_event="Robin relays the quote", ask_by=day(5), handoff=dict(HO),
     answers=[{"ts": now0 - 3600, "kind": "decision", "choice": "Yes", "via": "board"}])    # waiting on news only he relays: its then (the post-wake mover) is he and must stay
before_mig = {n: raw(n) for n in (143, 152, 155, 156, 158, 159)}
(T / "store/a/32.json").unlink()                                                           # the guards-off fixture above is an item the pass would rightly fix
GH_CALLS = []
real_enabled, real_on_change = _gh.enabled, _gh.on_change
_gh.enabled = lambda: True; _gh.on_change = lambda *a, **k: GH_CALLS.append(a[0])
try:
    item(37, needs=[BACK]); writes.save("a37", _service_store._load("a37"))
    check("6c migration: (probe) the mirror stub sees an ordinary save", GH_CALLS == ["a37"], GH_CALLS)
    GH_CALLS.clear()
    done = migsvc.migrate_owner_mover()
    mig_calls = list(GH_CALLS)
finally:
    _gh.enabled, _gh.on_change = real_enabled, real_on_change
check("6c migration: it posts nothing to GitHub (mirror off), though it rewrote items", len(done) >= 5 and mig_calls == [], (done, mig_calls))
check("6c migration: it rewrites the items that need it, and no other", sorted(g for g in done if g in {f"a{n}" for n in [*range(28, 37), 49, 50]}) == ["a34", "a35", "a36", "a49", "a50"], done)
check("6c migration: an old answer followed by a deliberate mover=Oliver (with a later record, or no record) is left byte for byte", all(raw(n) == before_mig[n] for n in (158, 159)), None)
check("6c migration: a waiting item keeps its stored mover=Oliver (where he picks it up when the wait ends is written) and its then, and the stale hand-off line ends",
      mt(36)["mover"] == OWN and mt(36)["then"] == OWN and isinstance(mt(36)["handoff"]["taken_at"], float), mt(36))
check("6c settle: …the same through model.settle (a waiting item: only the mover, no then key; a hand-back to an agent: the agent mover and then cleared as Done does)",
      model.settle(rd(36), True) is None and model.settle({**rd(36), "metadata": {**mt(36), "mover": OWN}}, True) is None
      and model.settle({**rd(36), "metadata": {**mt(36), "mover": OWN}}, True, waiting=True) == {"mover": ""}
      and model.settle({**rd(143), "metadata": {**mt(143), "mover": OWN, "then": BACK}}, True) == {"mover": BACK, "then": ""}, model.settle({**rd(36), "metadata": {**mt(36), "mover": OWN}}, True))
check("6c migration: an agent mover on an item that waits on him becomes he, the agent in then", mt(49)["mover"] == OWN and mt(49)["then"] == BACK, mt(49))
check("6c migration: the mover he held in an agent's state with a then goes back to the agent", mt(50)["mover"] == BACK and "then" not in mt(50), mt(50))
check("6c migration: a mover Oliver stored where he never held the item (no record, no answer), a hand-off still his with no answer after it, and a closed item are left byte for byte", all(raw(n) == before_mig[n] for n in (143, 152, 155, 156)), None)
check("6c migration: his answer made after the hand-off ends the record, taken at the answer", mt(34)["handoff"]["taken_at"] == now0 - 3600, mt(34)["handoff"])
check("6c migration: a record to him on an item that is no longer his ends too", isinstance(mt(35)["handoff"]["taken_at"], float), mt(35)["handoff"])
check("6c migration: the clocks stay (updated and confirmed unchanged)", all(rd(n)["updated"] == now0 - 10 * DAY and rd(n)["confirmed"] == now0 - 10 * DAY for n in (49, 50, 34, 35)), [rd(n)["updated"] for n in (49, 50)])
check("6c migration: it is idempotent: a second pass rewrites nothing", migsvc.migrate_owner_mover() == [], None)
AN = lambda ts: [{"ts": ts, "kind": "decision", "choice": "Yes", "via": "board"}]
item(51, su=now0 - 3600, needs=[BACK], mover=OWN, then=BACK, answers=AN(now0 - 3600.5))   # no record: his answer within a second of the item's last write counts as letting go
item(38, needs=[BACK], mover=OWN, then=OWN, handoff=dict(HO), answers=AN(now0 - 3600))    # alive, then holds he: the mover drops to the default, then stays as stored
item(39, needs=[BACK], mover=OWN, handoff=dict(HO), answers=AN(now0 - 3600))              # alive, no then: the mover just drops
done2 = migsvc.migrate_owner_mover()
check("6c migration: with no record, an answer within a second of the last write moves the mover back (and then goes, as Done does)", "a51" in done2 and mt(51)["mover"] == BACK and "then" not in mt(51), mt(51))
check("6c migration: an alive hand-back where then holds he: the mover drops to the default and then stays as stored", "a38" in done2 and "mover" not in mt(38) and mt(38)["then"] == OWN, mt(38))
check("6c migration: …and with no then at all the mover just drops", "a39" in done2 and "mover" not in mt(39) and "then" not in mt(39), mt(39))
# a live save where a wait replaces his state: then survives, not only the mover
item(40, needs=[BACK], mover=BACK)
it_d = _service_store._load("a40"); it_d["metadata"]["needs"] = ["decision", BACK]; it_d["metadata"]["ask"] = ASK
writes.save("a40", it_d)
it_d = _service_store._load("a40"); it_d["metadata"].update(needs=[BACK], wait_kind="relay", wait_event="Robin relays the quote", ask_by=day(5)); it_d["metadata"].pop("ask")
writes.save("a40", it_d)
check("6c mover: a save where a wait replaces his state leaves his stored mover alone (the on-save backstop does not settle a waiting item: he picks it up when the wait ends), then beside him", mt(40).get("mover") == OWN and mt(40).get("then") == BACK, mt(40))
set_cfg(guards=False, handoff=False)
item(157, needs=["decision", BACK], mover=BACK, ask=ASK)
check("6c migration: [model] guards = false and handoff = false: nothing to do", migsvc.migrate_owner_mover() == [], None)
set_cfg()
for n in list(range(28, 49)) + list(range(49, 170)): (T / f"store/a/{n}.json").unlink(missing_ok=True)
for p in (T / "store").glob("*/*.json"):
    if p.name != "projects.json" and json.loads(p.read_text()).get("subject") == "[home] his call, no mover named": p.unlink()

# ================================================================ 7. one mover in needs
item(82, needs=[FRONT])
refused_nw("7 second mover: two sessions in needs", 82, lambda: upd(82, needs=[FRONT, "home-beta-bg"]), "needs names more than one mover", "then=<session>", "who takes it after")
refused_nw("7 second mover: decision plus a session", 82, lambda: upd(82, needs=["decision", FRONT], ask=ASK), "decision plus", "then=<session>")
upd(82, needs=["decision"], ask=ASK, then=BACK)
check("7 second mover: …one mover (decision) and the session in then passes", mt(82)["needs"] == ["decision"] and mt(82)["then"] == BACK, mt(82))
set_cfg(one_mover=False)
upd(82, needs=["decision", BACK], ask=ASK)
check("7 second mover: [model] one_mover = false allows it again (only that guard)", mt(82)["needs"] == ["decision", BACK], mt(82))
set_cfg()
item(83, needs=["decision", FRONT], ask=ASK)
upd(83, description="- A thing\n- It lives here, edited\n- Done when done")
check("7 second mover: an old item with decision plus a session takes an update that does not touch the state", rd(83)["description"].endswith("edited\n- Done when done"), rd(83))
refused_nw("7 second mover: …a write that sets a field of the state meets the guard (a backstop wake)", 83, lambda: upd(83, wake=day(2)), "decision plus", "then=<session>")
upd(83, needs=["decision"], then=BACK, wake=day(2))
check("7 second mover: …and the fix is then=", mt(83)["needs"] == ["decision"] and mt(83)["then"] == BACK and wk_(mt(83)) == day(2), mt(83))
item(84, needs=["decision"], ask=ASK)
server._update("a84", sender=BACK, wake=day(2))
check("7 second mover: a background agent's write that the server names into needs (decision + the writer) is the server's naming, not a second mover the writer made", wk_(mt(84)) == day(2), mt(84))
# the naming stays in needs: a later write by anyone else is not refused for it (a background agent of the project is never a second mover)
item(43, needs=["decision"], ask=ASK)
server._update("a43", sender=BACK, next="team-back: carry on")
check("7 second mover: …a background agent's plain write names it into needs beside the decision", mt(43)["needs"] == ["decision", BACK], mt(43))
upd(43, wake=day(2))
check("7 second mover: …and a front agent's later wake on it passes (the background agent in needs is no second mover)", wk_(mt(43)) == day(2), mt(43))
item(45, needs=[FRONT])
server._update("a45", sender=BACK, next="team-back: carry on")
check("7 second mover: …the same for a front agent in needs and a background write", BACK in mt(45)["needs"] and FRONT in mt(45)["needs"], mt(45))
upd(45, wake=day(2))
check("7 second mover: …a later wake passes", wk_(mt(45)) == day(2), mt(45))
item(200, needs=[BACK, OTHER])
upd(200, wake=day(2))
check("7 second mover: two background agents of the project are no second mover either", wk_(mt(200)) == day(2), mt(200))
refused_nw("7 second mover: …but decision plus another project's background agent beside them is", 200, lambda: upd(200, needs=["decision", BACK, "home-beta-bg"], ask=ASK), "needs names more than one mover")

# ================================================================ 8. every next line names who takes it
item(85, needs=[BACK])
refused_nw("8 next: a line with no name is refused and quoted", 85, lambda: upd(85, next="look into the cache"), "next line 'look into the cache' does not say who takes it", "<name>:", "background agent")
refused_nw("8 next: …one bad line among good ones", 85, lambda: upd(85, next="home-front: look\nthen check it"), "'then check it'")
upd(85, next="Kim: send the contract")      # any `<name>:` opens a line (an outside party's too); next_rules.unnamed (N1) owns who may be named
check("8 next: …a name no one knows is a name (an outside party): it passes", "Kim: send the contract" in mt(85)["next"], mt(85))
refused_nw("8 next: …a name in the body is no name", 85, lambda: upd(85, next="Ask team-back to look into the cache"), "does not say who takes it")
upd(85, next="home-front: look into the cache\n  detail under it\n- Oliver: in PowerShell run `ssh -t box-a 'systemctl status x'`\n**team-back:** then check the log\n(rank dropped: noted by the server)")
check("8 next: …names, list markers, bold, an indented line and a server note pass", "Oliver: in PowerShell run" in mt(85)["next"], mt(85))
item(86, needs=[BACK], next="no name on this old line")
upd(86, priority="p2")
check("8 next: an old item whose next has no name takes an update that does not set next", mt(86)["priority"] == "p2" and mt(86)["next"] == "no name on this old line", mt(86))

# ================================================================ 9. a wait in next, on an alive item
item(87, needs=[BACK])
refused_nw("9 next wait: a line on the precise list is refused with the line, the fix named", 87, lambda: upd(87, next="home-front: wait for the PR to merge"), "next line 'home-front: wait for the PR to merge' reads as a wait (wait for / on / until)",
           "alive item", "set the wait itself", "write the action")
refused_nw("9 next wait: …until a date", 87, lambda: upd(87, next="home-front: park the work until 2026-11-02"), "until a date or item")
refused_nw("9 next wait: …an item id", 87, lambda: upd(87, next="home-front: blocked on board#12"), "blocked on / by")
refused_nw("9 next wait: …Japanese", 87, lambda: upd(87, next="home-front: 返信待機"), "wait word")
upd(87, next="home-front: no waiting for a slot, run it now")
check("9 next wait: a negation passes", "no waiting" in mt(87)["next"] and "model_flags" not in mt(87), mt(87))
upd(87, next="home-front: ship it when the build is green, after the review")
check("9 next wait: the broad list is accepted and nothing is stored for it", "when" in mt(87)["next"] and "model_flags" not in mt(87), mt(87))
check("9 next wait: …get shows the flag", "flag: next uses when, after" in _wt_get.stackshot_get("a87"), _wt_get.stackshot_get("a87"))
upd(87, next="home-front: ship it now")
check("9 next wait: …a next with none shows no flag", "model_flags" not in mt(87) and "flag: next uses" not in _wt_get.stackshot_get("a87"), mt(87))
item(97, needs=[BACK], next="home-front: ship it when the build is green")
writes.save("a97", {**rd(97), "metadata": {**mt(97), "model_flags": {"next_wait_words": ["when"]}}})      # an item stored before the flag was removed
upd(97, next="home-front: ship it after the review")
check("9 next wait: …a write that sets next drops a flag an older write stored", "model_flags" not in mt(97), mt(97))
upd(87, description="- A thing\n- It lives here, edited\n- Done when done")
item(88, needs=[BACK])
upd(88, wait_kind="relay", wait_event="Robin", ask_by=FUT, next="home-front: waiting for Robin's reply")
check("9 next wait: on a waiting item the line is the record of the wait and passes", "waiting for Robin" in mt(88)["next"], mt(88))
item(89, needs=[BACK], next="home-front: waiting for the build")
upd(89, description="- A thing\n- It lives here, edited\n- Done when done")
check("9 next wait: an old alive item with such a line is not blocked by an update that leaves next alone", rd(89)["description"].endswith("edited\n- Done when done"), rd(89))
item(90, needs=[BACK], next="home-front: waiting for the build", model_flags={"next_wait_words": ["when"]})
server._update("a90", sender="home-front", status="completed", outcome="done", reason="finished", description="- The thing is done and closed")
check("9 next wait: a close is never refused, and drops the flag", rd(90)["status"] == "completed" and "model_flags" not in mt(90), mt(90))

# ================================================================ 10. the re-park test: structured fields only
item(91, needs=[BACK])
basis = lambda: f"vendor visit booked for {day(12)}"
upd(91, hold=True, wake=day(2), wait_basis=basis())
upd(91, wake=day(3), wait_basis=basis())
check("10 re-park: the first move of a parked item's wake is counted", mt(91).get("repark") == 1, mt(91))
upd(91, next="home-front: look at it once more")
check("10 re-park: …an edit of next changes nothing: the count stays", mt(91).get("repark") == 1 and wk_(mt(91)) == day(3), mt(91))
upd(91, description="- A thing\n- It lives somewhere else\n- Done when done")
check("10 re-park: …nor does the description", mt(91).get("repark") == 1, mt(91))
upd(91, wake=day(4), wait_basis=basis(), next="home-front: and once more")
check("10 re-park: …a re-park that also edits next is still a re-park: the second", mt(91).get("repark") == 2, mt(91))
refused_nw("10 re-park: …so the third, whose only other change is next and the description, is refused", 91, lambda: upd(91, wake=day(5), wait_basis=basis(), next="home-front: another line", description="- A thing\n- Reworded again\n- Done when done"),
           "re-parked 2 times in a row with nothing else changed", "third move of its wake")
upd(91, post_wake_mover=OTHER, wake=day(5), wait_basis=basis())
check("10 re-park: a change of a structured field (the post-wake mover) is a real change: allowed, and the count starts again", "repark" not in mt(91) and wk_(mt(91)) == day(5), mt(91))
check("10 re-park: the compared fields are the structured ones", "wait_kind" in gates._REPARK_FIELDS and "needs" in gates._REPARK_FIELDS and "next" not in gates._REPARK_FIELDS and "description" not in gates._substance({"metadata": {}}), gates._REPARK_FIELDS)

# ================================================================ 11. an alarming word
item(92, needs=[BACK])
refused_nw("11 alarm: a next line with leak is refused with the everyday word", 92, lambda: upd(92, next="home-front: remove the leak in the cache"), "next uses \"leak\"", "leftover files", "everyday words")
refused_nw("11 alarm: …a subject with quota", 92, lambda: upd(92, subject="[home] raise the quota"), "subject uses \"quota\"", "limit or disk space")
refused_nw("11 alarm: …an ask with credentials", 92, lambda: upd(92, needs=["decision"], ask="Decide: rotate the Credentials · Recommend: yes · Stakes: low · By: no date"), "ask uses \"Credentials\"", "sign-in")
refused_nw("11 alarm: …kill", 92, lambda: upd(92, next="home-front: kill the old pane"), "kill", "stop")
refused("11 alarm: …a create with exposed in its subject", lambda: _wt_create._create(subject="[home] the port is exposed", description=DESC, project="projects/alpha", owner="home-front", next="home-front: close it"), "subject uses \"exposed\"", "visible")
upd(92, next="home-front: run `kill 4242` on the box, a killer feature stays")
check("11 alarm: a code span and a longer word are not the alarming word", "kill 4242" in mt(92)["next"], mt(92))

# ================================================================ the words
W_ = mg.wait_lines
check("words: monitor, thumbs, satisfied, money, thus are no weekday: no date word in a quote, no `until <date>` in next",
      not any(mg.has_wait_words(q) for q in ("monitor the thumbs", "satisfied with the money", "thus it works", "the sunny side", "a moneyed man")) and all(not W_(f"home-front: ship it until {w} lands")[0] for w in ("monitor", "thumbs", "satisfied", "money", "thus")),
      [W_(f"home-front: ship it until {w} lands") for w in ("monitor", "thumbs", "satisfied", "money", "thus")])
check("words: a weekday name or its abbreviation is a date word (Mon, Tues, Thur, Thursday, Sun)", all(mg.has_wait_words(f"until {d}") for d in ("Mon", "Tues", "Thur", "Thursday", "sun", "Wed")) and W_("home-front: ship it until Thursday")[0] and W_("home-front: ship it until Tues")[0], None)
check("words: a bare ordinal or a fraction is no date word (the 2nd, 2/3)", not mg.has_wait_words("the 2nd of three") and not mg.has_wait_words("2/3 done") and not W_("home-front: finish until 2/3 of the tests pass")[0] and mg.has_wait_words("Oct 3rd"), None)
check("words: a time wait whose quote only has such a word is still without a reason (the snooze guard)", not mg.has_wait_words("I like the monitor, thanks") and mg.has_wait_words("park it until Monday"), None)
for line in ("home-front: build the Waiting lane", "home-front: implement the waiting state", "home-front: fix the waiting.py bug", "home-front: check whether the test waits for the lock"):
    check(f"words: {line!r} is no wait", not W_(line)[0], W_(line))
check("words: wait for, waiting on, waiting for, waiting to hear stay precise", all(W_(l)[0] for l in ("home-front: wait for CI", "home-front: waiting on Robin", "home-front: waiting for the build", "home-front: waiting to hear back", "home-front: waits on Robin")), None)
check("words: an aside in parentheses is not read by the until-date and once patterns (the cancel line passes)",
      not W_("Oliver: cancel the plan before Wed Jan 14th (a cancellation keeps the service until Jan 20th)")[0] and not W_("home-front: merge it (once it lands the site updates)")[0], None)
check("words: …but wait for / waiting on / blocked on / on hold stay precise inside parentheses", all(W_(l)[0] for l in ("home-front: ship it (waiting on Robin)", "home-front: ship it (wait for CI)", "home-front: ship it (blocked on board#5)", "home-front: ship it (on hold)")), None)
check("words: a negation ends at a clause boundary (a comma, semicolon, colon, full stop, but)",
      W_("home-front: no change needed, wait for CI")[0] and W_("home-front: nothing to do now; waiting on Robin")[0] and W_("home-front: not much left but wait for CI")[0] and not W_("home-front: no waiting for a slot")[0] and not W_("home-front: no need to wait for CI")[0], None)
check("words: a fenced block is code, not prose (guards 8, 9 and 11)", not W_("home-front: run\n```\nwait for it\n```")[0] and mg.alarm_in("home-front: run\n```\nkill -9 1\n```") == ("", "")
      and [n for _, n in mg.next_openers("home-front: run\n```\nfoo bar\nmake test\n```")] == ["home-front"], None)
check("words: the refusal texts of guards 8, 9 and 11 ask for backticks around file names, commands and code", all("backticks" in t for t in (
      [p.text for p in mg.check({"status": "open", "subject": "[home] x", "metadata": {"project": "projects/alpha", "owner": U["home-front"], "next": "look at it"}}, mg.Ctx(), touched={"next"})[0]]
      + [p.text for p in mg.check({"status": "open", "subject": "[home] x", "metadata": {"project": "projects/alpha", "owner": U["home-front"], "next": "home-front: waiting on Robin"}}, mg.Ctx(), touched={"next"})[0]]
      + [p.text for p in mg.check({"status": "open", "subject": "[home] x", "metadata": {"project": "projects/alpha", "owner": U["home-front"], "next": "home-front: the leak"}}, mg.Ctx(), touched={"next"})[0]])), None)
check("words: a ```y``` line is no fence: the wait line after it is judged", W_("home-front: x\n```y```\nwait for z")[0] and W_("home-front: x\n```y```\nwait for z")[0][0][0] == "wait for z", W_("home-front: x\n```y```\nwait for z"))
check("words: an unclosed fence is no fence: its lines are judged (a wait line, a line with no name)", bool(W_("home-front: x\n```\nwait for z")[0]) and [n for _, n in mg.next_openers("home-front: x\n```\nfoo bar")][-1] == "", None)
check("words: a proper fenced block (with an info string) still exempts its lines", not W_("home-front: x\n```bash\nwait for z\n```")[0] and not W_("home-front: x\n~~~\nwait for z\n~~~")[0] and mg.alarm_in("```\nkill 1\n```") == ("", ""), None)
check("words: …and the line after the closing fence is judged again", W_("home-front: x\n```\nfoo\n```\nwait for z")[0], None)
item(201, needs=[FRONT], next="home-front: start")
upd(201, next="cse_0123456789abcdef: carry on")
check("8 next: a cloud session's name (cse_…) opens a line", mt(201)["next"].startswith("cse_0123"), mt(201))

# ================================================================ when a guard runs
item(93, owner=U["home-lost"], needs=[], next="look into it, quota is low")
before = rd(93)
upd(93, description="- A thing\n- It lives here, edited\n- Done when done")
check("when: an old item that fails several guards takes a description edit", rd(93)["description"].endswith("edited\n- Done when done"), rd(93))
upd(93, priority="p2"); upd(93, goal="The thing is looked into")
check("when: …a priority, a goal (a guard on its own field)", mt(93)["priority"] == "p2" and mt(93)["goal"].startswith("The thing"), mt(93))
_wt_complete.stackshot_confirm("a93", sender="home-front")
check("when: …a confirm", rd(93)["confirmed"] > before["confirmed"], None)
refused_nw("when: …setting next brings the field's own guards back, and only those (no mover refusal)", 93, lambda: upd(93, next="still no name, a leak"), "next line", "does not say who takes it", "\"leak\"", none=("is alive", "mover"))
refused_nw("when: …a state field brings the invariants back, and only those (no next refusal)", 93, lambda: upd(93, needs=["decision", "home-beta-bg"], ask=ASK), "needs names more than one mover", none=("does not say who takes it",))
server._update("a93", sender="home-front", status="completed", outcome="done", reason="finished", description="- The thing is done and closed")
check("when: a close is never blocked, whatever the old item fails", rd(93)["status"] == "completed", rd(93))
refused_nw("when: a reopen is a create again: every guard judges it", 93, lambda: server._update("a93", sender="home-front", status="open", next="no name here, a leak"), "next line", "does not say who takes it")
server._update("a93", sender="home-front", status="open", next="home-front: back again", mover=BACK)
check("when: …with a mover it reopens", rd(93)["status"] == "open" and mt(93)["mover"] == BACK, mt(93))
item(94, needs=[BACK], mover="home-nobody")
server._update("a94", sender="home-front", status="completed", outcome="done", reason="finished", description="- The thing is done and closed")
check("when: a close passes with a mover that is no one", rd(94)["status"] == "completed", rd(94))

# ================================================================ the switch
item(95, needs=[BACK])
refused_nw("switch: on (the default, with no [model] section), a nameless next is refused", 95, lambda: upd(95, next="no name here"), "does not say who takes it")
set_cfg(guards=False, handoff=False)      # the guards are off and the mover is no one: the hand-off's send-time guard (handoff suite) would refuse it
upd(95, next="no name here, a leak, waiting for it", mover="home-nobody", needs=[BACK, OTHER])
check("switch: [model] guards = false: none of the guards refuses (and no flag is written)", mt(95)["next"].startswith("no name") and mt(95)["mover"] == "home-nobody" and "model_flags" not in mt(95), mt(95))
refused_nw("switch: …the form checks of PR 1 still do (a bad wait_kind)", 95, lambda: upd(95, wait_kind="soon"), "wait_kind is one of")
set_cfg()
_cfg.CFG.pop("model", None)
refused_nw("switch: removing the section leaves the default: on", 95, lambda: upd(95, next="no name again"), "does not say who takes it")
# [model] guards = false restores today's behaviour entirely: the re-park test and the wait_basis rule too
item(202, needs=[BACK], hold=True, wake=day(2), wait_basis={"text": f"visit on {day(9)}", "wake": day(2), "by": "x", "at": 1.0})
item(203, needs=[BACK], hold=True, wake=day(2))
upd(202, wake=day(3), wait_basis=f"visit on {day(9)}"); upd(202, next="home-front: look again")
check("switch: guards on: a next edit does not reset the re-park count", mt(202).get("repark") == 1, mt(202))
upd(203, wait_basis=f"visit on {day(9)}")
check("switch: guards on: a held wake within the cap takes a basis (a time wait carries a reason)", W.basis_of(mt(203)) if False else mt(203).get("wait_basis"), mt(203))
set_cfg(guards=False)
item(204, needs=[BACK], hold=True, wake=day(2))
upd(204, wake=day(3))
check("switch: guards off: a plain re-park counts as before", mt(204).get("repark") == 1, mt(204))
upd(204, next="home-front: look a third time")
check("switch: guards off: …and a next edit resets the count (today's test: every field but the wait's own)", "repark" not in mt(204), mt(204))
refused_nw("switch: guards off: a basis on a held wake within the cap is 'not needed' again", 203, lambda: upd(203, wait_basis=f"visit on {day(9)}"), "not needed")
set_cfg()

# ================================================================ a create that passes, and the multi-problem refusal
out = _wt_create._create(subject="[home] a good create", description=DESC, project="projects/alpha", owner="home-front", next="home-front: write it", needs=[BACK], goal="It is written")
check("create: a write that meets every guard passes", "created s" in out, out)
refused("create: several problems are listed in one refusal, each with its fix", lambda: _wt_create._create(subject="[home] bad create", description=DESC, project="projects/alpha", owner="home-front",
                                                                                                          next="look into the quota", mover="home-nobody", goal="TBD"),
        "Refused: 4 problems", "(1)", "(2)", "(3)", "(4)", "quota", "placeholder", "does not say who takes it", "home-nobody")

# ================================================================ the report on the existing items
for g in ("a60", "a61", "a62", "a63", "a64", "a65", "a66", "a67", "a68", "a69", "a70", "a71", "a72", "a73", "a74", "a75", "a76", "a77", "a78", "a79", "a80", "a81", "a82", "a83", "a84", "a85", "a86",
          "a87", "a88", "a89", "a91", "a92", "a93", "a95"):
    p = T / f"store/a/{g[1:]}.json"
    if p.exists(): p.unlink()
for p in (T / "store/s").glob("*.json"): p.unlink()
for p in (T / "store/a").glob("*.json"): p.unlink()
item(1, needs=[BACK])                                                                                   # passes everything
item(2, owner=U["home-lost"], needs=[], mover="home-lost")                                                    # a mover that is no one (its pane is gone)
item(3, needs=[BACK], mover="home-nobody")                                                                 # …stored
item(4, needs=[BACK], wait_kind="anchor", wait_event="merged")                                           # wait input + no end
item(5, needs=[BACK], wait_kind="relay", wait_event="Robin", post_wake_mover="home-nobody", ask_by=FUT)    # post-wake mover
item(6, needs=[BACK], hold=True, wake=day(3))                                                            # snooze
item(7, needs=[BACK], next="home-front: TBD")                                                              # filler
item(8, needs=["decision", FRONT], ask=ASK, hold=True)                                                    # decision + hold, second mover
item(9, needs=[FRONT, "home-peer"])                                                                             # second mover
item(10, needs=[BACK], next="do it")                                                                     # next with no name
item(11, needs=[BACK], next="home-front: waiting for Robin")                                                # wait in next
item(12, needs=[BACK], subject="[home] the quota", next="home-front: when it is ready")                      # alarming word + a flag only
item(13, needs=[BACK], wait_kind="relay", wait_event="Robin")                                             # no end (post-wake: the owner default stands)
item(14, status="completed", needs=[], outcome="done", next="")                                          # closed with an outcome
item(15, status="completed", needs=[], next="")                                                          # closed without
item(16, status="completed", needs=[], next="")
item(17, needs=[BACK], hold=True, wake=day(3), wait_basis={"text": f"visit {day(4)}", "wake": day(3), "by": "x", "at": 1.0})   # waiting, a real date: fine, default post-wake
ctx = mg.Ctx(now=now0, label=_fleet_sessions_registry._session_label, shown=_gh.shown)
items = {f"a{i}": rd(i) for i in range(1, 18)}
rep = mg.report(items, ctx)
ids = lambda k: sorted(int(g[1:]) for g in rep.ids.get(k, []))
check("report: counts open and closed", rep.open == 14 and rep.closed == 3, (rep.open, rep.closed))
check("report: mover → 2 and 3", ids("mover") == [2, 3], rep.ids)
check("report: wait input → 4; post-wake mover → 5; snooze → 6", ids("wait_input") == [4] and ids("post_wake") == [5] and ids("snooze") == [6], rep.ids)
check("report: filler → 7; decision + hold → 8; second mover → 8 and 9", ids("filler") == [7] and ids("decision_hold") == [8] and ids("second_mover") == [8, 9], rep.ids)
check("report: next with no name → 10; a wait in next → 11; an alarming word → 12; no end → 4 and 13", ids("next_unnamed") == [10] and ids("next_wait") == [11] and ids("alarm") == [12] and ids("no_end") == [4, 13], rep.ids)
check("report: the closed items without an outcome → 15 and 16; the broad list flags 12", ids(mg.CLOSED_NO_OUTCOME) == [15, 16] and rep.flagged == ["a12"], (rep.ids, rep.flagged))
check("report: what rests on a default is counted (alive items with no stored mover, waiting ones with no post-wake mover)", rep.defaulted.get("mover", 0) >= 7 and rep.defaulted.get("post_wake_mover", 0) >= 4, rep.defaulted)
line = mg.brief_line(rep)
check("report: the brief line is one line of counts", line.startswith("model guards would refuse on existing items: mover 2 · wait input 1 · post-wake mover 1 · snooze 1 · filler 1 · wait with no end 2 · decision with a hold 1 · second mover 2 · next line with no name 1 · wait in next 1 · alarming word 1 · closed without an outcome 2")
      and "\n" not in line, line)
text = mg.full_text(rep, _gh.shown)
check("report: the full text lists the ids per guard, an example refusal each, the flags and the defaults", "mover: 2: a2, a3" in text and "closed without an outcome: 2: a15, a16" in text and "e.g. a2:" in text and "flagged for broad wait words in next (when, once, after, until; accepted, not refused): 1: a12" in text and "resting on a default" in text, text)
check("report: a clean board says nothing", mg.brief_line(mg.report({"a1": rd(1), "a14": rd(14)}, ctx)) == "", None)
server._GUARD_REPORT.update(at=0.0, rep=None)
brief = _wt_brief.stackshot_brief()
check("report: stackshot_brief carries the line (the store's items, read only)", "model guards would refuse on existing items: mover 2" in brief and brief.count("model guards would refuse") == 1, brief[:600])
set_cfg(guards=False); server._GUARD_REPORT.update(at=0.0, rep=None)
check("report: …with the guards off it still reads, and says they are off", "(the guards are off: [model] guards = false)" in _wt_brief.stackshot_brief(), None)
set_cfg(); server._GUARD_REPORT.update(at=0.0, rep=None)
snap = {p.name: p.read_text() for p in (T / "store/a").glob("*.json")}
server._model_report(0)
check("report: existing items are only read: no file changed", snap == {p.name: p.read_text() for p in (T / "store/a").glob("*.json")}, None)
cli = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml", "STACKSHOT_FLEET_DIR": f"{tmp}/fleet"})
check("report: tools/model_guard_report.py prints the full report", cli.returncode == 0 and "model guards on 14 open and 3 closed items" in cli.stdout and "mover: 2: board#2, board#3" in cli.stdout, (cli.returncode, cli.stdout[:500], cli.stderr[-500:]))
cl = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py"), "--line"], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml", "STACKSHOT_FLEET_DIR": f"{tmp}/fleet"})
check("report: …--line the one line, --json the ids", cl.stdout.startswith("model guards would refuse on existing items: mover 2") and json.loads(subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py"), "--json"], capture_output=True, text=True,
      env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml", "STACKSHOT_FLEET_DIR": f"{tmp}/fleet"}).stdout)["guards"]["mover"] == ["a2", "a3"], cl.stdout[:300])

# ---- 6d, the dry run: the open items that already have the owner-as-mover mismatch (tools/model_guard_report.py --owner-mover [--store DIR])
item(18, needs=[BACK], state="doing", mover=OWN, expected_by=day(2), subject="[home] the owner moves a doing item")                 # the mismatch
item(19, needs=[BACK], state="your-step", mover=OWN, step=STEP, subject="[home] his step")                                          # fine: his step
item(20, needs=["decision"], ask=ASK, mover=OWN, subject="[home] his ask")                                                          # fine: his ask
item(21, needs=[BACK], mover=OWN, subject="[home] owner mover, no state stored")                                                     # the mismatch, derived state
item(22, needs=[BACK], hold=True, wake=day(3), mover=OWN, wait_basis={"text": f"visit {day(4)}", "wake": day(3), "by": "x", "at": 1.0}, subject="[home] waiting, mover stored")   # waiting: not judged
item(23, status="completed", needs=[], mover=OWN, outcome="done", next="", subject="[home] closed")
rows = mg.owner_mover_rows({f"a{i}": rd(i) for i in range(18, 24)}, ctx)
check("dry run: owner_mover_rows lists the open items with the owner as mover and no step or ask: id, subject, mover, state, creator", [r["id"] for r in rows] == ["a18", "a21"]
      and rows[0]["subject"] == "[home] the owner moves a doing item" and rows[0]["mover"] == OWN and rows[0]["state"] == "doing" and rows[1]["state"] == "doing (derived)" and rows[0]["creator"], rows)
check("dry run: …the report's guard count agrees", sorted(mg.report({f"a{i}": rd(i) for i in range(18, 24)}, ctx).ids.get("owner_mover", [])) == ["a18", "a21"], None)
env_ = {**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml", "STACKSHOT_FLEET_DIR": f"{tmp}/fleet"}
cd = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py"), "--owner-mover", "--store", str(T / "store")], capture_output=True, text=True, env=env_)
check("dry run: tools/model_guard_report.py --owner-mover --store DIR prints a count and one line per item", cd.returncode == 0 and cd.stdout.startswith("2 open item(s) with the board's owner as mover and no step or ask")
      and "board#18 | [home] the owner moves a doing item | mover " + OWN + " | state doing | created by " in cd.stdout and "board#21 |" in cd.stdout and f"board#{BID_B}" not in cd.stdout and "board#22" not in cd.stdout, (cd.returncode, cd.stdout, cd.stderr[-300:]))
cj = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py"), "--owner-mover", "--json", "--store", str(T / "store")], capture_output=True, text=True, env=env_)
check("dry run: …--json is the list of records", cj.returncode == 0 and [r["id"] for r in json.loads(cj.stdout)] == ["a18", "a21"] and set(json.loads(cj.stdout)[0]) == {"id", "subject", "mover", "state", "creator", "gap"}, cj.stdout[:300])
snap2 = {pth.name: pth.read_text() for pth in (T / "store/a").glob("*.json")}
subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py"), "--owner-mover", "--store", str(T / "store")], capture_output=True, text=True, env=env_)
check("dry run: read only: no file of the store changed", snap2 == {pth.name: pth.read_text() for pth in (T / "store/a").glob("*.json")}, None)
cn = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/model_guard_report.py"), "--owner-mover", "--store", str(T / "no-such-folder")], capture_output=True, text=True, env=env_)
check("dry run: --store with a missing folder is an error, not an empty report", cn.returncode == 2 and "not a folder" in cn.stderr, (cn.returncode, cn.stderr))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": model guards scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
