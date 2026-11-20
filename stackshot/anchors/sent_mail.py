"""sent_mail.py: the files the sent-mail watch passes between the anchors service and the server, and the small pure rules on them.

The watch finishes a step of the user's that says "send this mail" when a mail he sent fits it (service/sent_match.py has the matching; docs/configuration-integrations.md has the whole of it). Two processes
take part and they share no memory, only files in the state folder, as the hub and the server already do for the event log:

  sent-watch.json    the server writes it (mode 0600): {"mode": "count" | "on", "at": when, "threads": [thread ids], "addrs": [addresses], "words": [words]}, or mode "off". The hub reads it on every pass. While it says
                     count or on, the hub reads the mail the user sends (the SENT label in the history it already polls, one messages.get a mail) and leaves one small file in the spool for each such mail that could
                     fit an open send step: one on a thread a step's item anchors, or to an address the steps' items name (`may_match`). While it says off, or has not been refreshed for WATCH_MAX_AGE, it reads
                     none of it and costs nothing. The server writes it when the mode or the lists change, and when it has aged (WATCH_REFRESH); with the setting off and no file there, nothing is written.
  sent-mail/<id>.json  one spool file per sent mail, written by the hub (readable by the service's user only, mode 0600): {"mid", "tid", "box" (the mailbox it left), "ts", "to": [[name, address], …], "cc": the same,
                     "subject" (clipped), "snip" (the first words Gmail gives, clipped to SNIP_MAX characters: never the whole body)}. The server reads them in its minute pass, decides each one and deletes the file.
                     A mail that matches nothing is deleted at once; one that waits for a second try keeps its file (its words included) until its verdict, at most ROW_MAX_AGE. The hub deletes a file older than that
                     itself (`sweep`), whatever the server is doing, and a half-written `.tmp` with it; nothing else keeps a word of any mail.
  sent-mail-counts.json  the server's counts of what it saw and did (never a word of a mail): what the dry run (mode count) reports, and the times of the model calls of the last hour (the cap).

The setting is `[anchor_hub] sent_mail_watch`: off (the default), count (the dry run: the mails are counted by what they would have done and nothing is ticked, asked or sent to a model) or on. Only these three words
are valid: anything else, `true` and `false` included, reads as off.

Pure apart from these files: no server import, no clock read (the caller passes `now`)."""
from __future__ import annotations

import json
import os
import re
from email.utils import getaddresses
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

MODES = ("off", "count", "on")
WATCH_REFRESH = 300.0           # s: the server rewrites an unchanged watch file at most this often
WATCH_MAX_AGE = 1800.0          # s: the hub reads a watch file the server has not refreshed for this long as off (the server is down or stopped)
ROW_MAX_AGE = 3 * 3600.0        # s: a mail waiting for a verdict is asked about, and dropped, after this
SWEEP_GRACE = 600.0             # s: the hub's own sweep deletes a spool file this much after the server would have given up on it
WATCH_LIST_MAX = 400            # entries kept in each list of the watch file
SUBJECT_MAX = 120
SNIP_MAX = 200
NAME_MAX = 60
MAX_ADDRS = 20                  # recipients kept for a mail (To and Cc together)
STOP = frozenset({"support", "info", "team", "admin", "sales", "noreply", "reply", "contact", "hello", "office", "desk", "billing", "help", "mail", "email", "send", "draft", "service"})      # a lone word of an address's name part that names no person
_ADDR = re.compile(r"^[^@\s<>,;:]+@[^@\s<>,;:]+\.[^@\s<>,;:]+$")
_MID = re.compile(r"[^A-Za-z0-9_-]")


def mode_of(value: Any) -> str:
    """The mode a setting names: off, count or on, in any case; anything else (true and false included, a typo, a missing value) is off, so a mail reader is never turned on by a slip."""
    if not isinstance(value, str):
        return "off"
    v = value.strip().lower()
    return v if v in MODES else "off"


def clip(value: Any, limit: int) -> str:
    """A text on one line, at most `limit` characters; anything that is not a text is empty."""
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def parse_addrs(*headers: Any) -> list[list[str]]:
    """The recipients of To and Cc headers as [name, address] pairs: the address in lower case, each address once (the first spelling of the name is kept), an entry that is no address (a group, a
    bare word) skipped, at most MAX_ADDRS."""
    out: list[list[str]] = []
    seen: set[str] = set()
    for h in headers:
        if not isinstance(h, str) or not h.strip():
            continue
        for name, addr in getaddresses([h]):
            a = addr.strip().lower()
            if not _ADDR.match(a) or a in seen:
                continue
            seen.add(a)
            out.append([clip(name, NAME_MAX), a])
            if len(out) >= MAX_ADDRS:
                return out
    return out


