"""Scenario test for the quick fix after an earlier states audit (quick fix 1a) — fixture data,
no live store, no network, no server socket.

The 7-day cap (waiting.py: a wait runs at most [waiting] cap_days after the item's last move unless his words are recorded for that wake)
wrongly capped two groups of parked items. This covers the two ways out:

A. His own words already in the store. server._record_cap_words records, as metadata.cap_ok for the item's current wake, a sentence the store
   attributes to him (an entry of metadata.answers: a board answer, or his hand-written GitHub comment with its id and url) that reads as a park:
   the quote, where it came from (the answer or comment, its time, the store commit) and the date it covers. It counts as cap_ok (the wake stands
   uncapped, no clock moves), shows in get and on the item page, has a History line, is idempotent, and goes with the wake. It refuses anything
   that is not his: an entry no session's tool could have written (an agent's comment), a GitHub entry without its comment id and url, a
   sentence that does not park ("Approve", "sent"), an answer older than the move that set the wake (the state clock), an entry that is not there, a quote the entry does not say, a said entry (an agent's quote
   of him), a closed item, an item with no wake.
B. A real-world date. update(wait_basis="<what happens> YYYY-MM-DD") lifts the cap for that wake only; refused for a wake within the cap (not
   needed), for an item with no wake date (a hold with no date), for a wake more than 365 days out, for a text of the wrong length, with a date that is not on the calendar, or with no date from the wake day to 30 days after it;
   a later wake drops it (the stored basis is read only for the wake it was given for); clear_wait_basis, clear_wake, clear_hold and a
   close drop it; get and the item page show it; the board's head lists these waits once a week (and every day with basis_weekday = -1).

Follow-ups from the review of that fix (quick fix 1b): the cheap gates (his words, a park) run before the store's history is read, and the history is read
before the item lock is taken, the result being checked again under the lock; an unreadable history (the history tool missing, a timeout, a version that
does not parse, the look-back running out) is waiting.UNREADABLE and refuses with "history unreadable: ask Oliver to answer again on the item", while
"not a checkout" and "no history for this file" keep the 24-hour lead; a wake set, cleared and set again to the same value is paired with the clear.

And the one-time job tools/cap_words.py: its dry run (the default) writes nothing and prints per item what it found; --apply records through the
client API (here routed into the server's own handler), refusing what the server refuses.

    tests/run-suite cap_words        → exit 0 / 1"""
import asyncio, datetime, importlib.util, json, os, re, sys, pathlib, tempfile, time, logging, hashlib
BID_A = 9193
BID_B = 9194
BID_D = 9196
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="capwordstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True, keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the caps on a wake and a due date, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone"), 1)}
now0 = time.time()
DAY = 86400.0
ZONE_OFFSET = 4 * 3600      # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-owner"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.service import writes; from stackshot.waits import waiting as W; from stackshot.github import ghsync
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
from stackshot.web.ui import render as ui_render
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))   # no rollout runway in the way
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
OWNER = server.OWNER
CAP = W.cap_days()

# ================================================================ A. his words already in the store
TS = now0 - 9 * DAY + 5.25
TB = now0 - 9 * DAY      # a base for answer times: after the default state clock (now0 - 10 days)
park = {"ts": TS, "kind": "decision", "text": "park this until Jun 4th", "via": "board"}
item(13, hold=True, wake=day(30), answers=[{"ts": now0 - 12 * DAY, "kind": "decision", "choice": "Approve", "text": "sent", "via": "board"}, park])
check("A: before: a wake a month out has no words recorded behind it", not W.words_of(rd(13)["metadata"]), rd(13)["metadata"])
before = rd(13)
out = server._record_cap_words({"sender": "home-test", "item": "a13", "ts": TS, "quote": "park this until Jun 4th", "commit": "010AC0DZZ"}, "testbox")
m = rd(13)["metadata"]; co = m.get("cap_ok") or {}
check("A: recorded: the reply names the item, the wake, the quote and the source", out["action"] == "set" and wk_(out) == day(30) and out["quote"] == park["text"] and "board" in out["source"], out)
check("A: cap_ok holds the wake it covers, who vouches, the quote and where it came from (the answer and the commit, hex only)",
      wk_(co) == day(30) and co.get("by") == "home-test via a script on testbox" and co.get("quote") == park["text"] and f"{OWNER}'s answer on the board" in co.get("source", "") and "first in store commit 010ac0d" in co["source"], co)
check("A: it counts as cap_ok: his words are on record for that very wake", W.words_of(rd(13)["metadata"]).get("quote") == park["text"], rd(13)["metadata"])
check("A: a filing edit: the state clock and the confirm did not move", rd(13)["state_updated"] == before["state_updated"] and rd(13)["confirmed"] == before["confirmed"], rd(13))
check("A: the answers on the item are as they were", rd(13)["metadata"]["answers"] == before["metadata"]["answers"], rd(13)["metadata"]["answers"])
out2 = server._record_cap_words({"sender": "home-test", "item": "a13", "ts": TS}, "testbox")
check("A: again with the same entry: already, nothing changes", out2["action"] == "already" and rd(13)["metadata"] == m, out2)
g = server.stackshot_get("a13")
check("A: get shows his words behind the wake, with the quote and its source", f"{OWNER}'s words behind the wake {day(30)}: “park this until Jun 4th”" in g and "answer on the board" in g, g)
bd = ui_render.Board(f"{tmp}/store")
ph = bd.item_html("a13")
check("A: the item page shows them in its sidebar", "<dt>His words</dt><dd>park this until Jun 4th" in ph, re.findall(r"<dt>His words</dt>.{0,200}", ph))
server._update("a13", wake=day(3), sender="home-owner")
check("A: a different wake does not keep the old record: his answer on the item (given since it last moved) is recorded again for the new wake, as a time wait's reason",
      rd(13)["metadata"]["cap_ok"]["wake"] == day(3) and rd(13)["metadata"]["cap_ok"]["quote"] == "park this until Jun 4th" and W.words_of(rd(13)["metadata"])["quote"] == "park this until Jun 4th", rd(13)["metadata"])
item(102, hold=True, wake=day(30), cap_ok={"wake": day(31), "by": "his recorded words", "quote": "park this", "source": "x"}, answers=[park])
check("A: words recorded for another wake do not cover this one", not W.words_of(rd(102)["metadata"]), rd(102)["metadata"])

# a GitHub comment of his, by its id
item(17, hold=True, wake=day(30), answers=[{"ts": TS + 1, "kind": "comment", "text": "Postpone this one, nothing urgent", "via": "github", "url": "https://github.com/x/y/issues/1#issuecomment-5", "comment_id": 5}])
out = server._record_cap_words({"sender": "home-test", "item": "a17", "comment_id": 5}, "testbox")
check("A: his hand-written GitHub comment is taken by its comment id", out["action"] == "set" and "comment on GitHub" in out["source"] and "(comment 5, " in out["source"] and rd(17)["metadata"]["cap_ok"]["quote"] == "Postpone this one, nothing urgent", out)
check("A: ...and cap_ok.source names the comment's url, not only its id", "https://github.com/x/y/issues/1#issuecomment-5" in rd(17)["metadata"]["cap_ok"]["source"], rd(17)["metadata"]["cap_ok"])

# an answer older than the item's current wake or hold is no words behind it (the state clock, as _owner_words_on)
item(62, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[{"ts": now0 - 8 * DAY, "kind": "decision", "text": "park this until Jun 4th", "via": "board"},
                                                                {"ts": now0 - 4 * DAY, "kind": "decision", "text": "park it a bit longer", "via": "board"}])
refused("A: with no history, an answer more than 24 hours before the move that set the current wake is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a62", "ts": now0 - 8 * DAY}, "testbox"), "more than 24 hours")
check("A: ...and nothing was recorded", "cap_ok" not in rd(62)["metadata"], rd(62)["metadata"])
out = server._record_cap_words({"sender": "home-test", "item": "a62", "ts": now0 - 4 * DAY}, "testbox")
check("A: an answer given after that move is taken (pairing: since the move)", out["action"] == "set" and rd(62)["metadata"]["cap_ok"]["quote"] == "park it a bit longer", out)
check("A: W.entry_current: at or after the state clock, with half a second of slack, not before it", W.entry_current({"state_updated": 1000.0}, 1000.0, now0) and W.entry_current({"state_updated": 1000.0}, 999.6, now0)
      and not W.entry_current({"state_updated": 1000.0}, 990.0, now0) and not W.entry_current({"state_updated": 1000.0}, "x", now0), None)
