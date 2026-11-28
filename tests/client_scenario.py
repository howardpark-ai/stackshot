"""Scenario tests for the client API and the keys of its callers, in two parts that each run in a process of their own (formerly the suites client and caller_keys): the client API's token, reads and refusals, and a caller trusted by a key of its own.

Part `client` - the client API, step (a) of the client contract (board batch 5) — fixture data, no live store, no network.

Covers: minting a machine token (the server keeps its hash, the token lands in a 0600 file and nowhere else); who the server
takes a token for; the reads (registry, rules, brief, page-ts, and items for the board check of), whoami and config; refusals; the same over HTTP in-process; a held poll that the server's shutdown cancels answers 200 with no deliveries (the item follow-up); the puller's CLI version probe starts no window on Windows; owner_name follows an owner change.

Part `caller_keys` - a caller trusted by a key of its own (fleet/caller_keys.py, service/caller_pass.py, the /keys routes and the pass gate of the form's calls in web/routes/client_api.py,
service/projects.py `_form_call`) — fixture data, the HTTP routes through Starlette's test client, a clock the suite sets, no live store, no network. Keys are generated here; every name is made up.

Covers:
  * the key files: the key's form (43 base64url characters, canonical), the fingerprint (sha256 of the 32 bytes, 64 hex, 16 shown), label and sender text (no markup, no mention), `sender_covers`;
  * enroll (`POST /keys/enroll`): no token needed; the key is kept pending (0600, in `keys-pending.json`) and trusted for nothing; the same key again changes nothing; a bad key, label, sender, body or
    a body over 8 KB is refused; at most 5 keys wait (a sixth is 429, an approved or waiting key is not counted again); 10 enrolls in 10 minutes from one address (429 with Retry-After); a pending key
    expires after 7 days; a standby copy answers 503;
  * the board item: one open decision item per pending key, marked `caller_key`, asking Approve or Reject with the fingerprint's first 16 characters; none when `[caller_keys] item_project` is empty;
    the owner's answer Approve approves the key and closes the item, Reject deletes the key and closes it, a key approved or revoked on the command line closes it too;
  * approving and revoking: `client keys list|approve|revoke` (a fingerprint typed under 8 characters, or naming no key, is refused), the entry moves to `keys.json` (0600), revoking an approved key
    deletes it and ends its passes;
  * the claim (`POST /keys/pass`): a good one trades for a pass (10 minutes, in memory, tied to the key's fingerprint and sender); a wrong signature, another key's signature, a wrong aud, an expired claim, a life over 60
    seconds (60 is fine), a clock more than 60 seconds off, a reused jti, a header that is not EdDSA, a missing or short jti and a key that is pending or unknown are each refused (400, 401 or 403); 429 over 60 a minute that prove nothing;
  * the limits (section 10): a claim whose signature verifies is never refused for other callers' junk (70 junk claims, or 70 signed by another key naming the approved one, or 700 from 700 addresses, then
    the valid claim: 200), it is limited per key (30 a minute); everything else per source address (the connection's, never a header; an IPv6 /64 is one) under a ceiling one address cannot use up;
    an enroll the same (60 junk, then a valid enroll from another address; 1000 junk take 10 of the ceiling); 5 keys wait at most and 3 from one address, and the owner can always free a place (`keys approve`,
    `keys revoke`, Reject on the item); the files keep a hash of the source, never an address;
  * what a request makes the server read (section 11): a claim naming a pending key with a wrong signature, a claim of an unknown key, a repeated enroll and a junk enroll scan the store 0 times; the key's
    own verified claim takes the owner's Approve in by the item's id; 10 enrolls inside a minute make one scan;
  * the lows (section 12): a pass whose sender is not the key's (a session id included) is 403 on project-agent; the approval prompt's Stakes say whole form and every `x-…` label, inside 240 characters even for
    an 80-character sender; an iat or exp that is a huge integer, infinite, not a number or past a trillion seconds is 401; a body or a claim part nested too deep for the parser is 400;
  * the pass and the gate: a pass opens the form's calls (For you list, the color tool, rename) when the call's sender is the key's label or starts with it and a `-`, and nothing else of /client; it stops
    after 10 minutes, after a revoke and after a restart (the table is memory); with no pass the old host lists decide exactly as before, with a pass or with the lists the form is let in.

  * the review's findings (section 13): a replayed, expired or reused signed claim counts for its source address and never for its key; an answer on the item of an earlier enroll of a key is no answer to
    a new enroll of it; a weak public key (the identity, a point of small order, a non-canonical one) is refused at enroll; a damaged key file is never written over (the command line and the server
    refuse); approving uses the whole fingerprint and an approve that fails leaves the item open; an IPv4-mapped IPv6 address counts as its IPv4 address; the source tag is keyed by a secret of the server's;
    the ceiling over all enrolls (300 in 10 minutes) ends in 429;
  * the third review's lows (section 14): no `.` in a label or a sender (a domain the board would draw as a link is refused at enroll, a legitimate sender still passes) and both are in code spans on the
    item; a claim whose signature is not the named key's is answered alike (403 unknown, the same body) for an approved, a pending and an unknown fingerprint, and only a verified signature of a waiting key
    is told `pending`; an enroll of an approved key answers `approved` with no item; `keys.lock` is 0600 whatever the umask, also when an earlier version made it 0644; a pending entry whose `enrolled_at`
    is no number is dropped, never a 500; a stale or wrong-board claim counts for its source address; a used claim stays refused for its whole life; a non-canonical encoding of a valid point is refused.

The two parts set up two different instances (a base config with a fleet of sessions and a store; one with a board address, the owner changed, and the form's host token), and the code under test reads its config and keeps module state at import: so each part runs in a process of its own (this file started again with `--part <name>`), exactly as the two suites did, and the parent adds their check counts.

    tests/run-suite client        -> exit 0 / 1"""
import contextlib as _cl, os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("client", "caller_keys")


