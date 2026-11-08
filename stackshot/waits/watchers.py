"""watchers.py — the waits' watchers of the item model (the design: docs/design, section 4 and the pause line of section 5).

A waiting item names what it waits on (model.py: wait_kind time | item | anchor | relay | event), and this module says when that wait is over and what the item turns into. The pure
half lives here: the readings (which items the watchers own, which are due, on what cause), the text of each arrival, the relay's fixed ask and its options, the chases, the
reading of the owner's answer to those asks, the date he gives. The server (server.py, the `_watch_*` functions) reads and writes the items, sends the messages and calls these.

  The watchers act ONLY on an item with a stored wait_kind, while [model] watchers is true. Every other item keeps today's wake pass and `after` release
  until the step 4 migration, so no item is moved by two mechanisms (`watches` is the gate those read).

  time    the wake passes → alive, the post-wake mover
  item    the last `after` item closes → alive, the post-wake mover; the backstop (ask_by, else the wake) passes first → alive, the post-wake mover, with the note that the item
          it waited on is still open
  anchor  the anchor module delivers a notice for the anchor → alive, the post-wake mover, the notice's gist on the item (the mover judges a false hit); the backstop passes
          first → alive, the post-wake mover, "the anchor stayed silent"
  event   the server is told of the fleet event the wait names (event_waits.py: a PR merged or released, a recycle, a fleet op's result, a job's run) → alive, the post-wake mover, with what
          happened; the backstop passes first → alive, the post-wake mover, "the event did not come". The stall pass does not run for it (a waiting item has no mover to nag)
  relay   the ask-by day comes → alive with the owner as mover, a ready question: has <party>'s <event> arrived? arrived / not yet, ask again on <date> / drop

  Chases (a relay or anchor wait): a follow-up an older item logged is only read (no call logs one now). With two on the item, the wait's next end (the ask-by day or the
  backstop) brings the item to the owner as "drop it?" (drop / keep waiting until <date>) instead of the usual arrival. Reading taken: "after two chases with no reply"
  is judged when the wait comes due, since only then has the last chase had its time to be answered.

[model] pause = true holds every transition here (and the wake pass beside them); when it turns false the due ones fire in one pass, one message per recipient."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any

from stackshot.core import config as _cfg
from stackshot.waits import event_waits as _ew
from stackshot.model import model as _model
from stackshot.waits import waiting as _wt

CHASE_KINDS = ("relay", "anchor")          # the waits a chase goes with
CHASES_MAX = 2                             # this many chases, no arrival: the next end of the wait asks the owner "drop it?"
DROP_ON_CLOSE = ("chases", "woke", "watch")
ARRIVED, NOT_YET, DROP, KEEP = "arrived", "not yet, ask again on <date>", "drop", "keep waiting until <date>"      # the buttons; the date is the one the owner gives in the box
NEEDS_DATE = "needdate"                    # the answer code when "not yet" came with no readable date: nothing is written, the page says so
_ASK_HEAD = "Decide: "
_OPT_MARK = " · Options: "


# ---------------------------------------------------------------------------------------------------------------- the switches
def enabled() -> bool:
    """[model] watchers (default true): the waits' watchers. false turns this module's transitions off, and an item with a stored wait_kind falls back to today's machinery."""
    return bool(_cfg.get("model", "watchers", default=True))


_HOLD: dict[str, Any] = {"until": 0.0, "by": "", "since": 0.0}      # the migration's own pause: held in the server process, never in the config file, and it lapses by itself
HOLD_CEILING_S = 3600.0        # the most one pass may hold the board, from its `begin`, however often it renews: a pass that runs past this lapses


def hold(by: str, seconds: float, now: float | None = None, begin: bool = False) -> None:
    """The migration pass holds the board-wide pause for `seconds` more (each batch of the pass renews it, so a pass that dies lets the board go on after a few minutes, never for good, and never
    past HOLD_CEILING_S after its `begin`, whatever renews it). `begin` starts the pass and its ceiling; a renewal keeps the ceiling it began with. A restart of the server drops it. It stands
    beside `[model] pause`: the config switch is the operator's, this one is the pass's, and lifting this never lifts that."""
    t = time.time() if now is None else now
    if begin or not _HOLD["since"]:
        _HOLD["since"] = t
    _HOLD["until"] = min(t + float(seconds), float(_HOLD["since"]) + HOLD_CEILING_S)
    _HOLD["by"] = str(by or "migration")


