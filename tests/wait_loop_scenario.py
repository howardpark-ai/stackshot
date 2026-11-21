"""Scenario test for the minute wait-loop walk (waits/wait_loop.py, audit/wait_loops.py, service/audit_ticks._loop_tick): a ring of items that wait on each other is found within a minute and told to the movers.
Fixture items staged in a scratch store, messages replaced by recorders, no live store, no network, no model call.

  1  the ring finder on plain data: a ring of two, of three and of one (an `after` on itself); a ring written in words (an open step that waits for another item) beside an `after`; an acyclic chain, a link to a closed item and a link
     to an item that does not exist are no ring; a step that names its own item is no wait; the fingerprint is the same for the same ring under either name of a link and differs for another ring; the answer does not depend on the order the
     items are read; a part with more than one ring is told as the shortest ring through the newest link; the newest link is the one written last, the higher item number settling a tie
  2  the walk on a staged store: a link-link ring of two, of three and a link-words ring are each found, and one finding goes to each item's mover, naming the ring, the newest link and what to do; nothing is found in a chain, a closed target
     or a missing target, and nothing is written for them
  3  the newest link: the link of the item written last is the one named, whichever item number it has; the time a link was first seen is kept in the walker's own file and a write to an item later does not make its old link new
  4  told once: a ring that stands is not told again the next minute, nor because its items were written; it is told again on the audit's re-tell cadence, as a later try; a ring that changes is told at once; a ring that ended leaves the
     record and is told afresh when it comes back
  5  the pass: a dry run sends and writes nothing; a daily run in progress stands the pass still; the cap on one pass's messages; a failed delivery is tried again; a quiet board reads no item whole and writes nothing; the store walk reads a
     file again only when it changed
  6  the server's tick: it stands still when the audit is off or in agent mode, and runs the pass through the server's own message function; it is a paced, board-gated tick of the fleet group, after the hand-back tick
  7  the weekly report: the loops found in the week are one line of the refusal report, the week before beside it, and no line when there were none
  8  what is a wait: a step's words link two items only where the item is what is waited for ("after merging, post the result on <item>" is none, "wait for <item>" is one); a done step is no wait; the item lines of a list of
     waits make a link in mode all and none in mode any; two items of different letters that share a number are told apart (the issue letter's is the one a `board#N` names), in the walk and in the telling; the shortest
     ring through the newest link is the one told

    tests/run-suite wait_loop        → exit 0 / 1"""
import datetime as dt, json, os, pathlib, random, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="waitloop-"); T = pathlib.Path(tmp)
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

from stackshot.core import config as _cfg; from stackshot.audit import audit; from stackshot.audit import audit_run as AR; from stackshot.audit import wait_loops as WL
from stackshot.waits import wait_loop as L
H = 3600; now = time.time()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

CREATOR = "00000000-0000-4000-8000-000000000001"
def item(i, status="open", wrote=None, after=None, nxt="home-agent: build it", letter="a", **meta):
    """One item <letter>{i} (a by default): open, waiting behind `after` (a list of ids), its next line `nxt`, last written `wrote` (an epoch)."""
    m = {"owner": CREATOR, "project": "projects/alpha", "state": "blocked" if after else "doing", "needs": ["home-agent"], "next": nxt, **meta}
    if after: m["after"] = list(after)
    d = {"id": str(i), "subject": f"[home] item {letter}{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - 9 * H if wrote is None else wrote,
         "state_updated": now - 9 * H, "confirmed": now - 9 * H, "metadata": m}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = "home-agent"
    return f"{letter}{i}", d
STORE = T / "store"
def put(*pairs):
    """Stage the store: exactly these items (the folder is emptied first); the walker's file cache is dropped, a rewrite within one clock tick of the same size would otherwise read as unchanged."""
    for p in STORE.glob("*/*.json"): p.unlink()
    for k, d in pairs: (STORE / k[0]).mkdir(exist_ok=True); (STORE / k[0] / f"{k[1:]}.json").write_text(json.dumps(d))
    WL._CACHE.clear()
ROLES = {"home-agent": {"role": "background"}, "other-agent": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=kw.pop("deliver", deliver), sessions=lambda: None, **kw)
AUD = T / "state/audit"
def clear_state():
    if AUD.is_dir():
        for p in AUD.glob("*"): p.unlink()
    sent.clear(); WL._CACHE.clear()
def rec(): return json.loads((AUD / WL.RECORD_FILE).read_text())
def msgs_text(): return "\n".join(t for _to, t, _f in sent)
def lines_of(text): return [l for l in text.splitlines() if l.startswith("board#")]
def loop_ids(lp): return [lk.src for lk in lp.links]

# ---- 1. the ring finder on plain data
def raw_of(**spec):
    """{id: (status, after, words)}: spec value (after ids, words ids, status)."""
    out = {}
    for k, v in spec.items():
        after, words, status = (list(v) + [(), (), "open"][len(v):])[:3] if isinstance(v, (tuple, list)) else ((), (), "open")
        out[k] = (status, tuple(after), tuple(words))
    return out
