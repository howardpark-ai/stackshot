"""Scenario test for `involved?key=<session>` of the client API: the open items a session is the contact of or an observer on, which `items?key=` (the items a session moves) does not list for it — fixture data, no live store, no network.

Covers: an item matches when the session is its contact, when it is one of its observers and when it is both (one row); an item that names the session in neither, and a closed item that names it in both, are not in the answer; a held item is
there with held true, and an item waiting on another open item too; the row's `list` is each of your-move, agents and waiting (the same word `items` gives for the item, and the Your move group of the home page's own renderer agrees); the
rows come last write first (an item that stores no `updated` by its `state_updated`) and not in the store's order; a session is found as the board finds one for `items?key=`: by its name, its transcript id, its permanent id, an old name (an
alias), whether the item stores a name or an id; the contact is the live one (a stored contact that is no front agent, and none stored, read as the project's -main agent); the row's fields are those of the `items` row for the same
item under the same names and in the same format; `url` as `your-move` gives it, with and without a board address; `observers` are names, in the stored order and without repeats; no cap (more rows than `open-records` gives); an unknown key is
`{"items": []}`; a blank, over-long or multi-line key is 400; the read writes nothing and changes no other read's answer; over HTTP: no token, a wrong token, the token in the query string, a Basic credential and a live caller's pass are 401, the
machine's token is the read's own answer, no-store, answered in a worker thread, a missing key is 400, a read-only standby serves it and a write to it is refused; the 404 list, `client.py` and the contract name the read.

    tests/run-suite client_involved         → exit 0 / 1

Every check runs inside a guard: a call that raises is a FAILed check, never an abort of the suite."""
import contextlib, io, json, os, re, sys, pathlib, logging, time, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="clientinvolved-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml, n = re.subn(r'(?m)^session_links = ""', f'session_links = "{tmp}/links"', toml); assert n == 1
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "links/a", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
M, A, B, S = "alpha-main", "work-a", "work-b", "swift-jaunty-charm"          # the project's -main agent, two more front agents, a background agent
SESS = {M: "00000000-0000-4000-8000-000000000001", S: "00000000-0000-4000-8000-000000000002", A: "00000000-0000-4000-8000-000000000003", B: "00000000-0000-4000-8000-000000000004"}
ALIAS = {B: ["work-b-old"]}                                                                                       # a session that was renamed: its old name is an alias in the registry
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in SESS.items()}))
(T / "links/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-11-20T00:00:00Z", "sessions": {u: {
    "id": u, "name": n, "aliases": ALIAS.get(n, []), "project": "", "state": "live", "created": "2026-11-01T00:00:00Z",
    "transcripts": [{"id": u, "machine": "a", "at": "2026-11-01T00:00:00Z", "why": "start"}]} for n, u in SESS.items()}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": M, "status": "active", "board": [], "board_open": 0,
    "agents": {M: "the main", A: "a front agent", B: "another front agent", S: "the builder"}, "back_agents": {S: "the builder"}}}}))
(T / "brain/projects/alpha.md").write_text(f"---\ntitle: Alpha\ndisplay-name: {M}\nagents:\n  {M}: the main\n  {A}: a front agent\n  {B}: another front agent\n  background:\n    {S}: the builder\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("9000"); (T / "store/anchors.json").write_text("{}")
now0 = time.time(); DAY = 86400.0
fails = []; ran = []
def check(name, cond, got=None):
    """`cond` is a value or a function of no argument: a function that raises is a failed check (a mutant that breaks the read fails here by name, it does not end the suite)."""
    ran.append(name)
    try: ok = bool(cond() if callable(cond) else cond)
    except Exception as e: ok, got = False, f"{type(e).__name__}: {e}"
    if not ok: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)

from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import readonly as _ro
from stackshot.core import store as _store
from stackshot.fleet import client
from stackshot.github import ghsync as _gh
from stackshot.service import caller_pass as _cp
from stackshot.service import client_reads as cr
from stackshot.web import render as _rmod
from stackshot.web import server
from stackshot.web.routes import client_api as _rt_client

