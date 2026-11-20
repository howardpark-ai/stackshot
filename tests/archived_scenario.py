"""Scenario test for the router's `archived` ruling: a notice the router delivers to no one and only records for the daily digest record
(the page pass, an image it cannot read, a quiet hour, a weak mention, what the call is unsure of). The word was `held` once, which reads as
waiting for a session's next turn; that is a different thing and keeps the word. Fixture data, no live store, no network.

Covers:
  1. A new notice of that kind is ruled archived in code (the page-pass and image rules, the call's own answer and its earlier word held),
     logged archived in the routing log and live.jsonl with an archived reason, listed archived by the digest, counted archived by status,
     and reported archived by the get tool; nothing in those says held.
  2. An old record is read as archived by every reader: a routing line that says held with no mark and a reason about the digest (read, lookup,
     counts, the get tool), an old live.jsonl line (the last line of a notice, the trace, the digest, its text, status). The record on disk stays as written.
  3. A hold for a session's next turn still says held: a ruling written with its kind (rule, record_auto), a line of an older router whose reason is
     worded as one, a live line that names the agent it was filed for (held_for), and the digest leaves such a notice out when it waits for an agent.
  4. A held written by hand with no kind (the route tool's old word) is written archived, and the route tool's reply says so.
  5. What is delivered to no one is archived even when it came from a front agent's gate: a notice the gate told to no one, and the router's front
     fyi / page-owed hold with no agent filed (held_for empty), is ruled archived in the log and in live.jsonl, listed by the digest, reported archived by get;
     an old line of that kind reads archived too (the marks decide first, the reason text last).
  6. An old router-ruled held whose model-written reason starts "held: " is archived (the reason text alone never makes a session hold); the audit split
     whose keepers were all held by an earlier try is ruled held with its `audit` mark; a live line names a hold only by held_for.

    tests/run-suite archived        → exit 0 / 1"""
import json, os, re, sys, time, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="archivedtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
S, A, X, B = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444"
for d in ("store/a", "fleet/a", "state/s2", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"},
                                                      X: {"name": "work-osprey-x", "machine": "a", "url": "", "seen": "x"}, B: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-x": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", "work-osprey", agents=AGENTS, back_agents={"work-osprey-x": AGENTS["work-osprey-x"]}),
    "projects/beta": page("Beta", "home-beta", agents={"home-beta-main": "Oliver's point of contact"})}}))
(T / "store/next-id").write_text("10")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://x.slack.com/archives/C0000000001", "items": None, "added": 1, "by": "t"}],
                                                   "projects/beta": [{"url": "https://x.slack.com/archives/C0000000002", "items": None, "added": 1, "by": "t"}]}))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.router import router as _router; from stackshot.router import router_live as live
from stackshot.web.tools import get as _wt_get
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
KEY, BKEY = "projects/alpha", "projects/beta"
NOW = time.time()
def rec(key, text, kind="message", who="home-beta", **kw):
    nid = routing.record(key, kind=kind, to="", label=f"message to {key}", who=who, text=text, target="project-wide", pilot=True, live=True, **kw)
    live.stash(nid, text)
    return nid
def notice(key, nid): return next(n for n in routing.read(key) if n["id"] == nid)
def disk(key): return [json.loads(l) for l in routing._file(key).read_text(encoding="utf-8").splitlines()]
def rulings_on_disk(key, nid): return [d for d in disk(key) if d.get("id") == nid and "ruling" in d and "kind" not in d]
def live_lines(): return live._router._read(live.live_path())
def put_live(d): live.live_path().parent.mkdir(parents=True, exist_ok=True); open(live.live_path(), "a", encoding="utf-8").write(json.dumps(d) + "\n")
def old_ruling(key, nid, ruling, reason, **kw): routing._append(key, {"id": nid, "ruling": ruling, "to": "", "reason": reason, "by": live.BY, "ts": time.time(), **kw})