SHOWN = lambda *ids: {f"board#{g[1:]}": g for g in ids}
def find(raw, stamp=None):
    e = L.links(raw, SHOWN(*raw))
    return e, L.loops(e, stamp) if stamp else L.loops(e)
e, lps = find(raw_of(a1=(("a2",),), a2=(("a1",),)))
check("1 a ring of two: one loop of two links, each item once", len(lps) == 1 and sorted(loop_ids(lps[0])) == ["a1", "a2"] and len(lps[0].links) == 2 and all(lk.form == L.AFTER for lk in lps[0].links), lps)
e, lps = find(raw_of(a1=(("a2",),), a2=(("a3",),), a3=(("a1",),)))
check("1 a ring of three, and in link order (each link's dst is the next link's src)", len(lps) == 1 and len(lps[0].links) == 3 and all(lps[0].links[i].dst == lps[0].links[(i + 1) % 3].src for i in range(3)), lps)
e, lps = find(raw_of(a1=(("a1",),)))
check("1 an `after` on itself is a ring of one", len(lps) == 1 and len(lps[0].links) == 1 and lps[0].links[0].src == lps[0].links[0].dst == "a1", lps)
e, lps = find(raw_of(a1=((), ("board#" "1",))))
check("1 a step that names its own item is no wait: no link, no ring", e == {} and lps == [], (e, lps))
e, lps = find(raw_of(a1=(("a2",), ()), a2=((), ("board#" "1",))))
check("1 a ring written in words on one side: an `after` and a step that waits, each link with its own form", len(lps) == 1 and sorted(lk.form for lk in lps[0].links) == [L.AFTER, L.WORDS], lps)
e, lps = find(raw_of(a1=((), ("board#" "2",)), a2=((), ("board#" "1",))))
check("1 a ring written in words on both sides", len(lps) == 1 and all(lk.form == L.WORDS for lk in lps[0].links), lps)
e, lps = find(raw_of(a1=(("a2",), ("board#" "2",)), a2=(("a1",),)))
check("1 a link written both ways is one link, and the `after` form stands", len(lps) == 1 and e[("a1", "a2")] == L.AFTER, (e, lps))
e, lps = find(raw_of(a1=(("a2",),), a2=(("a3",),), a3=((), (), "open")))
check("1 an acyclic chain is no ring", lps == [] and len(e) == 2, (e, lps))
e, lps = find(raw_of(a1=(("a2",),), a2=(("a1",),), a3=(("a1",),)))
check("1 an item that waits on a ring but is not in it is no part of it", len(lps) == 1 and sorted(loop_ids(lps[0])) == ["a1", "a2"], lps)
e, lps = find(raw_of(a1=(("a2",),), a2=(("a1",), (), "completed")))
check("1 a link to a closed item is no link, so no ring", lps == [] and e == {}, (e, lps))
e2, lps2 = find(raw_of(a1=(("a9",),), a2=(("a1",),)))
check("1 a link to an item that does not exist is no link, so no ring", lps2 == [] and ("a1", "a9") not in e2 and ("a2", "a1") in e2, (e2, lps2))
e, lps = find(raw_of(a1=((), ("board#" "2",), "completed"), a2=((), ("board#" "1",))))
check("1 a closed item waits on nothing: the words of its steps are no link", lps == [] and ("a1", "a2") not in e, (e, lps))
r1 = find(raw_of(a1=(("a2",),), a2=(("a1",),)))[1][0]; r2 = find(raw_of(a1=((), ("board#" "2",)), a2=((), ("board#" "1",))))[1][0]; r3 = find(raw_of(a1=(("a2",),), a2=(("a3",),), a3=(("a1",),)))[1][0]
check("1 the fingerprint names the ring, not the form of its links, and another ring has another", r1.fingerprint == r2.fingerprint and r1.fingerprint != r3.fingerprint and len(r1.fingerprint) == 6, (r1.fingerprint, r2.fingerprint, r3.fingerprint))
base = {"a1": (("a2",), ()), "a2": (("a3",), ()), "a3": (("a1",), ()), "a4": (("a1",), ()), "a5": (("a6",), ()), "a6": (("a5",), ())}
want = None; same = True
for seed in range(8):
    ks = list(base); random.Random(seed).shuffle(ks)
    raw = {k: ("open", *base[k]) for k in ks}
    got = [(tuple(lp.links), lp.fingerprint) for lp in L.loops(L.links(raw, SHOWN(*raw)), lambda s, d: 0.0)]
    want = want or got; same = same and got == want
