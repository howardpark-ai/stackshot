"""caller_keys.py: the public keys a caller (the fleet tool) registers for itself, and the list the owner approves.

A caller that holds an Ed25519 key of its own sends the public half to the server (`POST /keys/enroll`, no token). It is kept as a PENDING key and is trusted for nothing. The owner
approves it (by his answer on the board item the server raises for it, or with `stackshot client keys approve <fingerprint>` on the server box); the key then stands in `keys.json`
beside `clients.json`, and the caller may trade a signed claim for a short pass (`POST /keys/pass`, service/caller_pass.py). Revoking deletes the entry.

Two files in the secrets directory, both written whole to a temporary file and swapped in with `os.replace` (0600), under one lock file (`keys.lock`, 0600, an exclusive `flock`) so the server and the
command line never write over each other:
  keys.json          {<fingerprint>: {"public_key", "label", "sender", "enrolled", "approved", "item", "item_id", "source"}}   the approved keys
  keys-pending.json  {<fingerprint>: {"public_key", "label", "sender", "enrolled", "item", "item_id", "source"}}               the keys waiting for the owner (at most MAX_PENDING, each kept PENDING_TTL)

The fingerprint is the SHA-256 of the key's 32 raw bytes in hex (64 characters, stored whole); it is shown as its first 16 (`short`). `public_key` is those 32 bytes in base64url without padding (43
characters). `sender` is the label family the key speaks as: a call's own label is that, or that and a `-` and more (`sala` covers `sala-web`). `item` is the board item raised for the key ("" when none), as
shown to a person, and `item_id` the same item's id in the store, which is how the server finds it without a scan. `source` is a short keyed hash (HMAC-SHA-256 under a secret the server keeps in `keys-source.key`, 0600) of the address the key was enrolled from (never the address, and not
a hash anyone can compute from an address), which counts the keys one address has waiting.

This module reads and writes files and knows nothing of signatures (service/caller_pass.py verifies them, with the one library that can) or of the board. Standard library only: the command line of a client box runs it."""
from __future__ import annotations

import base64
import binascii
import datetime
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from stackshot.core import config as _cfg

MAX_PENDING = 5                    # keys waiting for the owner at once; a sixth enroll is refused until one is approved, revoked or has expired
MAX_PENDING_PER_SOURCE = 3         # …of which at most this many from one source address, so one address cannot take every place
PENDING_TTL = 7 * 86400            # a pending key nobody answered in this many seconds is dropped
LABEL_MAX = 80                     # a label or a sender: one line of at most this many characters
MIN_PREFIX = 8                     # a fingerprint typed short must have at least this many characters, and name one key

_KEY_RE = re.compile(r"[A-Za-z0-9_-]{43}")      # 32 bytes in base64url, no padding
_THREAD = threading.Lock()


class KeysFileError(RuntimeError):
    """A key file that exists but cannot be read as a list of keys. Whatever would write that file refuses instead, so the keys in it are not lost to a write of the one key at hand."""


def _approved_path() -> Path:
    return Path(_cfg.secrets("keys.json"))


def _pending_path() -> Path:
    return Path(_cfg.secrets("keys-pending.json"))


def decode_key(public_key: Any) -> bytes | None:
    """The 32 raw bytes of a public key given as base64url without padding (exactly 43 characters), or None when it is anything else."""
    if not isinstance(public_key, str) or not _KEY_RE.fullmatch(public_key):
        return None
    try:
        raw = base64.urlsafe_b64decode(public_key + "=")
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 and base64.urlsafe_b64encode(raw).rstrip(b"=").decode() == public_key else None     # the last character has spare bits: only the canonical form is a key


_P = 2 ** 255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P


