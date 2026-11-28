"""Scenario test for `involved?key=<session>` of the client API: the open items a session is the contact of or an observer on, which `items?key=` (the items a session moves) does not list for it — fixture data, no live store, no network.

Covers: an item matches when the session is its contact, when it is one of its observers and when it is both (one row); an item that names the session in neither, and a closed item that names it in both, are not in the answer; a held item is
there with held true, and an item waiting on another open item too; the row's `list` is each of your-move, agents and waiting (the same word `items` gives for the item, and the Your move group of the home page's own renderer agrees); the
rows come last write first (an item that stores no `updated` by its `state_updated`) and not in the store's order; a session is found as the board finds one for `items?key=`: by its name, its transcript id, its permanent id, an old name (an
alias), whether the item stores a name or an id, and a name is matched whole and as written (a part of it, a longer name and other letter case name nobody); an item queued behind another of its mover reads waiting, and an item stored
with the retired on-hold status is an open, held one; the session roles are built once for a read, with the queue rule on and off, and again at the next read, with the same answer as without that memo; the contact is the live one (a stored contact that is no front agent, and none stored, read as the project's -main agent); the row's fields are those of the `items` row for the same
item under the same names and in the same format; `until` is the day a held item comes back (a parked item, a time wait, a wait on an open item with a backstop day, a doing item waiting for a stated wake), the day the board's own
Waiting row shows, as stored in the instance's time zone, and null for an item that is not held, whatever date it stores, for a held one with no date and when the reading fails (a closed item with a date is not in the answer); `url` as `your-move` gives it, with and without a board address; `observers` are names, in the stored order and without repeats; no cap (more rows than `open-records` gives); an unknown key is
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

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import passmemo as _passmemo
from stackshot.core import readonly as _ro
from stackshot.core import store as _store
from stackshot.fleet import client
from stackshot.github import ghsync as _gh
from stackshot.model import last_activity as _la
from stackshot.model import model as _model
from stackshot.projects import projects as _prj
from stackshot.service import audit_ticks as _audit_ticks
from stackshot.service import caller_pass as _cp
from stackshot.service import client_reads as cr
from stackshot.service import item_read as _item_read
from stackshot.web import home as _home
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
put(17, subject="[home] waits on a date", age=6, contact=B, observers=[A], wait_kind="time", wake=D(6), mover=S)
put(18, subject="[home] observer stored as the permanent id, the newest", age=0.5, contact=B, observers=[SESS[A]], mover=S)
put(19, subject="[home] a stored contact that is no front agent", age=7, contact="ghost-one", mover=S)
put(20, subject="[home] no contact stored", age=8, mover=OWNER)
put(21, subject="[home] contact and observer under two names of one session", age=9, contact=B, observers=["work-b-old", B], mover=S)
put(22, subject="[home] observer under an old name", age=10, contact=M, observers=["work-b-old"], mover=S)
put(23, subject="[home] a file that stores no update time", age=3, state_age=2.5, updated=False, contact=A, mover=S)
put(24, subject="[home] waits on an open item", age=4.5, contact=A, mover=S, after=["a11"])
FOR_A = [18, 12, 23, 13, 16, 24, 11, 17]; FOR_B = {12, 13, 14, 17, 18, 21, 22}; FOR_M = {14, 19, 20, 22}
FIELDS = ["shown", "subject", "url", "mover", "contact", "observers", "list", "held", "until", "state_updated", "updated", "scope"]

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
check("a row has exactly the twelve fields, in this order", lambda: all(list(x) == FIELDS for x in r.values()) and len(r) == len(FOR_A), [list(x) for x in r.values()][:1])
check("scope is the item's group, from its project (the page is in org home)", lambda: all(x["scope"] == "home" for x in r.values()) and len(r) == len(FOR_A), [x["scope"] for x in r.values()])
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

# the day it comes back
check("until is null for an item with no date to come back on: held with none (parked, waiting on an open item) and not held",
      lambda: all(r[shown(n)]["until"] is None for n in (11, 12, 13, 16, 18, 23, 24)), {k: x["until"] for k, x in r.items()})
check("…and for a wait stored as a wake alone, which the board lists as waiting but does not hold", lambda: r[shown(17)]["list"] == "waiting" and r[shown(17)]["held"] is False and r[shown(17)]["until"] is None, r.get(shown(17)))
dated = {30: dict(subject="[home] parked to a day", mover=S, hold=True, wake=D(3)),
         31: dict(subject="[home] a time wait", mover=S, wait_kind="time", until=D(4)),
         32: dict(subject="[home] a day and an early hour", mover=S, until=D(5) + "T00:30"),
         33: dict(subject="[home] a day and a late hour", mover=S, until=D(6) + "T23:30"),
         34: dict(subject="[home] waits on an open item, back by a day", mover=S, after=["a11"], wait_kind="item", until=D(7)),
         35: dict(subject="[home] doing, waiting for a stated wake", mover=S, state="doing", wake=D(8), wait_basis={"text": "the vendor answers " + D(8), "wake": D(8), "by": S}),
         36: dict(subject="[home] news relayed, with a day", mover=S, wait_kind="relay", wait_event="their answer", until=D(9)),
         37: dict(subject="[home] an anchor, with a backstop day", mover=S, wait_kind="anchor", wait_anchor="https://repo.example.invalid/pull/1", until=D(10)),
         38: dict(subject="[home] a day beside a decision he owes", mover=OWNER, needs="decision", ask="which one?", hold=True, wake=D(11)),
         39: dict(subject="[home] doing, with a backstop wake and no reason", mover=S, state="doing", wake=D(12), steps=[{"text": "work-a: write it", "status": "open"}])}
for n, meta in dated.items(): put(n, age=30 + n / 100, contact=A, **meta)
put(40, subject="[home] closed with a day", status="completed", age=2, contact=A, mover=S, hold=True, wake=D(13), until=D(13), outcome="done")
try:
    u = rows(A); got = lambda n: (u[shown(n)]["held"], u[shown(n)]["until"])
    say = lambda ns: {n: (u.get(shown(n), Rows())["list"], got(n)) for n in ns}
    check("until: a parked item gives the day of its wake", lambda: got(30) == (True, D(3)), say((30,)))
    check("until: a time wait gives the day it ends on", lambda: got(31) == (True, D(4)) and u[shown(31)]["list"] == "waiting", say((31,)))
    check("until: a stored time of day is left off and no time zone moves the day (the instance's zone is not UTC)", lambda: got(32) == (True, D(5)) and got(33) == (True, D(6)), say((32, 33)))
    check("until: a wait on an open item gives the day it comes back anyway, a doing item that waits for a stated wake that day", lambda: got(34) == (True, D(7)) and got(35) == (True, D(8)), say((34, 35)))
    check("until: a waiting item that is not held (relayed news, an anchor) is null, though the board shows its day", lambda: all(u[shown(n)]["list"] == "waiting" and got(n) == (False, None) for n in (36, 37)), say((36, 37)))
    check("until: an item that stores a day and is not held (a decision he owes, a doing item's backstop) is null", lambda: all(got(n) == (False, None) for n in (38, 39)), say((38, 39)))
    check("until: a closed item that stores a day is not in the answer", lambda: shown(40) not in u and len(u) == len(FOR_A) + len(dated), sorted(u))
    def board_days():
        out = {}
        for n in (30, 31, 32, 33, 34, 35, 36, 37):
            it = {**json.loads((T / f"store/a/{n}.json").read_text()), "gid": f"a{n}"}
            end = _home.end_of(_model.view(it, _item_read._model_of(it), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {})))
            out[n] = end[:10] if end else None
        return out
    check("until is the day the home page's own reader gives for the item, and that reader gives the two waits that are not held a day", lambda: (lambda d: all(u[shown(n)]["until"] == d[n] for n in range(30, 36)) and d[36] == D(9) and d[37] == D(10))(board_days()), {k: x["until"] for k, x in u.items()})
    check("until is a string \"YYYY-MM-DD\" or null in every row", lambda: all(x["until"] is None or (isinstance(x["until"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["until"])) for x in u.values()), {k: x["until"] for k, x in u.items()})
    _end = _home.end_of
    def _boom(mod): raise ValueError("no reading")
    _home.end_of = _boom
    try:
        check("until: a reading that fails gives null for the row and the rest of the answer stands", lambda: inv(A)[0] == 200 and len(inv(A)[1]["items"]) == len(FOR_A) + len(dated) and all(x["until"] is None for x in inv(A)[1]["items"]))
    finally: _home.end_of = _end
finally:
    for n in list(dated) + [40]: drop(n)

# unknown and bad keys
check("a key that names nobody, and a session that is neither contact nor observer of an open item, is 200 {items: []}", lambda: inv("nobody-at-all") == (200, {"items": []}) and inv(S) == (200, {"items": []}) and inv("00000000-0000-4000-8000-0000000000ff") == (200, {"items": []}), (inv("nobody-at-all"), inv(S)))
check("a blank key, a missing key, a key with a line break or a tab and a key over 200 characters are 400", lambda: all(cr._client_get("involved", p)[0] == 400 for p in ({"key": ""}, {"key": "   "}, {}, {"key": "a\nb"}, {"key": "a\tb"}, {"key": "x" * 201})), [cr._client_get("involved", p)[0] for p in ({"key": ""}, {}, {"key": "x" * 201})])
check("the 400 is a plain line naming the key, as items gives it", lambda: cr._client_get("involved", {})[1] == "text/plain" and "key" in cr._client_get("involved", {})[2], cr._client_get("involved", {}))
check("a key of 200 characters is a key: 200 {items: []}", lambda: inv("x" * 200) == (200, {"items": []}))

# a name is matched whole, and as written
check(f"a key that is only the start of stored names names nobody (`work` against `{A}` and `{B}`)", lambda: inv("work") == (200, {"items": []}), inv("work"))
check(f"a key that a stored name is only the start of names nobody (`{A}-2`)", lambda: inv(A + "-2") == (200, {"items": []}), inv(A + "-2"))
check(f"a key that is a stored name in other letter case names nobody (`{A.upper()}`)", lambda: inv(A.upper()) == (200, {"items": []}), inv(A.upper()))

# the two readings a row's list also rests on: the queue rule and the retired on-hold status
def queue_rule(on):
    if on: _cfg.CFG.setdefault("model", {})["queued_behind"] = True
    else: _cfg.CFG.get("model", {}).pop("queued_behind", None)
    forget_queue()
def forget_queue(): _audit_ticks._QUEUE_CACHE.update(at=0.0, map={})          # the queue map is kept for some seconds: the next read works it out again
def roles_builds(call):
    """How many times the session roles were built while `call` ran (anchors.session_roles reads the projects waiting for their page once per build)."""
    n = [0]; real = _prj.with_pending
    def counted(*a, **k):
        if sys._getframe(1).f_code.co_name == "session_roles": n[0] += 1
        return real(*a, **k)
    _prj.with_pending = counted
    try: call()
    finally: _prj.with_pending = real
    return n[0]
put(50, subject="[home] the item a session has in hand", age=0.01, contact=A, mover=S, last_activity={"at": now0, "kind": _la.STATE_CHANGE, "what": "moved"})
put(51, subject="[home] an idle item of the same session", age=2.1, contact=A, mover=S)
put(52, status="on_hold", subject="[home] stored with the retired status", age=2.2, contact=A, mover=S)
try:
    queue_rule(False)
    check("with the queue rule off the idle item of a busy session is an agent's", lambda: rows(A)[shown(51)]["list"] == "agents", rows(A).get(shown(51)))
    queue_rule(True)
    check("an item queued behind another of its mover is listed waiting, as `items?key=` lists it; it is not held and has no day, and the item in hand is the agents'",
          lambda: (lambda u: u[shown(51)]["list"] == "waiting" == items_row(51, S)["list"] and u[shown(51)]["held"] is False and u[shown(51)]["until"] is None and u[shown(50)]["list"] == "agents")(rows(A)),
          {n: rows(A).get(shown(n)) for n in (50, 51)})
    queue_rule(False)
    check("an item stored with the retired on-hold status is in the answer as an open item that is held, listed as `items?key=` lists it, with no day",
          lambda: (lambda x, y: x["held"] is True and y["held"] is True and x["list"] == y["list"] == "waiting" and x["until"] is None)(rows(A)[shown(52)], items_row(52, S)), (rows(A).get(shown(52)), items_row(52, S)))
    check("…and the read left its file as it was stored", lambda: json.loads((T / "store/a/52.json").read_text())["status"] == "on_hold")

    # the session roles are worked out once for a read, not once for each item it looks at
    check("the counter of role builds counts one build for each call outside a pass memo", lambda: not _passmemo.active() and roles_builds(lambda: [_anc.session_roles() for _ in range(3)]) == 3)
    for on in (False, True):
        queue_rule(on); word = "on" if on else "off"
        def one(): forget_queue(); inv(A)
        def two(): one(); one()
        check(f"the session roles are built once for a read, however many open items it looks at (queue rule {word})", lambda: roles_builds(one) == 1, roles_builds(one))
        check(f"…and once more for the next read: the memo ends with its request (queue rule {word})", lambda: roles_builds(two) == 2 and not _passmemo.active(), roles_builds(two))
        def same():
            forget_queue(); with_memo = cr._client_get("involved", {"key": A})
            forget_queue(); without = cr._client_involved(A)
            return with_memo == without and with_memo[0] == 200 and len(json.loads(with_memo[2])["items"]) == len(FOR_A) + 3
        check(f"…and the answer is byte for byte the answer without the memo (queue rule {word})", same)
finally:
    queue_rule(False)
    for n in (50, 51, 52): drop(n)

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
check("client.py knows the read, and its usage text names the form and each field", lambda: "involved" in client.READS and "involved <session>" in usage and all(w in part for w in ("shown", "subject", "url", "mover", "contact", "observers", "list", "held", "until (the day a held item comes back", "YYYY-MM-DD", "null for an item that is not held", "state_updated", "updated", "newest write first", "400")), part[:200])
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
SHAPE = '{"items": [{' + ", ".join(f'"{f}"' for f in FIELDS) + '}]}'
example = lambda: json.loads(sec.split("```json", 1)[1].split("```", 1)[0])["items"]
check("the contract's shape line lists exactly the row's fields, in order", lambda: SHAPE in sec, sec[:200])
check("the contract's example rows carry exactly those fields, a day on the held row and null on the others", lambda: all(list(x) == FIELDS for x in example()) and all((x["until"] is not None) == x["held"] for x in example()) and any(x["held"] for x in example()), sec[-600:])
check("the contract describes the read: the route, the auth, each field, the order and the client's form", lambda: "GET /client/involved?key=<session>" in sec and "Bearer <machine token>" in sec and all(f"\"{f}\"" in sec for f in FIELDS) and "last write first" in sec and "get involved <session>" in sec and "`until` is `\"YYYY-MM-DD\"`" in sec and "that is not held" in sec and "instance's own time zone" in sec, sec[:200])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": client involved scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
