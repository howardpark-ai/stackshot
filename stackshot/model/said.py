"""said.py — the owner's own words on an item, checked against his message (the trailers):
the `said` parameter of create, update and complete, a list of {tag, quote, msg, session}, stored on the
item as metadata.said and posted to the item's GitHub issue as kernel-style trailer lines ("Acked-by: the owner <link>"), never
with the quote. The tags are the Linux kernel's: Acked-by (his decision), Suggested-by (his idea or request), Reported-by (a
problem he reported). The check: the message named by `msg` is found in the session's transcript on the server box
(~/.claude/projects/*/<session uuid>.jsonl, and the same under every other configured root), it is his own (type user, origin.kind human, not a meta entry, not a tool
result), not text a tool typed into the pane for him (it starts with the configured marker, [said] injected_marker, which
the fleet tool puts at the start of what it types: sala's `<!-- sala -->`; or, for messages from before the marker, it starts with one of the configured prefixes or contains one of the
configured phrases: stopgaps nothing newer relies on), and the quote is in it, whitespace aside. A readable
transcript that fails the check refuses the write; a transcript the box cannot read (a cloud session, another machine)
stores the entry unchecked.

A second, separate kind of entry (kind "acted", stored with the tag Done-by): proof that the owner DID his steps, never his words.
A message he sends while a session is working (a reply he got elsewhere, pasted in) is not stored as a typed user message: Claude Code
stores it as an attachment entry of type queued_command, chained after a tool result (or a meta user entry) inside the session's turn,
with attachment.origin.kind "human" and his text in attachment.prompt. {kind: acted, quote, msg, session} cites such an entry: it must be
an attachment entry, its attachment.type queued_command, its attachment.origin.kind human, and the quote must be in attachment.prompt
(nothing else of the entry is read). That human-origin entry is itself the proof, so it is accepted wherever it sits in the transcript;
no other entry counts by its position. Every other attachment (hook_additional_context, edited_text_file, file, nested_memory …) and a
queued_command whose origin is a peer, a task notification or missing is refused. The origin is not the whole test: the prompt gets the same
check as his typed words (injected(): the marker, the prefixes and the phrases), since a fleet tool can type its own text into the pane as a
queued message. An acted entry never counts where his words or his
decision are needed: it carries no Acked-by, Suggested-by or Reported-by tag. The audit's N4 (tools/next_report.py) reads a checked one as
proof of his steps ticked on the item within a day after its date.

Pure helpers with no config and no store, shared by the server (the gate and the reply), the GitHub mirror (the trailer lines
of a comment) and the renderer (the History's tags): the caller passes the transcript root, the marker and the prefixes it read.
The one exception is `_owner_words`, which tells whether an item shows the owner's own words: it reads the owner's name from core/instance.py and nothing else."""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from stackshot.core.instance import OWNER
from stackshot.core.lines import newline_lines

TAGS = ("Acked-by", "Suggested-by", "Reported-by")      # his words: the only tags any check of his words or decision reads
ACTED = "acted"                     # the kind of an entry that proves he did his steps (a queued message of his, origin human), never his words
WORDS = "words"                     # the kind of every other entry (the default)
ACTED_TAG = "Done-by"               # the tag an acted entry is stored and shown with; never one of TAGS
KEYS = ("tag", "quote", "msg", "session", "kind")
DEFAULT_ROOTS = ("~/.claude/projects",)   # [said] transcripts: where Claude Code keeps the transcripts on the box (a second config dir, CLAUDE_CONFIG_DIR, keeps its own)
# Stopgaps for messages typed by a fleet tool before it wrote a marker: none by default (an instance lists the ones its tool typed in its own file)
DEFAULT_PREFIXES: tuple[str, ...] = ()      # [said] injected_prefixes: the message starts with one
DEFAULT_PHRASES: tuple[str, ...] = ()       # [said] injected_phrases: the message contains one (the fleet tool's wording)
FORM = ("said=[{tag: Acked-by | Suggested-by | Reported-by, quote: his sentences cut verbatim, msg: the uuid of his message, session: where he said it (optional)}], "
        "or, to prove he did his steps from a message he sent while the session worked (a queued_command attachment entry, origin human), {kind: acted, quote: a piece of its text verbatim, msg: the uuid of the attachment entry, session (optional)}")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TRAILER_RX = re.compile(r"^(?P<tag>Acked-by|Suggested-by|Reported-by|Done-by): (?P<who>[^<\n]+?) <(?P<url>[^>\s]+)>(?P<unchecked> \(unchecked\))?$")