OWNER = _inst.OWNER
def put(i, status="open", subject=None, age=3.0, state_age=None, updated=True, **meta):
    rec = {"id": str(i), "subject": subject or f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
           "state_updated": now0 - (age if state_age is None else state_age) * DAY, "confirmed": now0 - age * DAY,
           "metadata": {"project": meta.pop("project", "projects/alpha"), **meta}}
    if updated: rec["updated"] = now0 - age * DAY
    (T / f"store/a/{i}.json").write_text(json.dumps(rec, ensure_ascii=False))
def drop(i): (T / f"store/a/{i}.json").unlink()
def D(n): return time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY))
shown = lambda n: _gh.shown(f"a{n}")

put(11, subject="[home] contact only, the owner moves it", age=5, contact=A, mover=OWNER)
put(12, subject="[home] observer only, a session moves it", age=1, contact=B, observers=[A], mover=S)
put(13, subject="[home] contact and observer", age=3, contact=A, observers=[A, B], mover=S)
put(14, subject="[home] names neither of work-a", age=2, contact=B, observers=[B, M], mover=S)
put(15, subject="[home] closed, names it twice", status="completed", age=2, contact=A, observers=[A], mover=S, outcome="done")
put(16, subject="[home] held", age=4, contact=A, hold=True, mover=S)
put(17, subject="[home] waits on a date", age=6, contact=B, observers=[A], mover=OWNER, wait_kind="time", wake=D(6), post_wake_mover=S)
put(18, subject="[home] observer stored as the permanent id, the newest", age=0.5, contact=B, observers=[SESS[A]], mover=S)
put(19, subject="[home] a stored contact that is no front agent", age=7, contact="ghost-one", mover=S)
put(20, subject="[home] no contact stored", age=8, mover=OWNER)
put(21, subject="[home] contact and observer under two names of one session", age=9, contact=B, observers=["work-b-old", B], mover=S)
put(22, subject="[home] observer under an old name", age=10, contact=M, observers=["work-b-old"], mover=S)
put(23, subject="[home] a file that stores no update time", age=3, state_age=2.5, updated=False, contact=A, mover=S)
put(24, subject="[home] waits on an open item", age=4.5, contact=A, mover=S, after=["a11"])
FOR_A = [18, 12, 23, 13, 16, 24, 11, 17]; FOR_B = {12, 13, 14, 17, 18, 21, 22}; FOR_M = {14, 19, 20, 22}
FIELDS = ["shown", "subject", "url", "mover", "contact", "observers", "list", "held", "state_updated", "updated"]

def inv(key):
    """(status, parsed body) of the read, a raise as (599, its text)."""
    try:
        st, ct, b = cr._client_get("involved", {"key": key})
        return st, (json.loads(b) if ct == "application/json" else b)
    except Exception as e: return 599, f"{type(e).__name__}: {e}"
class Rows(dict):
    """A row or a field a broken read lacks reads as an empty Rows, so the words a check prints when it fails (built before the check runs) never raise."""
    def __missing__(self, key): return Rows()
def rows(key): st, j = inv(key); return Rows({x["shown"]: Rows(x) for x in j["items"]}) if st == 200 else Rows()
def order(key): st, j = inv(key); return [x["shown"] for x in j["items"]] if st == 200 else None
shown_set = lambda ns: {shown(n) for n in ns}

