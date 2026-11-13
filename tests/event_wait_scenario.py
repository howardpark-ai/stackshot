"""Scenario test for waits on a fleet event (event_waits.py, wait_kind=event) — fixture data, no live store, no network, no server socket.

An item whose mover waits in the background for something the fleet does (a release running, a PR's merge, a recycle, a fleet op, a job's run) used to read as idle after ten minutes, got nagged by the stall
pass and was finally raised to the owner. An event wait is stored, watched by code and woken by the event. Covered:

  * the pure half: the phrases (parse, canonical text, a bare #n resolved against this repository), what matches what (a recycle's machine, a fleet op's verb, `many` only over more than one session),
    the words, the report a machine posts (event_from_report), the watchers' reading of it (can_end, watches, due at its backstop).
  * the write: a canonical phrase is stored and the reply says what is watched; a phrase that is no event, a pr_released for another repository, a PR already live and a PR already merged are refused;
    a backstop is required (the write guard); a create takes it too.
  * the wake: a release (`_released`, as release.sh posts it) turns the item that waits for it to its post-wake mover, told in one line what happened, and leaves another PR's wait alone; a recycle
    (`_recycled`) turns a recycle wait (its machine, or any) and a fleet op wait for its verb; POST /client/event turns a fleet op wait for `many` only when the report covers more than one session, a job wait by
    its name, refuses a report that names no op; a reported event older than the wait is not its arrival; the catch-up poll finds a merge or a release nobody was told of, and a PR closed unmerged;
    the backstop day brings the item back with "the event did not come".
  * the clocks: a watched event wait is waiting in the model (no mover), the stall pass does not look at it, and a recycle wait is not counted by /client/recycle-wanted.
  * the display: the item page and the home line say what it waits on, who watches it and its backstop.
  * client.py event posts the report and prints what woke.

    tests/run-suite event_wait      → exit 0 / 1"""
import contextlib, datetime, io, json, os, re, sys, pathlib, time, logging
BID_A = 9154
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="eventwaittest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n\n## Current state\n\nthe state.\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, subject=None, project="projects/alpha", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner or U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
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
from stackshot.web import server; from stackshot.service import writes; from stackshot.model import model; from stackshot.waits import watchers as wk; from stackshot.waits import event_waits as EW; from stackshot.web import render; from stackshot.web import itempage; from stackshot.waits import stall as S; from stackshot.service import create as create_svc
REAL_MERGED_PRS, REAL_GIT_COMMIT = server._merged_prs, server._git_commit      # before the checks below swap them for tables
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
SENT: list[tuple[str, str, str, str]] = []
server._tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK, FRONT = "team-back", "home-front"
UB = U["team-back"]
CFG = server._cfg.CFG.setdefault("model", {})
def cfg(**kw):
    for k, v in kw.items(): CFG[k] = v
cfg(guards=False, watchers=True, pause=False)
def sent(tag=None): return [x for x in SENT if tag is None or x[3] == tag]
def reset(): SENT.clear()
REPO = "example-owner/stackshot"
server._OWN_REPO[:] = [REPO]
PR = lambda n: f"{REPO}#{n}"

# ================================================================ the pure half
P = EW.parse
check("parse: every form, the machine and the verb kept, case and spaces forgiven", P("pr_released 7") == EW.Spec("pr_released", "#7") and P("PR_MERGED  o/r#12") == EW.Spec("pr_merged", "o/r#12")
      and P("pr_merged https://github.com/O/R/pull/12") == EW.Spec("pr_merged", "o/r#12") and P("recycle") == EW.Spec("recycle", "", "") and P("recycle box-1") == EW.Spec("recycle", "", "box-1")
      and P("fleet_op many") == EW.Spec("fleet_op", "many", "") and P("fleet_op Lane box-1") == EW.Spec("fleet_op", "lane", "box-1") and P("job_run nightly") == EW.Spec("job_run", "nightly"), [P(x) for x in ("pr_released 7", "fleet_op Lane box-1")])
for bad in ("", "soon", "pr_released", "pr_released abc", "pr_released o/r", "recycle a b", "fleet_op", "fleet_op 1x", "fleet_op a b c", "job_run", "job_run a b", "release 7"):
    check(f"parse: {bad!r} is no event, and the message names the forms", bool(EW.problem(bad)) and (bad.split(" ")[0] not in EW.KINDS and "|" in EW.problem(bad) or bad.split(" ")[0] in EW.KINDS), EW.problem(bad))
check("resolved: a bare PR number is this repository's, run through the moved table; another repository's stays; the others come back as they are",
      EW.resolved(P("pr_released 7"), "Owner/Repo", lambda r: r.lower()) == EW.Spec("pr_released", "owner/repo#7") and EW.resolved(P("pr_merged X/y#3"), "o/r", lambda r: r.lower()) == EW.Spec("pr_merged", "x/y#3")
      and EW.resolved(P("recycle"), "") == P("recycle"), None)
refused("resolved: a bare number with no repository of its own is refused", lambda: EW.resolved(P("pr_released 7"), ""), "no GitHub repository")
check("text and words: the canonical phrase and the person's reading", EW.text(P("fleet_op many box-1")) == "fleet_op many box-1" and EW.words("pr_released o/r#7") == "PR #7 live (o/r)" and EW.words("pr_merged #7") == "PR #7 merged"
      and EW.words("recycle box-1") == "the next recycle of box-1" and EW.words("fleet_op many") == "the next fleet op over more than one session" and EW.words("fleet_op lane") == "the next fleet lane"
      and EW.words("job_run nightly") == "the next run of job nightly" and EW.words("garbage in") == "garbage in", [EW.words(x) for x in ("pr_released o/r#7", "fleet_op many")])