check("1 the answer does not depend on the order the items are read (and the lowest item numbers come first)", same and [len(x[0]) for x in want] == [3, 2], want)
chord = raw_of(a1=(("a2", "a3"),), a2=(("a3",),), a3=(("a1", "a2"),))
e, _ = find(chord)
lps = L.loops(e, lambda s, d: 5.0 if (s, d) == ("a1", "a3") else 1.0)
check("1 a part with more than one ring is told as the shortest ring through the newest link", len(lps) == 1 and lps[0].newest == L.Link("a1", "a3", L.AFTER) and loop_ids(lps[0]) == ["a1", "a3"], lps)
lps = L.loops(e, lambda s, d: 5.0 if (s, d) == ("a3", "a2") else 1.0)
check("1 …through another link when that is the newest", lps[0].newest.src == "a3" and lps[0].newest.dst == "a2" and loop_ids(lps[0]) == ["a3", "a2"], lps)
e, _ = find(raw_of(a1=(("a2",),), a2=(("a1",),)))
check("1 the newest link is the one with the latest stamp", L.loops(e, lambda s, d: 9.0 if s == "a1" else 1.0)[0].newest.src == "a1" and L.loops(e, lambda s, d: 9.0 if s == "a2" else 1.0)[0].newest.src == "a2")
check("1 …and a tie goes to the higher item number, whichever order the items came", L.loops(e, lambda s, d: 3.0)[0].newest.src == "a2" and L.loops(dict(reversed(list(e.items()))), lambda s, d: 3.0)[0].newest.src == "a2")
long = {f"a{i}": (("a%d" % (i + 1),), ()) for i in range(1, 3000)}; long["a3000"] = (("a1",), ())
raw = {k: ("open", *v) for k, v in long.items()}
check("1 a ring of three thousand is found without reaching the recursion limit", len(L.loops(L.links(raw, SHOWN(*raw)))[0].links) == 3000)
it_words = item(1, nxt="home-agent: wait for board#" "2 to close, then ship it")[1]
check("1 reads: the words of an open step that waits on an item are a link, a plain line is none, a closed item reads nothing",
      L.reads(it_words) == ((), ("board#" "2",)) and L.reads(item(1, nxt="home-agent: build it")[1]) == ((), ()) and L.reads(item(1, status="completed", after=["a2"])[1]) == ((), ()), L.reads(it_words))
check("1 reads: the `after` list and the item lines of a list of waits are links, each id once", L.reads(item(1, after=["a2", "a2", "a3"])[1])[0] == ("a2", "a3"))

# ---- 2. the walk on a staged store
clear_state()
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a1"]))
r = WL.loop_pass(now=now, env=env())
fs = rec()["findings"]
check("2 a link-link ring of two is found: one loop, one finding for each of its two items, all of the category", r["loops"] == 1 and r["fresh"] == 2 and r["found"] == 1 and sorted(f["id"] for f in fs) == ["board#" "1", "board#" "2"]
      and all(f["category"] == "wait-loop" for f in fs), (r, fs))
check("2 …told to the movers: one message to the session that moves both, a line for each item", len(sent) == 1 and sent[0][0] == "home-agent" and sorted(l.split(" ")[0] for l in lines_of(sent[0][1])) == ["board#" "1", "board#" "2"], sent)
txt = sent[0][1]
check("2 …headed as a wait loop check, lines as '<id> · <check> · <evidence> · <fix>'", re.match(r"\[stackshot\] Wait loop check .+: 2 item\(s\) for you", txt) and all(len(l.split(" · ")) == 4 for l in lines_of(txt)), txt)
check("2 …naming the ring (the newest link's item first, back to it) and the newest link", "board#" "2 → board#" "1 → board#" "2" in txt and "newest link: board#" "2's wait on board#" "1 (an after link, written " in txt, txt)
l1 = next(l for l in lines_of(txt) if l.startswith("board#" "1 ")); l2 = next(l for l in lines_of(txt) if l.startswith("board#" "2 "))
check("2 …and what to do: the item that holds the newest link is told to end its own wait, the other to ask its mover", "end your wait on board#" "1 (clear its `after`)" in l2 and "board#" "2's mover ends its wait on board#" "1" in l1, (l1, l2))
check("2 …no machine and no fleet tool named in what is told", not re.search(r"sala|hp-", txt, re.I), txt)
check("2 the record is <state>/audit/wait-loops.json, shaped like the filing pass's, and no run record", (AUD / "wait-loops.json").exists() and rec()["items_read"] == 2 and all(f.get("sent") for f in fs) and audit.runs() == [] and audit.last() is None, rec())
check("2 the loop is one row of the loop log: its fingerprint and its items in ring order", [(x["fp"], x["items"]) for x in WL.read_log()] == [(r1.fingerprint, ["board#" "2", "board#" "1"])], WL.read_log())

clear_state()
put(item(11, wrote=now - 3 * H, after=["a12"]), item(12, wrote=now - 2 * H, after=["a13"]), item(13, wrote=now - H, after=["a11"]))
r = WL.loop_pass(now=now, env=env())
check("2 a link-link ring of three is found, and its three items are told", r["loops"] == 1 and r["fresh"] == 3 and len(lines_of(msgs_text())) == 3 and "board#" "13 → board#" "11 → board#" "12 → board#" "13" in msgs_text(), (r, msgs_text()))

