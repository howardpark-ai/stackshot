"""owner_words.py: what a write says about the owner's own words and who wrote it: the refusal of a session that names itself the owner (`_sender_not_owner`), the reply's lines on what a write recorded (`_said_note`), what shows
the owner's words behind a long wait (`_owner_words_on`, `_owner_quote_on`), the records of those words and of a wait's basis (`_cap_ok_put`, `_cap_ok_drop`, `_basis_put`), the mention-safe text of a mirrored comment (`_no_ping`),
and the writers the client routes call for a script: the sender of a script's call (`_script_sender`), the record of the owner's words behind a wake (`_cap_words_entry`, `_record_cap_words`), the description rewritten as bullets
(`_rebullet_write`) and the retired state route (`_state_write`). How an item may end (`OUTCOMES`), the sentence a refused close ends with (`_RELAUNCH`) and the words the wait-basis gate names a park by (`_BASIS_WORDS`)
are values of the write path that sit here beside them.

A service module: it reads the store, the config, the record of what was said and the clock, and writes an item only through `writes.save` and the update path, under the item lock. The debounced publish of the board and the
board's words for a time and its time zone are the surface's, reached through service/save_hooks.py."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import retired_inputs as _retired
from stackshot.core.instance import OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model_guards as _mg
from stackshot.model import rebullet as _rebullet
from stackshot.model import said as _said
from stackshot.model.bullet_text import _clip_line
from stackshot.model.field_gates import _bullets_on, _description_limits
from stackshot.model.ids import _norm_id
from stackshot.service import store as _svcstore
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import waiting as _wt


# A close carries how the item ended, like an issue tracker's closed issue. Before, a completed
# item kept its state from just before the close (its next, ask and whose move), which read as live work.
OUTCOMES = ("done", "dropped", "superseded")

# claude.ai caches a connector's tool list for about a day and a relaunch does not refresh it (claude-ai-mcp#45, #1044),
# so a session whose cached complete predates the close fields closes through the portal's Code Mode, which reads the live schema.
_RELAUNCH = (" If this tool shows no outcome, reason, outcome_text or superseded_by parameter, this session's cached tool list predates them: claude.ai "
             "refreshes it on its own within about a day, and a relaunch does not. Meanwhile close through the MCP Portal: "
             "portal_codemode_execute with codemode.stackshot_complete({item_id, outcome, reason, outcome_text, superseded_by}).")


def _sender_not_owner(sender: str) -> None:
    """only the server writes as the owner ([instance] owner, the owner). His own answer comes from the board's sign-in
    (POST /items/<n>/answer) and is headed `[author: the owner · board]`; a session that names itself the owner as the sender of an
    update, complete or confirm is refused, so no session's write can pass for his. The check reads the name as given and the
    session's name behind an id."""
    s = str(sender or "").strip()
    if not s:
        return
    norm = lambda x: re.sub(r"[^0-9a-z]+", " ", str(x or "").lower()).strip()
    o = norm(OWNER)
    if o and {norm(s), norm(_sr._session_label(s))} & {o, o + " board"}:
        raise ToolError(f"Refused: sender names {OWNER}. Only the board writes as {OWNER} (his answer from the item's page); "
                        f"pass sender=<your own session name or id>. When you write down what {OWNER} said, you are its author.")


def _said_note(entries: list[dict[str, Any]]) -> str:
    """The reply's lines on what the write recorded: checked against which transcript, or stored unchecked and why."""
    out = ""
    for e in entries:
        label = _sr._session_label(str(e.get("session") or "")) or "the sender"
        what = f"{e['tag']} (kind acted: proof he did a step, not his words)" if e.get("kind") == _said.ACTED else e["tag"]
        out += f"\n(said: {what} " + (f"checked against {label}'s transcript" if e.get("checked") else f"stored unchecked: {e.get('why') or 'the transcript could not be read'}") + ")"
    return out


