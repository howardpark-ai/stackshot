"""caller_pass.py: a caller trusted by a key of its own, not by the machine it runs on: enrolling the key, the signed claim, the pass, and the gate that takes a pass.

The routes (web/routes/client_api.py) hand their body to `enroll` and `claim_pass`, and a request's bearer to `pass_machine`; the store of keys is fleet/caller_keys.py.

  enroll(body)      `POST /keys/enroll` {public_key, label, sender}, no token. The key is kept as pending and is trusted for nothing; one board item (needs: decision) asks the owner whether to trust it,
                    in the project [caller_keys] item_project names ("" = no item: the command line `stackshot client keys approve` is the way). At most 5 keys wait, at most 3 of them from one source address;
                    10 enrolls in 10 minutes from one source address (and a ceiling over all of them). A key that is already approved answers the state `approved` and no board item (`item` is ""): whoever
                    sends a public key is not told the item of an approved key.
  claim_pass(body)  `POST /keys/pass` {claim}: the claim is a compact JWS signed with the approved key (alg EdDSA; claims iss = the key's fingerprint, aud = the board's origin, iat, exp, jti). It is
                    refused when the signature is wrong, the audience is not this board, it is expired, its life is over 60 s, its clock is over 60 s off, its jti was used before, or the key is
                    not approved. Else a pass: an opaque token for 10 minutes, kept in memory only (a restart of the server ends every pass), tied to the key's fingerprint and sender.
                    The signature is checked first, because it costs little and nothing else can be told from a caller who has no right to ask. What is told before it has verified is the same for every
                    fingerprint (403, `state` unknown: for an approved key with a signature that is not its own, for a pending key and for a key the server never heard of alike, and the same signature check is made for each), so
                    no caller can learn whether a fingerprint is approved or pending; only a claim signed with the key itself may be told that the key is pending, or why a claim of an approved key fails.
                    Then what a replay or a stale claim shows without any state of the key's
                    (its audience, its times, a jti that was used): such a claim is the source address's to pay for, since anyone who has once seen a signed claim can send it again. Only a claim that is fresh,
                    for this board and unused is limited per key (30 a minute), whoever else is calling, and nothing but such a claim counts there; every other request (no claim, no key, a bad signature, a stale
                    or used claim) is limited per source address and under a high ceiling over all sources.
  pass_machine(tok) a request's bearer token -> "pass:<fingerprint>" when it is a live pass of an approved key, else "". That string stands where a machine's name stands: `projects._form_call`
                    takes it as the New session form's caller when the call's `sender` is the key's (`sender_covers`); a machine token is never a pass and a pass never a machine.
  settle()          the keys and their board items agree: a pending key whose item the owner answered Approve is approved, Reject is deleted; an item whose key is approved (here, or on the command
                    line) or gone is closed. A key's own item is found by the id kept on its entry (no scan of the store): the pending keys' at each enroll, a key's own at its first verified claim. The one
                    scan of the whole store (for the items of keys that are gone) runs at an enroll at most once a minute. So no hook or timer is needed, and no request makes the server read the store.

Verifying an Ed25519 signature needs the `cryptography` package, which the server's own dependencies bring (fastmcp -> authlib); it is imported where it is used, so a server without it still
runs and answers the pass route 503 with the reason.

A service module: it reads the config and the project record and writes through `create_item` and the update tool's code. Imports point down only."""
from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import math
import re
import secrets
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet import caller_keys as _keys
from stackshot.github import ghsync as _gh
from stackshot.model import bullet_text as _bt
from stackshot.model import member_gates as _mgates
from stackshot.model.field_gates import _description_limits, _fit, _subject_max
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import answer_handover as _ah
from stackshot.service import create as _create_svc
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes

MACHINE_PREFIX = "pass:"           # a pass stands in for a machine's name as "pass:<fingerprint>"; a machine name never holds a colon (client.py mint)
PASS_PREFIX = "ssp_"               # what a pass token starts with, so a bearer is told from a machine token at a glance
PASS_TTL = 600                     # a pass lasts 10 minutes
CLAIM_LIFE_MAX = 60                # a claim's exp - iat, in seconds
SKEW_MAX = 60                      # how far a claim's iat may be from the server's clock, in seconds
PASSES_PER_KEY = 20                # live passes one key may hold; the oldest goes when it takes a 21st
JTI_MAX = 5000                     # one-time ids kept at once
NUMBER_MAX = 1e12                  # a claim's iat and exp are seconds: a number past this (or not finite) is no time
CLAIM_MAX = 2048                   # the claim's length in characters
BY = "stackshot (key enrollment)"  # who the board items and their closes are written by
APPROVE, REJECT = "Approve", "Reject"

_now = time.time                   # a suite sets its own clock here
_LOCK = threading.Lock()
_PASSES: dict[str, dict[str, Any]] = {}      # sha256 of the token -> {fp, sender, exp}
_JTIS: dict[tuple[str, str], float] = {}     # (fingerprint, jti) -> when it may be forgotten
_RAISE_LOCK = threading.Lock()
_SETTLED: set[str] = set()                    # keys whose item settle() has looked at since the server started
SWEEP_EVERY = 60                              # seconds between two scans of the whole store (an enroll starts one, at most this often)
_LAST_SWEEP = 0.0
_B64 = re.compile(r"[A-Za-z0-9_-]+")
_DUMMY_KEY = bytes.fromhex("58" + "66" * 31)   # Ed25519's base point: a public key no claim is signed with here, only checked against when the claim names no key we hold


class RateLimit:
    """At most `limit` calls in `window` seconds for each key (a source address, a fingerprint, or "" for all of a kind). The table is bounded: a new key past MAX_KEYS pushes out the one seen longest ago."""
    MAX_KEYS = 10000

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window, self.hits = limit, window, {}
        self.lock = threading.Lock()

    def allow(self, key: str = "") -> float:
        """0 when the call may go on (and is counted), else the seconds to wait (a refused call is not counted)."""
        with self.lock:
            now = _now()
            mine = [t for t in self.hits.get(key, ()) if now - t < self.window]
            if len(mine) >= self.limit:
                self.hits[key] = mine
                return max(1.0, self.window - (now - mine[0]))
            mine.append(now)
            if key not in self.hits and len(self.hits) >= self.MAX_KEYS:
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.window}
                if len(self.hits) >= self.MAX_KEYS:
                    del self.hits[min(self.hits, key=lambda k: self.hits[k][-1])]
            self.hits[key] = mine
            return 0.0


# Who may ask how often. A caller with no token proves nothing before its signature is checked, so the limits are two kinds: per source address for what proved nothing (the ceiling over all sources
# only bounds the server's work: a source counts against it only while it is inside its own limit, so one source cannot use it up), and per key for a claim whose signature verified, which no other
# caller can use up. The address is the connection's, as uvicorn gives it (`request.client`): the peer, or the client the loopback proxy in front of the server names in X-Forwarded-For.
ENROLL_SOURCE = RateLimit(10, 600)       # enrolls from one address
ENROLL_CEILING = RateLimit(300, 600)     # …and from all of them
CLAIM_SOURCE = RateLimit(60, 60)         # claims that did not verify, from one address
CLAIM_CEILING = RateLimit(600, 60)       # …and from all of them
CLAIM_KEY = RateLimit(30, 60)            # claims that verified, for one key


def reset_limits() -> None:
    """Forget every count: a suite's reset."""
    for r in (ENROLL_SOURCE, ENROLL_CEILING, CLAIM_SOURCE, CLAIM_CEILING, CLAIM_KEY):
        with r.lock:
            r.hits.clear()