# ---- 1. a new notice that goes to no one is archived
cx = _router.Context()
n_pp = {"id": "pp0001", "ts": NOW, "kind": "message", "label": f"message to {KEY}", "who": "nightly-job", "to": "", "target": "project-wide", "pilot": True, "live": True, "text": "keeper: the page is over budget"}
ln_pp = _router.code_rule(KEY, n_pp, KEY, cx, [])
check("1a: the page-pass rule rules a notice archived, not held", ln_pp and ln_pp["rule"] == "page-pass" and ln_pp["ruling"] == "archived" and not ln_pp.get("target"), ln_pp)
n_im = {**n_pp, "id": "im0001", "who": "home-beta", "text": "[files: photo.png]"}
ln_im = _router.code_rule(KEY, n_im, KEY, cx, [])
check("1b: an image-only notice is archived by the image rule, with an archived reason", ln_im and ln_im["rule"] == "image" and ln_im["ruling"] == "archived" and "archived for the digest" in ln_im["reason"] and "held" not in ln_im["reason"], ln_im)
check("1c: the router's judge knows archived and not held as a ruling of the thin call, and its prompt names archived", "archived" in _router.CALL_RULINGS and "held" not in _router.CALL_RULINGS and "- archived:" in _router.RUBRIC and "- held:" not in _router.RUBRIC, _router.CALL_RULINGS)
n_call = notice(KEY, rec(KEY, "something unclear about the vendor"))
ln_call = _router.call_line({"id": n_call["id"], "ruling": "archived", "target": "", "reason": "unsure", "for_owner": False}, n_call, KEY, KEY, cx, "t")
ln_old = _router.call_line({"id": n_call["id"], "ruling": "held", "target": "", "reason": "unsure", "for_owner": False}, n_call, KEY, KEY, cx, "t")
check("1d: the call's answer archived is archived, and its earlier word held is read as archived (a fallback is not made of it)", ln_call["ruling"] == "archived" and ln_old["ruling"] == "archived" and ln_old.get("source") == ln_call.get("source") and ln_old.get("rule") == ln_call.get("rule"), (ln_call, ln_old))

n_img = rec(KEY, "[files: photo.png]"); n_page = rec(KEY, "keeper: the page is over budget", who="nightly-job")
res = live.tick(now=NOW)
r_img, r_page = notice(KEY, n_img), notice(KEY, n_page)
check("1e: a live notice the router archives is ruled archived in the routing log, by the router, with the archived reason", r_img["ruling"] == "archived" and r_img["ruled_by"] == live.BY and r_img["reason"].startswith("image not read") and "archived for the digest" in r_img["reason"]
      and r_page["ruling"] == "archived", (r_img, r_page, res))
check("1f: …the ruling line on disk says archived and carries no next_turn mark (it is no hold for a session)", [d["ruling"] for d in rulings_on_disk(KEY, n_img)] == ["archived"] and all("next_turn" not in d for d in rulings_on_disk(KEY, n_img)), rulings_on_disk(KEY, n_img))
l_img = [d for d in live_lines() if d.get("id") == n_img and d.get("status") == "ruled"]
check("1g: …and live.jsonl logs it archived", len(l_img) == 1 and l_img[0]["ruling"] == "archived" and l_img[0]["rule"] == "image", l_img)
last = live._last()
rows, quiet, pagepass = live._digest_items(KEY, NOW, last, {"sent": {}})
check("1h: the digest lists the archived notice (main group) and the archived page-pass notice (its own group)", [r[1]["id"] for r in rows] == [n_img] and [r[1]["id"] for r in pagepass] == [n_page] and quiet == [], (rows, pagepass))
txt = live.digest_text(KEY, rows, "main", False)
check("1i: the digest text says archived, never held", re.search(r"1 notice was archived ", txt) and "The router ruled these archived; nothing is owed on an archived one." in txt and "held" not in txt, txt)
txt_pp = live.digest_text(KEY, pagepass, "pagepass", False)
check("1j: …the page-pass group's head too", "archived for the page pass" in txt_pp and "held" not in txt_pp, txt_pp)
st = next(r for r in live.status(now=NOW) if r["project"] == KEY)
check("1k: status counts them under archived_since_digest, and its table has an archived column", st["archived_since_digest"] == 2 and "held_since_digest" not in st and "archived" in live.render(live.status(now=NOW)).splitlines()[1], st)
rep = _wt_get._notice_report(n_img)
check("1l: the get tool reports the ruling as archived", "ruling: archived (kept in the daily digest record" in rep and "ruling: held" not in rep, rep)
c = routing.counts([KEY], now=NOW + 10)
check("1m: the counts keep archived apart from held", c["archived"] == 2 and c["held"] == 0, c)

