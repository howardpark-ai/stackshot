"""Scenario test for the screen a queued notice passes before delivery (stackshot/fleet/stale_notice.py) — fixture data, no live store, no network, no server.

The rule: a stall, wake, wait-ended or hand-off notice that waited in a queue is dropped when it is no longer true (its item closed, was parked again or has
another mover), when it is older than [client] stale_notice_hours, and when a newer one says the same; a notice that is still true is delivered, and a message
another session wrote is never touched.

Covers: 1. the shapes the screen recognizes (and the ones it leaves alone); 2. the screen itself: a closed item, a re-parked item, a moved item, a duplicate and an
over-age line each dropped, a still-true line kept, an unreadable item kept, the config key and its 0; 3. the per-session push queue (`push.flush`): stale lines
dropped before anything is sent, the rest sent as one turn, a queue of stale lines removed, and a queue for a session that is not live pruned; 4. the inbox
(`inbox.take`): stale lines dropped and their files removed, a line that waits past the cutoff for nobody removed, a session's message left waiting.

    tests/run-suite stale_notice        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stalenotice-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("base_url", "https://stackshot.test")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^ui_open = (true|false)", "ui_open = false", toml); assert n == 1
toml, n = re.subn(r"(?m)^allowed_emails = .*$", 'allowed_emails = ["you@example.com"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", ANCHOR_PUSH_SOURCE="msg", PUSH_INBOX_WAIT="0")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
for d in ("store/g", "state", "secrets", "brain/projects"): (T / d).mkdir(parents=True)
(T / "names.tsv").write_text("# hostname\tfleet\tletter\nbox-a\ttestbox\ta\n")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.core import config as cfg
from stackshot.fleet import inbox, push, stale_notice as sn
from stackshot.model import model as _model
pathlib.Path(push.A).mkdir(parents=True, exist_ok=True)      # the hub state directory the push queue lives in

NOW = 1_800_000_000.0
H = 3600.0
B = "board" + "#"                                                                     # the shown form of an item id, built so no literal id stands in this file
def put_item(n, status="open", **meta):
    (T / "store/g" / f"{n}.json").write_text(json.dumps({"id": f"g{n}", "status": status, "subject": f"item {n}", "metadata": meta}), encoding="utf-8")
BUILDER, MAIN = "box-a-builder", "box-a-main"
put_item(1, phase="alive", mover=BUILDER, needs=[])                                  # open, the builder's: every "still yours" notice about it is true
put_item(2, status="completed")                                                       # closed since
put_item(3, phase="waiting", hold=True, mover=BUILDER, wake="2099-01-01")             # parked again since
put_item(4, phase="alive", mover=MAIN, needs=[])                                      # another mover now
put_item(5, phase="alive", mover=MAIN, needs=[BUILDER])                               # another mover, but the builder is named in its needs
put_item(6, phase="alive")                                                            # no stored mover: the screen cannot tell, so it keeps the line
put_item(7, phase="waiting", mover=BUILDER, after=["g1"])                             # waiting behind another item: "still after" is that wait's own wording
put_item(8, phase="alive", mover=BUILDER, needs=[])
put_item(9, phase="alive", mover=MAIN, then=BUILDER)                                  # the builder takes it after: still its notice
put_item(10, phase="alive", mover="gone-session", needs=[])                          # the queue key of the pane that is not live below

OWNER = _model.owner_display()
put_item(11, phase="alive", mover=OWNER, needs=["decision"])                         # the owner moves it: its notices go to the project's builder, who is neither its mover, its then nor in its needs
put_item(12, phase="alive", mover="none", needs=[])                                   # no one moves it
put_item(13, phase="alive", mover="other-session", then=MAIN, needs=["decision"])     # a different session moves it, the builder is nowhere in it
put_item(14, phase="alive", hold=True, mover=BUILDER, needs=[])                       # held, though its phase is not "waiting"

def stall(n): return f"[stackshot] you have had no turn running for 10 minutes and this is still yours: {B}{n} item {n} (proj). Work it, hand it on or close it. → https://board.example/items/{n}"
def woke(n): return f"[stackshot] {B}{n} woke (wake 2026-11-07T09:00), back in its lane (your call, by its needs): item {n} (proj). It comes to you as its mover: act on it"
def yours(n): return f"[stackshot] {B}{n} is yours now: its wake 2026-11-09T10:00 came. item {n} → https://board.example/items/{n}"
def ended(*ns): return "[stackshot] 2 items are yours now, their waits ended:\n" + "\n".join(f"- {B}{n}: its wait ended. item {n}" for n in ns)
def untaken(n): return f"[stackshot] a hand-off of yours was not taken: {B}{n} item {n} (proj) was handed to a pane that has no turn running"
def came(n): return f"[stackshot] it came to you: {B}{n} item {n} (proj): the session it was handed to did not take it"
def row(text, age_h=0.1, **kw): return {"text": text, "ts": NOW - age_h * H, "from": "stackshot", **kw}

# ================================================================= 1. what the screen recognizes
kinds = {"stall": stall(1), "wake": woke(1), "wake ": yours(1), "wake  ": ended(1, 2), "handoff-sender": untaken(1), "handoff": came(1)}
for k, t in kinds.items():
    check(f"classify: {k.strip()} notice", sn.classify(t)[0] == k.strip(), sn.classify(t))
check("classify: a front agent's mark before the head is read", sn.classify("[for the owner] " + stall(1))[0] == "stall")
check("classify: the items it names, once each, as shown", sn.classify(ended(1, 2)) == ("wake", [f"{B}1", f"{B}2"]), sn.classify(ended(1, 2)))
check("classify: an item it is only queued behind is not what it is about", sn.classify(f"[stackshot] {B}7 woke (wake 2026-11-07): still after {B}1, {B}9, out of the queue until it closes")[1] == [f"{B}7"])
check("classify: a message another session wrote is no notice (even with the same words)", sn.classify("[stackshot message] from box-a-main\n" + stall(1))[0] == "")
check("classify: an anchor notice and plain text are no notice", sn.classify("[anchor] 2 queued earlier") == ("", []) and sn.classify("hello") == ("", []))

# ================================================================= 2. the screen
def screened(rows, rec=(BUILDER,), **kw):
    keep, dropped = sn.screen(rows, list(rec), now=NOW, **kw)
    return keep, {rows.index(r): w for r, w in dropped}
rows = [row(stall(1)), row(stall(2)), row(woke(3)), row(stall(4)), row(stall(5)), row(stall(6)), row(woke(1), age_h=7), row(untaken(2)), row(yours(9))]
keep, why = screened(rows)
check("screen: a still-true stall notice is kept", rows[0] in keep and 0 not in why, why)
check("screen: a closed item's notice is dropped", why.get(1) == "its item is closed", why)
check("screen: a re-parked item's wake notice is dropped", why.get(2) == "its item was parked again", why)
check("screen: a notice about an item another session moves is dropped", why.get(3) == "its item has another mover now", why)
check("screen: …unless the recipient is named in its needs, or is its then", rows[4] in keep and rows[8] in keep, why)
check("screen: an item with no stored mover keeps its notice (it cannot be told)", rows[5] in keep, why)
check("screen: a notice past the cutoff is dropped, whatever its item says", why.get(6) == "older than 6 hours", why)
check("screen: a hand-off that was not taken is dropped when its item closed", why.get(7) == "its item is closed", why)
keep, why = screened([row(untaken(4))])
check("screen: …but not for a mover that is not the recipient (it is the sender who is told)", len(keep) == 1 and not why, why)
keep, why = screened([row(untaken(3))])
check("screen: …nor for a parked item (the sender is still told the hand-off failed)", len(keep) == 1 and not why, why)
keep, why = screened([row(f"[stackshot] {B}7 woke (wake 2026-11-07): still after {B}1, out of the queue until it closes")])
check("screen: a wake that says the item is still queued behind another is true while it waits", len(keep) == 1 and not why, why)
keep, why = screened([row(yours(7))])
check("screen: …and the same item without that wording, parked again, is dropped", not keep and why.get(0) == "its item was parked again", why)
keep, why = screened([row(ended(2, 3))])
check("screen: a batch whose items have all gone stale is dropped", not keep and 0 in why, why)
keep, why = screened([row(ended(2, 1))])
check("screen: a batch with one item still true is delivered whole", len(keep) == 1 and not why, why)
keep, why = screened([row(stall(99))])
check("screen: an item the store does not hold keeps its notice", len(keep) == 1 and not why, why)

keep, why = screened([row(woke(11)), row(stall(11)), row(woke(12)), row(stall(12))])
check("screen: an item the owner moves, or no one, keeps its notices of every kind for the project's builder (the model sends them to it, the screen cannot tell)", len(keep) == 4 and not why, (keep, why))
keep, why = screened([row(woke(13)), row(stall(13))])
check("screen: an item a different session moves still drops its notices (the owner check is not a blanket keep)", not keep and set(why.values()) == {"its item has another mover now"}, (keep, why))
keep, why = screened([row(woke(14))])
check("screen: an item with a hold is parked again whatever its phase says", not keep and why.get(0) == "its item was parked again", (keep, why))
x, y, z = row(stall(1), age_h=3), row(stall(1), age_h=2, **{"from": "x"}), row(stall(1), age_h=1)
keep, why = screened([x, y, z])
check("screen: of three notices that say the same only the newest is kept, the two older ones collapse into it", keep == [z] and why == {0: "a newer notice says the same", 1: "a newer notice says the same"}, (keep, why))
bad = {"text": stall(1), "t": "x"}
keep, why = screened([bad])
check("screen: a line whose time is no number is kept (its age is unreadable)", keep == [bad] and not why, (keep, why))
check("screen: …and is not expired", sn.expired(bad, now=NOW) is False and sn.expired({"text": stall(1), "ts": []}, now=NOW) is False)
keep, why = sn.screen([row(stall(4)), row(woke(3)), row(stall(2))], [], now=NOW)
check("screen: with no recipient named, a moved item's notice is kept (there is nothing to compare), a parked or closed one is still dropped", [r["text"] for r in keep] == [stall(4)] and len(why) == 2, (keep, why))

a, b, c = row(stall(1), age_h=3), row(stall(8), age_h=2), row(stall(1), age_h=1)
keep, why = screened([a, b, c])
check("screen: of two notices about the same item the newest is kept, the older collapses into it", keep == [b, c] and why == {0: "a newer notice says the same"}, (keep, why))
keep, why = screened([row(stall(1)), row(woke(1))])
check("screen: a stall and a wake notice about one item are two different notices", len(keep) == 2 and not why, why)
keep, why = screened([row(stall(1), age_h=5.9)])
check("screen: just inside the cutoff is delivered", len(keep) == 1, why)
keep, why = screened([row(stall(1), age_h=500)], hours_=0)
check("screen: a cutoff of 0 turns the expiry off", len(keep) == 1 and not why, why)
keep, why = screened([row(stall(2), age_h=500)], hours_=0)
check("screen: …the state checks stay", not keep and why.get(0) == "its item is closed", why)
old_msg = row(f"[stackshot message] from box-a-main · 2026-10-14 18:04\n{B}2 is done", age_h=900)
keep, why = screened([old_msg])
check("screen: a session's message is never dropped, however old or whatever it names", keep == [old_msg] and not why, why)
cfg.CFG.setdefault("client", {})["stale_notice_hours"] = 1
keep, why = screened([row(stall(1), age_h=2)], hours_=None)
check("screen: [client] stale_notice_hours sets the cutoff", not keep and "older than 1 hours" in why.get(0, ""), why)
cfg.CFG["client"]["stale_notice_hours"] = "soon"
check("screen: a value that is no number is the default", sn.hours() == sn.DEFAULT_HOURS)
cfg.CFG["client"]["stale_notice_hours"] = -3
check("screen: a negative value is the default", sn.hours() == sn.DEFAULT_HOURS)
cfg.CFG["client"].pop("stale_notice_hours"); check("screen: unset is the default, 6 hours", sn.hours() == 6.0)
check("screen: a recipient is compared by name whatever the case, with no registry to read", sn.screen([row(stall(1))], [BUILDER.upper()], now=NOW)[0] != [])
check("screen: the example config sets the key to the default", re.search(r"(?m)^stale_notice_hours = 6 ", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)

# ================================================================= 3. the push queue
Q = pathlib.Path(push.Q)
sent = []
push.resolve = lambda name: "sock"; push.send = lambda sock, text: sent.append(text) or True
def qrows(name, rows):
    Q.mkdir(parents=True, exist_ok=True)
    (Q / f"{name}.jsonl").write_text("".join(json.dumps({"t": time.time() - r[1] * H, "text": r[0], "from": "stackshot"}) + "\n" for r in rows), encoding="utf-8")
qrows(BUILDER, [(stall(1), 3), (stall(2), 2), (woke(3), 2), (stall(1), 1), (yours(1), 8), (f"[stackshot message] from box-a-main\nplease look at {B}2", 900)])
rc = push.flush(BUILDER)
text = sent[-1] if sent else ""
check("flush: the queue is delivered", rc == 0 and len(sent) == 1, (rc, sent))
check("flush: …as one turn of what is still true: the newest stall notice and the session's message", text.startswith("[stackshot] 2 queued earlier:\n") and text.count(stall(1)) == 1 and f"please look at {B}2" in text, text)
check("flush: …without the closed item's, the parked item's, the older duplicate's and the over-age line", f"{B}2 item" not in text and f"{B}3" not in text and "is yours now" not in text, text)
check("flush: the queue file is gone once sent", not (Q / f"{BUILDER}.jsonl").exists())
sent.clear()
qrows(BUILDER, [(stall(2), 1), (woke(3), 1)])
rc = push.flush(BUILDER)
check("flush: a queue of stale lines sends nothing, and its file is removed", rc == 0 and sent == [] and not (Q / f"{BUILDER}.jsonl").exists(), (rc, sent))
push.resolve = lambda name: ""
qrows("gone-session", [(stall(2), 1), (stall(10), 30), (stall(10), 1)])
rc = push.flush("gone-session")
left = [json.loads(l)["text"] for l in (Q / "gone-session.jsonl").read_text().splitlines()] if (Q / "gone-session.jsonl").exists() else None
check("flush: a session that is not live keeps the lines that are still true, and loses the others", rc == 3 and left == [stall(10)], (rc, left))
push.enqueue("gone-session", stall(1))
check("enqueue: a line is appended to a pruned queue", len((Q / "gone-session.jsonl").read_text().splitlines()) == 2)

push.resolve = lambda name: "sock"; sent.clear()
qrows(BUILDER, [(woke(11), 1), (stall(12), 1), (stall(13), 1)])
rc = push.flush(BUILDER)
text = sent[-1] if sent else ""
check("flush: the owner's and no one's items keep their notices for the builder, a different session's item loses its own", rc == 0 and woke(11) in text and stall(12) in text and stall(13) not in text, (rc, text))
sent.clear()
qrows("", [(stall(4), 1), (stall(2), 1)])
rc = push.flush("")
check("flush: a queue with no session name keeps the moved item's notice (nothing to compare it with) and drops the closed one's", rc == 0 and len(sent) == 1 and stall(4) in sent[0] and stall(2) not in sent[0], (rc, sent))
sent.clear()
qrows(BUILDER, [(stall(1), 3), (stall(1), 2), (stall(1), 1)])
push.flush(BUILDER)
check("flush: three identical notices go out as one", len(sent) == 1 and sent[-1].count(stall(1)) == 1, sent)
import contextlib, io
qrows(BUILDER, [(stall(1), 1), (stall(2), 1)])
out = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
    push.flush(BUILDER)
check("flush: the reason a line was dropped is printed on stdout, where the sender's retry logs it", f"dropped a stale notice for {BUILDER}: its item is closed" in out.getvalue(), out.getvalue())
push.resolve = lambda name: ""

# ================================================================= 4. the inbox
LIVE = {"11111111-1111-4111-8111-111111111111": BUILDER}
U = next(iter(LIVE))
def waiting(): return sorted(p.name for p in (T / "state/inbox/msg").glob("*.json"))
i_ok = inbox.put(BUILDER, stall(1), "msg", now=NOW - 600, sender="stackshot")
i_closed = inbox.put(BUILDER, stall(2), "msg", now=NOW - 500, sender="stackshot")
i_dup_old = inbox.put(BUILDER, woke(8), "msg", now=NOW - 400, sender="stackshot")
i_dup_new = inbox.put(BUILDER, woke(8), "msg", now=NOW - 300, sender="stackshot")
i_msg = inbox.put(BUILDER, f"[stackshot message] from box-a-main\n{B}2 is done", "msg", now=NOW - 900 * H, sender="box-a-main")
i_old_away = inbox.put("box-a-away", stall(1), "msg", now=NOW - 30 * H, sender="stackshot")           # waits for a session that is not live, past the cutoff
i_new_away = inbox.put("box-a-away", stall(1), "msg", now=NOW - 60, sender="stackshot")
tk = inbox.take(LIVE, known={U}, only_src="msg", now=NOW)
ids = tk[0]["ids"] if tk else []
check("take: what is still true and the session's message are handed out together", len(tk) == 1 and set(ids) == {i_ok, i_dup_new, i_msg}, tk)
check("take: the closed item's notice and the older duplicate are not in the text", f"{B}2 item" not in tk[0]["text"] and tk[0]["text"].count(f"{B}8") == 1, tk and tk[0]["text"])
check("take: they are removed, not only skipped", not any(f"{i}.json" in waiting() for i in (i_closed, i_dup_old)), waiting())
check("take: a notice that waited past the cutoff for a session that is not live is removed", f"{i_old_away}.json" not in waiting(), waiting())
check("take: a fresh one for that session keeps waiting", f"{i_new_away}.json" in waiting(), waiting())
inbox.ack(ids)
check("take: the confirmed lines go, the one for the absent session stays", waiting() == [f"{i_new_away}.json"], waiting())
i_msg_old = inbox.put("box-a-away", f"[stackshot message] from box-a-main\n{B}2 is done", "msg", now=NOW - 900 * H, sender="box-a-main")
inbox.take(LIVE, known={U}, only_src="msg", now=NOW)
check("take: a session's old message keeps waiting for its session (no expiry for it)", f"{i_msg_old}.json" in waiting(), waiting())
i_all = inbox.put(BUILDER, stall(3), "msg", now=NOW - 60, sender="stackshot")
check("take: a session whose every line is stale is handed nothing", inbox.take(LIVE, known={U}, only_src="msg", now=NOW) == [] and f"{i_all}.json" not in waiting(), waiting())

U2 = "22222222-2222-4222-8222-222222222222"                                    # a live session with no name
i_own = inbox.put(U2, woke(11), "msg", now=NOW - 60, sender="stackshot")
i_mv = inbox.put(U2, stall(13), "msg", now=NOW - 50, sender="stackshot")
tk = inbox.take({U2: ""}, known={U2}, only_src="msg", now=NOW)
check("take: a session with no name is handed the owner-moved item's notice and loses the other session's", len(tk) == 1 and tk[0]["ids"] == [i_own] and f"{i_mv}.json" not in waiting(), (tk, waiting()))
inbox.ack(tk[0]["ids"] if tk else [])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
