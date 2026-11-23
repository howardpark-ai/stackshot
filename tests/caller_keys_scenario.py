"""Scenario test for a caller trusted by a key of its own (fleet/caller_keys.py, service/caller_pass.py, the /keys routes and the pass gate of the form's calls in web/routes/client_api.py,
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

    tests/run-suite caller_keys        → exit 0 / 1"""
import base64, contextlib, io, json, logging, os, pathlib, re, stat, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
BOARD = "https://board.example.org"
tmp = _scratch.mkdtemp(prefix="callerkeys-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
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
_web_page_debts._refuse_if_owing = lambda debtor: None
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

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