_ANCHOR_RX = re.compile(r"#said-(\d+)$")


def norm_ws(text: Any) -> str:
    """Runs of whitespace collapsed to one space, the ends stripped: how a quote is compared with the message."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_tag(tag: Any) -> str:
    """A tag as given → its canonical spelling; ValueError for anything but the three."""
    t = str(tag or "").strip()
    for k in TAGS:
        if t.lower() == k.lower():
            return k
    raise ValueError(f"said: tag must be one of {' | '.join(TAGS)} — got {t!r}")


def norm_kind(kind: Any) -> str:
    """A kind as given → "words" (absent or "words") or "acted"; ValueError for anything else."""
    k = str(kind or "").strip().lower()
    if k in ("", WORDS):
        return WORDS
    if k == ACTED:
        return ACTED
    raise ValueError(f"said: kind must be {WORDS} (the default: his words) or {ACTED} (proof he did his steps) — got {str(kind)!r}")


def parse(spec: Any) -> list[dict[str, str]]:
    """The tool's `said` argument as given → [{tag, quote, msg, session, kind}], each checked for shape: a list of objects, one
    object (taken as a list of one), or a JSON string of either (a client whose cached schema sends the parameter as text).
    ValueError with the hint on anything else; the transcript check is verify()'s."""
    if isinstance(spec, str):
        s = spec.strip()
        if not s:
            return []
        try:
            spec = json.loads(s)
        except ValueError:
            raise ValueError(f"said: not valid JSON; pass a list of objects, {FORM}")
    if isinstance(spec, dict):
        spec = [spec]
    if spec is None:
        return []
    if not isinstance(spec, list):
        raise ValueError(f"said: a list of objects, {FORM}")
    out: list[dict[str, str]] = []
    for i, x in enumerate(spec):
        if not isinstance(x, dict):
            raise ValueError(f"said[{i}]: an object {{tag, quote, msg, session}} or {{kind: acted, quote, msg, session}}, {FORM}")
        bad = [str(k) for k in x if k not in KEYS]
        if bad:
            raise ValueError(f"said[{i}]: unknown key{'s' if len(bad) > 1 else ''} {', '.join(bad)}; the keys are {', '.join(KEYS)}")
        try:
            kind = norm_kind(x.get("kind"))
            if kind == ACTED:
                t = str(x.get("tag") or "").strip()
                if t and t.lower() != ACTED_TAG.lower():
                    raise ValueError(f"said: an entry of kind {ACTED} proves he did his steps, never his words: leave tag out (it is stored as {ACTED_TAG}) — got tag {t!r}")
                tag = ACTED_TAG
            else:
                tag = norm_tag(x.get("tag"))
        except ValueError as e:
            raise ValueError(str(e).replace("said:", f"said[{i}]:", 1))
        quote = str(x.get("quote") or "")
        if not norm_ws(quote):
            raise ValueError(f"said[{i}] ({tag}): quote is required: " + ("a piece of the text he sent, cut verbatim from the attachment entry's prompt" if kind == ACTED
                                                                            else "his sentences about this item, cut verbatim from his message"))
        msg = str(x.get("msg") or "").strip()
        what = "the attachment entry" if kind == ACTED else "his message"
        if not msg:
            raise ValueError(f"said[{i}] ({tag}): msg is required: the uuid of {what}, the `uuid` field of its transcript entry")
        if not _UUID.match(msg):
            whose = "the attachment entry's" if kind == ACTED else "the message's"
            raise ValueError(f"said[{i}] ({tag}): msg must be {whose} uuid (the `uuid` field of its transcript entry, 36 characters) — got {msg!r}")
        out.append({"tag": tag, "quote": quote.strip(), "msg": msg.lower(), "session": str(x.get("session") or "").strip(), "kind": kind})
    return out


def is_uuid(value: Any) -> bool:
    return bool(_UUID.match(str(value or "").strip()))


def roots_of(value: Any) -> tuple[str, ...]:
    """[said] transcripts as read from the config (one path or a list) → the roots to search; the defaults when absent."""
    return _list_of(value, DEFAULT_ROOTS)


