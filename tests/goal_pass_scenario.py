"""Scenario test for the one-time goal pass (tools/goal_pass.py) — fixture items, a fake judge, no live store, no model, no network, no server.

Covers: the pass judges EVERY open item, one call each, lowest id first, the ones with no `Goal:` bullet too and not the closed ones; each call's message names the check with the subject and the Goal sentence
(or the first bullet of an item with no Goal bullet); the report prints id, verdict (unclear / clear / not judged), the judge's reason, the subject and the first bullet, then the counts, to stdout and to a
file (`--out`, else <paths.state>/audit/goal-pass-<stamp>.txt); `--max-calls` cuts the list; `--dry-run` lists the items and makes no call and writes no file; a failed call is "not judged"; and it is REPORT ONLY:
no item in the store changes, no message is sent, no audit record is written or touched.

    tests/run-suite goal_pass        → exit 0 / 1"""
import hashlib, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="goalpass-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home").mkdir()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("1")

from stackshot.core import config as _cfg; from stackshot.audit import audit_run as AR; from stackshot.tools import goal_pass as GP; from stackshot.fleet import client as _client
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

H = 3600; now = time.time()
OWNER = "00000000-0000-4000-8000-000000000001"
def item(i, subject, desc, status="open"):
    d = {"id": str(i), "subject": subject, "description": desc, "status": status, "updated": now - H, "state_updated": now - H, "confirmed": now - H, "written_at": now - H, "written_by": "home-agent",
         "metadata": {"owner": OWNER, "project": "projects/alpha", "state": "doing", "needs": ["home-agent"], "next": "home-agent: build it"}}
    return f"a{i}", d
ITEMS = dict([
    item(3, "[home] The nightly run fails when the disk is full", "- Goal: The nightly run finishes even when the disk fills\n- Problem: it fails"),
    item(1, "[home] Make the nightly run finish by 06:00", "- Goal: The nightly run finishes by 06:00\n- Lives in the nightly unit"),
    item(2, "[home] Retry bug in the sync", "- The sync retries forever\n- Lives in sync.py"),
    item(4, "[home] An old closed item", "- Goal: Something that was finished", status="completed"),
    item(5, "[home] No bullets at all", "just prose here"),
])
STORE = T / "store"
for gid, d in ITEMS.items(): (STORE / gid[0]).mkdir(exist_ok=True); (STORE / gid[0] / f"{gid[1:]}.json").write_text(json.dumps(d), encoding="utf-8")
def tree_hash():
    h = hashlib.sha256()
    for p in sorted(STORE.rglob("*")):
        if p.is_file(): h.update(str(p.relative_to(STORE)).encode()); h.update(p.read_bytes())
    return h.hexdigest()

# nothing may be sent: any message through the client or the audit's deliver is a failure
sent = []
_client.message = lambda *a, **k: (sent.append(("client.message", a)) or (500, {}))
AR._deliver = lambda *a, **k: (sent.append(("deliver", a)) or (False, "x"))
asked = []
def judge_fake(message):
    """a fake judge: 'yes' (unclear) when the evidence names a failure or has no Goal bullet, else 'no'; '5' fails"""
    asked.append(message)
    if re.search(r"^Item board#5:", message, re.M): return {"status": "spawn", "note": "boom"}
    m = re.search(r"^Item (board#\d+):", message, re.M)
    unclear = " fails " in message.split("Candidate checks")[1] or "no Goal bullet" in message
    ans = {"finding": "yes", "check": "goal-unclear", "reason": f"{m.group(1)}: names a symptom", "fix": "f"} if unclear else {"finding": "no", "check": "", "reason": f"{m.group(1)}: names a result", "fix": ""}
    return {"status": "ok", "text": json.dumps(ans)}
def env(**kw): return AR.Env(runner=kw.pop("runner", judge_fake), deliver=lambda *a, **k: sent.append(("env.deliver", a)) or (False, "x"), push=lambda *a, **k: sent.append(("env.push", a)) or (False, "x"), **kw)

before = tree_hash(); AUD = T / "state/audit"
def audit_files(): return sorted(p.name for p in AUD.glob("*")) if AUD.exists() else []