clear_state()
put(item(21, wrote=now - 3 * H, after=["a22"]), item(22, wrote=now - H, nxt="home-agent: wait for board#" "21 to close, then ship it"))
r = WL.loop_pass(now=now, env=env())
txt = msgs_text()
check("2 a link-words ring (one side waits only in its step's words) is found and both items are told", r["loops"] == 1 and r["fresh"] == 2 and sorted(f["id"] for f in rec()["findings"]) == ["board#" "21", "board#" "22"], (r, txt))
check("2 …the newest link is the words one, said as such, and the fix says to reword the step", "newest link: board#" "22's wait on board#" "21 (a step that waits in words, written " in txt and "reword its step as the action to take now" in txt, txt)

clear_state()
put(item(31, wrote=now - H, after=["a32"]), item(32, wrote=now - H, after=["a33"]), item(33, wrote=now - H),                      # an acyclic chain
    item(34, wrote=now - H, after=["a35"]), item(35, status="completed", wrote=now - H, after=["a34"], outcome="done"),            # the target closed
    item(36, wrote=now - H, after=["a99"]), item(37, wrote=now - H, after=["a36"]),                                               # the target missing
    item(38, wrote=now - H, nxt="home-agent: wait for board#" "39 to close"), item(39, wrote=now - H, nxt="home-agent: wait for board#" "40 to close"),   # a chain in words
    item(40, wrote=now - H, nxt="home-agent: wait for board#" "98 to close"))                                                       # in words, the target missing
r = WL.loop_pass(now=now, env=env())
check("2 an acyclic chain, a closed target and a missing target are not reported (also in words), and nothing is sent", r["loops"] == 0 and r["fresh"] == 0 and sent == [] and r["links"] >= 5, (r, sent))
check("2 …and no record and no log row is written for them", not (AUD / "wait-loops.json").exists() and WL.read_log() == [], os.listdir(AUD))

clear_state()
put(item(41, wrote=now - H, after=["a41"]))
r = WL.loop_pass(now=now, env=env())
check("2 an item that waits on itself is a ring of one: told, as its own wait", r["loops"] == 1 and r["fresh"] == 1 and "board#" "41's wait on itself" in msgs_text() and "end your wait on board#" "41" in msgs_text(), (r, msgs_text()))

# ---- 3. the newest link, and when a link was first seen
clear_state()
put(item(1, wrote=now - H, after=["a2"]), item(2, wrote=now - 5 * H, after=["a1"]))
WL.loop_pass(now=now, env=env())
check("3 the link of the item written last is the newest, whichever item number it has (a lower number here)", "newest link: board#" "1's wait on board#" "2" in msgs_text() and "board#" "1 → board#" "2 → board#" "1" in msgs_text(), msgs_text())
seen = json.loads((AUD / "wait-links.json").read_text())["seen"]
check("3 the first-seen stamps are kept in the walker's own file: a link already standing counts from the last write of its item", set(seen) == {"a1>a2", "a2>a1"} and abs(seen["a1>a2"] - (now - H)) < 1 and abs(seen["a2>a1"] - (now - 5 * H)) < 1, seen)
sent.clear()
put(item(1, wrote=now - H, after=["a2"]), item(2, wrote=now + 600, after=["a1"]))      # a2 is written afterwards: its old link does not become the new one
WL.loop_pass(now=now + 900, env=env())
seen2 = json.loads((AUD / "wait-links.json").read_text())["seen"]
check("3 a write to an item later does not make its standing link new: the stamps are as first seen", seen2 == seen and sent == [], (seen2, sent))
clear_state()
put(item(1, wrote=now - 5 * H, after=["a2"]), item(2, wrote=now - 5 * H, after=["a1"]))
WL.loop_pass(now=now, env=env())
sent.clear(); WL.loop_pass(now=now + 60, env=env())
put(item(1, wrote=now - 5 * H, after=["a2"]), item(2, wrote=now + 120, after=["a1"]), item(3, wrote=now + 130, after=["a2"]))     # a third item joins
r = WL.loop_pass(now=now + 120, env=env())
check("3 an item that waits on the ring but is no part of it changes nothing: the ring is the same ring, and told no more", r["loops"] == 1 and sent == [] and r["repeats"] == 2, (r, sent))
put(item(1, wrote=now - 5 * H, after=["a2"]), item(2, wrote=now - 5 * H, after=["a1"]))
WL.loop_pass(now=now + 180, env=env())
check("3 a link that is gone leaves the stamps", set(json.loads((AUD / "wait-links.json").read_text())["seen"]) == {"a1>a2", "a2>a1"}, json.loads((AUD / "wait-links.json").read_text()))