def _owner_words_on(item: dict[str, Any], said_l: list[dict[str, Any]], within_days: float) -> str:
    """What shows the owner's own words behind a long wait (waiting.py's cap): a said entry in this very call tagged Acked-by,
    checked against a real transcript, of a message no older than `within_days` ("a checked said entry"), else a board answer of his
    (a decision or a comment with text or a choice) given on this item since its last state change ("a board answer"); "" when
    none. An unchecked entry (a transcript this box cannot read) is not enough: the words behind a long wait must be provable, so
    that case asks him to answer on the item."""
    return _owner_quote_on(item, said_l, within_days)[0]


def _owner_quote_on(item: dict[str, Any], said_l: list[dict[str, Any]], within_days: float) -> tuple[str, str, str]:
    """_owner_words_on with the words themselves → (what shows them, his sentence, where it is from); ("", "", "") when none. The sentence is the said entry's quote or the board
    answer's text (an option's line when the answer was a button): the quote a time wait carries as its reason (the snooze guard)."""
    now = time.time()
    said_hits: list[tuple[str, str, str]] = []
    for e in said_l:
        try:
            if e.get("checked") and e.get("tag") == "Acked-by" and float(e.get("ts") or 0) >= now - within_days * 86400.0:
                said_hits.append(("a checked said entry", " ".join(str(e.get("quote") or "").split()), f"{OWNER}'s words, an Acked-by said entry checked against a transcript"))
        except (TypeError, ValueError):
            continue
    answers = (item.get("metadata") or {}).get("answers")
    clock = _wt.clock_of(item, now) if item else 0.0
    ans_hits: list[tuple[str, str, str]] = []
    for a in answers if isinstance(answers, list) else []:
        try:
            if isinstance(a, dict) and (a.get("text") or a.get("choice")) and float(a.get("ts") or 0) >= clock - 0.5:
                via = "the board" if a.get("via") == "board" else "GitHub"
                ans_hits.append(("a board answer", " ".join(str(a.get("text") or a.get("choice_line") or "").split()), f"{OWNER}'s {'answer' if a.get('kind') == 'decision' else 'note on his step' if a.get('kind') == 'step-reply' else 'comment'} on {via}"))
        except (TypeError, ValueError):
            continue
    hits = said_hits + ans_hits
    if not hits:
        return "", "", ""
    best = next((h for h in reversed(hits) if _mg.has_wait_words(h[1])), hits[-1])    # the latest whose words park, wait or name a date (the one a time wait can stand on), else the latest
    return hits[0][0], best[1], best[2]              # what shows them is the first kind, a said entry before a board answer, as it always was


def _cap_ok_put(meta: dict[str, Any], key: str, value: str, by: str, quote: str = "", source: str = "") -> None:
    """Record that the owner's words stand behind this wake or due date (metadata.cap_ok: wake + by, due + due_by); waiting.py honours
    the record only for that very date. `quote` and `source` (his sentence as the store holds it, and where from: the answer or comment
    and the commit) are kept beside it for the wake, so a person can see on what the long wait stands (get and the item page show them)."""
    co = dict(meta["cap_ok"]) if isinstance(meta.get("cap_ok"), dict) else {}
    co[key] = value
    co["by" if key == "wake" else "due_by"] = by
    if key == "wake":
        for k, v in (("quote", quote), ("source", source)):
            if v:
                co[k] = v
            else:
                co.pop(k, None)
    meta["cap_ok"] = co


def _cap_ok_drop(meta: dict[str, Any], key: str) -> None:
    """Drop the record for a wake or due date that goes, changes or was accepted without his words; the record goes when it holds neither."""
    co = meta.get("cap_ok")
    if isinstance(co, dict):
        co = {k: v for k, v in co.items() if k not in (key, "by" if key == "wake" else "due_by", *(("quote", "source") if key == "wake" else ()))}
        if co.get("wake") or co.get("due"):
            meta["cap_ok"] = co
            return
    meta.pop("cap_ok", None)


_BASIS_WORDS = "a real-world date"