def _source(addr: str) -> str:
    """A connection's address as the limits and the pending cap count it: an IPv4-mapped IPv6 address (::ffff:a.b.c.d) as the IPv4 address it carries, any other IPv6 address by its /64 (one subscriber
    holds the whole of it), anything else as it is, "" as "-"."""
    a = str(addr or "").strip()
    try:
        ip = ipaddress.ip_address(a)
    except ValueError:
        return a[:64] or "-"
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def _source_tag(addr: str) -> str:
    """What a pending key keeps of its source: a short keyed hash (fleet/caller_keys.py `source_tag`), never the address."""
    return _keys.source_tag(_source(addr))


def _unavailable() -> tuple[int, dict[str, Any]] | None:
    return (503, {"error": _ro.REFUSAL}) if _ro.is_read_only() else None


def _slow(source: str, per_source: RateLimit, ceiling: RateLimit) -> tuple[int, dict[str, Any]] | None:
    wait = per_source.allow(_source(source)) or ceiling.allow("")
    return (429, {"error": f"too many calls; try again in {int(wait) + 1} seconds", "retry_after": int(wait) + 1}) if wait else None


# ----------------------------------------------------------------------------- enroll
def enroll(body: dict[str, Any], source: str = "") -> tuple[int, dict[str, Any]]:
    """`POST /keys/enroll` {public_key, label, sender} -> 200 {state: pending | approved, fingerprint, short, item}; 400 a bad body or a weak key, 429 too many calls from the source address, too many keys waiting (in all, or
    from this source address), 503 a standby copy or a key file the server cannot read (nothing is written). `source` is the connection's address (the route's `request.client`).
    A key already approved or already waiting answers its state and changes nothing. `item` is the board item that asks the owner of a pending key ("" when [caller_keys] item_project is not set or the item
    could not be filed, and always "" for an approved key: the answer says that the key is approved, never which item it had)."""
    gone = _unavailable() or _slow(source, ENROLL_SOURCE, ENROLL_CEILING)
    if gone:
        return gone
    pub = body.get("public_key")
    raw = _keys.decode_key(pub)
    if raw is None:
        return 400, {"error": "public_key = an Ed25519 public key: its 32 raw bytes in base64url without padding (43 characters)"}
    if _keys.weak_key(raw):
        return 400, {"error": "public_key is a weak key (a point of the curve that is not a public key anyone holds the secret of, or not in its canonical form): make a key pair and send its public half"}
    label, sender = _keys.label_text(body.get("label")), _keys.sender_text(body.get("sender"))
    if not label or not sender:
        return 400, {"error": f"label and sender are required, each starting with a letter or digit and at most {_keys.LABEL_MAX} characters: label = what the key is for (letters, digits, spaces and . _ , + -), "
                              "sender = the label its calls carry (letters, digits and . _ -)"}
    try:
        from stackshot.service import owner_words as _owner_words
        _owner_words._sender_not_owner(sender)
    except ToolError as e:
        return 400, {"error": str(e)}
    _settle_waiting()                           # the owner's answers on the waiting keys' items, read by id: a Reject frees its place before this key is counted
    _sweep()
    try:
        state, fp, entry = _keys.enroll(str(pub), label, sender, source=_source_tag(source))
    except (_keys.KeysFileError, OSError) as e:
        print(f"caller keys: enroll refused: {e}", file=sys.stderr, flush=True)
        return 503, {"error": "the server cannot read its list of keys just now, so this key was not kept; the reason is in the server's log"}
    if state == "full":
        return 429, {"error": f"{_keys.MAX_PENDING} keys already wait for the owner's answer; one must be approved or revoked (or expire, after {_keys.PENDING_TTL // 86400} days) first"}
    if state == "busy":
        return 429, {"error": f"{_keys.MAX_PENDING_PER_SOURCE} keys from this address already wait for the owner's answer; one must be approved or revoked (or expire, after {_keys.PENDING_TTL // 86400} days) first"}
    item = str((entry or {}).get("item") or "") if state == "pending" else ""      # an approved key's board item is not told: the answer to an enroll names no item of someone else's key
    if state == "pending" and not item:
        item = _raise_item(fp, entry or {})
    return 200, {"state": state, "fingerprint": fp, "short": _keys.short(fp), "item": item}