def find_transcript(session: str, roots: Any) -> Path | None:
    """The transcript of a session on this box: <root>/*/<uuid>.jsonl under any of `roots` (one path or several; Claude Code
    keeps one directory per working directory, and each config dir its own projects/); the newest found. None when the
    session is not a transcript uuid or no file carries it."""
    s = str(session or "").strip().lower()
    if not is_uuid(s):
        return None
    hits: list[tuple[float, Path]] = []
    for root in ([roots] if isinstance(roots, (str, Path)) else list(roots or ())):
        try:
            hits += [(p.stat().st_mtime, p) for p in Path(root).expanduser().glob(f"*/{s}.jsonl")]
        except OSError:
            continue
    return max(hits, key=lambda h: h[0])[1] if hits else None


def find_entry(path: Path, msg: str) -> dict[str, Any] | None:
    """The transcript entry whose uuid is `msg`, None when none has it. The file is read line by line; only a line that
    carries the uuid is parsed. OSError when the file cannot be read."""
    m = str(msg or "").strip().lower()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if m not in line.lower():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and str(e.get("uuid") or "").lower() == m:
                return e
    return None


def text_of(entry: dict[str, Any]) -> tuple[str, bool]:
    """A user entry's text (a string content, or its text parts joined) → (text, is_tool_result)."""
    c = (entry.get("message") or {}).get("content") if isinstance(entry.get("message"), dict) else None
    if isinstance(c, str):
        return c, False
    if isinstance(c, list):
        parts = [p for p in c if isinstance(p, dict)]
        if any(p.get("type") == "tool_result" for p in parts):
            return "", True
        return "\n".join(str(p.get("text") or "") for p in parts if p.get("type") == "text"), False
    return "", False


TAIL = 512 * 1024    # bytes read from the end of a transcript to find its last turn


def transcript_error(path: Any, tail: int = TAIL, clip: int = 160) -> str:
    """The error the last turn in this transcript ended in, as Claude Code wrote it (an assistant entry with isApiErrorMessage:
    "Credit balance is too low", "You've hit your weekly limit · resets …", "API Error: 400 You have reached your specified
    workspace API usage limits …"), "" when that turn ended well, when a prompt came after the error (the pane is trying again)
    or when the tail holds no turn at all. Reads the last `tail` bytes only; a tool's result or injected context (isMeta) is
    part of a turn, not a new one; the CLI's other records (system, attachment, mode …) are passed over. The server reads the
    transcripts on its own box with it, and the puller reads the ones on its machine and reports the result."""
    import os
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END); size = f.tell()
            f.seek(max(0, size - tail))
            lines = newline_lines(f.read().decode("utf-8", "replace"))
    except OSError:
        return ""
    if size > tail:
        lines = lines[1:]                                 # the first line of a cut tail is a cut line
    for ln in reversed(lines):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("type") == "assistant":
            if not e.get("isApiErrorMessage"):
                return ""
            text = " ".join(text_of(e)[0].split())
            if len(text) > clip:
                cut = text[:clip].rsplit(" ", 1)[0] if " " in text[:clip] else text[:clip]
                text = cut.rstrip(" ,;:") + " …"
            return text or "an API error"
        if e.get("type") == "user":
            if e.get("toolUseResult") is not None or e.get("isMeta") or text_of(e)[1]:
                continue
            return ""
    return ""


def injected(text: str, prefixes: tuple[str, ...] | list[str] = DEFAULT_PREFIXES, phrases: tuple[str, ...] | list[str] = DEFAULT_PHRASES,
             marker: str = "") -> str:
    """Why a message is text a tool typed into the pane rather than the owner's own: "" when it is not. The marker ([said]
    injected_marker; "" = none) counts when the message STARTS with it, leading whitespace aside ("<marker> Read …" on one
    line, or the marker on a line of its own with the text below); a message that mentions or quotes it further down is his.
    For messages from before the marker two stopgaps: a prefix at the very
    start, a phrase anywhere in the text. Anything not listed passes; nothing newer than the marker relies on them."""
    head = str(text or "").lstrip()
    marker = str(marker or "").strip()
    if marker and head.startswith(marker):
        return f"it starts with the marker {marker!r} ([said] injected_marker)"
    for p in prefixes or ():
        p = str(p or "")
        if p and head.startswith(p):
            return f"it starts with {p!r} ([said] injected_prefixes)"
    for p in phrases or ():
        p = str(p or "")
        if p and p in head:
            return f"it contains {p!r} ([said] injected_phrases)"
    return ""