def _edwards_add(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    (x1, y1), (x2, y2) = a, b
    t = _D * x1 * x2 * y1 * y2 % _P
    return (x1 * y2 + x2 * y1) * pow(1 + t, _P - 2, _P) % _P, (y1 * y2 + x1 * x2) * pow(1 - t, _P - 2, _P) % _P


def weak_key(raw: bytes) -> bool:
    """Is a key's 32 bytes no key to trust: a y that is not canonical (not under 2^255-19), no point of the curve, or a point of order 8 or less (the identity among them), for which a signature made without any
    secret verifies. A point is of small order when eight times it is the identity; the check is the curve's own arithmetic, no list to keep right."""
    v = int.from_bytes(raw, "little")
    sign, y = v >> 255, v & ((1 << 255) - 1)
    if y >= _P:
        return True
    u, w = (y * y - 1) % _P, (_D * y * y + 1) % _P
    x2 = u * pow(w, _P - 2, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    if (x * x - x2) % _P:
        return True
    if x == 0 and sign:
        return True
    if (x & 1) != sign:
        x = _P - x
    pt = (x, y)
    for _ in range(3):
        pt = _edwards_add(pt, pt)
    return pt == (0, 1)


def fingerprint(public_key: str) -> str:
    """The key's fingerprint, 64 hex characters ("" for a text that is not a key)."""
    raw = decode_key(public_key)
    return hashlib.sha256(raw).hexdigest() if raw is not None else ""


def short(fp: str) -> str:
    """The first 16 characters of a fingerprint: what a person is shown."""
    return fp[:16]


def label_text(v: Any) -> str:
    """A key's label (what it is for) as the server keeps it, else "": at most LABEL_MAX characters of letters, digits, spaces and _ , + -, starting with a letter or digit. It is written on a board
    item the owner reads, and a caller with no token chose it, so no character that makes markup, a link or a mention is taken: there is no `.`, since the board makes a link of a bare domain
    (`login.example.com`)."""
    s = v.strip() if isinstance(v, str) else ""
    return s if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _,+-]{0,%d}" % (LABEL_MAX - 1), s) else ""


def sender_text(v: Any) -> str:
    """A key's sender label (the label its calls carry) as the server keeps it, else "": at most LABEL_MAX characters of letters, digits and _ -, starting with a letter or digit (no `.`, for the
    reason `label_text` gives: the sender is written on the board item too)."""
    s = v.strip() if isinstance(v, str) else ""
    return s if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,%d}" % (LABEL_MAX - 1), s) else ""


def sender_covers(entry_sender: str, sender: str) -> bool:
    """Does a key enrolled under `entry_sender` speak as `sender`: the same label, or that label, a `-` and more."""
    return bool(entry_sender) and bool(sender) and (sender == entry_sender or sender.startswith(entry_sender + "-"))


def _read(path: Path, strict: bool = False) -> dict[str, Any]:
    """The keys a file holds. A file that is not there is an empty list. One that is there but cannot be read as a list of keys is {} to a reader (no key is trusted), and with `strict` (every
    writer) a KeysFileError: a write over it would keep only the key at hand."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        if strict:
            raise KeysFileError(f"{path.name} cannot be read ({type(e).__name__}); nothing was written. Repair or move the file ({path}) and try again") from e
        return {}
    if not isinstance(d, dict) or not all(isinstance(v, dict) for v in d.values()):
        if strict:
            raise KeysFileError(f"{path.name} is not a list of keys; nothing was written. Repair or move the file ({path}) and try again")
        return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}
    return d


def _write(path: Path, d: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(d, indent=1, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _locked() -> Iterator[None]:
    """The two files' lock: one thread at a time in this process, one process at a time on the box."""
    p = Path(_cfg.secrets("keys.lock"))
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _THREAD, os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as lf:
        try:
            os.fchmod(lf.fileno(), 0o600)          # a lock file an earlier version made 0644 is brought to 0600 too (not ours to change: leave it)
        except OSError:
            pass
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def source_tag(bucket: str) -> str:
    """What a pending key keeps of the address it came from (`bucket`: the address as the limits count it): 12 hex characters of an HMAC-SHA-256 under the server's own secret, <secrets>/keys-source.key
    (made on first use, 0600). The addresses are few and known, so a plain hash of one would give it away; this one cannot be computed without the file."""
    p = Path(_cfg.secrets("keys-source.key"))
    try:
        key = p.read_bytes()
    except FileNotFoundError:
        key = b""
    if len(key) != 32:
        with _locked():
            try:
                key = p.read_bytes()
            except FileNotFoundError:
                key = b""
            if len(key) != 32:
                key = secrets.token_bytes(32)
                _write_bytes(p, key)
    return hmac.new(key, ("caller-key-source:" + bucket).encode(), hashlib.sha256).hexdigest()[:12]


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _stamp(now: float) -> str:
    """A time as the instance's own timezone writes it (what the owner reads in `keys list`)."""
    return datetime.datetime.fromtimestamp(now, _cfg.tz()).isoformat(timespec="seconds")