# ----------------------------------------------------------------------------- who a step names
def local_words(addr: str) -> list[str]:
    """The words of an address's name part (before the @) that are letters: "jane.roe@x.org" is ["jane", "roe"], "j2@x.org" is ["j"]."""
    return re.findall(r"[a-z]+", str(addr or "").split("@", 1)[0].lower())


def named_by(addr: str, addrs: Any, words: Any) -> bool:
    """Does an item name this recipient? Only the address counts, never a display name (that is written by whoever sent the mail the reply answers): the address is in the item's text (`addrs`), or every word of its
    name part is a whole word of the step (`words`) and the name is two words or more, or one word of five letters or more that names no desk or role (STOP)."""
    a = str(addr or "").strip().lower()
    if a in addrs:
        return True
    lw = local_words(a)
    if not lw or not all(w in words for w in lw):
        return False
    return len(lw) >= 2 or (len(lw[0]) >= 5 and lw[0] not in STOP)


def may_match(info: dict[str, Any], tid: str, recipients: list[str], selfs: Any = ()) -> bool:
    """Could a sent mail fit an open send step, by the watch file's lists (`info`: threads, addrs, words)? It is on a thread a step's item anchors, or went to somebody (not himself) the lists name. The server
    decides each such mail again, step by step."""
    if str(tid or "").lower() in set(info.get("threads") or ()):
        return True
    addrs, words = set(info.get("addrs") or ()), set(info.get("words") or ())
    return any(a not in selfs and named_by(a, addrs, words) for a in recipients)


def is_auto(headers: dict[str, str]) -> bool:
    """Is a sent mail one a machine made (a vacation reply, a filter's canned answer): Auto-Submitted other than "no", or a bulk, list, junk or auto-reply Precedence? Such a mail is no step of his."""
    auto = str(headers.get("auto-submitted") or "").strip().lower()
    prec = str(headers.get("precedence") or "").strip().lower()
    return (bool(auto) and auto != "no") or prec in ("bulk", "list", "junk", "auto_reply")


# ----------------------------------------------------------------------------- the files
def watch_path() -> Path:
    return _cfg.state("sent-watch.json")


def spool_dir() -> Path:
    return _cfg.state("sent-mail")


def counts_path() -> Path:
    return _cfg.state("sent-mail-counts.json")