# which items
check("the answer is 200 {items: [...]} and nothing else", lambda: inv(A)[0] == 200 and list(inv(A)[1]) == ["items"] and isinstance(inv(A)[1]["items"], list), inv(A))
check("a contact match, an observer match and an item that is both are in the answer, the both once", lambda: set(order(A)) == shown_set(FOR_A) and len(order(A)) == len(FOR_A), order(A))
check("an item that names the session in neither role is not in it", lambda: not (shown_set((14, 19, 20, 21, 22)) & set(order(A))), order(A))
check("a closed item that names the session as contact and observer is not in it, whichever key asks", lambda: shown(15) not in order(A) and shown(15) not in rows(B) and shown(15) not in rows(M), order(A))
check("work-b: its contact items, its observer items (by its name and its old name) and the item that names it under both names once", lambda: set(order(B)) == shown_set(FOR_B) and len(order(B)) == len(FOR_B), (order(B), shown_set(FOR_B)))
check("the project's -main agent: the items with a stored contact that is no front agent and with none (the live contact), a stored contact and an observer", lambda: set(order(M)) == shown_set(FOR_M), (order(M), shown_set(FOR_M)))
check("…the row of such an item shows the live contact, and the stored one that is no front agent is not matched", lambda: rows(M)[shown(19)]["contact"] == M and rows(M)[shown(20)]["contact"] == M and shown(19) not in rows("ghost-one"), rows(M).get(shown(19)))
check("a session is found by its transcript id (= its permanent id) as by its name, whether the item stores a name or an id", lambda: order(SESS[A]) == order(A) and shown(18) in order(A) and order(SESS[B]) == order(B), (order(SESS[A]), order(A)))
check("a renamed session is found under its old name as well (an alias of the registry): the same rows", lambda: order("work-b-old") == order(B), (order("work-b-old"), order(B)))
check("a key with blanks around it is the key", lambda: order("  " + A + " ") == order(A))

# order
check("the rows come last write first: `updated` newest first, an item that stores no `updated` by its `state_updated`", lambda: order(A) == [shown(n) for n in FOR_A], (order(A), [shown(n) for n in FOR_A]))
check("…which is not the store's order (the ids ascending) and not its reverse", lambda: order(A) != sorted(order(A), key=lambda s: int(re.findall(r"\d+", s)[-1])) and order(A) != sorted(order(A), key=lambda s: -int(re.findall(r"\d+", s)[-1])), order(A))
check("…the times of the rows are non-increasing", lambda: (lambda ts: ts == sorted(ts, reverse=True))([x["updated"] or x["state_updated"] for x in inv(A)[1]["items"]]))

# the row
r = rows(A)
check("a row has exactly the ten fields, in this order", lambda: all(list(x) == FIELDS for x in r.values()) and len(r) == len(FOR_A), [list(x) for x in r.values()][:1])
check("shown is the id as a person reads it, subject the item's", lambda: r[shown(11)]["subject"] == "[home] contact only, the owner moves it" and all(k == x["shown"] for k, x in r.items()), r.get(shown(11)))
check("contact is the contact's name now, observers the names of the observers: a stored name, a permanent id (as the name in use), an old name (as the current one), once each, in the stored order",
      lambda: r[shown(11)]["contact"] == A and r[shown(11)]["observers"] == [] and r[shown(13)]["observers"] == [A, B] and r[shown(18)]["observers"] == [A] and rows(B)[shown(21)]["observers"] == [B] and rows(B)[shown(22)]["observers"] == [B],
      (r[shown(13)], r[shown(18)], rows(B).get(shown(21))))
check("held: a parked item and an item that waits on an open item are held; the others are not", lambda: r[shown(16)]["held"] is True and r[shown(24)]["held"] is True and all(r[shown(n)]["held"] is False for n in (11, 12, 13, 18, 23)), {k: x["held"] for k, x in r.items()})
check("list: the owner's move is your-move, a session's is agents, a wait on a date is waiting", lambda: r[shown(11)]["list"] == "your-move" and r[shown(12)]["list"] == "agents" and r[shown(17)]["list"] == "waiting", {k: x["list"] for k, x in r.items()})
check("list is never empty and is one of the three words", lambda: all(x["list"] in ("your-move", "agents", "waiting") for x in r.values()) and all(x["list"] in ("your-move", "agents", "waiting") for x in rows(M).values()), {k: x["list"] for k, x in r.items()})
ym = lambda: {x["shown"] for x in _rmod.your_move(str(_store.STORE))}
check("the your-move rows are exactly the items of the home page's own Your move group", lambda: {k for k, x in r.items() if x["list"] == "your-move"} == ym() & set(r), (ym(), {k: x["list"] for k, x in r.items()}))
def items_row(n, key):
    st, ct, b = cr._client_get("items", {"key": key}); return {x["shown"]: x for x in json.loads(b)["items"]}.get(shown(n))
