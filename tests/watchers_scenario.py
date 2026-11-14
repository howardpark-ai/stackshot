"""Scenario test for the waits' watchers (watchers.py, step 2, PR 4) — fixture data, no live store, no network, no server socket.

An item that stores a wait_kind (time | item | anchor | relay | event) is watched by the new watchers and by nothing else; every other item keeps today's machinery. Covered:

  * time: the wake passes → alive, the post-wake mover (the hold, the wake and the wait's fields go, the mover is stored and told in one line); not before.
  * item: the last `after` item closes → alive, the post-wake mover; an `after` item still open keeps the wait; the backstop (ask_by) passing first → alive, with the note that the item is still open.
  * anchor: a notice for the anchor (the keeper passed it, or nobody rules the project) → alive, the post-wake mover, the notice's gist on the item; an older notice, another anchor, another project
    and a routine CI line do not count; the backstop → "the anchor stayed silent"; at wait-set the reply says what anchor-hub already recorded on the anchor, and when it does not watch it.
  * relay: the ask-by day → alive with the owner as mover and the fixed ask with its three options; each answer's effect: arrived → the post-wake mover, not yet → the wait again on the date he gave
    (no readable date: the note is kept as his comment, no date is set and the item asks him back with three days to pick from), drop → closed as not planned.
  * chases (stored on the item: no tool logs one any more, so a fixture holds them): get shows them; a moved ask_by resets them; two on a wait bring it to the owner at its next end as "drop it?" (drop / keep waiting
    until a date), and a wait with fewer comes back as before.
  * pause: [model] pause holds the watchers and the wake pass alike; when it is false again the due ones fire in one pass, one message per recipient; in normal running several items for one
    recipient in one pass are one message too.
  * the gate: the wake pass and the `after` release skip an item with a stored wait_kind and still run for the others; [model] watchers = false gives the item back to them.
  * get shows `chases: n` and `woke: <what> → <mover>` (until a session writes), the brief lists the relay waits as "waiting on the world".

    tests/run-suite watchers        → exit 0 / 1"""
import contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="watcherstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the waits' watchers, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
ZONE_HOURS = 4      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}},
                                                          "projects/beta": {"title": "Beta", "name": "Beta", "org": "home", "tags": [], "type": "project",
                                                                            "session": "", "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "brain/projects/beta.md").write_text("---\ntitle: Beta\n---\n\n# Beta\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, project="projects/alpha", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="a"): return rd(i, letter)["metadata"]
def raw(i, letter="a"): return (T / f"store/{letter}/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.service import writes; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.model import model; from stackshot.waits import watchers as wk
from stackshot.service import item_read as _item_read
from stackshot.service import update as _update_svc
from stackshot.web import answers as _web_answers
from stackshot.router import routing as _routing
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.projects import pages as _pages
from stackshot.core import instance as _core_instance
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.service import runner as runner_svc
from stackshot.web.tools import brief as _wt_brief
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
SENT: list[tuple[str, str, str, str]] = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, OTHER, FRONT = "team-back", "home-other", "home-front"
UB, UO, UF = U["team-back"], U["home-other"], U["home-front"]
OWN = model.owner_display()
CFG = _cfg.CFG.setdefault("model", {})
def sent(tag=None): return [x for x in SENT if tag is None or x[3] == tag]
def reset(): SENT.clear()
def cfg(**kw):
    for k, v in kw.items(): CFG[k] = v
cfg(guards=False, watchers=True, pause=False)       # the write guards have their own suite; here they are off except where a test turns them on
AURL = "https://github.com/o/r/pull/5"
def notice(text, ts=None, anchor="github:o/r#5", ruling="passed", to=None, **kw):
    n = {"id": "n" + str(len(SENT)) + str(int(time.time() * 1000) % 100000), "ts": now0 if ts is None else ts, "kind": "anchor", "anchor": anchor, "to": to or U["home-stew"], "text": text,
         "ruling": ruling, "ruled_at": now0 if ts is None else ts}
    n.update(kw); return n

# ================================================================ the pure half
check("kinds: a stored kind is read, anything else is none", wk.stored_kind({"wait_kind": " Relay "}) == "relay" and wk.stored_kind({"wait_kind": "soon"}) == "" and wk.stored_kind({}) == "", None)
TW = {"wait_kind": "time", "wake": "2026-12-01"}
check("watches: open, a stored kind and an end a watcher can see, only while [model] watchers is on", wk.watches({"status": "open", "metadata": TW}) and not wk.watches({"status": "completed", "metadata": TW})
      and not wk.watches({"status": "open", "metadata": {}}), None)
cfg(watchers=False); check("watches: …false turns it off", not wk.watches({"status": "open", "metadata": TW}), None); cfg(watchers=True)
check("watches: a wait no watcher can end is not watched (review finding 6): a time wait with no wake or end, an end date on an item that is not verifying, an anchor wait with no anchor, a relay with no ask-by, an item wait with no after and no date",
      not wk.watches({"status": "open", "metadata": {"wait_kind": "time"}}) and not wk.watches({"status": "open", "metadata": {"wait_kind": "time", "end": "2026-12-01"}})
      and not wk.watches({"status": "open", "metadata": {"wait_kind": "anchor", "ask_by": "2026-12-01"}}) and not wk.watches({"status": "open", "metadata": {"wait_kind": "relay"}})
      and not wk.watches({"status": "open", "metadata": {"wait_kind": "item"}}), None)
check("watches: …and one it can end is: a verifying time wait with an end date, an anchor wait with its anchor, an item wait with after or a backstop date",
      wk.watches({"status": "open", "metadata": {"wait_kind": "time", "state": "verifying", "end": "2026-12-01"}}) and wk.watches({"status": "open", "metadata": {"wait_kind": "anchor", "wait_anchor": "https://x/y"}})
      and wk.watches({"status": "open", "metadata": {"wait_kind": "item", "after": ["a1"]}}) and wk.watches({"status": "open", "metadata": {"wait_kind": "item", "ask_by": "2026-12-01"}}), None)
I = lambda **m: {"status": "open", "metadata": m}
NOW = now0
check("due: time at its wake, not before", wk.due(I(wait_kind="time", wake=day(-1)), NOW) == "time" and wk.due(I(wait_kind="time", wake=day(2)), NOW) == "" and wk.due(I(wait_kind="time"), NOW) == "", None)
check("due: relay on its ask-by day (the start of that day), not before", wk.due(I(wait_kind="relay", ask_by=day(-1)), NOW) == "relay" and wk.due(I(wait_kind="relay", ask_by=day(3)), NOW) == "", None)
check("due: item when no `after` item is open; backstop (ask_by or wake) first when one is",
      wk.due(I(wait_kind="item", after=["a1"]), NOW, []) == "item" and wk.due(I(wait_kind="item", after=["a1"]), NOW, ["a1"]) == ""
      and wk.due(I(wait_kind="item", after=["a1"], ask_by=day(-1)), NOW, ["a1"]) == "backstop" and wk.due(I(wait_kind="item", after=["a1"], wake=day(-1)), NOW, ["a1"]) == "backstop", None)
check("due: anchor only at its backstop (an arrival is an event)", wk.due(I(wait_kind="anchor", wait_anchor=AURL, ask_by=day(-1)), NOW) == "backstop" and wk.due(I(wait_kind="anchor", wait_anchor=AURL, ask_by=day(4)), NOW) == "", None)
check("next_moment: the wake, the ask-by day, the earlier backstop",
      wk.next_moment({"wait_kind": "time", "wake": day(2)}) == wk.day_epoch(day(2)) and wk.next_moment({"wait_kind": "relay", "ask_by": day(3)}) == wk.day_epoch(day(3))
      and wk.next_moment({"wait_kind": "anchor", "ask_by": day(5), "wake": day(2)}) == wk.day_epoch(day(2)) and wk.next_moment({}) is None, None)
check("ask: the relay question is the fixed text, the party's own event named", wk.relay_ask({"wait_event": "countersigned NDA"}) == "Decide: has countersigned NDA arrived? · Options: arrived / not yet, ask again on <date> / drop"
      and wk.relay_ask({"wait_event": "signature", "party": "Acme legal"}) == "Decide: has Acme legal's signature arrived? · Options: arrived / not yet, ask again on <date> / drop"
      and wk.is_watcher_ask(wk.relay_ask({"wait_event": "x"})) and wk.is_watcher_ask(wk.drop_ask({"wait_event": "x"})) and not wk.is_watcher_ask("Decide: a · Recommend: b · Stakes: c · By: d"), wk.relay_ask({"wait_event": "x"}))
check("options: relay arrived / not yet / drop, one recommended; drop-it: drop / keep waiting", [o["label"] for o in wk.relay_options()] == ["arrived", "not yet, ask again on <date>", "drop"] and sum(o["recommended"] for o in wk.relay_options()) == 1
      and [o["label"] for o in wk.drop_options()] == ["drop", "keep waiting until <date>"] and len(render.options_of({"metadata": {"options": wk.relay_options()}})) == 3
      and len(render.options_of({"metadata": {"options": wk.drop_options()}})) == 2 and all(len(o["label"]) <= render.OPTION_LABEL_MAX and len(o["line"]) <= render.OPTION_LINE_MAX for o in wk.relay_options() + wk.drop_options()), None)
today = datetime.date(2026, 10, 26)
pd = lambda t: wk.parse_date(t, today)
check("date: ISO, month and day (weekday, suffix, either order), tomorrow, next week, in N days or weeks",
      pd("2026-11-09") == "2026-11-09" and pd("Mon Nov 9th") == "2026-11-09" and pd("ask me on Nov 9") == "2026-11-09" and pd("9 Nov") == "2026-11-09" and pd("the 9th of November please") == "2026-11-09"
      and pd("tomorrow") == "2026-10-27" and pd("next week") == "2026-11-02" and pd("in 3 days") == "2026-10-29" and pd("in 2 weeks") == "2026-11-09", [pd(x) for x in ("Mon Nov 9th", "9 Nov", "the 9th of November please")])
check("date: Japanese and weekday forms (review finding 12): 明日, 明後日, 11月9日, 9日, 3日後, a weekday name, next Monday", pd("明日") == "2026-10-27" and pd("明後日 お知らせ") == "2026-10-28" and pd("11月9日に") == "2026-11-09"
      and pd("9日") == "2026-11-09" and pd("3日後") == "2026-10-29" and pd("Friday") == "2026-10-30" and pd("next Monday") == "2026-11-02" and pd("monday") == "2026-11-02" and pd("the month after") == "", [pd(x) for x in ("明日", "9日", "Friday", "monday")])
check("date: none, a past date and a day that is not one read as no date; a month and day already gone means next year", pd("") == "" and pd("soon") == "" and pd("2026-10-01") == "" and pd("Oct 1st") == "2027-10-01" and pd("Feb 30th") == "", [pd("Oct 1st"), pd("Feb 30th")])
chased = {"wait_kind": "relay", "chases": [{"at": 1, "by": "x", "note": "a"}, {"at": 2, "by": "x", "note": "b"}]}
check("chases: two on a relay or anchor wait is chased out; one is not; a time wait never is", wk.chased_out(chased) and wk.chased_out({**chased, "wait_kind": "anchor"}) and not wk.chased_out({**chased, "chases": chased["chases"][:1]})
      and not wk.chased_out({**chased, "wait_kind": "time"}), None)
check("anchor_hit: any notice counts; a routine line counts for a merge or close wait only when it says so", wk.anchor_hit("a reply", "x", False) and wk.anchor_hit("PR merged", "x", False)
      and not wk.anchor_hit("PR merged", "CI passed on the PR", True) and wk.anchor_hit("PR merged", "PR merged: x", True) and wk.anchor_hit("a reply", "CI passed", True), None)

# ================================================================ time
item(10, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=BACK, needs=[], subject="[home] time wait")
item(11, wait_kind="time", hold=True, wake=day(3), post_wake_mover=BACK, needs=[], subject="[home] time wait not yet")
reset()
woke = wakes_svc.wake_pass()
m = mt(10)
check("time: the wake that passed turns the item alive with the post-wake mover", "a10" in woke and m.get("mover") == BACK and "wake" not in m and "hold" not in m and "wait_kind" not in m and "post_wake_mover" not in m and m.get("needs") == [BACK], m)
mod = _item_read._model_of({**rd(10), "gid": "a10"})
check("time: …the model reads it as alive, the mover the post-wake mover", mod.state == "alive" and mod.mover == BACK and mod.mover_explicit and not mod.conflicts, mod)
check("time: …and records what arrived, once", m.get("woke", {}).get("what") == f"its wake {day(-1)} came" and m["woke"]["to"] == BACK, m.get("woke"))
check("time: the mover is told in one line: the item, what it waited on, that it is theirs", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "is yours now" in sent("watch")[0][2] and "its wake" in sent("watch")[0][2]
      and "time wait" in sent("watch")[0][2] and "\n" not in sent("watch")[0][2], sent())
check("time: an item whose wake has not come is left as it was", mt(11).get("wait_kind") == "time" and hd_(mt(11)) is True and wk_(mt(11)) == day(3), mt(11))
reset(); wakes_svc.wake_pass()
check("time: the next pass tells nobody again and moves nothing", not sent() and mt(10).get("mover") == BACK, sent())
check("time: the next moment of an item still waiting is its wake", wakes_svc.next_wake() is not None and wakes_svc.next_wake().strftime("%Y-%m-%d") == day(3), wakes_svc.next_wake())

# ================================================================ item
item(20, wait_kind="item", after=["a21", "a22"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] item wait")
item(21, subject="[home] first blocker"); item(22, subject="[home] second blocker")
def close(g, outcome="done"):
    it = rd(g); it["status"] = "completed"; it["metadata"].update(outcome=outcome, reason="r"); (T / f"store/a/{g}.json").write_text(json.dumps(it))
    return wakes_svc.release_after(f"a{g}", outcome, "", "home-front")
reset(); close(21)
check("item: one `after` item closing, another still open: the wait goes on", mt(20).get("wait_kind") == "item" and not mt(20).get("mover") and not sent("watch"), mt(20))
close(22)
m = mt(20)
check("item: the last `after` item closing turns the item alive with the post-wake mover", m.get("mover") == BACK and "wait_kind" not in m and "after" not in m and "ask_by" not in m and m.get("needs") == [BACK], m)
check("item: …told in one line, with what closed", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "a22" in sent("watch")[0][2] and "closed" in sent("watch")[0][2], sent())
item(30, wait_kind="item", after=["a31"], post_wake_mover=BACK, ask_by=day(-1), needs=[], subject="[home] backstop")
item(31, subject="[home] never closes")
reset(); woke = wakes_svc.wake_pass()
m = mt(30)
check("item: the backstop passing first turns it alive with the post-wake mover and the note that the item is still open", "a30" in woke and m.get("mover") == BACK and "a31" in m["woke"]["what"] and "still open" in m["woke"]["what"], m)
item(32, wait_kind="item", after=["a33", "a34"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] superseded blocker")
item(33, subject="[home] old"); item(34, subject="[home] replacement")
it = rd(33); it["status"] = "completed"; it["metadata"].update(outcome="superseded", reason="r", superseded_by="a34"); (T / "store/a/33.json").write_text(json.dumps(it))
wakes_svc.release_after("a33", "superseded", "a34", "home-front")
check("item: a superseded blocker is followed to its open replacement and the wait goes on", mt(32).get("wait_kind") == "item" and "a34" in mt(32).get("after") and not mt(32).get("mover"), mt(32))
item(35, wait_kind="item", after=["a36"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] catch-up")
item(36, status="completed", outcome="done", reason="r")
reset(); woke = wakes_svc.wake_pass()
check("item: a close nobody saw (every `after` item already closed) is found by the next pass", "a35" in woke and mt(35).get("mover") == BACK, mt(35))

# the runner's ten-minute catch-up finds the same close even with the ask-by days away (the minute tick's due-wake gate does not see such a wait)
from stackshot.core import runner as RUN
item(94, wait_kind="item", after=["a95"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] catch-up through the runner")
item(95, status="completed", outcome="done", reason="r")
reset(); wakes_svc.minute_wake_pass()
check("item: the minute tick's gate (no wake due) leaves a wait whose blockers all closed unseen, with a far ask-by", mt(94).get("wait_kind") == "item" and not mt(94).get("mover"), mt(94))
ten_ticks = [t for t in runner_svc.ticks() if t.pace == "tenmin" and t.name == "wake_catchup"]
check("item: the runner's table has the ten-minute wake catch-up", len(ten_ticks) == 1 and ten_ticks[0].group == "tenmin", [t.name for t in runner_svc.ticks()])
reset(); RUN.Runner(ten_ticks).run_round()
check("item: …and its tick, run by the runner, releases that wait to the post-wake mover", mt(94).get("mover") == BACK and "wait_kind" not in mt(94), mt(94))

# ================================================================ anchor
item(40, wait_kind="anchor", wait_anchor=AURL, wait_event="PR merged", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] anchor wait")
item(41, wait_kind="anchor", wait_anchor=AURL, wait_event="PR merged", ask_by=day(5), post_wake_mover=BACK, needs=[], project="projects/beta", subject="[home] same anchor, another project")
item(42, wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/6", wait_event="PR merged", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] another anchor")
reset()
wakes_svc.anchor_release("projects/alpha", notice("old comment", ts=now0 - 20 * DAY))
check("anchor: a notice older than the item's last move does not count", mt(40).get("wait_kind") == "anchor", mt(40))
wakes_svc.anchor_release("projects/alpha", notice("CI passed on the PR", log_only=True, ruled_by=server.AUTO_RULER, ruling="merged", to=""))
check("anchor: a routine line of the fleet's own PR (CI passing) does not end a wait for a merge", mt(40).get("wait_kind") == "anchor", mt(40))
wakes_svc.anchor_release("projects/alpha", notice("dropped by the keeper", ruling="dropped"))
check("anchor: a notice the keeper dropped does not count (as for today's anchor wait)", mt(40).get("wait_kind") == "anchor", mt(40))
rel = wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged: the work landed"), by="home-stew")
m = mt(40)
check("anchor: a notice the keeper passed turns the item alive with the post-wake mover, the gist on it", rel == ["a40"] and m.get("mover") == BACK and "PR #5 merged" in m["woke"]["what"] and AURL in m["woke"]["what"] and "wait_kind" not in m, (rel, m))
check("anchor: …told in one line", len(sent("watch")) == 1 and sent("watch")[0][1] == UB and "PR #5 merged" in sent("watch")[0][2], sent())
check("anchor: another project's item and another anchor's item are not touched", mt(41).get("wait_kind") == "anchor" and mt(42).get("wait_kind") == "anchor", (mt(41), mt(42)))
check("anchor: a notice again does nothing (the item is alive now)", wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged again")) == [], None)
item(43, wait_kind="anchor", wait_anchor=AURL, wait_event="PR merged", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] anchor wait, merged routine line")
reset()
rel = wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged by home-front", log_only=True, ruled_by=server.AUTO_RULER, ruling="merged", to=""))
check("anchor: …but a routine line that says merged does", "a43" in rel and mt(43).get("mover") == BACK, (rel, mt(43)))
item(44, wait_kind="anchor", wait_anchor=AURL, wait_event="a reply", ask_by=day(5), post_wake_mover=BACK, needs=[], project="projects/beta", subject="[home] no keeper")
rel = wakes_svc.anchor_release("projects/beta", notice("someone replied", ruling=None, to="", live=True), by="")
check("anchor: in a project nobody rules, a notice that arrived turns the items waiting on it there (a line the live router holds counts)", set(rel) == {"a41", "a44"}, (rel, mt(44)))
item(45, wait_kind="anchor", wait_anchor=AURL, wait_event="a reply", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] silent")
reset(); woke = wakes_svc.wake_pass()
m = mt(45)
check("anchor: the backstop passing with no notice turns it alive with the note that the anchor stayed silent", "a45" in woke and m.get("mover") == BACK and "the anchor stayed silent" in m["woke"]["what"], m)
item(46, wait_kind="anchor", wait_anchor=AURL, wait_event="a reply", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] found by the minute pass", watch={"set_at": now0 - 3600})
_routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="a reply on the PR", anchor="github:o/r#5", pilot=True)
nid = _routing.read("projects/alpha", since=now0 - 60)[-1]["id"]
_routing.rule(nid, "passed", to=BACK, reason="for the builder", by="home-stew")
time.sleep(0.01)
out = wakes_svc.anchor_pass()
check("anchor: the minute pass finds a keeper-passed notice in the routing log for an item that waits on it", "a46" in out and mt(46).get("mover") == BACK, (out, mt(46)))

# the wait-set report
_anc.save({"projects/alpha": [{"url": AURL, "items": None, "added": now0, "by": "x"}]})
item(47, subject="[home] about to wait on the anchor", su=now0 - 3600, needs=[BACK])
_routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="PR #5 got a review comment", anchor="github:o/r#5", pilot=True, ts=now0 - 600)
out = _update_svc._update("a47", sender=FRONT, wait_kind="anchor", wait_anchor=AURL, wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, then="", mover="none")
check("anchor: at wait-set the reply says what anchor-hub already recorded on the anchor since the item's last move", "anchor-hub already recorded" in out and "PR #5 got a review comment" in out, out)
check("anchor: …and the wait is stamped (a notice older than it is not its arrival)", mt(47).get("watch", {}).get("set_at", 0) >= now0 and mt(47).get("wait_kind") == "anchor", mt(47))
item(48, subject="[home] quiet anchor", su=now0 - 3600, needs=[BACK])
refused("anchor: an anchor that is not on the project's list cannot be set as the wait (anchor_wait_refusal has the rest)", lambda: _update_svc._update("a48", sender=FRONT, wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/9", wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none"), "anchors list", "anchors(project=\"projects/alpha\"")
out = server._watch_anchor_seen("projects/alpha", "https://github.com/o/r/pull/9", now0 - 3600)
check("anchor: …the report for a stored wait, nothing recorded, says so, and an anchor anchor-hub does not watch for the project is named", "recorded nothing" in out and "does not watch" in out and "anchors(project=\"projects/alpha\"" in out, out)
out = _update_svc._update("a47", sender=FRONT, ask_by=day(8))
check("anchor: moving the awaited date (ask_by) resets the backstop's stamp, and says nothing more of the anchor", mt(47)["watch"]["set_at"] >= now0 and "anchor-hub already" not in out, out)
rel = wakes_svc.anchor_release("projects/alpha", notice("older than the wait", ts=now0 - 56))
check("anchor: a notice from before the wait was set is not its arrival", mt(47).get("wait_kind") == "anchor", mt(47))

# ================================================================ relay
RASK = "Decide: has countersigned NDA arrived? · Options: arrived / not yet, ask again on <date> / drop"
item(50, wait_kind="relay", wait_event="countersigned NDA", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] relay wait")
item(51, wait_kind="relay", wait_event="the lease", ask_by=day(4), post_wake_mover=BACK, needs=[], subject="[home] relay wait not yet due")
reset(); woke = wakes_svc.wake_pass()
m = mt(50)
check("relay: the ask-by day turns the item to the owner with the fixed ask", "a50" in woke and m.get("ask") == RASK and m.get("needs") == ["decision"] and m.get("then") == BACK and "wait_kind" not in m, m)
check("relay: …its three options map to the board's buttons", [o["label"] for o in render.options_of(rd(50))] == ["arrived", "not yet, ask again on <date>", "drop"], m.get("options"))
check("relay: …the item reads alive with the owner as mover, then the post-wake mover", _item_read._model_of({**rd(50), "gid": "a50"}).owner_moves and _item_read._model_of({**rd(50), "gid": "a50"}).then == BACK, _item_read._model_of({**rd(50), "gid": "a50"}))
check("relay: …nobody is messaged (his queue is the board)", not sent("watch"), sent())
g = _wt_get.stackshot_get("a50")
check("relay: get shows the question and what turned it", "countersigned NDA" in g and re.search(r"woke: .*ask-by day .* came → the owner", g), g)
check("relay: …a write by a session is not nagged for the ask's shape", "[ask]" not in _update_svc._update("a50", sender=FRONT, next="team-back: look at it"), None)
check("relay: the item that is not due is untouched", mt(51).get("wait_kind") == "relay", mt(51))
br = _wt_brief.stackshot_brief()
check("relay: the brief lists the relay waits as waiting on the world: what, ask-by date", "Waiting on the world (1;" in br and f"the lease, ask by {day(4)}" in br, br[:1500])

reset()
TODAY = _pages.zone_now().date()
def ymd(n): return (TODAY + datetime.timedelta(days=n)).isoformat()
out = server._answer("a50", "not yet, ask again on <date>", "later please", "answer")
m = mt(50)
check("relay answer: not yet with a note that holds no date keeps the note as his comment, sets no date and asks back",
      out == "askedback" and [(a["kind"], a["text"]) for a in m["answers"]] == [("comment", "later please")] and "ask_by" not in m and "wait_kind" not in m and m.get("needs") == ["decision"], m)
check("relay answer: …the ask-back quotes the note and offers three days counted from today (a week, two weeks, a month), then the first question's own buttons",
      "later please" in m["ask"] and wk.is_watcher_ask(m["ask"]) and wk.asked_of(m) == "relay"
      and [o["label"] for o in render.options_of(rd(50))][:3] == [wk.ASK_AGAIN + wk.day_words(TODAY + datetime.timedelta(days=7)), wk.ASK_AGAIN + wk.day_words(TODAY + datetime.timedelta(days=14)), wk.ASK_AGAIN + wk.day_words(wk._add_months(TODAY, 1))]
      and [o["label"] for o in render.options_of(rd(50))][3:] == ["arrived", "not yet, ask again on <date>", "drop"], (m["ask"], m.get("options")))
check("relay answer: …it is his move still, and the page has lines for it",
      _item_read._model_of({**rd(50), "gid": "a50"}).owner_moves and '"askedback":' in open(os.path.join(STACK, "stackshot/web/render.py"), encoding="utf-8").read()
      and "askedback" in render.Board._SENT and "stalenote" in render.Board._SENT and "closednote" in render.Board._SENT and "needdate" not in render.Board._SENT, (m, sent()))
out = server._answer("a50", wk.ASK_AGAIN + wk.day_words(TODAY + datetime.timedelta(days=14)), "", "answer")
m = mt(50)
check("relay answer: a day picked from the ask-back puts the wait back on that day", out == "decision" and m.get("wait_kind") == "relay" and ab_(m) == ymd(14) and "ask" not in m and "options" not in m and "decision" not in (m.get("needs") or []), (out, m))
# the same question again, and a date typed in the box over a pick
it = rd(50); m = it["metadata"]
m.pop("wait_kind"); m.pop("ask_by"); m["needs"] = ["decision"]; m["watch"] = {"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "countersigned NDA", "ask_by": ymd(20), "post_wake_mover": BACK}}; m["ask"] = RASK; m["options"] = wk.relay_options()
(T / "store/a/50.json").write_text(json.dumps(it))
out = server._answer("a50", "not yet, ask again on <date>", "one more week", "answer")
check("relay answer: one more week counts from the date the wait already ended on", out == "decision" and ab_(mt(50)) == ymd(27), (out, mt(50)))
it = rd(50); m = it["metadata"]
m.pop("wait_kind"); m.pop("ask_by"); m["needs"] = ["decision"]; m["watch"] = {"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "countersigned NDA", "post_wake_mover": BACK}}; m["ask"] = RASK; m["options"] = wk.relay_options()
(T / "store/a/50.json").write_text(json.dumps(it))
check("relay answer: …and from today when the wait had no date", server._answer("a50", "not yet, ask again on <date>", "park it for a week", "answer") == "decision" and ab_(mt(50)) == ymd(7), mt(50))
it = rd(50); m = it["metadata"]
m.pop("wait_kind"); m.pop("ask_by"); m["needs"] = ["decision"]; m["watch"] = {"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "countersigned NDA", "post_wake_mover": BACK}}; m["ask"] = RASK; m["options"] = wk.relay_options()
(T / "store/a/50.json").write_text(json.dumps(it))
server._answer("a50", "not yet, ask again on <date>", f"ask again on {day(10)}", "answer")
m = mt(50)
check("relay answer: not yet with a date puts the wait back on that date", m.get("wait_kind") == "relay" and ab_(m) == day(10) and m.get("wait_event") == "countersigned NDA" and m.get("post_wake_mover") == BACK
      and "ask" not in m and "options" not in m and "decision" not in (m.get("needs") or []) and "then" not in m, m)
check("relay answer: …and the loop's next moment is that date", wakes_svc.next_wake().strftime("%Y-%m-%d") <= day(10), wakes_svc.next_wake())
item(52, wait_kind="relay", wait_event="the parcel", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] relay to arrive")
wakes_svc.wake_pass(); reset()
server._answer("a52", "arrived", "", "answer")
m = mt(52)
check("relay answer: arrived puts it with the post-wake mover, alive", m.get("mover") == BACK and m.get("needs") == [BACK] and "ask" not in m and "options" not in m and "wait_kind" not in m and "arrived" in m["woke"]["what"], m)
check("relay answer: …the mover is told through the answer's own notice", any(x[1] == UB and x[3] == "answer" for x in SENT), sent())
item(53, wait_kind="relay", wait_event="the quote", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] relay to drop")
item(54, wait_kind="item", after=["a53"], post_wake_mover=OTHER, ask_by=day(9), needs=[], subject="[home] waits on the one dropped")
wakes_svc.wake_pass(); reset()
server._answer("a53", "drop", "", "answer")
check("relay answer: drop closes it as not planned (dropped), the items that waited on it turn", rd(53)["status"] == "completed" and mt(53).get("outcome") == "dropped" and "dropped on" in mt(53).get("reason", "")
      and "ask" not in mt(53) and "chases" not in mt(53) and "watch" not in mt(53) and mt(54).get("mover") == OTHER, (mt(53), mt(54)))
item(55, wait_kind="relay", wait_event="the review", ask_by=day(-1), post_wake_mover=OWN, needs=[], subject="[home] relay, the owner relays and the owner takes it")
wakes_svc.wake_pass()
server._answer("a55", "arrived", "", "answer")
check("relay answer: a post-wake mover that is the owner falls back to the project's default holder on 'arrived' (not the creator)", mt(55).get("mover") in (UF, "home-front") and "wait_kind" not in mt(55), mt(55))

# ================================================================ the relative-date table (no model, a small table)
D0 = datetime.date(2026, 11, 10)      # a Tuesday
def pd(text, base=None): return wk.parse_date(text, D0, base)
def ds(n): return (D0 + datetime.timedelta(days=n)).isoformat()
check("dates: a week and its siblings", [pd(x) for x in ("a week", "in a week", "one week", "a week from now", "another week", "one more week", "park for 1 week")] == [ds(7)] * 7, [pd(x) for x in ("a week", "in a week", "one more week")])
check("dates: two weeks, a fortnight, in N days, N weeks", [pd(x) for x in ("two weeks", "in 2 weeks", "a fortnight", "in 3 days", "3 days", "tomorrow", "the day after tomorrow", "next week")] == [ds(14), ds(14), ds(14), ds(3), ds(3), ds(1), ds(2), ds(7)], [pd(x) for x in ("two weeks", "a fortnight", "the day after tomorrow")])
check("dates: a month, next month, in a month, N months (a month is calendar months, cut to a shorter month's last day)", [pd(x) for x in ("a month", "next month", "in a month", "a month from now", "3 months")] == ["2026-12-10"] * 4 + ["2027-02-10"]
      and wk.parse_date("a month", datetime.date(2026, 1, 31)) == "2026-02-28", [pd(x) for x in ("a month", "next month", "3 months")])
check("dates: end of the week is the Friday (the next Friday on a Friday), end of the month, after the weekend", [pd(x) for x in ("end of the week", "end of the month", "after the weekend")] == [ds(3), "2026-11-30", ds(6)]
      and wk.parse_date("end of the week", datetime.date(2026, 11, 13)) == "2026-11-20" and wk.parse_date("end of the month", datetime.date(2026, 11, 30)) == "2026-12-31", None)
check("dates: more and another count from the date the wait ended on when it is after today, a plain span from today", pd("one more week", datetime.date(2026, 11, 20)) == "2026-11-27" and pd("another month", datetime.date(2026, 11, 20)) == "2026-12-20"
      and pd("a week", datetime.date(2026, 11, 20)) == ds(7) and pd("one more week", datetime.date(2026, 11, 1)) == ds(7), None)
check("dates: a past phrase, a phrase with no number and an explicit date are not caught by the table", [pd(x) for x in ("a week ago", "two days ago", "later please", "soon", "")] == [""] * 5 and pd("a week, or Mar 9th") == "2027-03-09" and pd("2099-03-09 or a week") == "2099-03-09", [pd(x) for x in ("a week ago", "soon")])

# the table is read last, and only for a note that is mostly a date phrase
check("dates: the older readers keep their results when a stray span stands in the note (tomorrow, next week, a weekday)",
      pd("I'll look at it next week, it is a month-end task") == ds(7) and pd("I'll do it on Friday, it takes a day") == ds(3) and pd("I will do it tomorrow, took two weeks to get here") == ds(1)
      and pd("Friday, a day after the review") == ds(3), [pd(x) for x in ("I'll look at it next week, it is a month-end task", "I'll do it on Friday, it takes a day", "Friday, a day after the review")])
FALSE_POS = ("a month-end report", "the end of the month report is late", "I waited a week for this", "it has been two weeks already", "once a day", "one day", "a day", "this is a two-week thing", "it took a month ago")
check("dates: a span inside a sentence, hyphenated, an idiom or in the past reads as no date", [pd(x) for x in FALSE_POS] == [""] * len(FALSE_POS), [(x, pd(x)) for x in FALSE_POS if pd(x)])
IN_FALSE = ("I finished it in a week", "it arrived in a week, thanks", "they replied in two days last time", "it will take a month, so please check in a month", "I will do it in a week, it took a week last time")
check("dates: \"in N units\" inside a sentence is not a cue of its own: no date", [pd(x) for x in IN_FALSE] == [""] * len(IN_FALSE), [(x, pd(x)) for x in IN_FALSE if pd(x)])
check("dates: …while it as the whole note, at the start or after a cue word still reads", [pd(x) for x in ("in a week", "in two days", "please ask me in two days", "remind me in a month", "snooze it for a week")] == [ds(7), ds(2), ds(2), "2026-12-10", ds(7)],
      [pd(x) for x in ("in a week", "please ask me in two days", "remind me in a month")])
check("dates: …while the phrase as the whole note, at its start, or right after a cue word reads", [pd(x) for x in ("a week", "please, a week", "park for one more week", "I'll look again in two weeks", "wait a month", "give it a week", "ask again in 3 days", "check back end of the month", "for a day")]
      == [ds(7), ds(7), ds(7), ds(14), "2026-12-10", ds(7), ds(3), "2026-11-30", ds(1)], [pd(x) for x in ("a week", "please, a week", "I'll look again in two weeks", "for a day")])
check("dates: of two phrases the first in the text counts (not the first in the code)", [pd(x) for x in ("a week or end of the month", "end of the month or a week", "tomorrow or a month")] == [ds(7), "2026-11-30", ds(1)], [pd(x) for x in ("a week or end of the month", "end of the month or a week")])
check("dates: the day after tomorrow is not tomorrow", pd("the day after tomorrow") == ds(2) and pd("tomorrow") == ds(1), pd("the day after tomorrow"))
# the ask-back quotes a note: a separator of the ask (a middle dot) in it, on a line of its own or between no-break spaces, must not make the ask read as another kind of question
AB_META = {"watch": {"asked": "relay", "was": {"wait_event": "the contract"}}, "ask": wk.relay_ask({"wait_event": "the contract"})}
for note_ in ("ok\n\u00b7\nRecommend: later", "ok\u00a0\u00b7\u00a0Recommend: later", "ok \u00b7 Options: later \u00b7 Recommend: x"):
    ask_, opts_ = wk.ask_back(AB_META, note_, D0)
    check(f"ask-back: a note with a middle dot ({note_!r}) leaves the ask a watcher ask, so the pick that follows is read as before", wk.is_watcher_ask(ask_) and wk.asked_of({**AB_META, "ask": ask_}) == "relay" and " \u00b7 Recommend: " not in ask_ and ask_.count(" \u00b7 Options: ") == 1, ask_)
# the answer box: the same readings through a date button (the server's own day, not the fixed one)
def next_dow(n): return (TODAY + datetime.timedelta(days=(n - TODAY.weekday()) % 7 or 7)).isoformat()
def fresh_relay(i, ask_by=None):
    item(i, wait_kind="relay", wait_event="the contract", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] relay for the box")
    wakes_svc.wake_pass()
for i_, txt_, want_ in ((70, "Friday, a day after the review", next_dow(4)), (71, "I'll look at it next week, it is a month-end task", ymd(7)), (72, "ok, a month-end report", None)):
    fresh_relay(i_)
    out_ = server._answer(f"a{i_}", "not yet, ask again on <date>", txt_, "answer")
    check(f"answer box: {txt_!r} reads as the older readers do" if want_ else f"answer box: {txt_!r} reads as no date and is asked back", (ab_(mt(i_)) == want_ and out_ == "decision") if want_ else (out_ == "askedback" and "ask_by" not in mt(i_)), (out_, mt(i_)))

# ================================================================ the ask-back: the day is stored, the subject is the wait's
fresh_relay(73)
server._answer("a73", "not yet, ask again on <date>", "later please", "answer")
m = mt(73)
check("ask-back: each day button stores its ISO day, and the ask names the wait (watch.was holds its event)", [o.get("date") for o in m["options"][:3]] == [ymd(7), ymd(14), wk._add_months(TODAY, 1).isoformat()] and "the contract" in m["ask"] and "the news" not in m["ask"], m["ask"])
it = rd(73); it["metadata"]["options"][0]["label"] = "Ask again on Mon Jan 1st"; it["metadata"]["options"][0]["date"] = ymd(5); it["metadata"]["ask"] = it["metadata"]["ask"].replace(wk.ASK_AGAIN + wk.day_words(TODAY + datetime.timedelta(days=7)), "Ask again on Mon Jan 1st")
(T / "store/a/73.json").write_text(json.dumps(it))
check("ask-back: a pick is read from the stored day, never from the label (a label that names a month-day already past would roll to next year)", server._answer("a73", "Ask again on Mon Jan 1st", "", "answer") == "decision" and ab_(mt(73)) == ymd(5), mt(73))
fresh_relay(74)
server._answer("a74", "not yet, ask again on <date>", "later please", "answer")
it = rd(74); lab = it["metadata"]["options"][1]["label"]; it["metadata"]["options"][1]["date"] = ymd(-1); (T / "store/a/74.json").write_text(json.dumps(it))
out = server._answer("a74", lab, "", "answer")
check("ask-back: a pick that arrives after its day has passed asks again with new days; no wait is set", out == "askedback" and "ask_by" not in mt(74) and "wait_kind" not in mt(74) and mt(74)["options"][0]["date"] == ymd(7), (out, mt(74)))

# ================================================================ chases
item(60, wait_kind="relay", wait_event="the signed copy", ask_by=day(4), post_wake_mover=BACK, needs=[], subject="[home] chased relay", chases=[{"at": now0, "by": BACK, "note": "mailed Robin a reminder"}])      # a stored chase: fixture data (no tool logs one any more)
reset()
g = _wt_get.stackshot_get("a60")
check("chase: get shows chases: n with the last note of a stored chase", "chases: 1 (last by team-back: mailed Robin a reminder)" in g, g)
out = _update_svc._update("a60", sender=BACK, ask_by=day(5))
check("chase: a moved ask_by resets the backstop and the chases (they were about the old date)", "chases" not in mt(60) and ab_(mt(60)) == day(5), mt(60))
it = rd(60); it["metadata"].pop("until", None); it["metadata"]["ask_by"] = day(-1); it["metadata"]["chases"] = [{"at": 1.0, "by": BACK, "note": "one"}, {"at": 2.0, "by": BACK, "note": "two"}]; (T / "store/a/60.json").write_text(json.dumps(it))
reset(); woke = wakes_svc.wake_pass()
m = mt(60)
check("chase: two chases and no arrival: at the wait's end the item comes to the owner as drop it?", "a60" in woke and m["ask"].startswith("Decide: drop it?") and "· Options: drop / keep waiting until <date>" in m["ask"] and m.get("needs") == ["decision"]
      and [o["label"] for o in render.options_of(rd(60))] == ["drop", "keep waiting until <date>"] and len(m.get("chases") or []) == 2 and m.get("then") == BACK, m)
check("chase: …nobody is messaged", not sent("watch"), sent())
server._answer("a60", "keep waiting until <date>", "", "answer")
check("chase: keep waiting with no date keeps the note and asks back, the wait is not put back", mt(60).get("needs") == ["decision"] and "wait_kind" not in mt(60) and mt(60)["ask"].startswith("Decide: when should") and wk.asked_of(mt(60)) == "dropit"
      and [o["label"] for o in render.options_of(rd(60))][-2:] == ["drop", "keep waiting until <date>"], mt(60))
server._answer("a60", "keep waiting until <date>", f"until {day(12)}", "answer")
m = mt(60)
check("chase: keep waiting until a date puts the wait back on it and starts the chases over", m.get("wait_kind") == "relay" and ab_(m) == day(12) and "chases" not in m and "ask" not in m, m)
item(61, wait_kind="relay", wait_event="the schedule", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] chased then dropped", chases=[{"at": 1.0, "by": BACK, "note": "a"}, {"at": 2.0, "by": BACK, "note": "b"}])
wakes_svc.wake_pass()
server._answer("a61", "drop", "", "answer")
check("chase: drop it? answered drop closes the item", rd(61)["status"] == "completed" and mt(61).get("outcome") == "dropped", mt(61))
item(62, wait_kind="relay", wait_event="the form", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] one chase only", chases=[{"at": 1.0, "by": BACK, "note": "a"}])
wakes_svc.wake_pass()
check("chase: one chase is not enough: the usual relay question comes", mt(62).get("ask") == "Decide: has the form arrived? · Options: arrived / not yet, ask again on <date> / drop", mt(62))
item(63, wait_kind="anchor", wait_anchor=AURL, wait_event="a reply", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] anchor chased twice", chases=[{"at": 1.0, "by": BACK, "note": "a"}, {"at": 2.0, "by": BACK, "note": "b"}])
reset(); wakes_svc.wake_pass()
check("chase: an anchor that stayed silent after two chases comes to the owner as drop it?, not to the post-wake mover", mt(63).get("ask", "").startswith("Decide: drop it?") and not sent("watch") and "mover" not in mt(63), mt(63))
server._answer("a63", "keep waiting until <date>", f"{day(7)}", "answer")
check("chase: …keep waiting restores the anchor wait with its anchor and event", mt(63).get("wait_kind") == "anchor" and mt(63).get("wait_anchor") == AURL and mt(63).get("wait_event") == "a reply" and ab_(mt(63)) == day(7), mt(63))
item(64, subject="[home] closes with chases", chases=[{"at": 1.0, "by": BACK, "note": "a"}], woke={"what": "x", "to": BACK, "at": 1.0}, watch={"set_at": 1.0}, needs=[BACK])
_update_svc._update("a64", sender=BACK, status="completed", outcome="dropped", reason="not wanted any more", description="- Dropped: it was not wanted any more")
check("chase: a close drops the chases, the arrival and the wait's record", not any(k in mt(64) for k in ("chases", "woke", "watch")), mt(64))

# ================================================================ one message per recipient, and the pause
for i in (70, 71, 72):
    item(i, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=BACK, needs=[], subject=f"[home] batch {i}")
item(73, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=OTHER, needs=[], subject="[home] batch other")
item(74, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=FRONT, needs=[], subject="[home] batch front")
item(75, hold=True, wake=day(-1), needs=[BACK], subject="[home] plain hold, today's wake pass")
cfg(pause=True); reset()
check("pause: the wake pass does nothing and the watchers do nothing", wakes_svc.wake_pass() == [] and watching_svc.watch_pass() == [] and not SENT and mt(70).get("wait_kind") == "time" and hd_(mt(75)) is True, (SENT, mt(70)))
check("pause: …the item whose wake passed is left exactly as it was, the plain hold too", wk_(mt(75)) == day(-1), mt(75))
check("pause: the wake loop does not spin on a due wake", wakes_svc.next_wake() is not None and wakes_svc.next_wake() < _pages.zone_now(), None)
rel = wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged", ts=now0 + 1))
check("pause: a notice for an anchor wait does not turn it either", mt(47).get("wait_kind") == "anchor" and rel == [], mt(47))
cfg(pause=False); reset()
woke = wakes_svc.wake_pass()
check("pause off: the due ones fire in one pass", {"a70", "a71", "a72", "a73", "a74"} <= set(woke), woke)
w = sent()
tos = sorted(x[1] for x in w)
check("pause off: one message per recipient listing its items", tos == sorted([UB, UO, UF]) and len([x for x in w if x[1] == UB]) == 1, [(x[1], x[2][:60]) for x in w])
mb = next(x for x in w if x[1] == UB)
check("pause off: …the recipient with three watched items and a plain wake gets one message: the wake line, then the watchers' count and one line each (review finding 7)",
      "3 items are yours now" in mb[2] and all(f"a{n}:" in mb[2] for n in (70, 71, 72)) and "a75" in mb[2] and mb[2].count("\n") >= 4, mb[2])
mo = next(x for x in w if x[1] == UO)
check("pause off: …one item alone is one line", "\n" not in mo[2] and "a73" in mo[2], mo[2])
mf = next(x for x in w if x[1] == UF)
check("pause off: …a front agent gets the mark a front agent takes", mf[2].startswith(_wt_text._FOR_OWNER), mf[2])
check("pause off: …the messages that carry only watched items are tagged watch, the merged one is the wake pass's", [x[3] for x in w if x[1] == UO] == ["watch"] and [x[3] for x in w if x[1] == UB] == ["wake"], [(x[1], x[3]) for x in w])
check("pause off: today's wake pass released the plain hold in the same pass", "hold" not in mt(75) and "a75" in woke, mt(75))
SENT_COUNT = len(SENT); wakes_svc.wake_pass()
check("pause off: nothing is told twice", len(SENT) == SENT_COUNT, sent())

# ================================================================ the gate
now = time.time()
item(80, hold=True, wake=day(-20), su=now0 - 40 * DAY, needs=[BACK], subject="[home] overdue hold, today's wake pass")
item(81, wait_kind="time", hold=True, wake=day(-20), su=now0 - 40 * DAY, needs=[BACK], post_wake_mover=BACK, subject="[home] overdue, watched")
cfg(watchers=False)
reset(); woke = wakes_svc.wake_pass()
check("gate: …the wake pass too: today's release (the hold and the wake go), no watcher message", "a81" in woke and "hold" not in mt(81) and "wake" not in mt(81) and not sent("watch") and mt(81).get("wait_kind") == "time" and "mover" not in mt(81), mt(81))
item(82, wait_kind="relay", wait_event="the form", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] relay, switch off")
reset(); woke = wakes_svc.wake_pass()
check("switch off: a relay's ask-by day does nothing", "a82" not in woke and mt(82).get("wait_kind") == "relay" and "ask" not in mt(82), mt(82))
item(83, wait_kind="item", after=["a84"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] item wait, switch off")
item(84, subject="[home] its blocker")
close(84)
check("switch off: an `after` close releases the item as today (the after goes, no watcher mover)", "after" not in mt(83) and "mover" not in mt(83) and not sent("watch"), mt(83))
rel = wakes_svc.anchor_release("projects/alpha", notice("PR #5 merged", ts=now0 + 2))
check("switch off: an anchor notice leaves the anchor wait alone", mt(47).get("wait_kind") == "anchor" and rel == [], mt(47))
cfg(watchers=True)
item(85, wait_kind="item", after=["a86"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] item wait, switch on")
item(86, subject="[home] its blocker")
item(87, hold=True, after=["a86"], needs=[BACK], subject="[home] a plain after item")
reset(); close(86)
check("gate: with the switch on, one close turns the watched item (its mover) and releases today's plain after item (its sessions in needs), each its own way", mt(85).get("mover") == BACK and "woke" in mt(85) and "after" not in mt(87) and "hold" not in mt(87)
      and "woke" not in mt(87) and "mover" not in mt(87), (mt(85), mt(87)))
item(88, wait_kind="anchor", wait_anchor=AURL, wait_event="x", ask_by=day(9), after=["a89"], post_wake_mover=BACK, needs=[], subject="[home] anchor wait that also names an after")
item(89, subject="[home] its blocker")
close(89)
check("gate: an `after` close does not turn a watched wait of another kind", mt(88).get("wait_kind") == "anchor" and "mover" not in mt(88), mt(88))

# ================================================================ display: the arrival is shown until a session writes
g = _wt_get.stackshot_get("a10")
check("display: get shows woke: what arrived → the mover", re.search(r"woke: its wake \S+ came → team-back", g) is not None, g)
_update_svc._update("a10", sender=BACK, next="team-back: take it")
check("display: …until a session writes to the item", "woke" not in mt(10) and "woke:" not in _wt_get.stackshot_get("a10"), mt(10))
check("display: a closed item shows none of it", "chases:" not in _wt_get.stackshot_get("a64") and "woke:" not in _wt_get.stackshot_get("a64"), None)

# ================================================================ the write guards still read a watched wait (a real write, guards on)
cfg(guards=True)
item(90, subject="[home] guarded relay", needs=[BACK], su=now0 - 3600)
out = _update_svc._update("a90", sender=FRONT, wait_kind="relay", wait_event="the courier's parcel", ask_by=day(6), post_wake_mover=BACK, mover="none", next="team-back: nothing until it comes")
check("guards: a relay wait with its event, ask-by day and post-wake mover is accepted", mt(90).get("wait_kind") == "relay" and "model: waiting on news" in out, out)
out = _update_svc._update("a71", sender=BACK, next="team-back: take it from here")
check("guards: the post-wake mover's first write on the item that turned alive passes the write guards", "updated a71" in out and "model: alive · mover team-back" in out and "model conflict" not in out, out)
out = _update_svc._update("a52", sender=BACK, next="team-back: got it, working")
check("guards: …so does the one on an item the owner answered 'arrived' on", "updated a52" in out and "model conflict" not in out, out)
cfg(guards=False)

# ================================================================ the review round
import threading
A3, A2, A4, A5 = (f"https://github.com/o/r/pull/{n}" for n in (65, 77, 78, 79))
WATCHED = lambda: {"set_at": now0 - 3600}

# --- 1. a held item that stores an anchor wait is the watchers', not today's hold release; the replay gives unwatched held items nothing new
_anc.save({"projects/alpha": [{"url": A3, "items": ["a56", "a13", "a14"], "added": now0, "by": "x"}]})
item(56, hold=True, wake=day(9), wait_kind="anchor", wait_anchor=A3, wait_event="PR merged", ask_by=day(9), post_wake_mover=BACK, needs=[], subject="[home] held and watched", watch=WATCHED())
item(13, hold=True, wake=day(9), needs=[BACK], subject="[home] held, no stored wait")
reset()
rel = wakes_svc.anchor_release("projects/alpha", notice("PR #65 merged: it landed", anchor="github:o/r#65"), by="home-stew")
m = mt(56)
check("review 1: a held, anchor-scoped item with a stored anchor wait is turned by the watchers (alive, post-wake mover, the notice's gist), not released from hold by today's branch first",
      m.get("mover") == BACK and "wait_kind" not in m and "hold" not in m and "PR #65 merged" in m["woke"]["what"] and "stayed silent" not in m["woke"]["what"], m)
check("review 1: …told once, in the watchers' line", len([x for x in sent() if x[1] == UB and "a56" in x[0]]) == 1 and any("is yours now" in x[2] for x in sent() if "a56" in x[0]), sent())
check("review 1: …and the held item with no stored wait is released from hold as before, in the same call", "a13" in rel and "hold" not in mt(13) and "wait_kind" not in mt(13) and "mover" not in mt(13), (rel, mt(13)))
cfg(watchers=False)
item(14, hold=True, wake=day(9), wait_kind="anchor", wait_anchor=A3, wait_event="PR merged", ask_by=day(9), post_wake_mover=BACK, needs=[BACK], subject="[home] held, anchor kind, switch off")
rel = wakes_svc.anchor_release("projects/alpha", notice("PR #65 merged again", anchor="github:o/r#65"), by="home-stew")
check("review 1: with [model] watchers = false the same item is a plain held item again: released from hold, no mover", "a14" in rel and "hold" not in mt(14) and "mover" not in mt(14) and mt(14).get("wait_kind") == "anchor", (rel, mt(14)))
cfg(watchers=True)

_anc.save({"projects/alpha": [{"url": A2, "items": ["a57", "a15"], "added": now0, "by": "x"}]})
item(57, wait_kind="anchor", wait_anchor=A2, wait_event="a reply", ask_by=day(9), post_wake_mover=BACK, needs=[], subject="[home] replay, watched", watch=WATCHED())
item(15, hold=True, wake=day(9), needs=[BACK], subject="[home] replay, held and unwatched, same anchor")
nid = _routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="a reply on PR 77", anchor="github:o/r#77", pilot=True)
_routing.rule(nid, "passed", to=BACK, reason="for the builder", by="home-stew")
reset(); out = wakes_svc.anchor_pass()
check("review 1: the minute pass replays the keeper's ruling for the watched wait", "a57" in out and mt(57).get("mover") == BACK, (out, mt(57)))
check("review 1: …and gives the held item on the same anchor no release it did not get before (a keeper's ruling released it in no pass, only in _route)", "a15" not in out and hd_(mt(15)) is True and not mt(15).get("woke"), (out, mt(15)))

# --- 2 and 3. the lock order, and no pending-answer registration for a wait put back
class _Spy:
    def __init__(self, inner): self.inner, self.n, self.bad = inner, 0, []
    def __enter__(self):
        self.n += 1
        if not writes.ITEM_LOCK._is_owned(): self.bad.append("took the answer lock without the item lock")
        return self.inner.__enter__()
    def __exit__(self, *a): return self.inner.__exit__(*a)
item(58, wait_kind="relay", wait_event="the badge", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] lock order, arrived")
item(59, wait_kind="relay", wait_event="the key", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] lock order, drop")
item(66, wait_kind="relay", wait_event="the card", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] lock order, not yet")
wakes_svc.wake_pass()
spy = _Spy(_web_answers._ANSWER_LOCK); _web_answers._ANSWER_LOCK = spy
try:
    server._answer("a58", "arrived", "", "answer"); server._answer("a59", "drop", "", "answer"); server._answer("a66", "not yet, ask again on <date>", f"on {day(6)}", "answer")
finally:
    _web_answers._ANSWER_LOCK = spy.inner
check("review 2: _answer takes the item lock before the answer lock, on arrived, on drop (its after releases run inside) and on not yet", spy.n == 3 and not spy.bad, (spy.n, spy.bad))
pending = _web_answers._answers_load()
check("review 3: a wait put back (not yet, keep waiting) registers no pending answer, so no 'owner has not written' nag follows; arrived and drop still do", "a66" not in pending and "a58" in pending, list(pending))
item(67, subject="[home] lock stress", needs=[BACK]); errs = []
def _ans():
    try:
        for _ in range(40): server._answer("a67", "", "a note", "comment")
    except Exception as e: errs.append(repr(e))
def _upd():
    try:
        for i in range(40): _update_svc._update("a67", sender=BACK, next=f"team-back: step {i}")
    except Exception as e: errs.append(repr(e))
ths = [threading.Thread(target=f, daemon=True) for f in (_ans, _upd)]
for t in ths: t.start()
for t in ths: t.join(60)
check("review 2: an answer and an update on one item at once do not deadlock", not any(t.is_alive() for t in ths) and not errs, errs)

# --- 4. an answer in the box with no button: he took it up
item(16, wait_kind="relay", wait_event="the lease", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] box-only answer, relay ask")
item(17, wait_kind="relay", wait_event="the lease", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] box-only answer, drop it? ask", chases=[{"at": 1.0, "by": BACK, "note": "a"}, {"at": 2.0, "by": BACK, "note": "b"}])
item(18, wait_kind="relay", wait_event="the lease", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] a comment on a watcher ask")
wakes_svc.wake_pass(); reset()
check("review 4: the fixtures are up: the relay ask, and the drop it? ask after two chases", mt(16).get("ask", "").startswith("Decide: has") and mt(17).get("ask", "").startswith("Decide: drop it?"), (mt(16), mt(17)))
server._answer("a16", "", "not yet, try next Friday", "answer")
m = mt(16)
check("review 4: a box-only answer on the relay ask hands the item to the post-wake mover, alive", m.get("mover") == BACK and m.get("needs") == [BACK] and "then" not in m, m)
check("review 4: …the ask, the options and watch.asked are gone, the wait's own fields too, and no conflict is left", not any(k in m for k in ("ask", "options", "wait_kind", "post_wake_mover")) and "asked" not in (m.get("watch") or {})
      and not _item_read._model_of({**rd(16), "gid": "a16"}).conflicts and _item_read._model_of({**rd(16), "gid": "a16"}).mover == BACK, m)
check("review 4: …the wait's record stays in watch.was, so the mover can put the wait back", (m.get("watch") or {}).get("was", {}).get("wait_kind") == "relay" and m["watch"]["was"].get("wait_event") == "the lease", m.get("watch"))
check("review 4: …the arrival line is neutral: his words, and nothing claims an arrival", m["woke"]["what"] == f'{_core_instance.OWNER} answered in words: "not yet, try next Friday"' and "arrived" not in m["woke"]["what"].replace("answered", "") and m["woke"]["to"] == BACK, m.get("woke"))
check("review 4: …and the mover is told with his words", any(x[1] == UB and x[3] == "answer" and "not yet, try next Friday" in x[2] for x in SENT), sent("answer"))
server._answer("a17", "", "drop it, not needed", "answer")
check("review 4: the same on the drop it? ask: the item is not closed, it goes to the mover with his words", rd(17)["status"] == "open" and mt(17).get("mover") == BACK and "ask" not in mt(17) and "options" not in mt(17) and "then" not in mt(17)
      and mt(17)["woke"]["what"] == f'{_core_instance.OWNER} answered in words: "drop it, not needed"' and (mt(17).get("watch") or {}).get("was", {}).get("wait_kind") == "relay" and "asked" not in (mt(17).get("watch") or {}), mt(17))
server._answer("a18", "", "which lease is this?", "comment")
check("review 4: a comment (not an answer) on a watcher ask leaves the ask up", mt(18).get("ask", "").startswith("Decide: has") and mt(18).get("needs") == ["decision"], mt(18))

# --- 5. a wait stored before the stamp existed: no week-old notice wakes it
item(19, wait_kind="anchor", wait_anchor=A4, wait_event="PR merged", ask_by=day(9), post_wake_mover=BACK, needs=[], subject="[home] stored before the stamp existed")
it = rd(19); it["updated"] = now0 - 2 * DAY; (T / "store/a/19.json").write_text(json.dumps(it))
check("review 5: with no stamp the floor is the item's last write, not only its state clock", watching_svc.watch_floor(rd(19)) == now0 - 2 * DAY, watching_svc.watch_floor(rd(19)))
_anc.save({"projects/alpha": [{"url": A4, "items": None, "added": now0, "by": "x"}]})
wakes_svc.anchor_release("projects/alpha", notice("PR #78 merged long ago", anchor="github:o/r#78", ts=now0 - 5 * DAY), by="home-stew")
check("review 5: a notice from before the item's last write does not wake it", mt(19).get("wait_kind") == "anchor", mt(19))
nid = _routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="PR #78 merged three days ago", anchor="github:o/r#78", pilot=True, ts=now0 - 3 * DAY)
_routing.rule(nid, "passed", to=BACK, reason="for the builder", by="home-stew")
before = rd(19)["state_updated"]
wakes_svc.anchor_pass()
check("review 5: the minute pass stamps the wait on first sight (a filing save: the state clock stays) and does not wake it for the old line in the log", mt(19).get("watch", {}).get("set_at", 0) >= now0 and rd(19)["state_updated"] == before and mt(19).get("wait_kind") == "anchor", mt(19))
time.sleep(0.02)
nid = _routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="PR #78 merged now", anchor="github:o/r#78", pilot=True)
_routing.rule(nid, "passed", to=BACK, reason="for the builder", by="home-stew")
out = wakes_svc.anchor_pass()
check("review 5: …a notice after the stamp wakes it", "a19" in out and mt(19).get("mover") == BACK, (out, mt(19)))

# --- 6. a wait no watcher can end keeps today's mechanisms, and the brief lists it
item(68, wait_kind="anchor", hold=True, wake=day(-1), needs=[BACK], subject="[home] anchor kind, no anchor stored")
item(69, wait_kind="time", needs=[BACK], subject="[home] time kind, no date")
reset(); woke = wakes_svc.wake_pass()
check("review 6: an anchor wait with no stored anchor is released by today's wake pass (the hold goes, no watcher mover)", "a68" in woke and "hold" not in mt(68) and "mover" not in mt(68) and not any("a68" in x[0] for x in sent("watch")), mt(68))
br = _wt_brief.stackshot_brief()
check("review 6: the brief lists the waits no watcher can end", "Waits no watcher can end" in br and "a68" in br and "a69" in br, br[:1800])

# --- 8. the item turned to the owner passes the second-mover guard
cfg(guards=True)
item(23, wait_kind="relay", wait_event="the badge", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] second-mover guard")
wakes_svc.wake_pass()
mod = _item_read._model_of({**rd(23), "gid": "a23"})
check("review 8: the turned item's needs is decision alone, the post-wake mover is `then`, and the model reads no conflict", mt(23).get("needs") == ["decision"] and mt(23).get("then") == BACK and mod.owner_moves and not mod.conflicts, (mt(23), mod))
out = _update_svc._update("a23", sender=FRONT, next="home-front: read his answer on the board")
check("review 8: a session's write on it passes the write guards", "updated a23" in out and "model conflict" not in out, out)
cfg(guards=False)

# --- 9. a due wait is read again under the lock
item(76, wait_kind="time", hold=True, wake=day(5), post_wake_mover=BACK, needs=[], subject="[home] no longer due")
_real_due, _once = wk.due, []
def _fake_due(it, now, ao=None):
    if it.get("subject") == "[home] no longer due" and not _once:
        _once.append(1); return "time"
    return _real_due(it, now, ao)
wk.due = _fake_due
try:
    reset(); moved = watching_svc.watch_pass()
finally:
    wk.due = _real_due
check("review 9: an item that reads as due outside the lock but is not due under it is left alone", "a76" not in moved and mt(76).get("wait_kind") == "time" and hd_(mt(76)) is True and not any("a76" in x[0] for x in sent()), (moved, mt(76)))

# --- 12. a due item that keeps failing is backed off, not retried in a loop
item(92, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=BACK, needs=[], subject="[home] fails to turn")
_save0, _fails = writes.save, []
def _flaky(gid, it, *a, **k):
    if gid == "a92" and not ((it.get("metadata") or {}).get("watch") or {}).get("failed_at"):
        _fails.append(1); raise RuntimeError("disk")
    return _save0(gid, it, *a, **k)
writes.save = _flaky
try:
    reset(); moved = watching_svc.watch_pass(); n1 = len(_fails); moved2 = watching_svc.watch_pass()
finally:
    writes.save = _save0
check("review 12: a turn that fails is noted on the item (watch.failed_at) and is not retried in the same minute; nobody is told of it", "a92" not in moved and n1 >= 1 and len(_fails) == n1 and "a92" not in moved2
      and mt(92).get("watch", {}).get("failed_at", 0) >= now0 and mt(92).get("wait_kind") == "time" and not any("a92" in x[0] for x in sent("watch")), (mt(92), len(_fails), sent()))
check("review 12: …and its next moment is after the back-off, so the wake loop does not spin on it", wk.next_moment(mt(92)) > time.time() + wk.BACKOFF - 60, wk.next_moment(mt(92)))
reset(); moved = watching_svc.watch_pass(time.time() + wk.BACKOFF + 5)
check("review 12: …after the back-off it turns, and the failure note goes", "a92" in moved and mt(92).get("mover") == BACK and "failed_at" not in (mt(92).get("watch") or {}), mt(92))

item(24, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=BACK, needs=[], subject="[home] fails to turn, and to note it")
_save1 = writes.save
_tries = []
def _dead(gid, it, *a, **k):
    if gid == "a24": _tries.append(1); raise RuntimeError("disk")
    return _save1(gid, it, *a, **k)
writes.save = _dead
try:
    reset(); watching_svc.watch_pass(); n1 = len(_tries); watching_svc.watch_pass(); n2 = len(_tries)
    at_a = [at for g, _p, _i, at in wakes_svc.wake_rows() if g == "a24"]
finally:
    writes.save = _save1
check("review 2nd: a turn that fails and cannot even be noted on the item is not retried in the next pass (the back-off is kept in memory)", n1 >= 1 and n2 == n1 and "failed_at" not in (mt(24).get("watch") or {}), (n1, n2, mt(24)))
check("review 2nd: …and the wake loop's next moment for it is after the back-off", bool(at_a) and at_a[0] > _pages.zone_now(), at_a)
watching_svc.WATCH_BACKOFF.pop("a24", None)
item(25, wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/91", wait_event="a reply", ask_by=day(9), post_wake_mover=BACK, needs=[], subject="[home] bad stamp")
item(183, wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/96", wait_event="a reply", ask_by=day(9), post_wake_mover=BACK, needs=[], subject="[home] good stamp")
_stamp0 = watching_svc.watch_stamp
def _bad_stamp(gid):
    if gid == "a25": raise RuntimeError("unreadable")
    return _stamp0(gid)
watching_svc.watch_stamp = _bad_stamp
try:
    wakes_svc.anchor_pass()
finally:
    watching_svc.watch_stamp = _stamp0
check("review 2nd: one bad stamp does not abort the minute pass: the other waits are stamped", mt(183).get("watch", {}).get("set_at", 0) >= now0 and "set_at" not in (mt(25).get("watch") or {}), (mt(25), mt(183)))

# --- 11. the exemption for a watcher's ask holds only while the item's watch says it is up
RA = "Decide: has the parcel arrived? · Options: arrived / not yet, ask again on <date> / drop"
check("review 11: a needs=decision item whose ask only looks like a watcher's is nagged for the ask's shape", server._ask_owed({"needs": ["decision"], "ask": RA}) != "", server._ask_owed({"needs": ["decision"], "ask": RA}))
check("review 11: …one the watchers put up is not", server._ask_owed({"needs": ["decision"], "ask": RA, "watch": {"asked": "relay"}}) == "", None)
LINE = "Decide: ship it · Recommend: yes · Stakes: low · By: Mon Nov 2nd"
mm = {"needs": ["decision"], "ask": RA, "next": LINE + "\nteam-back: details"}
note = server._lift_ask(mm)
check("review 11: _lift_ask on a look-alike ask takes the ask-shaped first line of next as the ask", mm.get("ask") == LINE and note != "", (mm, note))
mm = {"needs": ["decision"], "ask": RA, "watch": {"asked": "relay"}, "next": LINE + "\nteam-back: details"}
check("review 11: …and leaves a watcher's own ask up", server._lift_ask(mm) == "" and mm.get("ask") == RA, mm)

# --- 12. smaller
item(190, wait_kind="item", after=["a37"], post_wake_mover=BACK, ask_by=day(9), needs=[], subject="[home] waits on a superseded blocker")
item(37, subject="[home] old blocker"); item(38, status="completed", outcome="done", reason="r", subject="[home] its replacement, already closed")
it = rd(37); it["status"] = "completed"; it["metadata"].update(outcome="superseded", reason="r", superseded_by="a38"); (T / "store/a/37.json").write_text(json.dumps(it))
reset(); wakes_svc.release_after("a37", "superseded", "a38", "home-front")
check("review 12: a superseded blocker whose replacement is closed too: the arrival names the replacement", mt(190).get("mover") == BACK and "a38" in mt(190)["woke"]["what"] and "superseded" in mt(190)["woke"]["what"], mt(190).get("woke"))
item(93, wait_kind="relay", wait_event="the draft", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] one chase, then not yet", chases=[{"at": 1.0, "by": BACK, "note": "a"}])
wakes_svc.wake_pass()
server._answer("a93", "not yet, ask again on <date>", f"on {day(8)}", "answer")
check("review 12: not yet with a new date resets the chases as well", ab_(mt(93)) == day(8) and "chases" not in mt(93) and mt(93).get("wait_kind") == "relay", mt(93))
_anc.save({"projects/alpha": [{"url": A5, "items": ["a39", "a49"], "added": now0, "by": "x"}]})
item(39, wait_kind="anchor", wait_anchor=A5, wait_event="a reply", ask_by=day(9), post_wake_mover=BACK, needs=[], subject="[home] route: watched", watch=WATCHED())
item(49, hold=True, wake=day(9), needs=[BACK], subject="[home] route: held")
nid = _routing.record("projects/alpha", kind="anchor", to=U["home-stew"], label="github anchor", who="someone", text="a reply on PR 79", anchor="github:o/r#79", pilot=True)
reply = _wt_route._route(nid, "passed", to=BACK, reason="for the builder", sender="home-stew")
check("review 12: _route's reply says a watched item turned to its mover, and a held one was released from hold", "a39 turned to team-back" in reply and "a49 waited on this anchor and is released from hold" in reply and "a39 waited" not in reply, reply)
item(196, wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/97", wait_event="a reply", ask_by=day(9), post_wake_mover=BACK, needs=[], project="projects/beta", subject="[home] pre-filter", watch={"set_at": now0 - 56})
_read0, _since = _routing.read, []
def _read_spy(project, since=0.0, *a, **k):
    _since.append((project, since)); return _read0(project, since, *a, **k)
_routing.read = _read_spy
try:
    wakes_svc.anchor_pass()
finally:
    _routing.read = _read0
check("review 12: the minute pass reads the routing log from the oldest floor of the watched waits, not a week back", any(p == "projects/beta" and s >= now0 - 56 - 1 for p, s in _since) and not any(p == "projects/beta" and s < now0 - 56 - 1 for p, s in _since), _since)
_anc.save({"projects/alpha": [{"url": AURL, "items": None, "added": now0, "by": "x"}]})

# ================================================================ the example config documents the switches
ex = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("config: the example documents [model] watchers and pause", re.search(r"(?m)^watchers = true", ex) and re.search(r"(?m)^pause = false", ex), None)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