it0 = {"state_updated": 100000.0}
check("A: entry_pairs: since the move pairs", W.entry_pairs(it0, 100001.0, now0)[0] and W.entry_pairs(it0, 99999.7, now0)[0], None)
check("A: entry_pairs: earlier, with the previous state change before the answer (nothing between), pairs whatever the lead", W.entry_pairs(it0, 50000.0, now0, prior=40000.0)[0], W.entry_pairs(it0, 50000.0, now0, prior=40000.0))
check("A: entry_pairs: earlier, with a state change between the answer and the move, is refused", not W.entry_pairs(it0, 99000.0, now0, prior=99500.0)[0] and "came after it" in W.entry_pairs(it0, 99000.0, now0, prior=99500.0)[1], W.entry_pairs(it0, 99000.0, now0, prior=99500.0))
check("A: entry_pairs: with no history, 24 hours before pairs and more does not", W.entry_pairs(it0, 100000.0 - 86000, now0)[0] and not W.entry_pairs(it0, 100000.0 - 87000, now0)[0], None)
# the sender is required, and an @ in his words never pings through the mirror's comment
refused("A: a call without a sender is refused", lambda: server._record_cap_words({"item": "a18", "ts": TS}, "testbox"), "sender is required")
notes = []
_save0 = writes.save
writes.save = lambda gid, it, *a, **k: (notes.append(k.get("note") or (a[2] if len(a) > 2 else "")), _save0(gid, it, *a, **k))[1]
item(63, hold=True, wake=day(30), answers=[{"ts": TB + 1, "kind": "decision", "text": "park this until Jun 4th, ask @someone-else", "via": "board"}])
server._record_cap_words({"sender": "home-test @x", "item": "a63", "ts": TB + 1}, "testbox")
writes.save = _save0
check("A: the mirror's note for the record breaks every @ (no one is pinged by his words or the sender)", notes and all(re.search("@(?!\u200b)", n) is None for n in notes) and "@\u200bsomeone-else" in notes[0], notes)

# what must be refused
item(58, hold=True, wake=day(30), answers=[
    {"ts": TB+1, "kind": "comment", "text": "park it until the 4th", "via": "mcp"},                                         # an agent's comment: no tool of a session can write to answers, but if one did, via says so
    {"ts": TB+2, "kind": "comment", "text": "park it until the 4th", "via": "github"},                                      # a GitHub entry without the reader's mark (comment id and url)
    {"ts": TB+3, "kind": "decision", "choice": "Approve", "text": "sent", "via": "board"},                                    # his, but no park
    {"ts": TB+4, "kind": "note", "text": "park it until the 4th", "via": "board"},                                           # not a decision or a comment
    {"ts": TB+5, "kind": "decision", "text": "", "choice": "Approve", "via": "board"},                                        # no text
], said=[{"tag": "Acked-by", "quote": "park it until the 4th", "msg": "11111111-1111-4111-8111-000000000001", "session": U["home-owner"], "checked": True, "ts": now0}])
refused("A: an entry that is not via the board or the GitHub reader (an agent-written comment) is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "ts": TB+1}, "testbox"), "own words")
refused("A: a GitHub entry with no comment id and url is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "ts": TB+2}, "testbox"), "comment id and url")
refused("A: his words that do not park (\"sent\") are refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "ts": TB+3}, "testbox"), "do not park")
refused("A: an entry of another kind is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "ts": TB+4}, "testbox"), "own words")
refused("A: an entry with no text is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "ts": TB+5}, "testbox"), "own words")
refused("A: an entry that is not in the item's answers is refused, whatever the caller says it said",
        lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "ts": 999.0, "quote": "park it until the 4th"}, "testbox"), "holds no answer or comment")
refused("A: a quote with no entry named is refused (the server takes no text from the caller)",
        lambda: server._record_cap_words({"sender": "home-test", "item": "a58", "quote": "park it until the 4th"}, "testbox"), "holds no answer or comment")
item(18, hold=True, wake=day(30), answers=[park])
refused("A: a quote the entry does not say is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a18", "ts": TS, "quote": "park it forever"}, "testbox"), "not what the entry says")
check("A: …and nothing was recorded by the refusals", all("cap_ok" not in rd(i)["metadata"] for i in (58, 18)), (rd(58)["metadata"], rd(18)["metadata"]))
item(19, hold=True, wake=day(30), said=[{"tag": "Acked-by", "quote": "park it until the 4th", "msg": "11111111-1111-4111-8111-000000000001", "session": U["home-owner"], "checked": True, "ts": now0}])
refused("A: a said entry (an agent's quote of him) is not a source: only his answers on the item are", lambda: server._record_cap_words({"sender": "home-test", "item": "a19", "ts": now0}, "testbox"), "holds no answer or comment")
item(21, status="completed", answers=[park], outcome="done")
refused("A: a closed item is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a21", "ts": TS}, "testbox"), "not open")
item(59, answers=[park])
refused("A: an item with no wake date has nothing for his words to cover", lambda: server._record_cap_words({"sender": "home-test", "item": "a59", "ts": TS}, "testbox"), "no wake date")
refused("A: an item that is not there is refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a70", "ts": TS}, "testbox"))
check("A: the owner's GitHub comment (no [author: …] header) is his; one with a session's header is not (ghsync.is_owner_comment)",
      ghsync.is_owner_comment({"user": {"login": "example-owner"}, "body": "park this"}, "example-owner")
      and not ghsync.is_owner_comment({"user": {"login": "example-owner"}, "body": "[author: home-owner · 00000000-0000-4000-8000-000000000001]\nwake set to 2099-06-04"}, "example-owner"), None)
check("A: park_words reads \"postpone\", a Japanese hold and a park, not a bare approval or an address that holds the word",
      W.park_words("i say we postpone for now") and W.park_words("これは来月まで保留にしよう") and W.park_words("keep this parked until jun 4") and not W.park_words("Approve") and not W.park_words("see example.org"), None)

# ================================================================ B. a real-world date
B = lambda n: f"The vendor visits Tue {day(n)} 14:00"
item(22, hold=True, wake=day(30))                                            # stored with no words (like): a wake past the cap
check("B: before: no words and no basis behind the wake", not W.words_of(rd(22)["metadata"]) and not W.basis_of(rd(22)["metadata"]), rd(22)["metadata"])
sc = rd(22)["state_updated"]
out = server._update("a22", wait_basis=B(33), sender="home-owner")
m = rd(22)["metadata"]; wb = m.get("wait_basis") or {}
check("B: on a wake already stored the basis is recorded for that wake: text, wake, who, when", wb.get("text") == B(33) and wk_(wb) == day(30) and wb.get("by") and wb.get("at"), m)
check("B: it lifts the cap for that wake: the basis is read for it", W.basis_of(rd(22)["metadata"]) == B(33), rd(22)["metadata"])
check("B: it is a filing edit: the state clock did not move, and no cap_ok words are claimed", rd(22)["state_updated"] == sc and "cap_ok" not in m, rd(22))
g = server.stackshot_get("a22")
check("B: get shows the wait basis and what it lifts", f"wait basis: {B(33)} (lifts the 7-day cap for the wake {day(30)} only; set by " in g and "waiting:" not in g, g)
ph = ui_render.Board(f"{tmp}/store").item_html("a22")
check("B: the item page shows it in its sidebar", f"<dt>Waits on</dt><dd>{B(33)}</dd>" in ph, re.findall(r"<dt>Waits on</dt>.{0,200}", ph))
# only for its date
d = rd(22); d["metadata"].pop("until", None); d["metadata"]["wake"] = day(31); (T / "store/a/22.json").write_text(json.dumps(d))
check("B: the same item with its wake moved by hand to another date has no basis for it any more (the basis is bound to its wake)", not W.basis_of(rd(22)["metadata"]), rd(22)["metadata"])
d["metadata"].pop("until", None); d["metadata"]["wake"] = day(30); (T / "store/a/22.json").write_text(json.dumps(d))
refused("B: moving the wake to another date past the cap with no words is refused (the cap), and the basis stays on the old wake",
        lambda: server._update("a22", wake=day(31), sender="home-owner"), "at most 7 days", "wait_basis=")