def same_as_items(n):
    x, y = r.get(shown(n)), items_row(n, S)
    return x is not None and y is not None and all(x[f] == y[f] for f in ("shown", "subject", "contact", "list", "held", "state_updated", "updated"))
check("an item a session moves reads as `items?key=` gives it, in every field the two share: the same values in the same format", lambda: all(same_as_items(n) for n in (12, 13, 16, 23, 24, 18)), [(n, r.get(shown(n)), items_row(n, S)) for n in (12, 16)])
facts = lambda ids: json.loads(cr._client_get("item-facts", {"key": S, "ids": ",".join(f"a{n}" for n in ids)})[2])["items"]
check("mover is a string, the name of whoever moves it now: a session by the name it has now, the owner as the item model names him", lambda: r[shown(12)]["mover"] == S and r[shown(13)]["mover"] == S and r[shown(11)]["mover"] == facts([11])["a11"]["mover"] and r[shown(11)]["mover"] not in ("", S) and all(isinstance(x["mover"], str) for x in r.values()), {k: x["mover"] for k, x in r.items()})
check("…and is the mover `item-facts` gives for the same item, for every row", lambda: all(r[shown(n)]["mover"] == facts([n])[f"a{n}"]["mover"] for n in FOR_A) and all(rows(M)[shown(n)]["mover"] == facts([n])[f"a{n}"]["mover"] for n in FOR_M), {k: x["mover"] for k, x in r.items()})
check("times are epoch seconds: updated is the item's last write, state_updated the last change of state, updated null for a file that stores none",
      lambda: abs(r[shown(12)]["updated"] - (now0 - 1 * DAY)) < 1 and abs(r[shown(12)]["state_updated"] - (now0 - 1 * DAY)) < 1 and r[shown(23)]["updated"] is None and abs(r[shown(23)]["state_updated"] - (now0 - 2.5 * DAY)) < 1, r[shown(23)])
_was = _inst.BOARD_URL
try:
    _inst.BOARD_URL = "https://board.example.invalid/"
    check("url is the item's page under the board address", lambda: all(rows(A)[shown(n)]["url"] == f"https://board.example.invalid/items/{_gh.href_id(f'a{n}')}" for n in FOR_A), rows(A)[shown(11)])
    check("…the same url your-move gives the same item", lambda: next(x["url"] for x in json.loads(cr._client_get("your-move", {})[2])["items"] if x["shown"] == shown(11)) == rows(A)[shown(11)]["url"])
    _inst.BOARD_URL = ""
    check("…and the path alone while the instance has no board address", lambda: all(rows(A)[shown(n)]["url"] == f"/items/{_gh.href_id(f'a{n}')}" for n in FOR_A), rows(A)[shown(11)])
finally: _inst.BOARD_URL = _was

# unknown and bad keys
check("a key that names nobody, and a session that is neither contact nor observer of an open item, is 200 {items: []}", lambda: inv("nobody-at-all") == (200, {"items": []}) and inv(S) == (200, {"items": []}) and inv("00000000-0000-4000-8000-0000000000ff") == (200, {"items": []}), (inv("nobody-at-all"), inv(S)))
check("a blank key, a missing key, a key with a line break or a tab and a key over 200 characters are 400", lambda: all(cr._client_get("involved", p)[0] == 400 for p in ({"key": ""}, {"key": "   "}, {}, {"key": "a\nb"}, {"key": "a\tb"}, {"key": "x" * 201})), [cr._client_get("involved", p)[0] for p in ({"key": ""}, {}, {"key": "x" * 201})])
check("the 400 is a plain line naming the key, as items gives it", lambda: cr._client_get("involved", {})[1] == "text/plain" and "key" in cr._client_get("involved", {})[2], cr._client_get("involved", {}))
check("a key of 200 characters is a key: 200 {items: []}", lambda: inv("x" * 200) == (200, {"items": []}))