def _write(path: Path, text: str, private: bool = False) -> bool:
    """Write `text` beside `path` and move it over (a stop in the middle leaves the old file); mode 0600 when `private`. A failed write leaves no `.tmp` behind. → whether it was written."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o777)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _list(v: Any, limit: int = WATCH_LIST_MAX) -> list[str]:
    return sorted({str(x).strip().lower() for x in v if isinstance(x, str) and x.strip()})[:limit] if isinstance(v, list) else []


def read_watch_full(now: float | None = None) -> dict[str, Any]:
    """What the server asked for: {"mode": off | count | on, "threads": […], "addrs": […], "words": […]}. A missing, torn or unreadable file is off, and so is one older than WATCH_MAX_AGE when the caller gives
    its clock (`now`)."""
    off: dict[str, Any] = {"mode": "off", "threads": [], "addrs": [], "words": []}
    try:
        d = json.loads(watch_path().read_text(encoding="utf-8"))
        mode = mode_of(d.get("mode"))
        at = d.get("at")
        if now is not None and not (isinstance(at, (int, float)) and not isinstance(at, bool) and now - float(at) <= WATCH_MAX_AGE):
            return off
        return {"mode": mode, "threads": _list(d.get("threads")), "addrs": _list(d.get("addrs")), "words": _list(d.get("words"))}
    except (OSError, ValueError, AttributeError):
        return off


def read_watch(now: float | None = None) -> str:
    """The mode the server asked for: off, count or on (see read_watch_full)."""
    return read_watch_full(now)["mode"]


def write_watch(mode: str, now: float, info: dict[str, Any] | None = None) -> bool:
    """Say what the hub should do, and which mails could matter (`info`: threads, addrs, words). An unchanged file is not written again until it is WATCH_REFRESH old; with the mode off and no file there is
    nothing to say and nothing is written. → whether the file was written."""
    mode = mode_of(mode)
    want = {k: _list((info or {}).get(k)) if mode != "off" else [] for k in ("threads", "addrs", "words")}
    try:
        d = json.loads(watch_path().read_text(encoding="utf-8"))
        if mode_of(d.get("mode")) == mode and isinstance(d.get("at"), (int, float)) and 0 <= now - float(d["at"]) < WATCH_REFRESH and all(_list(d.get(k)) == want[k] for k in want):
            return False
    except (OSError, ValueError, AttributeError):
        if mode == "off":
            return False
    return _write(watch_path(), json.dumps({"mode": mode, "at": round(now, 1), **want}) + "\n", private=True)


def _safe_mid(mid: Any) -> str:
    return _MID.sub("", str(mid or ""))[:80]


def clean_row(r: Any) -> dict[str, Any] | None:
    """A spool row as the server uses it, None for one of the wrong shape (a hand edit, a torn file that still parsed)."""
    if not isinstance(r, dict):
        return None
    mid, tid = _safe_mid(r.get("mid")), _safe_mid(r.get("tid"))
    ts = r.get("ts")
    if not mid or not tid or isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:
        return None
    def people(v: Any) -> list[list[str]]:
        out = []
        for p in v if isinstance(v, list) else []:
            if isinstance(p, (list, tuple)) and len(p) == 2 and isinstance(p[1], str) and _ADDR.match(p[1].strip().lower()):
                out.append([clip(p[0], NAME_MAX), p[1].strip().lower()])
        return out[:MAX_ADDRS]
    out = {"mid": mid, "tid": tid, "box": clip(r.get("box"), 120).lower(), "ts": float(ts), "to": people(r.get("to")), "cc": people(r.get("cc")),
           "subject": clip(r.get("subject"), SUBJECT_MAX), "snip": clip(r.get("snip"), SNIP_MAX)}
    for k in ("seen", "next_at"):
        if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool):
            out[k] = float(r[k])
    if isinstance(r.get("tries"), int) and not isinstance(r.get("tries"), bool) and r["tries"] > 0:
        out["tries"] = r["tries"]
    if isinstance(r.get("pending"), list):
        out["pending"] = [str(g) for g in r["pending"] if isinstance(g, str)][:50]
    return out


def put(row: dict[str, Any]) -> bool:
    """The hub leaves one sent mail for the server (a file readable by the service's user only). → whether it was written; a row of the wrong shape is not."""
    r = clean_row(row)
    if r is None:
        return False
    return _write(spool_dir() / f"{r['mid']}.json", json.dumps(r, ensure_ascii=False) + "\n", private=True)


def update(row: dict[str, Any]) -> bool:
    """The server keeps a row for a second try, with what it noted on it (seen, tries, next_at, pending). → whether it was written."""
    return put(row)


def rows() -> list[dict[str, Any]]:
    """The spool's mails, oldest first; a file that cannot be read or is of the wrong shape is skipped."""
    out: list[dict[str, Any]] = []
    try:
        names = sorted(os.listdir(spool_dir()))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            r = clean_row(json.loads((spool_dir() / n).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if r is not None:
            out.append(r)
    return sorted(out, key=lambda r: (r["ts"], r["mid"]))


def drop(mid: Any) -> None:
    """Delete one mail's file (a file already gone is fine)."""
    m = _safe_mid(mid)
    if m:
        try:
            (spool_dir() / f"{m}.json").unlink()
        except OSError:
            pass


def drop_all() -> int:
    """Delete every spool file, readable or not (the watch is off, or no step waits for a mail). → how many."""
    n = 0
    try:
        for p in spool_dir().iterdir():
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def sweep(now: float) -> int:
    """The hub's own age limit: delete every file in the spool older than ROW_MAX_AGE (and a little), whatever its name, whatever the server is doing and whether the watch is on. → how many."""
    n = 0
    try:
        for p in spool_dir().iterdir():
            try:
                if now - p.stat().st_mtime > ROW_MAX_AGE + SWEEP_GRACE:
                    p.unlink()
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def load_counts() -> dict[str, Any]:
    try:
        d = json.loads(counts_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_counts(counts: dict[str, Any]) -> bool:
    return _write(counts_path(), json.dumps(counts, sort_keys=True) + "\n")