# ---- 4. told once
clear_state()
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a1"]))
WL.loop_pass(now=now, env=env()); first = rec(); sent.clear()
r = WL.loop_pass(now=now + 60, env=env())
check("4 a ring that stands is not told again the next minute", sent == [] and r["fresh"] == 0 and r["repeats"] == 2 and r["found"] == 0, (r, sent))
check("4 …and its record is as it was (the first send's stamps stand)", rec() == first, rec())
put(item(1, wrote=now + 100, after=["a2"], nxt="home-agent: still blocked"), item(2, wrote=now + 100, after=["a1"], nxt="home-agent: still blocked"))
r = WL.loop_pass(now=now + 120, env=env())
check("4 …nor because its items were written: a write is no new ring, only the re-tell cadence sends it again", sent == [] and r["fresh"] == 0 and r["repeats"] == 2, (r, sent))
RH = _cfg.audit_remind_hours() * 3600
r = WL.loop_pass(now=now + RH - 60, env=env())
check("4 …not before the re-tell hours have passed", sent == [] and r["fresh"] == 0, (r, sent))
r = WL.loop_pass(now=now + RH + 60, env=env())
check("4 …and again once they have, worded as a later try", r["fresh"] == 2 and len(sent) == 1 and "second try" in sent[0][1], (r, sent))
check("4 …with the count of tries on the record", sorted(f["tries"] for f in rec()["findings"]) == [2, 2], rec()["findings"])
check("4 …a ring told again is not a new ring: the log has one row", len(WL.read_log()) == 1, WL.read_log())
clear_state()
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a1"]))
WL.loop_pass(now=now, env=env()); sent.clear()
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a3"]), item(3, wrote=now - H, after=["a1"]))      # the ring changes: the third item joins it
r = WL.loop_pass(now=now + 60, env=env())
check("4 a ring that changes (an item joins it) is another ring and is told at once, to all three", r["fresh"] == 3 and r["found"] == 1 and len(sent) == 1 and len(lines_of(sent[0][1])) == 3 and "board#" "3" in sent[0][1], (r, sent))
check("4 …and the first ring's findings left the record", sorted(f["id"] for f in rec()["findings"]) == ["board#" "1", "board#" "2", "board#" "3"] and len({f["detail"].split(":")[0] for f in rec()["findings"]}) == 1, rec()["findings"])
sent.clear()
put(item(1, wrote=now - 3 * H), item(2, wrote=now - H), item(3, wrote=now - H))                                      # the ring ends
r = WL.loop_pass(now=now + 120, env=env())
check("4 a ring that ended leaves the record and sends nothing", r["loops"] == 0 and sent == [] and rec()["findings"] == [], (r, rec()["findings"]))
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a3"]), item(3, wrote=now - H, after=["a1"]))      # and it comes back
r = WL.loop_pass(now=now + 180, env=env())
check("4 …and is told afresh when it comes back", r["fresh"] == 3 and r["found"] == 1 and len(sent) == 1, (r, sent))
check("4 …counted again in the log (a ring that came back is a ring found)", len(WL.read_log()) == 3, WL.read_log())

# ---- 5. the pass
clear_state()
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a1"]))
rd = WL.loop_pass(now=now, env=env(), dry=True)
check("5 a dry run lists the findings and sends and writes nothing", rd["dry"] is True and len(rd["detail"]) == 2 and sent == [] and not list(AUD.glob("*")), (rd.keys(), os.listdir(AUD)))
(AUD / f"run-{dt.date.fromtimestamp(now):%Y-%m-%d}-050000.json").write_text(json.dumps({"started": now - 60, "finished": None, "findings": []}))
rs = WL.loop_pass(now=now, env=env())
check("5 a daily run in progress: the pass skips, sends nothing and writes nothing", rs == {"skipped": "a daily run is in progress"} and sent == [] and not (AUD / "wait-loops.json").exists() and not (AUD / "wait-links.json").exists(), rs)
check("5 …and a dry run is never refused for a running one", WL.loop_pass(now=now, env=env(), dry=True)["dry"] is True)
clear_state()
failing = lambda to, text, fyi=False: (False, "[500] down")
WL.loop_pass(now=now, env=env(deliver=failing))
check("5 a message no one received leaves its findings without a send stamp", not any(f.get("sent") for f in rec()["findings"]) and len(rec()["findings"]) == 2, rec()["findings"])
r = WL.loop_pass(now=now + 60, env=env())
check("5 …so the next minute tells the ring", r["fresh"] == 2 and len(sent) == 1 and all(f.get("sent") for f in rec()["findings"]), (r, sent))
check("5 …and the ring is one row of the log, not two", len(WL.read_log()) == 1, WL.read_log())
clear_state()
real_cap = WL.LOOP_CAP; WL.LOOP_CAP = 3
put(*[p for n in (1, 3, 5) for p in (item(n, wrote=now - 3 * H, after=[f"a{n + 1}"]), item(n + 1, wrote=now - H, after=[f"a{n}"]))])          # three rings of two: six findings
try:
    r = WL.loop_pass(now=now, env=env())
    check("5 the cap: one pass sends at most LOOP_CAP findings, and the rest are not recorded as sent", r["fresh"] == 3 and r.get("held") == 3 and len(rec()["findings"]) == 3 and sum(len(lines_of(t)) for _to, t, _f in sent) == 3, (r, rec()["findings"]))
    sent.clear(); r = WL.loop_pass(now=now + 60, env=env())
    check("5 …and the next minute sends the others", r["fresh"] == 3 and r["repeats"] == 3 and sum(len(lines_of(t)) for _to, t, _f in sent) == 3 and len(rec()["findings"]) == 6, (r, rec()["findings"]))