def check(entry: dict[str, Any] | None, quote: str, prefixes: tuple[str, ...] | list[str] = DEFAULT_PREFIXES,
          phrases: tuple[str, ...] | list[str] = DEFAULT_PHRASES, marker: str = "") -> tuple[str, str]:
    """One rule for every tag → (code, detail): "ok" when `entry` is the owner's own message and the quote is in it;
    "missing" (no such entry), "not_user" (not a user entry), "tool_result", "not_human" (origin.kind is not human: a
    peer's message, a plugin's, none), "meta" (isMeta), "injected" (the marker or a prefix), "quote" (not in the text)."""
    if entry is None:
        return "missing", "no entry has this uuid"
    if str(entry.get("type") or "") != "user":
        t = str(entry.get("type") or "")
        if t == "attachment":
            return "not_user", (f"it is an attachment entry (something pasted or attached in a turn), not a typed user message; to record that he did a step from it, "
                                f"cite it with kind: {ACTED}")
        return "not_user", f"it is a {t or 'typeless'} entry, not a user message"
    text, tool = text_of(entry)
    if tool:
        return "tool_result", "it is a tool result"
    origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
    kind = str(origin.get("kind") or "")
    if kind != "human":
        return "not_human", (f"its origin is {kind}, not human" if kind else "it has no human origin")
    if entry.get("isMeta"):
        return "meta", "it is a meta entry (isMeta), not his typed message"
    why = injected(text, prefixes, phrases, marker)
    if why:
        return "injected", why
    if norm_ws(quote) not in norm_ws(text):
        return "quote", "the quote is not in the message (whitespace aside, the quote is cut verbatim from his words)"
    return "ok", ""


def entry_ts(entry: dict[str, Any]) -> float:
    """The entry's timestamp as epoch seconds, 0.0 when it has none it can read."""
    v = entry.get("timestamp")
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v or "").strip()
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else 0.0
    except (TypeError, ValueError):
        return 0.0


def verify(session: str, msg: str, quote: str, root: Any, prefixes: tuple[str, ...] | list[str] = DEFAULT_PREFIXES,
           phrases: tuple[str, ...] | list[str] = DEFAULT_PHRASES, marker: str = "") -> dict[str, Any]:
    """The check against the transcript on this box → {code, detail, checked, ts, prompt_source, path}: code "ok" (checked
    True), "unreadable" (no transcript for the session here, or one the box cannot read: checked False, nothing refused),
    else one of check()'s failure codes (the caller refuses the write). prompt_source is the entry's promptSource (typed,
    queued, …) for the record only: it never decides the outcome."""
    path = find_transcript(session, root)
    if path is None:
        return {"code": "unreadable", "detail": "no transcript for this session on this box", "checked": False, "ts": 0.0, "prompt_source": "", "path": ""}
    try:
        entry = find_entry(path, msg)
    except OSError as e:
        return {"code": "unreadable", "detail": f"the transcript cannot be read ({e.__class__.__name__})", "checked": False, "ts": 0.0, "prompt_source": "", "path": str(path)}
    code, detail = check(entry, quote, prefixes, phrases, marker)
    return {"code": code, "detail": detail, "checked": code == "ok", "ts": entry_ts(entry) if entry else 0.0,
            "prompt_source": str((entry or {}).get("promptSource") or ""), "path": str(path)}


QUEUED = "queued_command"           # the attachment type of a message he sends while the session works; the only one an acted entry may cite
_ATTACHMENT_WHAT = {                # a plain word on the attachment types a citation most often names by mistake
    "hook_additional_context": "context a hook added to the turn",
    "edited_text_file": "a file edit the CLI noticed",
    "file": "a file read into the turn",
    "nested_memory": "a memory file the CLI loaded",
}


def queued_prompt(entry: dict[str, Any]) -> str:
    """The text of a queued message: its attachment's `prompt` only (a string, or a list of content blocks whose text parts are joined by newlines)."""
    att = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else {}
    p = att.get("prompt")
    if isinstance(p, str):
        return p
    if isinstance(p, list):
        return "\n".join(str(b.get("text") or "") for b in p if isinstance(b, dict) and b.get("type") == "text")
    return ""