check("B: …still recorded for the old wake", wk_(rd(22)["metadata"]) == day(30) and W.basis_of(rd(22)["metadata"]) == B(33), rd(22)["metadata"])
refused("B: moving the wake to within the cap with no reason is refused (a time wait carries one), and the basis stays on the old wake",
        lambda: server._update("a22", wake=day(5), sender="home-owner"), "no reason", "wait_basis=")
server._update("a22", wake=day(5), wait_basis=f"visit on {day(6)}", sender="home-owner")
check("B: moving the wake to within the cap with a basis of its own binds the new basis to the new wake (a held item takes a basis at any length)", W.basis_of(rd(22)["metadata"]) == f"visit on {day(6)}" and wk_(rd(22)["metadata"]) == day(5), rd(22)["metadata"])
d_ = rd(22); d_["metadata"].pop("wait_basis", None); (T / "store/a/22.json").write_text(json.dumps(d_))      # the next checks start from a held wake with no basis
server._update("a22", wake=day(40), wait_basis=f"visit on {day(41)}", hold=True, sender="home-owner")
check("B: a far wake with a basis in the same call is accepted, and the basis is bound to it", wk_(rd(22)["metadata"]) == day(40) and W.basis_of(rd(22)["metadata"]) == f"visit on {day(41)}", rd(22)["metadata"])
server._update("a22", wake=day(42), wait_basis=f"visit moved to {day(43)}", sender="home-owner")
check("B: …and a later far wake with its own basis replaces it", wk_(rd(22)["metadata"]) == day(42) and W.basis_of(rd(22)["metadata"]) == f"visit moved to {day(43)}", rd(22)["metadata"])
refused("B: clear_wait_basis on a held wake would leave a time wait with no reason: refused", lambda: server._update("a22", clear_wait_basis=True, sender="home-owner"), "no reason")
refused("B: wait_basis=\"none\" the same", lambda: server._update("a22", wait_basis="none", sender="home-owner"), "no reason")
server._update("a22", clear_wait_basis=True, clear_hold=True, sender="home-owner")
check("B: clear_wait_basis with the hold released (no wait is left) drops it, and the wake alone is a backstop again", "wait_basis" not in rd(22)["metadata"] and "hold" not in rd(22)["metadata"], rd(22)["metadata"])
d_ = rd(22); d_["metadata"].update(hold=True, wake=day(42)); (T / "store/a/22.json").write_text(json.dumps(d_))
check("B: …and a stored hold with that wake and no basis has none", not W.basis_of(rd(22)["metadata"]), rd(22)["metadata"])

# refusals
item(23, wake=day(3))
refused("B: a wake under the cap that is no hold (a backstop wake) needs no basis: refused (not needed)", lambda: server._update("a23", wait_basis=B(4), sender="home-owner"), "not needed")
refused("B: …the same when the wake is set in the same call", lambda: server._update("a23", wake=day(6), wait_basis=B(7), sender="home-owner"), "not needed")
item(2020, hold=True, wake=day(3))
server._update("a2020", wait_basis=B(4), sender="home-owner")
check("B: a held wake under the cap takes a basis (a time wait carries a reason at any length)", W.basis_of(rd(2020)["metadata"]) == B(4), rd(2020)["metadata"])
item(28, hold=True, recycle=True, recycle_at=now0)                          # a hold with no date of its own
refused("B: a hold with no date has no wake for a basis to explain: refused", lambda: server._update("a28", wait_basis=B(33), sender="home-owner"), "no wake date")
item(64)
refused("B: …nor an item with no hold or wake, nor hold=true in the same call without a wake", lambda: server._update("a64", hold=True, wait_basis=B(33), sender="home-owner"), "no wake date")
item(29, hold=True, wake=day(30))
refused("B: a reason with no date is a way around the rule: refused", lambda: server._update("a29", wait_basis="waiting for the vendor to answer", sender="home-owner"), "YYYY-MM-DD")
refused("B: a date before the wake day is no basis for waiting until the wake", lambda: server._update("a29", wait_basis=f"vendor answered on {day(10)}", sender="home-owner"), "none of its dates")
refused("B: a text of the wrong length is refused", lambda: server._update("a29", wait_basis=day(33), sender="home-owner"), "12 to 300")
refused("B: clear_wait_basis does not go with a new basis", lambda: server._update("a29", wait_basis=B(33), clear_wait_basis=True, sender="home-owner"), "does not go with")
refused("B: a basis does not go with a call that drops the wake", lambda: server._update("a29", wait_basis=B(33), clear_wake=True, sender="home-owner"), "drops the wake")
check("B: …and nothing was recorded by the refusals", "wait_basis" not in rd(29)["metadata"] and "wait_basis" not in rd(23)["metadata"], (rd(29)["metadata"], rd(23)["metadata"]))
W._cfg.CFG.setdefault("waiting", {})["cap_needs_owner"] = False
refused("B: with the cap switched off ([waiting] cap_needs_owner = false) there is nothing to lift on a backstop wake: refused", lambda: server._update("a23", wait_basis=B(4), sender="home-owner"), "not needed")
server._update("a29", wait_basis=B(33), sender="home-owner")
check("B: …a held wake still takes it: it is the time wait's reason, whatever the cap", W.basis_of(rd(29)["metadata"]) == B(33), rd(29)["metadata"])
W._cfg.CFG["waiting"]["cap_needs_owner"] = True
item(65, hold=True, wake=day(30))
refused("B: a date 31 days after the wake day is outside the window", lambda: server._update("a65", wait_basis=f"vendor answers on {day(61)}", sender="home-owner"), "none of its dates", "30 days")
item(68, hold=True, wake=day(30))
server._update("a68", wait_basis=f"vendor answers on {day(60)}", sender="home-owner")
check("B: a date 30 days after the wake day (a deliberate early check) is accepted", W.basis_of(rd(68)["metadata"]) == f"vendor answers on {day(60)}", rd(68)["metadata"])
server._update("a68", clear_wait_basis=True, clear_hold=True, sender="home-owner")
check("B: W.basis_problem: day 0 and day 30 pass, day 31 and the day before the wake do not", not W.basis_problem("x on 2026-11-09", datetime.date(2026, 11, 9)) and not W.basis_problem("x on 2026-12-09", datetime.date(2026, 11, 9))
      and W.basis_problem("x on 2026-12-10", datetime.date(2026, 11, 9)) and W.basis_problem("x on 2026-11-08", datetime.date(2026, 11, 9)), None)
refused("B: a date that is not on the calendar is refused", lambda: server._update("a65", wait_basis="vendor reply due 2026-02-30", sender="home-owner"), "not a real calendar date")
refused("B: ...even beside a real date in the window", lambda: server._update("a65", wait_basis=f"visit {day(31)} or 2026-02-30", sender="home-owner"), "not a real calendar date")
refused("B: a far date that merely sounds distant is no basis for a wake a month out", lambda: server._update("a65", wait_basis="check later 2030-01-01", sender="home-owner"), "none of its dates")
refused("B: a wake more than a year out is refused whatever the basis", lambda: server._update("a65", wake="2099-12-31", hold=True, wait_basis="vendor reply 2099-12-31", sender="home-owner"), "at most 365 days")
refused("B: ...the same for a wake a year and a month out", lambda: server._update("a65", wake=day(396), hold=True, wait_basis=f"vendor reply {day(397)}", sender="home-owner"), "at most 365 days")
refused("B: a far basis on a wake set in the same call is refused too", lambda: server._update("a65", wake=day(40), hold=True, wait_basis="check later 2030-01-01", sender="home-owner"), "none of its dates")
check("B: ...and nothing was recorded by those refusals", "wait_basis" not in rd(65)["metadata"] and wk_(rd(65)["metadata"]) == day(30), rd(65)["metadata"])
server._update("a65", wake=day(300), hold=True, wait_basis=f"the sample license expires {day(302)}", sender="home-owner")
check("B: a wake 300 days out with its date inside the window is accepted (the limit is a year)", W.basis_of(rd(65)["metadata"]) == f"the sample license expires {day(302)}", rd(65)["metadata"])
# the server fires the wake: the basis goes with it
d = rd(65); d["metadata"].pop("until", None); d["metadata"]["hold"] = True; d["metadata"]["wake"] = day(-1); d["metadata"]["wait_basis"]["wake"] = day(-1); (T / "store/a/65.json").write_text(json.dumps(d))
check("B: before the pass: the item is on hold with a basis for its (past) wake", hd_(rd(65)["metadata"]) and W.basis_of(rd(65)["metadata"]), rd(65)["metadata"])
woke = server._wake_pass()
check("B: _wake_pass firing the wake drops the basis with the hold and the wake", "a65" in woke and "wait_basis" not in rd(65)["metadata"] and "wake" not in rd(65)["metadata"] and "hold" not in rd(65)["metadata"], (woke, rd(65)["metadata"]))