ev = EW.event
check("matches: a PR by its key, a recycle by machine (any when the wait names none), a fleet op by verb / any / many (needs a count over one) and machine, a job by name",
      EW.matches(P("pr_released o/r#7"), ev("pr_released", "o/r#7")) and not EW.matches(P("pr_released o/r#7"), ev("pr_released", "o/r#8")) and not EW.matches(P("pr_released o/r#7"), ev("pr_merged", "o/r#7"))
      and EW.matches(P("recycle"), ev("recycle", machine="box-1")) and EW.matches(P("recycle box-1"), ev("recycle", machine="box-1")) and not EW.matches(P("recycle box-2"), ev("recycle", machine="box-1"))
      and EW.matches(P("fleet_op lane"), ev("fleet_op", verb="lane")) and not EW.matches(P("fleet_op lane"), ev("fleet_op", verb="update")) and EW.matches(P("fleet_op any"), ev("fleet_op", verb="x"))
      and EW.matches(P("fleet_op many"), ev("fleet_op", verb="update", sessions=3)) and not EW.matches(P("fleet_op many"), ev("fleet_op", verb="update", sessions=1)) and not EW.matches(P("fleet_op many"), ev("fleet_op", verb="update"))
      and EW.matches(P("fleet_op lane box-1"), ev("fleet_op", machine="box-1", verb="lane")) and not EW.matches(P("fleet_op lane box-1"), ev("fleet_op", machine="box-2", verb="lane"))
      and EW.matches(P("job_run nightly"), ev("job_run", name="nightly")) and not EW.matches(P("job_run nightly"), ev("job_run", name="weekly")), None)
check("arrival: the event's own words, else a plain line", EW.arrival(ev("pr_released", "o/r#7")) == "PR #7 is live" and EW.arrival(ev("recycle", machine="box-1", result="partial")) == "a recycle finished on box-1 (partial)"
      and EW.arrival(ev("fleet_op", verb="lane", sessions=4)) == "fleet op lane finished, 4 sessions" and EW.arrival(ev("job_run", name="nightly")) == "job nightly ran" and EW.arrival(ev("recycle", what="the  words")) == "the words", None)
rep = EW.event_from_report
check("report: a fleet op needs its verb, a job its name, a count is a whole number, the kind is one a machine reports",
      rep({"kind": "fleet_op", "verb": "Lane", "sessions": "5", "machine": "box-1", "text": "done"})["sessions"] == 5 and rep({"kind": "job_run", "name": "nightly"})["name"] == "nightly" and rep({"kind": "recycle"})["kind"] == "recycle", None)
for body, want in (({"kind": "pr_released"}, "kind is one of"), ({"kind": "fleet_op"}, "names the op"), ({"kind": "job_run"}, "names the job"), ({"kind": "fleet_op", "verb": "x", "sessions": "many"}, "whole number"),
                   ({"kind": "fleet_op", "verb": "x", "sessions": -1}, "whole number"), ({"kind": "recycle", "machine": "a b"}, "not a machine name")):
    refused(f"report: {body} is refused", lambda body=body: rep(body), want)

W = lambda **m: {"status": "open", "metadata": {"wait_kind": "event", **m}}
check("watchers: an event wait with a real phrase and a backstop can be ended and is watched; one with a bad phrase, none or no backstop is not (it keeps the old mechanisms); off with [model] watchers",
      wk.watches(W(wait_event="recycle", ask_by=day(3))) and wk.watches(W(wait_event="recycle", wake=day(3))) and not wk.watches(W(wait_event="recycle")) and not wk.watches(W(wait_event="whenever", ask_by=day(3))) and not wk.watches(W(ask_by=day(3))) and wk.stored_kind({"wait_kind": "event"}) == "event" and "event" in model.WAIT_KINDS, None)
check("watchers: the backstop (ask_by or wake) is the only date the clock reads for an event wait; before it nothing is due", wk.due(W(wait_event="recycle", ask_by=day(-1)), now0) == "backstop"
      and wk.due(W(wait_event="recycle", ask_by=day(3)), now0) == "" and wk.due(W(wait_event="recycle", wake=day(-1)), now0) == "backstop" and wk.due(W(wait_event="recycle"), now0) == ""
      and wk.next_moment({"wait_kind": "event", "ask_by": day(3)}) == wk.day_epoch(day(3)), None)

# ================================================================ the model reads it as waiting
item(1, wait_kind="event", wait_event=f"pr_released {PR(7)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 7's release")
m1 = server._model_of({**rd(1), "gid": "a1"})
check("model: a stored event wait is waiting, with no mover, the event and its post-wake mover", m1.state == model.WAITING and m1.wait is not None and m1.wait.kind == "event" and m1.wait.event == f"pr_released {PR(7)}"
      and m1.wait.post_wake_mover == BACK and not m1.mover and not any("conflict" in str(c).lower() for c in (getattr(m1, "conflicts", None) or [])), (m1.state, m1.wait, m1.mover, getattr(m1, "conflicts", None)))
check("clocks: the stall pass has no work to look at (not due), and the item is watched, so the idle clock skips it", S.not_due({**rd(1), "gid": "a1"}, now0) != "" and wk.watches(rd(1)), S.not_due({**rd(1), "gid": "a1"}, now0))
check("clocks: …whereas the same item as plain work is due for the stall pass", S.not_due({**rd(1), "metadata": {k: v for k, v in mt(1).items() if k not in ("wait_kind", "wait_event", "ask_by", "post_wake_mover")} | {"mover": BACK}, "gid": "a1"}, now0) == "", None)
page = itempage.wait_what(m1.wait)
check("display: the item page says what it waits on, who watches it and the backstop word", page == "PR #7 live (example-owner/stackshot)" and itempage.watched_by("event") == "the server" and itempage.wait_end_label(m1.wait) == "backstop", page)

# ================================================================ the write
CAN = {"example-owner/stackshot#7": "x"}
item(10, mover=BACK, subject="[home] doing, will wait for a release")
out = server._update("a10", sender=BACK, wait_kind="event", wait_event="pr_released 7", ask_by=day(5), post_wake_mover=BACK, mover="none")
check("write: an event wait is stored in its canonical form (a bare number is this repository's) and the reply says what the server watches",
      mt(10).get("wait_kind") == "event" and mt(10).get("wait_event") == f"pr_released {PR(7)}" and "event wait: the server watches for PR #7 live" in out and "The stall pass does not run for it" in out, (mt(10), out[-500:]))
