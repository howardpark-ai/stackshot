"""tools/cap_words.py — the one-time job after an earlier states audit: stop the
parked items it is given from being refused or re-asked once the 7-day cap runs out. Stdlib only, Python 3.11+.

  A. Items the owner parked himself ("snooze until the sprint ends", "postpone"), whose answer was never saved as his words (named with --a-item). The job finds, in each item's metadata.answers, the newest sentence of his that parks it (a board answer, or his own
     hand-written comment on the issue: the entries the store attributes to him), and records it as metadata.cap_ok for the item's wake
     (the quote, where it came from: the answer or comment and the store commit that first held it, and the date it covers).
  B. Items an agent parked to a real-world date (a vendor reply, a certificate renewal), named with --b-item. The job records the
     basis given for each with --basis (the date from the item's own text, in the form "<what happens> YYYY-MM-DD") as metadata.wait_basis
     through the update path.

  tools/cap_words.py                      dry run (the default): reads the store and its git history, prints per item what it found and would
                                          record, writes nothing, needs no server
  tools/cap_words.py --apply --sender <you>   records what the dry run printed, through the server's client API (POST /client/cap-words, this
                                          machine's token), so the store write, the History line and the GitHub mirror are the server's own
  --a-item board#N [--a-item …]           an item whose park is the owner's own words (kind A); none by default
  --b-item board#N [--b-item …]           an item an agent parked to a real-world date (kind B); none by default
  --item board#N [--item …]               only these items (default: every item named by --a-item or --b-item)
  --basis board#N="<text>"                the basis of a B item (it must name a YYYY-MM-DD)
  --use board#N=<ts|comment id>           for an A item, record this entry of its metadata.answers instead of the newest park (still only an entry the
                                          store attributes to him that reads as a park)

Words are never typed in: an A item takes only an entry that already stands in the item's answers, and the server copies the quote from the
item itself. An item with no words of his is reported as such and left alone; an agent's paraphrase (a status line such as "Parked until …")
is shown, and never used. The config is the usual one ($STACKSHOT_CONFIG or ~/.config/stackshot/stackshot.toml); to try it on a copy of the
live store, point a config's paths.store, paths.repo and paths.state at the copies. Exit 0 · 1 when --apply could not record something."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.waits import waiting as _wt  # noqa: E402

A_ITEMS: tuple[int, ...] = ()      # the items --a-item names (the owner's own park)
B_ITEMS: tuple[int, ...] = ()      # the items --b-item names (an agent's park to a real-world date)
B_BASIS: dict[int, str] = {}       # a basis proposed for a B item before --basis: none; every basis comes from --basis
_ISO = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def store() -> Path:
    return _cfg.path("paths", "store")


def load(n: int) -> dict[str, Any] | None:
    try:
        return json.loads((store() / "g" / f"{n}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def local_time(ts: float) -> str:
    return dt.datetime.fromtimestamp(float(ts), _cfg.tz()).strftime("%a %b %d %H:%M %Z")


def attributed(a: Any) -> bool:
    """An entry the store attributes to the owner, by the same test the server applies when it records it (server._record_cap_words): written by the
    board's answer form (via board) or by the reader of his hand-written GitHub comments (via github, with the comment's id and url), kind decision or
    comment, with text. No session's tool writes metadata.answers."""
    if not isinstance(a, dict) or a.get("kind") not in ("decision", "comment") or a.get("via") not in ("board", "github"):
        return False
    if not str(a.get("text") or "").strip():
        return False
    return a.get("via") != "github" or (a.get("comment_id") is not None and bool(str(a.get("url") or "").strip()))


def first_commit(n: int, a: dict[str, Any]) -> str:
    """The store commit that first held this entry (the oldest commit that added its timestamp to the item's file), '' when git cannot say."""
    repo = _cfg.path("paths", "repo")
    key = str(a.get("ts"))
    try:
        r = subprocess.run(["git", "-C", str(repo), "log", "--reverse", "--format=%h", f"-S{key}", "--", f"board-data/g/{n}.json"],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout.split() or [""])[0]
    except (OSError, subprocess.SubprocessError):
        return ""


def _owner_rx() -> "re.Pattern[str]":
    """The owner's name or an alias, in any case ([instance] owner and owner_aliases)."""
    return re.compile("|".join(re.escape(n) for n in _cfg.owner_names()) or r"(?!)", re.I)


def agent_text(item: dict[str, Any]) -> list[str]:
    """Lines of the item's own text (next, description) that mention a park by <owner>: an agent's paraphrase, shown and never used."""
    m = item.get("metadata") or {}
    out = []
    for field in ("next", "description"):
        for ln in str(m.get(field) if field == "next" else item.get(field) or "").splitlines():
            if _owner_rx().search(ln) and _wt.park_words(ln):
                out.append(f"{field}: {' '.join(ln.split())[:220]}")
    return out


def status_line(gid: str, item: dict[str, Any], now: float) -> str:
    return f"last move {local_time(_wt.clock_of(item, now))}"