# ================================================================ part client: the client API, step (a) of the client contract
def part_client():
    import hashlib, json, os, re, socket, stat, sys, pathlib, tempfile, logging, time
    import _scratch, _instance
    sys.path.insert(0, STACK)
    tmp = _scratch.mkdtemp(prefix="clienttest-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1   # the fixtures' subjects
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)   # the session and machine state is a fixture under fleet/
    for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
    (T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
    (T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] item 1", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": "sparrow", "project": "projects/alpha"}}))
    (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))

    # ---- 1. minting
    from stackshot.fleet import client
    _real_urlopen = client.urllib.request.urlopen   # a later block patches it with an in-process app; the pass checks below talk to a real stub server
    path = client.mint("box-far"); tok = open(path).read().strip()
    d = json.loads((T / "secrets/clients.json").read_text())
    check("the server keeps the token's hash, not the token", d["box-far"]["sha256"] == hashlib.sha256(tok.encode()).hexdigest() and tok not in (T / "secrets/clients.json").read_text(), d)
    check("the token file is private", stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(T / "secrets/clients.json").st_mode) == 0o600, oct(os.stat(path).st_mode))
    check("a remote machine's token is not installed here", not (T / "secrets/client.token").exists())
    me = socket.gethostname(); mine = open(client.mint(me)).read().strip()
    check("the server box's own token is installed with the local address", (T / "secrets/client.token").read_text().strip() == mine and (T / "secrets/client.url").read_text().startswith("http://127.0.0.1:"), (T / "secrets/client.url").read_text())
    try: client.mint("bad name/../x"); check("a machine name with a path in it is refused", False)
    except ValueError: check("a machine name with a path in it is refused", True)
    old = tok; tok = open(client.mint("box-far")).read().strip(); check("minting again replaces the token", tok != old)

    # ---- 2. whom the server takes a token for
    from stackshot.web import server
    from stackshot.web.tools import notes as _notes_tool
    from stackshot.service import client_reads as client_reads_svc
    from stackshot.service import messaging as _messaging
    from stackshot.model import holders as _holders
    from stackshot.service import item_read as _item_read
    from stackshot.service import update as _update_svc
    from stackshot.web import render as _rmod
    from stackshot.service import store as _service_store
    from stackshot.core import instance as _core_instance
    import datetime as dt
    from stackshot.web import home as _home
    from fastmcp.exceptions import ToolError
    from stackshot.web import publish as _web_publish
    from stackshot.service import wakes as wakes_svc
    from stackshot.web.tools import anchors as _wt_anchors
    from stackshot.web.tools import route as _wt_route
    from stackshot.web.tools import brief as _wt_brief
    from stackshot.web.tools import complete as _wt_complete
    from stackshot.web.tools import get as _wt_get
    from stackshot.web.tools import update as _wt_update
    from stackshot.web.routes import client_api as _rt_client
    from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
    hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
    wk_ = lambda m: _WT.wake_value(m)
    ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
    from stackshot.core import store as _core_store
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    check("a valid token names its machine", _rt_client._client_machine("Bearer " + tok) == "box-far" and _rt_client._client_machine("bearer " + mine) == me)
    check("a replaced token is dead", _rt_client._client_machine("Bearer " + old) == "")
    for bad in ("", "Bearer ", "Bearer short", "Basic " + tok, tok, "Bearer " + tok + "x"):
        check(f"refused: {bad[:14]!r}", _rt_client._client_machine(bad) == "", bad[:20])
    client.revoke("box-far"); check("a revoked machine is refused", _rt_client._client_machine("Bearer " + tok) == "" and not os.path.exists(path))
    tok = open(client.mint("box-far")).read().strip()

    # ---- 3. the reads
    st, ct, body = client_reads_svc._client_get("registry", {}); check("registry: the page registry as stored", st == 200 and "projects/alpha" in json.loads(body)["pages"], body[:120])
    st, ct, body = client_reads_svc._client_get("brief", {}); check("brief: what a session start prints", st == 200 and body.startswith("Board: 1 open"), body[:120])
    st, ct, body = client_reads_svc._client_get("rules", {}); check("rules: the rulebook", st == 200 and len(body) > 500 and ct.startswith("text/markdown"), (st, len(body)))
    st, ct, body = client_reads_svc._client_get("page-ts", {"key": "projects/alpha"}); check("page-ts: a page's last change", st == 200 and json.loads(body)["ts"] and json.loads(body)["key"] == "projects/alpha", body)
    st, ct, body = client_reads_svc._client_get("page-ts", {"key": "projects/alpha.md"}); check("page-ts: a trailing .md is fine", st == 200 and json.loads(body)["key"] == "projects/alpha", body)
    st, ct, body = client_reads_svc._client_get("page-ts", {"key": "projects/none"}); check("page-ts: a page that does not exist has no time", st == 200 and json.loads(body)["ts"] is None, body)
    # 2026-10-16: page-ts for a page that is not in the mirror used to ask the server's own client API from inside the server (pages._api →
    # client.get over the loopback): the event loop could not answer that request until its 6 s timeout ran out, so every request waited.
    # The server never makes that call; a spy on client.get stands in for the loopback (the real one stalls the loop until its timeout).
    from stackshot.projects import pages as _pg_self
    _calls = []; _real_get = client.get; client.get = lambda *a, **k: (_calls.append(a), (0, ""))[1]
    _unreach = len(_pg_self.UNREACHABLE)
    try:
        st, ct, body = client_reads_svc._client_get("page-ts", {"key": "projects/none"})
        check("page-ts for a missing page makes no call to the server itself", _calls == [] and len(_pg_self.UNREACHABLE) == _unreach and _pg_self.LOCAL_ONLY, (_calls, _pg_self.LOCAL_ONLY))
        check("pages._api answers nothing in the server process", _pg_self._api("page-ts", "projects/none") is None and _calls == [], _calls)
    finally: client.get = _real_get
    for bad in ("", "../etc/passwd", "projects/../../x", "inbox/thing"):
        st, ct, body = client_reads_svc._client_get("page-ts", {"key": bad}); check(f"page-ts refuses {bad!r}", st == 400, (st, body))
    st, ct, body = client_reads_svc._client_get("secrets", {}); check("an unknown read is 404", st == 404, (st, body))

    # ---- 3b. the hold record, the unexplained-holds report and the new holds in the briefings (the part that shipped):
    # hold=true behaves as before (no gate); a hold records who set it and when; the report lists a hold when nothing holds it NOW, whatever was stored as its reason;
    # the holds set in the last 24 hours go to board.md's head, the brief tool and the session-start brief; a malformed record never breaks any of them
    import time as _t
    def mk(i, **meta):
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] hold fixture {i}", "description": "A thing. It lives here. Done when done.", "status": meta.pop("status", "open"),
                                                           "updated": _t.time() - 60, "state_updated": _t.time() - 60, "confirmed": _t.time() - 60,
                                                           "metadata": {"owner": "sparrow", "project": "projects/alpha", "next": "do the thing", **meta}}))
    def rdm(i): return json.loads((T / f"store/a/{i}.json").read_text())["metadata"]
    def upd(i, **kw):
        try: return _wt_update.stackshot_update(item_id=f"a{i}", sender="sparrow", **kw), ""
        except ToolError as e: return "", str(e)
    def D(n): return (_pg_self.zone_now() + dt.timedelta(days=n)).strftime("%Y-%m-%d")      # a date n days from today: the fixtures hold no calendar date, so the suite reads the same on any day
    WK = (_pg_self.zone_now() + dt.timedelta(days=5)).strftime("%Y-%m-%d")
    BAS = "visit on " + (_pg_self.zone_now() + dt.timedelta(days=9)).strftime("%Y-%m-%d")      # a time wait carries a reason
    for i in range(2, 12): mk(i)
    mk(20)                                                             # an item that others wait on
    res, err = upd(2, hold=True, recycle=True)
    check("hold=true behaves as before: a session's hold for a pane recycle is accepted", not err and _holders._is_held(_service_store._load("a2")), (err, rdm(2)))
    hs = rdm(2).get("hold_set") or {}
    check("…and records who set it and when, nothing more (the reason is the wait_basis, not in the hold record)", set(hs) == {"at", "by"} and hs["by"] == "sparrow" and abs(hs["at"] - _t.time()) < 60, hs)
    check("get shows who set the hold and when", "parked: set by sparrow " in _wt_get.stackshot_get("a2"), _wt_get.stackshot_get("a2"))
    upd(2, clear_hold=True)
    check("clear_hold releases it and drops the record", not _holders._is_held(_service_store._load("a2")) and "hold_set" not in rdm(2), rdm(2))
    res, err = upd(3, hold=True)
    check("a hold with no wake and nothing holding it is accepted, with the server's backstop day stored as until and marked, the hold flag gone", not err and "hold" not in rdm(3) and rdm(3).get("until") == D(14) and rdm(3).get("until_server") == D(14), (res, err, rdm(3)))
    check("the update tool's text no longer invites a session to park its own item: no \"without asking\", no \"park it to the date\", no \"nearest date to check\"",
          not any(x in _wt_update._UPDATE_DESC for x in ("without asking", "park it to the date", "an owner parks its own item", "nearest date to check")) and "A session does not park to defer work it could do now" in _wt_update._UPDATE_DESC,
          _wt_update._UPDATE_DESC[:200])
    # the server's own holds are untouched: the board button records the board as the setter
    mk(12)
    _update_svc._update("a12", hold=True, recycle=True, sender="sparrow")
    check("the core write (what the server's own paths use) holds as before", _holders._is_held(_service_store._load("a12")), rdm(12))

    # the report: read only, a hold nothing holds now
    _sa = _item_read._scoped_anchors; _item_read._scoped_anchors = lambda proj, gid: [{"url": "https://github.com/example-owner/stackshot/pull/9", "items": [gid]}] if gid == "a10" else _sa(proj, gid)
    mk(13, hold=True, wake=D(1))                                              # stored before the record, nothing holds it: listed
    mk(14, hold=True, wake=D(2), hold_set={"at": _t.time() - 7200, "by": "sparrow"})                    # recorded, nothing holds it: listed
    mk(15, hold=True, wake=D(3), hold_set={"at": _t.time() - 7200, "by": "sparrow", "why": ["said"]})   # a stored reason is never trusted: listed
    mk(16, hold=True, wake=D(4), after=["a20"])                               # an open after holds it
    mk(17, hold=True, wake=D(5), recycle=True)                                # a recycle holds it
    mk(18, hold=True, wake=D(6), needs=["external"])                          # an outside party holds it
    mk(10, hold=True, wake=D(7))                                              # an anchor scoped to it holds it (patched above)
    mk(19, status="completed", hold=True)                                             # closed: never listed
    mk(21, hold=True, wake=D(8), hold_set={"at": "garbage", "by": "sparrow"}); mk(22, hold=True, wake=D(9), hold_set="oops")   # malformed records
    before = {f.name: f.read_text() for f in (T / "store/a").glob("*.json")}
    try: rows = _notes_tool._holds_unexplained(); rep = _notes_tool._holds_report()
    finally: _item_read._scoped_anchors = _sa
    gids = [r["gid"] for r in rows]
    check("the report lists a hold nothing holds now (stored before the record, recorded, or with a stored reason), and none that an after, a recycle, needs external or an anchor holds",
          {"a13", "a14", "a15"} <= set(gids) and not {"a16", "a17", "a18", "a10", "a19", "a1", "a2"} & set(gids), gids)
    check("a malformed record (a value that is no number, a record that is no object) breaks nothing and reads as no record", {"a21", "a22"} <= set(gids)
          and all(r["at"] == 0 for r in rows if r["gid"] in ("a21", "a22", "a13")) and next(r for r in rows if r["gid"] == "a22")["by"] == "", [r for r in rows if r["gid"] in ("a21", "a22")])
    row = next(r for r in rows if r["gid"] == "a14"); old = next(r for r in rows if r["gid"] == "a13")
    check("each row has the owner, the wake, who set it and when; a hold from before the record says so", row["owner"] and wk_(row) == D(2) and row["by"] == "sparrow" and row["at"] > 0
          and old["by"] == "" and old["at"] == 0 and wk_(old) == D(1), (row, old))
    check("the printed report: one line per item with mover, wake, setter and time", "a14 · mover sparrow · wake " + D(2) + " · set by sparrow (" in rep and "a13 · mover sparrow · wake " + D(1) + " · set by unknown (before the record)" in rep
          and "a16 ·" not in rep and "update clear_hold=true" in rep and " open item(s) parked that nothing holds now (no open after, pane recycle, needs external or item-scoped anchor); " in rep and "on hold" not in rep, rep)
    check("the report writes nothing: every item file is as it was", before == {f.name: f.read_text() for f in (T / "store/a").glob("*.json")})
    st, ct, body = client_reads_svc._client_get("holds", {}); check("the client API serves it as holds", st == 200 and "a14 · mover sparrow · wake " + D(2) + "" in body and "a16 ·" not in body and ct.startswith("text/plain"), (st, body[:120]))
    _cg = client.get; client.get = lambda what, *a, **k: (200, client_reads_svc._client_get(what, {})[2]); _o = sys.stdout; sys.stdout = __import__("io").StringIO()
    try: rc = client.main(["client.py", "holds"]); printed = sys.stdout.getvalue()
    finally: sys.stdout = _o; client.get = _cg
    check("client.py holds prints the report and exits 0", rc == 0 and "a14 · mover sparrow" in printed and printed.endswith("\n"), (rc, printed[:200]))
    client.get = lambda what, *a, **k: (401, "no token"); _o = sys.stdout; sys.stdout = __import__("io").StringIO()
    try: rc = client.main(["client.py", "holds"])
    finally: sys.stdout = _o; client.get = _cg
    check("client.py holds exits 1 when the server is not reached", rc == 1)

    # client.py get agent-name <project> <name>...: the server's JSON on stdout and exit 0 whenever the call answers (every name invalid included), 1 for a call that failed or was misused
    _asked = []
    def _fake_get(code, text):
        def g(what, *a, **k): _asked.append((what, k)); return code, text
        return g
    def _agent_name_cli(argv, code=200, text='{"results": []}'):
        real = client.get; client.get = _fake_get(code, text); _o, _e = sys.stdout, sys.stderr; sys.stdout = __import__("io").StringIO(); sys.stderr = __import__("io").StringIO()
        try: rc = client.main(["client.py", "get", "agent-name", *argv]); return rc, sys.stdout.getvalue(), sys.stderr.getvalue()
        finally: sys.stdout, sys.stderr = _o, _e; client.get = real
    all_bad = json.dumps({"project": "prj_e1", "key": "projects/alpha", "results": [{"name": "x", "valid": False, "code": "prefix", "reason": "r"}], "first_free": None, "prefixes": ["a"]})
    rc, out_, err_ = _agent_name_cli(["projects/alpha", "a-one", "a-two"], 200, all_bad)
    check("client.py get agent-name: asks the read with the project as key and the names comma separated, prints the JSON, exits 0 (even with every name invalid)",
          rc == 0 and json.loads(out_)["first_free"] is None and (_asked[-1][0], {k: v for k, v in _asked[-1][1].items() if k != "timeout"}) == ("agent-name", {"key": "projects/alpha", "names": "a-one,a-two"}) and err_ == "", (rc, out_, err_, _asked))
    rc, out_, err_ = _agent_name_cli(["projects/nope", "a-one"], 404, "no project 'projects/nope'")
    check("client.py get agent-name: an unknown project (404) exits 1 with the reason on stderr and nothing on stdout", rc == 1 and out_ == "" and "[404]" in err_ and "no project" in err_, (rc, out_, err_))
    rc, out_, err_ = _agent_name_cli(["projects/alpha", "a-one"], 0, "URLError")
    check("client.py get agent-name: a server not reached exits 1", rc == 1 and out_ == "", (rc, out_, err_))
    n_asked = len(_asked)
    bad_use = [_agent_name_cli(a) for a in ([], ["projects/alpha"], ["projects/alpha", "--x"], ["projects/alpha", "a,b"], ["projects/alpha", " "])]
    check("client.py get agent-name: no project, no name, a flag or a comma in a name prints the usage on stderr, exits 1 and asks nothing", all(rc == 1 and o == "" and e.startswith("usage: client.py get agent-name") for rc, o, e in bad_use) and len(_asked) == n_asked, bad_use)
    check("client.py get agent-name: its usage names neither a machine nor a session manager", "sala" not in client.AGENT_NAME_USAGE.casefold() and "agent-name" in client.READS)

    # a time that fromtimestamp cannot take (a milliseconds epoch, 1e300, a numeric string) is no record: nothing raises anywhere, the item reads as a hold from before the record
    BAD = {30: 1e12, 31: 1.76e12, 32: 1e300, 33: "1e12", 34: float("inf"), 35: -5, 36: 4102444801}
    for n, v in BAD.items(): mk(n, hold=True, wake=D(10), hold_set={"at": v, "by": "sparrow"})
    mk(37, hold=True, wake=D(11), hold_set={"at": _t.time() - 60, "by": "sparrow\n## injected heading\r\n- [a1](#x) fake"})
    md_ = _rmod.render(str(_core_store.STORE), "full"); br_ = _rmod.render(str(_core_store.STORE), "brief"); rows_ = _notes_tool._holds_unexplained(); rep_ = _notes_tool._holds_report()
    check("a hold time outside 0 < t < year 2100 (1e12, 1.76e12, 1e300, \"1e12\", inf, negative, 2100+1 s) reads as no record: board.md, the brief, the report, get and an update all work, the item listed as before the record",
          all(_rmod.hold_at({"metadata": {"hold_set": {"at": v}}}) == 0.0 for v in BAD.values()) and all(f"a{n} · mover sparrow · wake " + D(10) + " · set by sparrow (before the record)" in rep_ for n in BAD)
          and all(next(r for r in rows_ if r["gid"] == f"a{n}")["at"] == 0 for n in BAD) and all(_wt_get.stackshot_get(f"a{n}") for n in BAD) and not upd(30, next="sparrow: the step that comes now", dropped=[1])[1]
          and _rmod.hold_at({"metadata": {"hold_set": {"at": _t.time() - 5}}}) > 0, (rep_[:300], rows_[:2]))
    mk(38, hold=True, recycle=True, hold_set={"at": 1790000000.0, "by": "home-first"}); upd(38, hold=True)      # a hold with a date folds into until and keeps no record; one that waits on an item or a recycle keeps its flag and record
    check("hold=true passed again on an item already held keeps the original record (who and when)", rdm(38)["hold_set"] == {"at": 1790000000.0, "by": "home-first"}, rdm(38))
    mk(39, hold=True, recycle=True); upd(39, hold=True)
    check("…but a hold with no record gets one when a session passes hold=true on it", set(rdm(39).get("hold_set") or {}) == {"at", "by"}, rdm(39))
    check("a hold_set.by with newlines is collapsed to one line before it reaches board.md, the report or get: no line is injected",
          "## injected heading" not in "\n".join(l for l in md_.splitlines() if l.startswith("## ") or l.startswith("- [a1]")) and "set by sparrow ## injected heading - [a1](#x) fake" in br_.replace("\n", " ") + md_
          and _rmod.hold_by({"metadata": {"hold_set": {"by": "x\ny" + "z" * 200}}}) == "x y" + "z" * 77 and "\n## injected" not in rep_ and "\n## injected" not in _wt_get.stackshot_get("a37"), (md_[md_.find("a37"):][:200],))
    # a hold's record goes when the hold ends: by the wake pass, by an after closing, by a release
    mk(40, hold=True, wake=(_pg_self.zone_now() - dt.timedelta(days=1)).strftime("%Y-%m-%d"), hold_set={"at": _t.time() - 3600, "by": "sparrow"})
    wakes_svc.wake_pass()
    check("the wake pass that releases a hold drops its record too", not _holders._is_held(_service_store._load("a40")) and "hold_set" not in rdm(40) and "hold" not in rdm(40), rdm(40))
    mk(41, hold=True, wake=WK, after=["a42"], hold_set={"at": _t.time() - 3600, "by": "sparrow"}); mk(42)
    check("while its after item is open, nothing is unexplained about the hold", "a41" not in [r["gid"] for r in _notes_tool._holds_unexplained()])
    _wt_complete.stackshot_complete("a42", sender="sparrow", outcome="done", reason="finished", description="- Finished: the thing is done")
    check("an after item closing releases the hold and drops its record", not _holders._is_held(_service_store._load("a41")) and "hold_set" not in rdm(41) and "hold" not in rdm(41) and "after" not in rdm(41), rdm(41))
    mk(43, hold=True, wake=WK, after=["a44"]); mk(44, status="completed"); mk(45, hold=True, wake=WK, after=["a46"])
    check("a held item whose after item is already closed, or missing, is listed as unexplained: nothing open holds it",
          {"a43", "a45"} <= {r["gid"] for r in _notes_tool._holds_unexplained()}, [r["gid"] for r in _notes_tool._holds_unexplained()])

    # the briefing data: the holds set in the last 24 hours (board.md's head, the brief tool, the session-start brief); a malformed record breaks none
    for i in (3, 4, 5): mk(i)
    mk(3, hold=True, wake=WK, hold_set={"at": _t.time() - 60, "by": "sparrow"})                      # new, nothing holds it
    mk(4, hold=True, wake=WK, after=["a20"], hold_set={"at": _t.time() - 60, "by": "sparrow"})       # new, an open after holds it
    mk(23, hold=True, wake=D(6), hold_set={"at": _t.time() - 3 * 86400, "by": "sparrow"})   # set three days ago: not new
    md = _rmod.render(str(_core_store.STORE), "full"); br = _rmod.render(str(_core_store.STORE), "brief")
    sect = md[md.find("## Newly parked"):md.find("Shared by every")]
    check("board.md has a section of the holds set in the last 24 hours, each with its owner, setter, wake and what holds it",
          "## Newly parked (last 24 hours)" in md and re.search(r"- \[a3\]\(#task-a-3\) · mover `[^`]*` · set by sparrow .* · wake .* · nothing holds it now", sect)
          and re.search(r"\[a4\].* · parked for after a20", sect), sect)
    check("the legacy renderer marks a parked item (parked, wake <day>) or (parked, no wake date) and an after wait \"after a20\", never on hold", re.search(r"\*\*a3 · [^\n]*\*\* \(parked, wake ", md) and re.search(r"\*\*a4 · [^\n]*\*\* \([^)\n]*after a20", md) and "(on hold" not in md and ", on hold" not in md, [l for l in md.split("\n") if "**a3 ·" in l or "**a4 ·" in l])
    check("…and not one set three days ago, one stored before the record, a malformed record or an item that is not held",
          all(f"[a{n}](#task-a-{n})" not in sect for n in (23, 13, 21, 22, 19, 1, 30, 31, 32, 33)), sect)
    check("the session-start brief lists them too", "  newly parked (24 h): a3 [home] hold fixture 3" in br and "nothing holds it now" in br and "parked for after a20" in br and "a23" not in br, br)
    (T / "board.md").write_text(md, encoding="utf-8")
    head = _wt_brief.stackshot_brief()
    check("the brief tool's head carries the section (it reads board.md up to the first lane)", head.find("## Newly parked") != -1 and head.find("## Newly parked") < head.find("All open items in full"), head[:300])
    check("a hold_set whose time is no number never raises in the renderer or in get", _rmod.hold_at({"metadata": {"hold_set": {"at": "x"}}}) == 0.0 and _rmod.hold_at({"metadata": {"hold_set": {"at": float("nan")}}}) == 0.0
          and "parked: set by sparrow" in _wt_get.stackshot_get("a21") and _wt_get.stackshot_get("a22"), _wt_get.stackshot_get("a21"))
    _update_svc._update("a3", clear_hold=True, sender="sparrow")
    check("a released hold is no longer new", "[a3]" not in _rmod.render(str(_core_store.STORE), "full").split("Shared by every")[0].split("## Newly parked")[-1])
    for i in range(2, 50): (T / f"store/a/{i}.json").unlink(missing_ok=True)

    # ---- 4. over HTTP, in-process
    from starlette.testclient import TestClient
    app = server.mcp.http_app()
    with TestClient(app) as c:
        r = c.get("/client/registry"); check("http: no token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/registry", headers={"Authorization": "Bearer " + "x" * 43}); check("http: a wrong token → 401", r.status_code == 401, r.status_code)
        H = {"Authorization": "Bearer " + tok}
        r = c.get("/client/whoami", headers=H); check("http: whoami names the machine", r.status_code == 200 and r.json() == {"machine": "box-far"}, r.text)
        r = c.get("/client/registry", headers=H); check("http: registry", r.status_code == 200 and "projects/alpha" in r.json()["pages"] and r.headers["cache-control"] == "no-store", r.text[:100])
        r = c.get("/client/page-ts", params={"key": "projects/alpha"}, headers=H); check("http: page-ts", r.status_code == 200 and r.json()["ts"], r.text)
        r = c.get("/client/brief", headers=H); check("http: brief", r.status_code == 200 and r.text.startswith("Board: 1 open"), r.text[:80])
        r = c.get("/client/holds", headers=H); check("http: holds → the report (nothing on hold without a reason here)", r.status_code == 200 and r.text == "no open item is parked without something holding it\n" and r.headers["cache-control"] == "no-store", r.text[:100])
        r = c.get("/client/holds"); check("http: holds without a token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/nothing", headers=H); check("http: unknown read → 404", r.status_code == 404, r.status_code)
        # agent-name: the register's name checks as a read, behind the same token as the other reads
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "names": "a-b"}); check("http: agent-name without a token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "names": "a-b"}, headers={"Authorization": "Bearer " + "x" * 43}); check("http: agent-name with a wrong token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "names": "a-b, c-d"}, headers=H); an = r.json() if r.status_code == 200 else {}
        check("http: agent-name with a valid token → 200 JSON: the project, its key, one result per name stripped and in order, first_free and the prefixes, nothing cached",
              r.status_code == 200 and r.headers["cache-control"] == "no-store" and an.get("key") == "projects/alpha" and an["project"].startswith("prj_") and [x["name"] for x in an["results"]] == ["a-b", "c-d"]
              and all(set(x) == {"name", "valid", "code", "reason"} for x in an["results"]) and isinstance(an["prefixes"], list) and an["prefixes"] and set(an) == {"project", "key", "results", "first_free", "prefixes"}, r.text[:400])
        good_ = an["prefixes"][0] + "-helper"
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "name": good_}, headers=H); an = r.json() if r.status_code == 200 else {}
        check("http: agent-name takes a single name= too; this project has no agent and no recent item, so it is hidden and every name says so (the register's own text), with no first_free",
              r.status_code == 200 and [(x["name"], x["valid"], x["code"]) for x in an["results"]] == [(good_, False, "hidden")] and "is hidden, not listed" in an["results"][0]["reason"] and an["first_free"] is None, r.text[:300])
        r = c.get("/client/agent-name", params={"key": "projects/no-such", "names": good_}, headers=H)
        check("http: agent-name for an unknown project → 404 with the text the other project reads give", r.status_code == 404 and r.text.startswith("no project 'projects/no-such'"), (r.status_code, r.text[:200]))
        r = c.get("/client/agent-name", params={"names": good_}, headers=H); check("http: agent-name with no key → 400", r.status_code == 400 and "key" in r.text, (r.status_code, r.text))
        r = c.get("/client/agent-name", params={"key": "projects/alpha"}, headers=H); check("http: agent-name with no names → 400 with a plain line", r.status_code == 400 and r.text.startswith("names ="), (r.status_code, r.text))
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "names": " , ,"}, headers=H); check("http: agent-name with only empty names → 400", r.status_code == 400, (r.status_code, r.text))
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "names": ",".join(f"x-{i}" for i in range(20))}, headers=H); check("http: agent-name with 20 names → 200", r.status_code == 200 and len(r.json()["results"]) == 20, (r.status_code, r.text[:100]))
        r = c.get("/client/agent-name", params={"key": "projects/alpha", "names": ",".join(f"x-{i}" for i in range(21))}, headers=H)
        check("http: agent-name with 21 names → 400 with a plain line, nothing answered", r.status_code == 400 and r.text.startswith("names = at most 20") and not r.text.startswith("{"), (r.status_code, r.text[:100]))
        r = c.get("/client/config"); check("http: config without a token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/config", headers=H); cj = r.json() if r.status_code == 200 else {}
        check("http: config — the instance's non-secret settings a client's hooks need", r.status_code == 200 and r.headers["cache-control"] == "no-store"
              and cj["instance"]["timezone"] == "Asia/Dubai" and cj["pages"] == {"flavor": "plain", "dirs": ["projects", "ops"]} and cj["paths"] == {"brain": f"{tmp}/brain"}
              and cj["subject"]["prefixes"] == ["[work] ", "[home] "] and cj["page_gate"] == {"keeper_currency": "keepers"} and cj["server"] == {"path": "/mcp"}
              and cj["board_check"] == {"mode": "off"}
              and set(cj) == {"instance", "pages", "paths", "subject", "page_gate", "board_check", "gbrain", "server"}, r.text[:400])
        check("http: config carries no secret and no secrets path", "secret" not in r.text.lower() and "token" not in r.text.lower() and f"{tmp}/secrets" not in r.text
              and "allowed_emails" not in r.text, r.text[:400])
        # the client's own fetch, against the same app
        import urllib.request, io
        class _Resp:
            def __init__(s, r): s.status = r.status_code; s._b = r.content
            def read(s): return s._b
            def __enter__(s): return s
            def __exit__(s, *a): return False
        def fake_urlopen(req, timeout=0):
            r = c.get(req.full_url.replace(client.server_url(), ""), headers=dict(req.header_items()))
            if r.status_code >= 400:
                import urllib.error; raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r)
        client.urllib.request.urlopen = fake_urlopen
        st, body = client.get("whoami"); check("client.get uses this machine's token", st == 200 and json.loads(body)["machine"] == me, (st, body))
        st, body = client.get("page-ts", "projects/alpha"); check("client.get passes the key", st == 200 and json.loads(body)["key"] == "projects/alpha", (st, body))
        # the write verb: a script's message, over HTTP and through client.py
        sent = []
        sent_kw = []      # the flags (fyi, question) each call to the message path carried
        _messaging._message = lambda to, text, sender, auth="", origin="", **kw: (sent.append((to, text, sender, auth, origin)), sent_kw.append(kw), "delivered → x — arrives as a labelled [stackshot message] turn")[2] if sender else (_ for _ in ()).throw(ToolError("Refused: sender is required"))
        r = c.post("/client/message", json={"to": "projects/alpha", "text": "hello", "sender": "nightly-job"}); check("http: a message without a token → 401", r.status_code == 401 and not sent, r.status_code)
        r = c.post("/client/message", json={"to": "projects/alpha", "text": "hello", "sender": "nightly-job"}, headers=H)
        check("http: a message with a machine token goes through the message path, marked with the machine", r.status_code == 200 and r.json()["result"].startswith("delivered") and sent == [("projects/alpha", "hello", "nightly-job", "machine:box-far", "box-far")], (r.text, sent))
        r = c.post("/client/message", json={"to": "projects/alpha", "text": "hello"}, headers=H); check("http: a refusal comes back as 400 with the reason", r.status_code == 400 and "sender is required" in r.json()["error"], r.text)
        r = c.post("/client/message", content=b"not json", headers=H); check("http: a body that is not JSON → 400", r.status_code == 400, r.text)
        r = c.get("/client/message", headers=H); check("http: the message path does not answer a GET as a read", r.status_code == 404, r.status_code)
        def fake_urlopen2(req, timeout=0):
            r = c.post(req.full_url.replace(client.server_url(), ""), content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(req.full_url.replace(client.server_url(), ""), headers=dict(req.header_items()))
            if r.status_code >= 400:
                import urllib.error; raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r)
        client.urllib.request.urlopen = fake_urlopen2
        st, body = client.message("projects/alpha", "from the client", "size-watch"); check("client.message sends with this machine's token and returns the server's answer", st == 200 and body.startswith("delivered") and sent[-1] == ("projects/alpha", "from the client", "size-watch", f"machine:{me}", me), (st, body, sent[-1]))
        st, body = client.message("projects/alpha", "x", ""); check("client.message hands back a refusal's reason", st == 400 and "sender is required" in body, (st, body))
        check("client.py message needs a label", client.main(["client.py", "message", "projects/alpha", "hi"]) == 1 and client.main(["client.py", "message", "projects/alpha", "hi", "--sender", "nightly-job"]) == 0 and sent[-1][1:3] == ("hi", "nightly-job"), sent[-1])
        st, body = client.message("projects/alpha", "is it ready?", "size-watch", question=True); check("client.message with question=True carries it through POST /client/message to the message path, and fyi is not set", st == 200 and sent_kw[-1] == {"question": True}, (st, body, sent_kw[-1]))
        st, body = client.message("projects/alpha", "fyi only", "size-watch", fyi=True); check("client.message with fyi=True carries only fyi (unchanged)", st == 200 and sent_kw[-1] == {"fyi": True}, sent_kw[-1])
        st, body = client.message("projects/alpha", "plain", "size-watch"); check("client.message without a flag sends neither mark", st == 200 and sent_kw[-1] == {}, sent_kw[-1])
        r = c.post("/client/message", json={"to": "projects/alpha", "text": "q", "sender": "nightly-job", "question": "yes"}, headers=H); check("http: only a question of true marks the message (a string does not)", r.status_code == 200 and sent_kw[-1] == {}, (r.text, sent_kw[-1]))
        n_sent = len(sent)
        check("client.py message --question marks the message as a question (exit 0)", client.main(["client.py", "message", "projects/alpha", "is it ready?", "--sender", "nightly-job", "--question"]) == 0 and len(sent) == n_sent + 1 and sent_kw[-1] == {"question": True}, (sent[-1], sent_kw[-1]))
        n_sent = len(sent); out_ = io.StringIO()
        with _cl.redirect_stdout(out_): rc_ = client.main(["client.py", "message", "projects/alpha", "is it ready?", "--sender", "nightly-job", "--question", "--fyi"])
        check("client.py message --question beside --fyi is a usage error (exit 1), nothing sent", rc_ == 1 and len(sent) == n_sent and "usage: client.py message" in out_.getvalue(), (rc_, out_.getvalue()[:200]))
        out_ = io.StringIO()
        with _cl.redirect_stdout(out_): client.main(["client.py", "message", "projects/alpha"])
        check("client.py message usage text names --question and that it does not go with --fyi", "--question" in out_.getvalue() and "Not with --fyi" in out_.getvalue(), out_.getvalue()[:300])
        # ---- a SendMessage handover a box's hook reports (pages.py touch → POST /client/handover) names the background agent
        _reg46, _a1 = (T / "store/projects.json").read_text(), (T / "store/a/1.json").read_text()
        rg = json.loads(_reg46); rg["pages"]["projects/alpha"].update(agents={"sparrow-main": "front", "sparrow-bg": "back"}, back_agents={"sparrow-bg": "back"}); (T / "store/projects.json").write_text(json.dumps(rg))
        M = "dddddddd-4444-4444-8444-444444444444"; (T / "fleet/a/sessions.json").write_text(json.dumps({M: {"name": "sparrow-main", "machine": "a", "url": "", "seen": "x"}}))
        m1 = lambda: json.loads((T / "store/a/1.json").read_text())["metadata"]
        r = c.post("/client/handover", json={"to": "sparrow-bg", "text": "a1 is yours", "sender": "sparrow-main"}); check("http: a handover without a token → 401", r.status_code == 401 and "needs" not in m1(), r.status_code)
        r = c.post("/client/handover", json={"to": "sparrow-bg", "text": "a1 is yours"}, headers=H); check("http: a handover without a sender → 400", r.status_code == 400 and "sender" in r.json()["error"], r.text)
        r = c.post("/client/handover", json={"to": "sparrow-bg", "text": "please take a1: the build", "sender": "sparrow-main"}, headers=H)
        check("http: a handover to a background agent names it in the item's needs, with the path in the record", r.status_code == 200 and m1().get("needs") == ["sparrow-bg"]
              and r.json() == {"result": "(named sparrow-bg in a1's needs: handover message from sparrow-main (SendMessage on box-far))"}, (r.text, m1()))
        (T / "store/a/1.json").write_text(_a1)
        r = c.post("/client/handover", json={"to": "sparrow-main", "text": "a1 is yours", "sender": "sparrow-bg"}, headers=H)
        check("http: a handover to a front agent names nobody, an empty result", r.status_code == 200 and r.json() == {"result": ""} and "needs" not in m1(), r.text)
        # the hook side: pages.py touch on a SendMessage payload posts the handover through client.post (this machine's token) and hands the server's line to the hook
        import io as _io; from stackshot.projects import pages
        pl = {"tool_name": "SendMessage", "session_id": M, "tool_input": {"to": "sparrow-bg", "message": "take a1 please"}, "tool_response": "Message sent"}
        out = pages.handover(pl)
        check("pages.py: a SendMessage to a background agent that names an item is reported with the sender's name, and the server's line comes back",
              out == f"[stackshot] (named sparrow-bg in a1's needs: handover message from sparrow-main (SendMessage on {me}))" and m1().get("needs") == ["sparrow-bg"], (out, m1()))
        calls = []; _post = client.post; client.post = lambda *a, **k: (calls.append(a), _post(*a, **k))[1]
        try:
            check("pages.py: a message that names no item makes no call", pages.handover({**pl, "tool_input": {"to": "sparrow-bg", "message": "no id here, just words"}}) == "" and not calls, calls)
            check("pages.py: a message that names an item but goes to a front agent makes the call and gets nothing back", pages.handover({**pl, "tool_input": {"to": "sparrow-main", "message": "a1 again"}}) == "" and len(calls) == 1, calls)
        finally: client.post = _post
        (T / "store/a/1.json").write_text(_a1)
        _in, _out = sys.stdin, sys.stdout; sys.stdin, sys.stdout = _io.StringIO(json.dumps(pl)), _io.StringIO()
        try: pages.cmd_touch(); printed = sys.stdout.getvalue()
        finally: sys.stdin, sys.stdout = _in, _out
        check("pages.py touch: the hook entry prints the server's line as one additionalContext", json.loads(printed or "{}") == {"hookSpecificOutput": {"hookEventName": "PostToolUse",
              "additionalContext": f"[stackshot] (named sparrow-bg in a1's needs: handover message from sparrow-main (SendMessage on {me}))"}} and m1().get("needs") == ["sparrow-bg"], printed)
        (T / "store/a/1.json").write_text(_a1); (T / "store/projects.json").write_text(_reg46); (T / "fleet/a/sessions.json").write_text("{}")
        # ---- anchor-add: a hook adds the anchors of a pull request or an issue (POST /client/anchor-add, client.py post anchor-add -); the anchors tool's add, never its remove
        _anchors_raw = (T / "store/anchors.json").read_text()
        rg = json.loads(_reg46); rg["pages"]["projects/beta"] = {**rg["pages"]["projects/alpha"], "title": "Beta", "name": "Beta"}; (T / "store/projects.json").write_text(json.dumps(rg))
        def _fx(n, project, status="open"):
            (T / f"store/a/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] anchor fixture {n}", "description": "A thing. It lives here. Done when done.", "status": status,
                                                              "metadata": {"owner": "sparrow", "project": project}}))
        _fx(2, "projects/beta"); _fx(3, "projects/alpha", "completed"); _fx(4, "projects/alpha")
        anc = lambda: json.loads((T / "store/anchors.json").read_text())
        U1, U2, U3 = (f"https://github.com/example-org/example-repo/pull/{n}" for n in (101, 102, 103)); U4 = "https://github.com/example-org/example-repo/issues/104"
        BY = "hook-sender via a script on box-far"
        add_ = lambda body, hdr=H: c.post("/client/anchor-add", json=body, headers=hdr)
        r = add_({"project": "projects/alpha", "add": [U1], "sender": "hook-sender"}, {}); check("http: anchor-add without a token → 401, nothing stored", r.status_code == 401 and anc() == {}, (r.status_code, anc()))
        r = add_({"project": "projects/alpha", "add": [U1], "sender": "hook-sender"}, {"Authorization": "Bearer " + "x" * 43}); check("http: anchor-add with a wrong token → 401, nothing stored", r.status_code == 401 and anc() == {}, (r.status_code, anc()))
        r = c.post("/client/anchor-add", content=b"not json", headers=H); check("http: anchor-add with a body that is not JSON → 400", r.status_code == 400, r.text)
        r = c.get("/client/anchor-add", headers=H); check("http: anchor-add does not answer a GET", r.status_code == 404, r.status_code)
        r = add_({"project": "projects/alpha", "add": [U1], "sender": "hook-sender"})
        check("http: a project-wide add → 200 with the tool's own text, and the anchor is stored project-wide with who added it",
              r.status_code == 200 and set(r.json()) == {"result"} and r.json()["result"].startswith("projects/alpha anchors (") and f"- {U1}  [project-wide]" in r.json()["result"]
              and anc()["projects/alpha"] == [{"url": U1, "items": None, "added": anc()["projects/alpha"][0]["added"], "by": BY}], (r.text, anc()))
        r = add_({"project": "alpha", "add": [U2], "items": ["a1"], "sender": "hook-sender"})
        check("http: an item-scoped add (the bare slug names the project) → 200, the anchor is listed and stored for that item only",
              r.status_code == 200 and f"- {U2}  [items: a1]" in r.json()["result"] and f"- {U1}  [project-wide]" in r.json()["result"]
              and [(e["url"], e["items"]) for e in anc()["projects/alpha"]] == [(U1, None), (U2, ["a1"])], (r.text, anc()))
        r = add_({"project": "projects/alpha", "add": [U2], "items": ["a4"], "sender": "hook-sender"})
        check("http: adding a URL again scoped to another item widens its items (the tool's union)", r.status_code == 200 and f"- {U2}  [items: a1, a4]" in r.json()["result"], (r.text, anc()))
        r = add_({"project": "projects/alpha", "add": [U2], "sender": "hook-sender"})
        check("http: adding it project-wide makes it project-wide", r.status_code == 200 and f"- {U2}  [project-wide]" in r.json()["result"], r.text)
        r = add_({"project": "projects/alpha", "add": [U2], "items": ["a1"], "sender": "hook-sender"})
        check("http: …and a scoped add never narrows a project-wide anchor again", r.status_code == 200 and f"- {U2}  [project-wide]" in r.json()["result"]
              and [(e["url"], e["items"]) for e in anc()["projects/alpha"]] == [(U1, None), (U2, None)], (r.text, anc()))
        r = add_({"project": "projects/alpha", "add": [U3, U4], "items": [" a4 "], "sender": "hook-sender", "remove": []})
        check("http: several URLs in one call, an item id with blanks around it, and an empty remove (nothing to remove) → 200", r.status_code == 200 and f"- {U3}  [items: a4]" in r.json()["result"] and f"- {U4}  [items: a4]" in r.json()["result"], (r.text, anc()))
        r = add_({"project": "projects/alpha", "add": [U1], "items": [], "sender": "hook-sender"})
        check("http: an empty items list is project-wide, as the tool takes it", r.status_code == 200 and f"- {U1}  [project-wide]" in r.json()["result"], r.text)
        PR = lambda n: f"https://github.com/example-org/example-repo/pull/{n}"
        by_of = lambda url: next((e["by"] for e in anc()["projects/alpha"] if e["url"] == url), None)
        r = add_({"project": "projects/alpha", "add": [PR(n) for n in range(201, 211)], "sender": "hook-sender"})
        check("http: exactly 10 URLs in one call are taken", r.status_code == 200 and all(f"- {PR(n)}  [project-wide]" in r.json()["result"] for n in range(201, 211)), r.text[:300])
        U300 = PR("7" * (300 - len(PR(""))))
        r = add_({"project": "projects/alpha", "add": [U300], "sender": "hook-sender"}); check("http: a URL of exactly 300 characters is taken", r.status_code == 200 and len(U300) == 300 and by_of(U300) == BY, (r.status_code, r.text[:200]))
        r = add_({"project": "projects/alpha", "add": [U4 + "1"], "items": ["a4"] * 20, "sender": "hook-sender"}); check("http: exactly 20 item ids are taken", r.status_code == 200 and f"- {U4}1  [items: a4]" in r.json()["result"], r.text[:300])
        r = add_({"project": "projects/alpha", "add": [PR(301)], "sender": "hook\x1b[31m-sender‮  \t with \n blanks\x00​"})
        check("http: control, bidi and zero-width characters are taken out of the sender and the blanks collapsed", r.status_code == 200 and by_of(PR(301)) == "hook[31m-sender with blanks via a script on box-far", (r.text[:200], by_of(PR(301))))
        r = add_({"project": "projects/alpha", "add": [PR(302)], "sender": "h" * 80}); check("http: a sender of exactly 80 characters is taken", r.status_code == 200 and by_of(PR(302)) == "h" * 80 + " via a script on box-far", r.text[:200])
        for n_, u_ in enumerate(("https://github.com/example-org/.github/pull/1", "https://github.com/.a/b/pull/1", "https://github.com/a/b./pull/1")):
            r = add_({"project": "projects/alpha", "add": [u_], "sender": "hook-sender"})
            check(f"http: a name that merely starts or ends with a dot is a name and is taken ({u_[19:-7]})", r.status_code == 200 and by_of(u_) == BY, (r.status_code, r.text[:200]))
        r = add_({"project": "projects/alpha", "add": [PR(303)], "sender": "hook\u3164\u115f\u1160\u2800\uffa0-sender"})
        check("http: Hangul fillers and the braille blank are taken out of the sender", r.status_code == 200 and by_of(PR(303)) == BY, (r.text[:200], by_of(PR(303))))
        before = (T / "store/anchors.json").read_text()
        def refused_(name, body, *words, status=400):
            r = add_(body); err = r.json().get("error", "") if r.status_code == status and isinstance(r.json(), dict) else ""
            check(name, r.status_code == status and set(r.json()) == {"error"} and all(w in err for w in words) and (T / "store/anchors.json").read_text() == before, (r.status_code, r.text[:300]))
        S = "hook-sender"
        refused_("http: anchor-add of a completed item is refused with the tool's text, nothing stored", {"project": "projects/alpha", "add": [U3], "items": ["a3"], "sender": S}, "Refused", "a3 is completed", "leave it project-wide")
        refused_("http: …an item of another project", {"project": "projects/alpha", "add": [U3], "items": ["a2"], "sender": S}, "Refused", "a2 belongs to projects/beta, not projects/alpha")
        refused_("http: …an item that does not exist", {"project": "projects/alpha", "add": [U3], "items": ["a99"], "sender": S}, "Refused", "no item a99")
        refused_("http: …one good and one completed item (nothing of the call is stored)", {"project": "projects/alpha", "add": [U3], "items": ["a4", "a3"], "sender": S}, "a3 is completed")
        ONLY = "only pull request and issue URLs are accepted here"
        refused_("http: …a URL that is no anchor shape", {"project": "projects/alpha", "add": ["https://example.invalid/not-an-anchor"], "sender": S}, ONLY)
        refused_("http: …a good URL beside a bad one stores neither", {"project": "projects/alpha", "add": [U3 + "0", "not a url"], "sender": S}, ONLY)
        # the machine token is no proof of the owner: the tool's other shapes, which make the server read mail, chat, files or a repo's notifications, are not taken here
        for what_, url_ in (("a Gmail query", "gmail:q:from:someone"), ("a Gmail query scoped to a mailbox", "gmail:q@work:from:someone"), ("a Gmail thread link", "https://mail.google.com/mail/u/0/#inbox/0123456789abcdef"),
                            ("a Slack channel", "https://example-team.slack.com/archives/C0123456789"), ("a Slack anchor id", "slack:C0123456789"),
                            ("a Drive file", "https://drive.google.com/file/d/0123456789abcdefghij/view"), ("a Drive anchor id", "drive:0123456789abcdefghij"),
                            ("a Notion page", "https://www.notion.so/Page-0123456789abcdef0123456789abcdef"), ("a repo's notifications id", "github:example-org/example-repo@notifications"),
                            ("a repo's notifications link", "https://github.com/example-org/example-repo"), ("a repo's releases", "https://github.com/example-org/example-repo/releases"),
                            ("a repo URL with a trailing slash", "https://github.com/example-org/example-repo/"), ("an anchor id of a pull request", "github:example-org/example-repo#101"),
                            ("a repo URL with no pull request number", "https://github.com/example-org/example-repo/pull/"), ("a pull request number that is not digits", PR("abc")),
                            ("a pull request under /files", PR(101) + "/files"), ("a fragment", PR(101) + "#issuecomment-1"), ("a query", PR(101) + "?x=1"), ("trailing text", PR(101) + " and more"),
                            ("a trailing newline", PR(101) + "\n"), ("a newline inside", PR(101) + "\nslack:C0123456789"), ("a NUL", PR(101) + "\x00"), ("a leading blank", " " + PR(101)),
                            ("a `..` owner", "https://github.com/../example-repo/pull/1"), ("`..` as owner and repo", "https://github.com/../../pull/1"), ("a `.` repo", "https://github.com/example-org/./pull/1"),
                            ("a `.` owner", "https://github.com/./example-repo/pull/1"), ("a `..` repo", "https://github.com/example-org/../pull/1"),
                            ("plain http", "http://github.com/example-org/example-repo/pull/101"), ("another host", "https://github.example.invalid/example-org/example-repo/pull/101"), ("an Arabic-Indic digit", PR("١٢"))):
            refused_(f"http: …{what_} is not a pull request or issue URL: refused, nothing stored", {"project": "projects/alpha", "add": [url_], "sender": S}, ONLY)
        refused_("http: …a good URL beside a Gmail query stores neither", {"project": "projects/alpha", "add": [U3 + "0", "gmail:q:from:someone"], "sender": S}, ONLY)
        refused_("http: …11 URLs in one call", {"project": "projects/alpha", "add": [PR(400 + n) for n in range(11)], "sender": S}, "add takes at most 10 URLs")
        refused_("http: …11 copies of one URL count as 11", {"project": "projects/alpha", "add": [U3] * 11, "sender": S}, "add takes at most 10 URLs")
        refused_("http: …a URL of 301 characters", {"project": "projects/alpha", "add": [PR("7" * (301 - len(PR(""))))], "sender": S}, "at most 300 characters")
        refused_("http: …21 item ids in one call (a repeated id counts each time)", {"project": "projects/alpha", "add": [U3], "items": ["a4"] * 21, "sender": S}, "items takes at most 20")
        refused_("http: …a project of over 200 characters", {"project": "p" * 201, "add": [U3], "sender": S}, "project is required")
        refused_("http: …a sender that is not text (a number)", {"project": "projects/alpha", "add": [U3], "sender": 5}, "sender is required, as text")
        refused_("http: …a sender that is not text (a list)", {"project": "projects/alpha", "add": [U3], "sender": ["x"]}, "sender is required, as text")
        refused_("http: …a sender of only Hangul fillers and braille blanks", {"project": "projects/alpha", "add": [U3], "sender": "\u3164\u115f\u1160\u2800\uffa0"}, "sender is required")
        refused_("http: …a sender of only control characters", {"project": "projects/alpha", "add": [U3], "sender": "\x1b‮\x00"}, "sender is required")
        refused_("http: …a sender of 81 characters after the control characters are taken out", {"project": "projects/alpha", "add": [U3], "sender": "h" * 40 + "\x1b" + "h" * 41}, "sender is required")
        refused_("http: …a project that names no page", {"project": "projects/no-such", "add": [U3], "sender": S}, "Refused", "names no page")
        refused_("http: a body with no project is refused with the shape", {"add": [U3], "sender": S}, "project is required", "sender")
        refused_("http: …a project that is not text", {"project": 5, "add": [U3], "sender": S}, "project is required")
        refused_("http: …a blank project", {"project": "  ", "add": [U3], "sender": S}, "project is required")
        refused_("http: …no add", {"project": "projects/alpha", "sender": S}, "add must be a non-empty list")
        refused_("http: …an empty add", {"project": "projects/alpha", "add": [], "sender": S}, "add must be a non-empty list")
        refused_("http: …an add that is a string, not a list", {"project": "projects/alpha", "add": U3, "sender": S}, "add must be a non-empty list")
        refused_("http: …an add with a value that is not text", {"project": "projects/alpha", "add": [U3, 7], "sender": S}, "add must be a non-empty list")
        refused_("http: …items that is a string, not a list", {"project": "projects/alpha", "add": [U3], "items": "a1", "sender": S}, "items must be a list")
        refused_("http: …items with a value that is not text", {"project": "projects/alpha", "add": [U3], "items": [1], "sender": S}, "items must be a list")
        refused_("http: …no sender", {"project": "projects/alpha", "add": [U3]}, "sender is required")
        refused_("http: …a sender over 80 characters", {"project": "projects/alpha", "add": [U3], "sender": "s" * 81}, "sender is required")
        refused_("http: a body that carries a remove is refused, and removes nothing", {"project": "projects/alpha", "add": [U3], "sender": S, "remove": [U1]}, "only adds anchors")
        r = add_({"project": "projects/alpha", "add": [U3], "sender": S, "remove": [U1]})
        check("http: …the anchor the remove named is still on the page", any(e["url"] == U1 for e in anc()["projects/alpha"]), anc())
        # the script client: `post anchor-add -` reads the JSON object on stdin, prints the server's text and exits 0, or says why on stderr and exits 1
        def run_(argv, text):
            out_, err_ = io.StringIO(), io.StringIO(); _in = sys.stdin; sys.stdin = io.StringIO(text)
            try:
                with _cl.redirect_stdout(out_), _cl.redirect_stderr(err_): rc = client.main(["client.py", "post", "anchor-add", *argv])
            finally: sys.stdin = _in
            return rc, out_.getvalue(), err_.getvalue()
        rc_, o_, e_ = run_(["-"], json.dumps({"project": "projects/alpha", "add": [U3 + "1"], "items": ["a4"], "sender": S}))
        check("client.py post anchor-add -: a good body prints the server's text and exits 0", rc_ == 0 and f"- {U3}1  [items: a4]" in o_ and not e_, (rc_, o_, e_))
        rc_, o_, e_ = run_(["-"], json.dumps({"project": "projects/alpha", "add": [U3], "items": ["a3"], "sender": S}))
        check("client.py post anchor-add -: a refusal prints the tool's text on stderr and exits 1", rc_ == 1 and not o_ and "[400]" in e_ and "a3 is completed" in e_, (rc_, o_, e_))
        n_ = len(anc()["projects/alpha"])
        for name_, argv_, text_ in (("a body that is not JSON", ["-"], "nope"), ("a body that is not an object", ["-"], "[1]"), ("a body with no sender", ["-"], json.dumps({"project": "projects/alpha", "add": [U3]})),
                                    ("a body with an empty add", ["-"], json.dumps({"project": "projects/alpha", "add": [], "sender": S})), ("no dash", [], "{}"), ("a flag instead of the dash", ["--project", "x"], "{}")):
            rc_, o_, e_ = run_(argv_, text_)
            check(f"client.py post anchor-add: {name_} → usage on stderr, exit 1, nothing sent", rc_ == 1 and not o_ and "usage: client.py post anchor-add" in e_ and len(anc()["projects/alpha"]) == n_, (rc_, o_, e_))
        for n in (2, 3, 4): (T / f"store/a/{n}.json").unlink()
        (T / "store/projects.json").write_text(_reg46); (T / "store/anchors.json").write_text(_anchors_raw)
        os.remove(T / "secrets/client.token"); st, body = client.get("registry"); check("client.get without a token says how to get one", st == 401 and "mint" in body, (st, body))

    # ---- 5. a held poll when the server stops (the item follow-up): uvicorn cancels the handler once its graceful shutdown times out;
    # the puller gets an empty answer (200), not a 500 and a traceback in the server's log
    import asyncio
    from starlette.requests import Request
    async def _held_poll_cancelled():
        body = json.dumps({"sessions": [], "wait": 30}).encode()
        async def receive(): return {"type": "http.request", "body": body, "more_body": False}
        req = Request({"type": "http", "method": "POST", "path": "/client/poll", "query_string": b"", "path_params": {"what": "poll"},
                       "headers": [(b"authorization", ("Bearer " + tok).encode()), (b"content-type", b"application/json")]}, receive)
        t = asyncio.create_task(_rt_client.client_write(req))
        await asyncio.sleep(1.5); held = not t.done()
        t.cancel()
        try: return held, await t
        except asyncio.CancelledError: return held, None
    held, resp = asyncio.run(_held_poll_cancelled())
    _pb = json.loads(resp.body) if resp is not None else {}
    check("poll: a held poll cancelled by the server's shutdown answers 200 with no deliveries (and what is current, puller 9, and the repo address, puller 10)", held and resp is not None and resp.status_code == 200
          and _pb.get("deliveries") == [] and _pb.get("machine") == "box-far" and {"puller", "stackshot", "self_update"} <= set(_pb.get("current") or {}) <= {"puller", "stackshot", "self_update", "repo"}, (held, resp and resp.status_code, resp and resp.body))

    # ---- 6. the puller's CLI version probe starts no window on Windows (2026-10-05): pythonw has no console, so a console child
    # would get a fresh one, which Windows 11 shows as a terminal flashing every ten minutes
    import subprocess; from stackshot.fleet import puller
    seen = []
    class _Out: stdout = "2.1.288 (Claude Code)"
    def _fake_run(args, **kw): seen.append(kw); return _Out()
    _run, _win, _ver = puller.subprocess.run, puller.WINDOWS, dict(puller._VER)
    try:
        puller.subprocess.run = _fake_run
        for win in (True, False):
            puller.WINDOWS = win
            puller._VER = {"at": 0.0, "v": ""}; seen.clear(); v = puller.cli_version([])
            if win:
                check("puller: on Windows the version probe runs with CREATE_NO_WINDOW and no stdin", seen and seen[0].get("creationflags") == 0x08000000 and seen[0].get("stdin") is subprocess.DEVNULL, seen)
            else:
                check("puller: elsewhere the version probe sets no creationflags, and no stdin", seen and "creationflags" not in seen[0] and seen[0].get("stdin") is subprocess.DEVNULL, seen)
            check(f"puller: the probe's answer is the version ({'windows' if win else 'linux'})", v == "2.1.288", v)
        # an update swaps the binary: the version is asked again at once, not after the 10-min wait
        puller.WINDOWS = False; _sig = puller._cli_sig
        try:
            puller._cli_sig = lambda: ("/x/claude", 1, 1); puller._VER = {"at": 0.0, "v": "", "sig": None}; puller.cli_version([]); seen.clear()
            puller.cli_version([]); check("puller: same binary within 10 min → no new probe", not seen, seen)
            puller._cli_sig = lambda: ("/x/claude", 2, 2); _Out.stdout = "2.1.289 (Claude Code)"; v = puller.cli_version([])
            check("puller: the binary changed → probed again at once, new version reported", len(seen) == 1 and v == "2.1.289", (seen, v))
            puller._cli_sig = lambda: None; seen.clear(); puller.cli_version([])
            check("puller: binary not found → no probe until the 10 min pass", not seen, seen)
        finally:
            puller._cli_sig = _sig
    finally:
        puller.subprocess.run, puller.WINDOWS, puller._VER = _run, _win, _ver

    # ---- 6b. the router's own `claude -p` call is not a session: the CLI registers it (cwd = <tmp>/stackshot-router-XXXX, made by
    # router.run_call with config.ROUTER_CWD_PREFIX; router_scenario checks the call's cwd), and the puller must not report it
    import tempfile as _tf; from stackshot.core import config as _cfgm
    _reg = T / "registry"; _reg.mkdir()
    def _rec(n, sid, cwd):
        (_reg / f"{n}.json").write_text(json.dumps({"sessionId": sid, "name": n, "pid": os.getpid(), "messagingSocketPath": "/x/sock", "cwd": cwd, "updatedAt": 1}))
    _tmpdir = _tf.gettempdir()
    _rec("router", "11111111-1111-4111-8111-111111111111", os.path.join(_tmpdir, _cfgm.ROUTER_CWD_PREFIX + "ab12cd"))
    _rec("normal", "22222222-2222-4222-8222-222222222222", "/home/user")
    _rec("lookalike-elsewhere", "33333333-3333-4333-8333-333333333333", "/srv/" + _cfgm.ROUTER_CWD_PREFIX + "ab12cd")
    _rec("other-in-tmp", "44444444-4444-4444-8444-444444444444", os.path.join(_tmpdir, "something-else"))
    _rec("no-cwd", "55555555-5555-4555-8555-555555555555", "")
    _names = sorted(r["name"] for r in puller.sessions(str(_reg)))
    check("puller: a record in <tmp>/stackshot-router-* is skipped, every other record is kept", _names == ["lookalike-elsewhere", "no-cwd", "normal", "other-in-tmp"], _names)
    check("puller: the shared prefix is the one the router's temporary directory has", _cfgm.ROUTER_CWD_PREFIX == "stackshot-router-")

    # ---- 7. items?key=<session>: the open items a session owns, for the end-of-turn board check
    U, V = "aaaaaaaa-1111-4111-8111-111111111111", "bbbbbbbb-2222-4222-8222-222222222222"
    (T / "fleet/a/sessions.json").write_text(json.dumps({U: {"name": "sparrow", "machine": "a"}, V: {"name": "home-other", "machine": "a"}}))
    def item(n, owner, status="open", **extra):
        meta = {"owner": owner, "project": "projects/alpha", **extra.pop("meta", {})}
        if not ({"needs", "mover", "then", "hold", "after"} & set(meta)): meta["mover"] = owner      # the creator moves nothing; the fixture's items are moved by their former creator
        (T / f"store/a/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] item {n}", "description": "x", "status": status, "metadata": meta, **extra}))
    item(2, U, state_updated=100.0, confirmed=200.0, updated=300.0, meta={"needs": "decision", "then": U, "next": "first\nsecond"})
    item(3, U, "on_hold")                                       # the retired status, not yet migrated: open and held
    item(4, U, meta={"hold": True, "mover": U})
    item(5, U, "completed"); item(6, V); item(7, "cse_0123456789abcdef", meta={"owner_name": "sparrow", "mover": "sparrow"})
    gids = lambda body: [x["gid"] for x in json.loads(body)["items"]]
    st, ct, body = client_reads_svc._client_get("items", {"key": U})
    check("items: by the transcript uuid, the session's open items only (an owner stored by name, a held one, one by owner_name)",
          st == 200 and ct == "application/json" and gids(body) == ["a1", "a2", "a3", "a4", "a7"], (st, body[:400]))
    st, ct, body2 = client_reads_svc._client_get("items", {"key": "sparrow"}); check("items: by the pane name, the same", st == 200 and gids(body2) == gids(body), body2[:300])
    st, ct, body3 = client_reads_svc._client_get("items", {"key": V}); check("items: another session sees only its own", st == 200 and gids(body3) == ["a6"], body3[:300])
    st, ct, body4 = client_reads_svc._client_get("items", {"key": "nobody-at-all"}); check("items: a session that owns nothing: an empty list", st == 200 and json.loads(body4) == {"items": []}, body4)
    x = {i["gid"]: i for i in json.loads(body)["items"]}
    eb2, od2 = x["a2"].pop("expected_by"), x["a2"].pop("overdue")      # kept as keys, always empty (they go in a later release)
    check("items: the fields", x["a2"] == {"gid": "a2", "shown": "a2", "subject": "[home] item 2", "needs": ["decision"], "contact": "", "next": "first\nsecond", "state_updated": 100.0, "confirmed": 200.0, "updated": 300.0, "held": False, "list": "your-move",
          "mover": {"kind": _cfgm.owner_mover_kind(), "who": _core_instance.OWNER}, "wait": "", "scope": "home", "roles": ["then"]}, x["a2"])   # roles = the asking session's live roles (the owner's item, Oliver moves it: keeper only); the stored item state (derived here); the one rule's fields (waiting.py): whose move, by when
    check("items: expected_by and overdue stay as keys and are always empty (no expected time is computed), wait is the empty string", eb2 is None and od2 is None and x["a2"]["wait"] == "" and all(i["expected_by"] is None for i in json.loads(body)["items"]), (eb2, od2))
    check("items: held, from metadata.hold and from the retired status", x["a3"]["held"] and x["a4"]["held"] and not x["a1"]["held"], (x["a3"], x["a4"]))
    check("items: an older file without the clocks: state_updated and updated null, confirmed from its fallback", x["a1"]["state_updated"] is None and x["a1"]["updated"] is None and x["a1"]["confirmed"] > 0, x["a1"])
    for bad in ("", "a\nb", "x" * 201):
        st, ct, b = client_reads_svc._client_get("items", {"key": bad}); check(f"items refuses the key {bad[:6]!r}", st == 400, (st, b))
    with TestClient(app) as c:
        r = c.get("/client/items", params={"key": U}); check("http: items without a token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/items", params={"key": U}, headers={"Authorization": "Bearer " + "y" * 43}); check("http: items with a wrong token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/items", params={"key": U}, headers=H)
        check("http: items with the machine's token", r.status_code == 200 and [i["gid"] for i in r.json()["items"]] == ["a1", "a2", "a3", "a4", "a7"] and r.headers["cache-control"] == "no-store", r.text[:200])
    check("client.py knows the read", "items" in client.READS)

    # ---- 7b. every row carries `list`, the home page's list the item is in (home.list_of), so the fleet tool's items sheet groups as the page does
    X = "dddddddd-4444-4444-8444-444444444444"
    (T / "fleet/a/sessions.json").write_text(json.dumps({U: {"name": "sparrow", "machine": "a"}, V: {"name": "home-other", "machine": "a"}, X: {"name": "home-lister", "machine": "a"}}))
    item(21, X, meta={"needs": "decision", "then": X, "next": "home-lister: carry on"})                    # Oliver moves it: Your move
    item(22, X)                                                                                           # an agent (X) moves it: Agents at work
    item(23, X, meta={"wait_kind": "time", "wake": "2030-01-01", "then": X, "post_wake_mover": X})       # waiting on a time, X takes it after: Waiting
    rows = {i["gid"]: i for i in json.loads(client_reads_svc._client_get("items", {"key": X})[2])["items"]}
    check("items: list is your-move for an item Oliver moves, agents for one an agent moves, waiting for a wait",
          (rows.get("a21") or {}).get("list") == "your-move" and (rows.get("a22") or {}).get("list") == "agents" and (rows.get("a23") or {}).get("list") == "waiting",
          {g: r.get("list") for g, r in rows.items()})
    check("items: every row of the list is one of the three words", rows and all(r.get("list") in ("your-move", "agents", "waiting") for r in rows.values()), {g: r.get("list") for g, r in rows.items()})
    check("items: list is the home page's own reading of the item (home.list_of on the model)",
          all(r["list"] == _home.list_of(_item_read._model_of(dict(json.loads((T / f"store/a/{g[1:]}.json").read_text()), gid=g))) for g, r in rows.items()), rows)
    for n in (21, 22, 23): (T / f"store/a/{n}.json").unlink()        # the later sections count the fixture's items
    (T / "fleet/a/sessions.json").write_text(json.dumps({U: {"name": "sparrow", "machine": "a"}, V: {"name": "home-other", "machine": "a"}}))

    # ---- 7c. the raw reads: item-record, open-records, anchors-record return what the store files hold, nothing derived
    cr = client_reads_svc; from stackshot.github import ghsync as _gh_
    raw = lambda n: json.loads((T / f"store/a/{n}.json").read_text(encoding="utf-8"))
    st, ct, b = cr._client_get("item-record", {"key": "a2"}); j = json.loads(b)
    check("item-record: exactly the stored record (compared with the file), with its id and how it is shown", st == 200 and ct == "application/json" and j == {"id": "a2", "shown": "a2", "record": raw(2), "anchors": []} and j["record"]["metadata"]["then"] == U, (st, b[:300]))
    st, ct, b = cr._client_get("item-record", {"key": "a3"}); j = json.loads(b)
    check("item-record: nothing is read through: the retired status stays as stored, no derived field is added", st == 200 and j["record"] == raw(3) and j["record"]["status"] == "on_hold" and "hold" not in j["record"]["metadata"], b[:300])
    st, ct, b = cr._client_get("item-record", {"key": "a5"}); j = json.loads(b)
    check("item-record: a closed item is returned too", st == 200 and j["record"] == raw(5) and j["record"]["status"] == "completed", b[:300])
    st, ct, b = cr._client_get("item-record", {"key": "A2"}); check("item-record: the id is read as the other reads read it (case)", st == 200 and json.loads(b)["id"] == "a2", (st, b[:100]))
    for bad in ("", "x; rm -rf", "a\n2", "a" * 201, "not an id"):
        st, ct, b = cr._client_get("item-record", {"key": bad}); check(f"item-record refuses the id {bad[:8]!r} cleanly (400, no traceback)", st == 400 and "Traceback" not in b, (st, b[:120]))
    st, ct, b = cr._client_get("item-record", {"key": "a999"}); check("item-record: an id that names no item is 404", st == 404 and ct.startswith("text/plain"), (st, b))
    (T / "store/a/8.json").write_text("{not json"); st, ct, b = cr._client_get("item-record", {"key": "a8"}); check("item-record: a file that is there and does not read is 503 (not 404: the item exists), not a crash", st == 503 and "Traceback" not in b, (st, b)); (T / "store/a/8.json").write_text("[1]")
    st, ct, b = cr._client_get("item-record", {"key": "a8"}); check("item-record: a file that is no record is 503 too", st == 503, (st, b)); (T / "store/a/8.json").unlink()
    _mpf = T / "store" / _gh_.MAP_NAME; _mp0 = _mpf.read_text() if _mpf.exists() else None; mp_ = _gh_.load_map(T / "store"); _gh_.save_map({**mp_, "aliases": {**mp_["aliases"], "s9": "a2"}}, T / "store")
    try: st, ct, b = cr._client_get("item-record", {"key": "s9"}); j = json.loads(b)
    finally: _mpf.unlink() if _mp0 is None else _mpf.write_text(_mp0)
    check("item-record: an old id of a migrated item reads through the alias map and answers the id now", st == 200 and j["id"] == "a2" and j["record"] == raw(2), (st, b[:150]))

    item(9, U, "completed", meta={"mover": U})
    def recs(key): st_, _c, b_ = cr._client_get("open-records", {"key": key}); return st_, json.loads(b_) if st_ == 200 else b_
    for who in (U, "sparrow", V, "nobody-at-all"):
        st, j = recs(who); want = gids(cr._client_get("items", {"key": who})[2])
        check(f"open-records ({who[:8]}): the same items as `items`, in the same order, each the stored record", st == 200 and [x["id"] for x in j["items"]] == want and all(x["record"] == raw(int(x["id"][1:])) for x in j["items"]) and j["total"] == len(want) and j["truncated"] is False and j["session"] == who, (st, str(j)[:300]))
    st, j = recs(U); ids_ = [x["id"] for x in j["items"]]
    check("open-records: the session's items in every state (held, retired status, a decision it takes after), never a closed one; item-record has the closed one", ids_ == ["a1", "a2", "a3", "a4", "a7"] and "a5" not in ids_ and "a9" not in ids_ and json.loads(cr._client_get("item-record", {"key": "a9"})[2])["record"]["status"] == "completed", ids_)
    check("open-records: another session's items are not in it", recs(V)[1]["items"][0]["id"] == "a6" and len(recs(V)[1]["items"]) == 1 and recs("nobody-at-all")[1] == {"session": "nobody-at-all", "total": 0, "truncated": False, "unreadable": [], "items": []}, recs(V)[1])
    _rr = cr._raw_record      # the view skips a file that does not read, so the race (a file damaged after the view listed it) is made by the read itself
    cr._raw_record = lambda p: (None, "unreadable") if str(p).endswith("/4.json") else _rr(p)
    try: st, j = recs(U)
    finally: cr._raw_record = _rr
    check("open-records: an item whose file does not read when it is read is named in `unreadable`, left out of items, and the rest still answer", st == 200 and j["unreadable"] == ["a4"] and [x["id"] for x in j["items"]] == ["a1", "a2", "a3", "a7"] and j["total"] == 5, j)
    cr._raw_record = lambda p: (lambda r: ({**r[0], "status": "completed"}, "") if str(p).endswith("/2.json") and r[0] else r)(_rr(p))      # item 2 closes between the view's listing and the read of its file
    try: st, j = recs(U)
    finally: cr._raw_record = _rr
    check("open-records: an item that closed after the view listed it is left out and not counted in total, and the answer is not truncated for it", st == 200 and [x["id"] for x in j["items"]] == ["a1", "a3", "a4", "a7"] and j["total"] == 4 and j["truncated"] is False and j["unreadable"] == [], j)
    (T / "store/a/4.json").write_text(json.dumps({**raw(4), "status": "completed"}))
    check("open-records: an item closed on the file is dropped from the next answer and from its total, and the answer is not truncated for it", [x["id"] for x in recs(U)[1]["items"]] == ["a1", "a2", "a3", "a7"] and recs(U)[1]["total"] == 4 and recs(U)[1]["truncated"] is False, recs(U)[1]["total"])
    (T / "store/a/4.json").write_text(json.dumps({**raw(4), "status": "open"}))
    for bad in ("", "a\nb", "x" * 201):
        st, ct, b = cr._client_get("open-records", {"key": bad}); check(f"open-records refuses the key {bad[:6]!r}", st == 400, (st, b))
    _mx, _by = cr._RECORDS_MAX, cr._RECORDS_BYTES
    try:
        cr._RECORDS_MAX = 2; st, j = recs(U)
        check("open-records: past the cap the answer is cut, total says how many there are and truncated is true", st == 200 and len(j["items"]) == 2 and j["total"] == 5 and j["truncated"] is True and [x["id"] for x in j["items"]] == ["a1", "a2"], (len(j["items"]), j["total"], j["truncated"]))
        cr._RECORDS_MAX = _mx; cr._RECORDS_BYTES = 1; st, j = recs(U)
        check("open-records: past the byte bound the answer is cut too, and holds at least one record", st == 200 and len(j["items"]) == 1 and j["truncated"] is True, (len(j["items"]), j["truncated"]))
        cr._RECORDS_BYTES = _by; cr._RECORDS_MAX = 5; st, j = recs(U)
        check("open-records: exactly the cap is not truncated", st == 200 and len(j["items"]) == 5 and j["truncated"] is False, (len(j["items"]), j["truncated"]))
    finally: cr._RECORDS_MAX, cr._RECORDS_BYTES = _mx, _by

    AN = {"projects/alpha": [{"url": "https://github.com/o/r/pull/7", "items": ["a2"], "added": 1700000000.0, "by": "sparrow"}, {"url": "https://example.test/x", "items": None, "added": 1700000001.0, "by": "x"}], "projects/beta": []}
    (T / "store/anchors.json").write_text(json.dumps(AN)); st, ct, b = cr._client_get("anchors-record", {})
    check("anchors-record: the map exactly as the file has it", st == 200 and json.loads(b) == {"anchors": json.loads((T / "store/anchors.json").read_text()), "truncated": False} and json.loads(b)["anchors"] == AN, (st, b[:200]))
    (T / "store/anchors.json").unlink(); st, ct, b = cr._client_get("anchors-record", {}); check("anchors-record: no file is an empty map", st == 200 and json.loads(b) == {"anchors": {}, "truncated": False}, (st, b))
    (T / "store/anchors.json").write_text("{not json"); st, ct, b = cr._client_get("anchors-record", {}); check("anchors-record: a file that does not read is 503", st == 503, (st, b))
    (T / "store/anchors.json").write_text("[1]"); st, ct, b = cr._client_get("anchors-record", {}); check("anchors-record: a file that is no map is 503", st == 503, (st, b))
    (T / "store/anchors.json").write_text(json.dumps(AN)); cr._RECORDS_BYTES = 1
    try: st, ct, b = cr._client_get("anchors-record", {}); j = json.loads(b)
    finally: cr._RECORDS_BYTES = _by
    check("anchors-record: past the byte bound the later projects are left out and truncated is true", st == 200 and j["truncated"] is True and list(j["anchors"]) == ["projects/alpha"], b[:200])

    # projects-record: the project record alone, the value state-files carries as `projects`
    PR_ = {"schema": 1, "generated": "2030-01-01T00:00:00Z", "projects": {"p-e1": {"id": "p-e1", "key": "projects/alpha", "keeper": "sparrow", "agents": {}}}, "by_key": {"projects/alpha": "p-e1"}}
    (T / "state").mkdir(exist_ok=True); PRF_ = T / "state/projects.json"
    PRF_.write_text(json.dumps(PR_)); st, ct, b = cr._client_get("projects-record", {}); sf_ = json.loads(cr._client_get("state-files", {})[2])
    check("projects-record: the file as published, as 200 JSON", st == 200 and ct == "application/json" and json.loads(b) == PR_, (st, ct, b[:200]))
    check("projects-record: equal to what state-files carries under projects, and to no other part of it", json.loads(b) == sf_["projects"] and set(json.loads(b)) == set(PR_) and "fleet" not in json.loads(b) and "host" not in json.loads(b), (b[:200], str(sf_)[:200]))
    PRF_.write_text(json.dumps({**PR_, "generated": "2031-02-02T00:00:00Z"})); st, ct, b = cr._client_get("projects-record", {})
    check("projects-record: follows the file at each call, and still equals state-files", st == 200 and json.loads(b)["generated"] == "2031-02-02T00:00:00Z" and json.loads(b) == json.loads(cr._client_get("state-files", {})[2])["projects"], (st, b[:200]))
    PRF_.write_text("{not json"); st, ct, b = cr._client_get("projects-record", {}); check("projects-record: a file that does not read is 503, not an empty answer", st == 503 and ct.startswith("text/plain") and "Traceback" not in b and "project record" in b, (st, b))
    PRF_.write_text("[1]"); st, ct, b = cr._client_get("projects-record", {}); check("projects-record: a file that is no object is 503", st == 503, (st, b))
    PRF_.unlink(); st, ct, b = cr._client_get("projects-record", {}); check("projects-record: no file is 503, as state-files carries null for it", st == 503 and json.loads(cr._client_get("state-files", {})[2])["projects"] is None, (st, b))
    PRF_.write_text(json.dumps(PR_))

    # the anchors that name an item come with it (anchor_scope, the model's own reader): a project-wide anchor names no item
    (T / "store/anchors.json").write_text(json.dumps({**AN, "projects/beta": [{"url": "https://github.com/o/r/pull/7", "items": ["a2", "a1"], "added": 1700000005.0, "by": "x"}, {"url": "https://example.test/z", "items": ["a1"], "added": 1700000006.0, "by": "y"}]}))
    j = json.loads(cr._client_get("item-record", {"key": "a2"})[2]); a_ = j["anchors"]
    check("item-record: the anchors scoped to the item, each once with the page that holds it and every page, `scoped` not carried, the project-wide anchor left out",
          j["record"] == raw(2) and len(a_) == 1 and a_[0]["url"] == "https://github.com/o/r/pull/7" and a_[0]["page"] == "projects/alpha" and a_[0]["pages"] == ["projects/alpha", "projects/beta"] and sorted(a_[0]["items"]) == ["a1", "a2"] and "scoped" not in a_[0]
          and all(x["url"] != "https://example.test/x" for x in a_), a_)
    check("item-record: an item no anchor names has an empty list", json.loads(cr._client_get("item-record", {"key": "a3"})[2])["anchors"] == [])
    check("item-record: the anchors of another item are not in it", [x["url"] for x in json.loads(cr._client_get("item-record", {"key": "a1"})[2])["anchors"]] == ["https://github.com/o/r/pull/7", "https://example.test/z"], json.loads(cr._client_get("item-record", {"key": "a1"})[2])["anchors"])
    st, j = recs(U); by_ = {x["id"]: x["anchors"] for x in j["items"]}
    check("open-records: every row carries its own scoped anchors, as item-record gives them", st == 200 and all(by_[g] == json.loads(cr._client_get("item-record", {"key": g})[2])["anchors"] for g in by_) and len(by_["a2"]) == 1 and by_["a3"] == [], by_)
    (T / "store/anchors.json").write_text("{not json")
    st1, _c, b1 = cr._client_get("item-record", {"key": "a2"}); st2, _c, b2 = cr._client_get("open-records", {"key": U}); st3, _c, b3 = cr._client_get("item-record", {"key": "a999"})
    check("an anchors file that does not read is 503 for item-record and open-records (never an answer with the anchors left off); an item that does not exist is still 404", (st1, st2, st3) == (503, 503, 404) and "Traceback" not in b1 + b2, (st1, st2, st3, b1, b2))
    (T / "store/anchors.json").unlink()
    check("no anchors file: the reads answer with no anchors", json.loads(cr._client_get("item-record", {"key": "a2"})[2])["anchors"] == [] and recs(U)[0] == 200)
    (T / "store/anchors.json").write_text(json.dumps(AN))

    with TestClient(app) as c:
        for path, prm in (("item-record", {"key": "a2"}), ("open-records", {"key": U}), ("anchors-record", {}), ("projects-record", {})):
            r = c.get(f"/client/{path}", params=prm); check(f"http: {path} without a token → 401", r.status_code == 401, r.status_code)
            r = c.get(f"/client/{path}", params=prm, headers={"Authorization": "Bearer " + "y" * 43}); check(f"http: {path} with an unknown token → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/item-record", params={"key": "a2"}, headers=H); check("http: item-record with the machine's token is the read's own answer", r.status_code == 200 and r.text == cr._client_item_record("a2")[2] and r.headers["cache-control"] == "no-store", r.text[:150])
        r = c.get("/client/item-record", params={"key": "zz9; x"}, headers=H); check("http: item-record with a bad id → 400", r.status_code == 400, (r.status_code, r.text[:100]))
        r = c.get("/client/item-record", params={"key": "a999"}, headers=H); check("http: item-record with an unknown id → 404", r.status_code == 404, r.status_code)
        r = c.get("/client/open-records", params={"key": U}, headers=H); check("http: open-records with the machine's token", r.status_code == 200 and [x["id"] for x in r.json()["items"]] == ["a1", "a2", "a3", "a4", "a7"], r.text[:150])
        r = c.get("/client/anchors-record", headers=H); check("http: anchors-record with the machine's token", r.status_code == 200 and r.json()["anchors"] == AN, r.text[:150])
        r = c.get("/client/projects-record", headers=H); check("http: projects-record with the machine's token is the read's own answer, and the value state-files carries", r.status_code == 200 and r.text == cr._client_projects_record()[2] and r.json() == PR_ == c.get("/client/state-files", headers=H).json()["projects"] and r.headers["cache-control"] == "no-store", r.text[:150])
        r = c.get("/client/open-records", params={"key": U}, headers=H); check("http: open-records is the read's own answer", r.text == cr._client_open_records(U)[2], r.text[:150])
        _real_or = cr._client_open_records; _loop_seen = []
        def _probe_or(k):
            try: asyncio.get_running_loop(); _loop_seen.append(True)
            except RuntimeError: _loop_seen.append(False)
            return _real_or(k)
        cr._client_open_records = _probe_or
        try:
            r = c.get("/client/open-records", params={"key": U}, headers=H)
        finally:
            cr._client_open_records = _real_or
        check("http: open-records is answered from the threadpool, not the event loop (it scans the board)", r.status_code == 200 and _loop_seen == [False], (r.status_code, _loop_seen))
        _real_an = cr._ask_named._client_asks_named; _loop_seen = []
        def _probe_an(k, since):
            try: asyncio.get_running_loop(); _loop_seen.append(True)
            except RuntimeError: _loop_seen.append(False)
            return _real_an(k, since)
        cr._ask_named._client_asks_named = _probe_an
        try:
            r = c.get("/client/asks-named", params={"key": U, "since": "1"}, headers=H)
        finally:
            cr._ask_named._client_asks_named = _real_an
        check("http: asks-named is answered from the threadpool, not the event loop (it reads the message log and the board)", r.status_code == 200 and _loop_seen == [False], (r.status_code, r.text[:100], _loop_seen))
        r = c.get("/client/open-records", params={"key": "a\nb"}, headers=H); check("http: open-records with a bad key → 400", r.status_code == 400, (r.status_code, r.text[:100]))
        r = c.get("/client/item-record", headers=H); check("http: item-record with no key → 400", r.status_code == 400, (r.status_code, r.text[:100]))
        other = open(client.mint("box-other")).read().strip()
        r = c.get("/client/item-record", params={"key": "a2"}, headers={"Authorization": "Bearer " + other}); check("http: any machine's token reads, as for the other client reads (the gate is the machine token and nothing else)", r.status_code == 200 and r.json()["id"] == "a2", r.status_code)
        client.revoke("box-other")
        for what_, hd_x in (("a revoked token", {"Authorization": "Bearer " + other}), ("a Basic credential", {"Authorization": "Basic " + tok}), ("the token as a bare Authorization value", {"Authorization": tok}), ("the token in a cookie", {"Cookie": "token=" + tok, "stackshot_token": tok}), ("a short bearer", {"Authorization": "Bearer short"})):
            for path, prm in (("item-record", {"key": "a2"}), ("open-records", {"key": U}), ("anchors-record", {}), ("projects-record", {})):
                r = c.get(f"/client/{path}", params=prm, headers=hd_x); check(f"http: {path} with {what_} → 401, no record in the answer", r.status_code == 401 and "subject" not in r.text, (r.status_code, r.text[:80]))
        for path, prm in (("item-record", {"key": "a2", "token": tok}), ("open-records", {"key": U, "token": tok}), ("anchors-record", {"token": tok}), ("projects-record", {"token": tok})):
            r = c.get(f"/client/{path}", params=prm); check(f"http: {path} with the token in the query string → 401", r.status_code == 401, r.status_code)
        r = c.get("/client/nothing", headers=H); check("http: the 404 list names the new reads", all(w in r.text for w in ("item-record?key=<item id>", "open-records?key=<session>", "anchors-record", "projects-record")), r.text[:200])
    _usage_text = open(client.__file__, encoding="utf-8").read().split('"""', 2)[1]       # the usage text is the module's opening string, read as text
    _new_lines = _usage_text.split("client.py get item-record")[1].split("client.py get inbox-holds")[0]
    check("client.py knows the four reads and its usage text names them, with no machine and no session manager in the new lines", all(w in client.READS for w in ("item-record", "open-records", "anchors-record", "projects-record"))
          and all(f"client.py get {w}" in _usage_text for w in ("item-record", "open-records", "anchors-record", "projects-record")) and "sala" not in _new_lines.casefold() and "hp-" not in _new_lines)
    (T / "store/anchors.json").write_text("{}")
    for n in (9,): (T / f"store/a/{n}.json").unlink()        # the later sections count the fixture's items

    # ---- 8. owner_name follows an owner change: update(owner=…) without owner_name left the old owner's
    # name on the item, and the old owner's board check (items?key=, by owner or owner_name) kept asking about what it handed over
    W = "cccccccc-3333-4333-8333-333333333333"                  # a uuid the fleet does not know
    md = lambda n: json.loads((T / f"store/a/{n}.json").read_text())["metadata"]
    item(8, V, meta={"owner_name": "home-other"}); item(9, V, meta={"owner_name": "home-other"})
    _update_svc._update("a8", owner=U, sender="home-other"); m = md(8)
    check("owner change: to a known session's uuid without owner_name, owner_name becomes the name the fleet knows", m["owner"] == U and m["owner_name"] == "sparrow", m)
    st, ct, b = client_reads_svc._client_get("items", {"key": V}); st2, ct2, b2 = client_reads_svc._client_get("items", {"key": "home-other"})
    check("owner change: the board check follows the mover, not the creator: the session that moves the item still lists it, by uuid or by name", "a8" in gids(b) and "a8" in gids(b2), (b[:300], b2[:300]))
    st, ct, b = client_reads_svc._client_get("items", {"key": U}); check("owner change: …and the session named as creator now lists nothing for it", "a8" not in gids(b), b[:300])
    _update_svc._update("a8", owner="home-other", sender="sparrow"); m = md(8)
    check("owner change: to a pane name, stored as its uuid and the name as owner_name", m["owner"] == V and m["owner_name"] == "home-other", m)
    _ho_was = dict(_cfgm.CFG.get("model") or {}); _cfgm.CFG["model"] = {**_ho_was, "handoff": False}      # this one check needs a session no pane of which exists: the hand-off's send-time guard (handoff suite) would refuse it
    _update_svc._update("a8", owner=W, sender="home-other"); m = md(8)
    check("owner change: to a uuid the fleet does not know, the old owner_name goes", m["owner"] == W and "owner_name" not in m, m)
    _update_svc._update("a9", owner="home-retired", sender="home-other"); m = md(9)
    _cfgm.CFG["model"] = _ho_was
    check("owner change: to a name no live session carries, stored as given and as owner_name", m["owner"] == "home-retired" and m["owner_name"] == "home-retired", m)
    _update_svc._update("a8", owner=U, owner_name="X", sender="home-other"); m = md(8)
    check("owner change with owner_name: the given name is kept", m["owner"] == U and m["owner_name"] == "X", m)
    _update_svc._update("a7", owner="cse_0123456789abcdef", sender="sparrow"); m = md(7)
    check("owner re-passed unchanged without owner_name: the name it carries stays (a chat's name is only its owner_name)", m["owner_name"] == "sparrow", m)

    # the dispatcher of /client/{what} lives in web/routes/client_api.py: the `what` -> handlers table of its branches is pinned, as it stood when it left server.py
    import ast, inspect
    def _what_table(fn):
        tree = ast.parse(inspect.getsource(fn)).body[0]
        def whats(t):
            if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "what":
                c = t.comparators[0]
                return [c.value] if isinstance(t.ops[0], ast.Eq) else [e.value for e in c.elts] if isinstance(t.ops[0], ast.In) else []
            return []
        def calls(nodes):
            out = []
            for n in nodes:
                for c in ast.walk(n):
                    if isinstance(c, ast.Call):
                        f = c.func
                        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id.startswith("_"): out.append(f"{f.value.id}.{f.attr}")
                        elif isinstance(f, ast.Name) and f.id.startswith("_"): out.append(f.id)
            return list(dict.fromkeys(out))
        return [" | ".join(whats(st.test)) + " -> " + ", ".join(calls(st.body)) for st in tree.body if isinstance(st, ast.If) and whats(st.test)]
    _WHAT_TABLE = [
        "recycled -> _recycle_svc._recycled",
        "recycle-due -> _recycle_svc._recycle_due",
        "released -> _relsvc.released",
        "event -> _ew.event_from_report, _evwaits.evwait_report, _ew.arrival, _gh.shown",
        "sweep-released -> _relsvc.sweep_released",
        "sweep-step-proof -> _proofs.sweep_proofs",
        "page-debt -> _page_debt.enabled, _pdsvc.page_debt_pass, _page_debt.mode",
        "orphan-handover -> _handoff.orphan_handover",
        "backfill-contact -> _contacts._contact_backfill",
        "repoint -> _repoint.repoint",
        "message -> _relsvc._release_green, _messaging.count_client_call, _messaging.begin_client_call, _messaging._message, _messaging.end_client_call",
        "handover -> _agent_names._name_on_handover",
        "project-agent -> _project_agent",
        "project-agent-mandate -> _project_agent_mandate",
        "project-agent-rename -> _project_agent_rename",
        "project-agent-retire -> _project_agent_retire",
        "project -> _new_project",
        "project-list -> _project_list",
        "question -> _question_svc._question",
        "terminal-prompt -> _terminal_prompt_svc._terminal_prompt",
        "job-gap -> _job_gap._jobgap_post",
        "catch -> _catches._catch_post",
        "anchor-add -> _client_anchor_add",
        "item-open -> _item_open._itemopen_post",
        "item-sync -> _item_sync._itemsync_post",
        "job-failed -> _job_alert._jobalert_failed_post",
        "job-ok -> _job_alert._jobalert_ok_post",
        "cap-words -> _owner_words._script_sender, _norm_id, _update_svc._update, _owner_words._record_cap_words, _gh.shown",
        "rebullet -> _owner_words._rebullet_write",
        "state -> _owner_words._state_write",
        "migrate -> _migrations.migration_gate, _migrations.migrate_write",
        "register -> _clients.register",
        "setup-result -> _clients.setup_result",
        "seen -> _clients.seen",
        "ack -> _inbox.peek, _inbox.ack, _handoff.handoff_acked",
        "held -> _clients.sessions_on, _held.ack, _held.mark_client, _held.lease",
        "inbox-hold -> _inbox_holds.api_hold",
        "inbox-release -> _inbox_holds.api_release",
        "drain -> _clients.sessions_on, _clients.seen, _clients.register, _inbox.take",
        "agent-state -> _agent_state_svc.post",
        "machines -> _machines_svc.post",
    ]
    check("client_post: the `what` -> handlers table of the dispatcher is the one it had in server.py (%d branches)" % len(_WHAT_TABLE), _what_table(_rt_client._client_post) == _WHAT_TABLE, _what_table(_rt_client._client_post))
    check("client_post: an unknown `what` is a 404 naming the writes there are, and the dispatcher is no name of server", _rt_client._client_post("home", "no-such-write", {})[0] == 404 and not hasattr(server, "_client_post"), _rt_client._client_post("home", "no-such-write", {}))

    # ---- 6. $STACKSHOT_CLIENT_PASS: a caller's pass goes as the Bearer of a get and a post in place of the machine token (docs/client-contract.md, *A caller's own key*)
    import http.server, io as _pio, threading, contextlib
    client.urllib.request.urlopen = _real_urlopen
    _seen = []                                           # (method, path, Authorization header) of every request the stub got
    class _Stub(http.server.BaseHTTPRequestHandler):
        def _answer(self):
            auth = self.headers.get("Authorization", ""); _seen.append((self.command, self.path, auth))
            n = int(self.headers.get("Content-Length") or 0)
            if n: self.rfile.read(n)
            if auth == "Bearer tok-from-file-e0": code, body = 200, b'{"ok": true, "machine": "box-e0"}'
            else: code, body = 401, json.dumps({"error": "unauthorized: " + auth}).encode()   # a server that echoes the header: the client must still not print the pass
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        do_GET = do_POST = _answer
        def log_message(self, *a): pass
    _srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stub); _thr = threading.Thread(target=_srv.serve_forever, daemon=True); _thr.start()
    _env0 = {k: os.environ.get(k) for k in ("STACKSHOT_URL", client.PASS_ENV)}; _tokfile0 = pathlib.Path(client.TOKEN)
    try:
        os.environ["STACKSHOT_URL"] = f"http://127.0.0.1:{_srv.server_address[1]}"
        _tokfile0.parent.mkdir(parents=True, exist_ok=True); _tokfile0.write_text("tok-from-file-e0\n")
        def _cli(*argv):
            out, err = _pio.StringIO(), _pio.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = client.main(["client.py", *argv])
            return rc, out.getvalue(), err.getvalue()
        PASSV = "ssp_e1"
        os.environ.pop(client.PASS_ENV, None); _seen.clear()
        st, body = client.get("whoami"); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"})
        check("pass: unset, a get and a post send the machine token from the file", st == 200 and sp == 200 and [a for _, _, a in _seen] == ["Bearer tok-from-file-e0"] * 2, (st, sp, _seen))
        for label, val in (("empty", ""), ("blanks only", "   ")):
            os.environ[client.PASS_ENV] = val; _seen.clear()
            st, body = client.get("whoami"); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"})
            check(f"pass: {label}, the token file value is sent, as when unset", st == 200 and sp == 200 and [a for _, _, a in _seen] == ["Bearer tok-from-file-e0"] * 2, (st, sp, _seen))
        os.environ[client.PASS_ENV] = PASSV; _seen.clear()
        st, body = client.get("whoami"); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"})
        check("pass: set, a get sends it as the Bearer in place of the token file", _seen[:1] == [("GET", "/client/whoami", "Bearer " + PASSV)], _seen)
        check("pass: set, a post sends it as the Bearer in place of the token file", _seen[1:] == [("POST", "/client/project-agent-retire", "Bearer " + PASSV)], _seen)
        os.environ[client.PASS_ENV] = "  " + PASSV + " \n"; _seen.clear(); client.get("whoami")
        check("pass: blanks around the value are dropped, as around a token read from the file", [a for _, _, a in _seen] == ["Bearer " + PASSV], _seen)
        os.environ[client.PASS_ENV] = PASSV; os.remove(_tokfile0); _seen.clear()
        st, body = client.get("whoami"); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"})
        check("pass: set, the token file is not read (a box with no token still sends the pass)", st == 401 and sp == 401 and "no token" not in body and [a for _, _, a in _seen] == ["Bearer " + PASSV] * 2, (st, sp, body, _seen))
        _tokfile0.write_text("tok-from-file-e0\n")
        # the pass never reaches a text the client prints or returns, on a 401 from a server that even echoes the header
        for val in (PASSV, "not-a-pass-e2"):                                   # a value that does not start with ssp_ is sent as it is and is kept out of every text as well
            os.environ[client.PASS_ENV] = val; _seen.clear()
            st, body = client.get("whoami"); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"})
            rc1, o1, e1 = _cli("get", "whoami"); rc2, o2, e2 = _cli("post", "project-agent-retire", "alpha", "x", "--sender", "k")
            check(f"pass: {val[:4]}... is sent as it is, and a 401 comes back as 401", st == 401 and sp == 401 and all(a == "Bearer " + val for _, _, a in _seen) and len(_seen) == 4, (st, sp, _seen))
            check(f"pass: {val[:4]}... is in no returned text, stdout or stderr of a 401 (get and post, API and command line)",
                  val not in body and val not in json.dumps(bp) and all(val not in t for t in (o1, e1, o2, e2)) and rc1 != 0 and rc2 != 0 and "<pass>" in body, (body, bp, o1, e1, o2, e2))
        # a value the transport refuses (a line break inside it) and a server that is not there: no text repeats it
        os.environ[client.PASS_ENV] = "ssp_e3\nX-Extra: e3"; _seen.clear()
        st, body = client.get("whoami"); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"})
        rc1, o1, e1 = _cli("get", "whoami"); rc2, o2, e2 = _cli("post", "project-agent-retire", "alpha", "x")
        check("pass: a value the transport refuses is not sent, answers [0], and no text repeats any part of it",
              st == 0 and sp == 0 and not _seen and all("e3" not in str(t) and "ssp_" not in str(t) for t in (body, bp, o1, e1, o2, e2)) and rc1 != 0 and rc2 != 0 and "withheld" in body, (st, sp, body, bp, o1, e1, o2, e2))
        os.environ[client.PASS_ENV] = PASSV; os.environ["STACKSHOT_URL"] = "http://127.0.0.1:9"                 # nothing listens: not reached
        st, body = client.get("whoami", timeout=3); sp, bp = client.post("project-agent-retire", {"project": "alpha", "name": "x"}, timeout=3)
        check("pass: a server that is not reached answers [0] and its text does not repeat the pass", st == 0 and sp == 0 and PASSV not in body and PASSV not in str(bp), (st, sp, body, bp))
    finally:
        _srv.shutdown(); _srv.server_close(); _thr.join(5)
        for k, v in _env0.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        with contextlib.suppress(FileNotFoundError): os.remove(_tokfile0)

    # ---- 7. `post agent-state --file <path>`: the fleet's session manager pushes its snapshot with the script client. A stub server stands for the route (this branch does not need the route's code);
    #         it answers as the route's contract says: 200 {"ok": true, "agents": N}, 400 with a one-line reason, 401 as plain text.
    _got = []                                            # (path, Authorization, Content-Type, body bytes) of every request the stub got
    _mode = {"v": "ok"}
    class _AgentStub(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n) if n else b""
            _got.append((self.path, self.headers.get("Authorization", ""), self.headers.get("Content-Type", ""), raw))
            if _mode["v"] == "ok":
                try: cnt = len(json.loads(raw)["agents"])
                except Exception: cnt = 0
                code, body, ctype = 200, json.dumps({"ok": True, "agents": cnt}).encode(), "application/json"
            elif _mode["v"] == "mok":
                try: cnt = len(json.loads(raw)["machines"])
                except Exception: cnt = 0
                code, body, ctype = 200, json.dumps({"ok": True, "machines": cnt}).encode(), "application/json"
            elif _mode["v"] == "kept": code, body, ctype = 200, json.dumps({"ok": True, "kept": "newer"}).encode(), "application/json"
            elif _mode["v"] == "dropped": code, body, ctype = 200, json.dumps({"ok": True, "machines": 2, "dropped": ["machines[1].online"]}).encode(), "application/json"
            elif _mode["v"] == "big": code, body, ctype = 413, json.dumps({"error": "the body is 1000001 bytes, over the 1000000-byte limit"}).encode(), "application/json"
            elif _mode["v"] == "bad": code, body, ctype = 400, json.dumps({"error": "schema must be 1"}).encode(), "application/json"
            elif _mode["v"] == "multi": code, body, ctype = 400, json.dumps({"error": "agent 'x' is no object\nand a second line"}).encode(), "application/json"
            elif _mode["v"] == "echo400": code, body, ctype = 400, json.dumps({"error": "bad token " + self.headers.get("Authorization", "").split()[-1]}).encode(), "application/json"
            elif _mode["v"] == "echotext": code, body, ctype = 502, ("upstream said: " + self.headers.get("Authorization", "")).encode(), "text/plain"
            elif _mode["v"] == "noerror": code, body, ctype = 404, json.dumps({"detail": "x" * 250 + "TAIL-" + "y" * 300, "n": 1}).encode(), "application/json"
            elif _mode["v"] == "list": code, body, ctype = 404, b"[1, 2,\n 3]", "application/json"
            else: code, body, ctype = 401, b"unauthorized: a machine token is required (Authorization: Bearer ...)", "text/plain"
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
    _asrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AgentStub); _athr = threading.Thread(target=_asrv.serve_forever, daemon=True); _athr.start()
    _aenv = {k: os.environ.get(k) for k in ("STACKSHOT_URL", client.PASS_ENV)}; _atok = pathlib.Path(client.TOKEN); _adir = T / "agent-state-files"; _adir.mkdir(exist_ok=True)
    try:
        os.environ["STACKSHOT_URL"] = f"http://127.0.0.1:{_asrv.server_address[1]}"; os.environ.pop(client.PASS_ENV, None)
        _atok.parent.mkdir(parents=True, exist_ok=True); _atok.write_text("tok-agent-e7\n")
        def _acli(*argv):
            out, err = _pio.StringIO(), _pio.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = client.main(["client.py", *argv])
            return rc, out.getvalue(), err.getvalue()
        def _afile(name, data):
            p = _adir / name; p.write_bytes(data); return str(p)
        def _one_line(text): return text.endswith("\n") and text.count("\n") == 1
        # a body with spacing and key order a re-encode would change, and characters outside ASCII (escapes only in this source)
        _body = ('{"schema" : 1,\n  "written":1700000000, "agents":{"caf\u00e9-main":{"state":"busy","why":"caf\u00e9 \u2013 \u4e2d\u6587 \U0001F600","since":1,"pane":"turn","read":true,"subagents":[]},\n'
                 '  "b":{"state":"idle","since":2,"why":"","pane":"idle","read":true}}}\n').encode("utf-8")
        _mode["v"] = "ok"; _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", _afile("good.json", _body))
        check("agent-state: a good file is POSTed to /client/agent-state with the machine token and its bytes unchanged",
              rc == 0 and len(_got) == 1 and _got[0][0] == "/client/agent-state" and _got[0][1] == "Bearer tok-agent-e7" and _got[0][2] == "application/json" and _got[0][3] == _body, (rc, out, err, _got[:1]))
        check("agent-state: the server's 200 JSON is printed on stdout, nothing on stderr, exit 0", json.loads(out) == {"ok": True, "agents": 2} and out.count("\n") == 1 and err == "", (out, err))
        _blob = b"\xff\xfe\x00 not json, not utf-8 \r\n \x80\x81 {"; _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", _afile("blob.bin", _blob))
        check("agent-state: the file is never parsed or decoded: a body that is no JSON and no UTF-8 reaches the server byte for byte", rc == 0 and [g[3] for g in _got] == [_blob], (rc, err, _got))
        _full = b"x" * 1_000_000; _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", _afile("full.json", _full))
        check("agent-state: a file of exactly 1,000,000 bytes is sent whole", rc == 0 and [g[3] for g in _got] == [_full], (rc, err, [len(g[3]) for g in _got]))
        _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", _afile("over.json", b"x" * 1_000_001))
        check("agent-state: a file of 1,000,001 bytes is refused with one line on stderr and exit 1, and nothing is sent", rc == 1 and not _got and out == "" and _one_line(err) and "limit" in err, (rc, out, err, _got))
        _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "no-such-file.json"))
        check("agent-state: a missing file is refused with one line on stderr and exit 1, and nothing is sent", rc == 1 and not _got and out == "" and _one_line(err) and "no-such-file" in err, (rc, out, err, _got))
        _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", str(_adir))
        check("agent-state: a path that cannot be read as a file (a folder) is refused the same way, nothing sent", rc == 1 and not _got and out == "" and _one_line(err), (rc, out, err, _got))
        _locked = _afile("locked.json", _body); os.chmod(_locked, 0)
        _got.clear()
        if os.access(_locked, os.R_OK): check("agent-state: (running as a user that reads a mode 000 file: that check is skipped)", True)
        else:
            rc, out, err = _acli("post", "agent-state", "--file", _locked)
            check("agent-state: an unreadable file (mode 000) is refused with one line on stderr and exit 1, nothing sent", rc == 1 and not _got and out == "" and _one_line(err), (rc, out, err, _got))
        for label, argv in (("no --file", ["post", "agent-state"]), ("--file with no value", ["post", "agent-state", "--file"]), ("a stray argument", ["post", "agent-state", "--file", str(_adir / "good.json"), "extra"]), ("an unknown option", ["post", "agent-state", "--path", str(_adir / "good.json")])):
            _got.clear(); rc, out, err = _acli(*argv)
            check(f"agent-state: {label} is a usage error on stderr, exit 1, nothing sent", rc == 1 and not _got and out == "" and "usage: client.py post agent-state --file <path>" in err, (rc, out, err, _got))
        _got.clear(); rc, out, err = _acli("post", "no-such-what", "--file", str(_adir / "good.json"))
        check("agent-state: any other <what> after `post` is a usage error (the module's usage, exit 1) and nothing is sent", rc == 1 and not _got and "post agent-state --file <path>" in out, (rc, out, err, _got))
        _mode["v"] = "bad"; _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "good.json"))
        check("agent-state: a 400 prints the server's reason as one line on stderr, nothing on stdout, exit 1", rc == 1 and len(_got) == 1 and out == "" and _one_line(err) and "schema must be 1" in err and "400" in err, (rc, out, err))
        _mode["v"] = "multi"; rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "good.json"))
        check("agent-state: a reason of several lines is still one line on stderr", rc == 1 and out == "" and _one_line(err) and "no object" in err and "second line" in err, (rc, out, err))
        _mode["v"] = "unauth"; _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "good.json"))
        check("agent-state: a 401 (plain text) is exit 1 with its reason on stderr and nothing on stdout", rc == 1 and len(_got) == 1 and out == "" and _one_line(err) and "401" in err and "machine token" in err, (rc, out, err))
        # -- what the file is: only a regular file is read (a pipe with no writer must not hang the client); a link to one is read
        import signal as _sig
        class _Hung(BaseException): pass
        def _guarded(*argv, secs=8):
            """Run the client with an alarm: a call that blocks is cut off (and reported) instead of hanging the suite."""
            def _fire(*a): raise _Hung()
            old = _sig.signal(_sig.SIGALRM, _fire); _sig.alarm(secs)
            try: return (*_acli(*argv), False)
            except _Hung: return 1, "", "", True
            finally: _sig.alarm(0); _sig.signal(_sig.SIGALRM, old)
        _fifo = str(_adir / "pipe.json"); os.mkfifo(_fifo)
        try:
            _got.clear(); rc, out, err, hung = _guarded("post", "agent-state", "--file", _fifo)
            check("agent-state: a named pipe with no writer is refused at once (not a regular file), one line, exit 1, nothing sent", not hung and rc == 1 and not _got and out == "" and _one_line(err) and "not a regular file" in err, (hung, rc, out, err, _got))
        finally: os.remove(_fifo)
        _got.clear(); rc, out, err, hung = _guarded("post", "agent-state", "--file", str(_adir))
        check("agent-state: a folder is refused as not a regular file, one line, nothing sent", not hung and rc == 1 and not _got and out == "" and _one_line(err) and "not a regular file" in err, (rc, out, err, _got))
        if os.path.exists("/dev/zero"):
            _got.clear(); rc, out, err, hung = _guarded("post", "agent-state", "--file", "/dev/zero")
            check("agent-state: a device (/dev/zero) is refused as not a regular file, one line, nothing sent", not hung and rc == 1 and not _got and out == "" and _one_line(err) and "not a regular file" in err, (rc, out, err, _got))
        _mode["v"] = "ok"; _lnk = _adir / "link.json"; os.symlink(str(_adir / "good.json"), _lnk); _got.clear()
        rc, out, err, hung = _guarded("post", "agent-state", "--file", str(_lnk))
        check("agent-state: a link to a regular file is read and sent as the file's own bytes", rc == 0 and [g[3] for g in _got] == [_body] and err == "", (rc, out, err, _got))
        # -- one line whatever the path holds: control characters collapse, the token is never echoed
        for label, name in (("a newline", "a\nb.json"), ("an escape and a tab", "a\x1b[31m\tb.json"), ("a carriage return and a NUL-free bell", "a\r\x07b.json")):
            _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", str(_adir / name))
            check(f"agent-state: a missing path with {label} in it still gives one line on stderr, exit 1, nothing sent", rc == 1 and not _got and out == "" and _one_line(err) and not any(c in err[:-1] for c in "\r\x07\x1b\t"), (rc, out, err, _got))
        _dnl = _adir / "dir\nwith newline"; _dnl.mkdir(); _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", str(_dnl))
        check("agent-state: a folder with a newline in its name is refused in one line", rc == 1 and not _got and _one_line(err) and "not a regular file" in err, (rc, out, err, _got))
        # -- an empty --file value is a usage error, like a missing one
        for label, val in (("empty", ""), ("blank", "  ")):
            _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", val)
            check(f"agent-state: a {label} --file value is a usage error on stderr, exit 1, nothing sent", rc == 1 and not _got and out == "" and "usage: client.py post agent-state --file <path>" in err, (rc, out, err, _got))
        # -- the machine token is never printed: not from a server text that echoes it, not from a path that holds it
        _good = str(_adir / "good.json")
        for mode, code in (("echo400", "400"), ("echotext", "502")):
            _mode["v"] = mode; _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", _good)
            check(f"agent-state: a {code} answer that echoes the machine token never lets it reach stderr or stdout", rc == 1 and len(_got) == 1 and _one_line(err) and code in err and "tok-agent-e7" not in err + out, (rc, out, err))
        _mode["v"] = "ok"; _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "gone-tok-agent-e7.json"))
        check("agent-state: a not-readable path that holds the machine token is refused without printing the token", rc == 1 and not _got and _one_line(err) and "gone-" in err and "tok-agent-e7" not in err + out, (rc, out, err))
        # -- a non-200 answer with no `error` key: the status and the start of the body, never `None`
        _mode["v"] = "noerror"; _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", _good)
        check("agent-state: a 404 JSON answer with no `error` prints the status and the first 200 characters of the body on one line", rc == 1 and out == "" and _one_line(err) and "[404]" in err and "None" not in err and "detail" in err and "TAIL-" not in err and len(err) < 400, (rc, out, err))
        _mode["v"] = "list"; _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", _good)
        check("agent-state: a 404 answer that is a JSON list prints its text on one line", rc == 1 and _one_line(err) and "[404]" in err and "[1, 2, 3]" in err and "None" not in err, (rc, out, err))
        _mode["v"] = "ok"; os.remove(_atok); _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "good.json"))
        check("agent-state: with no token on the machine nothing is sent, one line on stderr, exit 1", rc == 1 and not _got and out == "" and _one_line(err) and "no token" in err, (rc, out, err, _got))
        _atok.write_text("tok-agent-e7\n")
        _dead = socket.socket(); _dead.bind(("127.0.0.1", 0)); _deadport = _dead.getsockname()[1]; _dead.close()      # a port nothing listens on
        os.environ["STACKSHOT_URL"] = f"http://127.0.0.1:{_deadport}"; _got.clear()
        rc, out, err = _acli("post", "agent-state", "--file", str(_adir / "good.json"))
        check("agent-state: a connection refused is one line on stderr, nothing on stdout, exit 1", rc == 1 and not _got and out == "" and _one_line(err) and "[0]" in err, (rc, out, err))
        os.environ["STACKSHOT_URL"] = f"http://127.0.0.1:{_asrv.server_address[1]}"; _got.clear()
        _run = subprocess.run([sys.executable, client.__file__, "post", "agent-state", "--file", str(_adir / "good.json")], capture_output=True, text=True, timeout=60, env=dict(os.environ))
        check("agent-state: run as a script (python3 stackshot/fleet/client.py post agent-state --file <path>) it posts the same bytes, prints the JSON and exits 0",
              _run.returncode == 0 and json.loads(_run.stdout) == {"ok": True, "agents": 2} and [g[3] for g in _got] == [_body], (_run.returncode, _run.stdout, _run.stderr, _got))

        # ---- 8. `post machines --file <path>`: the fleet manager posts its machine list with the script client (the same stub; the route's own checks are in tests/machines_list_scenario.py)
        _mbody = ('{"schema" : 1,\n "written":1700000000, "machines":[{"name":"caf\u00e9-one","retired":false},\n {"name":"two","retired":true,"roles":["sala-host"]}], "not_read":[]}\n').encode("utf-8")
        _mode["v"] = "mok"; _got.clear()
        rc, out, err = _acli("post", "machines", "--file", _afile("machines.json", _mbody))
        check("machines: a good file is POSTed to /client/machines with the machine token and its bytes unchanged",
              rc == 0 and len(_got) == 1 and _got[0][0] == "/client/machines" and _got[0][1] == "Bearer tok-agent-e7" and _got[0][2] == "application/json" and _got[0][3] == _mbody, (rc, out, err, _got[:1]))
        check("machines: the server's 200 JSON is printed on stdout, nothing on stderr, exit 0", json.loads(out) == {"ok": True, "machines": 2} and out.count("\n") == 1 and err == "", (out, err))
        _mode["v"] = "kept"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", _afile("machines.json", _mbody))
        check("machines: an answer {kept: newer} (200, not stored) is printed as given, says one line `kept: the server holds a newer list` on stderr and still exits 0",
              rc == 0 and json.loads(out) == {"ok": True, "kept": "newer"} and err == "kept: the server holds a newer list\n", (rc, out, err))
        _mode["v"] = "dropped"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", _afile("machines.json", _mbody))
        check("machines: an answer with a `dropped` list is printed whole on stdout and says nothing on stderr, exit 0; the usage text says so", rc == 0 and json.loads(out) == {"ok": True, "machines": 2, "dropped": ["machines[1].online"]} and err == ""
              and "dropped" in client.MACHINES_USAGE and "stdout only" in client.MACHINES_USAGE, (rc, out, err))
        _mode["v"] = "mok"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", _afile("machines.json", _mbody))
        check("machines: a stored list (no `kept`) says nothing on stderr", rc == 0 and err == "", (rc, err))
        _got.clear(); rc, out, err = _acli("post", "machines", "--file", _afile("machines-blob.bin", _blob))
        check("machines: the file is never parsed or decoded: a body that is no JSON and no UTF-8 reaches the server byte for byte", rc == 0 and [g[3] for g in _got] == [_blob], (rc, err, _got))
        _got.clear(); rc, out, err = _acli("post", "machines", "--file", _afile("machines-full.json", _full))
        check("machines: a file of exactly 1,000,000 bytes is sent whole", rc == 0 and [g[3] for g in _got] == [_full], (rc, err, [len(g[3]) for g in _got]))
        check("machines: the client's body limit is named MACHINES_BODY_MAX (1,000,000, the server's) and the old name is gone", client.MACHINES_BODY_MAX == 1_000_000 and not hasattr(client, "MACHINES_MAX"), (getattr(client, "MACHINES_BODY_MAX", None), hasattr(client, "MACHINES_MAX")))
        _got.clear(); rc, out, err = _acli("post", "machines", "--file", _afile("machines-over.json", b"x" * 1_000_001))
        check("machines: a file of 1,000,001 bytes is refused before sending: one line on stderr, exit 1, nothing sent", rc == 1 and not _got and out == "" and _one_line(err) and "limit" in err and "machine list" in err, (rc, out, err, _got))
        _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "no-such-machines.json"))
        check("machines: a missing file is refused with one line on stderr and exit 1, and nothing is sent", rc == 1 and not _got and out == "" and _one_line(err) and "no-such-machines" in err, (rc, out, err, _got))
        _got.clear(); rc, out, err, hung = _guarded("post", "machines", "--file", str(_adir))
        check("machines: a folder is refused as not a regular file, one line, nothing sent", not hung and rc == 1 and not _got and out == "" and _one_line(err) and "not a regular file" in err, (rc, out, err, _got))
        for label, argv in (("no --file", ["post", "machines"]), ("--file with no value", ["post", "machines", "--file"]), ("an empty --file value", ["post", "machines", "--file", ""]), ("a stray argument", ["post", "machines", "--file", str(_adir / "machines.json"), "extra"]),
                            ("an unknown option", ["post", "machines", "--path", str(_adir / "machines.json")]), ("a bare - and more", ["post", "machines", "-", "extra"])):
            _got.clear(); rc, out, err = _acli(*argv)
            check(f"machines: {label} is a usage error on stderr, exit 1, nothing sent", rc == 1 and not _got and out == "" and "usage: client.py post machines --file <path>" in err, (rc, out, err, _got))
        _mode["v"] = "bad"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "machines.json"))
        check("machines: a 400 prints the server's reason as one line on stderr, nothing on stdout, exit 1", rc == 1 and len(_got) == 1 and out == "" and _one_line(err) and "schema must be 1" in err and "400" in err, (rc, out, err))
        _mode["v"] = "big"; rc, out, err = _acli("post", "machines", "--file", str(_adir / "machines.json"))
        check("machines: a 413 prints the server's reason as one line on stderr, nothing on stdout, exit 1", rc == 1 and out == "" and _one_line(err) and "413" in err and "limit" in err, (rc, out, err))
        _mode["v"] = "unauth"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "machines.json"))
        check("machines: a 401 (plain text) is exit 1 with its reason on stderr and nothing on stdout", rc == 1 and len(_got) == 1 and out == "" and _one_line(err) and "401" in err and "machine token" in err, (rc, out, err))
        for mode, code in (("echo400", "400"), ("echotext", "502")):
            _mode["v"] = mode; _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "machines.json"))
            check(f"machines: a {code} answer that echoes the machine token never lets it reach stderr or stdout", rc == 1 and len(_got) == 1 and _one_line(err) and code in err and "tok-agent-e7" not in err + out, (rc, out, err))
        _mode["v"] = "mok"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "gone-tok-agent-e7.json"))
        check("machines: a not-readable path that holds the machine token is refused without printing the token", rc == 1 and not _got and _one_line(err) and "gone-" in err and "tok-agent-e7" not in err + out, (rc, out, err))
        _atok.unlink(); _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "machines.json"))
        check("machines: with no token on the machine nothing is sent, one line on stderr, exit 1", rc == 1 and not _got and out == "" and _one_line(err) and "no token" in err and "tok-agent-e7" not in err, (rc, out, err, _got))
        _atok.write_text("tok-agent-e7\n")
        os.environ[client.PASS_ENV] = "ssp_pass-in-use-4f1"; _mode["v"] = "echo400"; _got.clear(); rc, out, err = _acli("post", "machines", "--file", str(_adir / "machines.json"))
        check("machines: with a pass in use the pass is sent and is never printed, not from a server text that echoes it", rc == 1 and len(_got) == 1 and _got[0][1] == "Bearer ssp_pass-in-use-4f1" and "ssp_pass-in-use-4f1" not in err + out and "tok-agent-e7" not in err + out, (rc, out, err))
        os.environ.pop(client.PASS_ENV, None)
        # -- standard input: `--file -` and a bare `-`, run as a script (the client reads file descriptor 0), to the same limit
        _mode["v"] = "mok"
        for label, argv in (("`--file -`", ["--file", "-"]), ("a bare `-`", ["-"])):
            _got.clear(); _run = subprocess.run([sys.executable, client.__file__, "post", "machines", *argv], input=_mbody, capture_output=True, timeout=60, env=dict(os.environ))
            check(f"machines: {label} reads the body from standard input and posts the same bytes, prints the JSON and exits 0", _run.returncode == 0 and json.loads(_run.stdout) == {"ok": True, "machines": 2} and [g[3] for g in _got] == [_mbody] and _got[0][0] == "/client/machines", (_run.returncode, _run.stdout, _run.stderr, _got))
        _got.clear(); _run = subprocess.run([sys.executable, client.__file__, "post", "machines", "--file", "-"], input=b"x" * 1_000_000, capture_output=True, timeout=60, env=dict(os.environ))
        check("machines: a standard input of exactly 1,000,000 bytes is sent whole", _run.returncode == 0 and [len(g[3]) for g in _got] == [1_000_000], (_run.returncode, _run.stderr, [len(g[3]) for g in _got]))
        _got.clear(); _run = subprocess.run([sys.executable, client.__file__, "post", "machines", "--file", "-"], input=b"x" * 1_000_001, capture_output=True, timeout=60, env=dict(os.environ))
        _err = _run.stderr.decode()
        check("machines: a standard input of 1,000,001 bytes is refused before sending: one line on stderr, exit 1, nothing sent", _run.returncode == 1 and not _got and _run.stdout == b"" and _one_line(_err) and "standard input" in _err and "limit" in _err, (_run.returncode, _run.stdout, _err, _got))
        _got.clear(); _run = subprocess.run([sys.executable, client.__file__, "post", "machines", "--file", "-"], stdin=subprocess.DEVNULL, capture_output=True, timeout=60, env=dict(os.environ))
        check("machines: an empty standard input is sent as an empty body (the server refuses it), nothing is printed on stdout", _run.returncode in (0, 1) and [g[3] for g in _got] == [b""], (_run.returncode, _run.stderr, _got))
        _got.clear(); rc, out, err = _acli("post", "agent-state", "--file", "-")
        check("agent-state: `-` is still a path there (a file of that name), not standard input: a missing file is refused, nothing sent", rc == 1 and not _got and _one_line(err) and "standard input" not in err, (rc, out, err, _got))
    finally:
        _asrv.shutdown(); _asrv.server_close(); _athr.join(5)
        for k, v in _aenv.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        with contextlib.suppress(FileNotFoundError): os.remove(_atok)
        import shutil as _sh; _sh.rmtree(_adir, ignore_errors=True)

    import shutil; shutil.rmtree(tmp, ignore_errors=True)

    return ran, fails