def release() -> None:
    _HOLD["until"], _HOLD["by"], _HOLD["since"] = 0.0, "", 0.0


def holding(now: float | None = None) -> bool:
    """Is the migration's hold up (the pass is running)?"""
    return (time.time() if now is None else now) < float(_HOLD["until"])


def holder() -> str:
    """Who began the pass that holds the board now ("" when none holds it): the only caller whose apply or end the route takes."""
    return str(_HOLD["by"]) if holding() else ""


def paused() -> bool:
    """[model] pause (default false): the board-wide pause switch, or the migration pass's hold. While true no wait ends, no wake fires (the wake pass reads it too) and no hand-off clock runs; the due ones fire when it turns false."""
    return bool(_cfg.get("model", "pause", default=False)) or holding()


def stored_kind(meta: dict[str, Any]) -> str:
    """The wait_kind an item stores ("" when none or not one of the four)."""
    k = _model.clean((meta or {}).get("wait_kind")).lower()
    return k if k in _model.WAIT_KINDS else ""


def time_epoch(meta: dict[str, Any]) -> float | None:
    """When a time wait ends: its wake, else (a verifying item) its end date, the end of that day."""
    ep = day_epoch(meta.get("wake"))
    if ep is None and meta.get("state") == "verifying" and meta.get("end"):
        ep = _wt.due_epoch(meta.get("end"))
    return ep


def can_end(meta: dict[str, Any]) -> bool:
    """Can some watcher end this stored wait: a time wait needs a wake (or a verifying end date), a relay its ask-by day, an item wait its `after` or a backstop date, an anchor wait the
    anchor it watches, an event wait its event phrase and a backstop date. A wait no watcher can end stays with today's mechanisms."""
    k = stored_kind(meta)
    if k == "time":
        return time_epoch(meta) is not None
    if k == "relay":
        return day_epoch(meta.get("ask_by")) is not None
    if k == "item":
        return bool(_wt.after_of(meta)) or backstop_epoch(meta) is not None
    if k == "anchor":
        return bool(_model.clean(meta.get("wait_anchor")))
    if k == "event":
        return not _ew.problem(meta.get("wait_event")) and backstop_epoch(meta) is not None      # an event that may never come needs a day it comes back anyway; without one the nag keeps the item
    return False


def watches(item: dict[str, Any]) -> bool:
    """Does this module own the item's wait: watchers are on, the item is open, it stores a wait_kind and a watcher can end that wait. The wake pass and the `after` release
    skip such an item; one whose wait no watcher can end (a time wait with no date, an anchor wait with no anchor) keeps today's mechanisms."""
    return enabled() and item.get("status") == "open" and can_end(item.get("metadata") or {})


# ---------------------------------------------------------------------------------------------------------------- when a wait is over
BACKOFF = 600.0        # an item whose turn failed is left alone this long (metadata.watch.failed_at)


def failed_at(meta: dict[str, Any]) -> float:
    w = (meta or {}).get("watch")
    try:
        return float(w.get("failed_at") or 0) if isinstance(w, dict) else 0.0
    except (TypeError, ValueError):
        return 0.0


def day_epoch(value: Any) -> float | None:
    """A stored date (YYYY-MM-DD, or with THH:MM) as the moment it falls due: the start of that day in the instance timezone, so the ask-by day brings the question on that day."""
    return _wt.wake_epoch(value)


def backstop_epoch(meta: dict[str, Any]) -> float | None:
    """The date an item or anchor wait comes back anyway: the earlier of its ask_by and its wake, None when it has neither."""
    eps = [e for e in (day_epoch(meta.get("ask_by")), day_epoch(meta.get("wake"))) if e is not None]
    return min(eps) if eps else None


def next_moment(meta: dict[str, Any]) -> float | None:
    """The moment the scheduler next has to look at this wait (a wake, a relay's ask-by, a backstop), None for none: the runner sleeps until the earliest. An item whose last turn failed
    is looked at again BACKOFF after the failure, not at once."""
    k = stored_kind(meta)
    ep = time_epoch(meta) if k == "time" else day_epoch(meta.get("ask_by")) if k == "relay" else backstop_epoch(meta) if k in ("item", "anchor", "event") else None
    fa = failed_at(meta)
    if ep is not None and fa and ep <= fa + BACKOFF:
        ep = fa + BACKOFF
    return ep