def plan_a(n: int, use: str, now: float) -> dict[str, Any]:
    gid = f"g{n}"
    item = load(n)
    if item is None:
        return {"n": n, "kind": "A", "found": False, "lines": [f"board#{n}: not in the store"]}
    m = item.get("metadata") or {}
    out = {"n": n, "kind": "A", "found": False, "body": None, "lines": []}
    L = out["lines"]
    L.append(f"board#{n} · {item.get('subject')}")
    L.append(f"  state: {item.get('status')}; wake {m.get('wake') or 'none'}; hold {bool(m.get('hold'))}; needs {m.get('needs') or 'none'}")
    if item.get("status") == "open":
        L.append("  now: " + status_line(gid, item, now))
    entries = [a for a in (m.get("answers") or []) if isinstance(a, dict)]
    prior = None
    pairing = {}
    if item.get("status") == "open" and any(attributed(a) and _wt.park_words(a.get("text")) for a in entries):
        prior = _wt.prior_state_ts(gid, str(m.get("wake") or ""))
        L.append("  state history (store git): " + ("UNREADABLE: the history exists but could not be read, so no answer pairs unless given since the move that set the wake" if prior is _wt.UNREADABLE
                 else f"the state last changed at {local_time(prior)}, before the move that set the wake {m.get('wake')}" if prior is not None else "no earlier state change can be shown (24-hour lead rule)"))
    for a in entries:
        mark = ("HIS" if attributed(a) else "not his") + (", reads as a park" if attributed(a) and _wt.park_words(a.get("text")) else "")
        if attributed(a) and _wt.park_words(a.get("text")):
            pairing[id(a)] = _wt.entry_pairs(item, a.get("ts"), now, prior)
            ok, why = pairing[id(a)]
            mark += f", pairs with the current wake or hold ({why})" if ok else f", but STALE: {why}"
        L.append(f"  entry {a.get('ts')} {local_time(a.get('ts') or 0)} · {a.get('kind')} via {a.get('via')} · {mark} · “{' '.join(str(a.get('text') or a.get('choice') or '').split())[:300]}”")
    if not entries:
        L.append("  no answers or comments of his are stored on the item")
    co = m.get("cap_ok") if isinstance(m.get("cap_ok"), dict) else {}
    pick = None
    cands = [a for a in entries if attributed(a) and _wt.park_words(a.get("text")) and pairing.get(id(a), (False,))[0]]   # the server's tests (waiting.entry_pairs)
    if use:
        cands = [a for a in cands if use in (str(a.get("ts")), str(a.get("comment_id")))]
    if cands:
        pick = max(cands, key=lambda a: float(a.get("ts") or 0))
    if pick is None:
        L.append("  NOTHING TO RECORD: no stored sentence of his parks this item and stands behind the move that set its current wake or hold")
    elif co.get("wake") == m.get("wake") and str(co.get("quote") or "").strip() == str(pick.get("text") or "").strip():
        L.append("  ALREADY RECORDED: cap_ok holds this quote for the current wake")
    elif not m.get("wake"):
        L.append("  NOTHING TO RECORD: the item has no wake date for his words to cover")
    elif item.get("status") != "open":
        L.append("  NOTHING TO RECORD: the item is not open")
    else:
        sha = first_commit(n, pick)
        body = {"item": f"board#{n}", "quote": str(pick.get("text") or "").strip(), "commit": sha}
        if pick.get("comment_id") is not None:
            body["comment_id"] = pick["comment_id"]
        else:
            body["ts"] = pick["ts"]
        out.update(found=True, body=body)
        L.append(f"  WOULD RECORD cap_ok for wake {m.get('wake')}: “{' '.join(body['quote'].split())[:400]}”")
        L.append(f"    from: his {pick.get('kind')} on the {pick.get('via')}, {local_time(pick['ts'])}"
                 + (f" (comment {pick['comment_id']})" if pick.get("comment_id") is not None else "") + f"; first in store commit {sha or '(unknown)'}")
    for t in agent_text(item):
        L.append(f"  an agent's text, NOT used as his words: {t}")
    return out


