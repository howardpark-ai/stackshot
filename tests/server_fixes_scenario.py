"""tests/server_fixes_scenario.py: the server files four kinds of item wrongly written itself, and says what was wrong (server_fixes.py).

Four facts-only fixes, each with the audit message or refusal it retires. A fixed write goes through, the fix is a line in History ("stackshot: ..."), and the reply (or, for a fix made by the
ten-minute pass, one message to the mover) says what was wrong. A mover who disagrees sends that fix back and the server leaves the field alone. Never by the server: closing an item, writing an
ask, changing an item the owner moves. Checked against a scratch store and config (no port, no real server, no model call):

  1  wake_park     the write that parks a wake which is the whole of the mover's wait (server `_date_only_wait`) is a History line and records the fix; clear_hold sends it back and neither the write nor the
                   pass parks that wake again (a different wake is a new fact); the ten-minute pass parks the same shape set in the store (server `_wake_park` through audit_run.Env.wake_park) and tells the
                   mover once, so the why-not-now finding for it is no longer sent; a run with no writer (the command line, --dry-run) still lists the finding
  2  front_mover   another session's mover, then or post_wake_mover set to a front agent becomes the project's builder, with the reply and History saying so; sending the same value again keeps it as sent;
                   a project with no builder is refused as before; the sender naming itself, the owner and a background agent are as they were
  3  wait_reason   a hold with a wake and no reason, whose own next or description says what it waits for on the wake's day, takes that line as its wait_basis (the snooze refusal it retired); the mover's
                   own wait_basis is used as given; with no loose reason the refusal stands, and an item waiting on the owner is never fixed
  4  settled_pick  a quoted span or a pick the owner already made is no wait on him: board_report's mislabeled-state check and the server's hold note stay quiet, a present wait on him is still found
  5  never         the fixes close nothing, write no ask and leave an item the owner moves as it was
  6  review        no wait reason for an item the owner moves; the pass's park is the server's own save; the front-mover mark is bound to its sender and a day; a negated or awaited pick still waits on him;
                   no park for a front agent's item

    tests/run-suite server_fixes        -> exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="dateonlywait-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-echo-main")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY, HOUR = 86400.0, 3600.0
ZONE_OFFSET = 4 * HOUR                       # the instance timezone (Asia/Dubai, "timezone" above): UTC+4, no DST
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}},
                                                  "projects/echo": {"title": "Echo", "name": "Echo", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0,
                                                                    "agents": {"home-echo-main": "the front"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", su=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC if desc is None else desc, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.service import gates; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web.tools import create as _wt_create; from stackshot.web.tools import update as _wt_update; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR; from stackshot.waits import dated_wait as DW; from stackshot.model import model as MODEL
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.front_sender = lambda who: False
BACK = "team-back"
def bupd(i, **kw): return server._update(f"a{i}", sender=BACK, **kw)
def stamped(i): return (mt(i).get("phase"), mt(i).get("waits_on"))
local_day = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%d")
w2 = local_day(now0 + 2 * DAY)
PARK = "(parked: wake"
SN_HEAD = "alone is a wait until that date, and this item's only open next line"
TIMED = f"{BACK}: at 08:00 run the nightly check and report"

from stackshot.waits import server_fixes as SF; from stackshot.tools import board_report as BR
from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR
OWN = server.OWNER
log = lambda i: [e["text"] for e in ((mt(i).get("stall") or {}).get("log") or [])]
w3 = local_day(now0 + 3 * DAY)
FRONT, BUILD, OTHER = "home-front", "team-back", "home-other"
fm_marked = lambda meta: any(e.startswith(f"mover={FRONT}|") for e in SF.mark_tokens(meta, SF.FRONT_MOVER))      # the front_mover mark is bound to the sender and a time

# ================================================================ 1. wake_park
item(101, needs=[BACK], next="")
out = bupd(101, next=TIMED, wake=f"{w2}T08:00", wait_reason="the nightly job writes the report at 08:00")
check("1 the write parks it, as before", out.count(PARK) == 1 and hd_(mt(101)) is True, out)
check("1 History: one line in the item's log, naming the wake and the way out", len(log(101)) == 1 and "parked" in log(101)[0] and f"{w2}T08:00" in log(101)[0] and "clear_hold" in log(101)[0], log(101))
check("1 …and the fix is recorded for that wake", SF.marked(mt(101), SF.WAKE_PARK, f"{w2}T08:00"), mt(101).get(SF.MARK))
out = bupd(101, clear_hold=True, next=f"{BACK}: write the report now")
check("1 the mover who disagrees sends it back with clear_hold: released, and the wake is recorded as declined", not hd_(mt(101)) and SF.declined(mt(101), SF.WAKE_PARK, f"{w2}T08:00") and not SF.marked(mt(101), SF.WAKE_PARK, f"{w2}T08:00"), mt(101))
out = bupd(101, next=TIMED, wake=f"{w2}T08:00")
check("1 …and the same wake with the same kind of step is not parked again (the date is stored as until and no hold)", PARK not in out and "hold" not in mt(101) and wk_(mt(101)) == f"{w2}T08:00", (out[-300:], mt(101)))
out = bupd(101, next=TIMED, wake=f"{w3}T08:00", wait_reason="the nightly job writes the report at 08:00")
check("1 …a different wake is a new fact and is parked", out.count(PARK) == 1 and hd_(mt(101)) is True, (out[-300:], mt(101)))

# the ten-minute pass
H = 3600; now = time.time()
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900
wake_f = lambda ts: dt.datetime.fromtimestamp(ts + ZONE_OFFSET, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M")
def aitem(i, wake_in_h=6.0, nxt=None, mover="team-back", **kw):
    w = wake_f(now + wake_in_h * H)
    nxt = f"{mover}: at {w[-5:]} run the nightly check and report" if nxt is None else nxt
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open", "updated": now - H, "written_at": now - H, "written_by": mover,
         "state_updated": now - H, "confirmed": now - H,
         "metadata": {"owner": U["home-front"], "project": "projects/alpha", "state": "doing", "needs": [mover], "next": nxt, "wake": w, **kw}}
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
    return f"a{i}", d
ROLES = {"team-back": {"role": "background"}, "ops-other": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, sessions=lambda: None,
                             pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, **kw)
shape = dict([aitem(9031), aitem(9071)])
fs, _f = AC.filing_findings(shape, {}, now, env())
check("1 (as before) the check itself still finds the shape, for a run that cannot write", sorted(re.sub(r"\D", "", f["id"]) for f in fs if f["category"] == "why-not-now") == ["9031", "9071"], fs)
dry = AR.filing_pass(now=now, items=shape, anchors={}, env=env(wake_park=server._wake_park), dry=True)
check("1 --dry-run lists them and parks nothing", dry["findings"] == 2 and not hd_(mt(9031)) and not sent, (dry, sent))
r0 = AR.filing_pass(now=now, items=shape, anchors={}, env=env())
check("1 a pass with no writer (the command line) sends the finding as it always did", r0["fresh"] == 2 and sent and "· why-not-now ·" in sent[0][1], (r0, sent))
sent.clear(); (T / "state/audit/filing.json").unlink(missing_ok=True)
w9031 = wk_(mt(9031))
r1 = AR.filing_pass(now=now, items=shape, anchors={}, env=env(wake_park=server._wake_park))
check("1 the pass parks each item itself: on hold with the wake as it was, a wait_basis from the step, stored waiting on a time", all(hd_(mt(i)) is True and wk_(mt(i)) for i in (9031, 9071))
      and "text" in (mt(9031).get("wait_basis") or {}) and stamped(9031) == ("waiting", "time"), (mt(9031), stamped(9031)))
check("1 …History has a line for each, and the fix is recorded", len(log(9031)) == 1 and "parked" in log(9031)[0] and "clear_hold" in log(9031)[0] and SF.marked(mt(9031), SF.WAKE_PARK, w9031), (log(9031), mt(9031).get(SF.MARK)))
check("1 …the why-not-now finding is not sent (the audit message is retired): one short message to the mover says what the server did and how to undo it", r1["fresh"] == 0
      and not [m for m in sent if "· why-not-now ·" in m[1]] and len(sent) == 1 and sent[0][0] == "team-back" and sent[0][2] is True and "clear_hold" in sent[0][1] and all(str(i) in sent[0][1] for i in (9031, 9071)), (r1, sent))
check("1 …the record says what the pass did", [re.sub(r"\D", "", x) for x in r1.get("wake_park", {}).get("parked", [])] == ["9031", "9071"], r1)
sent.clear()
r2 = AR.filing_pass(now=now + 600, items={"a9031": rd(9031), "a9071": rd(9071)}, anchors={}, env=env(wake_park=server._wake_park))
check("1 the next pass finds nothing to do and sends nothing", r2["findings"] == 0 and not sent, (r2, sent))
server._update("a9031", sender="team-back", clear_hold=True, next="team-back: write the report now")
check("1 clear_hold on the pass's park is the mover's no: recorded as declined", SF.declined(mt(9031), SF.WAKE_PARK, w9031) and not hd_(mt(9031)), mt(9031))
back_ = dict([aitem(9031, nxt=f"team-back: at {w9031[-5:]} run the nightly check and report")])
back_["a9031"]["metadata"]["wake"] = w9031; back_["a9031"]["metadata"]["fix_declined"] = {"wake_park": [w9031]}
(T / "store/a/9031.json").write_text(json.dumps(back_["a9031"]))
sent.clear()
r3 = AR.filing_pass(now=now + 1200, items=back_, anchors={}, env=env(wake_park=server._wake_park))
check("1 a declined wake is left alone by the pass: not parked, no finding, no message", not hd_(mt(9031)) and r3["findings"] == 0 and not sent, (r3, sent, mt(9031)))

# ================================================================ 2. front_mover
def fput(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": "open",
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": BUILD, "project": "projects/alpha", "next": f"{BUILD}: carry on", **meta}}))
holder = lambda i: telling.holder(rd(i))
telling.tell_woken = lambda *a, **k: None
def refusal(fn):
    try:
        fn(); return ""
    except Exception as e:  # noqa: BLE001
        return str(e)
fput(201, mover=BUILD, needs=[BUILD])
out = _wt_update.stackshot_update(item_id="a201", sender=OTHER, mover=FRONT, next=f"{BUILD}: carry on")
check("2 another session's mover=<front agent> goes through with the project's builder as mover", "Refused" not in out and holder(201) == BUILD, (out[:300], mt(201)))
check("2 …the reply says what was wrong, names the builder and how to keep the front agent", f"mover={BUILD}" in out and f"mover={FRONT}" in out and "no hand-off notice" in out and "send mover=" in out, out)
check("2 …History has a line naming both, and the fix is recorded", len(log(201)) == 1 and FRONT in log(201)[0] and BUILD in log(201)[0] and fm_marked(mt(201)), (log(201), mt(201).get(SF.MARK)))
out = _wt_update.stackshot_update(item_id="a201", sender=OTHER, mover=FRONT, next=f"{BUILD}: carry on")
check("2 the same value sent again is the mover's no: kept as sent, the front agent is the mover", "Refused" not in out and holder(201) == FRONT and not fm_marked(mt(201)), (out[:300], mt(201)))
check("2 …and the reply says so", "as you sent it" in out, out)
fput(202, mover=OWN, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", then=BUILD, state="your-call")
out = _wt_update.stackshot_update(item_id="a202", sender=OTHER, then=FRONT)
check("2 then=<front agent> becomes the builder; the item the owner moves is otherwise as it was (his mover, his decision, his ask)", "Refused" not in out and mt(202).get("then") == BUILD and mt(202).get("mover") == OWN
      and mt(202).get("needs") == ["decision"] and mt(202).get("ask") == "Decide: a or b - Recommend: a - Stakes: none - By: no date", (out[:300], mt(202)))
DESC2 = "- Goal: A thing\n- It lives here\n- Done when done"
r = _wt_create.stackshot_create(subject="[home] handed to the front", description=DESC2, project="projects/alpha", sender=OTHER, mover=FRONT, next=f"{BUILD}: look at it")
new_gid = re.search(r"created (\w+) ", r).group(1)
new_item = server._load(new_gid)
new_log = [e["text"] for e in ((new_item["metadata"].get("stall") or {}).get("log") or [])]
check("2 create: the same fix; the item is made with the builder as mover and the reply says so", r.startswith("created") and telling.holder(new_item) == BUILD and f"mover={BUILD}" in r and "no hand-off notice" in r, r[:400])
check("2 …History has the line on the new item, and the fix is recorded", any(FRONT in x and BUILD in x for x in new_log) and fm_marked(new_item["metadata"]), (new_log, new_item["metadata"]))
fput(203, mover=FRONT)
out = _wt_update.stackshot_update(item_id="a203", sender=OTHER, mover=FRONT, next=f"{BUILD}: carry on")
check("2 re-sending the mover the item already holds changes nothing and says nothing", holder(203) == FRONT and "no hand-off notice" not in out and not log(203), out[:300])
fput(204, mover=BUILD)
out = _wt_update.stackshot_update(item_id="a204", sender=FRONT, mover=FRONT, next=f"{FRONT}: take it over")
check("2 a front agent naming itself is as it was: no fix, no line", holder(204) == FRONT and not log(204) and "no hand-off notice" not in out, out[:300])
fput(205, mover=BUILD)
out = _wt_update.stackshot_update(item_id="a205", sender=FRONT, mover=OTHER)
check("2 …a background mover set by a front agent", holder(205) == OTHER and not log(205), out[:200])
fput(207, mover=OTHER, project="projects/echo")
msg = refusal(lambda: _wt_update.stackshot_update(item_id="a207", sender=OTHER, mover="home-echo-main", next=f"{OTHER}: x"))
check("2 a project with no builder keeps the refusal, as before (nothing to substitute)", msg.startswith("Refused:") and "no builder and no background agent" in msg and holder(207) == OTHER, (msg, mt(207)))

# ================================================================ 3. wait_reason
item(301, needs=[BACK], next="")
out = bupd(301, hold=True, wake=w2, next=f"{BACK}: collect the logs until {w2}, then review")
check("3 a hold with a wake and no reason, whose own next says what it waits for on that day, goes through", "Refused" not in out and hd_(mt(301)) is True, out[:400])
check("3 …the line is the wait_basis, with the wake it stands for", "collect the logs until" in mt(301)["wait_basis"]["text"] and w2 in mt(301)["wait_basis"]["text"] and mt(301)["wait_basis"]["wake"] == w2, mt(301).get("wait_basis"))
check("3 …the reply says what was missing and what the server took", "wait_basis" in out and "collect the logs until" in out, out)
check("3 …History has a line", len(log(301)) == 1 and "wait reason" in log(301)[0], (log(301), mt(301).get(SF.MARK)))
item(302, needs=[BACK], next=f"{BACK}: carry on", desc=f"- The export is not ready\n- We wait for the vendor's export until {w2}\n- Done when imported")
out = bupd(302, hold=True, wake=w2)
check("3 the loose reason in the description is lifted the same way", "Refused" not in out and hd_(mt(302)) is True and "vendor's export until" in mt(302)["wait_basis"]["text"], (out[:300], mt(302)))
item(303, needs=[BACK], next="")
out = bupd(303, hold=True, wake=w2, wait_basis=f"the export ships the export on {w2}", next=f"{BACK}: collect the logs until {w2}, then review")
check("3 a mover's own wait_basis in the call is used as given (the server leaves the field alone)", mt(303)["wait_basis"]["text"] == f"the export ships the export on {w2}" and not log(303), (mt(303), log(303)))
out = bupd(303, priority="p2")
check("3 …and a later write leaves it alone", mt(303)["wait_basis"]["text"] == f"the export ships the export on {w2}" and not log(303), mt(303))
item(304, needs=[BACK], next="")
msg = refusal(lambda: bupd(304, hold=True, wake=w2, next=f"{BACK}: carry on with the thing"))
check("3 with no loose reason the refusal stands, as before", msg.startswith("Refused:") and "no reason" in msg and not hd_(mt(304)), msg[:300])
item(305, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", mover=OWN, state="your-call", next=f"{OWN}: pick one")
msg = refusal(lambda: bupd(305, hold=True, wake=w2, next=f"{OWN}: pick one, we wait until {w2}"))
check("3 an item that waits on the owner is never fixed (a hold beside his decision is refused as before)", msg.startswith("Refused:") and not hd_(mt(305)) and not log(305), (msg[:300], mt(305)))

# ================================================================ 4. settled_pick
names = SF.owner_names()
o = (server._cfg.owner_names() or [OWN])[0]      # a name the board report matches (the instance's alias); the server's own hold note matches server.OWNER
settled = lambda t: SF.settled_out(t, names)
check("4 a quoted span and a past pick are blanked, a present wait is not", o not in settled(f"{o} picked A") and "decides" not in settled(f'He wrote "wait until {o} decides"')
      and f"waiting on {o}" in settled(f"waiting on {o}") and settled("a b") == "a b", (settled(f"{o} picked A"), settled(f'He wrote "{o} decides"')))
def item_br(i, text):
    wake = wake_f(now + 3 * 86400)
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open", "updated": now - H, "state_updated": now - H, "confirmed": now - H, "written_at": now - H, "written_by": "team-back",
         "metadata": {"owner": U["home-front"], "project": "projects/alpha", "state": "parked", "hold": True, "needs": ["team-back"], "wake": wake, "next": "team-back: look at it later",
                      "wait_basis": {"text": text, "wake": wake, "by": "team-back", "at": now - H}}}
    return f"a{i}", d
def br(text):
    gid, d = item_br(8000, text)
    return [k for k, _ in BR.check_item(d, gid, {gid: d}, {}, now)]
check("4 (as before) a hold whose words wait on the owner's decision is mislabeled", "mislabeled-state" in br(f"{o}'s decision on the vendor comes after {w2}") and "mislabeled-state" in br(f"waiting on {o} until {w2}"), None)
check("4 a hold that records a pick the owner already made is not", "mislabeled-state" not in br(f"the export ships {w2}; {o} picked option A on the board") and "mislabeled-state" not in br(f"the export ships {w2}; {o} has approved the release"), br(f"the export ships {w2}; {o} picked option A"))
check("4 …nor one that quotes his words", "mislabeled-state" not in br(f'the export ships {w2}; his answer was "{o} approves B"') and "mislabeled-state" not in br(f"the export ships {w2}; his note, 'waiting on {o} was over'"), None)
check("4 …but a pick recorded beside a present wait on him is still found", "mislabeled-state" in br(f"{o} picked A; waiting on {o} for the date, after {w2}"), None)
note_q = server._form_notes(parked=True, meta={"next": f'{BACK}: his answer was "wait until {server.OWNER} decides"; carry out A'}, gid="a1")
note_p = server._form_notes(parked=True, meta={"next": f"{BACK}: wait until {server.OWNER} decides"}, gid="a1")
check("4 the server's hold note is quiet for a quoted past answer and still speaks for a present wait on him", "waits on" not in note_q and "waits on" in note_p, (note_q, note_p))

# ================================================================ 5. never by the server
sent.clear()
aitem(9100, mover=OWN, needs=["decision"], ask="Decide: a or b - Recommend: a - Stakes: none - By: no date", nxt=f"{OWN}: at 08:00 pick one", state="your-call")
raw_ = (T / "store/a/9100.json").read_bytes()
res_ = server._wake_park("a9100", now)
check("5 the pass does not park an item the owner moves: byte for byte as it was", res_.get("parked") is False and (T / "store/a/9100.json").read_bytes() == raw_, (res_, mt(9100)))
_k, d9 = aitem(9101, nxt="team-back: at 08:00 run it"); d9["status"] = "completed"; (T / "store/a/9101.json").write_text(json.dumps(d9))
check("5 …nor a closed item", server._wake_park("a9101", now).get("parked") is False and rd(9101)["status"] == "completed", rd(9101))
fixed_ids = (101, 201, 202, 301, 302, 9071)
check("5 no fix closed an item or wrote an ask: every item the fixes touched is still open, and none carries an ask it was not given",
      all(rd(i)["status"] == "open" for i in fixed_ids) and all(not mt(i).get("ask") for i in fixed_ids if i != 202), None)
check("5 the fix keys are the server's bookkeeping: a write that changes only them is no re-park", SF.MARK in gates._REPARK_QUIET and SF.DECLINED in gates._REPARK_QUIET, None)


# ================================================================ 6. the review's fixes
# 6.1 an item the owner moves: a session's hold with a wake and a next line is refused as before, and nothing is written
item(401, mover=OWN, state="your-step", needs=[], next=f"{OWN}: collect the logs until {w2}, then review")
raw_ = (T / "store/a/401.json").read_bytes()
msg = refusal(lambda: bupd(401, hold=True, wake=w2))
check("6.1 a session's hold on an item the owner moves (state your-step) stays refused", msg.startswith("Refused:"), msg[:300])
check("6.1 …and the item is byte for byte as it was", (T / "store/a/401.json").read_bytes() == raw_, mt(401))
item(402, mover=OWN, state="your-call", needs=[], next=f"{BACK}: collect the logs until {w2}, then review")
raw_ = (T / "store/a/402.json").read_bytes()
msg = refusal(lambda: bupd(402, hold=True, wake=w2))
check("6.1 …also with the owner as mover and a next line that is the session's own", msg.startswith("Refused:") and (T / "store/a/402.json").read_bytes() == raw_, (msg[:300], mt(402)))

# 6.2 the pass's park is the server's own save: no writer, so the author, the activity clock and a pending answer are as they were
_k, d_ = aitem(9200)
d_["written_by"] = "someone-else"; d_["activity"] = now - 5 * H; (T / "store/a/9200.json").write_text(json.dumps(d_))
server._answers_save({"a9200": {"told": [server._session_id(BACK)], "kind": "decision"}})
before_ = rd(9200)
res_ = server._wake_park("a9200", now)
after_ = rd(9200)
check("6.2 the pass parks it", res_.get("parked") is True and hd_(after_["metadata"]) is True and "text" in (after_["metadata"].get("wait_basis") or {}), (res_, after_["metadata"]))
check("6.2 …written_by and written_at are as they were", after_.get("written_by") == "someone-else" and after_.get("written_at") == before_.get("written_at"), (before_.get("written_by"), after_.get("written_by")))
check("6.2 …the activity clock did not move", before_.get("activity") and after_.get("activity") == before_.get("activity"), (before_.get("activity"), after_.get("activity")))
check("6.2 …and the pending answer record is still there", "a9200" in server._answers_load(), server._answers_load())
check("6.2 …with the History line and the record", len(log(9200)) == 1 and "parked" in log(9200)[0] and SF.marked(mt(9200), SF.WAKE_PARK, str(wk_(before_["metadata"]))), (log(9200), mt(9200)))

# 6.3 the front_mover mark is bound to the session whose write was fixed, and lasts a day
fput(210, mover=BUILD, needs=[BUILD])
out = _wt_update.stackshot_update(item_id="a210", sender=OTHER, mover=FRONT, next=f"{BUILD}: carry on")
check("6.3 the first send is substituted and marked for its sender", holder(210) == BUILD and fm_marked(mt(210)), (out[:200], mt(210).get(SF.MARK)))
fput(211, mover=BUILD, **{SF.MARK: {SF.FRONT_MOVER: [SF.bind(f"mover={FRONT}", server._session_id(OTHER) or OTHER, time.time())]}})
out = _wt_update.stackshot_update(item_id="a211", sender=BACK, mover=FRONT, next=f"{BUILD}: carry on")
check("6.3 an unrelated session after another's token is substituted, not waved through", holder(211) == BUILD and "as you sent it" not in out, (out[:300], mt(211)))
fput(212, mover=BUILD, **{SF.MARK: {SF.FRONT_MOVER: [SF.bind(f"mover={FRONT}", server._session_id(OTHER) or OTHER, time.time() - 2 * DAY)]}})
out = _wt_update.stackshot_update(item_id="a212", sender=OTHER, mover=FRONT, next=f"{BUILD}: carry on")
check("6.3 …and the same session after a stale token (two days) is substituted again", holder(212) == BUILD and "as you sent it" not in out, (out[:300], mt(212)))
fput(213, mover=BUILD, **{SF.MARK: {SF.FRONT_MOVER: [SF.bind(f"mover={FRONT}", server._session_id(OTHER) or OTHER, time.time() - 2 * HOUR)]}})
out = _wt_update.stackshot_update(item_id="a213", sender=OTHER, mover=FRONT, next=f"{BUILD}: carry on")
check("6.3 …while the same session within the day sending it again is kept as sent", holder(213) == FRONT and "as you sent it" in out, (out[:300], mt(213)))

# 6.4 a negation, a waiting word before the name and his name alone in quotes still wait on him
check("6.4 'wait until <owner> has not yet decided' is still a wait on him", o in settled(f"wait until {o} has not yet decided") and o in settled(f"{o} hasn't decided"), settled(f"wait until {o} has not yet decided"))
check("6.4 'parked until <owner> confirmed or rejected' is still a wait on him", o in settled(f"parked until {o} confirmed or rejected") and o in settled(f"waiting on {o} picked one"), settled(f"parked until {o} confirmed or rejected"))
check("6.4 a quoted <owner> name alone ('blocked on <owner> approval') is the name, not a quoted answer", o in settled(f"blocked on '{o}' approval") and server._waits_on_owner(f"blocked on '{server.OWNER}' approval"), settled(f"blocked on '{o}' approval"))
check("6.4 …the readers find them: the board report calls each hold mislabeled", all("mislabeled-state" in br(f"{t} (after {w2})") for t in (f"wait until {o} has not yet decided", f"parked until {o} confirmed or rejected", f"blocked on '{o}' approval")), None)
check("6.4 (as before) a past pick with nothing waiting before it is still blanked", o not in settled(f"the export ships; {o} has approved it") and o not in settled(f"{o} picked A"), None)

# 6.5 the pass parks nothing whose mover is a front agent: the finding stands and the item is as it was
_k, d_ = aitem(9210, mover="alpha-main")
raw_ = (T / "store/a/9210.json").read_bytes()
parked_calls = []
sent.clear()
r_ = AR.filing_pass(now=now, items={"a9210": rd(9210)}, anchors={}, env=env(wake_park=lambda g, n: parked_calls.append(g) or {"parked": False}))
check("6.5 the pass does not call the park for a front agent's item", not parked_calls and (T / "store/a/9210.json").read_bytes() == raw_, (parked_calls, r_, sent))
fs_, _f = AC.filing_findings({"a9210": rd(9210)}, {}, now, env())
check("6.5 …and the finding for it is still raised", any(f["category"] == "why-not-now" for f in fs_), fs_)

# 6.7 the wait-end fix is one of the server's fixes (wait_end_scenario holds its cases); a send-back unmarks and declines only the kinds it names
check("6.7 wait_end is one of the fixes", SF.WAIT_END == "wait_end" and SF.WAIT_END in SF.FIXES)
meta_ = {}
SF.mark(meta_, SF.WAIT_END, "item:board#" "1|aaaaaaaa"); SF.mark(meta_, SF.WAIT_END, "pr:o/r#7|bbbbbbbb")
server._wait_end_sent_back(meta_, ("item",))
check("6.7 a send-back of the item kind unmarks and declines only that kind", SF.declined(meta_, SF.WAIT_END, "item:board#" "1|aaaaaaaa") and not SF.marked(meta_, SF.WAIT_END, "item:board#" "1|aaaaaaaa")
      and SF.marked(meta_, SF.WAIT_END, "pr:o/r#7|bbbbbbbb") and not SF.declined(meta_, SF.WAIT_END, "pr:o/r#7|bbbbbbbb"), meta_)

# 6.6 nothing left of the dead pieces
check("6.6 the unused front-mover gate is gone", not hasattr(server, "_gate_front_mover"), None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": server fixes scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