# ---- 1. dry run: the list, no call, no file
lines = []
res = GP.run(dict(ITEMS), env=env(), dry=True, out=lines.append)
check("dry run: lists the open items, lowest id first, closed ones left out", [l.split(" · ")[0] for l in lines[1:]] == ["board#1", "board#2", "board#3", "board#5"], lines)
check("dry run: shows the subject and the first bullet, '(none)' for prose", any("board#2 · [home] Retry bug in the sync · first bullet: The sync retries forever" in l for l in lines) and any("board#5" in l and "first bullet: (none)" in l for l in lines), lines)
check("dry run: no call, and the CLI writes no file", asked == [] and GP.main(["--dry-run"], env=env(), items=dict(ITEMS)) == 0 and audit_files() == [] and asked == [], (len(asked), audit_files()))

# ---- 2. the full pass
asked.clear(); lines = []
res = GP.run(dict(ITEMS), env=env(), out=lines.append)
text = "\n".join(lines)
check("one call per open item (the Goal-less ones too), lowest id first, none for the closed one", [re.search(r"^Item (board#\d+):", m, re.M).group(1) for m in asked] == ["board#1", "board#2", "board#3", "board#5"], [m[:30] for m in asked])
check("the message of an item with a Goal bullet names the subject and the Goal sentence", "- goal-unclear: the subject and the Goal bullet, judged once for the pass: subject: [home] Make the nightly run finish by 06:00 | Goal: The nightly run finishes by 06:00" in asked[0], asked[0])
check("…and of an item with none its first bullet", "- goal-unclear: the item has no Goal bullet (filed before the form): subject: [home] Retry bug in the sync | first bullet: The sync retries forever" in asked[1], asked[1])
check("…and of prose with no bullet says so", "first bullet: (none)" in asked[3], asked[3])
check("the report: id, verdict and the judge's reason, then the subject and the first bullet, per item",
      "board#1 · clear · board#1: names a result\n  subject: [home] Make the nightly run finish by 06:00\n  first bullet: Goal: The nightly run finishes by 06:00" in text
      and "board#2 · unclear · board#2: names a symptom\n  subject: [home] Retry bug in the sync\n  first bullet: The sync retries forever" in text
      and "board#3 · unclear · board#3: names a symptom" in text, text)
check("a failed call is 'not judged', and the counts say so", "board#5 · not judged\n" in text and text.splitlines()[-1].startswith("counts: 2 unclear · 1 clear · 1 not judged") and res["counts"] == {"open": 4, "judged": 3, "unclear": 2, "clear": 1, "not_judged": 1}, (text[-300:], res["counts"]))
check("…and the header says report only", text.startswith("goal pass: 4 open item(s), one call each (4 made, 1 failed) · report only: nothing filed, no message sent"), text[:200])
check("the closed item is nowhere in the report", "board#4" not in text, None)

# ---- 3. the file, the stdout copy, --max-calls
asked.clear(); out_file = T / "report" / "mine.txt"
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = GP.main(["--out", str(out_file), "--max-calls", "2"], env=env(), items=dict(ITEMS))
check("--out writes the report to that file, and stdout carries the same text plus the path line", rc == 0 and out_file.read_text(encoding="utf-8").rstrip("\n") in buf.getvalue() and f"report written to {out_file}" in buf.getvalue(), buf.getvalue()[-200:])
check("--max-calls 2 judges the first two open items only", len(asked) == 2 and "board#3" not in out_file.read_text(encoding="utf-8") and "board#2" in out_file.read_text(encoding="utf-8"), len(asked))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = GP.main(["--store", str(STORE)], env=env())          # reads the store's items; the file goes to <state>/audit/goal-pass-<stamp>.txt
files = audit_files()
check("without --out: <state>/audit/goal-pass-<stamp>.txt, read from the store", rc == 0 and len(files) == 1 and re.fullmatch(r"goal-pass-\d{4}-\d{2}-\d{2}-\d{6}\.txt", files[0]) and "board#3 · unclear" in (AUD / files[0]).read_text(encoding="utf-8"), (files, buf.getvalue()[-200:]))

# ---- 4. report only
check("the store is byte for byte as it was", tree_hash() == before, None)
check("no message was sent by any route", sent == [], sent)
check("no audit record was written or touched (only the report file is in the audit folder)", not list(AUD.glob("run-*.json")) and not list(AUD.glob("filing*")) and not list(AUD.glob("dates*")), audit_files())

print(("ok" if not fails else "FAILED") + f": goal_pass scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