check("write: …the wait is stamped (watch.set_at), so an older reported event is not its arrival", (mt(10).get("watch") or {}).get("set_at"), mt(10))
refused("write: a phrase that is no event is refused with the forms", lambda: server._update("a10", sender=BACK, wait_kind="event", wait_event="when it is done", ask_by=day(5), post_wake_mover=BACK), "not an event the server watches", "pr_released")
refused("write: pr_released for another repository is refused (release.sh releases this one only); pr_merged is the event", lambda: server._update("a10", sender=BACK, wait_kind="event", wait_event="pr_released other/repo#3", ask_by=day(5), post_wake_mover=BACK),
        "pr_released is release.sh's event", "pr_merged other/repo#3")
server._released_live_base = lambda: ("goodsha", "headsha")
server._merged_prs = lambda head, limit=3000: {9: ("sha9", now0 - 3600)}
server._released_is_live = lambda sha, good, head: ""
refused("write: a PR already merged and live is refused (nothing would ever report it)", lambda: server._update("a10", sender=BACK, wait_kind="event", wait_event="pr_released 9", ask_by=day(5), post_wake_mover=BACK), "already merged and live")
MERGED, DEAD = {PR(9) if False else "o/r#9": True}, {"o/r#4": "its pull request was closed without being merged"}
from stackshot.core import ghbudget as _gbud
GH_TAGS = []
def fake_pr_merged(ref, now, gh_st):
    ref = server._check_ref(ref); GH_TAGS.append(_gbud.current())      # the ledger tag in force while the PR is read
    rec = {"merged": MERGED.get(ref, False), "err": "", "next": now + 300}
    if ref in DEAD: rec["dead"] = DEAD[ref]
    gh_st[ref] = rec
    return rec["merged"], ""
REAL_PR_MERGED = server._pr_merged
server._pr_merged = fake_pr_merged
refused("write: a PR already merged is refused for pr_merged", lambda: server._update("a10", sender=BACK, wait_kind="event", wait_event="pr_merged o/r#9", ask_by=day(5), post_wake_mover=BACK), "already merged")
refused("write: a PR closed without merging is refused", lambda: server._update("a10", sender=BACK, wait_kind="event", wait_event="pr_merged o/r#4", ask_by=day(5), post_wake_mover=BACK), "closed without being merged")
before = rd(10)
out = server._update("a10", sender=BACK, next="team-back: keep going")
check("write: an unrelated update of the item keeps the wait as stored (the gate reads only a changed wait)", mt(10).get("wait_event") == f"pr_released {PR(7)}" and mt(10).get("wait_kind") == "event", mt(10))
cfg(guards=True)
item(11, mover=BACK, subject="[home] doing, no backstop")
out_ = server._update("a11", sender=BACK, wait_kind="event", wait_event="recycle", post_wake_mover=BACK, mover="none")
check("write: an event wait with no backstop day is not refused: until is taken (the item's words, else tomorrow) and the reply says so", mt(11).get("until") and "wait_kind=event came with no date" in out_ and "ask_by" not in mt(11), (out_[-300:], mt(11)))
refused("write: …and a phrase the guard cannot read as an event", lambda: server._update("a11", sender=BACK, wait_kind="event", wait_event="soonish", ask_by=day(4), post_wake_mover=BACK, mover="none"), "event")
cfg(guards=False)
n, g = None, None
try:
    g, out = create_svc.create_item(subject="[home] filed waiting on a recycle", description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: nothing until the recycle", goal="Done when the recycle ran.",
                                 wait_kind="event", wait_event="recycle testbox", ask_by=day(4), post_wake_mover=BACK, mover="none", request_id="evw-create-1")
except Exception as e:
    out = f"ERR {e}"
check("create: an item can be filed already waiting on an event, its phrase canonical and the reply saying what is watched", g and server._load(g)["metadata"].get("wait_kind") == "event" and server._load(g)["metadata"].get("wait_event") == "recycle testbox" and "event wait:" in out, out[-400:])
refused("create: …and a create for an event that already happened is refused", lambda: create_svc.create_item(subject="[home] filed waiting on a live PR", description=DESC, project="projects/alpha", owner=U["home-front"],
        next="team-back: nothing", goal="Done when it is live.", wait_kind="event", wait_event="pr_released 9", ask_by=day(4), post_wake_mover=BACK, mover="none", request_id="evw-create-2"), "already merged and live")
server._merged_prs = lambda head, limit=3000: {}

# ================================================================ the wake: a release
for i in (20, 21, 22):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
item(20, wait_kind="event", wait_event=f"pr_released {PR(13)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 13")
item(21, wait_kind="event", wait_event=f"pr_released {PR(14)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 14")
item(22, wait_kind="event", wait_event=f"pr_merged {PR(13)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 13's merge")
reset()
server._git_commit = lambda ref: "f" * 40 if ref else ""
server._merged_prs = lambda head, limit=3000: {13: ("a" * 40, now0 - 600)}
server._released_live_base = lambda: ("b" * 40, "c" * 40)
server._released_is_live = lambda sha, good, head: ""
r = server._released(f"https://github.com/{REPO}/pull/13", sha="f" * 40)
check("release: the item that waits for the PR's release turns alive with its post-wake mover, with what happened", mt(20).get("mover") == BACK and "wait_kind" not in mt(20) and "PR #13 is live" in mt(20)["woke"]["what"], mt(20))
check("release: …told in one line", len([x for x in sent("watch") if x[0] == "a20"]) == 1 and sent("watch")[0][1] == UB and "PR #13 is live" in sent("watch")[0][2], sent())
check("release: …a wait for the merge of the same PR is over too (a release is a merge), another PR's wait is not", mt(22).get("mover") == BACK and mt(21).get("wait_kind") == "event" and "a21" not in [x[0] for x in sent("watch")], (mt(22), mt(21)))
check("release: …a release again does nothing more", server._evwait_report(EW.event("pr_released", PR(13))) == [] and len(sent("watch")) == 2, sent())
from stackshot.waits import handoff as HO
check("release: …and the event wake records the hand-off to the post-wake mover, from the server (the record follows the mover: none open names anyone else)",
      (mt(20).get("handoff") or {}).get("to") == BACK and (mt(20).get("handoff") or {}).get("from") == "stackshot" and not HO.stale(rd(20), BACK, server._ho_same), mt(20))