finally:
    WL.LOOP_CAP = real_cap
clear_state()
put(item(1, wrote=now - H), item(2, wrote=now - H))
calls = []; real_row = WL.row_of
WL.row_of = lambda d: (calls.append(1), real_row(d))[1]
try:
    WL.loop_pass(now=now, env=env())
    n1 = len(calls)
    WL.loop_pass(now=now + 60, env=env())
    check("5 the store walk reads a file again only when it changed: a quiet board is parsed once", n1 == 2 and len(calls) == 2, (n1, len(calls)))
    p2 = STORE / "a/2.json"; d2 = json.loads(p2.read_text()); d2["metadata"]["after"] = ["a1"]; p2.write_text(json.dumps(d2))
    WL.loop_pass(now=now + 120, env=env())
    check("5 …a changed file is read again, and an unchanged one is not", len(calls) == 3, len(calls))
    p2.unlink()
    r = WL.loop_pass(now=now + 180, env=env())
    check("5 …a file that is gone leaves the walk", r["items"] == 1 and "a2" not in WL._CACHE[str(T / "store")], r)
finally:
    WL.row_of = real_row
check("5 a quiet board writes no record and no log, only (when links stand) the walker's own stamp file", not (AUD / "wait-loops.json").exists() and WL.read_log() == [])
(STORE / "a/9.json").write_text("{not json"); (STORE / "a/x.json").write_text("{}")
check("5 a file that does not parse is left out of the walk", WL.loop_pass(now=now + 240, env=env())["items"] == 1)
(STORE / "a/9.json").unlink(); (STORE / "a/x.json").unlink()

# ---- 6. the server's tick
from stackshot.web import server      # imports the wiring that installs the service hooks
from stackshot.service import audit_ticks as audit_ticks_svc
from stackshot.service import messaging as _messaging
from stackshot.service import runner as _runner
clear_state()
put(item(1, wrote=now - 3 * H, after=["a2"]), item(2, wrote=now - H, after=["a1"]))
msgs = []
real_msg = _messaging._message
_messaging._message = lambda to, text, sender, auth="", origin="", fyi=False: (msgs.append((to, text, sender, auth, origin, fyi)), "delivered to " + to)[1]
try:
    _cfg.CFG["audit"]["enabled"] = False
    check("6 the tick stands still while the audit is off", audit_ticks_svc._loop_tick() is None and msgs == [])
    _cfg.CFG["audit"]["enabled"] = True; _cfg.CFG["audit"]["mode"] = "agent"
    check("6 …and in agent mode (the rollback)", audit_ticks_svc._loop_tick() is None and msgs == [])
    _cfg.CFG["audit"]["mode"] = "script"
    res = audit_ticks_svc._loop_tick()
    check("6 with the audit on it walks the store and sends through the server's own message function, as the audit's sender, from a script",
          res is not None and res["loops"] == 1 and msgs and all(m[2] == "stackshot audit" and m[3] == "server" and m[5] is False for m in msgs), (res, msgs[:1]))
    n = len(msgs)
    audit_ticks_svc._loop_tick()
    check("6 the next tick sends nothing new", len(msgs) == n)
finally:
    _messaging._message = real_msg
tbl = [t for t in _runner.ticks()]
names = [t.name for t in tbl]
lt = tbl[names.index("loop_tick")] if "loop_tick" in names else None
check("6 the runner has a loop tick: in the fleet group, paced, board-gated, right after the hand-back tick", lt is not None and lt.group == "fleet" and lt.board is True and names.index("loop_tick") == names.index("handback_tick") + 1,
      [(t.name, t.group) for t in tbl])