def plan_b(n: int, basis_override: str, now: float) -> dict[str, Any]:
    gid = f"g{n}"
    item = load(n)
    if item is None:
        return {"n": n, "kind": "B", "found": False, "lines": [f"board#{n}: not in the store"]}
    m = item.get("metadata") or {}
    out = {"n": n, "kind": "B", "found": False, "body": None, "lines": []}
    L = out["lines"]
    L.append(f"board#{n} · {item.get('subject')}")
    L.append(f"  state: {item.get('status')}; wake {m.get('wake') or 'none'}; due {m.get('due') or 'none'}; hold {bool(m.get('hold'))}")
    if item.get("status") == "open":
        L.append("  now: " + status_line(gid, item, now))
    basis = " ".join((basis_override or B_BASIS.get(n, "")).split())
    wake = _wt.wake_epoch(m.get("wake")) if m.get("wake") else None
    why = ""
    if item.get("status") != "open":
        why = "the item is not open"
    elif wake is None:
        why = "the item has no wake date (a wait_basis needs one)"
    elif (wake - now) / 86400.0 <= _wt.cap_days():
        why = f"the wake is {(wake - now) / 86400.0:.0f} days out, within the {_wt.cap_days():g}-day cap: not needed"
    else:
        wake_day = dt.datetime.fromtimestamp(wake, _cfg.tz()).date()
        if (wake - now) / 86400.0 > _wt.BASIS_MAX_WAKE_DAYS:
            why = f"the wake is {(wake - now) / 86400.0:.0f} days out; a basis stands for a wake at most {_wt.BASIS_MAX_WAKE_DAYS} days away"
        elif not 12 <= len(basis) <= 300:
            why = f"the basis {basis!r} is not 12-300 characters"
        else:
            bp = _wt.basis_problem(basis, wake_day)
            if bp:
                why = f"the basis {basis!r} cannot stand for the wake {m.get('wake')}: {bp}"
    if isinstance(m.get("wait_basis"), dict) and _wt.basis_of(m) == basis:
        L.append("  ALREADY RECORDED: wait_basis holds this text for the current wake")
    elif why:
        L.append(f"  NOTHING TO RECORD: {why}")
    else:
        out.update(found=True, body={"item": f"board#{n}", "basis": basis})
        L.append(f"  WOULD RECORD wait_basis for wake {m.get('wake')}: “{basis}”")
        L.append("    proposed from the item's own text; replace with --basis board#%d=\"…\"" % n)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Record the park words of the board's owner (A) and the real-world date of a long wait (B) on the items named by --a-item and --b-item. Dry run by default.")
    ap.add_argument("--apply", action="store_true", help="record what the dry run prints, through the server's client API")
    ap.add_argument("--sender", default="", help="with --apply: the name of the session that runs the job (required; the record keeps \"<sender> via a script on <machine>\")")
    ap.add_argument("--a-item", action="append", default=[], metavar="board#N", help="an item whose park is the owner's own words (repeatable)")
    ap.add_argument("--b-item", action="append", default=[], metavar="board#N", help="an item an agent parked to a real-world date (repeatable)")
    ap.add_argument("--item", action="append", default=[], metavar="board#N", help="only this item (repeatable)")
    ap.add_argument("--basis", action="append", default=[], metavar='board#N="text"', help="the basis of a B item")
    ap.add_argument("--use", action="append", default=[], metavar="board#N=<ts|comment id>", help="the entry of an A item to record")
    a = ap.parse_args(argv)

    def pairs(items: list[str], what: str) -> dict[int, str]:
        out = {}
        for x in items:
            k, sep, v = x.partition("=")
            m = re.fullmatch(r"(?:board)?#?(\d+)", k.strip())
            if not (m and sep and v.strip()):
                ap.error(f"{what} takes board#N=<value>, got {x!r}")
            out[int(m[1])] = v.strip()
        return out
    basis, use = pairs(a.basis, "--basis"), pairs(a.use, "--use")
    a_items, b_items = tuple(A_ITEMS), tuple(B_ITEMS)
    for opt, what in ((a.a_item, "--a-item"), (a.b_item, "--b-item")):
        got = []
        for x in opt:
            m = re.fullmatch(r"(?:board)?#?(\d+)", x.strip())
            if not m:
                ap.error(f"{what} takes board#N, got {x!r}")
            got.append(int(m[1]))
        if what == "--a-item":
            a_items += tuple(got)
        else:
            b_items += tuple(got)
    only = set()
    for x in a.item:
        m = re.fullmatch(r"(?:board)?#?(\d+)", x.strip())
        if not m:
            ap.error(f"--item takes board#N, got {x!r}")
        only.add(int(m[1]))
    now = time.time()
    plans = [plan_a(n, use.get(n, ""), now) for n in a_items if not only or n in only] + [plan_b(n, basis.get(n, ""), now) for n in b_items if not only or n in only]
    for p in plans:
        print("\n".join(p["lines"]))
        print()
    todo = [p for p in plans if p.get("found")]
    print(f"{'APPLY' if a.apply else 'DRY RUN'}: {len(todo)} of {len(plans)} items have something to record"
          + ("" if a.apply else "; nothing was written. Run again with --apply to record them through the server."))
    if not a.apply:
        return 0
    if not a.sender.strip():
        ap.error("--apply needs --sender <the name of the session that runs this>")
    from stackshot.fleet import client as _client  # noqa: E402  — only an apply needs this machine's token and the server's address
    bad = 0
    for p in todo:
        status, d = _client.post("cap-words", {**p["body"], "sender": a.sender.strip()}, 60.0)
        if status == 200 and isinstance(d, dict):
            print(f"recorded board#{p['n']}: {d.get('action')}" + (f" · {d.get('source')}" if d.get("source") else ""))
        else:
            bad += 1
            print(f"NOT recorded board#{p['n']}: [{status}] {d.get('error') if isinstance(d, dict) else d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