# ================================================================ the wake: the catch-up poll
reset()
server._merged_prs = lambda head, limit=3000: {15: ("d" * 40, now0 - 300)}
item(23, wait_kind="event", wait_event=f"pr_released {PR(15)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] missed release")
item(24, wait_kind="event", wait_event="pr_merged o/r#9", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] merge on GitHub")
item(25, wait_kind="event", wait_event="pr_merged o/r#4", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] PR closed unmerged")
item(26, wait_kind="event", wait_event="pr_merged o/r#5", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] not yet")
server._EVW_LAST[0] = 0.0
fired = server._evwait_tick()
check("poll: a release nobody was told of (the merge is in last-good and HEAD) is found; a merge GitHub reports is found; a PR closed unmerged brings the item back saying it will never merge",
      set(fired) == {"a23", "a24", "a25"} and mt(23).get("mover") == BACK and "PR #15 is live" in mt(23)["woke"]["what"] and mt(24).get("mover") == BACK and mt(25).get("mover") == BACK and "never merge" in mt(25)["woke"]["what"], (fired, mt(23), mt(25)))
check("poll: …a PR still open keeps its wait, and the poll runs at most once a minute", mt(26).get("wait_kind") == "event" and server._evwait_tick() == [], mt(26))

# ================================================================ the wake: recycle, fleet op, job
for i in (30, 31, 32, 33, 34, 35):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
item(30, wait_kind="event", wait_event="recycle", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] any recycle")
item(31, wait_kind="event", wait_event="recycle othermachine", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] another machine's recycle")
item(32, wait_kind="event", wait_event="fleet_op many", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] a many-session op")
item(33, wait_kind="event", wait_event="fleet_op recycle", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] a recycle op")
reset()
server._recycled("testbox", "recycle", started=now0 - 120, result="ok", skipped=[], flag_at=now0 - 120)
check("recycle: the end-of-recycle hook turns a recycle wait (any machine) and a fleet op wait for that verb; another machine's recycle wait and a many-session wait are not touched (the hook does not know the count)",
      mt(30).get("mover") == BACK and "a recycle finished on testbox" in mt(30)["woke"]["what"] and mt(33).get("mover") == BACK and mt(31).get("wait_kind") == "event" and mt(32).get("wait_kind") == "event", (mt(30), mt(31), mt(32), mt(33)))
check("recycle: …each woken item's mover is told (several items in one pass are one message)", {g for x in sent("watch") for g in x[0].split(",")} >= {"a30", "a33"} and all(x[1] == UB for x in sent("watch")), sent())
# an item whose wait was set after a reported event: not its arrival
item(34, wait_kind="event", wait_event="recycle", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] set just now", su=now0 + 60.0)
check("floor: a reported event older than the wait (the item was written after it) is not its arrival", server._evwait_report(EW.event("recycle", machine="testbox"), now=now0) == [] and mt(34).get("wait_kind") == "event", mt(34))
check("floor: …a later one is", server._evwait_report(EW.event("recycle", machine="testbox"), now=now0 + 120) == ["a34"] and mt(34).get("mover") == BACK, mt(34))

from starlette.testclient import TestClient
from stackshot.fleet import client
tok = open(client.mint("testbox")).read().strip()
reset()
with TestClient(server.mcp.http_app()) as c:
    h = {"Authorization": "Bearer " + tok}
    res = c.post("/client/event", json={"kind": "fleet_op", "verb": "update", "sessions": 1}, headers=h)
    check("route: a fleet op over one session does not end a `many` wait", res.status_code == 200 and res.json()["woken"] == [] and mt(32).get("wait_kind") == "event", (res.status_code, res.text))
    res = c.post("/client/event", json={"kind": "fleet_op", "verb": "update", "sessions": 6, "text": "sala update finished on 6 sessions"}, headers=h)
    check("route: …one over six sessions does, and the item's mover is told what the report said", res.status_code == 200 and res.json()["woken"] == [server._gh.shown("a32")] and mt(32).get("mover") == BACK
          and "sala update finished on 6 sessions" in mt(32)["woke"]["what"], (res.status_code, res.text, mt(32)))
    item(35, wait_kind="event", wait_event="job_run nightly", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] a job")
    res = c.post("/client/event", json={"kind": "job_run", "name": "weekly"}, headers=h)
    check("route: another job's run does not end it", res.status_code == 200 and res.json()["woken"] == [] and mt(35).get("wait_kind") == "event", res.text)
    res = c.post("/client/event", json={"kind": "job_run", "name": "nightly"}, headers=h)
    check("route: …its own run does", res.status_code == 200 and res.json()["woken"] == [server._gh.shown("a35")] and mt(35).get("mover") == BACK, res.text)
    # a provision op over four sessions, as the fleet tool reports the end of every op
    item(80, wait_kind="event", wait_event="fleet_op provision", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] a provision wait")
    item(81, wait_kind="event", wait_event="fleet_op many", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] a many wait")
    item(82, wait_kind="event", wait_event="fleet_op lane", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] a lane wait")
    res = c.post("/client/event", json={"kind": "fleet_op", "verb": "provision", "sessions": 4, "result": "ok", "text": "provision finished on 4 sessions"}, headers=h)
    check("route: a provision op over four sessions wakes the `fleet_op provision` wait and the `fleet_op many` wait, not the lane wait, and both are told what the report said",
          res.status_code == 200 and sorted(res.json()["woken"]) == sorted(server._gh.shown(g) for g in ("a80", "a81")) and mt(80).get("mover") == BACK and mt(81).get("mover") == BACK
          and mt(82).get("wait_kind") == "event" and "provision finished on 4 sessions" in mt(81)["woke"]["what"], (res.status_code, res.text, mt(80), mt(81)))
    for body, want in (({"kind": "fleet_op"}, "names the op"), ({"kind": "bogus"}, "kind is one of"), ({"kind": "pr_released"}, "kind is one of")):
        res = c.post("/client/event", json=body, headers=h)
        check(f"route: {body} is a 400 that says why", res.status_code == 400 and want in res.json().get("error", ""), res.text)
    res = c.post("/client/event", json={"kind": "recycle"})
    check("route: no token, no write", res.status_code == 401, res.text)
    item(9154, wait_kind="event", wait_event="recycle testbox", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] this machine's recycle")
    res = c.post("/client/event", json={"kind": "recycle"}, headers=h)
    check("route: a report names no machine: the token's machine is used", res.status_code == 200 and "a9154" in str(res.json()["woken"]) or res.json()["woken"] == [server._gh.shown("a9154")], res.text)