# ---- 7. the weekly report
from stackshot.tools import refusal_report as RR
clear_state()
today = dt.datetime.fromtimestamp(now, _cfg.tz()).date()
monday = RR.week_start(today) - dt.timedelta(days=7)
a, b = RR.week_bounds(monday); p, _ = RR.week_bounds(monday - dt.timedelta(days=7))
WL.log_found([{"at": a + 3600, "fp": "aaaaaa", "items": ["board#" "1", "board#" "2"]}, {"at": a + 2 * 86400, "fp": "bbbbbb", "items": ["board#" "3"]}, {"at": p + 3600, "fp": "cccccc", "items": ["board#" "4"]}], b + 86400)
check("7 log_count counts the loops found in a week, and only that week", WL.log_count(a, b) == 2 and WL.log_count(p, a) == 1 and WL.log_count(b, b + 7 * 86400) == 0, (WL.log_count(a, b), WL.log_count(p, a)))
cur, prev = RR.collect(monday)
check("7 the week's counts carry the loops, this week and the one before", cur["loops"] == 2 and prev["loops"] == 1, (cur.get("loops"), prev.get("loops")))
cur["calls"] = {"stackshot_update": 3}; prev["calls"] = {"stackshot_update": 2}
txt = RR.build(monday, cur, prev)
check("7 the report has one line for them, in the report's own form: the count and the week before", sum(1 for l in txt.splitlines() if "wait loops found" in l) == 1 and "wait loops found (items that wait on each other, told to their movers): 2; the week before 1" in txt, txt)
none = {**cur, "loops": 0}; nonep = {**prev, "loops": 0}
check("7 …and no line when there were none in either week, nor when the counts are not there (an older caller)", "wait loops" not in RR.build(monday, none, nonep) and "wait loops" not in RR.build(monday, {k: v for k, v in cur.items() if k != "loops"}, {k: v for k, v in prev.items() if k != "loops"}), None)
check("7 …only the week before: the line shows the count of this week as zero", "wait loops found (items that wait on each other, told to their movers): 0; the week before 1" in RR.build(monday, none, prev), RR.build(monday, none, prev))
check("7 the log keeps 60 days: older rows are dropped as a new one is written", (WL.log_found([{"at": b + 90 * 86400, "fp": "dddddd", "items": ["board#" "5"]}], b + 90 * 86400), WL.log_count(0, b + 10 * 86400))[1] == 0)

# ---- 8. what is a wait: the words reader, the list modes, the numbers two letters share, the shortest ring
bd = lambda n: f"board#{n}"
_gh = _cfg.CFG.setdefault("github", {}); _had_letter = _gh.get("issues_letter"); _gh["issues_letter"] = "a"      # the fixtures' items are a<n>: the issue letter, as the board's own board#N names it
def walk_loops(*pairs, at=None):
    """Stage the store, walk once on a clean slate, and give the pass's result."""
    clear_state(); put(*pairs)
    return WL.loop_pass(now=at or now, env=env())
def pair_words(phrase, n=2):
    """Item a1 whose step says `phrase` (it names item n) and item a2 that waits behind a1: a loop only if the step really waits for a2."""
    return (item(1, wrote=now - H, nxt=f"home-agent: {phrase.format(B=bd(n))}"), item(2, wrote=now - H, after=["a1"]))
for i, phrase in enumerate(("after merging, post the result on {B}", "when done, tell {B}", "once shipped, close {B}", "once I finish, {B} can start"), 1):
    r = walk_loops(*pair_words(phrase))
    check(f"8 not a wait ({i}): a step that only names the item it acts on afterward ('{phrase.format(B='<item>')}') makes no link, no loop, no message", r["loops"] == 0 and sent == [] and L.waits_on(phrase.format(B=bd(2))) == [], (r, sent))
r = walk_loops(item(61, letter="a", wrote=now - H, nxt=f"home-agent: once the spike is proven, start build 2 and the answer tools of {bd(62)}"), item(62, letter="a", wrote=now - H, after=["a61"]))
check("8 not a wait (5): an open item that is told to start a later one, which waits behind it (a chain), is no loop and is told nothing", r["loops"] == 0 and sent == [] and r["links"] == 1, (r, sent))
bad = []
for phrase in ("wait for {B} to close", "waiting on {B}", "waits on {B} to close", "awaiting {B}", "blocked on {B}", "blocked by {B}", "pending {B}", "wait until {B} closes", "until {B} is closed",
               "after {B} lands", "once {B} is merged", "when {B} is done", "after the item {B} is answered"):
    r = walk_loops(*pair_words(phrase + ", then ship it"))
    if not (r["loops"] == 1 and r["fresh"] == 2 and L.waits_on(phrase.format(B=bd(2))) == [bd(2)]): bad.append((phrase, r["loops"]))
check("8 a wait: each phrase that waits for the item is a link, and the ring with an `after` back is found and told to both", not bad, bad)
bad = [p_ for p_ in ("do not wait for {B}", "no need to wait until {B} closes", "wait for {B} or a day", "either {B} lands or the date comes", "wait for it unless {B} is closed", "tell {B}, once it is done", "close {B}") if L.waits_on(p_.format(B=bd(2)))]
check("8 not a wait: a negation, an alternative and an id that is only the object of an action are skipped, an ambiguous clause is no link", not bad, bad)
check("8 a wait stays one when the words stand on a line of a longer step, and a code span or a fenced block is not read",
      L.waits_on(f"home-agent: build it.\nThen wait for {bd(3)} to close.") == [bd(3)] and L.waits_on(f"home-agent: run `wait for {bd(3)}`") == [] and L.waits_on(f"home-agent: x\n```\nwait for {bd(3)}\n```") == [])