# the read writes nothing and changes no other read
def snap(): return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted((T / "store").rglob("*")) if p.is_file()}
others = lambda: [cr._client_get("items", {"key": k})[2] for k in (A, B, M, S, SESS[A])] + [cr._client_get("your-move", {})[2], cr._client_get("item-facts", {"key": S, "ids": "a12,a13"})[2], cr._client_get("open-records", {"key": S})[2]]
before_o, before_s = others(), snap()
for k in (A, B, M, "nobody", ""): inv(k)
check("the read writes no file of the store, and every other read answers as it did", lambda: snap() == before_s and others() == before_o, None)
def fresh():
    put(25, subject="[home] new, work-a is contact", age=0.1, contact=A, mover=S)
    try: first = order(A)[0] == shown(25)
    finally: drop(25)
    return first and order(A)[0] == shown(18)
check("the read is not kept between calls: an item added since is read at the next call and gone when removed", fresh, order(A))
def reopen():
    p = T / "store/a/11.json"; t = p.read_text()
    try:
        p.write_text(json.dumps({**json.loads(t), "status": "completed"})); gone = shown(11) not in order(A)
    finally: p.write_text(t)
    return gone and shown(11) in order(A)
check("an item closed since leaves the answer at the next call, and comes back when reopened", reopen)
def damaged():
    (T / "store/a/26.json").write_text("{not json"); (T / "store/a/27.json").write_text("[1, 2]")
    try: return order(A) == [shown(n) for n in FOR_A]
    finally: drop(26); drop(27)
check("a damaged item file and a file that is no item are skipped, the rest is the answer", damaged, order(A))

# no cap
many = 330
for n in range(100, 100 + many): put(n, subject=f"[home] bulk {n}", age=20 + n / 100, contact=A, observers=[B], mover=S)
check("no cap: more rows than open-records gives are all in the answer, in order", lambda: len(order(A)) == len(FOR_A) + many and order(A)[: len(FOR_A)] == [shown(n) for n in FOR_A] and order(A)[len(FOR_A):] == [shown(n) for n in range(100, 100 + many)], len(order(A) or []))
for n in range(100, 100 + many): drop(n)

# the surface
tok = open(client.mint("box-far")).read().strip(); H = {"Authorization": "Bearer " + tok}
from starlette.testclient import TestClient
seen_threads = []; _real = _rt_client._client_get
def spy(what, params):
    seen_threads.append((what, threading.current_thread().name)); return _real(what, params)
_rt_client._client_get = spy
app = server.mcp.http_app()
try:
    with TestClient(app) as c:
        Q = f"/client/involved?key={A}"
        r0 = c.get(Q)
        r1 = c.get(Q, headers={"Authorization": "Bearer " + "x" * 43})
        r2 = c.get("/client/involved", params={"key": A, "token": tok})
        r3 = c.get(Q, headers={"Authorization": "Basic " + tok})
        r4 = c.get(Q, headers={"Authorization": tok})
        ok = c.get(Q, headers=H)
        miss = c.get("/client/involved", headers=H)
        blank = c.get("/client/involved?key=", headers=H)
        nobody = c.get("/client/involved?key=nobody-at-all", headers=H)
        wh = c.get("/client/whoami", headers=H)
        # a live pass of an approved key: it opens the New session form's calls and nothing else of /client
        PASS = _cp.PASS_PREFIX + "p" * 43
        import hashlib
        _cp._PASSES[hashlib.sha256(PASS.encode()).hexdigest()] = {"fp": "f" * 64, "sender": "alpha", "exp": time.time() + 600}
        _lookup = _cp._keys.lookup_approved; _cp._keys.lookup_approved = lambda fp: {"sender": "alpha"}
        try:
            live = _cp.pass_machine("Bearer " + PASS)
            rp = c.get(Q, headers={"Authorization": "Bearer " + PASS})
        finally: _cp._keys.lookup_approved = _lookup; _cp._PASSES.clear()
        nf = c.get("/client/nothing-here", headers=H)
        # a read-only standby serves it, and refuses a write
        _ro._reload_for_test(True)
        try:
            sb = c.get(Q, headers=H)
            wr = c.post("/client/for-you/seen", json={"id": "all", "sender": "x"}, headers=H)
        finally: _ro._reload_for_test(False)