# going with the wake
for how, kw in (("clear_wake", {"clear_wake": True}), ("clear_hold", {"clear_hold": True}), ("a close", {"status": "completed", "outcome": "done", "reason": "ok", "description": "- Done"})):
    item(32, wake=day(30), wait_basis={"text": B(33), "wake": day(30), "by": "home-owner", "at": now0}, **({"hold": True} if how != "clear_wake" else {}))   # (a hold cannot lose its wake and stay a hold)
    try:
        server._update("a32", sender="home-owner", **kw)
    except Exception as e:
        check(f"B: {how} runs", False, str(e))
    check(f"B: {how} drops the basis with the wake", "wait_basis" not in rd(32)["metadata"], rd(32)["metadata"])

# the weekly list in the board's head
for _g in (2020, 29):      # the items of the refusal tests above hold a basis now: they are closed so that the lists below count only their own
    _d = rd(_g); _d.update(status="completed", outcome="done"); (T / f"store/a/{_g}.json").write_text(json.dumps(_d))
item(66, hold=True, wake=day(30), wait_basis={"text": B(33), "wake": day(30), "by": "home-owner", "at": now0})
item(34, hold=True, wake=day(31), wait_basis={"text": "stale basis " + day(33), "wake": day(30), "by": "home-owner", "at": now0})   # for another wake: no basis
item(212, hold=True, wake=day(5))
item(35, status="completed", outcome="done", wait_basis={"text": B(33), "wake": day(30), "by": "x", "at": now0})
ZONE = server.ZONE
mon, tue = datetime.datetime(2026, 10, 26, 9, 0, tzinfo=ZONE), datetime.datetime(2026, 10, 27, 9, 0, tzinfo=ZONE)
check("digest: the Monday of 2026-10-26 is a Monday", mon.weekday() == 0 and tue.weekday() == 1, None)
bm = ui_render.Board(f"{tmp}/store", now=mon); bt = ui_render.Board(f"{tmp}/store", now=tue)
check("digest: the Board holds the open waits that stand on a basis for their wake (not a stale one, not a closed item)", sorted(r["gid"] for r in bm.basis_waits) == ["a66"], [r["gid"] for r in bm.basis_waits])
md_m, md_t = bm.markdown(), bt.markdown()
sec = md_m.split("## Waits on a real-world date (weekly)")[1].split("## Machines")[0] if "## Waits on a real-world date (weekly)" in md_m else ""
check("digest: on the weekly day the board's head lists them (before Machines), each with its wake, its basis and who set it", "a66" in sec and B(33) in sec and "set by home-owner" in sec and "a34" not in sec and "a35" not in sec
      and md_m.index("## Waits on a real-world date") < md_m.index("## Machines"), sec[:500])
check("digest: on another weekday the section is not there", "Waits on a real-world date" not in md_t, md_t[:100])
check("digest: the brief lists them on the weekly day only", "waits on a real-world date: a66" in bm.brief() and "waits on a real-world date" not in bt.brief(), (bm.brief(), bt.brief()))
server._cfg.CFG.setdefault("waiting", {})["basis_weekday"] = -1
check("digest: [waiting] basis_weekday = -1 lists them every day", "a66" in bt.markdown() and "waits on a real-world date: a66" in bt.brief(), None)
server._cfg.CFG["waiting"]["basis_weekday"] = 1
check("digest: …and 1 is Tuesday", "a66" in bt.markdown() and "Waits on a real-world date" not in bm.markdown(), None)
server._cfg.CFG["waiting"].pop("basis_weekday")

# the web board's rows, every day (the wait that stands on a real-world date is a row of the Waiting list, with its basis, its wake date and who set it, in place of the block)
item(67, hold=True, wake=day(40), wait_basis={"text": f"vendor answers on {day(43)}", "wake": day(40), "by": "home-stew", "at": now0})
bm, bt = ui_render.Board(f"{tmp}/store", now=mon), ui_render.Board(f"{tmp}/store", now=tue)
hm, ht = bm.html(), bt.html()
def sect(h):      # the Waiting list
    i = h.find('<section id="waiting-list">')
    return h[i:h.find("</section>", i)] if i >= 0 else ""
def rowof(h, g):
    w = sect(h); i = w.find(f'id="task-a-{g}"')
    return w[i:w.find("</li>", i)] if i >= 0 else ""
sm = sect(hm)
check("web: the Waiting list carries the rows every day, not only on the weekly one (a Monday and a Tuesday alike), and no block of its own", sm and sect(ht) and rowof(hm, 66) and rowof(ht, 66) and 'id="outside-event"' not in hm, sm[:200])
bm2 = ui_render.Board(f"{tmp}/store", now=mon)
check("web: a basis in the row of each open item whose wake has a valid basis (66 and 67); none beside a stale basis or a plain wake, and no row for a closed item",
      sorted(r["gid"] for r in bm2.basis_waits) == ["a66", "a67"] and B(33) in rowof(hm, 66) and f"vendor answers on {day(43)}" in rowof(hm, 67)
      and "stale basis" not in sm and rowof(hm, 34) and rowof(hm, 212) and "set by" not in rowof(hm, 212) and "set by" not in rowof(hm, 34) and 'id="task-a-35"' not in sm
      and sm.count("set by") == 2 and re.search(r'Waiting <span class="count">(\d+)</span>', sm).group(1) == str(sm.count('<li class="irow hrow')), (sm.count("set by"), re.findall(r'Waiting <span class="count">\d+</span>', sm), sm.count('<li class="irow hrow')))
check("web: ...each row has the item link, the subject, the basis text, the wake as a date and who set it", "/items/a66" in rowof(hm, 66) and "item 66" in rowof(hm, 66) and B(33) in rowof(hm, 66)
      and "set by home-owner" in rowof(hm, 66) and "set by home-stew" in rowof(hm, 67) and re.search(r"until \w{3} \w{3} \d+\w\w", rowof(hm, 66)), rowof(hm, 66))
check("web: ...the oldest wake first and the newest last", sm.index('id="task-a-66"') < sm.index('id="task-a-67"'), sm)
check("web: ...it is the Waiting block, in the live set, and there is no block of its own", ' waiting-list=' in ht and ' outside-event=' not in ht and 'id="outside-event"' not in ht, None)
# no row once the wake changes (the basis is read only for the wake it was given for), and no section at all when none is left
server._update("a67", clear_hold=True, sender="home-owner")      # the hold and its wake go (a new wake would need a reason of its own:), and the basis with them
sm = sect(ui_render.Board(f"{tmp}/store", now=mon).html())
check("web: once an item's wake goes its basis goes (the basis was for the old wake): one basis left on the Waiting list, and its heading counts the rows", f"vendor answers on {day(43)}" not in sm and B(33) in sm and sm.count("set by") == 1
      and re.search(r'Waiting <span class="count">(\d+)</span>', sm).group(1) == str(sm.count('<li class="irow hrow')), sm)