def _basis_put(meta: dict[str, Any], text: str, wake: str, by: str) -> None:
    """metadata.wait_basis for this very wake: {text, wake, by, at}."""
    meta["wait_basis"] = {"text": text, "wake": wake, "by": by, "at": time.time()}


def _no_ping(text: str) -> str:
    """Text bound for a GitHub comment with every @ broken by a zero-width space, so that a mention in an item's text or in his words pings no one."""
    return str(text).replace("@", "@\u200b")


def _script_sender(body: dict[str, Any], machine: str) -> str:
    """The `sender` of a cap-words call (required: the session that ran the job, as every client call's sender is its own word; the machine token proves
    the machine) → "<sender> via a script on <machine>", which the record keeps as who recorded it."""
    sender = " ".join(str(body.get("sender") or "").split())
    if not sender or len(sender) > 80:
        raise ToolError("Refused: sender is required, the name of the session that runs this job (at most 80 characters)")
    return f"{sender} via a script on {machine}"


def _cap_words_entry(gid: str, spec: dict[str, Any], item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The gates of _record_cap_words that read the item alone (no history): it is open, it has a wake, the entry the caller names stands in
    metadata.answers, it is his own words (kind decision or comment, via board or github, a GitHub one with its comment id and url; the words are what
    he typed, else the option he pressed and its line: waiting.answer_words), and it reads as a park (what he typed: waiting.park_words; a button: park_words or a
    "wait" word, waiting.answer_parks, which the migration's park_quote takes too). → (the wake, the entry). Run once before the store's history is read and again under the item lock."""
    meta = item.get("metadata") or {}
    if item.get("status") != "open":
        raise ToolError(f"Refused: {_gh.shown(gid)} is not open; words are recorded for an open item's wake")
    wake = str(_wt.wake_value(meta) or "")
    if not wake:
        raise ToolError(f"Refused: {_gh.shown(gid)} has no wake date for his words to cover")
    entries = [a for a in meta.get("answers") or [] if isinstance(a, dict)]
    ts, cid = spec.get("ts"), spec.get("comment_id")
    hit = None
    for a in entries:
        try:
            if (ts is not None and abs(float(a.get("ts") or 0) - float(ts)) < 1e-6) or (cid is not None and a.get("comment_id") is not None and int(a["comment_id"]) == int(cid)):
                hit = a
                break
        except (TypeError, ValueError):
            continue
    if hit is None:
        raise ToolError(f"Refused: {_gh.shown(gid)} holds no answer or comment of his with {'ts ' + str(ts) if ts is not None else 'comment_id ' + str(cid)}; only entries in its metadata.answers count")
    text = _wt.answer_words(hit)
    if hit.get("kind") not in ("decision", "comment") or hit.get("via") not in ("board", "github") or not text:
        raise ToolError(f"Refused: that entry is not {OWNER}'s own words with text (kind decision or comment, via board or github)")
    if hit.get("via") == "github" and not (hit.get("comment_id") is not None and str(hit.get("url") or "").strip()):
        raise ToolError(f"Refused: a GitHub entry counts only with its comment id and url (the reader's mark that {OWNER} wrote it by hand)")
    if not _wt.answer_parks(hit):
        if not str(hit.get("text") or "").strip():
            raise ToolError(f"Refused: that button is not {OWNER}'s own words that park or wait ({_clip_line(text, 80)!r}); a button counts when its option and line park or wait")
        raise ToolError(f"Refused: {OWNER}'s words on {_gh.shown(gid)} do not park or postpone it ({_clip_line(text, 80)!r}); only words that do can stand behind a long wait")
    return wake, hit


def _record_cap_words(spec: dict[str, Any], machine: str) -> dict[str, Any]:
    """One-time job of the quick fix for items the owner himself parked whose answer was never saved as his words: record, as
    metadata.cap_ok for the item's current wake, a sentence of his that the store already holds. Only text the store attributes to him is taken,
    never a quote the caller gives: the caller names the entry, `{"ts": the answer's time}` or `{"comment_id": n}`, as it stands in metadata.answers
    (written only by the board's answer form with his sign-in, kind decision or comment, via board, and by the GitHub reader for his own hand-written
    comments, via github with the comment's id and url; no session's tool writes there), and the server copies the quote from that entry. The entry must
    read as a park (waiting.park_words: "Approve" or "sent" is his but no park), must stand behind the current wake (waiting.entry_pairs: given since the move that set it, or the last thing before it, no state move between them by the store's git history, else within 24 hours), the item must be open with a wake, and `quote`, when the caller sends
    it, must be the entry's text (a stale pick is refused). `commit` (the store commit that first held the entry) is kept as provenance. The record
    is a filing edit made under the item lock through `writes.save`: no clock moves, History gets one line (the store's git, render.Board.item_log). → {"item", "wake", "quote", "source", "action": set | already}; refusals raise ToolError."""
    by = _script_sender(spec, machine)
    gid = _norm_id(str(spec.get("item") or ""))
    # The cheap gates first, on a read taken before the lock: the entry must be his and read as a park. Only then the store's history is read (a
    # subprocess that can take seconds, never while holding the item lock, which every other write waits on); the result is checked again under the lock.
    item0 = _svcstore._load(gid)
    wake0, hit0 = _cap_words_entry(gid, spec, item0)
    read_prior = not _wt.entry_current(item0, hit0.get("ts"), time.time())
    prior = _wt.prior_state_ts(gid, wake0) if read_prior else None
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        meta = dict(item.get("metadata") or {})
        wake, hit = _cap_words_entry(gid, spec, item)
        text = _wt.answer_words(hit)
        now_t = time.time()      # as _owner_words_on, but his answer usually comes just BEFORE the session's move on it: waiting.entry_pairs
        current = _wt.entry_current(item, hit.get("ts"), now_t)
        if wake != wake0 or item.get("state_updated") != item0.get("state_updated") or (not current and not read_prior):
            raise ToolError(f"Refused: {_gh.shown(gid)} moved while its history was being read (its wake or state changed); run the job again")
        ok, how = _wt.entry_pairs(item, hit.get("ts"), now_t, None if current else prior)
        if not ok:
            raise ToolError(f"Refused: that entry of {OWNER}'s does not stand behind {_gh.shown(gid)}'s current wake or hold: {how}"
                            + ("" if how == _wt.UNREADABLE_WHY else f". Ask {OWNER} to answer on the item again"))
        quote = str(spec.get("quote") or "")
        if quote and " ".join(quote.split()) != " ".join(text.split()):
            raise ToolError(f"Refused: the quote is not what the entry says ({_clip_line(text, 80)!r}); the server records the entry's own text")
        when = _hooks().when_words(dt.datetime.fromtimestamp(float(hit.get("ts") or 0), _hooks().zone()))
        kind = "comment" if hit.get("kind") == "comment" else "answer"
        src = f"{OWNER}'s {kind} on {'the board' if hit.get('via') == 'board' else 'GitHub'}, {when}" + (f" (comment {hit['comment_id']}, {str(hit.get('url') or '').strip()})" if hit.get("comment_id") is not None else "")
        commit = re.sub(r"[^0-9a-f]", "", str(spec.get("commit") or "").lower())[:12]
        if commit:
            src += f"; first in store commit {commit}"
        co = meta.get("cap_ok") if isinstance(meta.get("cap_ok"), dict) else {}
        if co.get("wake") == wake and co.get("quote") == text:
            return {"item": _gh.shown(gid), "wake": wake, "quote": text, "source": str(co.get("source") or src), "action": "already"}
        _cap_ok_put(meta, "wake", wake, by, quote=text, source=src)
        item["metadata"] = meta
        item["updated"] = time.time()          # the item's own clock; the state clock and the confirm stay (a filing edit): the cap runs from the last move, and his words lift it
        # Bookkeeping, not activity (no kind, no writer): this copies words the store already holds from his entry in metadata.answers, which moved the clock when it arrived; a script's filing edit that
        # moved no clock, so counting it would make an old answer read as new work whenever the job runs.
        _writes.save(gid, item, note=f"his words recorded for the wake {wake}: {_no_ping(_clip_line(text, 200))} ({_no_ping(src)}), by {_no_ping(by)}")
        _hooks().publish()
    return {"item": _gh.shown(gid), "wake": wake, "quote": text, "source": src, "action": "set"}


def _rebullet_write(spec: dict[str, Any], machine: str) -> dict[str, Any]:
    """tools/rebullet_descriptions.py: one open item's description rewritten as short bullets, through the update path (its gates, its History line, the
    the search), under the item lock, as the author `rebullet`. The body: item, sender, old (the description the rewrite was made from) and description
    (the rewrite). This is the only writer of the pass: the caller's token must be a machine in [model] rebullet_machines (default: the server box); the item must be open and its
    description still the `old` the rewrite was made from (a session's edit since then wins and the rewrite is dropped); and rebullet.verdict judges the rewrite here too,
    so a lossy one (a link, a number, a date or a quote gone) is refused whoever sends it. The write is a filing edit (REFORMAT): the item's state clock and its confirm stay (its `updated` time does move), no page
    is owed and no one is told. `sender` must not name a session. → {"item", "action": set | already, "result"}; refusals raise ToolError."""
    allowed = _cfg.get("model", "rebullet_machines", default=[])
    allowed = [allowed] if isinstance(allowed, str) else [str(x) for x in allowed] if isinstance(allowed, list) else []
    if not machine or machine not in allowed:
        raise ToolError("Refused: the re-bullet pass writes only from the server box (a machine in [model] rebullet_machines; none is set when the list is empty)")
    by = _script_sender(spec, machine)
    if " ".join(str(spec.get("sender") or "").split()).casefold() in _mg.Ctx().roster():
        raise ToolError("Refused: sender names a session; the pass writes as itself (rebullet), never as a session")
    gid = _norm_id(str(spec.get("item") or ""))
    old, new = spec.get("old"), spec.get("description")
    if not isinstance(old, str) or not isinstance(new, str) or not new.strip():
        raise ToolError("Refused: old (the description the rewrite was made from) and description (the rewrite) are required strings")
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        if item.get("status") != "open":
            raise ToolError(f"Refused: {_gh.shown(gid)} is not open; a closed item is left alone")
        cur = str(item.get("description") or "")
        if cur.strip() == new.strip():
            return {"item": _gh.shown(gid), "action": "already", "result": ""}
        if cur.strip() != old.strip():
            raise ToolError(f"Refused: the description of {_gh.shown(gid)} changed since the rewrite was made from it; nothing was written")
        why = _rebullet.verdict(cur, new, max_lines=int(_cfg.CFG["description"].get("max_lines", 8)), line_max=_description_limits()[1], strict=_bullets_on(), forbid=list(_cfg.CFG["description"].get("forbid_tokens", [])),
                                  subject=str(item.get("subject") or ""))
        if why:
            raise ToolError(f"Refused: {why}")
        _writes.REFORMAT.on = True
        try:
            out = _update_svc._update(gid, description=new, sender=by)
        finally:
            _writes.REFORMAT.on = False
    return {"item": _gh.shown(gid), "action": "set", "result": out.splitlines()[0] if out else ""}


def _state_write(spec: dict[str, Any], machine: str) -> dict[str, Any]:
    """POST /client/state: retired, an item stores alive or waiting directly now, so the route has no state to set or clear (retired_inputs.client_refusal). It still answers, with the refusal that names the
    fields to pass through update, and writes nothing; its caller's token is checked first as for any client route. A refusal raises ToolError (the route answers 400)."""
    _script_sender(spec, machine)
    raise ToolError(_retired.client_refusal(OWNER))