def _front_and_rec(project: str) -> tuple[dict[str, Any], list[str]] | None:
    try:
        recs = _prj.refs(project, _registry("projects"))
    except ValueError:
        return None
    if len(recs) != 1:
        return None
    front = _item_read._front_keepers(recs[0]["key"])
    return (recs[0], front) if front else None


def _marked_items() -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """The open items marked as a key's, by fingerprint, with their records: one scan of the store (the mark is read as text first, so a store of thousands is cheap to scan)."""
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for gid, p in _item_files():
        try:
            if '"caller_key"' not in p.read_text(encoding="utf-8"):
                continue
            it = _svcstore._load(gid)
        except (OSError, ValueError, ToolError):
            continue
        fp = str((it.get("metadata") or {}).get("caller_key") or "")
        if it.get("status") == "open" and fp:
            out.setdefault(fp, []).append((gid, it))
    return out


def _open_items(fp: str) -> list[tuple[str, dict[str, Any]]]:
    return _marked_items().get(fp or "", [])


ASK_MAX = 240                      # the board's limit for an ask line, in characters


def _ask_line(short: str, sender: str) -> str:
    """The question the item puts to the owner. Its Stakes part says what approving gives: the whole of the New session form, and every sender label that starts with the key's own and a dash. A long sender
    is shortened here to keep the line inside the board's limit (the item's description holds it whole). The sender is in a code span, so the board never draws anything the caller wrote as a link."""
    for cut in (len(sender), 24, 16, 8):
        s = sender if cut == len(sender) else sender[:cut - 1] + "…"
        ask = (f"Decide: whether key {short} may call as `{s}` · Recommend: {REJECT} unless you enrolled it · "
               f"Stakes: it gets the whole New session form (register an agent, rename, retire, For you) and every `{s}-…` label · By: no date")
        if len(ask) <= ASK_MAX:
            return ask
    return ask


def _raise_item(fp: str, entry: dict[str, Any]) -> str:
    """The one board item that asks the owner about a pending key -> its id as shown, "" when none is filed (no project set, none that lists a front agent, or the board refused it: the key stays pending
    and `keys approve` still works). Filed as a script's decision item, as the question route files one (create_item, the create tool's own code)."""
    project = str(_cfg.get("caller_keys", "item_project") or "").strip()
    if not project:
        return ""
    short = _keys.short(fp)
    try:
        with _RAISE_LOCK:                       # the look for an open item and the create are one step, so two enrolls of one key file one item
            have = _open_items(fp)
            for old_gid, old in have:           # an item the owner already answered is the answer to an earlier enroll of this key: it is closed, never reused for this one
                if _decision_of(old) is not None:
                    _close(old_gid, fp, "dropped", "the key enrolled again; this item answered the earlier enroll")
            have = [(g, it) for g, it in have if _decision_of(it) is None]
            if have:
                gid = have[0][0]
            else:
                got = _front_and_rec(project)
                if not got:
                    print(f"caller keys: no item for {short}: {project!r} is no project that lists a front agent", file=sys.stderr, flush=True)
                    return ""
                rec, front = got
                max_lines, line_max = _description_limits()
                desc = _bt.bullets("\n".join([
                    f"A caller asked to be trusted by a key of its own: label `{entry.get('label', '')}`, sender `{entry.get('sender', '')}`",
                    f"The key's fingerprint starts {short} (the whole of it is in `stackshot client keys list` on the server box)",
                    f"Approve on this item, or run `stackshot client keys approve {short}` on the server box; Reject drops the key",
                    "Until you answer, the key is trusted for nothing",
                ]), max_lines, line_max)
                subject = f"decide whether to trust the caller key {short}"
                ask = _ask_line(short, str(entry.get("sender", "")))
                options = [{"label": APPROVE, "line": "Trust this key for its sender label", "recommended": False},
                           {"label": REJECT, "line": "Drop the key; nothing changes", "recommended": True}]
                _writes.QUESTION.on = True
                try:
                    gid, _reply = _create_svc.create_item(subject=_fit(_svcstore._shown_ids(subject), _subject_max()), description=desc, project=rec["key"], owner=front[0], then=front[0],
                                                          needs=["decision"], ask=ask, options=options, by=BY, extra={"caller_key": fp})
                finally:
                    _writes.QUESTION.on = False
            shown = _gh.shown(gid)
        _keys.set_item(fp, shown, gid)
        return shown
    except (ToolError, OSError, ValueError, _keys.KeysFileError) as e:
        print(f"caller keys: no item for {short}: {e}", file=sys.stderr, flush=True)
        return ""