# ---- 2. an old record is read as archived by every reader
o1, o2 = rec(BKEY, "old photo [files: a.png]"), rec(BKEY, "old page pass", who="nightly-job")
old_ruling(BKEY, o1, "held", "image not read: the notice is only a file or an image, which the router cannot read; held for the digest")
old_ruling(BKEY, o2, "held", "page pass")
check("2a: routing.read reads an old held ruling (no mark, a reason about the digest, or the page pass) as archived", notice(BKEY, o1)["ruling"] == "archived" and notice(BKEY, o2)["ruling"] == "archived", (notice(BKEY, o1), notice(BKEY, o2)))
check("2b: …and routing.lookup too", routing.lookup(o1, BKEY)[1]["ruling"] == "archived" and routing.lookup(o2)[1]["ruling"] == "archived")
check("2c: …the record on disk stays as written", [d["ruling"] for d in rulings_on_disk(BKEY, o1)] == ["held"] and "next_turn" not in rulings_on_disk(BKEY, o1)[0], rulings_on_disk(BKEY, o1))
s1 = rec(BKEY, "a completion for the builder"); old_ruling(BKEY, s1, "held", "held: asks nothing (closed)")
s2 = rec(BKEY, "an answer for the front agent"); old_ruling(BKEY, s2, "held", "written onto the item it names, not delivered: an answer to work-osprey-main's question, and the person is not in that conversation")
s3 = rec(BKEY, "a page owed"); old_ruling(BKEY, s3, "held", "held: front agent, the page is owed (page-owed)")      # the front gate told nobody: filed for no one
s4 = rec(BKEY, "an fyi for the front agent"); old_ruling(BKEY, s4, "held", "held: front agent, work-osprey-main (rides its next turn, starts none)")
check("2d: an old held worded as a line filed for a session's next turn stays held (the three worded reasons); one the gate told to no one reads archived", all(notice(BKEY, i)["ruling"] == "held" for i in (s1, s2, s4)) and notice(BKEY, s3)["ruling"] == "archived", [notice(BKEY, i)["ruling"] for i in (s1, s2, s3, s4)])
cb = routing.counts([BKEY], now=NOW + 10)
check("2e: counts across the change: the old held lines count as archived (3), the filed session holds stay held (3)", cb["archived"] == 3 and cb["held"] == 3, cb)
rep_old = _wt_get._notice_report(o1); rep_s = _wt_get._notice_report(s1)
check("2f: the get tool says archived for an old record, held for the session's", "ruling: archived (kept" in rep_old and "ruling: held for an agent's next turn" in rep_s, (rep_old, rep_s))
put_live({"id": o1, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "rule": "image", "source": "code", "ts": NOW - 60})
put_live({"id": o2, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "rule": "page-pass", "source": "code", "ts": NOW - 50})
put_live({"id": s1, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "hold": "closed", "held_for": "work-osprey-x", "reason": "held: asks nothing (closed)", "ts": NOW - 40})
put_live({"id": s3, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "hold": "page-owed", "held_for": "", "reason": "held: front agent, the page is owed (page-owed)", "ts": NOW - 30})
last = live._last()
check("2g: the last line of an old live.jsonl notice reads archived; one filed for an agent (held_for) reads held, and a hold with no agent filed reads archived", last[o1]["ruling"] == "archived" and last[o2]["ruling"] == "archived" and last[s1]["ruling"] == "held" and last[s3]["ruling"] == "archived", {i: last[i]["ruling"] for i in (o1, o2, s1, s3)})
check("2h: the trace of an old notice reads archived", live.trace(o1)["last"]["ruling"] == "archived" and live.trace(o1)["ruled"]["ruling"] == "archived" and live.trace(s1)["last"]["ruling"] == "held", (live.trace(o1), live.trace(s1)))
rows_b, quiet_b, pagepass_b = live._digest_items(BKEY, NOW, last, {"sent": {}})
check("2i: the digest lists the old archived ones, a front page-owed hold with no agent filed, and leaves out the one held for an agent (held_for)",
      [r[1]["id"] for r in rows_b] == [o1, s3] and [r[1]["id"] for r in pagepass_b] == [o2], ([r[1]["id"] for r in rows_b], [r[1]["id"] for r in pagepass_b]))
txt_b = live.digest_text(BKEY, rows_b, "main", False)
check("2j: …and its text says archived for them", "2 notices were archived" in txt_b and "archived" in txt_b.splitlines()[-1], txt_b)
st_b = next(r for r in live.status(now=NOW) if r["project"] == BKEY)
check("2k: status counts the old ones under archived_since_digest", st_b["archived_since_digest"] == 3, st_b)

