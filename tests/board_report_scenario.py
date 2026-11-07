"""Scenario test for the audit's board checks (tools/board_report.py, audit.py board-check) — fixture data, no live store, no network, no server socket.

The two kinds, each on the item that has it and on none other (an item on an agent that has gone quiet is no board check any more: it is the silence pass's, tests/silence_scenario.py): arbitrary-hold (a hold with no after, check, party, anchor or words of Oliver's and with words that name no
event; not one an open after item, needs external, Oliver's recorded words or an event in the wait basis holds) and mislabeled-state (stored state against the derived one, a your-call with no ask, an outside item with
no external in needs, a hold whose words wait on Oliver's decision or on an outside party; not a clean parked item). The tool changes no file (a digest of the store before and after), `--line`, `--json` and the listing agree, and
`audit.py board-check` runs the same report.

    tests/run-suite board_report        → exit 0 / 1"""
import hashlib, json, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="brtest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
(T / "store/a").mkdir(parents=True); (T / "store2/a").mkdir(parents=True)

import board_report as BR
now = time.time(); OWNER = "00000000-0000-4000-8000-000000000001"; H = 3600
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M", time.gmtime(ts))
at = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))
WAKE = iso(now + 3 * 86400)
def item(i, status="open", updated=None, wrote=None, by="home-agent", store="store", **meta):
    base = {"owner": OWNER, "project": "projects/alpha"}
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H if updated is None else updated,
         "state_updated": now - H, "confirmed": now - H, "metadata": {**base, **meta}}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = by
    (T / f"{store}/a/{i}.json").write_text(json.dumps(d))
def doing(i, ago, **kw):                 # a doing item on a session, its expected_by a day out
    item(i, state="doing", needs=["home-agent"], next="home-agent: build it", expected_by=at(now + 30 * H), expected_reason="the build runs overnight", wrote=now - ago * H, updated=now - ago * H, **kw)

doing(1, 8)                                                                                                                       # quiet 8 hours (no board finding; the silence pass's), a far expected_by does not excuse it
doing(2, 1)                                                                                                                       # clean: written an hour ago
item(3, state="doing", needs=["home-agent"], next="home-agent: build it", expected_by=at(now + 30 * H), expected_reason="the build runs overnight", wrote=now - H, by="migration", updated=now - 9 * H)         # quiet: the migration's stamp is no session write
item(4, state="doing", needs=["home-agent"], next="home-agent: build it", expected_by=at(now + 30 * H), expected_reason="the build runs overnight", wrote=now - 9 * H, by="home-agent", updated=now - H)         # quiet: a server save moved `updated`, but the session stamp says 9 hours and that is what counts
item(5, state="verifying", needs=["home-agent"], next="home-agent: check the result", wrote=now - 20 * H, updated=now - 20 * H)           # clean: verifying is a wait, not work
item(6, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: check the phase", wrote=now - 20 * H, updated=now - 20 * H,
     wait_basis={"text": "the second phase ends after 2099-11-17", "wake": WAKE, "by": "home-agent", "at": now - 20 * H})              # clean: held, an event in its basis
item(7, state="your-call", needs=["decision"], ask="Pick A or B?", mover="Oliver", next="Oliver: pick A or B", wrote=now - 20 * H, updated=now - 20 * H)       # clean: Oliver's, not an agent's
item(8, state="doing", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: check the phase", wrote=now - H, updated=now - H,
     wait_basis={"text": "the second phase ends after 2099-11-17", "wake": WAKE, "by": "home-agent", "at": now - H})                    # mislabeled: doing while held