def enrolled_at(e: dict[str, Any]) -> float:
    """When a pending entry was enrolled, in seconds since the epoch; 0 (long expired) for a value that is no finite number, as a hand-edited file may hold."""
    try:
        t = float(e.get("enrolled_at") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return t if math.isfinite(t) else 0.0


def _purged(pending: dict[str, Any], now: float) -> dict[str, Any]:
    return {fp: e for fp, e in pending.items() if now - enrolled_at(e) < PENDING_TTL}


def approved() -> dict[str, dict[str, Any]]:
    """The approved keys, as the file holds them now ({} when there is none or it cannot be read: no key is trusted)."""
    return _read(_approved_path())


def pending(now: float | None = None) -> dict[str, dict[str, Any]]:
    """The keys waiting for the owner, those that have not expired."""
    return _purged(_read(_pending_path()), time.time() if now is None else now)


def lookup_approved(fp: str) -> dict[str, Any] | None:
    """The approved entry of a full fingerprint, or None. Read from the file at each call, so a revoke is in force at once."""
    e = approved().get(fp) if isinstance(fp, str) else None
    return e if isinstance(e, dict) and decode_key(e.get("public_key")) is not None else None


def enroll(public_key: str, label: str, sender: str, now: float | None = None, source: str = "") -> tuple[str, str, dict[str, Any] | None]:
    """Keep a key as pending -> (state, fingerprint, entry): "approved" (the key is already approved: nothing changes), "pending" (kept now, or was already waiting: the same
    key again changes nothing), "full" (MAX_PENDING other keys are waiting: nothing kept), "busy" (MAX_PENDING_PER_SOURCE keys of this `source` are waiting: nothing kept; "" is no source and has no
    limit of its own), "bad" (not a key, or a weak one: see `weak_key`). The caller has checked the label and the sender."""
    now = time.time() if now is None else now
    fp = fingerprint(public_key)
    if not fp or weak_key(decode_key(public_key) or b""):
        return "bad", "", None
    with _locked():
        have = _read(_approved_path(), True).get(fp)
        if have:
            return "approved", fp, have
        pend = _purged(_read(_pending_path(), True), now)
        if fp in pend:
            return "pending", fp, pend[fp]
        if len(pend) >= MAX_PENDING:
            return "full", fp, None
        if source and sum(1 for e in pend.values() if e.get("source") == source) >= MAX_PENDING_PER_SOURCE:
            return "busy", fp, None
        pend[fp] = {"public_key": public_key, "label": label, "sender": sender, "enrolled": _stamp(now), "enrolled_at": now, "item": "", "item_id": "", "source": source}
        _write(_pending_path(), pend)
        return "pending", fp, pend[fp]


def set_item(fp: str, item: str, item_id: str = "") -> None:
    """Record the board item raised for a pending key: as shown, and its id in the store."""
    with _locked():
        pend = _read(_pending_path(), True)
        if fp in pend:
            pend[fp]["item"] = item
            pend[fp]["item_id"] = item_id
            _write(_pending_path(), pend)


def _match(d: dict[str, Any], prefix: str) -> str | None:
    """The one fingerprint of `d` that starts with `prefix` (at least MIN_PREFIX hex characters), else None."""
    p = (prefix or "").strip().lower()
    if len(p) < MIN_PREFIX or not re.fullmatch(r"[0-9a-f]+", p):
        return None
    hit = [fp for fp in d if fp.startswith(p)]
    return hit[0] if len(hit) == 1 else None


def approve(prefix: str, now: float | None = None) -> tuple[str, dict[str, Any] | None]:
    """Move a pending key to the approved list -> (its fingerprint, the entry), or ("", None) when no one pending key starts with `prefix`."""
    now = time.time() if now is None else now
    with _locked():
        pend = _purged(_read(_pending_path(), True), now)
        fp = _match(pend, prefix)
        if not fp:
            return "", None
        e = {k: v for k, v in pend[fp].items() if k != "enrolled_at"}
        e["approved"] = _stamp(now)
        ok = _read(_approved_path(), True)
        ok[fp] = e
        _write(_approved_path(), ok)        # approved first: a crash between the two writes leaves the key approved and still pending, never lost
        del pend[fp]
        _write(_pending_path(), pend)
        return fp, e


def revoke(prefix: str) -> tuple[str, str]:
    """Delete a key, approved or pending -> (its fingerprint, "approved" | "pending"), or ("", "") when no one key starts with `prefix`."""
    with _locked():
        for kind, path in (("approved", _approved_path()), ("pending", _pending_path())):
            d = _read(path, True)
            fp = _match(d, prefix)
            if fp:
                del d[fp]
                _write(path, d)
                return fp, kind
    return "", ""


def listing(now: float | None = None) -> list[str]:
    """One line per key for the command line: state, the short fingerprint, the sender, the label, when it was enrolled, the board item."""
    out = []
    now = time.time() if now is None else now
    for state, d in (("approved", _read(_approved_path(), True)), ("pending", _purged(_read(_pending_path(), True), now))):
        for fp, e in sorted(d.items(), key=lambda kv: str(kv[1].get("enrolled") or "")):
            out.append(f"{state:<9} {short(fp)}  {e.get('sender', '')}  {e.get('label', '')}  since {str(e.get('enrolled') or '')[:16]}" + (f"  {e['item']}" if e.get("item") else ""))
    return out