def settle() -> None:
    """Make the keys and their board items agree, by one scan of the whole store (see the module's text). Never raises: a failure is a line on stderr, and the next call tries again."""
    try:
        for fp, have in _marked_items().items():
            _settle_one(fp, have)
    except Exception as e:  # noqa: BLE001 — the callers are the routes, which must answer whatever the board does
        print(f"caller keys: settle failed: {e}", file=sys.stderr, flush=True)


def _sweep() -> None:
    """`settle()` at most once in SWEEP_EVERY seconds: the one place a request makes the server scan the store (for the items of keys that are gone), and only an enroll that passed its limits."""
    global _LAST_SWEEP
    now = _now()
    with _LOCK:
        if now - _LAST_SWEEP < SWEEP_EVERY:
            return
        _LAST_SWEEP = now
    settle()


def _entry_item(fp: str, entry: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The open item an entry of the key files names (`item_id`), read by its id: [] when none is kept, it is gone or closed, or it is not marked as this key's."""
    gid = str((entry or {}).get("item_id") or "")
    if not gid:
        return []
    try:
        it = _svcstore._load(gid)
    except (OSError, ValueError, ToolError, IndexError):
        return []
    return [(gid, it)] if it.get("status") == "open" and str((it.get("metadata") or {}).get("caller_key") or "") == fp else []


def _settle_entry(fp: str, entry: dict[str, Any]) -> None:
    """`_settle_one` for the one key, with the item its entry names: no scan. Never raises."""
    try:
        _settle_one(fp, _entry_item(fp, entry))
    except Exception as e:  # noqa: BLE001
        print(f"caller keys: settle of {_keys.short(fp)} failed: {e}", file=sys.stderr, flush=True)


def _settle_waiting() -> None:
    """The owner's answers on the items of the keys that wait (at most MAX_PENDING reads, by id)."""
    for fp, e in _keys.pending().items():
        _settle_entry(fp, e)


def _decision_of(it: dict[str, Any], since: float = 0.0) -> tuple[str, float] | None:
    """The owner's newest decision on an item -> (the label he chose, when), None when he has decided nothing, or (with `since`) nothing since that time."""
    ans = _ah._hooks().answers_of(it)
    a = next((x for x in reversed(ans or []) if x.get("kind") != "comment" and _mgates.owners(x)), None)      # another member's decision approves and rejects nothing
    if not a:
        return None
    try:
        ts = float(a.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    return (str(a.get("choice") or "").strip().lower(), ts) if ts >= since else None


def _settle_one(fp: str, have: list[tuple[str, dict[str, Any]]]) -> None:
    for gid, it in have:
        done, reason = "", ""
        if _keys.lookup_approved(fp):
            done, reason = "done", "the key is approved"
        elif fp in _keys.pending():
            # only an answer given after the key enrolled counts: one on an item of an earlier enroll of the same key is not an answer to this one
            got = _decision_of(it, _keys.enrolled_at(_keys.pending()[fp]))
            choice = got[0] if got else ""
            if choice == APPROVE.lower():
                if not _keys.approve(fp)[0]:
                    print(f"caller keys: {_keys.short(fp)} was not approved: it is no longer waiting; the item stays open", file=sys.stderr, flush=True)
                    continue
                done, reason = "done", f"{OWNER} approved the key"
            elif choice == REJECT.lower():
                if not _keys.revoke(fp)[0]:
                    print(f"caller keys: {_keys.short(fp)} was not dropped: it is no longer waiting; the item stays open", file=sys.stderr, flush=True)
                    continue
                done, reason = "dropped", f"{OWNER} rejected the key"
        else:
            done, reason = "dropped", "the key is gone (revoked or expired)"
        if done:
            _close(gid, fp, done, reason)


def _close(gid: str, fp: str, outcome: str, reason: str) -> None:
    max_lines, line_max = _description_limits()
    desc = _bt.bullets(f"The caller key {_keys.short(fp)}: {reason}", max_lines, line_max)
    _writes.QUESTION.on = _writes.TERMINAL_ROW.on = True       # a script's row: no alarm-word judgement, no page owed, no session told
    try:
        _update_svc._update(gid, outcome_text=desc, status="completed", outcome=outcome, reason=reason, sender=BY)
    finally:
        _writes.QUESTION.on = _writes.TERMINAL_ROW.on = False


# ----------------------------------------------------------------------------- the claim and the pass
def _b64(s: str) -> bytes | None:
    if not s or not _B64.fullmatch(s):
        return None
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError):
        return None


def _audiences() -> set[str]:
    """What a claim's aud may be: the board's address ([instance] board_url) as written without a closing slash, and its origin (scheme, host and port) -- an empty set when no address is set."""
    url = str(_cfg.get("instance", "board_url") or "").strip().rstrip("/")
    u = urlsplit(url)
    if not (u.scheme and u.netloc):
        return set()
    return {url, f"{u.scheme.lower()}://{u.netloc.lower()}"}


def _refuse(why: str, status: int = 401) -> tuple[int, dict[str, Any]]:
    return status, {"error": f"claim refused: {why}"}


def _parse_claim(body: dict[str, Any]) -> tuple[int, dict[str, Any]] | dict[str, Any]:
    """The claim's parts -> a dict {iss, signed (the bytes the signature covers), sig, pay}, or the (status, JSON) of a claim that cannot be read. Nothing here looks at a key."""
    claim = body.get("claim")
    if not isinstance(claim, str) or len(claim) > CLAIM_MAX or claim.count(".") != 2:
        return 400, {"error": "claim = a compact JWS: <header>.<payload>.<signature>, each part base64url, the whole at most 2048 characters"}
    head_b, pay_b, sig_b = claim.split(".")
    raw = [_b64(p) for p in (head_b, pay_b, sig_b)]
    if any(x is None for x in raw):
        return 400, {"error": "claim = a compact JWS: <header>.<payload>.<signature>, each part base64url"}
    try:
        header, pay = json.loads(raw[0]), json.loads(raw[1])
    except (ValueError, RecursionError):        # RecursionError: a part that nests arrays or objects deeper than the parser goes
        return 400, {"error": "claim: the header and the payload are JSON objects"}
    if not isinstance(header, dict) or not isinstance(pay, dict):
        return 400, {"error": "claim: the header and the payload are JSON objects"}
    if header.get("alg") != "EdDSA" or "crit" in header:
        return _refuse("the header's alg is EdDSA, and nothing else")
    iss = pay.get("iss")
    if not isinstance(iss, str) or not re.fullmatch(r"[0-9a-f]{64}", iss):
        return _refuse("iss = the key's fingerprint, 64 lowercase hex characters")
    return {"iss": iss, "signed": f"{head_b}.{pay_b}".encode("ascii"), "sig": raw[2] or b"", "pay": pay}


def _unproven(source: str, answer: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    """The answer to a request whose claim did not verify (unreadable, no such key, a signature that is not the key's): counted against its source address, and 429 when that is spent. The count is the
    address's own and the ceiling's, never a key's, so no number of these can make a key's verified claim wait."""
    return _slow(source, CLAIM_SOURCE, CLAIM_CEILING) or answer


def _number(v: Any) -> float | None:
    """A claim's iat or exp as a float, None when it is no number, not finite, or past NUMBER_MAX (a huge integer is no time, and converting it raises OverflowError)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and abs(f) <= NUMBER_MAX else None


def claim_pass(body: dict[str, Any], source: str = "") -> tuple[int, dict[str, Any]]:
    """`POST /keys/pass` {claim} -> 200 {pass, expires_in, fingerprint, sender}; 400 a claim that is no compact JWS, 401 a claim that fails after its signature verified (the reason is in `error`), 403 a key that is not
    approved (`state`: pending | unknown), 429 too many calls, 503 a standby copy, or no board address set, or no signature library. `source` is the connection's address (the route's `request.client`).
    What is told before a signature has verified is the same for every fingerprint: a claim whose signature is not the named key's, whether that key is approved, pending or not known at all, is 403 `state`
    unknown, and counts for the source address. Only a claim signed with the key itself may be told more (`state` pending for a key still waiting; the reason a claim of an approved key fails).
    The signature comes first; then a claim that is stale, for another board or already used is counted for its source address; only a claim that is fresh, for this board and unused is counted for the key
    (CLAIM_KEY) and for nobody else; any other request is counted for its source address."""
    gone = _unavailable()
    if gone:
        return gone
    c = _parse_claim(body)
    if isinstance(c, tuple):
        return _unproven(source, c)
    iss, pay = c["iss"], c["pay"]
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return 503, {"error": "this server has no signature library (the `cryptography` package), so it cannot verify a claim"}
    entry = _keys.lookup_approved(iss)
    waiting = None if entry else _keys.pending().get(iss)       # a key still waiting may prove it is its owner's: the owner may have answered the item since
    key = _keys.decode_key((entry or waiting or {}).get("public_key"))
    try:
        Ed25519PublicKey.from_public_bytes(key or _DUMMY_KEY).verify(c["sig"], c["signed"])        # an unknown key is checked against a fixed key, so the time it takes does not tell either
        proven = key is not None
    except (InvalidSignature, ValueError):
        proven = False
    if not proven:                                               # no key, or a signature that is not its own: ONE answer for an approved, a pending and an unknown key, so a caller with no right learns nothing of a fingerprint
        return _unproven(source, (403, {"error": "claim refused: the key is not approved", "state": "unknown"}))
    auds = _audiences()
    if not auds:
        return 503, {"error": "this server has no board address ([instance] board_url), so a claim has no audience to name"}
    stale = _stale(pay, auds)                   # a signed claim that is out of date, for another board or already used costs nothing to send again: the source address pays for it, never the key
    if stale:
        return _unproven(source, stale)
    jti = str(pay["jti"])
    with _LOCK:
        if _jti_used(iss, jti):
            return _unproven(source, _refuse("this jti was already used"))
    wait = CLAIM_KEY.allow(iss)                 # fresh, for this board and unused, and the signature is the key's own: from here the count is the key's
    if wait:
        return 429, {"error": f"too many calls; try again in {int(wait) + 1} seconds", "retry_after": int(wait) + 1}
    if waiting:
        _settle_entry(iss, waiting)             # the owner may have answered the board item: take it in before judging the key
        entry = _keys.lookup_approved(iss)
    elif entry.get("item_id") and iss not in _SETTLED:
        _SETTLED.add(iss)
        _settle_entry(iss, entry)               # a key approved on the command line: its item is closed at its first pass of this run
    if not entry:
        return 403, {"error": "claim refused: the key is not approved", "state": "pending" if iss in _keys.pending() else "unknown"}
    now = _now()
    with _LOCK:
        if _jti_used(iss, jti):                 # two claims of one jti at once: the second is the replay
            return _unproven(source, _refuse("this jti was already used"))
        if len(_JTIS) >= JTI_MAX:
            return 429, {"error": "too many claims in their first minute; try again shortly", "retry_after": 60}
        _JTIS[(iss, jti)] = float(_number(pay["exp"])) + SKEW_MAX
        for h in [h for h, p in _PASSES.items() if p["exp"] < now]:
            del _PASSES[h]
        mine = sorted((h for h, p in _PASSES.items() if p["fp"] == iss), key=lambda h: _PASSES[h]["exp"])
        for h in mine[:max(0, len(mine) - PASSES_PER_KEY + 1)]:
            del _PASSES[h]
        tok = PASS_PREFIX + secrets.token_urlsafe(32)
        _PASSES[hashlib.sha256(tok.encode()).hexdigest()] = {"fp": iss, "sender": str(entry.get("sender") or ""), "exp": now + PASS_TTL}
    return 200, {"pass": tok, "expires_in": PASS_TTL, "fingerprint": iss, "sender": str(entry.get("sender") or "")}


def _stale(pay: dict[str, Any], auds: set[str]) -> tuple[int, dict[str, Any]] | None:
    """The refusal of a claim that is not for this board, or whose numbers or times are wrong or past, else None. It looks at nothing of the key."""
    aud = pay.get("aud")
    if not isinstance(aud, str) or aud not in auds:
        return _refuse("aud is not this board")
    jti = pay.get("jti")
    iat, exp = _number(pay.get("iat")), _number(pay.get("exp"))
    if iat is None or exp is None or not isinstance(jti, str) or not 8 <= len(jti) <= 128 or any(ord(ch) < 33 or ord(ch) > 126 for ch in jti):
        return _refuse("iat and exp are numbers (seconds since the epoch) and jti is 8 to 128 printable characters")
    now = _now()
    if not 0 < exp - iat <= CLAIM_LIFE_MAX:
        return _refuse(f"its life (exp - iat) must be over 0 and at most {CLAIM_LIFE_MAX} seconds")
    if abs(now - iat) > SKEW_MAX:
        return _refuse(f"iat is more than {SKEW_MAX} seconds from the server's clock")
    if now > exp:
        return _refuse("it has expired")
    return None


def _jti_used(iss: str, jti: str) -> bool:
    """Was this key's jti used inside its life (the caller holds _LOCK); the ones past it are forgotten here."""
    now = _now()
    for k in [k for k, until in _JTIS.items() if until < now]:
        del _JTIS[k]
    return (iss, jti) in _JTIS


def pass_machine(authorization: str) -> str:
    """A request's Authorization header -> "pass:<fingerprint>" when it carries a live pass of a key that is approved now, else "". A key revoked after its pass was given stops at once."""
    tok = authorization[7:].strip() if authorization[:7].lower() == "bearer " else ""
    if not tok.startswith(PASS_PREFIX):
        return ""
    with _LOCK:
        p = _PASSES.get(hashlib.sha256(tok.encode()).hexdigest())
    if not p or p["exp"] < _now():
        return ""
    entry = _keys.lookup_approved(p["fp"])
    return MACHINE_PREFIX + p["fp"] if entry and entry.get("sender") == p["sender"] else ""


def is_pass(machine: str) -> bool:
    return machine.startswith(MACHINE_PREFIX)


def form_pass_ok(machine: str, sender: str) -> bool:
    """Is a call made with a pass the New session form's: the key is approved and the call's `sender` is the key's label or one that starts with it and a `-`."""
    entry = _keys.lookup_approved(machine[len(MACHINE_PREFIX):]) if is_pass(machine) else None
    return bool(entry) and _keys.sender_covers(str(entry.get("sender") or ""), sender)


def forget_passes(fp: str = "") -> None:
    """Drop every pass of a key (all keys with none named): a suite's reset."""
    with _LOCK:
        for h in [h for h, p in _PASSES.items() if not fp or p["fp"] == fp]:
            del _PASSES[h]
        if not fp:
            _JTIS.clear()