item(9, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: pick A or B", wrote=now - H, updated=now - H)             # mislabeled: your-call with no ask
item(10, state="outside", needs=["home-agent"], next="home-agent: build it", wrote=now - H, updated=now - H)                              # mislabeled: outside with no external in needs
item(9012, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: put it to him", wrote=now - H, updated=now - H,
     wait_basis={"text": "Oliver's decision on the vendor comes after 2026-11-20", "wake": WAKE, "by": "home-agent", "at": now - H})          # mislabeled: a hold whose words wait on Oliver's decision
item(9020, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look at the answer", wrote=now - H, updated=now - H,
     wait_basis={"text": "waiting for a reply from the vendor, expected after 2026-11-20", "wake": WAKE, "by": "home-agent", "at": now - H})  # mislabeled: a hold whose words wait on an outside party
item(13, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look at it later", wrote=now - H, updated=now - H)     # arbitrary: no event, no reason
item(14, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: on Mon Nov 2nd check back", wrote=now - H, updated=now - H)     # arbitrary: only a date
item(15, state="blocked", hold=True, needs=["home-agent"], after=["a9019"], next="home-agent: carry on", wrote=now - H, updated=now - H)     # clean: an open after item holds it
item(16, state="outside", hold=True, needs=["external"], party="Acme", chase=at(now + 2 * 86400)[:10], wake=WAKE, next="home-agent: look at the answer", wrote=now - H, updated=now - H)     # clean: needs external, a party named
item(17, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look again", wrote=now - H, updated=now - H,
     cap_ok={"wake": WAKE, "by": "Oliver", "quote": "park it until Monday"})                                                           # clean: his recorded words
item(18, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: wait for board#9019 to land", wrote=now - H, updated=now - H)         # clean: the words name an item
item(9019, state="doing", needs=["home-agent"], next="home-agent: build it", expected_by=at(now + 3 * H), expected_reason="the build runs", wrote=now - H, updated=now - H)         # the open item item 15 waits after (clean)
item(21, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look again", wrote=now - H, updated=now - H)               # clean: only the anchor scoped to it holds it (anchors.json below)
item(22, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look again", wait_kind="relay", wrote=now - H, updated=now - H)   # clean: a stored wait kind holds it
item(23, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look again", check="read the log", wrote=now - H, updated=now - H)  # clean: a check holds it
item(24, state="outside", hold=True, needs=["external"], party="Acme", chase=at(now + 2 * 86400)[:10], wake=WAKE, next="home-agent: waiting for the vendor reply", wrote=now - H, updated=now - H)   # clean: labeled outside, the vendor words are not second-guessed
item(25, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: waiting for the vendor reply", wrote=now - H, updated=now - H,
     cap_ok={"wake": WAKE, "by": "Oliver", "quote": "park it until Monday"})                                                           # clean: on his recorded words, the vendor words are not second-guessed
item(26, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: look again after the weekend", wrote=now - H, updated=now - H)     # arbitrary: "the weekend" is no event
item(27, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: continue when ready", wrote=now - H, updated=now - H)             # arbitrary: "ready" is no event
item(28, state="doing", needs=["home-agent"], after=["a9019"], next="home-agent: build it", expected_by=at(now + 30 * H), expected_reason="the build runs overnight", wrote=now - 10 * H, updated=now - 10 * H)   # mislabeled only: it reads as blocked, so it is not also idle
item(29, state="doing", next="home-agent: build it", expected_by=at(now + 30 * H), expected_reason="the build runs overnight", wrote=now - 10 * H, updated=now - 10 * H, store="store2")   # store2: no session in needs, the project's fallback mover moves it
item(30, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: read the counts", wrote=now - H, updated=now - H,
     wait_basis={"text": f"log collection ends {WAKE[:10]}", "wake": WAKE, "by": "home-agent", "at": now - H})                           # clean: a window park in the documented form
item(31, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: read the counts", wrote=now - H, updated=now - H,
     wait_basis={"text": f"trial week {WAKE[:10]}", "wake": WAKE, "by": "home-agent", "at": now - H})                                    # clean: a basis with only a real date and no event word: the date is its reason
item(32, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: read the counts", wrote=now - H, updated=now - H,
     wait_basis={"text": f"trial week 2026-02-30", "wake": WAKE, "by": "home-agent", "at": now - H})                                     # arbitrary: 2026-02-30 is no calendar date
item(33, state="parked", hold=True, needs=["home-agent"], wake=WAKE, next="home-agent: read the counts", wrote=now - H, updated=now - H,
     wait_basis={"text": f"log collection ends {WAKE[:10]}", "wake": iso(now + 9 * 86400), "by": "home-agent", "at": now - H})        # arbitrary: the basis was written for another wake and is read without it
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://github.com/x/y/pull/1", "items": ["a21"], "added": now - H}]}))
item(9011, status="completed", state="doing", needs=["home-agent"], next="", wrote=now - 40 * H, updated=now - 40 * H, outcome="done")   # closed: left alone

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def digest(): return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((T / "store").glob("*/*.json"))}
d0 = digest()

import next_report as NR
rep = BR.scan(NR.load_all(T / "store"), BR.load_anchors(T / "store"), now)
by = {}
for f in rep["findings"]: by.setdefault(f["id"], []).append(f["kind"])
kind = lambda i: sorted(set(by.get(f"board#{i}", [])))
check("no idle-on-agent kind: items 8, 8 and 9 hours old on a session are no board finding", kind(1) == [] and kind(3) == [] and kind(4) == [] and "idle-on-agent" not in BR.KINDS and not hasattr(BR, "IDLE_HOURS"), by)
check("clean: written an hour ago, verifying, held, on Oliver", kind(2) == [] and kind(5) == [] and kind(6) == [] and kind(7) == [], by)
check("mislabeled-state: doing while held, your-call with no ask, outside with no external in needs", kind(8) == ["mislabeled-state"] and kind(9) == ["mislabeled-state"] and kind(10) == ["mislabeled-state"], by)
check("the doing-while-held finding says it is on hold", any(f["id"] == "board#8" and "on hold" in f["detail"] for f in rep["findings"]), rep["findings"])
check("mislabeled-state: a hold whose words wait on Oliver's decision, and on an outside party", kind(9012) == ["mislabeled-state"] and kind(9020) == ["mislabeled-state"]
      and any(f["id"] == "board#9012" and "your-call" in f["detail"] for f in rep["findings"]) and any(f["id"] == "board#9020" and "outside" in f["detail"] for f in rep["findings"]), rep["findings"])
check("arbitrary-hold: a hold whose words name no event, and one that names only a date", kind(13) == ["arbitrary-hold"] and kind(14) == ["arbitrary-hold"], by)
check("a hold that something holds is no finding: an open after item, needs external with a party, Oliver's recorded words, an item in the words",
      kind(15) == [] and kind(16) == [] and kind(17) == [] and kind(18) == [], by)
check("names_event: an item, a PR and a thing that ends are events; a date and vague words are not",
      BR.names_event("wait for board#9019") and BR.names_event("after PR 19 is live") and BR.names_event("the second phase ends 2099-11-17")
      and not BR.names_event("check back on Mon Nov 2nd") and not BR.names_event("look at it later") and not BR.names_event("parked, nothing holds it now"), None)
check("a hold that only an anchor scoped to it, a wait kind or a check holds is no finding", kind(21) == [] and kind(22) == [] and kind(23) == [], by)
check("an outside hold and one on his recorded words are not second-guessed from a 'waiting for the vendor reply' text", kind(24) == [] and kind(25) == [], by)
check("arbitrary-hold: 'after the weekend' and 'when ready' name no event", kind(26) == ["arbitrary-hold"] and kind(27) == ["arbitrary-hold"], by)
check("a window park in the documented form (wait_basis 'log collection ends <the wake day>') is no arbitrary-hold finding, nor is a basis with a real date and no event word ('trial week <the wake day>')", kind(30) == [] and kind(31) == [], by)
check("…but a basis whose date is not on the calendar, and one written for another wake (read as no basis), are still arbitrary", kind(32) == ["arbitrary-hold"] and kind(33) == ["arbitrary-hold"], by)
check("names_event: the taught form 'log collection ends <date>' names its event by the word ends", BR.names_event(f"log collection ends {WAKE[:10]}") and BR.names_event("trial week ends 2026-11-02"), None)
check("dated_basis: a real date in the basis for the current wake counts; a fake date, no date or another wake's basis does not",
      BR.dated_basis({"wake": WAKE, "wait_basis": {"text": "trial week 2026-11-02", "wake": WAKE}}) and not BR.dated_basis({"wake": WAKE, "wait_basis": {"text": "trial week 2026-02-30", "wake": WAKE}})
      and not BR.dated_basis({"wake": WAKE, "wait_basis": {"text": "trial week soon", "wake": WAKE}}) and not BR.dated_basis({"wake": WAKE, "wait_basis": {"text": "trial week 2026-11-02", "wake": "2030-01-01"}}) and not BR.dated_basis({}), None)
check("names_event: Monitor, Satisfied and Friends are no weekday or month, Friday is", BR.names_event("until Monitor") and BR.names_event("after Satisfied") and BR.names_event("when Friends reply")
      and not BR.names_event("until Friday") and not BR.names_event("after the weekend") and not BR.names_event("when ready"), None)
check("a stored doing item that reads as blocked is a mislabeled-state finding only, not also idle", kind(28) == ["mislabeled-state"], by)
BR._wt.FALLBACK_MOVER = lambda project: "home-fallback" if project == "projects/alpha" else ""
rep2 = BR.scan(NR.load_all(T / "store2"), {}, now)
check("an item with no mover of its own gets the project's fallback mover, and no board finding (its silence is the silence pass's)", rep2["findings"] == [] and BR.mover_of(NR.load_all(T / "store2")["a29"]) == "home-fallback", rep2["findings"])
BR._wt.FALLBACK_MOVER = None
check("fallback_mover reads the registry and never raises: '' where the project names no agent", BR.fallback_mover("projects/alpha") == "", BR.fallback_mover("projects/alpha"))
check("a closed item is left as it is", "board#9011" not in by, by)
check("a clean item and the open after item name no finding", kind(2) == [] and kind(9019) == [], by)
check("the counts: 31 open, 1 closed, 12 items with a finding, per kind 6 arbitrary, 6 mislabeled", rep["open"] == 31 and rep["closed"] == 1 and rep["items"] == 12
      and rep["kinds"] == {"arbitrary-hold": 6, "mislabeled-state": 6}, (rep["open"], rep["closed"], rep["items"], rep["kinds"]))
check("a finding carries id, project, mover, category and kind, and names a session as mover", all(set(f) >= {"id", "project", "mover", "category", "kind", "detail"} and f["category"] == "board checks"
      and f["project"] == "projects/alpha" for f in rep["findings"]), rep["findings"][:2])
check("the owner's names match whole and in their own case: a host called ae-box or a role ae-ops is not AE, a Japanese particle after オリバー still counts",
      BR._owner_rx().search("AE decides") and BR._owner_rx().search("オリバーの答えを待つ") and BR._owner_rx().search("Oliver's call")
      and not BR._owner_rx().search("ae-box is down") and not BR._owner_rx().search("ae-ops pick the lane") and not BR._owner_rx().search("shop pick"), None)
check("the decision words hold for every alias: Oliver, AE and オリバー deciding, and a decision waiting on any of them",
      all(BR._decision_rx().search(t) for t in ("Oliver decided the lane", "AE will approve it", "オリバーが決定 decision", "waiting on AE", "waiting for Oliver", "the answer from オリバー"))
      and not BR._decision_rx().search("ae-ops pick the lane") and not BR._decision_rx().search("ae-box is down"), None)
check("the check changes no file", digest() == d0, None)

def run(*a):
    r = subprocess.run([sys.executable, *a], capture_output=True, text=True, env=dict(os.environ)); return r.returncode, r.stdout, r.stderr
rc, out, err = run(os.path.join(STACK, "tools", "board_report.py"), "--store", str(T / "store"))
check("the listing: one line per finding, then the counts line; exit 0", rc == 0 and len(re.findall(r" \| (?:arbitrary-hold|mislabeled-state) \| ", out)) == len(rep["findings"]) and "Board checks: 12 item(s)" in out, (rc, out[-400:], err[-300:]))
rc, out, _ = run(os.path.join(STACK, "tools", "board_report.py"), "--store", str(T / "store"), "--line")
check("--line gives the one line with the counts per kind", rc == 0 and out.strip() == "Board checks: 12 item(s) · arbitrary-hold 6 · mislabeled-state 6", out)
rc, out, _ = run(os.path.join(STACK, "audit.py"), "board-check", "--json", "--store", str(T / "store"))
js = json.loads(out) if rc == 0 else {}
check("audit.py board-check --json runs the same report", js.get("kinds") == rep["kinds"] and [f["id"] for f in js.get("findings", [])] == [f["id"] for f in rep["findings"]], (rc, out[:300]))
rc, _, err = run(os.path.join(STACK, "tools", "board_report.py"), "--store", str(T / "no-such"))
check("a --store that is no folder: exit 2", rc == 2, (rc, err))
rc, _, err = run(os.path.join(STACK, "audit.py"), "bogus")
check("audit.py's usage names board-check", rc == 2 and "board-check" in err, (rc, err))

check("nothing was written by any of it", digest() == d0, None)

print(("ok" if not fails else "FAILED") + f": board_report scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