# ---- 3. a hold for a session's next turn still says held
h1 = rec(BKEY, "a fyi for the front agent")
_p, r_h1 = routing.rule(h1, "held", reason="held: front agent, work-osprey-main (rides its next turn, starts none)", by=live.BY, next_turn="fyi")
check("3a: a ruling written with its kind is held, and the line on disk carries the kind", r_h1["ruling"] == "held" and notice(BKEY, h1)["ruling"] == "held" and rulings_on_disk(BKEY, h1)[0]["next_turn"] == "fyi", rulings_on_disk(BKEY, h1))
h2 = rec(BKEY, "a hold whose reason is not worded as one"); routing.rule(h2, "held", reason="router hold", by=live.BY, next_turn="closed")
check("3b: …whatever its reason says (the kind decides)", notice(BKEY, h2)["ruling"] == "held", notice(BKEY, h2))
na = routing.record_auto(BKEY, "held", "held: asks nothing (closed)", next_turn="closed", kind="board", label="closed a1", who="stackshot", text="a1 closed", pilot=True)
nb = routing.record_auto(BKEY, "held", "held: asks nothing (closed)", kind="board", label="closed a2", who="stackshot", text="a2 closed", pilot=True)
check("3c: a log-only record of a session hold (record_auto with its kind) is held; one with no kind is written archived", notice(BKEY, na)["ruling"] == "held" and notice(BKEY, nb)["ruling"] == "archived"
      and rulings_on_disk(BKEY, na)[0].get("next_turn") == "closed" and rulings_on_disk(BKEY, nb)[0]["ruling"] == "archived", (rulings_on_disk(BKEY, na), rulings_on_disk(BKEY, nb)))

# ---- 4. held by hand, with no kind, is archived
h3 = rec(BKEY, "overruled by hand")
_p, r_h3 = routing.rule(h3, "held", reason="by hand", by="someone")
check("4a: rule(…, held) with no kind returns and writes archived (the route tool's old word)", r_h3["ruling"] == "archived" and [d["ruling"] for d in rulings_on_disk(BKEY, h3)] == ["archived"] and notice(BKEY, h3)["ruling"] == "archived", rulings_on_disk(BKEY, h3))
try: routing.rule(h3, "parked"); refused = False
except ValueError: refused = True
check("4b: …a word that is no ruling is refused", refused)

# ---- 4c. the route tool's reply names the stored ruling
from stackshot.web.tools import route as _wt_route
_wt_route._publish = lambda: None
h4 = rec(BKEY, "overruled by hand through the tool")
reply = _wt_route._route(h4, "held", reason="by hand", sender="")
check("4c: the route tool's reply says archived (the ruling as stored) when held was asked with no kind, never the word that was asked", reply.startswith(f"ruled {h4} ({BKEY}): archived") and "): held" not in reply, reply)

# ---- 5. a notice delivered to no one is archived, whoever's gate it came from (probe P4)
q1 = rec(BKEY, "the front gate told nobody"); old_ruling(BKEY, q1, "archived", "archived: front agent, Oliver is not there for its pane (30 min) (progress)")
put_live({"id": q1, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "archived", "rule": "message-item", "hold": "page-owed", "held_for": "", "source": "code",
          "reason": "archived: front agent, its hook cannot fetch held lines (page-owed)", "ts": NOW - 20})
q2 = rec(BKEY, "a front hold with no agent filed, as an older router wrote it"); old_ruling(BKEY, q2, "held", "held: front agent, its hook cannot fetch held lines (page-owed)")
put_live({"id": q2, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "rule": "message-item", "hold": "page-owed", "held_for": "", "source": "code",
          "reason": "held: front agent, its hook cannot fetch held lines (page-owed)", "ts": NOW - 10})
last = live._last()
rows_q, _qq, _pq = live._digest_items(BKEY, NOW, last, {"sent": {}})
ids_q = [r[1]["id"] for r in rows_q]
check("5a: a notice the gate told to no one reads archived in the routing log and in the live line, and the digest lists it", notice(BKEY, q1)["ruling"] == "archived" and last[q1]["ruling"] == "archived" and q1 in ids_q, (notice(BKEY, q1), last[q1], ids_q))
check("5b: …and the same for an old line of that kind (a held with no agent filed, its reason not worded as a filed line): archived in the log, the live line and the digest", notice(BKEY, q2)["ruling"] == "archived" and last[q2]["ruling"] == "archived" and q2 in ids_q, (notice(BKEY, q2), last[q2], ids_q))
rep_q1, rep_q2 = _wt_get._notice_report(q1), _wt_get._notice_report(q2)
check("5c: get and the digest say the same word for them: archived, never held for an agent's next turn", "ruling: archived" in rep_q1 and "ruling: archived" in rep_q2 and "held for an agent" not in rep_q1 + rep_q2
      and "archived by the router and not passed" in live.digest_text(BKEY, [r for r in rows_q if r[1]["id"] in (q1, q2)], "main", False), (rep_q1, rep_q2))