# ================================================================ the backstop
item(40, wait_kind="event", wait_event="fleet_op many", ask_by=day(-1), post_wake_mover=BACK, needs=[], subject="[home] the event never came")
reset()
woke = server._watch_pass(now0)
check("backstop: the day passes with no report: the item comes back to its post-wake mover saying the event did not come", "a40" in woke and mt(40).get("mover") == BACK and "the event did not come" in mt(40)["woke"]["what"]
      and "wait_kind" not in mt(40), (woke, mt(40)))
check("backstop: …told in one line", [x[0] for x in sent("watch")] == ["a40"] and "the event did not come" in sent("watch")[0][2], sent())

# ================================================================ /client/recycle-wanted
item(50, wait_kind="event", wait_event="recycle", ask_by=day(5), post_wake_mover=BACK, needs=[], recycle=True, recycle_at=now0, mover=BACK, subject="[home] waits for the next recycle")
item(51, mover=BACK, recycle=True, recycle_at=now0, subject="[home] asks for a recycle")
item(52, wait_kind="event", wait_event="recycle", ask_by=day(5), post_wake_mover=BACK, needs=[], mover=BACK, recycle_at=now0, subject="[home] only waits for the next recycle")
wanted = server._recycle_wanted("testbox")
check("recycle-wanted: an item that asks for a recycle is counted, an event wait that carries the recycle flag too asks the same, one that only waits for the next recycle (no flag) is not",
      "a51" in wanted and "a50" in wanted and "a52" not in wanted, wanted)

# ================================================================ the display
server._cfg.CFG.setdefault("model", {})["watchers"] = True
html = render.Board().item_html("a1") if hasattr(render, "Board") and False else ""
home = server._fmt({**rd(1), "gid": "a1"})
check("get: the model line says what the item waits on", "PR #7 live" in home or "fleet event" in home or "event" in home, home[:600])

# ================================================================ review fixes: the poll looks up only the PRs the waits name, once per commit
for i in (21, 26):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
MERGES = {k: (f"{k:040x}", now0 - 7200) for k in range(100, 1100)}
MERGES[16] = (f"{16:040x}", now0 - 600)
GIT_LOGS, LIVE_CALLS, GH_CALLS = [], [], []
def counting_merged(head, limit=3000):
    GIT_LOGS.append(head); return dict(MERGES)
def counting_live(sha, good, head):
    LIVE_CALLS.append(sha); return "" if sha in LIVE_NOW else f"its merge {sha[:7]} is not in the last-good commit {good[:7]} yet"
LIVE_NOW: set[str] = set()
server._merged_prs = counting_merged; server._released_is_live = counting_live
server._released_live_base = lambda: ("b" * 40, "c" * 40)
server._PROOF_GIT.clear(); server._EVW_SEEN[0] = None
item(60, wait_kind="event", wait_event=f"pr_released {PR(16)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 16")
item(61, wait_kind="event", wait_event=f"pr_released {PR(17)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 17 (not merged)")
reset()
check("poll: a pass with a thousand merges in last-good looks up only the PRs the waits name (one git log, one liveness check)", server._evwait_poll(now0) == [] and len(GIT_LOGS) == 1 and LIVE_CALLS == [MERGES[16][0]], (len(GIT_LOGS), LIVE_CALLS))
n_logs, n_live = len(GIT_LOGS), len(LIVE_CALLS)
server._evwait_poll(now0 + 60); server._evwait_poll(now0 + 120)
check("poll: …a pass with last-good, HEAD and the waits as they were reads no git at all", len(GIT_LOGS) == n_logs and len(LIVE_CALLS) == n_live, (len(GIT_LOGS), LIVE_CALLS))
server._released_live_base = lambda: ("d" * 40, "c" * 40)
LIVE_NOW.add(MERGES[16][0])
check("poll: …last-good moving makes it look again, and the PR that is now live turns its item (the other PR's wait stays)", server._evwait_poll(now0 + 180) == ["a60"] and mt(60).get("mover") == BACK and mt(61).get("wait_kind") == "event"
      and len(GIT_LOGS) == n_logs + 1, (GIT_LOGS, mt(60)))
server._released_live_base = lambda: ("d" * 40, "c" * 40)
GIT_LOGS.clear(); server._EVW_SEEN[0] = None
item(62, wait_kind="event", wait_event=f"pr_released {PR(18)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for PR 18 (closed unmerged)")
DEAD[server._check_ref(PR(18))] = "its pull request was closed without being merged"
reset()
fired = server._evwait_poll(now0 + 240)
check("poll: a pr_released wait on a PR closed without a merge ends with the dead answer, as pr_merged does", "a62" in fired and "never be released" in mt(62)["woke"]["what"] and mt(61).get("wait_kind") == "event", (fired, mt(62)))
server._merged_prs = lambda head, limit=3000: {}
server._released_is_live = lambda sha, good, head: ""
server._PROOF_GIT.clear(); server._EVW_SEEN[0] = None

# ================================================================ review fixes: the catch-up and the early read share _EVW_GH
item(70, wait_kind="event", wait_event="pr_merged o/r#20", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] merge not yet")
server._EVW_GH.clear(); server._EVW_POLLED.clear()
inner = fake_pr_merged
def pr_merged_with_a_racing_write(ref, now, gh_st):
    out = inner(ref, now, gh_st)
    gh_st["o/r#98"] = {"merged": False, "err": "", "next": now + 300}      # the request thread's early read stores a key while the pass runs
    return out
server._pr_merged = pr_merged_with_a_racing_write
try:
    server._evwait_poll(now0 + 300)
    server._evwait_poll(now0 + 600)
finally:
    server._pr_merged = inner