finally: _rt_client._client_get = _real
check("http: no token → 401, a wrong token → 401, the token in the query string → 401, a Basic credential → 401, a bare Authorization value → 401",
      lambda: [x.status_code for x in (r0, r1, r2, r3, r4)] == [401] * 5 and not any("subject" in x.text for x in (r0, r1, r2, r3, r4)), [x.status_code for x in (r0, r1, r2, r3, r4)])
check("http: a live pass of an approved key is 401 (it opens the form's calls only)", lambda: live.startswith(_cp.MACHINE_PREFIX) and rp.status_code == 401 and "subject" not in rp.text, (live, rp.status_code, rp.text[:100]))
check("http: the machine's token gets the read's own answer, no-store, JSON", lambda: ok.status_code == 200 and ok.json() == inv(A)[1] and len(ok.json()["items"]) == len(FOR_A) and ok.headers["cache-control"] == "no-store" and ok.headers["content-type"].startswith("application/json"), (ok.status_code, ok.text[:150]))
check("http: a missing key and a blank key are 400, an unknown key 200 with no item", lambda: miss.status_code == 400 and blank.status_code == 400 and nobody.status_code == 200 and nobody.json() == {"items": []}, (miss.status_code, blank.status_code, nobody.status_code))
check("http: it is answered in a worker thread, not on the event loop (it scans the board)", lambda: [w for w, t in seen_threads if w == "involved"] and all("worker" in t.lower() or "anyio" in t.lower() for w, t in seen_threads if w == "involved") and wh.status_code == 200, seen_threads)
check("http: the 404 list of reads names it", lambda: nf.status_code == 404 and "involved?key=<session>" in nf.text, nf.text[:200])
check("a read-only standby copy serves it, as it serves the other reads, and a write is still refused", lambda: sb.status_code == 200 and sb.json() == inv(A)[1] and wr.status_code == 503 and "read-only standby" in wr.text, (sb.status_code, wr.status_code, wr.text[:120]))
usage = open(client.__file__, encoding="utf-8").read().split('"""', 2)[1]
part = usage.split("client.py get involved", 1)[1].split("client.py get your-move", 1)[0] if "client.py get involved" in usage else ""
check("client.py knows the read, and its usage text names the form and each field", lambda: "involved" in client.READS and "involved <session>" in usage and all(w in part for w in ("shown", "subject", "url", "mover", "contact", "observers", "list", "held", "state_updated", "updated", "newest write first", "400")), part[:200])
_get = client.get; got_args = []
def fake_get(what, key="", timeout=10.0, **k): got_args.append((what, key)); return 200, json.dumps({"items": []})
client.get = fake_get
try:
    out = io.StringIO()
    with contextlib.redirect_stdout(out): rc = client.main(["client.py", "get", "involved", A])
finally: client.get = _get
check("client.py get involved <session> asks for the read with the key, prints the server's JSON and exits 0", lambda: rc == 0 and got_args == [("involved", A)] and json.loads(out.getvalue()) == {"items": []}, (rc, got_args, out.getvalue()))
doc = open(os.path.join(STACK, "docs", "client-contract.md"), encoding="utf-8").read()
HEAD = "## The open items a session is the contact of or an observer on"
sec = doc.split(HEAD, 1)[1].split("\n## ", 1)[0] if HEAD in doc else ""
check("the contract describes the read: the route, the auth, each field, the order and the client's form", lambda: "GET /client/involved?key=<session>" in sec and "Bearer <machine token>" in sec and all(f"\"{f}\"" in sec for f in FIELDS) and "last write first" in sec and "get involved <session>" in sec, sec[:200])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": client involved scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