stepdone = {"text": f"home-agent: wait for {bd(2)} to close", "status": "done", "by": "home-agent", "at": 1}
r = walk_loops(item(1, wrote=now - H, steps=[stepdone]), item(2, wrote=now - H, after=["a1"]))
check("8 a done step is no wait: its words make no link, and no loop", L.reads(item(1, steps=[stepdone])[1]) == ((), ()) and r["loops"] == 0 and sent == [], (r, sent))
r = walk_loops(item(1, wrote=now - H, steps=[{**stepdone, "status": "dropped"}]), item(2, wrote=now - H, after=["a1"]))
check("8 …nor a dropped step", r["loops"] == 0 and sent == [], (r, sent))

lst = lambda mode, *waits: dict(wait_kind="list", wait_mode=mode, until="2099-01-05", waits=list(waits))
ITEM2, TIME = {"kind": "item", "after": "a2"}, {"kind": "time", "until": "2099-01-03"}
r = walk_loops(item(1, wrote=now - H, **lst("all", ITEM2, TIME)), item(2, wrote=now - H, after=["a1"]))
check("8 a list of waits in mode all: its item line is a link, and the ring is found and told", r["loops"] == 1 and r["fresh"] == 2 and r["links"] == 2 and sorted(f["id"] for f in rec()["findings"]) == [bd(1), bd(2)], (r, sent))
r = walk_loops(item(1, wrote=now - H, **lst("any", ITEM2, TIME)), item(2, wrote=now - H, after=["a1"]))
check("8 the same list in mode any is no link (it ends when the time comes): no loop, nothing told", r["loops"] == 0 and r["links"] == 1 and sent == [], (r, sent))
check("8 reads: mode any reads no item line, mode all reads it, an item waiting on a plain `after` beside an any list keeps the `after`",
      L.reads(item(1, **lst("any", ITEM2, TIME))[1]) == ((), ()) and L.reads(item(1, **lst("all", ITEM2, TIME))[1]) == (("a2",), ()) and L.reads(item(1, after=["a3"], **lst("any", ITEM2, TIME))[1]) == (("a3",), ()))

# two letters of one number: the issue letter's item (a, set below) and a closed one of another letter (q)
closed = lambda i: item(i, letter="q", status="completed", wrote=now - 9 * H, outcome="done")
r = walk_loops(item(61, letter="a", wrote=now - H, nxt=f"home-agent: wait for {bd(62)} to close"), item(62, letter="a", wrote=now - H, after=["a61"]), closed(61), closed(62))
check("8 a ring is found where closed items of another letter share the numbers (board#N is the issue letter's item, not the later letter's closed one)", r["loops"] == 1 and r["fresh"] == 2 and r["links"] == 2, (r, sent))
r1_ = walk_loops(item(61, letter="a", wrote=now - H, after=["a62"]), item(62, letter="a", wrote=now - H, after=["a61"]), closed(61), closed(62))
n1 = len(sent); r2_ = WL.loop_pass(now=now + 60, env=env()); r3_ = WL.loop_pass(now=now + 120, env=env())
check("8 …and a ring told once is not told again the next minute, nor the one after, though the closed items share its numbers", r1_["fresh"] == 2 and n1 == 1 and r2_["fresh"] == 0 and r3_["fresh"] == 0 and len(sent) == 1 and r2_["repeats"] == 2, (r1_, r2_, r3_, len(sent)))
check("8 the shown id of a shared number is the issue letter's whatever its status, else an open one, else the lowest letter",
      WL.by_shown_of({"a5": "completed", "q5": "open", "r5": "open"})[bd(5)] == "a5" and WL.by_shown_of({"q5": "completed", "r5": "open"})[bd(5)] == "r5" and WL.by_shown_of({"q5": "open", "r5": "open"})[bd(5)] == "q5")

# the shortest ring through the newest link: a ring of four with a shorter way back inside it
e, _ = find(raw_of(a1=(("a2",),), a2=(("a3", "a4"),), a3=(("a1",),), a4=(("a5",),), a5=(("a1",),)))
lps = L.loops(e, lambda s, d: 5.0 if (s, d) == ("a1", "a2") else 1.0)
check("8 a ring of four with a shorter ring inside it: the ring told is the shortest through the newest link, not the first one found", len(lps) == 1 and loop_ids(lps[0]) == ["a1", "a2", "a3"], lps)

if _had_letter is None: _gh.pop("issues_letter", None)
else: _gh["issues_letter"] = _had_letter
if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: wait loop scenario, {len(ran)} checks")