check("race: a key the early read stored while the catch-up ran is not dropped by the catch-up, and nothing raises", "o/r#98" in server._EVW_GH and "o/r#20" in server._EVW_GH and "o/r#20" in server._EVW_POLLED and "o/r#98" not in server._EVW_POLLED, (dict(server._EVW_GH), server._EVW_POLLED))
(T / "store/a/70.json").unlink()
server._evwait_poll(now0 + 900)
check("race: …a key the catch-up read itself is dropped once no wait names it", "o/r#20" not in server._EVW_GH and "o/r#98" in server._EVW_GH, dict(server._EVW_GH))
server._EVW_GH.clear(); server._EVW_POLLED.clear()

# ================================================================ review fixes: the catch-up tells the sessions a step notice reached already
server._merged_prs = lambda head, limit=3000: {90: ("9" * 40, now0 - 60)}
server._released_is_live = lambda sha, good, head: ""
server._released_live_base = lambda: ("e" * 40, "c" * 40)
server._PROOF_GIT.clear(); server._EVW_SEEN[0] = None
item(71, wait_kind="event", wait_event=f"pr_released {PR(90)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] told by a step notice just now")
item(72, wait_kind="event", wait_event=f"pr_released {PR(90)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] told by a step notice long ago")
server._PROOF_TOLD_SID.clear()
server._PROOF_TOLD_SID["a71"] = (UB, time.time())
server._PROOF_TOLD_SID["a72"] = (UB, time.time() - 1000.0)
reset()
fired = server._evwait_poll(now0 + 10)
check("catch-up: an item a step notice told its session about a moment ago turns without a second message; one told long ago is told again", set(fired) == {"a71", "a72"}
      and [g for x in sent("watch") for g in x[0].split(",")] == ["a72"] and "a72" not in server._PROOF_TOLD_SID, (fired, sent(), dict(server._PROOF_TOLD_SID)))
server._PROOF_TOLD_SID.clear()
server._merged_prs = lambda head, limit=3000: {}

# ================================================================ review fixes: the write gate reads before the lock and not on GitHub under it
LOCKED_CALLS = []
def spy_pr_merged(ref, now, gh_st):
    LOCKED_CALLS.append(writes.ITEM_LOCK._is_owned()); return fake_pr_merged(ref, now, gh_st)
server._pr_merged = spy_pr_merged
item(63, mover=BACK, subject="[home] will wait for a merge")
server._EVW_GH.clear()
out = server._update("a63", sender=BACK, wait_kind="event", wait_event="pr_merged o/r#11", ask_by=day(5), post_wake_mover=BACK, mover="none")
check("gate: the pull request is read on GitHub before the item lock is taken, and the gate under the lock makes no GitHub call", LOCKED_CALLS == [False] and mt(63).get("wait_event") == "pr_merged o/r#11", (LOCKED_CALLS, mt(63)))
server._EVW_GH.clear(); LOCKED_CALLS.clear()
item(63, mover=BACK, subject="[home] will wait for a merged PR")
refused("gate: …and a PR the early read found merged is still refused", lambda: server._update("a63", sender=BACK, wait_kind="event", wait_event="pr_merged o/r#9", ask_by=day(5), post_wake_mover=BACK, mover="none"), "already merged")
check("gate: …the read for that refusal was also made outside the lock", LOCKED_CALLS == [False], LOCKED_CALLS)
LOCKED_CALLS.clear(); server._EVW_GH.clear()
try:
    g2, _o = create_svc.create_item(subject="[home] filed waiting on a merge", description=DESC, project="projects/alpha", owner=U["home-front"], next="team-back: nothing", goal="Done when it merged.",
                                 wait_kind="event", wait_event="pr_merged o/r#12", ask_by=day(4), post_wake_mover=BACK, mover="none", request_id="evw-create-3")
except Exception as e:
    g2 = None
check("gate: a create takes the same path (the early read is the tool's, ahead of its lock; create_item (service/create.py) itself reads the cache only)", g2 is not None and all(c is False for c in LOCKED_CALLS), (g2, LOCKED_CALLS))
server._pr_merged = fake_pr_merged

# ================================================================ review fixes: a backstop must be after now; which events are live
item(64, mover=BACK, subject="[home] will wait with a past backstop")
refused("backstop: today's date has already begun (a day falls due at 00:00 in the instance timezone), so it is refused and the reply says why", lambda: server._update("a64", sender=BACK, wait_kind="event", wait_event="recycle", ask_by=day(0), post_wake_mover=BACK, mover="none"),
        "is not after now", "00:00 of that day in the instance timezone")
refused("backstop: …a wake in the past is refused too", lambda: server._update("a64", sender=BACK, wait_kind="event", wait_event="recycle", wake=day(-2), post_wake_mover=BACK, mover="none"), "future")
out = server._update("a64", sender=BACK, wait_kind="event", wait_event="recycle", ask_by=day(1), post_wake_mover=BACK, mover="none")
check("backstop: tomorrow is accepted, and a recycle wait carries no 'nothing tells the server' line", mt(64).get("wait_kind") == "event" and "Nothing tells the server" not in out, out[-400:])
refused("backstop: …moving the stored backstop into the past later is refused as well", lambda: server._update("a64", sender=BACK, ask_by=day(-1)), "is not after now")
out = server._update("a64", sender=BACK, wait_kind="event", wait_event="job_run nightly", ask_by=day(3), post_wake_mover=BACK)
check("live: a wait on an event nothing reports yet (a job run) says so in the reply and names its backstop", "Nothing tells the server of this event yet" in out and day(3) in out, out[-500:])
for ph in ("fleet_op many", "fleet_op provision", "fleet_op lane box-1"):
    out = server._update("a64", sender=BACK, wait_kind="event", wait_event=ph, ask_by=day(3), post_wake_mover=BACK)
    check(f"live: a `{ph}` wait is live, so the reply carries no 'nothing tells the server' line", "Nothing tells the server" not in out and "the fleet tool reports the end of each op" in out, out[-500:])
check("live: …the pure test says which are live (PR kinds, recycle, every fleet_op form) and which are not (job_run)",
      all(EW.live(P(x)) for x in ("pr_released 7", "pr_merged o/r#7", "recycle", "recycle box-1", "fleet_op recycle", "fleet_op reboot", "fleet_op any", "fleet_op many", "fleet_op provision", "fleet_op update box-1", "fleet_op lane")) and not EW.live(P("job_run nightly")), None)