_it = json.loads((T / "store/a/66.json").read_text()); (T / "store/a/66.json").write_text(json.dumps({**_it, "status": "completed", "outcome": "done"}))
h_none = ui_render.Board(f"{tmp}/store", now=mon).html()
check("web: with no basis left, no Waiting row says 'set by', the closed item has no row, and no block of the old kind comes back", "set by" not in sect(h_none) and not rowof(h_none, 66) and B(33) not in sect(h_none)
      and 'id="outside-event"' not in h_none and "Parked on an outside event" not in h_none and " outside-event=" not in h_none, sect(h_none)[:400])
(T / "store/a/66.json").write_text(json.dumps(_it))
# the row's text is written by sessions, so it is escaped; "set by" is the session's name as the page names it (a session id reads as its name)
evil = f'<script>alert("x")</script> & "q" \'s <img src=x onerror=1> on {day(43)}'
item(70, hold=True, wake=day(40), wait_basis={"text": evil, "wake": day(40), "by": "<b>x</b>", "at": now0})
_d = rd(70); _d["subject"] = '[home] <i>subject</i> & "q"'; (T / "store/a/70.json").write_text(json.dumps(_d))
item(71, hold=True, wake=day(41), wait_basis={"text": f"vendor answers on {day(44)}", "wake": day(41), "by": U["home-stew"], "at": now0})
_real_dn = ui_render._sr.display_name; ui_render._sr.display_name = lambda x: {U["home-stew"]: "home-stew"}.get(str(x)) or _real_dn(x)    # the registry of the live fleet is not here: a session id reads as its name
try:
    sm = sect(ui_render.Board(f"{tmp}/store", now=mon).html())
finally:
    ui_render._sr.display_name = _real_dn
check("web: a hostile basis text, subject and setter are escaped in the row", "/items/a70" in sm and "<script>" not in sm and "&lt;script&gt;" in sm and "<img" not in sm and "&lt;img" in sm
      and "&quot;q&quot;" in sm.replace("&#x27;", "'") and "<b>x</b>" not in sm and "set by &lt;b&gt;x&lt;/b&gt;" in sm and "<i>subject</i>" not in sm, sm)
check("web: ...the setter is shown through the session's name, not its id", "/items/a71" in sm and "set by home-stew" in sm and U["home-stew"] not in sm, sm[sm.find("/items/a71"):][:400])
os.remove(T / "store/a/70.json"); os.remove(T / "store/a/71.json")

# ================================================================ the client API (what tools/cap_words.py --apply sends)
item(36, hold=True, wake=day(30), answers=[park])
st, d = server._client_post("testbox", "cap-words", {"sender": "home-test", "item": "a36", "ts": TS})
check("API: cap-words with an entry records his words", st == 200 and d["action"] == "set" and rd(36)["metadata"]["cap_ok"]["quote"] == park["text"], (st, d))
item(37, hold=True, wake=day(30))
st, d = server._client_post("testbox", "cap-words", {"sender": "home-test", "item": "a37", "basis": B(33)})
check("API: cap-words with a basis goes through the update path", st == 200 and d["action"] == "set" and W.basis_of(rd(37)["metadata"]) == B(33) and rd(37)["metadata"]["wait_basis"]["by"] == "home-test via a script on testbox", (st, d, rd(37)["metadata"]))
st, d = server._client_post("testbox", "cap-words", {"sender": "home-test", "item": "a37", "basis": "no date here at all"})
check("API: a refusal is a 400 with the reason", st == 400 and "YYYY-MM-DD" in d["error"], (st, d))
st, d = server._client_post("testbox", "cap-words", {"sender": "home-test", "item": "a58", "ts": TB+1})
check("API: an agent's entry is a 400", st == 400 and "own words" in d["error"], (st, d))

# the only writers of metadata.answers are the board's answer form and the GitHub reader: not create, update or said
import inspect
from stackshot.service import update as _upd_svc
for fn in ("stackshot_create", "stackshot_update", "stackshot_complete", "_create", "_update", "update_unlocked"):
    ps = inspect.signature(getattr(_upd_svc if fn == "update_unlocked" else server, fn)).parameters
    check(f"writers: {fn} has no parameter that writes answers", "answers" not in ps and not any(x.kind is inspect.Parameter.VAR_KEYWORD for x in ps.values()), list(ps))
item(38, hold=True, wake=day(30), answers=[park])
ans0 = rd(38)["metadata"]["answers"]
server._update("a38", next="home-owner: changed", sender="home-owner")
try:
    server._update("a38", next="again", said=[{"tag": "Acked-by", "quote": "park it", "session": U["home-owner"], "answers": [{"ts": 1.0, "kind": "decision", "text": "park forever", "via": "board"}]}], sender="home-owner")
except Exception:
    pass
check("writers: update (and said) leave the item's answers as they were", rd(38)["metadata"]["answers"] == ans0, rd(38)["metadata"]["answers"])
try:
    server._create(subject="[home] new one", description=DESC, project="projects/alpha", sender="home-owner", answers=[{"ts": 1.0}])
    check("writers: create refuses an answers argument", False)
except TypeError:
    check("writers: create refuses an answers argument", True)
except Exception as e:
    check("writers: create refuses an answers argument", False, str(e))

# over HTTP, in-process: the machine token is required; the sender too
from stackshot.fleet import client as _client
from starlette.testclient import TestClient
(T / "secrets").mkdir(exist_ok=True)
tok = open(_client.mint("home-test")).read().strip()
item(39, hold=True, wake=day(30), answers=[park])
with TestClient(server.mcp.http_app()) as c:
    r = c.post("/client/cap-words", json={"sender": "home-test", "item": "a39", "ts": TS})
    check("http: cap-words without the machine token is 401 and writes nothing", r.status_code == 401 and "cap_ok" not in rd(39)["metadata"], (r.status_code, r.text[:100]))
    r = c.post("/client/cap-words", json={"sender": "home-test", "item": "a39", "ts": TS}, headers={"Authorization": "Bearer " + "x" * 43})
    check("http: ...a wrong token is 401 too", r.status_code == 401 and "cap_ok" not in rd(39)["metadata"], (r.status_code, r.text[:100]))
    H = {"Authorization": "Bearer " + tok}
    r = c.post("/client/cap-words", json={"item": "a39", "ts": TS}, headers=H)
    check("http: with the token but no sender it is a 400 and writes nothing", r.status_code == 400 and "sender is required" in r.text and "cap_ok" not in rd(39)["metadata"], (r.status_code, r.text[:200]))
    r = c.post("/client/cap-words", json={"sender": "home-test", "item": "a39", "ts": TS}, headers=H)
    check("http: with the token and a sender it records, naming sender and machine", r.status_code == 200 and rd(39)["metadata"]["cap_ok"]["by"] == "home-test via a script on home-test", (r.status_code, r.text[:200], rd(39)["metadata"]))

# ================================================================ tools/cap_words.py
spec = importlib.util.spec_from_file_location("cap_words", os.path.join(STACK, "stackshot", "tools", "cap_words.py")); cw = importlib.util.module_from_spec(spec); spec.loader.exec_module(cw)
item(9193, letter="g", hold=True, wake="2099-06-04T09:00", su=now0 - 9 * DAY,
     answers=[{"ts": TB + 10.5, "kind": "decision", "text": "keep this parked until jun 4", "via": "board"}, {"ts": TB + 11.5, "kind": "decision", "choice": "Approve", "text": "ok", "via": "board"}])