def check_acted(entry: dict[str, Any] | None, quote: str, prefixes: tuple[str, ...] | list[str] = DEFAULT_PREFIXES,
                phrases: tuple[str, ...] | list[str] = DEFAULT_PHRASES, marker: str = "") -> tuple[str, str]:
    """The test of a kind-acted entry → (code, detail): "ok" when `entry` (the transcript entry whose uuid was cited) is an attachment entry
    of type queued_command whose attachment.origin.kind is human (a message the owner sent while the session worked, stored by the CLI inside
    the session's turn), the prompt is not text a tool typed into the pane, and the quote is in its attachment.prompt. That entry is itself
    the proof, so where it sits in the transcript is not read, and no other entry is ever accepted by its position. "missing" (no such entry),
    "not_attachment" (any other entry type: a typed message of his is cited as words), "not_queued" (an attachment of any other type: hook
    context, a file, a memory file …), "not_human" (a queued message whose origin is a peer, a task notification, or none), "injected" (the
    prompt starts with the marker or a prefix, or holds a phrase: the same test as his typed words, injected()), "quote" (not in its prompt)."""
    if entry is None:
        return "missing", "no entry has this uuid"
    if str(entry.get("type") or "") != "attachment":
        t = str(entry.get("type") or "typeless")
        return "not_attachment", f"it is a {t} entry, not an attachment entry" + ("; a typed message of his is cited as his words (a tag, no kind)" if t == "user" else "")
    att = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else {}
    atype = str(att.get("type") or "")
    if atype != QUEUED:
        what = _ATTACHMENT_WHAT.get(atype, "")
        return "not_queued", (f"it is a{'n' if atype[:1] in 'aeiou' and atype else ''} {atype or 'typeless'} attachment" + (f" ({what})" if what else "")
                              + f", not a message he sent; only a {QUEUED} attachment with origin human counts")
    origin = att.get("origin") if isinstance(att.get("origin"), dict) else {}
    kind = str(origin.get("kind") or "")
    if kind != "human":
        return "not_human", (f"it is a {QUEUED} whose origin is {kind}, not human" if kind else f"it is a {QUEUED} with no origin, so nothing shows he sent it")
    prompt = queued_prompt(entry)
    why = injected(prompt, prefixes, phrases, marker)
    if why:
        return "injected", why
    if norm_ws(quote) not in norm_ws(prompt):
        return "quote", "the quote is not in the queued message's prompt (whitespace aside, the quote is cut verbatim from the text he sent)"
    return "ok", ""


def verify_acted(session: str, msg: str, quote: str, root: Any, prefixes: tuple[str, ...] | list[str] = DEFAULT_PREFIXES,
                 phrases: tuple[str, ...] | list[str] = DEFAULT_PHRASES, marker: str = "") -> dict[str, Any]:
    """verify() for a kind-acted entry: the same transcript lookup (find_entry streams the file and parses only the line that carries the
    uuid, so a transcript of hundreds of megabytes is never held in memory), the same injected-text test and the same result shape,
    check_acted's codes."""
    path = find_transcript(session, root)
    if path is None:
        return {"code": "unreadable", "detail": "no transcript for this session on this box", "checked": False, "ts": 0.0, "prompt_source": "", "path": ""}
    try:
        entry = find_entry(path, msg)
    except OSError as e:
        return {"code": "unreadable", "detail": f"the transcript cannot be read ({e.__class__.__name__})", "checked": False, "ts": 0.0, "prompt_source": "", "path": str(path)}
    code, detail = check_acted(entry, quote, prefixes, phrases, marker)
    return {"code": code, "detail": detail, "checked": code == "ok", "ts": entry_ts(entry) if entry else 0.0, "prompt_source": "", "path": str(path)}