check("live: …the tool text says the same (every fleet_op form live, job_run on its backstop) and that the day starts at 00:00 in the instance timezone", "every fleet_op form" in server._MODEL_FORM and "fleet_op recycle, reboot or any" not in server._MODEL_FORM and "job_run wait turns only on its backstop" in server._MODEL_FORM and "00:00 of that day in the instance timezone" in server._MODEL_FORM, None)

check("alias: the first name of the kind (sala_op) is still read, as a phrase and as a report, and stored as fleet_op", P("sala_op Lane box-1") == EW.Spec("fleet_op", "lane", "box-1") and EW.text(P("sala_op many")) == "fleet_op many"
      and rep({"kind": "sala_op", "verb": "update"})["kind"] == "fleet_op" and "sala" not in EW.FORMS.lower(), None)
_tools = {t.name: t.description for t in __import__("asyncio").run(server.mcp.list_tools())}
check("tool text: create, update and get all name the event wait (the kind, its phrases, the model line); no fleet tool is named in any tool text",
      all("wait_kind=time | anchor | item | relay | event" in _tools[n] and EW.FORMS in _tools[n] for n in ("create", "update")) and "a fleet event (<the event>; backstop <day>)" in _tools["get"]
      and not any(re.search(r"(?i)(?<![a-z0-9])sala(?:mander)?(?![a-z0-9])", d) for d in _tools.values()), [n for n, d in _tools.items() if re.search(r"(?i)(?<![a-z0-9])sala", d)])

_params = {t.name: t.parameters.get("properties", {}) for t in __import__("asyncio").run(server.mcp.list_tools())}
check("tool text: create and update describe the wait_kind and wait_event parameters themselves, the event kind and its phrases included",
      all("time | anchor | item | relay | event" in _params[n]["wait_kind"].get("description", "") and EW.FORMS in _params[n]["wait_event"].get("description", "") for n in ("create", "update")), {n: _params[n].get("wait_kind") for n in ("create", "update")})

# ================================================================ review fixes: an event is matched again under the lock; one notice per session
item(65, wait_kind="event", wait_event="recycle testbox", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] re-matched under the lock", su=now0 + 60.0)
o = {}
check("fire: an event that does not match the wait as it stands under the lock does not turn the item", server._watch_fire("a65", "event", now0 + 10, o, {"what": "x"}, ev=EW.event("recycle", machine="elsewhere")) is False and mt(65).get("wait_kind") == "event" and not o, (mt(65), o))
check("fire: …a reported event older than the wait is not its arrival either", server._watch_fire("a65", "event", now0 + 10, o, {"what": "x"}, ev=EW.event("recycle", machine="testbox")) is False and mt(65).get("wait_kind") == "event", mt(65))
check("fire: …the matching one turns it", server._watch_fire("a65", "event", now0 + 120, o, {"what": "x"}, ev=EW.event("recycle", machine="testbox")) is True and mt(65).get("mover") == BACK, mt(65))
item(66, wait_kind="event", wait_event=f"pr_released {PR(80)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] told by the release already")
item(67, wait_kind="event", wait_event=f"pr_released {PR(80)}", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] not told by the release")
reset()
fired = server._evwait_report(EW.event("pr_released", PR(80)), told={"a66": UB})
check("one notice: an item the release's step notice already told this session about turns without a second message; another item for the same session is told", set(fired) == {"a66", "a67"}
      and [g for x in sent("watch") for g in x[0].split(",")] == ["a67"], (fired, sent()))

# ================================================================ client.py event
sentp = []
def fake_post(what, body, timeout=60.0):
    sentp.append((what, body)); return 200, {"event": "a recycle finished on testbox", "woken": [f"board#{BID_A}"]}
client.post = fake_post
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "event", "--kind", "fleet_op", "--verb", "update", "--sessions", "6", "--text", "done"])
check("client.py event posts the report and prints what it woke", rc == 0 and sentp[-1] == ("event", {"kind": "fleet_op", "verb": "update", "sessions": "6", "text": "done"}) and f"woke board#{BID_A}" in buf.getvalue(), (rc, sentp, buf.getvalue()))
fake_post_err = lambda what, body, timeout=60.0: (400, {"error": "a fleet_op report names the op: verb (lane, provision, update …)"})
client.post = fake_post_err
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "event", "--kind", "fleet_op"])
check("client.py event: a refusal prints its reason and exits 1; no --kind prints the usage", rc == 1 and "names the op" in buf.getvalue(), buf.getvalue())
err = io.StringIO()
with contextlib.redirect_stderr(err): rc = client.main(["client.py", "event"])
check("client.py event with no kind: usage on stderr, exit 1", rc == 1 and "usage: client.py event --kind" in err.getvalue(), err.getvalue())
check("client.py's help names the verb and says how to wait for it", "client.py event --kind recycle|fleet_op|job_run" in client.__doc__ and 'wait_kind="event"' in client.__doc__, None)
# ================================================================ the real reader behind _pr_merged is shared with the done check (pr_state.py)
from stackshot.github import pr_state as _prs
class _Cl:
    repo_id = 0
    def __init__(self): self.calls = []
    def repo_path(self, rest=""): return "/repos/o/r" + rest
    def request(self, method, path, **kw):
        self.calls.append((path, kw.get("etag"), _gbud.current())); return {"state": "open", "merged": False, "merged_at": None}