item(9194, letter="g", hold=True, wake="2099-06-07", needs=["external"], su=now0 - 9 * DAY, next="Parked (Oliver) until a reviewer moves it.")   # no words of his stored, an agent's paraphrase
item(9195, letter="g", hold=True, wake=day(5), su=now0 - 2 * DAY, answers=[{"ts": TB + 12.5, "kind": "decision", "text": "the supplier replied", "via": "board"}])
item(9196, letter="g", hold=True, wake=day(300), due=day(307), su=now0 - 9 * DAY)
item(9197, letter="g", hold=True, wake=day(3), su=now0 - DAY)
p9001, p9002, p9003 = cw.plan_a(9193, "", now0), cw.plan_a(9194, "", now0), cw.plan_a(9195, "", now0)
check("tool: an item with his park words: found, the body names the entry by ts and carries his sentence", p9001["found"] and p9001["body"]["ts"] == TB + 10.5 and p9001["body"]["quote"] == "keep this parked until jun 4", p9001)
check("tool: the dry run lists every entry, marks his and the park, and says what it would record", "HIS, reads as a park" in "\n".join(p9001["lines"]) and "WOULD RECORD cap_ok for wake 2099-06-04T09:00" in "\n".join(p9001["lines"]), p9001["lines"])
check("tool: an item with no words of his is reported as such and left alone; an agent's paraphrase is shown and not used",
      not p9002["found"] and "no answers or comments of his are stored" in "\n".join(p9002["lines"]) and "NOT used as his words" in "\n".join(p9002["lines"]) and "NOTHING TO RECORD" in "\n".join(p9002["lines"]), p9002["lines"])
check("tool: his words that do not park are listed but not picked", not p9003["found"] and "HIS ·" in "\n".join(p9003["lines"]) and "NOTHING TO RECORD" in "\n".join(p9003["lines"]), p9003["lines"])
p9004, p9005 = cw.plan_b(9196, "", now0), cw.plan_b(9197, "", now0)
check("tool: a B item with no basis given has none proposed and is not recorded (no basis table ships with the tool, and no item is named by default)",
      not p9004["found"] and cw.B_BASIS == {} and cw.A_ITEMS == () and cw.B_ITEMS == (), p9004)
p9004 = cw.plan_b(9196, f"the sample license expires {day(301)}", now0)
check("tool: …with a basis of its own it is found", p9004["found"] and p9004["body"] == {"item": f"board#{BID_D}", "basis": f"the sample license expires {day(301)}"}, p9004)
check("tool: a B item whose wake is within the cap needs none", not p9005["found"] and "not needed" in "\n".join(p9005["lines"]), p9005)
snap = lambda: hashlib.sha256(b"".join(p.read_bytes() for p in sorted((T / "store").rglob("*.json")))).hexdigest()
h0 = snap()
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = cw.main(["--a-item", f"board#{BID_A}", "--a-item", f"board#{BID_B}"])
check("tool: the dry run (the default) writes nothing and says so", rc == 0 and snap() == h0 and "DRY RUN" in buf.getvalue() and "nothing was written" in buf.getvalue(), buf.getvalue()[-300:])
from stackshot.fleet import client as _client
real_post = _client.post
_client.post = lambda what, body, timeout=20.0: server._client_post("testbox", what, body)
try:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cw.main(["--apply", "--sender", "home-test", "--a-item", f"board#{BID_A}", "--a-item", f"board#{BID_B}", "--b-item", f"board#{BID_D}", "--basis", f"board#{BID_D}=the sample license expires {day(301)}"])
finally:
    _client.post = real_post
check("tool: --apply records what was found through the server and leaves the item with no words alone",
      rc == 0 and rd(9193, "g")["metadata"].get("cap_ok", {}).get("quote") == "keep this parked until jun 4" and "cap_ok" not in rd(9194, "g")["metadata"]
      and W.basis_of(rd(9196, "g")["metadata"]) == f"the sample license expires {day(301)}" and f"recorded board#{BID_A}: set" in buf.getvalue(), buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = cw.main(["--a-item", f"board#{BID_A}", "--b-item", f"board#{BID_D}", "--basis", f"board#{BID_D}=the sample license expires {day(301)}"])
check("tool: a second dry run says they are already recorded", "ALREADY RECORDED" in buf.getvalue() and buf.getvalue().count("ALREADY RECORDED") == 2, buf.getvalue())

# ================================================================ pairing by the store's history (waiting.prior_state_ts)
import subprocess
def vcs(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", tmp, *a], capture_output=True, text=True, check=True)
vcs("init", "-q"); vcs("config", "gc.auto", "0")
def commit(i, msg):
    vcs("add", f"store/a/{i}.json"); vcs("commit", "-q", "-m", msg)
ans = lambda ts, text="park this until Jun 4th": {"ts": ts, "kind": "decision", "text": text, "via": "board"}
def put(i, **top):
    d = rd(i); d.update(top); (T / f"store/a/{i}.json").write_text(json.dumps(d))
# 45: Oliver answers (6 days ago), the session sets the wake from it (state move 4 days ago): he spoke last before the move -> pairs, however long the gap
item(45, hold=True, su=now0 - 20 * DAY); commit(45, "created")
d = rd(45); d["metadata"]["answers"] = [ans(now0 - 6 * DAY)]; (T / "store/a/45.json").write_text(json.dumps(d)); commit(45, "his answer")
d = rd(45); d["metadata"]["wake"] = day(30); d["state_updated"] = now0 - 4 * DAY; (T / "store/a/45.json").write_text(json.dumps(d)); commit(45, "wake set from his answer")
check("history: prior_state_ts reads the state change before the move that set the wake (passing over the version that only added an answer)", abs((W.prior_state_ts("a45", day(30)) or 0) - (now0 - 20 * DAY)) < 1e-3, W.prior_state_ts("a45", day(30)))
out = server._record_cap_words({"sender": "home-test", "item": "a45", "ts": now0 - 6 * DAY}, "testbox")
check("history: his answer, then the wake set from it: pairs although it is 2 days before the state clock", out["action"] == "set" and rd(45)["metadata"]["cap_ok"]["quote"] == "park this until Jun 4th", out)
# 46: his park answer, then a wake set, then another wake change, then the current one -> stale
item(46, hold=True, wake=day(30), su=now0 - 20 * DAY, answers=[ans(now0 - 6 * DAY)]); commit(46, "created with his answer")
for k, t in enumerate((now0 - 5 * DAY, now0 - 4 * DAY, now0 - 3 * DAY)):
    d = rd(46); d["state_updated"] = t; d["metadata"]["wake"] = day(10 + k * 10); (T / "store/a/46.json").write_text(json.dumps(d)); commit(46, f"wake change {k}")
refused("history: his park answer, then a wake set, then another wake change, then the current one: refused", lambda: server._record_cap_words({"sender": "home-test", "item": "a46", "ts": now0 - 6 * DAY}, "testbox"), "came after it")
check("history: ...and nothing was recorded", "cap_ok" not in rd(46)["metadata"], rd(46)["metadata"])
# 48: the wake is set from his answer, and the state clock moves again later (a hold flag, needs) with the same wake: still pairs
item(48, su=now0 - 20 * DAY); commit(48, "created")
d = rd(48); d["metadata"]["answers"] = [ans(now0 - 6 * DAY)]; (T / "store/a/48.json").write_text(json.dumps(d)); commit(48, "his answer")
d = rd(48); d["metadata"]["wake"] = day(30); d["state_updated"] = now0 - 5 * DAY; (T / "store/a/48.json").write_text(json.dumps(d)); commit(48, "wake set")
d = rd(48); d["metadata"]["hold"] = True; d["state_updated"] = now0 - 2 * DAY; (T / "store/a/48.json").write_text(json.dumps(d)); commit(48, "hold flag set later")
out = server._record_cap_words({"sender": "home-test", "item": "a48", "ts": now0 - 6 * DAY}, "testbox")
check("history: a hold flag set after the wake does not stand between his answer and the wake: pairs", out["action"] == "set", out)
# 47: a file never committed: the 24-hour lead
item(47, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 5 * DAY - 3600), ans(now0 - 8 * DAY, "park it for a while")])
check("history: a file with no history gives no prior", W.prior_state_ts("a47", day(30)) is None, W.prior_state_ts("a47", day(30)))
out = server._record_cap_words({"sender": "home-test", "item": "a47", "ts": now0 - 5 * DAY - 3600}, "testbox")
check("history: with no history an answer an hour before the move pairs (24-hour lead)", out["action"] == "set", out)
refused("history: ...and one three days before does not", lambda: server._record_cap_words({"sender": "home-test", "item": "a47", "ts": now0 - 8 * DAY}, "testbox"), "more than 24 hours")

