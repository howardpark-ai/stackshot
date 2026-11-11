"""Scenario test for the Notion receiver (anchorhub/notion.py): a scripted Notion (a fake API, no network) is played against
notion.run and every hub.event call is recorded, then compared with notion_expected.jsonl. The expected file was produced by the
receiver as it was before batch 6 (four copies of the scan logic) and matched by the one-scan version, 2026-10-01.
It covers: a watched page (baseline, comment, edit), a database (row edited, row added, row comment), a subpage of a page and of
a row, self / system / trashed changes (no notice), a reboot's catch-up (page, database, a page with no saved state), and that
nothing repeats afterwards. Takes about 15 s (the receiver's loop waits 1 s per pass).

    tests/run-suite notion            compare with the expected file → exit 0 / 1
    tests/run-suite notion --print    print what the receiver emits (to regenerate the expected file on purpose)"""
import sys, os, json, io, time, re, pathlib, tempfile, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="hubtest-")
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
assert n1 == 1 and n2 == 1
toml, n3 = re.subn(r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"', toml); assert n3 == 1   # a fixed zone, so nothing depends on the host's (the expected events carry offsets from T0, not clock times)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.makedirs(f"{tmp}/state/anchor-hub"); os.makedirs(f"{tmp}/secrets/anchor-hub")
pathlib.Path(tmp, "secrets/anchor-hub/env").write_text("NOTION_TOKEN=tok\nNOTION_HOOK_TOKEN=hooktok\n")
sys.path.insert(0, STACK)

T0 = float(int(time.time() // 60 * 60))
def iso(off): return datetime.fromtimestamp(T0 + off, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
def hx(c): return (c * 32)[:32]
ME, OTHER, BOT, SYS = hx("1"), hx("2"), hx("3"), "00000000-0000-0000-0000-000000000001"
PAGE, PAGE2, PAGE3, DB, DS = hx("a"), hx("9"), hx("8"), hx("b"), hx("c")
ROW1, ROW2, ROW3, ROW4, ROW5, SUB1, SUB2 = hx("d"), hx("e"), hx("f"), hx("4"), hx("5"), hx("6"), hx("7")
names = {ME: "Oliver Quinn", OTHER: "Dana Lee"}
pages, comments = {}, {}
def page(pid, title, parent, created, edited, by=OTHER, cby=OTHER, **kw):
    typ, val = parent
    pages[pid] = {"id": pid, "url": f"https://www.notion.so/{pid}", "parent": {"type": typ, typ: val}, "created_time": iso(created), "last_edited_time": iso(edited),
                  "created_by": {"id": cby}, "last_edited_by": {"id": by}, "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}}, **kw}
def comment(block, cid, text, at, by=OTHER):
    comments.setdefault(block, []).append({"id": cid, "created_time": iso(at), "created_by": {"id": by}, "rich_text": [{"plain_text": text}]})
page(PAGE, "Launch plan", ("workspace", True), -90000, -3600); comment(PAGE, "c-old", "an old comment", -5000)
page(PAGE2, "Self and system page", ("workspace", True), -90000, -3600)
page(PAGE3, "Late binding", ("workspace", True), -90000, -3600); comment(PAGE3, "p3-old", "before the pause", -600)
page(ROW1, "Row one: the Acme release", ("database_id", DB), -7200, -3600); comment(ROW1, "r1-old", "old row comment", -4000)
page(ROW3, "Row three", ("database_id", DB), -7200, -3600)
page(ROW4, "Row four (trashed)", ("database_id", DB), -7200, -3600)
page(SUB2, "Draft under row one", ("page_id", ROW1), -7200, -3600)

def fake(req, timeout=None):
    u = urllib.parse.urlparse(req.full_url); path = "/" + u.path.split("/", 2)[2]; q = urllib.parse.parse_qs(u.query); method = req.get_method()
    ver = {k.lower(): v for k, v in req.header_items()}.get("notion-version")
    def ok(o): return io.BytesIO(json.dumps(o).encode())
    def nf(): raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    users = {"results": [{"id": ME, "type": "person", "name": names[ME], "person": {"email": "you@example.com"}},
                         {"id": OTHER, "type": "person", "name": names[OTHER], "person": {"email": "dana@example.io"}}]}
    if path == "/users/me": return ok({"type": "bot", "id": BOT, "bot": {"owner": {"user": {"id": ME}}}})
    if path == "/users": return ok(users)
    if path.startswith("/users/"): uid = path.split("/")[2]; return ok({"id": uid, "name": names[uid]}) if uid in names else nf()
    if path.startswith("/databases/") and path.endswith("/query") and method == "POST":
        db = path.split("/")[2]; body = json.loads(req.data or b"{}")
        if db != DB: nf()
        rows = [p for p in pages.values() if p["parent"].get("database_id") == DB]
        f = ((body.get("filter") or {}).get("last_edited_time") or {}).get("on_or_after")
        if f: rows = [r for r in rows if r["last_edited_time"] >= f]
        rows.sort(key=lambda r: r["last_edited_time"], reverse=True)
        return ok({"results": rows[: body.get("page_size", 100)]})
    if path.startswith("/databases/"):
        if path.split("/")[2] != DB: nf()
        d = {"id": DB, "title": [{"plain_text": "Launch tracker"}], "url": f"https://www.notion.so/{DB}"}
        if ver == "2025-09-03": d["data_sources"] = [{"id": DS}]
        return ok(d)
    if path.startswith("/pages/"): pid = path.split("/")[2]; return ok(pages[pid]) if pid in pages else nf()
    if path.startswith("/blocks/"): nf()
    if path == "/comments": return ok({"results": comments.get(q["block_id"][0], [])})
    raise AssertionError("unexpected call " + method + " " + path)
urllib.request.urlopen = fake

import logging; logging.disable(logging.INFO)
from stackshot.anchors.anchorhub import core, notion
Hub, run = core.Hub, notion.run
hub = Hub(); events = []
def rec(anchor, summary, kind="slack"):
    ts = summary.get("ts")
    off = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() - T0) if isinstance(ts, str) and "T" in ts else ts
    events.append({"anchor": anchor, "kind": kind, "label": f"{core._anc.kind_of(anchor)} {summary['title']}", "who": summary["who"], "text": summary["text"], "url": summary["url"], "ts": off})
hub.event = rec
hub.bindings = {f"notion:{PAGE}": {"s"}, f"notion:{PAGE2}": {"s"}, f"notion:{DB}": {"s"}}
hub.status["anchors"][f"notion:{PAGE}"] = {"type": "Notion", "title": '"Launch plan"', "label": 'Notion "Launch plan"'}
run(hub)
def mark(name): events.append({"--": name})
def settle(s=3.5): time.sleep(s)
settle(3.0); mark("baseline done (no events expected above)")
# ---- round 1: pushes
comment(PAGE, "c1", "Looks good — ship it", 60); pages[PAGE].update(last_edited_time=iso(180), last_edited_by={"id": OTHER})
pages[ROW1].update(last_edited_time=iso(200), last_edited_by={"id": OTHER}); comment(ROW1, "r1-c1", "who signs this off?", 200)
page(ROW2, "Row two: a new release", ("database_id", DB), 240, 240)
page(SUB1, "Notes under the plan", ("page_id", PAGE), 240, 240); comment(SUB1, "s1-c1", "first note", 250)
pages[SUB2].update(last_edited_time=iso(260), last_edited_by={"id": OTHER})
pages[ROW3].update(last_edited_time=iso(240), last_edited_by={"id": ME}); comment(ROW3, "r3-mine", "my own comment", 240, by=ME)
pages[PAGE2].update(last_edited_time=iso(240), last_edited_by={"id": SYS}); comment(PAGE2, "p2-mine", "mine", 240, by=ME)
pages[ROW4].update(last_edited_time=iso(240), last_edited_by={"id": OTHER}, in_trash=True)
for x in (PAGE, ROW1, ROW2, SUB1, SUB2, ROW3, PAGE2, ROW4): hub.triggers.put(("notion", x))
settle(); mark("round 1 done")
# ---- round 2: the same things again, now with saved state
comment(PAGE, "c2", "A long one: " + "lorem ipsum dolor sit amet " * 8, 300)
pages[ROW1].update(last_edited_time=iso(320), last_edited_by={"id": OTHER})
pages[SUB1].update(last_edited_time=iso(320), last_edited_by={"id": OTHER})
pages[PAGE2].update(last_edited_time=iso(320), last_edited_by={"id": OTHER})
for x in (PAGE, ROW1, SUB1, PAGE2): hub.triggers.put(("notion", x))
settle(); mark("round 2 done")
# ---- round 3: a reboot's catch-up (no pushes): changes after `since`, one page with no saved state
comment(PAGE, "c3", "during the downtime", 400); pages[PAGE].update(last_edited_time=iso(400), last_edited_by={"id": OTHER})
comment(PAGE, "c3-mine", "my own, during the downtime", 410, by=ME)
comment(PAGE3, "p3-new", "new on the late page", 420); pages[PAGE3].update(last_edited_time=iso(420), last_edited_by={"id": OTHER})
pages[ROW1].update(last_edited_time=iso(460), last_edited_by={"id": OTHER}); comment(ROW1, "r1-c2", "comment on a caught-up row", 460)
page(ROW5, "Row five: added while down", ("database_id", DB), 460, 460)
pages[PAGE2].update(last_edited_time=iso(380), last_edited_by={"id": OTHER})        # before `since`: not news
with hub.lock: hub.bindings[f"notion:{PAGE3}"] = {"s"}
n = hub.catchups["notion"](T0 + 390)
mark(f"catch-up returned {n}")
settle(2.5); mark("after the catch-up (the loop has run again)")
# ---- round 4: a push after the catch-up must not repeat anything
for x in (PAGE, PAGE3, ROW1, ROW5): hub.triggers.put(("notion", x))
settle(); mark("round 4 done (nothing new expected)")
saved = hub.savers["notion"]()
def norm(o):
    if isinstance(o, dict): return {str(k): norm(v) for k, v in sorted(o.items(), key=lambda kv: str(kv[0])) if k not in ("base", "last_iso")}
    if isinstance(o, (set, frozenset, list, tuple)): return sorted((norm(v) for v in o), key=str) if isinstance(o, (set, frozenset)) else [norm(v) for v in o]
    return re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+Z", lambda m: "T%+d" % int(datetime.fromisoformat(m.group(0).replace("Z", "+00:00")).timestamp() - T0), o) if isinstance(o, str) else o
got = [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events] + ["STATE " + json.dumps(norm(saved), ensure_ascii=False, sort_keys=True)]
if "--print" in sys.argv:
    print("\n".join(got)); sys.stdout.flush(); os._exit(0)
want = pathlib.Path(SCR, "notion_expected.jsonl").read_text(encoding="utf-8").rstrip("\n").split("\n")
if got == want: print(f"ok: notion receiver, {sum(1 for e in events if 'anchor' in e)} events as expected"); sys.stdout.flush(); os._exit(0)
for i, (g, w) in enumerate(zip(got, want)):
    if g != w: print(f"line {i + 1}\n  expected: {w[:300]}\n  got:      {g[:300]}"); break
else: print(f"length differs: expected {len(want)} lines, got {len(got)}")
sys.stdout.flush(); os._exit(1)