st_q = next(r for r in live.status(now=NOW) if r["project"] == BKEY)
check("5d: status counts them under archived_since_digest", st_q["archived_since_digest"] >= 2 and "held_since_digest" not in st_q, st_q)

# ---- 6. P1: an old router-ruled held whose reason is model-written text that starts "held: "
cb0 = routing.counts([BKEY], now=NOW + 10)
p1 = rec(BKEY, "something unclear for the call"); old_ruling(BKEY, p1, "held", "held: the notice is unclear, kept for later")
put_live({"id": p1, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "rule": "call", "source": "call", "reason": "held: the notice is unclear, kept for later", "ts": NOW - 5})
cp = routing.counts([BKEY], now=NOW + 10)
check("6a: an old router-ruled held whose reason starts 'held: ' with no mark reads archived in routing.read and in the live line and its trace", notice(BKEY, p1)["ruling"] == "archived" and live._last()[p1]["ruling"] == "archived" and live.trace(p1)["last"]["ruling"] == "archived", (notice(BKEY, p1), live._last()[p1]))
check("6b: …in the counts (one more archived, held unchanged)", cp["archived"] == cb0["archived"] + 1 and cp["held"] == cb0["held"], (cp, cb0))
check("6c: …and in the get tool", "ruling: archived" in _wt_get._notice_report(p1), _wt_get._notice_report(p1))
check("6d: a hold's mark outranks its reason (held with next_turn is held whatever the reason says); with no mark only a reason worded as a filed line keeps held",
      routing.ruling_of("held", "fyi", "anything") == "held" and routing.ruling_of("held", "", "router hold") == "archived" and routing.ruling_of("held", "", "held: the notice is unclear") == "archived"
      and routing.ruling_of("held", "", "held: asks nothing (closed)") == "held")

# live lines whose reason does not start 'held: ': only held_for decides
mk1, mk2 = rec(BKEY, "a live line filed for an agent, reason not worded as a hold"), rec(BKEY, "a live line with a hold name but no agent filed")
put_live({"id": mk1, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "hold": "fyi", "held_for": "work-osprey-main", "reason": "router hold", "ts": NOW - 4})
put_live({"id": mk2, "project": BKEY, "key": BKEY, "status": "ruled", "ruling": "held", "hold": "fyi", "held_for": "", "reason": "router hold", "ts": NOW - 3})
lk = live._last()
check("6e: a live line names a hold only by held_for: filed for an agent reads held, the same with no agent reads archived (the reason is not read)", lk[mk1]["ruling"] == "held" and lk[mk2]["ruling"] == "archived", (lk[mk1], lk[mk2]))
check("6f: …and so does the trace", live.trace(mk1)["last"]["ruling"] == "held" and live.trace(mk2)["last"]["ruling"] == "archived")

# the audit split whose keepers were all held by an earlier try: ruled held, the ruling line carries its audit mark
au = rec(BKEY, "audit: a1 stalled; a2 stalled", kind="board")
n_au = notice(BKEY, au)
split_ln = {"id": au, "ruling": "passed", "target": "", "reason": "split", "split": {"home-beta-main": ["a1"], "work-osprey-x": ["a2"]}}
base_au = {"id": au, "ts": NOW, "project": BKEY, "key": BKEY, "kind": "board", "ruling": "passed", "target": "", "reason": "split", "marked": False}
prior_au = {"sent": {"home-beta-main": "home-beta-main: held", "work-osprey-x": "work-osprey-x: held"}}
res_au = live._act_split(n_au, BKEY, BKEY, split_ln, cx, prior_au, base_au, "home-beta-main")
check("6g: an audit split whose keepers were all held by an earlier try is ruled held, with its audit mark on the ruling line (held_for lists the agents)",
      res_au.get("status") == "ruled" and res_au.get("ruling") == "held" and res_au.get("hold") == "audit" and res_au.get("held_for") == "home-beta-main, work-osprey-x"
      and [d.get("next_turn") for d in rulings_on_disk(BKEY, au)] == ["audit"] and notice(BKEY, au)["ruling"] == "held", (res_au, rulings_on_disk(BKEY, au)))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