CL9 = _Cl(); _cg9 = server._check_gh; server._check_gh = lambda repo: CL9
try:
    server._pr_merged = REAL_PR_MERGED; _prs.reset(); server._EVW_GH.clear(); server._EVW_POLLED.clear(); reset()
    item(80, wait_kind="event", wait_event="pr_merged o/r#19", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for a merge")
    server._evwait_preread("event", "pr_merged o/r#19")                                  # the write gate's early read (a request thread)
    t9 = time.time()
    with _gbud.tag("done_check"): ok9 = server._check_eval("pr_merged o/r#19", t9, {})   # the done check asks for the same PR inside the pace
    fired9 = server._evwait_poll(t9 + 1)                                                  # and so does the catch-up (it reads the other waits of the store too: only PR 19 is counted)
    C31 = lambda: [c for c in CL9.calls if c[0].endswith("/pulls/19")]
    check("shared: the early read, a done check and the catch-up on one PR make one read, tagged for the event wait that made it, ETag asked for",
          C31() == [("/repos/o/r/pulls/19", True, "event_wait")] and ok9 == (False, "") and fired9 == [] and mt(80).get("wait_kind") == "event", (CL9.calls, ok9, fired9))
    check("shared: ...the catch-up's memory and the done check's dict hold the same record", server._EVW_GH["o/r#19"]["merged"] is False and server._EVW_GH["o/r#19"] == _prs.known("o/r#19"), (dict(server._EVW_GH), _prs.known("o/r#19")))
    fired9 = server._evwait_poll(t9 + 301)
    check("shared: past the pace the catch-up reads again, once", len(C31()) == 2 and C31()[1][2] == "event_wait" and fired9 == [], CL9.calls)
finally:
    server._check_gh = _cg9; server._pr_merged = fake_pr_merged; _prs.reset(); server._EVW_GH.clear(); server._EVW_POLLED.clear()
    (T / "store/a/80.json").unlink(missing_ok=True)

check("every PR an event wait read on GitHub (the write gate's early read and the catch-up pass) was read under the 'event_wait' ledger tag, and the tag is gone afterwards",
      GH_TAGS and set(GH_TAGS) == {"event_wait"} and _gbud.current() == "", (len(GH_TAGS), set(GH_TAGS), _gbud.current()))

# ================================================================ a [released.repos] repository: a PR is live when its merge is in the sibling checkout's HEAD (real git, a scratch repo)
import subprocess
SIB = "example-owner/sibling"; SC = T / "sib"
SENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": tmp}
def sg(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=SC, env=SENV, capture_output=True, text=True, check=True).stdout.strip()
SC.mkdir(); sg("init", "-q", "-b", "main"); (SC / "f").write_text("0"); sg("add", "f"); sg("commit", "-qm", "base")
for n, br in ((7, "main"), (8, "pending")):      # #7 is merged into main (deployed); #8 is merged on a side branch the checkout has not been moved to
    sg("checkout", "-q", br) if br == "main" else sg("checkout", "-qb", br)
    sg("checkout", "-qb", f"topic{n}"); (SC / "f").write_text(str(n)); sg("commit", "-qam", f"change {n}")
    sg("checkout", "-q", br); sg("merge", "-q", "--no-ff", "-m", f"Merge pull request #{n} from example-owner/topic{n}", f"topic{n}")
sg("checkout", "-q", "main")
server._merged_prs, server._git_commit = REAL_MERGED_PRS, REAL_GIT_COMMIT; server._PROOF_GIT.clear(); server._EVW_SEEN[0] = None
def wgate(phrase): return server._evwait_gate({}, {"wait_kind": "event", "wait_event": phrase, "ask_by": day(5)}, creating=True)
refused("foreign: with no [released.repos] a pr_released for a sibling repository is refused as before, and the refusal says none is configured",
        lambda: wgate(f"pr_released {SIB}#8"), "pr_released is release.sh's event", "none is configured", f"pr_merged {SIB}#8")
server._cfg.CFG["released"] = {"repos": {SIB: {"checkout": str(SC)}}}
try:
    check("foreign: a configured repository's PR that is not live yet is a wait the server stores (the reply says what is watched)", "event wait: the server watches for" in wgate(f"pr_released {SIB}#8"), wgate(f"pr_released {SIB}#8"))
    refused("foreign: …one already live (its merge is in the checkout's HEAD) is refused, as for this repository", lambda: wgate(f"pr_released {SIB}#7"), "already merged and live")
    refused("foreign: …a repository the table does not list is refused, naming the listed one", lambda: wgate("pr_released other-owner/else#3"), "pr_released is release.sh's event", SIB)
    item(90, wait_kind="event", wait_event=f"pr_released {SIB}#8", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for a sibling PR")
    item(91, wait_kind="event", wait_event=f"pr_released {SIB}#7", ask_by=day(5), post_wake_mover=BACK, needs=[], subject="[home] waits for a sibling PR already live")
    DEAD.pop(server._check_ref(f"{SIB}#8"), None); reset()
    fired = server._evwait_poll(now0 + 400)
    check("foreign poll: the PR merged into HEAD turns its wait, the PR whose merge is on another branch does not", "a91" in fired and "a90" not in fired and mt(90).get("wait_kind") == "event" and mt(91).get("mover") == BACK, (fired, mt(91)))
    check("…and the arrival words name the checkout, not main's tests", "in the checkout" in mt(91)["woke"]["what"] and "main's" not in mt(91)["woke"]["what"], mt(91).get("woke"))
    sg("merge", "-q", "--ff-only", "pending")      # the sibling's deploy: its checkout moves to the branch that holds #8
    fired = server._evwait_poll(now0 + 460)
    check("foreign poll: after the checkout moves, the PR that was not live turns its wait", "a90" in fired and mt(90).get("mover") == BACK, (fired, mt(90)))
    server._cfg.CFG["released"] = {"repos": {SIB: {"checkout": "relative/path"}, "not a repo name": {"checkout": str(SC)}, "x/y": "no table"}}
    check("foreign: an entry without an absolute checkout, a key that is no owner/repo and a value that is no table are all ignored, and said", server._cfg.released_repos() == {}
          and len(server._cfg.released_notes()) == 3, (server._cfg.released_repos(), server._cfg.released_notes()))
    server._cfg.CFG["released"] = {"repos": {SIB.upper(): {"checkout": "~/sib-checkout"}}}
    check("foreign: names are lower-cased and ~ is expanded", server._cfg.released_repos() == {SIB: pathlib.Path(os.path.expanduser("~/sib-checkout"))} and server._cfg.released_notes() == [], server._cfg.released_repos())
finally:
    server._cfg.CFG.pop("released", None)
    server._merged_prs, server._git_commit = (lambda head, limit=3000: {}), (lambda ref: "f" * 40 if ref else "")

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