# ================================================================ the history unreadable is not "no history" (follow-up (b) of the review of quick fix 1a)
# 49: a committed file whose current wake was set from his answer an hour earlier: with a readable history the answer pairs; with an unreadable one it is refused
item(49, hold=True, su=now0 - 20 * DAY); commit(49, "created")
d = rd(49); d["metadata"]["answers"] = [ans(now0 - 6 * DAY)]; (T / "store/a/49.json").write_text(json.dumps(d)); commit(49, "his answer")
d = rd(49); d["metadata"]["wake"] = day(30); d["state_updated"] = now0 - 4 * DAY; (T / "store/a/49.json").write_text(json.dumps(d)); commit(49, "wake set from his answer")
check("unreadable: with a readable history prior_state_ts is the state change before the wake", abs((W.prior_state_ts("a49", day(30)) or 0) - (now0 - 20 * DAY)) < 1e-3, W.prior_state_ts("a49", day(30)))
check("unreadable: UNREADABLE is a value of its own, falsy, and neither None nor a time", W.UNREADABLE is not None and not W.UNREADABLE and repr(W.UNREADABLE) == "UNREADABLE", repr(W.UNREADABLE))
ok_, why_ = W.entry_pairs(rd(49), now0 - 6 * DAY, now0, W.UNREADABLE)
check("unreadable: entry_pairs refuses an earlier answer with the words to tell Oliver", not ok_ and why_ == "history unreadable: ask Oliver to answer again on the item", (ok_, why_))
check("unreadable: ...but an answer given since the state clock still pairs without any history", W.entry_pairs(rd(49), now0 - 3 * DAY, now0, W.UNREADABLE)[0], None)
real_run = subprocess.run
def gitless(*a, **k): raise FileNotFoundError("git")
def slow(*a, **k): raise subprocess.TimeoutExpired(a[0] if a else "git", 30)
for label, fake in (("git missing", gitless), ("a timeout", slow)):
    subprocess.run = fake
    try: got = W.prior_state_ts("a49", day(30))
    finally: subprocess.run = real_run
    check(f"unreadable: {label} is UNREADABLE, not None", got is W.UNREADABLE, got)
subprocess.run = gitless
try:
    refused("unreadable: with git missing the server refuses an earlier answer and says why", lambda: server._record_cap_words({"sender": "home-test", "item": "a49", "ts": now0 - 6 * DAY}, "testbox"), "history unreadable: ask Oliver to answer again on the item")
finally: subprocess.run = real_run
check("unreadable: ...and records nothing", "cap_ok" not in rd(49)["metadata"], rd(49)["metadata"])
# a version that does not parse
item(50, hold=True, su=now0 - 20 * DAY); commit(50, "created")
(T / "store/a/50.json").write_text("{ not json"); commit(50, "damaged")
d = {"id": "50", "subject": "[home] item 50", "description": DESC, "status": "open", "updated": now0 - 4 * DAY, "state_updated": now0 - 4 * DAY, "confirmed": now0 - 4 * DAY,
     "metadata": {"owner": U["home-owner"], "project": "projects/alpha", "next": "do the thing", "hold": True, "wake": day(30), "answers": [ans(now0 - 6 * DAY)]}}
(T / "store/a/50.json").write_text(json.dumps(d)); commit(50, "wake set")
check("unreadable: a version of the file that does not parse is UNREADABLE", W.prior_state_ts("a50", day(30)) is W.UNREADABLE, W.prior_state_ts("a50", day(30)))
refused("unreadable: ...and the server refuses an earlier answer", lambda: server._record_cap_words({"sender": "home-test", "item": "a50", "ts": now0 - 6 * DAY}, "testbox"), "history unreadable")
# the look-back runs out: more versions than `limit`, all carrying the wake
item(51, hold=True, wake=day(30), su=now0 - 20 * DAY, answers=[ans(now0 - 6 * DAY)]); commit(51, "created with the wake")
for k in range(4):
    d = rd(51); d["metadata"]["next"] = f"do the thing {k}"; (T / "store/a/51.json").write_text(json.dumps(d)); commit(51, f"note {k}")
check("unreadable: the look-back running out before the run ends is UNREADABLE", W.prior_state_ts("a51", day(30), limit=3) is W.UNREADABLE, W.prior_state_ts("a51", day(30), limit=3))
check("unreadable: ...while a wake that stood since the first version, with the whole history read, is None", W.prior_state_ts("a51", day(30)) is None, W.prior_state_ts("a51", day(30)))
# not a checkout, and no history for the file, stay the 24-hour lead (47 above); a store outside the repo too
check("unreadable: a file the repository has never seen is None (the 24-hour lead stays)", W.prior_state_ts("a47", day(30)) is None, W.prior_state_ts("a47", day(30)))
r_ = W._cfg.path("paths", "repo")
os.makedirs(f"{tmp}/plain", exist_ok=True)
W._cfg.CFG["paths"]["repo"] = f"{tmp}/plain"; W._cfg.CFG["paths"]["store"] = f"{tmp}/plain/store"
try: got = W.prior_state_ts("a47", day(30))
finally:
    W._cfg.CFG["paths"]["repo"] = str(r_); W._cfg.CFG["paths"]["store"] = f"{tmp}/store"
check("unreadable: a directory that is not a git checkout is None (the 24-hour lead stays)", got is None, got)

# ================================================================ the order of the checks, and the lock (follow-up (a))
calls = []
real_prior = W.prior_state_ts
def spy(gid, wake, limit=200):
    calls.append((gid, wake, writes.ITEM_LOCK._is_owned()))
    return real_prior(gid, wake, limit)
W.prior_state_ts = spy
try:
    item(69, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 8 * DAY, "sent")])
    refused("order: words that do not park are refused before the history is read", lambda: server._record_cap_words({"sender": "home-test", "item": "a69", "ts": now0 - 8 * DAY}, "testbox"), "do not park")
    check("order: ...the history was not read at all", calls == [], calls)
    item(52, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 8 * DAY)])
    refused("order: an earlier park answer on an item with no history is stale (24-hour lead) and the history was read", lambda: server._record_cap_words({"sender": "home-test", "item": "a52", "ts": now0 - 8 * DAY}, "testbox"), "more than 24 hours")
    check("order: ...once, and before the item lock was taken", len(calls) == 1 and calls[0][0] == "a52" and calls[0][2] is False, calls)
    calls.clear()
    item(53, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 4 * DAY)])
    out = server._record_cap_words({"sender": "home-test", "item": "a53", "ts": now0 - 4 * DAY}, "testbox")
    check("order: an answer given since the move that set the wake pairs without reading the history", out["action"] == "set" and calls == [], (out, calls))
    # the result is still checked under the lock: the item moves while the history is read
    calls.clear()
    item(54, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 5 * DAY - 3600)])
    def spy_moves(gid, wake, limit=200):
        got = real_prior(gid, wake, limit)
        d = rd(54); d["metadata"]["wake"] = day(31); (T / "store/a/54.json").write_text(json.dumps(d))     # another session sets a new wake meanwhile
        return got
    W.prior_state_ts = spy_moves
    refused("lock: a wake that changed while the history was read is refused, to be run again", lambda: server._record_cap_words({"sender": "home-test", "item": "a54", "ts": now0 - 5 * DAY - 3600}, "testbox"), "moved while its history was being read")
    check("lock: ...and nothing was recorded", "cap_ok" not in rd(54)["metadata"], rd(54)["metadata"])
    # the answer is current at the first read (so no history is read for it); the state clock then moves before the lock is taken
    item(55, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 4 * DAY)])
    W.prior_state_ts = spy
    calls.clear()
    orig_load = server._load; n_loads = [0]
    def load_moving(g):
        if g == "a55":
            n_loads[0] += 1
            if n_loads[0] == 2:                      # the first read is the one before the lock; the second is under it
                dd = rd(55); dd["state_updated"] = now0 - 1 * DAY; (T / "store/a/55.json").write_text(json.dumps(dd))
        return orig_load(g)
    server._load = load_moving
    try:
        refused("lock: a state clock that moved after a current answer was read without history is refused, to be run again", lambda: server._record_cap_words({"sender": "home-test", "item": "a55", "ts": now0 - 4 * DAY}, "testbox"), "moved while its history was being read")
    finally:
        server._load = orig_load
    check("lock: ...and the history was never read for it, nothing recorded", calls == [] and "cap_ok" not in rd(55)["metadata"], (calls, rd(55)["metadata"]))
    # the state clock moves while the history is read, the wake does not: refused as well (the wake alone is not enough to compare)
    item(56, hold=True, wake=day(30), su=now0 - 5 * DAY, answers=[ans(now0 - 5 * DAY - 3600)])
    def spy_state(gid, wake, limit=200):
        got = real_prior(gid, wake, limit)
        dd = rd(56); dd["state_updated"] = now0 - 2 * DAY; (T / "store/a/56.json").write_text(json.dumps(dd))     # the same wake, another move of the item meanwhile
        return got
    W.prior_state_ts = spy_state
    refused("lock: a state move with the same wake while the history was read is refused too, to be run again", lambda: server._record_cap_words({"sender": "home-test", "item": "a56", "ts": now0 - 5 * DAY - 3600}, "testbox"), "moved while its history was being read")
    check("lock: ...and nothing was recorded", "cap_ok" not in rd(56)["metadata"] and wk_(rd(56)["metadata"]) == day(30), rd(56)["metadata"])