# ================================================================ part caller_keys: a caller trusted by a key of its own
def part_caller_keys():
    import base64, contextlib, io, json, logging, os, pathlib, re, stat, sys, time
    import _scratch, _instance
    sys.path.insert(0, STACK)
    BOARD = "https://board.example.org"
    tmp = _scratch.mkdtemp(prefix="callerkeys-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]'), (r"(?m)^require_marks = true", "require_marks = false")):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "state/hub-x", "state/site", "secrets", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
    now0 = time.time()
    NAMES = ("home-front", "team-back", "home-stew")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                    "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * 86400, "seen": {}, "reported": []}))
    HOST, TOKEN = "form-box", "f" * 43
    import hashlib
    (T / "secrets/clients.json").write_text(json.dumps({HOST: {"sha256": hashlib.sha256(TOKEN.encode()).hexdigest(), "created": "2026-01-01T00:00:00+04:00"}}))
    sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

    from stackshot.web import server
    from stackshot.core import config as _cfg
    from stackshot.core import readonly as _ro
    from stackshot.fleet import caller_keys as K
    from stackshot.fleet import client as _client
    from stackshot.service import caller_pass as CP
    from stackshot.web.routes import client_api as _client_api_mod
    from stackshot.service import projects as _projects_svc
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
    from stackshot.service import telling
    from starlette.testclient import TestClient
    from stackshot.web.colorcombos import WEB_LABEL as WL
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""
    telling.tell_woken = lambda *a, **k: None

    _src_tag = lambda a: CP._source_tag(a)
    CLOCK = [1_800_000_000.0]
    CP._now = lambda: CLOCK[0]
    SEC = T / "secrets"; APPROVED, PENDING = SEC / "keys.json", SEC / "keys-pending.json"
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    class Caller:
        """A caller's key: the private half stays here, the public half is what the server is told."""
        def __init__(self):
            self.sk = Ed25519PrivateKey.generate()
            self.pub = b64(self.sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
            self.fp = hashlib.sha256(base64.urlsafe_b64decode(self.pub + "=")).hexdigest()
        def claim(self, header=None, sk=None, sign=True, **over):
            pay = {"iss": self.fp, "aud": BOARD, "iat": CLOCK[0], "exp": CLOCK[0] + 30, "jti": f"jti-{len(ran)}-{time.monotonic_ns()}", **over}
            pay = {k: v for k, v in pay.items() if v is not None}
            h = b64(json.dumps(header or {"alg": "EdDSA", "typ": "JWT"}).encode()); p = b64(json.dumps(pay).encode())
            return f"{h}.{p}.{b64((sk or self.sk).sign(f'{h}.{p}'.encode('ascii')))}"
        def enroll_body(self, label="the fleet tool", sender="alpha"):
            return {"public_key": self.pub, "label": label, "sender": sender}

    def reset_limits(): CP.reset_limits()
    def wipe():
        for f in SEC.glob("keys*"): f.unlink()
        CP.forget_passes(); CP._SETTLED.clear(); CP._LAST_SWEEP = 0.0; reset_limits()
    class Answer:
        """What CP.enroll / CP.claim_pass answered, read like a response."""
        def __init__(self, t): self.status_code, self._j = t
        def json(self): return self._j
    def enroll_from(cl, src, **kw):
        """An enroll that came from the address `src` (the route passes the connection's own; a suite that wants another address calls the service)."""
        return Answer(CP.enroll(cl.enroll_body(**kw), src))
    def trade_from(claim, src): return Answer(CP.claim_pass({"claim": claim}, src))
    def items():
        out = []
        for p in sorted((T / "store").glob("*/*.json")):
            try: it = json.loads(p.read_text())
            except ValueError: continue
            if isinstance(it, dict) and (it.get("metadata") or {}).get("caller_key"): out.append((p.parent.name + p.stem, it))
        return out
    def open_items(): return [(g, it) for g, it in items() if it.get("status") == "open"]
    def answer(gid, choice, ts=None):
        """The owner's answer on an item, given at `ts` (the real clock's now or later when none: a key's enrollment is stamped by the real clock)."""
        p = T / f"store/{gid[0]}/{gid[1:]}.json"; it = json.loads(p.read_text()); m = it["metadata"]
        m["answers"] = [{"ts": max(CLOCK[0], time.time()) if ts is None else ts, "kind": "decision", "choice": choice, "via": "board"}]
        p.write_text(json.dumps(it))

    JH = {"Content-Type": "application/json"}
    try:
        with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
            def post(path, body, headers=None, rate=False):
                if not rate: reset_limits()          # the rate limits have checks of their own (rate=True); every other call starts with room
                return c.post(path, content=body if isinstance(body, (bytes, str)) else json.dumps(body), headers={**JH, **(headers or {})})
            def enroll(cl, **kw): return post("/keys/enroll", cl.enroll_body(**kw))
            def trade(claim): return post("/keys/pass", {"claim": claim})
            _cfg.CFG["caller_keys"] = {"item_project": "projects/alpha"}

            # ---- 1. the key's form
            a = Caller()
            check("a key is 43 base64url characters, canonical: decode gives its 32 bytes", K.decode_key(a.pub) == base64.urlsafe_b64decode(a.pub + "="), a.pub)
            bad = [a.pub[:-1], a.pub + "A", a.pub[:-1] + "=", "", None, 7, a.pub.replace(a.pub[5], "+", 1) if a.pub[5] not in "+/" else a.pub, a.pub[:42] + ("B" if a.pub[42] != "B" else "C")]
            bad = [x for x in bad if x != a.pub]
            check("a text of another length, padding, a character outside the alphabet, a non-text or a non-canonical last character is no key", all(K.decode_key(x) is None for x in bad), [x for x in bad if K.decode_key(x) is not None])
            check("the fingerprint is the sha256 of the 32 bytes in hex, 64 characters, 16 shown", K.fingerprint(a.pub) == a.fp and len(a.fp) == 64 and K.short(a.fp) == a.fp[:16] and K.fingerprint("x") == "")
            check("a label is letters, digits, spaces and _ , + -; markup, a mention, a link, a dot or a line break is no label", [bool(K.label_text(x)) for x in ("the fleet tool", "box-1, main", "@oliver", "a `b`", "see [x](y)", "a\nb", "x" * 81, " ", "<b>", "http://x.example", "login.example.com", "v1.2", "a_b+c")] == [True, True, False, False, False, False, False, False, False, False, False, False, True])
            check("a sender is letters, digits and _ -; no dot, so no domain", [bool(K.sender_text(x)) for x in ("alpha", "my-agent", "agent_1", "a.b_c-d", "pay.example.co", "login.example.com", "a b", "@a", "-a", "")] == [True, True, True, False, False, False, False, False, False, False])
            check("a key speaks as its sender and as its sender, a dash and more, never as a longer word", K.sender_covers("alpha", "alpha") and K.sender_covers("alpha", "alpha-web") and not K.sender_covers("alpha", "alphabet") and not K.sender_covers("alpha", "") and not K.sender_covers("", ""))

            # ---- 2. enroll: no token, pending, trusted for nothing
            wipe()
            r = enroll(a)
            j = r.json()
            check("enroll with no token: 200, pending, the fingerprint whole and short", r.status_code == 200 and j["state"] == "pending" and j["fingerprint"] == a.fp and j["short"] == a.fp[:16], (r.status_code, r.text))
            check("the key is in keys-pending.json (0600) with its label, sender and public key; keys.json does not exist", PENDING.exists() and not APPROVED.exists() and stat.S_IMODE(os.stat(PENDING).st_mode) == 0o600
                  and json.loads(PENDING.read_text())[a.fp]["public_key"] == a.pub and json.loads(PENDING.read_text())[a.fp]["sender"] == "alpha", PENDING.read_text() if PENDING.exists() else None)
            check("the answer is no-store", r.headers.get("cache-control") == "no-store", r.headers)
            r2 = enroll(a)
            check("the same key again: still pending, nothing changes, the same item", r2.status_code == 200 and r2.json()["state"] == "pending" and r2.json()["item"] == j["item"] and len(json.loads(PENDING.read_text())) == 1, r2.text)
            check("a pending key is trusted for nothing: its claim is 403 pending, and no pass is made", trade(a.claim()).status_code == 403 and trade(a.claim()).json()["state"] == "pending" and not CP._PASSES)
            check("an unknown key's claim is 403 unknown", trade(Caller().claim()).status_code == 403 and trade(Caller().claim()).json()["state"] == "unknown")
            check("bad bodies: a bad key, a label or sender with markup, a missing sender, a list, a body that is no JSON, each 400",
                  [enroll(Caller(), label="@x").status_code, enroll(Caller(), sender="a b").status_code, post("/keys/enroll", {"public_key": "nope", "label": "x", "sender": "x"}).status_code, post("/keys/enroll", {"public_key": a.pub, "label": "x"}).status_code,
                   post("/keys/enroll", "[1]").status_code, post("/keys/enroll", "not json").status_code] == [400] * 6)
            check("a sender that is the owner's own name is refused", enroll(Caller(), sender="Oliver").status_code == 400)
            check("a body over 8 KB is 413", post("/keys/enroll", b"{" + b" " * 9000 + b"}").status_code == 413)
            check("nothing but the one key was kept", list(json.loads(PENDING.read_text())) == [a.fp])

            # ---- 3. the board item
            got = open_items()
            check("one open decision item is marked for the key, under the project's front agent, asking Approve or Reject", len(got) == 1 and got[0][1]["metadata"].get("caller_key") == a.fp and "decision" in got[0][1]["metadata"].get("needs", [])
                  and [o["label"] for o in got[0][1]["metadata"].get("options", [])] == ["Approve", "Reject"] and a.fp[:16] in got[0][1]["metadata"].get("ask", "") and got[0][1]["metadata"].get("owner") in (U["home-front"], "home-front"), got[0][1]["metadata"] if got else None)
            check("the answer names the item, and the pending file records it", bool(j["item"]) and json.loads(PENDING.read_text())[a.fp]["item"] == j["item"], j)
            check("the item text carries the fingerprint's first 16 characters and the command, and the label as the caller wrote it", a.fp[:16] in got[0][1]["description"] and "keys approve" in got[0][1]["description"] and "the fleet tool" in got[0][1]["description"], got[0][1]["description"])

            # ---- 4. approving on the board
            answer(got[0][0], "Approve")
            r = trade(a.claim())
            check("the owner's answer Approve is taken in at the key's next claim: the key is approved and the claim trades", r.status_code == 200 and r.json()["fingerprint"] == a.fp, (r.status_code, r.text))
            check("the key moved from pending to keys.json (0600) with its approval time", a.fp in json.loads(APPROVED.read_text()) and a.fp not in json.loads(PENDING.read_text()) and stat.S_IMODE(os.stat(APPROVED).st_mode) == 0o600 and json.loads(APPROVED.read_text())[a.fp].get("approved"))
            done = items()[0][1]
            check("the item is closed as done", done["status"] == "completed" and not open_items(), (done.get("status"), done.get("outcome")))
            pass_a = r.json()
            check("the pass is an opaque token of 10 minutes tied to the key's fingerprint and sender, and is not in any file", pass_a["pass"].startswith("ssp_") and pass_a["expires_in"] == 600 and pass_a["sender"] == "alpha"
                  and pass_a["pass"] not in APPROVED.read_text() and pass_a["pass"] not in PENDING.read_text(), pass_a)

            # ---- 5. rejecting on the board, and the command line
            b = Caller(); jb = enroll(b).json(); gb = open_items()[0][0]
            answer(gb, "Reject")
            check("the owner's answer Reject: the claim is refused 403, the key is gone and its item is closed", trade(b.claim()).status_code == 403 and b.fp not in json.loads(PENDING.read_text())
                  and [it for g, it in items() if it["metadata"]["caller_key"] == b.fp][0]["status"] == "completed", [it["status"] for g, it in items()])
            check("…and the key is neither pending nor approved", b.fp not in K.pending() and b.fp not in K.approved())
            c2 = Caller(); enroll(c2); g2 = open_items()[0][0]
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc_short = _client.main(["client", "keys", "approve", c2.fp[:7]])
                rc_none = _client.main(["client", "keys", "approve", "0" * 12])
                rc_list = _client.main(["client", "keys", "list"])
                rc_usage = _client.main(["client", "keys", "approve"])
                shown = out.getvalue()
            check("keys approve with under 8 characters, or naming no key, is refused (exit 1); no key was approved", rc_short == 1 and rc_none == 1 and rc_usage == 1 and c2.fp not in K.approved(), shown)
            check("keys list shows the approved and the pending key with the first 16 characters, the sender and the label, and never a whole fingerprint", rc_list == 0 and a.fp[:16] in shown and c2.fp[:16] in shown and "approved" in shown and "pending" in shown and a.fp not in shown, shown)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = _client.main(["client", "keys", "approve", c2.fp[:12]])
            check("keys approve <fingerprint> approves a pending key", rc == 0 and c2.fp in K.approved() and c2.fp not in K.pending() and "approved" in out.getvalue(), out.getvalue())
            check("a key approved on the command line has its item closed at the key's first claim", trade(c2.claim()).status_code == 200 and not [g for g, it in open_items() if g == g2] and [it for g, it in items() if g == g2][0]["status"] == "completed")

            # ---- 6. the pending cap, the rate limit and the expiry
            wipe(); [enroll_from(Caller(), f"198.51.100.{i}") for i in range(5)]
            extra = Caller(); r = enroll_from(extra, "198.51.100.9")
            check("a sixth key while five wait is 429, and is not kept", r.status_code == 429 and extra.fp not in K.pending() and len(K.pending()) == 5, (r.status_code, r.json()))
            first = next(iter(K.pending()))
            K.approve(first[:16])
            check("an approved key does not count as waiting: a sixth is then kept", enroll_from(extra, "198.51.100.9").status_code == 200 and extra.fp in K.pending() and len(K.pending()) == 5)
            check("a key already approved enrolling again answers approved and changes nothing", post("/keys/enroll", {"public_key": json.loads(APPROVED.read_text())[first]["public_key"], "label": "x", "sender": "x"}).json()["state"] == "approved")
            late = K.pending(now=time.time() + K.PENDING_TTL + 5)
            check("a pending key nobody answered for 7 days is gone", late == {} and K.enroll(Caller().pub, "x", "x", now=time.time() + K.PENDING_TTL + 5)[0] == "pending")
            wipe(); reset_limits()
            codes = [post("/keys/enroll", {"public_key": "bad", "label": "x", "sender": "x"}, rate=True).status_code for _ in range(12)]
            r = post("/keys/enroll", {"public_key": "bad", "label": "x", "sender": "x"}, rate=True)
            check("10 enrolls in 10 minutes from one address, then 429 with Retry-After (a refused one counts too)", codes == [400] * 10 + [429, 429] and r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["retry_after"] >= 1, (codes, r.headers))
            CLOCK[0] += 601
            check("…and the window moves on", post("/keys/enroll", {"public_key": "bad", "label": "x", "sender": "x"}, rate=True).status_code == 400)
            wipe()
            _cfg.CFG["caller_keys"] = {"item_project": ""}
            n0 = len(items()); d = Caller(); r = enroll(d)
            check("with [caller_keys] item_project empty no item is raised, the key is kept pending and `item` is empty", r.status_code == 200 and r.json()["item"] == "" and len(items()) == n0 and d.fp in K.pending(), r.text)
            _cfg.CFG["caller_keys"] = {"item_project": "projects/none-such"}
            e = Caller(); r = enroll(e)
            check("a project that does not exist raises no item and still keeps the key (the command line is the way)", r.status_code == 200 and r.json()["item"] == "" and e.fp in K.pending(), r.text)
            _cfg.CFG["caller_keys"] = {"item_project": "projects/alpha"}
            real = _ro.is_read_only; _ro.is_read_only = lambda: True
            try: stand = (enroll(Caller()).status_code, trade(d.claim()).status_code)
            finally: _ro.is_read_only = real
            check("a standby copy answers enroll and pass 503", stand == (503, 503), stand)

            # ---- 7. the claim
            wipe(); k = Caller(); enroll(k); K.approve(k.fp[:16])
            good = trade(k.claim())
            check("a good claim: 200 and a pass", good.status_code == 200 and good.json()["pass"].startswith("ssp_"), good.text)
            check("a claim of exactly 60 seconds is fine", trade(k.claim(exp=CLOCK[0] + 60)).status_code == 200)
            r = trade(k.claim(exp=CLOCK[0] + 61)); check("a claim of 61 seconds is 401 (life)", r.status_code == 401 and "life" in r.json()["error"], r.text)
            r = trade(k.claim(exp=CLOCK[0])); check("a claim with no life (exp = iat) is 401", r.status_code == 401, r.text)
            r = trade(k.claim(iat=CLOCK[0] + 120, exp=CLOCK[0] + 150)); check("a claim made 120 seconds ahead of the server's clock is 401 (skew)", r.status_code == 401 and "clock" in r.json()["error"], r.text)
            r = trade(k.claim(iat=CLOCK[0] - 120, exp=CLOCK[0] - 100)); check("a claim made 120 seconds behind is 401 (skew)", r.status_code == 401, r.text)
            check("a claim 59 seconds ahead or behind is taken", trade(k.claim(iat=CLOCK[0] + 59, exp=CLOCK[0] + 89)).status_code == 200 and trade(k.claim(iat=CLOCK[0] - 59, exp=CLOCK[0] + 1)).status_code == 200)
            r = trade(k.claim(iat=CLOCK[0] - 50, exp=CLOCK[0] - 10)); check("an expired claim inside the skew is 401 (expired)", r.status_code == 401 and "expired" in r.json()["error"], r.text)
            r = trade(k.claim(aud="https://elsewhere.example.org")); check("a claim for another board is 401 (aud)", r.status_code == 401 and "aud" in r.json()["error"], r.text)
            check("an aud that is the board's address with more after it, or that is no text, is 401", trade(k.claim(aud=BOARD + "/x")).status_code == 401 and trade(k.claim(aud=[BOARD])).status_code == 401 and trade(k.claim(aud=None)).status_code == 401)
            j1 = "jti-reused-1"; first_use = trade(k.claim(jti=j1)); again = trade(k.claim(jti=j1))
            check("a jti used once is refused the second time (401), and is free again after its life", first_use.status_code == 200 and again.status_code == 401 and "jti" in again.json()["error"], again.text)
            CLOCK[0] += 200
            check("…a forgotten jti trades again", trade(k.claim(jti=j1)).status_code == 200)
            other = Caller()
            check("another key's jti is not this key's", trade(other.claim(jti="jti-shared-1")).status_code == 403 and trade(k.claim(jti="jti-shared-1")).status_code == 200)
            bad_sig = k.claim().rsplit(".", 1); sig = bytearray(base64.urlsafe_b64decode(bad_sig[1] + "==")); sig[0] ^= 1
            r = trade(bad_sig[0] + "." + b64(bytes(sig))); check("a signature with one bit changed is 403 unknown (the answer of every claim whose signature is not the key's)", r.status_code == 403 and r.json()["state"] == "unknown", r.text)
            r = trade(k.claim(sk=other.sk)); check("a claim for this key signed by another key is 403 unknown", r.status_code == 403 and r.json()["state"] == "unknown", r.text)
            h, p, s = k.claim().split("."); p2 = b64(json.dumps({**json.loads(base64.urlsafe_b64decode(p + "==")), "exp": CLOCK[0] + 5000}).encode())
            r = trade(f"{h}.{p2}.{s}"); check("a payload changed after signing is 403 unknown", r.status_code == 403 and r.json()["state"] == "unknown", r.text)
            check("a header that is not EdDSA (none, HS256, a lower-case name) is 401", all(trade(k.claim(header={"alg": a_})).status_code == 401 for a_ in ("none", "HS256", "eddsa", "RS256")))
            check("a header with `crit` is 401", trade(k.claim(header={"alg": "EdDSA", "crit": ["x"], "x": 1})).status_code == 401)
            check("a missing jti, a jti under 8 characters, an iat that is a text and an exp that is a bool are 401", all(trade(k.claim(**kw)).status_code == 401 for kw in ({"jti": None}, {"jti": "short"}, {"iat": "now"}, {"exp": True})))
            check("an iss that is not a whole fingerprint is 401", trade(k.claim(iss=k.fp[:16])).status_code == 401 and trade(k.claim(iss=k.fp.upper())).status_code == 401)
            check("a claim that is not three base64url parts, or whose parts are no JSON, is 400", [trade(x).status_code for x in ("a.b", "a.b.c.d", "a b.c.d", f"{b64(b'[]')}.{b64(b'{}')}.AAAA", f"{b64(b'x')}.{b64(b'y')}.AAAA")] == [400] * 5)
            check("a claim over 2048 characters is 400, and the body without a claim", trade("a." * 1100 + "a").status_code == 400 and post("/keys/pass", {}).status_code == 400)
            reset_limits()
            codes = [post("/keys/pass", {"claim": "a.b.c"}, rate=True).status_code for _ in range(61)]
            check("60 claims a minute that prove nothing, from one address, then 429", codes[:60] == [400] * 60 and codes[60] == 429, codes[58:])
            reset_limits()

            # ---- 8. the pass and the gate
            AUTH = lambda tok: {"Authorization": "Bearer " + tok}
            wipe(); k = Caller(); enroll(k, sender="alpha"); K.approve(k.fp[:16]); tok = trade(k.claim()).json()["pass"]
            seen_body = {"id": "all", "sender": "alpha-web"}
            r = post("/client/for-you/seen", seen_body, AUTH(tok))
            check("a pass opens the For you write for its key's label plus a dash and more: 200", r.status_code == 200 and r.json()["ok"] is True, (r.status_code, r.text))
            check("the key's own label alone is covered too", post("/client/for-you/seen", {"id": "all", "sender": "alpha"}, AUTH(tok)).status_code == 200)
            r = post("/client/for-you/seen", {"id": "all", "sender": "alphabet"}, AUTH(tok)); check("a sender that is not the key's label or its dash form is 403", r.status_code == 403, (r.status_code, r.text))
            r = post("/client/for-you/seen", {"id": "all", "sender": "someone-else"}, AUTH(tok)); check("another sender is 403", r.status_code == 403)
            r = post("/client/setup-result", {"ok": True}, AUTH(tok)); check("a pass opens no other verb of /client: 403 naming the form's calls", r.status_code == 403 and "project-agent" in r.json()["error"], (r.status_code, r.text))
            r = post("/client/anchor-add", {"project": "projects/alpha", "add": ["https://github.com/example-org/example-repo/pull/101"], "sender": "alpha-web"}, AUTH(tok))
            check("a pass opens no anchor-add: 403 naming the form's calls, nothing added", r.status_code == 403 and "project-agent" in r.json()["error"], (r.status_code, r.text))
            r = c.get("/client/whoami", headers=AUTH(tok)); check("a pass opens no read of /client: 401", r.status_code == 401, (r.status_code, r.text))
            r = post("/client/poll", {"sessions": []}, AUTH(tok)); check("a pass is not a machine: poll is 403", r.status_code == 403)
            r = post("/client/project-agent-rename", {"project": "projects/none-such", "old": "x", "new": "y", "sender": "alpha-rename"}, AUTH(tok))
            check("a pass opens the rename call to the form's checks (past the gate: the project is what is missing, 404)", r.status_code == 404 and "only the web form" not in r.text, (r.status_code, r.text))
            r = post("/client/project-agent-rename", {"project": "projects/none-such", "old": "x", "new": "y", "sender": "other-rename"}, AUTH(tok))
            check("…and a sender that is not the key's is refused as not the form", r.status_code == 403 and "only the web form" in r.text, (r.status_code, r.text))
            r = c.get("/client/colors/combos", headers=AUTH(tok)); check("a pass reads the color tool's list", r.status_code == 200 and "combos" in r.json(), (r.status_code, r.text))
            r = post("/client/colors/combos/delete", {"id": "00000000", "sender": "alpha-web"}, AUTH(tok)); check("…and a write of it needs the web form's own label (alpha-web is not it): 403", r.status_code == 403, (r.status_code, r.text))
            fam = WL.split("-")[0]; kc = Caller(); enroll(kc, sender=fam); K.approve(kc.fp[:16]); tc = trade(kc.claim()).json()["pass"]
            r = post("/client/colors/combos/delete", {"id": "00000000", "sender": WL}, AUTH(tc)); check("a key whose label covers the web form's label may write the color tool's list: 200", r.status_code == 200 and "combos" in r.json(), (r.status_code, r.text))
            r = post("/client/colors/combos/delete", {"id": "00000000", "sender": WL}, AUTH(TOKEN)); check("the same write by a machine token in no list is 403", r.status_code == 403, (r.status_code, r.text))
            r = post("/client/for-you/seen", seen_body, AUTH("ssp_" + "x" * 43)); check("a pass that was never given is 401", r.status_code == 401)
            r = post("/client/for-you/seen", seen_body); check("no token and no pass is 401", r.status_code == 401)
            r = post("/client/for-you/seen", seen_body, AUTH(TOKEN)); check("a machine token that is in no list is 403 (the old behavior with no pass)", r.status_code == 403 and "form_machines" in r.text, (r.status_code, r.text))
            _cfg.CFG["project_agent"] = {"form_senders": ["lists-web"], "form_machines": [HOST]}
            r = post("/client/for-you/seen", {"id": "all", "sender": "lists-web"}, AUTH(TOKEN)); check("during the overlap the host lists still let the form in: 200", r.status_code == 200, (r.status_code, r.text))
            r = post("/client/for-you/seen", {"id": "all", "sender": "lists-web"}, AUTH(tok)); check("…a pass does not carry the lists' label: 403", r.status_code == 403)
            check("_form_call: a pass, the lists, neither", _projects_svc._form_call("pass:" + k.fp, "alpha-web") and _projects_svc._form_call(HOST, "lists-web") and not _projects_svc._form_call(HOST, "alpha-web")
                  and not _projects_svc._form_call("pass:" + "0" * 64, "alpha-web") and not _projects_svc._form_call("", "alpha-web"))
            _cfg.CFG["project_agent"] = {}

            CLOCK[0] += 599
            check("a pass is good for 10 minutes (599 seconds in)", post("/client/for-you/seen", seen_body, AUTH(tok)).status_code == 200)
            CLOCK[0] += 2
            check("…and not after (601 seconds in): 401", post("/client/for-you/seen", seen_body, AUTH(tok)).status_code == 401)
            tok = trade(k.claim()).json()["pass"]
            CP.forget_passes()
            check("a restart of the server (the table is memory) ends every pass: 401", post("/client/for-you/seen", seen_body, AUTH(tok)).status_code == 401)
            tok = trade(k.claim()).json()["pass"]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = _client.main(["client", "keys", "revoke", k.fp[:20]])
            check("keys revoke deletes the approved key (exit 0)", rc == 0 and k.fp not in K.approved() and "revoked" in out.getvalue(), out.getvalue())
            check("a pass of a revoked key fails at once: 401", post("/client/for-you/seen", seen_body, AUTH(tok)).status_code == 401)
            r = trade(k.claim()); check("…and its claim is 403 unknown", r.status_code == 403 and r.json()["state"] == "unknown", r.text)
            out = io.StringIO()
            with contextlib.redirect_stderr(out), contextlib.redirect_stdout(out):
                rc = _client.main(["client", "keys", "revoke", k.fp[:20]])
            check("revoking a key that is gone is exit 1", rc == 1, out.getvalue())
            e2 = Caller(); enroll(e2)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = _client.main(["client", "keys", "revoke", e2.fp[:10]])
            check("keys revoke also deletes a pending key", rc == 0 and e2.fp not in K.pending())
            CLOCK[0] += CP.SWEEP_EVERY + 1
            check("the item of a key that is gone is closed at the next enroll after a minute", enroll(Caller()).status_code == 200 and not [g for g, it in open_items() if it["metadata"]["caller_key"] == e2.fp])

            # ---- 9. the routes
            paths = {(r.path, tuple(sorted(r.methods or ()))) for r in server.mcp.http_app().routes if hasattr(r, "path")}
            check("/keys/enroll and /keys/pass are routes of POST, and /client/{what} does not take them", ("/keys/enroll", ("POST",)) in paths and ("/keys/pass", ("POST",)) in paths, sorted(p for p in paths if "keys" in p[0]))

            # ---- 10. the limits: what a caller who proves nothing can and cannot take from one who does
            # (a) a claim whose signature verifies is never refused for other callers' junk: it is counted for its key, and only the key's own calls count there
            wipe(); k = Caller(); enroll(k); K.approve(k.fp[:16]); stranger = Caller()
            junk = [post("/keys/pass", {"claim": "a.b.c"}, rate=True).status_code for _ in range(70)]
            r = post("/keys/pass", {"claim": k.claim()}, rate=True)
            check("70 junk claims from one address, then a valid claim from the same address: 200 (the junk was counted for the address, 429 from the 61st)", junk[:60] == [400] * 60 and junk[60:] == [429] * 10 and r.status_code == 200, (junk[58:], r.status_code, r.text))
            reset_limits()
            forged = [post("/keys/pass", {"claim": k.claim(sk=stranger.sk)}, rate=True).status_code for _ in range(70)]
            r = post("/keys/pass", {"claim": k.claim()}, rate=True)
            check("70 claims that name the approved key but are signed by another: 403 then 429 for their address, and the key's own valid claim still 200", forged[0] == 403 and forged[-1] == 429 and r.status_code == 200, (forged[:2], forged[-2:], r.status_code, r.text))
            reset_limits()
            for i in range(700): trade_from("a.b.c", f"2001:db8:{i:x}::1")
            check("700 junk claims from 700 addresses (700 IPv6 /64s) spend the ceiling over all of them (600 a minute): a further junk claim is 429", trade_from("a.b.c", "203.0.113.99").status_code == 429)
            r = trade_from(k.claim(), "203.0.113.99")
            check("…and a valid claim of the approved key still trades (the ceiling is not the key's)", r.status_code == 200, (r.status_code, r.json()))
            reset_limits()
            for i in range(1000): trade_from("a.b.c", "203.0.113.50")
            check("one address's 1000 junk claims take 60 from the ceiling and no more: another address is not refused", trade_from("a.b.c", "203.0.113.51").status_code == 400 and len(CP.CLAIM_CEILING.hits.get("", [])) <= 62, len(CP.CLAIM_CEILING.hits.get("", [])))
            # (b) the address: per address, the connection's own, never a header
            reset_limits()
            a_codes = [trade_from("a.b.c", "192.0.2.1").status_code for _ in range(62)]
            check("an address is counted by itself: 60 then 429 for 192.0.2.1, while 192.0.2.2 has all its calls", a_codes[:60] == [400] * 60 and a_codes[60:] == [429, 429] and trade_from("a.b.c", "192.0.2.2").status_code == 400, a_codes[58:])
            reset_limits()
            v6 = [trade_from("a.b.c", f"2001:db8:1:2:{i:x}::1").status_code for i in range(62)]
            check("an IPv6 address counts by its /64: 62 addresses of one /64 are one source", v6[:60] == [400] * 60 and v6[60:] == [429, 429] and trade_from("a.b.c", "2001:db8:1:3::1").status_code == 400, v6[58:])
            reset_limits()
            far = TestClient(server.mcp.http_app(), base_url=BOARD, client=("203.0.113.7", 5000))
            far_codes = [far.post("/keys/pass", content=json.dumps({"claim": "a.b.c"}), headers={**JH, "X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(62)]
            check("the route counts the connection's address (203.0.113.7): a header naming another address each time changes nothing, 429 from the 61st", far_codes[:60] == [400] * 60 and far_codes[60:] == [429, 429], far_codes[58:])
            check("…and a caller at another address (the suite's own) is not held by it", post("/keys/pass", {"claim": "a.b.c"}, rate=True).status_code == 400)
            # the key's own limit
            reset_limits(); kk = Caller(); enroll(kk); K.approve(kk.fp[:16]); other_k = Caller(); enroll(other_k); K.approve(other_k.fp[:16])
            own = [trade_from(kk.claim(), "192.0.2.77").status_code for _ in range(31)]
            r = trade_from(kk.claim(), "192.0.2.77")
            check("a key's valid claims are limited per key: 30 a minute, then 429 with retry_after", own[:30] == [200] * 30 and own[30] == 429 and r.status_code == 429 and r.json()["retry_after"] >= 1, (own[28:], r.json()))
            check("…another key is not held by it", trade_from(other_k.claim(), "192.0.2.77").status_code == 200)
            CLOCK[0] += 61
            check("…and the window moves on", trade_from(kk.claim(), "192.0.2.77").status_code == 200)
            # enroll: 60 junk then one valid
            wipe(); reset_limits()
            junk = [enroll_from(Caller(), "192.0.2.5", label="@bad").status_code for _ in range(60)]
            good = Caller(); r = enroll_from(good, "192.0.2.6")
            check("60 junk enrolls from one address (429 from the 11th), then a valid enroll from another address: kept pending", junk[:10] == [400] * 10 and junk[10:] == [429] * 50 and r.status_code == 200 and r.json()["state"] == "pending" and good.fp in K.pending(), (junk[8:12], r.status_code, r.json()))
            reset_limits()
            for i in range(60): CP.enroll({"public_key": "bad", "label": "x", "sender": "x"}, f"192.0.2.{100 + i}")
            r = enroll_from(Caller(), "192.0.2.200")
            check("60 junk enrolls from 60 addresses, then a valid enroll: kept pending (the ceiling is 300 in 10 minutes)", r.status_code == 200 and r.json()["state"] == "pending", (r.status_code, r.json()))
            reset_limits()
            for i in range(1000): CP.enroll({"public_key": "bad", "label": "x", "sender": "x"}, "192.0.2.50")
            check("one address's 1000 junk enrolls take 10 from the ceiling and no more", len(CP.ENROLL_CEILING.hits.get("", [])) == 10, len(CP.ENROLL_CEILING.hits.get("", [])))
            # (c) the pending places: 5 in all, 3 from one address, and the owner always has a way out
            wipe(); reset_limits()
            first3 = [enroll_from(Caller(), "192.0.2.10") for _ in range(3)]; fourth = enroll_from(Caller(), "192.0.2.10")
            check("one address keeps 3 keys waiting, not a 4th (429 naming the address), and the 4th is not kept", [x.status_code for x in first3] == [200] * 3 and fourth.status_code == 429 and "this address" in fourth.json()["error"] and len(K.pending()) == 3, (fourth.status_code, fourth.json()))
            again = enroll_from(Caller(), "192.0.2.10"); one = next(iter(K.pending())); pub_one = K.pending()[one]["public_key"]
            check("…a key that already waits enrolls again from that address: unchanged, not refused", CP.enroll({"public_key": pub_one, "label": "x", "sender": "x"}, "192.0.2.10")[1]["state"] == "pending")
            other_a, other_b = enroll_from(Caller(), "192.0.2.11"), enroll_from(Caller(), "192.0.2.12")
            late = enroll_from(Caller(), "192.0.2.13")
            check("other addresses fill the other two places; then a 6th, from any address, is 429 (5 in all)", other_a.status_code == other_b.status_code == 200 and late.status_code == 429 and len(K.pending()) == 5 and "this address" not in late.json()["error"], (late.status_code, late.json()))
            check("the keys' files hold a hash of the source and never an address", "192.0.2" not in PENDING.read_text() and all(len(e.get("source", "")) == 12 for e in json.loads(PENDING.read_text()).values()), PENDING.read_text())
            out = io.StringIO()
            with contextlib.redirect_stdout(out): rc = _client.main(["client", "keys", "approve", one[:12]])
            check("the owner's way out 1: `keys approve` of a pending key works with every place taken", rc == 0 and one in K.approved() and len(K.pending()) == 4, out.getvalue())
            check("…and the place it frees is taken by the next enroll, from the address that was held", enroll_from(Caller(), "192.0.2.13").status_code == 200 and len(K.pending()) == 5)
            victim = next(fp for fp, e in K.pending().items() if e["source"] == _src_tag("192.0.2.10"))
            with contextlib.redirect_stdout(io.StringIO()): rc = _client.main(["client", "keys", "revoke", victim[:12]])
            check("the owner's way out 2: `keys revoke` of a pending key frees its place", rc == 0 and victim not in K.pending() and enroll_from(Caller(), "192.0.2.14").status_code == 200 and len(K.pending()) == 5)
            gid, rej = next((g, it["metadata"]["caller_key"]) for g, it in open_items() if it["metadata"]["caller_key"] in K.pending())
            answer(gid, "Reject")
            check("the owner's way out 3: Reject on the board item frees the place at the next enroll (the item is read by its id)", enroll_from(Caller(), "192.0.2.15").status_code == 200 and rej not in K.pending() and len(K.pending()) == 5, K.pending().keys())

            # ---- 11. what a request may make the server read
            wipe(); reset_limits(); _cfg.CFG["caller_keys"] = {"item_project": "projects/alpha"}
            scans = [0]; real_files = CP._item_files
            def counting(): scans[0] += 1; return real_files()
            CP._item_files = counting
            try:
                w = Caller(); enroll(w); fp_w = w.fp; n0 = scans[0]
                for _ in range(20): enroll(w)                                   # the same pending key again and again, inside the minute
                check("the same pending key enrolled 20 more times scans the store 0 times (its item is read by id)", scans[0] == n0, (n0, scans[0]))
                stranger = Caller()
                for _ in range(20): post("/keys/pass", {"claim": w.claim(sk=stranger.sk)}, rate=True)
                check("20 claims that name a pending key but carry another key's signature scan the store 0 times", scans[0] == n0, (n0, scans[0]))
                reset_limits(); n1 = scans[0]
                for _ in range(20): trade(Caller().claim())
                check("20 claims of keys the server never heard of scan the store 0 times", scans[0] == n1)
                g_w = open_items()[0][0]; answer(g_w, "Approve"); n2 = scans[0]
                r = trade(w.claim())
                check("the pending key's own claim (signature verified) takes the owner's Approve in, by id: 200, the item is closed, 0 scans", r.status_code == 200 and not open_items() and scans[0] == n2, (r.status_code, scans[0] - n2))
                CLOCK[0] += CP.SWEEP_EVERY + 1; n3 = scans[0]
                for _ in range(10): enroll(w)
                check("10 enrolls inside a minute scan the whole store once in all (for the items of keys that are gone)", scans[0] - n3 == 1, scans[0] - n3)
                CLOCK[0] += CP.SWEEP_EVERY + 1; reset_limits(); n4 = scans[0]
                for _ in range(5): CP.enroll({"public_key": "bad", "label": "x", "sender": "x"}, "192.0.2.99")
                check("a junk enroll of a bad body scans the store 0 times", scans[0] == n4, scans[0] - n4)
            finally:
                CP._item_files = real_files

            # ---- 12. the lows
            # a pass reaches only the form's branch of project-agent
            wipe(); k = Caller(); enroll(k, sender="alpha"); K.approve(k.fp[:16]); tok = trade(k.claim()).json()["pass"]
            pa = {"project": "projects/alpha", "name": "home-front-helper", "role": "helper", "mandate": "a helper", "front": False}
            r = post("/client/project-agent", {**pa, "sender": U["home-front"]}, AUTH(tok))
            check("a pass whose sender is a session id (the non-form branch's proof) is 403 on project-agent, with the pass's own text", r.status_code == 403 and "a pass opens only" in r.text, (r.status_code, r.text))
            r = post("/client/project-agent", {**pa, "sender": "someone-else"}, AUTH(tok))
            check("…a sender the key does not cover is 403 the same", r.status_code == 403 and "a pass opens only" in r.text, (r.status_code, r.text))
            r = post("/client/project-agent", {**pa, "project": "projects/none-such", "sender": "alpha-web"}, AUTH(tok))
            check("…a sender the key covers goes on to the form's checks (the project is what is missing: 404)", r.status_code == 404, (r.status_code, r.text))
            r = post("/client/project-agent", {**pa, "sender": "alpha-web"}, AUTH(tok))
            check("…and the form's call by a pass does list the agent", r.status_code == 200, (r.status_code, r.text))
            # the approval prompt says what approving gives
            wipe(); reset_limits(); p1 = Caller(); jj = enroll(p1, sender="alpha").json(); ask = open_items()[0][1]["metadata"]["ask"]
            check("the item's ask says the key gets the whole New session form and every label that starts with its sender and a dash, inside the board's 240 characters", "whole New session form" in ask and "register" in ask and "rename" in ask and "retire" in ask and "For you" in ask and "every `alpha-…` label" in ask and "may call as `alpha`" in ask and len(ask) <= 240, ask)
            long_sender = "s" * 80; ask_long = CP._ask_line("0" * 16, long_sender)
            check("a sender of 80 characters is cut in the ask to stay inside 240, and the item is still raised", len(ask_long) <= 240 and "whole New session form" in ask_long and bool(enroll(Caller(), sender=long_sender).json()["item"]), ask_long)
            # numbers in a claim
            wipe(); reset_limits(); k = Caller(); enroll(k); K.approve(k.fp[:16])
            def code_of(**kw):
                try: return trade(k.claim(**kw)).status_code
                except Exception as e: return f"raised {type(e).__name__}"
            huge = 10 ** 400
            check("an iat or exp that is a huge integer is 401, never a 500", [code_of(iat=huge, exp=huge + 30), code_of(iat=-huge, exp=-huge + 30), code_of(exp=huge), code_of(iat=-huge)] == [401] * 4, [code_of(iat=huge, exp=huge + 30), code_of(exp=huge)])
            check("…and so is a float that is infinite, not a number, or past a trillion seconds", [code_of(exp=float("inf")), code_of(iat=float("-inf")), code_of(iat=float("nan")), code_of(iat=1e13, exp=1e13 + 30), code_of(iat=1e300, exp=1.5e300)] == [401] * 5)
            check("…and an honest claim still trades", code_of() == 200)
            # a body that nests too deep for the parser is a 400, never a 500
            class _Deep:
                def __init__(self, real): self._real = real
                def loads(self, *a, **k): raise RecursionError("maximum recursion depth exceeded")
                def __getattr__(self, name): return getattr(self._real, name)
            def deep_status(path, body):
                try: return post(path, body, rate=False).status_code
                except Exception as e: return f"raised {type(e).__name__}"
            real_json = _client_api_mod.json
            _client_api_mod.json = _Deep(real_json)
            try: shim = deep_status("/keys/enroll", b"[[[[]]]]")
            finally: _client_api_mod.json = real_json
            check("a body the JSON parser cannot take for its depth (RecursionError) is 400 on the route", shim == 400, shim)
            check("…a real one of 8000 nested arrays is 400 too (whatever this Python does with it)", deep_status("/keys/enroll", b"[" * 4000 + b"]" * 4000) == 400 and deep_status("/keys/pass", b"[" * 8000) == 400)
            real_cp_json = CP.json
            CP.json = _Deep(real_cp_json)
            try: shim = deep_status("/keys/pass", {"claim": f"{b64(b'{}')}.{b64(b'{}')}.AAAA"})
            finally: CP.json = real_cp_json
            check("a claim whose header cannot be parsed for its depth is 400", shim == 400, shim)
            nest = "[" * 1400
            check("…a real claim with a header nested 1400 deep is 400", deep_status("/keys/pass", {"claim": f"{b64(nest.encode())}.{b64(b'{}')}.AAAA"}) == 400)

            # ---- 13. the review's findings
            # M1: a signed claim that is expired, for another board or already used is the source address's to pay for, never the key's
            wipe(); k = Caller(); enroll(k); K.approve(k.fp[:16]); reset_limits()
            used = k.claim(jti="jti-replayed-0001"); first_use = trade_from(used, "198.51.100.1")
            replays = [trade_from(used, f"198.51.100.{i}").status_code for i in range(2, 33)]
            r = trade_from(k.claim(), "198.51.100.200")
            check("one used claim sent 31 times from 31 addresses is 401 each, counts nothing for the key, and the key's fresh valid claim still trades (200)", first_use.status_code == 200 and replays == [401] * 31 and r.status_code == 200
                  and len(CP.CLAIM_KEY.hits.get(k.fp, [])) == 2, (first_use.status_code, replays[-3:], r.status_code, len(CP.CLAIM_KEY.hits.get(k.fp, []))))
            reset_limits()
            old = k.claim(iat=CLOCK[0] - 50, exp=CLOCK[0] - 10)
            stale = [trade_from(old, f"198.51.100.{i}").status_code for i in range(1, 32)]
            r = trade_from(k.claim(), "198.51.100.200")
            check("an expired signed claim sent 31 times from 31 addresses counts nothing for the key: the fresh claim is 200", stale == [401] * 31 and r.status_code == 200 and len(CP.CLAIM_KEY.hits.get(k.fp, [])) == 1, (stale[-3:], r.status_code))
            reset_limits()
            elsewhere = k.claim(aud="https://elsewhere.example.org")
            wrong = [trade_from(elsewhere, f"198.51.100.{i}").status_code for i in range(1, 32)]
            check("…and so does a claim signed for another board", wrong == [401] * 31 and trade_from(k.claim(), "198.51.100.200").status_code == 200 and len(CP.CLAIM_KEY.hits.get(k.fp, [])) == 1, wrong[-3:])
            reset_limits()
            same_src = [trade_from(used, "198.51.100.77").status_code for _ in range(62)]
            check("…while the replays from one address are limited as that address's own: 60 of them, then 429", same_src[:60] == [401] * 60 and same_src[60:] == [429, 429], same_src[58:])

            # A: an answer on the item of an earlier enroll is no answer to a new enroll of the same key
            wipe(); reset_limits(); _cfg.CFG["caller_keys"] = {"item_project": "projects/alpha"}
            w = Caller(); enroll_from(w, "192.0.2.21", sender="alpha-web"); g_old = open_items()[0][0]
            CP._LAST_SWEEP = CLOCK[0]                                   # a sweep just ran: the old item is not closed as the item of a key that is gone
            answer(g_old, "Approve", ts=time.time()); time.sleep(0.05)
            with contextlib.redirect_stdout(io.StringIO()): _client.main(["client", "keys", "revoke", w.fp[:12]])
            again = enroll_from(w, "192.0.2.21", sender="alpha")
            check("a key revoked after the owner's Approve and enrolled again (as another label) stays pending: its claim is 403, it is not approved", again.json()["state"] == "pending" and trade(w.claim()).status_code == 403 and w.fp not in K.approved()
                  and K.pending()[w.fp]["sender"] == "alpha", (again.json(), list(K.approved())))
            now_open = [(g, it) for g, it in open_items() if it["metadata"]["caller_key"] == w.fp]
            check("…the answered item of the earlier enroll is closed, and a new item with no answer asks about the new one", len(now_open) == 1 and now_open[0][0] != g_old and not now_open[0][1]["metadata"].get("answers")
                  and [it for g, it in items() if g == g_old][0]["status"] == "completed", [(g, it["status"]) for g, it in items()])
            wipe(); reset_limits()
            w2 = Caller(); enroll_from(w2, "192.0.2.22", sender="alpha-web"); g2 = open_items()[0][0]; CP._LAST_SWEEP = CLOCK[0]
            answer(g2, "Approve", ts=time.time()); time.sleep(0.05)
            with contextlib.redirect_stdout(io.StringIO()): _client.main(["client", "keys", "revoke", w2.fp[:12]])
            _cfg.CFG["caller_keys"] = {"item_project": ""}              # the new enroll files no item of its own: the old, answered one is all the board has for this key
            enroll_from(w2, "192.0.2.22", sender="alpha"); CP.settle()
            check("an answer older than the key's enrollment is ignored by the settle too", w2.fp in K.pending() and w2.fp not in K.approved() and [it for g, it in items() if g == g2][0]["status"] == "open")
            _cfg.CFG["caller_keys"] = {"item_project": "projects/alpha"}

            # B: a weak public key is refused at enroll
            wipe(); reset_limits()
            P = 2 ** 255 - 19
            weak = {"the identity point": b"\x01" + b"\x00" * 31, "y = 0 (order 4)": b"\x00" * 32, "y = -1 (order 2)": b"\xec" + b"\xff" * 30 + b"\x7f", "the identity, not canonical (y = p + 1)": (P + 1).to_bytes(32, "little"),
                    "an order-8 point": bytes.fromhex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"), "another order-8 point": bytes.fromhex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"),
                    "y = 0, the other sign (order 4)": b"\x00" * 31 + b"\x80", "the identity with the sign bit set": b"\x01" + b"\x00" * 30 + b"\x80"}
            got = {n: post("/keys/enroll", {"public_key": b64(raw), "label": "x", "sender": "x"}) for n, raw in weak.items()}
            check("a weak public key (the identity, a point of small order, a non-canonical one) is 400 at enroll and is kept nowhere", all(r.status_code == 400 and "weak" in r.json()["error"] for r in got.values()) and not PENDING.exists(), {n: r.status_code for n, r in got.items()})
            check("…a key a caller really holds is not weak", all(not K.weak_key(base64.urlsafe_b64decode(Caller().pub + "=")) for _ in range(8)) and enroll(Caller()).status_code == 200)

            # C: a key file that cannot be read is never written over
            wipe(); reset_limits(); k = Caller(); enroll(k); K.approve(k.fp[:16]); m = Caller(); enroll(m)
            def cli(*argv):
                err = io.StringIO()
                with contextlib.redirect_stdout(err), contextlib.redirect_stderr(err): rc = _client.main(["client", "keys", *argv])
                return rc, err.getvalue()
            for junk_text in ("{not json", "[1]", ""):
                APPROVED.write_text(junk_text)
                rc_a, out_a = cli("approve", m.fp[:12]); rc_r, out_r = cli("revoke", k.fp[:12]); rc_l, out_l = cli("list")
                check(f"an approved-keys file that is {junk_text!r} is refused by approve, revoke and list (exit 1, a clear line) and left as it is; the pending key stays pending", rc_a == rc_r == rc_l == 1 and "keys.json" in out_a and "nothing was written" in out_a
                      and APPROVED.read_text() == junk_text and m.fp in K.pending(), (rc_a, rc_r, rc_l, out_a, APPROVED.read_text()))
            check("…the same for a server that cannot take an enroll (503, the file unchanged)", enroll_from(Caller(), "192.0.2.31").status_code == 503 and APPROVED.read_text() == "" and m.fp in K.pending())
            APPROVED.unlink()
            PENDING.write_text("garbage"); r = enroll_from(Caller(), "192.0.2.32"); rc_p, out_p = cli("approve", m.fp[:12])
            check("a pending-keys file that cannot be read is refused too: enroll is 503 and approve exit 1, the file unchanged", r.status_code == 503 and rc_p == 1 and PENDING.read_text() == "garbage", (r.status_code, rc_p, out_p))
            PENDING.unlink()
            check("a file that is not there is an empty list: an enroll is kept", enroll_from(Caller(), "192.0.2.33").status_code == 200 and len(K.pending()) == 1)

            # D: the settle approves with the whole fingerprint and closes the item only when the approve took
            wipe(); reset_limits(); d1 = Caller(); enroll(d1); gd = open_items()[0][0]; answer(gd, "Approve")
            calls = []; real_approve = K.approve
            K.approve = lambda prefix, *a, **kw: (calls.append(prefix), ("", None))[1]
            try: CP.settle()
            finally: K.approve = real_approve
            check("the settle asks for the whole 64-character fingerprint, and an approve that did not take leaves the item open and the key pending", calls == [d1.fp] and d1.fp in K.pending() and d1.fp not in K.approved()
                  and [it for g, it in items() if g == gd][0]["status"] == "open", (calls, [it["status"] for g, it in items()]))
            CP.settle()
            check("…and the next settle, with the approve working, approves it and closes the item", d1.fp in K.approved() and [it for g, it in items() if g == gd][0]["status"] == "completed")
            d2 = Caller(); enroll(d2); gr = [g for g, it in open_items() if it["metadata"]["caller_key"] == d2.fp][0]; answer(gr, "Reject")
            real_revoke = K.revoke; rcalls = []
            K.revoke = lambda prefix, *a, **kw: (rcalls.append(prefix), ("", ""))[1]
            try: CP.settle()
            finally: K.revoke = real_revoke
            check("a revoke that did not take leaves a rejected key's item open too, and asks with the whole fingerprint", rcalls == [d2.fp] and [it for g, it in items() if g == gr][0]["status"] == "open")

            # E: an IPv4-mapped IPv6 address is the IPv4 address
            reset_limits()
            check("an IPv4-mapped IPv6 address is counted as its IPv4 address; other IPv6 addresses by their /64", CP._source("::ffff:192.0.2.9") == CP._source("192.0.2.9") == "192.0.2.9" and CP._source("2001:db8:1:2:3::4") == "2001:db8:1:2::/64"
                  and CP._source("::ffff:192.0.2.9") != CP._source("::ffff:192.0.2.10"))
            mapped = [trade_from("a.b.c", "::ffff:192.0.2.9").status_code for _ in range(62)]
            check("62 junk claims from one IPv4-mapped address: 429 from the 61st, while another mapped address and the plain IPv4 neighbour are not held", mapped[:60] == [400] * 60 and mapped[60:] == [429, 429]
                  and trade_from("a.b.c", "::ffff:192.0.2.10").status_code == 400 and trade_from("a.b.c", "192.0.2.11").status_code == 400, mapped[58:])

            # F: the source tag is keyed by a secret the server keeps
            wipe(); reset_limits(); tag = _src_tag("192.0.2.40"); SRC_KEY = SEC / "keys-source.key"
            unsalted = hashlib.sha256(("caller-key-source:" + CP._source("192.0.2.40")).encode()).hexdigest()[:12]
            check("the source tag is not the plain hash of the address, is stable, and the secret it needs is a 32-byte file (0600) of the server's", tag != unsalted and tag == _src_tag("192.0.2.40") and tag != _src_tag("192.0.2.41")
                  and SRC_KEY.exists() and SRC_KEY.stat().st_size == 32 and stat.S_IMODE(os.stat(SRC_KEY).st_mode) == 0o600 and len(tag) == 12, (tag, unsalted))
            SRC_KEY.unlink()
            check("…and another secret gives another tag for the same address", _src_tag("192.0.2.40") != tag)
            check("the pending file keeps neither the address nor its plain hash", (enroll_from(Caller(), "192.0.2.40"), unsalted not in PENDING.read_text() and "192.0.2.40" not in PENDING.read_text())[1])

            # G: the ceiling over all enrolls is 300 in 10 minutes
            wipe(); reset_limits()
            codes = [CP.enroll({"public_key": "bad", "label": "x", "sender": "x"}, f"2001:db8:{i:x}::1")[0] for i in range(302)]
            check("300 junk enrolls from 300 different addresses spend the ceiling: the 301st, from yet another address, is 429, and so is a valid one", codes[:300] == [400] * 300 and codes[300:] == [429, 429]
                  and enroll_from(Caller(), "203.0.113.5").status_code == 429, (codes[298:],))
            CLOCK[0] += 601
            check("…and the window moves on", enroll_from(Caller(), "203.0.113.6").status_code == 200)

            # ---- 14. the third review's lows
            # L1: a label or a sender from a caller with no token is shown on the board; a bare domain there is drawn as a link, so no `.` is taken
            wipe(); reset_limits(); _cfg.CFG["caller_keys"] = {"item_project": "projects/alpha"}
            n_open = len(open_items())
            refused = [enroll(Caller(), label="login.example.com").status_code, enroll(Caller(), sender="pay.example.co").status_code, enroll(Caller(), sender="login.example.com").status_code, enroll(Caller(), label="see pay.example.co").status_code]
            check("a label or a sender with a dot (a domain the board would draw as a link) is 400 at enroll, and nothing is kept or raised", refused == [400] * 4 and not PENDING.exists() and len(open_items()) == n_open, refused)
            good_ok = [enroll(Caller(), label="the fleet tool", sender=sn).status_code for sn in ("my-agent", "agent_1", "alpha")]
            check("…while a legitimate label and sender (my-agent, agent_1, alpha) are kept pending", good_ok == [200] * 3 and len(K.pending()) == 3, good_ok)
            wipe(); reset_limits(); shown_key = Caller(); enroll(shown_key, label="the fleet tool", sender="alpha"); it0 = [it for g, it in open_items() if it["metadata"]["caller_key"] == shown_key.fp][0]
            check("the item shows the label and the sender in code spans (description and ask)", "label `the fleet tool`, sender `alpha`" in it0["description"] and "may call as `alpha`" in it0["metadata"]["ask"], (it0["description"], it0["metadata"]["ask"]))

            # L2: a caller with no right learns nothing of a fingerprint before a signature has verified
            wipe(); reset_limits()
            ka, kp, ku, stranger = Caller(), Caller(), Caller(), Caller()
            enroll(ka); K.approve(ka.fp[:16]); enroll(kp)
            answers = {"approved key, another's signature": trade(ka.claim(sk=stranger.sk)), "pending key, another's signature": trade(kp.claim(sk=stranger.sk)),
                       "unknown key, another's signature": trade(ku.claim(sk=stranger.sk)), "unknown key, its own signature": trade(ku.claim())}
            shape = {n: (r.status_code, r.json()) for n, r in answers.items()}
            check("a claim whose signature is not the named key's gets ONE answer (403, the same body, state unknown) for an approved, a pending and an unknown fingerprint", len({json.dumps(v, sort_keys=True) for v in shape.values()}) == 1
                  and all(v[0] == 403 and v[1]["state"] == "unknown" for v in shape.values()), shape)
            r = trade(kp.claim())
            check("a pending key's claim signed with its own key is told 403 pending (only a verified signature may be)", r.status_code == 403 and r.json()["state"] == "pending", (r.status_code, r.text))
            check("…and nothing of this makes a pass", not CP._PASSES)
            # an enroll of an approved key says approved and names no item
            wipe(); reset_limits(); ke = Caller(); first = enroll(ke).json(); K.approve(ke.fp[:16])
            again = enroll(ke).json()
            check("a key that already waited with an item and is approved: enrolling it again answers approved, the same fingerprint and no item", bool(first["item"]) and json.loads(APPROVED.read_text())[ke.fp].get("item") == first["item"]
                  and again["state"] == "approved" and again["fingerprint"] == ke.fp and again["item"] == "", (first, again))
            check("…while a waiting key's repeated enroll still names its item", (lambda c_: enroll(c_).json()["item"] == enroll(c_).json()["item"] != "")(Caller()))

            # L5: the lock file, and a hand-edited enrolled_at
            wipe(); LOCK = SEC / "keys.lock"; LOCK.unlink(missing_ok=True); old_umask = os.umask(0o022)
            try:
                K.enroll(Caller().pub, "x", "x"); made = stat.S_IMODE(os.stat(LOCK).st_mode)
                LOCK.chmod(0o644); K.enroll(Caller().pub, "x", "x"); mended = stat.S_IMODE(os.stat(LOCK).st_mode)
            finally: os.umask(old_umask)
            check("keys.lock is 0600 like its neighbors, with an ordinary umask, and one an earlier version made 0644 is mended", made == 0o600 and mended == 0o600, (oct(made), oct(mended)))
            wipe(); reset_limits(); keep, hand = Caller(), Caller(); enroll(keep); enroll(hand)
            edited = json.loads(PENDING.read_text())
            for bad_val in ("soon", [1], {"a": 1}, float("inf"), "nan"):
                edited[hand.fp]["enrolled_at"] = bad_val; PENDING.write_text(json.dumps(edited))
                try: got_p = K.pending(); outcome = (sorted(got_p) == [keep.fp])
                except Exception as e_: outcome = f"raised {type(e_).__name__}"
                check(f"a pending entry whose enrolled_at is {bad_val!r} is dropped as expired, never an error; the others stay", outcome is True, outcome)
            edited[hand.fp]["enrolled_at"] = "soon"; PENDING.write_text(json.dumps(edited))
            r = enroll(Caller())
            check("…and an enroll over such a file is 200, not 500 (the bad entry is gone from the list after it)", r.status_code == 200 and hand.fp not in json.loads(PENDING.read_text()) and keep.fp in json.loads(PENDING.read_text()), (r.status_code, r.text))

            # the gaps the mutants showed
            # (a) a stale claim (expired, or for another board) is counted for its source address
            wipe(); reset_limits(); k = Caller(); enroll(k); K.approve(k.fp[:16])
            old = k.claim(iat=CLOCK[0] - 50, exp=CLOCK[0] - 10)
            same_old = [trade_from(old, "198.51.100.88").status_code for _ in range(62)]
            check("one address sending an expired signed claim 62 times: 401 for 60, then 429 (a stale claim is counted for its source address)", same_old[:60] == [401] * 60 and same_old[60:] == [429, 429], same_old[58:])
            reset_limits(); elsewhere = k.claim(aud="https://elsewhere.example.org")
            same_aud = [trade_from(elsewhere, "198.51.100.89").status_code for _ in range(62)]
            check("…and a claim for another board the same", same_aud[:60] == [401] * 60 and same_aud[60:] == [429, 429] and trade_from(k.claim(), "198.51.100.90").status_code == 200, same_aud[58:])
            # (b) a used claim is refused for the whole of its life, not only at the instant it was used
            reset_limits(); lived = k.claim(jti="jti-whole-life-1", exp=CLOCK[0] + 60); t0 = CLOCK[0]
            used_now = trade(lived)
            CLOCK[0] = t0 + 5; replay5 = trade(lived)
            CLOCK[0] = t0 + 55; replay55 = trade(lived)
            CLOCK[0] = t0
            check("a claim used once and sent again 5 and 55 seconds later (still inside its life and the clock skew) is 401 jti both times", used_now.status_code == 200 and replay5.status_code == 401 and "jti" in replay5.json()["error"]
                  and replay55.status_code == 401 and "jti" in replay55.json()["error"], (used_now.status_code, replay5.text, replay55.text))
            # (c) a non-canonical encoding of a valid point (y >= p) is refused at enroll
            y3 = (3).to_bytes(32, "little"); y3_noncanonical = (3 + P).to_bytes(32, "little")
            check("the point y = 3 is a valid key in its canonical form, and the same point written as y + p (not canonical) is weak", not K.weak_key(y3) and K.weak_key(y3_noncanonical))
            wipe(); reset_limits()
            r_ok, r_nc = post("/keys/enroll", {"public_key": b64(y3), "label": "x", "sender": "x"}), post("/keys/enroll", {"public_key": b64(y3_noncanonical), "label": "x", "sender": "x"})
            check("…at enroll the canonical one is kept and the non-canonical one is 400 weak, kept nowhere", r_ok.status_code == 200 and r_nc.status_code == 400 and "weak" in r_nc.json()["error"] and list(json.loads(PENDING.read_text())) == [hashlib.sha256(y3).hexdigest()], (r_ok.status_code, r_nc.status_code, r_nc.text))

    finally:
        pass

    return ran, fails

MARK = "@@client part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"client": part_client, "caller_keys": part_caller_keys}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as both suites always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: client scenario, {total} checks")