def due(item: dict[str, Any], now: float, after_open: list[str] | None = None) -> str:
    """Why this item's wait is over by the clock, "" when it is not: time (the wake passed), item (every `after` item is closed: the catch-up of the close event), backstop (an
    item or anchor wait ran out its date), relay (the ask-by day came). An anchor's arrival is an event (the anchor module), not a date, so it is not here. An item whose last turn failed
    is not due for BACKOFF seconds. `after_open` = the `after` items still open (the server reads them)."""
    meta = item.get("metadata") or {}
    k = stored_kind(meta)
    fa = failed_at(meta)
    if fa and now < fa + BACKOFF:
        return ""
    if k == "time":
        ep = time_epoch(meta)
        return "time" if ep is not None and ep <= now else ""
    if k == "relay":
        ep = day_epoch(meta.get("ask_by"))
        return "relay" if ep is not None and ep <= now else ""
    if k == "item":
        if _wt.after_of(meta) and not (after_open or []):
            return "item"
    if k in ("item", "anchor", "event"):
        ep = backstop_epoch(meta)
        if ep is not None and ep <= now:
            return "backstop"
    return ""


def chases_of(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The chases logged on the item, oldest first: [{at, by, note}]."""
    v = (meta or {}).get("chases")
    return [c for c in v if isinstance(c, dict)] if isinstance(v, list) else []


def chased_out(meta: dict[str, Any]) -> bool:
    """A relay or anchor wait with CHASES_MAX chases on it: its next end asks "drop it?"."""
    return stored_kind(meta) in CHASE_KINDS and len(chases_of(meta)) >= CHASES_MAX


# ---------------------------------------------------------------------------------------------------------------- the asks
def subject_of(meta: dict[str, Any], clip: int = 110) -> str:
    """What a relay or an anchor wait is for, as the ask names it: "<party>'s <event>" when the item stores a party that the event does not already name, else the event."""
    event = _model.clean(meta.get("wait_event")) or "the news"
    party = _model.clean(meta.get("party"))
    text = f"{party}'s {event}" if party and party.lower() not in event.lower() else event
    return text if len(text) <= clip else text[:clip].rstrip() + "…"


def relay_ask(meta: dict[str, Any]) -> str:
    """The relay question, fixed (the design doc): "Decide: has <party>'s <event> arrived? · Options: arrived / not yet, ask again on <date> / drop"."""
    return f"{_ASK_HEAD}has {subject_of(meta)} arrived?{_OPT_MARK}arrived / not yet, ask again on <date> / drop"


def drop_ask(meta: dict[str, Any]) -> str:
    """The question an item chased twice comes with: "Decide: drop it? … · Options: drop / keep waiting until <date>"."""
    return (f"{_ASK_HEAD}drop it? {subject_of(meta, 80)} did not arrive after {len(chases_of(meta))} chases{_OPT_MARK}drop / keep waiting until <date>")


def is_watcher_ask(ask: Any) -> bool:
    """Is this ask one of the two above (they carry no Recommend, Stakes or By, so the ask shape of render.parse_ask does not read them: the ask check lets them stand)."""
    t = str(ask or "")
    return t.startswith(_ASK_HEAD) and _OPT_MARK in t and " · Recommend: " not in t


def relay_options() -> list[dict[str, Any]]:
    """The relay question's buttons, in the shape of an option the owner's page offers (label, line, recommended)."""
    return [{"label": ARRIVED, "line": "It came: the item goes on to the session that takes it after the wait.", "recommended": False},
            {"label": NOT_YET, "line": "Give the date in the box (Mar 9th, or 2099-03-09): the item waits again and the question comes back then.", "recommended": True},
            {"label": DROP, "line": "It is no longer wanted: the item closes as not planned.", "recommended": False}]


def drop_options() -> list[dict[str, Any]]:
    """The "drop it?" question's buttons."""
    return [{"label": DROP, "line": "It is no longer wanted: the item closes as not planned.", "recommended": True},
            {"label": KEEP, "line": "Give the date in the box (Mar 9th, or 2099-03-09): the wait goes on and the chases start again.", "recommended": False}]


# ---------------------------------------------------------------------------------------------------------------- the wait that turned (the record of what to put back)
WAS_FIELDS = ("wait_kind", "wait_anchor", "wait_event", "post_wake_mover", "ask_by", "wake", "after", "party", "needs")


def remember(meta: dict[str, Any], asked: str, now: float) -> None:
    """The item is about to turn to the owner for a watcher ask: keep the wait's fields (what to put back on "not yet" or "keep waiting") and which ask is up, under metadata.watch."""
    was = {k: meta[k] for k in WAS_FIELDS if meta.get(k) not in (None, "", [])}
    w = dict(meta.get("watch") or {}) if isinstance(meta.get("watch"), dict) else {}
    w.update({"asked": asked, "was": was, "at": now})
    meta["watch"] = w


def asked_of(meta: dict[str, Any]) -> str:
    """Which watcher ask is up on the item: relay | dropit | "" (none)."""
    w = meta.get("watch")
    a = str(w.get("asked") or "") if isinstance(w, dict) else ""
    return a if a in ("relay", "dropit") and is_watcher_ask(meta.get("ask")) else ""


def restore_wait(meta: dict[str, Any], date: str, reset_chases: bool, now: float = 0.0) -> None:
    """Put the wait back on the item with a new end date (the owner's "not yet" or "keep waiting"): its fields as they were, the end moved to `date` (a relay's ask-by, the backstop of an
    anchor wait: its ask_by, the old wake dropped). A moved date resets the backstop and (reset_chases) the chases, a new round; a notice older than `now` is not the wait's arrival."""
    w = meta.get("watch") if isinstance(meta.get("watch"), dict) else {}
    was = dict(w.get("was") or {})
    for k in ("wake", "ask_by"):
        meta.pop(k, None)
    for k, v in was.items():
        if k not in ("wake", "ask_by"):
            meta[k] = v
    meta["ask_by"] = date
    if reset_chases:
        meta.pop("chases", None)
    meta["watch"] = {k: v for k, v in w.items() if k not in ("asked", "was", "failed_at")}
    if now:
        meta["watch"]["set_at"] = now


# ---------------------------------------------------------------------------------------------------------------- the arrival
LIVE_DROP = ("hold", "hold_set", "wake", "wait_basis", "waiting", "wait_failed", "idle", "after", "recycle", "recycle_at", *_model.WAIT_GROUP)      # what the end of a wait clears


def end_wait(meta: dict[str, Any]) -> None:
    """A wait ends (the watcher's arrival, the owner's Done on a step): what LIVE_DROP lists goes, and cap_ok keeps only what lifts the cap on a due date (the owner's words for the
    wake go with the wake), so the item's expected-by is not cut back to the cap and does not resurface early."""
    for k in LIVE_DROP:
        meta.pop(k, None)
    if isinstance(meta.get("cap_ok"), dict):
        co = {k: v for k, v in meta["cap_ok"].items() if k not in ("wake", "by", "quote", "source")}
        if co.get("due"):
            meta["cap_ok"] = co
        else:
            meta.pop("cap_ok", None)


def turn_alive(meta: dict[str, Any], mover: str, what: str, now: float) -> None:
    """The wait is over and the item is an agent's: the hold, the wake, `after` and the wait's fields go, the mover is the post-wake mover (also the one session in needs, so every
    reader of needs sees the same mover), and the arrival is recorded once (`woke`: what arrived and who has it)."""
    end_wait(meta)
    meta["mover"] = mover
    meta.pop("then", None)
    meta["needs"] = [mover]
    meta["woke"] = {"what": what, "to": mover, "at": now}
    if isinstance(meta.get("watch"), dict):
        meta["watch"] = {k: v for k, v in meta["watch"].items() if k not in ("asked", "was", "failed_at")}
        if not meta["watch"]:
            meta.pop("watch")


def turn_to_owner(meta: dict[str, Any], then: str, ask: str, options: list[dict[str, Any]], what: str, now: float) -> None:
    """The wait is over and the item is the owner's move: needs is decision alone (a second mover in needs is refused by the guards; the one who takes it after him is `then`, the post-wake
    mover), the ask and its options up."""
    for k in LIVE_DROP:
        meta.pop(k, None)
    meta.pop("mover", None)
    if then:
        meta["then"] = then
    else:
        meta.pop("then", None)
    meta["needs"] = ["decision"]
    meta["ask"], meta["options"] = ask, options
    meta["woke"] = {"what": what, "to": _model.owner_display(), "at": now}


def woke_line(meta: dict[str, Any], label=str) -> str:
    """get's `woke: <what arrived> → <mover>` ("" when the item has no arrival on record)."""
    w = meta.get("woke")
    if not isinstance(w, dict) or not w.get("what"):
        return ""
    to = str(w.get("to") or "")
    return f"woke: {w['what']} → {label(to) if to and not _model.is_owner(to) else to or 'no one'}"


def chases_line(meta: dict[str, Any], label=str) -> str:
    """get's `chases: n` with the last one's note and who logged it ("" when none)."""
    rows = chases_of(meta)
    if not rows:
        return ""
    last = rows[-1]
    return f"chases: {len(rows)} (last by {label(str(last.get('by') or ''))}: {last.get('note') or ''})"


def world_line(gid_shown: str, subject: str, meta: dict[str, Any]) -> str:
    """One line of the brief's "waiting on the world": the item, what it waits on, its ask-by date, its chases."""
    n = len(chases_of(meta))
    return f"- {gid_shown} {subject}: {subject_of(meta)}, ask by {_model.clean(meta.get('ask_by')) or 'no date'}" + (f", chased {n}x" if n else "")


# ---------------------------------------------------------------------------------------------------------------- the owner's answer
def parse_date(text: Any, today: dt.date | None = None) -> str:
    """The date the owner gave, as YYYY-MM-DD ("" when none can be read, or it is not after today). Reads 2099-03-09, Mar 9th, Mon Mar 9th, 9 Mar, 9th March, tomorrow, next week, in 3 days, in 2 weeks, a weekday name (the next one, "next Monday" too); a month and day without a year is the next one to come. The instance's own words ([keywords.dates]: a month and a day number
    followed by month_suffix and day_suffix, a day number alone, N days or weeks later, tomorrow, the day after tomorrow, next week) read the same."""
    today = today or dt.date.today()
    t = str(text or "")
    low = t.lower()
    best: dt.date | None = None
    mo_s, dy_s, wk_s, lat_s = (_cfg.kw_alt("dates", k) for k in ("month_suffix", "day_suffix", "week_suffix", "later_words"))      # the instance's own date words, "" for none

    def nxt(month: int, day: int) -> dt.date | None:
        for year in (today.year, today.year + 1):
            try:
                cand = dt.date(year, month, day)
            except ValueError:
                continue
            if cand > today:
                return cand
        return None
    m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", t)
    if m:
        try:
            best = dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            best = None
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    mon = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    if best is None:
        m = re.search(rf"(\d{{1,2}})\s*(?:{mo_s})\s*(\d{{1,2}})\s*(?:{dy_s})", t, re.I) if mo_s and dy_s else None
        if m:
            best = nxt(int(m[1]), int(m[2]))
    if best is None:
        m = re.search(rf"\b{mon}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", low)
        md = None
        if m:
            md = (months.index(m[1][:3]) + 1, int(m[2]))
        else:
            m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{mon}\b", low)
            if m:
                md = (months.index(m[2][:3]) + 1, int(m[1]))
        if md:
            best = nxt(*md)
    if best is None:
        m = re.search(rf"(?<!\d)(\d{{1,2}})\s*(?:{dy_s})(?!\s*(?:{lat_s}))" if lat_s else rf"(?<!\d)(\d{{1,2}})\s*(?:{dy_s})", t, re.I) if dy_s else None
        if m:
            y, mo = today.year, today.month
            for _ in range(3):
                try:
                    cand = dt.date(y, mo, int(m[1]))
                except ValueError:
                    cand = None
                if cand and cand > today:
                    best = cand
                    break
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    if best is None:
        units = "|".join(x for x in (dy_s, wk_s) if x)
        m = re.search(r"\bin\s+(\d{1,3})\s+(day|week)s?\b", low) or (re.search(rf"(\d{{1,3}})\s*({units})\s*(?:{lat_s})", t, re.I) if units and lat_s else None)
        if m:
            best = today + dt.timedelta(days=int(m[1]) * (7 if (m[2].lower() == "week" or (wk_s and re.fullmatch(wk_s, m[2], re.I))) else 1))
        elif (a_ := _cfg.kw_alt("dates", "day_after_tomorrow")) and re.search(a_, t, re.I):
            best = today + dt.timedelta(days=2)
        elif re.search(r"\btomorrow\b" + _cfg.kw_pipe(_cfg.kw_alt("dates", "tomorrow")), low):
            best = today + dt.timedelta(days=1)
        elif re.search(r"\bnext week\b" + _cfg.kw_pipe(_cfg.kw_alt("dates", "next_week")), low):
            best = today + dt.timedelta(days=7)
    if best is None:
        days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        m = re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?\b", low)
        if m:
            ahead = (days.index(m[1]) - today.weekday()) % 7 or 7
            best = today + dt.timedelta(days=ahead)
    return best.isoformat() if best is not None and best > today else ""


def answer_effect(meta: dict[str, Any], choice: str, text: str, today: dt.date | None = None) -> dict[str, str]:
    """What the owner's pick on a watcher ask does: {"do": arrived | wait | drop | words | needdate | "", "date": the new end date for a wait}. "" = the pick is not one of this ask's buttons.
    arrived (relay ask's button) → the item goes to its post-wake mover; wait (not yet, or keep waiting) with the date he gave; drop → close as not planned; needdate = a wait button with no date;
    words = an answer in the box with no button: it is never read as arrived or as drop, the item goes to its post-wake mover with his words and the record of the wait, and the mover judges."""
    asked = asked_of(meta)
    if not asked:
        return {"do": ""}
    c = str(choice or "").strip()
    if not c:                              # an answer in the box with no button: his words, which the post-wake mover reads
        return {"do": "words", "text": str(text or "").strip()}
    if asked == "relay" and c == ARRIVED:
        return {"do": "arrived"}
    if c == DROP:
        return {"do": "drop"}
    if (asked == "relay" and c == NOT_YET) or (asked == "dropit" and c == KEEP):
        date = parse_date(text, today)
        return {"do": "wait", "date": date} if date else {"do": NEEDS_DATE}
    return {"do": ""}


# ---------------------------------------------------------------------------------------------------------------- the words of an arrival
def what_time(wake: str) -> str:
    return f"its wake {wake} came"


def what_item(closed: str, how: str) -> str:
    return f"{closed}, the last item it waited on, {how}"


def what_item_backstop(date: str, still_open: list[str]) -> str:
    return f"its backstop {date} came and {', '.join(still_open) or 'the item it waited on'} {'is' if len(still_open) < 2 else 'are'} still open"


def what_anchor(url: str, gist: str, how: str) -> str:
    g = _model.clean(gist)
    return f"a notice from {url} {how}" + (f": {g[:200]}" if g else "")


def what_anchor_silent(url: str, date: str) -> str:
    return f"the anchor stayed silent: {url} had no notice by {date}"


def what_event(ev: dict[str, Any]) -> str:
    """An event wait's arrival: what the server was told (event_waits.arrival)."""
    return _ew.arrival(ev)


def what_event_silent(phrase: Any, date: str) -> str:
    return f"the event did not come: {_ew.words(phrase)} was not reported by {date}"


def message(rows: list[tuple[str, str, str, str]]) -> str:
    """One message to one recipient, rows = [(item shown, what arrived, subject, link)]. One item alone is one line; several are a count and one line each."""
    if len(rows) == 1:
        g, what, subj, link = rows[0]
        return f"[stackshot] {g} is yours now: {what}. {subj} → {link}"
    out = [f"[stackshot] {len(rows)} items are yours now, their waits ended:"]
    out += [f"- {g}: {what}. {subj} → {link}" for g, what, subj, link in rows]
    return "\n".join(out)


def anchor_hit(event: Any, text: Any, auto: bool) -> bool:
    """Does this notice count as the awaited event. Any notice that reaches the server for the anchor does, and the post-wake mover judges a false hit; one exception: a routine line the
    anchor module logged and ruled itself (the fleet's own PR: a push, CI passing, an open) does not end a wait for a merge, a close or a landing, which needs a line that says so."""
    if not auto:
        return True
    if re.search(r"merg|clos|land|done|resolv|finish|complet", _model.clean(event).lower()):
        return bool(re.search(r"merg|clos", _model.clean(text).lower()))
    return True