def _list_of(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        value = [value]
    return tuple(str(p) for p in value if str(p or "")) if isinstance(value, list) else default


def prefixes_of(value: Any) -> tuple[str, ...]:
    """[said] injected_prefixes as read from the config → the tuple to check with; the defaults when the key is absent."""
    return _list_of(value, DEFAULT_PREFIXES)


def phrases_of(value: Any) -> tuple[str, ...]:
    """[said] injected_phrases as read from the config → the tuple to check with; the defaults when the key is absent."""
    return _list_of(value, DEFAULT_PHRASES)


# ----------------------------------------------------------------------------- the stored entries and the trailer lines
def entries_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """metadata.said as a clean list of {tag, quote, session, msg, ts, checked, prompt_source, by, why, kind}; a misshaped entry is
    kept as a blank one (never dropped: the positions are the anchors). kind is "acted" for an entry that proves he did his steps
    (tag Done-by), "words" for every other."""
    v = (meta or {}).get("said")
    out: list[dict[str, Any]] = []
    if not isinstance(v, list):
        return out
    for x in v:
        x = x if isinstance(x, dict) else {}
        try:
            ts = float(x.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        tag = str(x.get("tag") or "")
        kind = ACTED if (x.get("kind") == ACTED or tag == ACTED_TAG) else WORDS
        out.append({"kind": kind, "tag": ACTED_TAG if kind == ACTED else (tag if tag in TAGS else (tag or "?")), "quote": str(x.get("quote") or ""), "session": str(x.get("session") or ""),
                    "msg": str(x.get("msg") or ""), "ts": ts, "checked": bool(x.get("checked")), "prompt_source": str(x.get("prompt_source") or ""),
                    "by": str(x.get("by") or ""), "why": str(x.get("why") or "")})
    return out


def new_entries(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[tuple[int, dict[str, Any]]]:
    """The entries `after` has beyond `before` (the list only grows) → [(position, entry)], position 1-based: the anchor
    said-<position> on the item page."""
    a, b = entries_of(before), entries_of(after)
    return [(i + 1, e) for i, e in enumerate(b) if i >= len(a)]


def anchor(n: int) -> str:
    return f"said-{int(n)}"


def trailer(tag: str, owner: str, url: str, checked: bool) -> str:
    """One kernel-style trailer line for the issue comment: "Acked-by: the owner <https://…/items/<n>#said-2>", " (unchecked)"
    after the link when the transcript could not be read. Never the quote."""
    return f"{tag}: {owner} <{url}>" + ("" if checked else " (unchecked)")


def split_trailers(text: str) -> tuple[str, list[dict[str, Any]]]:
    """A comment's text → (the text without its trailer block, the trailers parsed: [{tag, who, url, n, checked}]). The
    trailers are the last lines of the text, one per line, after a blank line; a text with none is returned as it is."""
    lines = str(text or "").rstrip().split("\n")
    found: list[dict[str, Any]] = []
    while lines:
        m = TRAILER_RX.match(lines[-1].strip())
        if not m:
            break
        a = _ANCHOR_RX.search(m.group("url"))
        found.insert(0, {"tag": m.group("tag"), "who": m.group("who").strip(), "url": m.group("url"), "n": int(a.group(1)) if a else 0,
                         "checked": not m.group("unchecked")})
        lines.pop()
    if not found:
        return str(text or ""), []
    return "\n".join(lines).rstrip("\n").rstrip(), found


def recorded_words(entries: list[dict[str, Any]]) -> str:
    """The log line of a write that recorded his words and changed nothing else: "Acked-by recorded", "Acked-by and
    Reported-by recorded"."""
    tags = []
    for e in entries:
        t = str(e.get("tag") or "")
        if t and t not in tags:
            tags.append(t)
    if not tags:
        return ""
    return (tags[0] if len(tags) == 1 else ", ".join(tags[:-1]) + " and " + tags[-1]) + " recorded"


# A close with the owner's own words on the item was told to a
# front agent mover in one line, and no other close was; that close is a row on his For you list (notify/foryou.py),
# and the same words make an item watched there (_foryou_watched). The front agent mover is told of any close by another
# session, his words or not, in its own marked line (tell_owner_close), beside that row. His words are on it when (1) a `said` entry is (metadata.said: his sentences
# cut from his own message, checked against his transcript), or (2) the description or the close's reason quotes him: his name and a colon
# before an opening quote mark, or his name, a comma and a weekday. The second is the loosest and deliberately
# narrow. A board answer alone does not count: answering a decision picks an option, it does not ask to hear of the close.
_OWNER_QUOTED = re.compile(rf"\b{re.escape(OWNER)}\b[^:\n]{{0,40}}:\s*[\"“]|\b{re.escape(OWNER)}, (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")


def _owner_words(item: dict[str, Any]) -> str:
    """What shows the owner's own words (the owner's) are on the item, in the order of how certain it is: "a said entry", "quoted in
    the text"; "" when none (see _OWNER_QUOTED). A board answer alone is not his words about the close: answering a decision is
    picking an option, not asking to hear of the close."""
    meta = item.get("metadata") or {}
    if any(e["quote"] and e["tag"] in TAGS for e in entries_of(meta)):     # unchecked counts on purpose: a quote attached with Acked-by is still his words on record
        return "a said entry"
    if item.get("status") == "completed" and str(meta.get("outcome_text") or "").strip():      # a close keeps the description (the item's background, which may quote him for any reason): what the close wrote is its outcome text and its reason
        text = f"{meta.get('outcome_text')}\n{meta.get('reason') or ''}"
    else:
        text = f"{item.get('description') or ''}\n{meta.get('reason') or ''}"
    if _OWNER_QUOTED.search(text):
        return "quoted in the text"
    return ""