finally:
    W.prior_state_ts = real_prior

# ================================================================ a wake that is set, cleared and set again to the same value (follow-up (c))
# One value in three versions of the file: the run the CURRENT wake was set in is the newest one only; the clear ends the earlier run, and the state change
# before the current set is the clear, not the creation. His answer before the clear is therefore stale; one given after the clear pairs.
A1, A2 = now0 - 9 * DAY, now0 - 6 * DAY
item(57, su=now0 - 20 * DAY); commit(57, "created, no wake")
d = rd(57); d["metadata"]["answers"] = [ans(A1)]; (T / "store/a/57.json").write_text(json.dumps(d)); commit(57, "his first answer")
d = rd(57); d["metadata"]["hold"] = True; d["metadata"]["wake"] = day(30); d["state_updated"] = now0 - 8 * DAY; (T / "store/a/57.json").write_text(json.dumps(d)); commit(57, "wake set")
d = rd(57); d["metadata"].pop("wake"); d["metadata"].pop("hold"); d["state_updated"] = now0 - 7 * DAY; (T / "store/a/57.json").write_text(json.dumps(d)); commit(57, "wake cleared")
d = rd(57); d["metadata"]["answers"].append(ans(A2, "postpone it, same date")); (T / "store/a/57.json").write_text(json.dumps(d)); commit(57, "his second answer")
d = rd(57); d["metadata"]["hold"] = True; d["metadata"]["wake"] = day(30); d["state_updated"] = now0 - 5 * DAY; (T / "store/a/57.json").write_text(json.dumps(d)); commit(57, "the same wake set again")
p_a = W.prior_state_ts("a57", day(30))
check("again: prior_state_ts of a wake set, cleared and set again to the same value is the clear (the newest run's start), not the first set or the creation",
      p_a is not None and p_a is not W.UNREADABLE and abs(p_a - (now0 - 7 * DAY)) < 1e-3, p_a)
check("again: …the same wake read before the clear and after would differ: the first run is not counted", abs(p_a - (now0 - 20 * DAY)) > 1.0 and abs(p_a - (now0 - 8 * DAY)) > 1.0, p_a)
refused("again: his answer from before the clear is stale: a state move (the clear) lies between it and the current set", lambda: server._record_cap_words({"sender": "home-test", "item": "a57", "ts": A1}, "testbox"), "came after it")
check("again: …nothing was recorded", "cap_ok" not in rd(57)["metadata"], rd(57)["metadata"])
out = server._record_cap_words({"sender": "home-test", "item": "a57", "ts": A2}, "testbox")
check("again: his answer given after the clear, the last thing before the current set, pairs", out["action"] == "set" and rd(57)["metadata"]["cap_ok"]["quote"] == "postpone it, same date", out)

# ================================================================ C. a verifying item (not held) moves its wake closer
# A verifying item's end date is its time wait (no hold flag). An earlier wake with one call has to work: the snooze check asks a time wait for a reason
# (wait_basis bound to the new wake) and the basis gate asks whether the item is held; the two agreed only for a stored hold.
VER = dict(state="verifying", proof="the link opens on the phone", end=day(9), needs=["team-back"])
item(80, **VER)
check("C: before: the verifying item has no hold flag and no wake: it waits on its end date", not hd_(rd(80)["metadata"]) and not wk_(rd(80)["metadata"]) and rd(80)["metadata"]["end"] == day(9), rd(80)["metadata"])
refused("C: an earlier wake alone on a verifying item asks a time wait for its reason", lambda: server._update("a80", wake=day(1), sender="team-back"), "no reason", "wait_basis=")
check("C: …and nothing was written", "wake" not in rd(80)["metadata"], rd(80)["metadata"])
def tried(f):
    """run an update; (True, "") when it went through, (False, the refusal) when it did not: a refusal is then a failed check, not an uncaught error"""
    try: f(); return True, ""
    except Exception as e: return False, str(e)
ok_, err_ = tried(lambda: server._update("a80", wake=day(1), wait_basis=f"the soak ends {day(1)}", sender="team-back"))
check("C: the call with a wait_basis of its own goes through (one call satisfies both checks)", ok_, err_)
m = rd(80)["metadata"]
check("C: the same call with a wait_basis of its own works: the wake is stored, the basis is bound to it, the item stays verifying and unheld",
      wk_(m) == day(1) and W.basis_of(m) == f"the soak ends {day(1)}" and m["state"] == "verifying" and m["end"] == day(9) and "hold" not in m, m)
check("C: …and the wait now ends at the new wake", W.wake_epoch(wk_(rd(80)["metadata"])) == W.wake_epoch(day(1)), rd(80)["metadata"])
server._update("a80", wake=day(2), wait_basis=f"the soak ends {day(2)} after all", sender="team-back")
check("C: a later wake with its own basis replaces both", wk_(rd(80)["metadata"]) == day(2) and W.basis_of(rd(80)["metadata"]) == f"the soak ends {day(2)} after all", rd(80)["metadata"])
item(81, **VER)
refused("C: a wait_basis on a verifying item with a wake past its 365-day reach is still refused", lambda: server._update("a81", wake="2099-12-31", wait_basis="vendor reply 2099-12-31", sender="team-back"), "at most 365 days")
# the hold and the wake in one call, on an item still on agent (a stored doing): the stored item is no time wait yet, the call makes it one
item(83, needs=["team-back"], state="doing")
refused("C: hold=true with the wake and no basis, on a doing item, is refused with the reason guard (nothing is stored)",
        lambda: server._update("a83", hold=True, wake=day(1), sender="team-back"), "no reason", "wait_basis=")
check("C: …and the item is as it was", rd(83)["metadata"].get("state") == "doing" and "wake" not in rd(83)["metadata"] and not hd_(rd(83)["metadata"]), rd(83)["metadata"])
ok_, err_ = tried(lambda: server._update("a83", hold=True, wake=day(1), wait_basis=f"the soak ends {day(1)}", sender="team-back"))
check("C: the same call with a wait_basis goes through", ok_, err_)
m = rd(83)["metadata"]
check("C: …the item is held, with the wake and the basis bound to it", hd_(m) is True and wk_(m) == day(1) and W.basis_of(m) == f"the soak ends {day(1)}", m)
# the other side stays as it was: a wake alone on an alive item is a backstop that needs no basis, and a basis for it is not needed
item(82, needs=["team-back"], state="doing")
server._update("a82", wake=day(2), sender="team-back")
check("C: a wake alone on a doing item is a date to wait on (stored as until, no hold): accepted with no basis", wk_(rd(82)["metadata"]) == day(2) and "hold" not in rd(82)["metadata"] and _WT.stored_until(rd(82)["metadata"]) == day(2), rd(82)["metadata"])
refused("C: …and a wait_basis for it is not needed", lambda: server._update("a82", wake=day(3), wait_basis=f"visit on {day(4)}", sender="team-back"), "not needed")

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": cap words scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
