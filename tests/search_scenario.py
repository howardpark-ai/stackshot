"""Scenario test for the board's search index and query (search.py; the results page itself is drawn by ui/search.py and has its own suite, ui_search) — fixture data,
a store that is a git repo (the History of an item is read from it), the HTTP route through Starlette's test client; no live store, no network.

Covers: each of the four kinds found and linked (an item by its subject, goal, description, next and ask and by its id; a History entry; a project
page's Current state; a session name, linked to sala while its pane lives and plain text when it does not); results grouped by kind in a fixed order;
an update re-indexes (the new word is found at once, the old one is not, two writes inside one clock tick included; a deleted item goes; a page
rewritten is read again); a Japanese query (a prefix of a word, Japanese in the subject, the description and the History); a query of one character, an
empty one and one with no word in it find nothing; a match marker cannot be forged from text; a very long query is cut, not an error; the index file
lives in the state directory and survives a restart (nothing is indexed twice), a schema change rebuilds it; the LIKE fallback answers the same;
the server's one item save asks for the item to be re-indexed; the results page at /search syncs before it answers, says when the index is being built
or rebuilt, and lets a code bug through.

    tests/run-suite search        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, tempfile, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="searchtest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"
SALA = "https://sala.example.org/#s={name}"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
toml = toml.replace('session_view = ""', f'session_view = "{SALA}"', 1); assert "sala.example.org" in toml                  # live session names drawn as their sala links
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets", "touch"): (T / d).mkdir(parents=True)
STORE = T / "store"

S1, S2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({
    S1: {"name": "home-x-main", "machine": "a", "url": "", "seen": "x"},
    S2: {"name": "home-old-pane", "machine": "a", "url": "", "seen": "x", "gone": "2020-01-01T00:00:00Z"}}))     # long gone: a name, no live pane
page = {"title": "Alpha project", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-x-main", "status": "active", "board": [], "board_row": False,
        "updated": 1, "mirror": "https://example.invalid/alpha"}
(STORE / "projects.json").write_text(json.dumps({"pages": {"projects/alpha": page}})); (STORE / "next-id").write_text("20"); (STORE / "anchors.json").write_text("{}")
BRAIN_PAGE = T / "brain/projects/alpha.md"
BRAIN_PAGE.write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state (as of 2026-10-26)\n- the narwhal tusk is calibrated and the ferret waits\n\n## Timeline\n- 2026-10-01 | home | started the zzzdated line\n")


def item(i, subject, description="A thing. It lives here. Done when done.", status="open", **md):
    p = STORE / f"a/{i}.json"
    p.write_text(json.dumps({"id": str(i), "subject": subject, "description": description, "status": status,
                             "metadata": {"owner": S1, "project": "projects/alpha", **md}, "updated": time.time() - 3600 + int(i)}, ensure_ascii=False))
    return p


def git(*a): subprocess.run(["git", "-C", str(STORE), *a], check=True, capture_output=True)


git("init", "-q"); git("config", "commit.gpgsign", "false")
item(1, "[home] Quokka migration plan", "the wombat checkpoint comes first", goal="ship the marsupial move", next="home-x-main: tune the zebra", ask="Decide: which kangaroo?")
item(2, "[home] ボード・検索・試験", "日本語・説明です", next="home-x-main: かな・次の・段階")
item(3, "[home] Danger <script>alert(1)</script> xss", "<img src=x onerror=alert(2)> and a\x02forged\x03 marker", next="home-x-main: <b>bold</b> next")
item(4, "[home] Finished kiwi", "closed long ago", status="completed", outcome="done", reason="the kiwi is shipped")
item(5, "[home] Obsolete platypus", "second version follows")
git("add", "-A"); git("commit", "-q", "-m", "first versions")
item(5, "[home] Renamed item", "second version follows", answers=[{"ts": time.time() - 100, "kind": "decision", "choice": "Go", "text": "proceed with the aardvark plan", "via": "board"}])
item(2, "[home] ボード・検索・試験 (修正)", "日本語・説明です", next="home-x-main: かな・次の・段階")                           # a Japanese subject edit: the History keeps the old one
git("add", "-A"); git("commit", "-q", "-m", "second versions")

sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

import server, render, search
from ui import search as ui_search, render as ui_render
server._publish = lambda: None
from starlette.testclient import TestClient

SEL = lambda q: {k: [x["key"] for x in v] for k, v in search.query(q).items() if v}      # {kind: [keys]} of a query
fresh = lambda: render.Board(str(STORE))
b0 = fresh()
r0 = search.sync(b0)
check("the first sync indexes every item, the project page and the sessions, with nothing left", r0["items"] == 5 and r0["pages"] == 1 and r0["sessions"] >= 2 and r0["left"] == 0 and not search.building(), r0)
check("the index file lives under the state directory", (T / "state/search/index.db").is_file() and search.size_bytes() > 0, search.size_bytes())

# ---- 1. the four kinds, each found by its own text
check("item: found by a word of its subject", SEL("quokka").get("item") == ["a1"], SEL("quokka"))
check("item: …of its description", SEL("wombat").get("item") == ["a1"] and SEL("checkpoint").get("item") == ["a1"], SEL("wombat"))
check("item: …of its goal", SEL("marsupial").get("item") == ["a1"], SEL("marsupial"))
check("item: …of its next lines", SEL("zebra").get("item") == ["a1"], SEL("zebra"))
check("item: …of its ask", SEL("kangaroo").get("item") == ["a1"], SEL("kangaroo"))
check("item: found by its id, as shown and as stored", SEL("a1").get("item") == ["a1"] and "a1" in SEL("a1 quokka").get("item", []), SEL("a1"))
check("item: a closed item is found too", SEL("kiwi").get("item") == ["a4"], SEL("kiwi"))
check("item: a prefix of a word finds it (a typed word is not yet whole)", SEL("quok").get("item") == ["a1"] and SEL("wombat check").get("item") == ["a1"], SEL("quok"))
check("item: every word must match (an AND)", SEL("quokka zebra").get("item") == ["a1"] and not SEL("quokka kiwi").get("item"), SEL("quokka kiwi"))
hist = SEL("platypus")
check("history: an entry of the item's History is found (the old subject of an edit: its first version and its edit), under its item", set(hist.get("history", [])) == {"a5"} and len(hist["history"]) == 2, hist)
check("history: …and the text of an answer", SEL("aardvark").get("history") == ["a5"], SEL("aardvark"))
check("history: the renamed item is found by its new subject as an item, not by the old one", SEL("renamed").get("item") == ["a5"] and not SEL("platypus").get("item"), SEL("platypus"))
check("project: the Current state of a project page is found, under its page key", SEL("narwhal").get("project") == ["projects/alpha"], SEL("narwhal"))
check("project: …and the page's timeline is not (only the Current state is indexed)", not SEL("zzzdated"), SEL("zzzdated"))
check("project: …nor is the page found by its name and key", SEL("alpha").get("project") == ["projects/alpha"], SEL("alpha"))
check("session: a session name is found, whole or by a part of it", SEL("home-x-main").get("session") == ["home-x-main"] and SEL("x-main").get("session") == ["home-x-main"] and SEL("old-pane").get("session") == ["home-old-pane"], SEL("x-main"))
check("no match: nothing, in no kind", SEL("nonexistentword") == {}, SEL("nonexistentword"))

# ---- 2. one character, empty, no word
check("a query of one character finds nothing", SEL("q") == {} and SEL("a") == {} and SEL("日") == {}, SEL("q"))
check("an empty query, and spaces alone, find nothing", SEL("") == {} and SEL("   ") == {}, SEL(""))
check("a query with no letter or digit in it finds nothing (and is no FTS syntax error)", SEL('"*') == {} and SEL("()-:") == {} and SEL("^ + ~") == {}, SEL('"*'))
check("a query of FTS syntax is only words: quotes, a star, NEAR, a column filter, an operator word", SEL('"quokka"').get("item") == ["a1"] and SEL("NEAR(zebra quokka)") == {} and SEL("title:quokka") == {}
      and SEL("quokka OR kiwi") == {} and SEL("quokka NOT zebra") == {}, [SEL(x) for x in ('"quokka"', "NEAR(zebra quokka)", "title:quokka", "quokka OR kiwi")])

# ---- 3. Japanese
check("Japanese: a word of a subject is found", SEL("ボード").get("item") == ["a2"], SEL("ボード"))
check("Japanese: a word of the description (the whole word, and a prefix of it)", SEL("日本語").get("item") == ["a2"] and SEL("日本").get("item") == ["a2"], SEL("日本"))
check("Japanese: a word of the next lines", SEL("かな").get("item") == ["a2"], SEL("かな"))
check("Japanese: a prefix of a word typed with its particle left off (ボードで would carry one)", SEL("検索").get("item") == ["a2"], SEL("検索"))
check("Japanese: two words (an AND) and a word with a Latin one", SEL("ボード 検索").get("item") == ["a2"] and not SEL("ボード quokka").get("item"), SEL("ボード 検索"))
check("Japanese: the History keeps what the edit replaced (the subject it was)", set(SEL("試験").get("history", [])) == {"a2"} and SEL("修正").get("item") == ["a2"], SEL("試験"))

# ---- 4. the results page at /search (its markup is checked in ui_search; here only what the index owes it)
COOKIE = server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(server._UI_COOKIE, cookie)
        return c.get(path, follow_redirects=False)
    r = get("/search?q=" + "x" * 5000)
    check("a very long query is cut, not an error", r.status_code == 200 and len(r.text) < 200000)
    r = get("/search?q=forged")
    check("control characters in text cannot forge a match marker (only the snippet's own <mark>)", "forged" in r.text and r.text.count("<mark>") == r.text.count("</mark>") and "\x02" not in r.text and "\x03" not in r.text, r.text.count("<mark>"))

    # ---- 6. an update re-indexes
    server._save("a1", {**json.loads((STORE / "a/1.json").read_text()), "description": "the okapi checkpoint comes first"})
    check("the server's one item save asks for the item to be re-indexed", "a1" in search._FORCE, search._FORCE)
    r = get("/search?q=okapi")
    check("an update re-indexes: the new word is found at once (the results page syncs before it answers), the old one is not", 'href="/items/a1"' in r.text and "wombat" not in r.text and SEL("okapi").get("item") == ["a1"], SEL("okapi"))
    check("…its History is the thread's (the page never reads git): the item is owed and touched again, the next full sync reads it; an item whose History was read before is not 'partial' (no 'still being built')", "a1" in search._FORCE and "a1" not in search._PARTIAL and not search.building() and search.sync(fresh())["items"] >= 1 and "a1" not in search._FORCE, search._FORCE)
    check("…and the old word finds nothing", SEL("wombat") == {})
    p1 = STORE / "a/1.json"; d1 = json.loads(p1.read_text())
    st = p1.stat()
    d1["description"] = "the tapir checkpoint comes first"                        # the same size, the same instant: only the touch can tell
    p1.write_text(json.dumps(d1, ensure_ascii=False, indent=1)); os.utime(p1, ns=(st.st_atime_ns, st.st_mtime_ns))
    search.sync(fresh())
    check("a write the stamp cannot see is not indexed until it is touched", search.sync(fresh())["items"] == 0 and SEL("tapir") == {})
    search.touch("a1")
    check("…touched, it is (the save does this)", search.sync(fresh())["items"] == 1 and SEL("tapir").get("item") == ["a1"] and not SEL("okapi"), SEL("tapir"))
    item(6, "[home] Brand new gecko item")
    check("a new item file is found by the next query", get("/search?q=gecko").text.count('href="/items/a6"') >= 1)
    (STORE / "a/6.json").unlink()
    check("a deleted item is no longer found", 'href="/items/a6"' not in get("/search?q=gecko").text and SEL("gecko") == {}, SEL("gecko"))
    BRAIN_PAGE.write_text(BRAIN_PAGE.read_text().replace("narwhal tusk", "manatee flipper")); os.utime(BRAIN_PAGE, (time.time() + 10, time.time() + 10))
    r = get("/search?q=manatee&w=all")
    check("a project page rewritten is read again: the new Current state is found, the old words are not", 'href="/projects/alpha"' in r.text and SEL("narwhal") == {}, SEL("manatee"))
    d3 = json.loads((STORE / "a/3.json").read_text()); d3["description"] = "second text"; (STORE / "a/3.json").write_text(json.dumps(d3))
    item(1, "[home] Quokka migration plan", "the okapi checkpoint", goal="ship the marsupial move", next="home-x-main: tune the zebra", ask="Decide: which kangaroo?")
    check("a hand-edited store file (no save) is indexed by the stamp alone", search.sync(fresh())["items"] >= 2 and SEL("okapi").get("item") == ["a1"])

# ---- 7. the index: size, restart, schema, build in chunks
b1 = fresh()
check("a restart keeps the index: nothing is indexed twice (the stamps are in the file)", (search.reset(), search.sync(b1))[1]["items"] == 0 and SEL("okapi").get("item") == ["a1"], SEL("okapi"))
import sqlite3
con = sqlite3.connect(str(T / "state/search/index.db")); n_doc = con.execute("select count(*) from doc").fetchone()[0]; kinds = dict(con.execute("select kind, count(*) from doc group by kind").fetchall()); con.close()
check("the index holds rows of all four kinds", set(kinds) == set(search.KINDS) and n_doc == sum(kinds.values()), kinds)
search.reset(); con = sqlite3.connect(str(T / "state/search/index.db")); con.execute("pragma user_version=0"); con.close()
check("a schema change drops the index and builds it again", search.sync(fresh())["items"] == 5 and SEL("okapi").get("item") == ["a1"])
search.reset(); (T / "state/search/index.db").unlink()
tot = search.build(fresh)
check("build() indexes everything in chunks and says nothing is left", tot["items"] == 5 and tot["left"] == 0 and not search.building(), tot)
search.reset(); (T / "state/search/index.db").unlink()
part = search.sync(fresh(), max_items=2)
check("a bounded sync indexes the newest first and says what is left; the index is 'being built' until it is done", part["items"] == 2 and part["left"] == 3 and search.building(), part)
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    c.cookies.set(server._UI_COOKIE, COOKIE)
    rr = c.get("/search?q=home")
    check("the results page indexes the rest of the items' text in one visit (REQUEST_ITEMS a visit), the History is owed to the thread; the thread's pass finishes it and drops the note",
          "a2" in " ".join(search._PARTIAL) and search.building() and search.sync(fresh())["left"] == 0 and not search.building() and "still being built" not in c.get("/search?q=home").text, (search._PARTIAL, search.building()))
search.reset(); (T / "state/search/index.db").unlink()
search.sync(fresh(), max_items=1)
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    c.cookies.set(server._UI_COOKIE, COOKIE)
    check("…and says so while it is still going", "still being built" in c.get("/search?q=home").text or not search.building())

# ---- 8. the LIKE fallback (a SQLite build without FTS5) answers the same
search.reset(); (T / "state/search/index.db").unlink(); search._FTS = False
search.sync(fresh())
check("fallback: the same four kinds found, Japanese too", SEL("quok").get("item") == ["a1"] and SEL("今日") == {} and SEL("ボード").get("item") == ["a2"] and SEL("narwhal") == {} and SEL("manatee").get("project") == ["projects/alpha"]
      and SEL("home-x-main").get("session") == ["home-x-main"] and SEL("aardvark").get("history") == ["a5"], {q: SEL(q) for q in ("quok", "ボード", "manatee", "aardvark")})
check("fallback: one character and an empty query find nothing; a % or _ is no wildcard", SEL("q") == {} and SEL("") == {} and SEL("%%") == {} and SEL("qu%") == SEL("qu") and SEL("quok_a") == {}, SEL("quok_a"))
check("fallback: a snippet marks the match", "\x02" in (search.query("okapi")["item"][0]["snip"]), search.query("okapi")["item"])
search.reset(); search._FTS = True; (T / "state/search/index.db").unlink()
search.sync(fresh())
check("…and the next start with FTS5 recreates the table (the mode is part of the schema)", SEL("okapi").get("item") == ["a1"])
_dbp = search._db_path; search.reset(); search._db_path = lambda: pathlib.Path("/proc/nope/index.db")          # a path that cannot be made: the index is in memory
try:
    search.sync(fresh())
    check("an unwritable state directory falls back to memory and still answers", SEL("okapi").get("item") == ["a1"] and search.size_bytes() == 0, SEL("okapi"))
finally:
    search._db_path = _dbp; search.reset()
# ---- 10. the pass: a failing item, the lock, the mirror, an empty History, a partial Board, a damaged file
import types, threading, sqlite3 as _sq
search.reset(); (T / "state/search/index.db").unlink(missing_ok=True); search._FAILED.clear(); search._PARTIAL.clear(); search.PAUSE = 0.0
_ow = search._write_item
def _bad_write(con, p):
    if p["gid"] == "a2": raise ValueError("boom")
    return _ow(con, p)
search._write_item = _bad_write
t0 = time.time(); tot = search.build(fresh)
check("1: an item that keeps failing is left out for the rest of the pass: build() returns, names it, and the others are in", time.time() - t0 < 60 and tot["failed"] == ["a2"] and tot["left"] == 0 and tot["items"] == 4 and SEL("quokka").get("item") == ["a1"], tot)
check("1: …and it is not tried again before RETRY_AFTER (a new pass indexes nothing)", search.build(fresh)["items"] == 0 and "a2" in search._FAILED)
search._write_item = _ow; search._FAILED.clear()
check("1: …once the window is over (or the cause gone) it is indexed", search.build(fresh)["items"] == 1 and SEL("ボード").get("item") == ["a2"])
_calls = []
_os = search.sync
search.sync = lambda board, max_items=None, skip=None, history=True: (_calls.append(1), {"items": 0, "pages": 0, "sessions": 0, "left": 5, "failed": []})[1]
tot = search.build(fresh)
search.sync = _os
check("1: a pass whose chunks index nothing ends after STALL of them", len(_calls) == search.STALL and tot["left"] == 5, _calls)

free = []; b = fresh(); _ie = b.item_events
def _probe(r):
    got = []
    th = threading.Thread(target=lambda: got.append(search._LOCK.acquire(timeout=3)) or (got[0] and search._LOCK.release())); th.start(); th.join()
    free.append(got[0]); return _ie(r)
b.item_events = _probe; search.touch("a1"); search.touch("a5"); search.sync(b)
check("2: the History is read with the lock free (another thread takes it meanwhile)", len(free) == 2 and all(free), free)

item(7, "[home] Mirror item")
check("3: a new item is read once, the stamp being the item file's alone (the mirror keeps no copy of an issue's comments)", search.sync(fresh())["items"] == 1)

b = fresh(); _ie = b.item_events
b.item_events = lambda r: ([], 0) if r["gid"] == "a3" else _ie(r)
search.touch("a3"); r4 = search.sync(b)
con = search._con(); st3 = con.execute("select sig from stamp where kind='item' and key='a3'").fetchone()[0]
check("4: an item whose History came back empty (a git timeout) keeps its text in the index but is not stamped as done, and is named", r4["failed"] == ["a3"] and st3.endswith("!") and SEL("danger").get("item") == ["a3"] and "a3" not in search._PARTIAL, (r4, st3))
check("4: …and is not tried again within RETRY_AFTER", (search.touch("a3"), search.sync(b))[1]["items"] == 1 and "a3" in search._FAILED and search.sync(b)["items"] == 0)
search._FAILED.clear(); r4 = search.sync(fresh())
check("4: …with git answering again it is read and stamped", r4["items"] >= 1 and not search._con().execute("select sig from stamp where key='a3'").fetchone()[0].endswith("!"), r4)

for i in range(30, 45): item(i, f"[home] filler number {i}")
search.sync(fresh())
con = search._con(); have = con.execute("select count(*) from stamp where kind='item'").fetchone()[0]
pb = fresh(); pb.rows = pb.rows[:3]
search.sync(pb)
check("5: a Board that read three items of twenty drops nothing (more than a tenth of the stamps)", con.execute("select count(*) from stamp where kind='item'").fetchone()[0] == have and SEL("quokka").get("item") == ["a1"] and SEL("filler").get("item"), have)
pb = fresh(); pb.rows = [r for r in pb.rows if r["gid"] != "a44"]
search.sync(pb)
check("5: …one gone item (a twentieth) is dropped", con.execute("select count(*) from stamp where kind='item'").fetchone()[0] == have - 1 and not SEL("number 44").get("item"), SEL("number 44"))
search.sync(fresh())          # the item is still in the store: back in
con = search._con(); have = con.execute("select count(*) from stamp where kind='item'").fetchone()[0]
for i in range(30, 38):       # a bulk re-key: eight of twenty-one items take new ids (the store as big as before), more than a tenth, and the old ones go
    (STORE / f"a/{i}.json").unlink(); item(100 + i, f"[home] filler number {100 + i}")
r5 = search.sync(fresh())
olds = con.execute("select count(*) from stamp where kind='item' and key in (%s)" % ",".join(f"'a{i}'" for i in range(30, 38))).fetchone()[0]
check("5: a re-key of more than a tenth (the Board as big as the stamps) drops the old rows and takes the new", olds == 0 and con.execute("select count(*) from stamp where kind='item'").fetchone()[0] == have and SEL(f"number {100 + 35}").get("item") == [f"a{100 + 35}"] and not SEL("number 35").get("item"), (olds, r5))

def _boom(ws): raise _sq.DatabaseError("database disk image is malformed")
_rq = search.find; search.find = _boom
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    c.cookies.set(server._UI_COOKIE, COOKIE)
    r6 = c.get("/search?q=quokka")
search.find = _rq
check("6: a damaged index: the page says it is being rebuilt, the file is dropped and the thread is woken", "being rebuilt" in r6.text and r6.status_code == 200 and not (T / "state/search/index.db").exists() and search._WAKE.is_set(), r6.text[r6.text.find("being rebuilt") - 100:][:300])
search._WAKE.clear(); search.build(fresh)
check("6: …the next pass builds it again", SEL("quokka").get("item") == ["a1"] and (T / "state/search/index.db").is_file())
search.reset(); (T / "state/search/index.db").write_bytes(b"this is not a database" * 400)
check("6: a file that is not a database is replaced at open, not served from memory", (search.sync(fresh()), not (T / "state/search/index.db").read_bytes().startswith(b"this is not"), SEL("quokka").get("item") == ["a1"])[1:] == (True, True))
check("1: only a damaged file is damage: a bare DatabaseError and the named OperationalErrors; a ProgrammingError, an IntegrityError, a lock or any other error is not",
      search._corrupt(_sq.DatabaseError("x")) and search._corrupt(_sq.OperationalError("no such table: doc")) and search._corrupt(_sq.OperationalError("database disk image is malformed"))
      and not any(search._corrupt(e) for e in (_sq.ProgrammingError("x"), _sq.IntegrityError("x"), _sq.OperationalError("database is locked"), _sq.InterfaceError("x"), ValueError("x"), _sq.NotSupportedError("x"))))
def _bug(ws): raise _sq.ProgrammingError("a code bug")
search.find = _bug
try:
    ui_search.results_html(ui_render.Board(str(STORE)), "quokka"); _raised = False
except _sq.ProgrammingError:
    _raised = True
finally:
    search.find = _rq
check("1: a code bug in the query shows as an error and does not delete the index", _raised and (T / "state/search/index.db").is_file() and SEL("quokka").get("item") == ["a1"])
check("7: the connection runs with synchronous=NORMAL in WAL mode", search._con().execute("pragma synchronous").fetchone()[0] == 1 and search._con().execute("pragma journal_mode").fetchone()[0] == "wal")
check("8: a term under two characters is dropped; nothing left finds nothing", search.terms("a bc d efg") == ["bc", "efg"] and SEL("a quokka") == SEL("quokka") and SEL("a b") == {} and SEL("日 ボード") == SEL("ボード"))
fake = types.SimpleNamespace(fleet={}, sess={"name:evil\x02name\x03": {"machine": "a"}, "name:\x02\x03": {"machine": "a"}}, rows=[], proj={})
search._sync_sessions(search._con(), fake)
rows = search._con().execute("select key, title, body from doc where kind='session'").fetchall()
check("11: a session name is cleaned before it is indexed (no match marker can come from it); an empty one is skipped", len(rows) == 1 and not any("\x02" in x or "\x03" in x for r in rows for x in r), rows)

# ---- 9. the thread: a save is in the index a moment later, with no page asked for
import threading
search.reset(); (T / "state/search/index.db").unlink(missing_ok=True); search.DEBOUNCE, search.EVERY = 0.05, 60.0
_tids = []
_base = os.getpriority(os.PRIO_PROCESS, threading.get_native_id())     # the runner's own nice (CI's unit runs at 10), read before the thread starts
threading.Thread(target=lambda: (_tids.append(threading.get_native_id()), search.loop(fresh)), daemon=True).start()
def wait_for(q, secs=20, whole=False):   # whole: also wait for the pass to end (the build lets the lock go between chunks of CHUNK items,
    end = time.time() + secs                 # so the first chunk is searchable while the rest is still to index)
    while time.time() < end:
        if SEL(q) and not (whole and search.building()): return True
        time.sleep(0.1)
    return False
check("the thread's first build indexes the store with no page asked for", wait_for("okapi", whole=True), (SEL("okapi"), search.building()))
check("7: the search thread runs at nice 10 (or at the runner's own, when that is higher) and the main thread keeps its own", bool(_tids) and os.getpriority(os.PRIO_PROCESS, _tids[0]) == max(10, _base) and os.getpriority(os.PRIO_PROCESS, threading.get_native_id()) == _base, (_base, _tids, os.getpriority(os.PRIO_PROCESS, _tids[0]) if _tids else None))
server._save("a4", {**json.loads((STORE / "a/4.json").read_text()), "description": "closed long ago, then a xylophone arrived"})
search.DEBOUNCE = 1.5; search._WAKE.set()
_t_end = time.time() + 10
while search._WAKE.is_set() and time.time() < _t_end: time.sleep(0.01)
_cleared = not search._WAKE.is_set(); time.sleep(0.2); search.touch("a4"); _kept = search._WAKE.is_set()
check("9: the wake is cleared before the pause, so a touch during the pause stays asked for", _cleared and _kept, (_cleared, _kept))
search.DEBOUNCE = 0.05
check("a save is in the index a moment later, from the thread (the box needs no page load to see it)", wait_for("xylophone") and SEL("xylophone").get("item") == ["a4"], SEL("xylophone"))


print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
