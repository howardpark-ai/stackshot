"""question.py: `client.py post question`, a script's question for the owner as a needs=decision item.

`_question` files one open item on a project for the owner, under the project's front agent, written by a script on a machine; it goes through the create tool's own code (service/create.py), so the subject prefix,
the ask's form, the options, the page-debt rules and the GitHub mirror all apply. `_question_text` turns the script's text into the item's `- ` bullets. `_QUESTION_LOCK` makes the look in the request map and the write
one step. The write sets the QUESTION flag of service/writes.py for its duration (the guard on alarming words does not judge a script's text), and the terminal prompt and the job gap use the same flag.

A service module: it reads the project record and the store and writes through `create_item`. The route that calls it (`_client_post`) is the surface's.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import bullet_text as _bt
from stackshot.model.field_gates import _bullets_on, _description_limits, _fit, _subject_max
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import create as _create_svc
from stackshot.service import item_read as _item_read
from stackshot.service import owner_words as _owner_words
from stackshot.service import store as _svcstore
from stackshot.service import writes as _writes


_QUESTION_LOCK = threading.Lock()
_QUESTION_MAX_CHARS = 8000       # a question's text, well under GitHub's 65,536-character issue body


def _question_text(text: str, machine: str, sender: str) -> tuple[str, str]:
    """The question's text as an item's description -> (the description, "") or ("", why it is refused). A script's lines are written as `- `
    bullets (a bullet or star marker it already carries is not doubled; a line with no letter or digit is skipped), each clipped by how it reads to [description]
    line_max characters at a word outside any link, with an ellipsis (bullet_text.clip_bullet: the description gate judges the item like any create),
    and the last bullet says who filed it (clipped the same way, so a long sender is never a 400), so the owner sees it on the item page and in the GitHub issue
    body, which both show the description: "- Filed by <sender> (a script on <machine>)". A text over the description gate's line limit ([description] max_lines
    non-blank lines, less the one bullet of provenance) or over _QUESTION_MAX_CHARS is refused, and the script shortens it. With [description] require_bullets =
    false the text is kept as it was before an earlier change: its lines as written, then a blank line and the plain line "Filed by <sender> (a script on <machine>)"."""
    max_lines, line_max = _description_limits()
    limit = max_lines - 1
    body = text.strip()
    on = _bullets_on()
    lines = _bt.clean_lines(body) if on else [ln for ln in body.splitlines() if ln.strip()]       # a line that is empty once its marker is off (or has no letter or digit) is no line
    if not lines:
        return "", "the question's text has no line of words (only markers, digits or punctuation)"
    if len(lines) > limit:
        return "", f"the question's text has {len(lines)} lines and an item's description takes at most {limit} (one more is the line that says who filed it); shorten it, and put long detail on the project's page"
    if len(body) > _QUESTION_MAX_CHARS:
        return "", f"the question's text has {len(body)} characters and at most {_QUESTION_MAX_CHARS} are taken; shorten it, and put long detail on the project's page"
    if not on:
        return "\n".join(ln.rstrip() for ln in body.splitlines()) + f"\n\nFiled by {sender} (a script on {machine})", ""
    out = [_bt.clip_bullet("- " + t, line_max) for t in lines]
    return "\n".join(out + [_bt.clip_bullet(f"- Filed by {sender} (a script on {machine})", line_max)]), ""


def _question(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post question --project P --ask "…" --subject "…" --request-id T [--option "label=line" …] [--recommended label] [--sender label]`
    (the question text on stdin): file an open needs=decision item on project P for the owner, filed under the project's front agent (its
    -main agent first, as the create tool's owner refusals name them), written by a script on `machine` named `sender`. It goes
    through create_item (service/create.py), the create tool's own code: the subject prefix, the ask's form, the options (2 to 6, exactly one recommended),
    the one-decision gate, the project page, the page-debt rules (charged to the page's keeper only) and the GitHub mirror all apply, and a refusal is
    the tool's text (400). A project that lists no front agent is refused (409). The subject and the request_id are required: there is no
    default prefix, and every filing is safe to repeat. The call is idempotent per (machine, sender, request_id): the same triple again
    answers the same item and files nothing, kept in the server's request map (REQUESTS in service/create.py, <state>/requests.json) like a tool create's
    request_id; an entry whose item is gone files anew. The text is written as `- ` bullets, each clipped to the line limit; too many lines or characters is a 400. The description ends
    with the bullet "- Filed by <sender> (a script on <machine>)". -> (status, {item, project, owner, repeat})."""
    project, ask, sender, subject, rid = (str(body.get(k) or "").strip() for k in ("project", "ask", "sender", "subject", "request_id"))
    text = body.get("text") if isinstance(body.get("text"), str) else ""
    options = body.get("options")
    if not (project and ask and text.strip()):
        return 400, {"error": "project, ask and text are required: the project, the ask line (Decide: \u2026 \u00b7 Recommend: \u2026 \u00b7 Stakes: \u2026 \u00b7 By: \u2026) and the question's text"}
    if options is not None and not isinstance(options, list):
        return 400, {"error": "options is a list of {label, line, recommended}"}
    if not subject:        # no default prefix: a question filed under another scope's prefix would land in the wrong place on the board
        return 400, {"error": "subject is required (--subject): the item's subject, which must start with one of the instance's subject prefixes "
                              + " or ".join(f"{p!r}" for p in _cfg.CFG["subject"]["prefixes"]) + ", then the action and its object"}
    if not rid:
        return 400, {"error": "request_id is required (--request-id): a token of the script's own, the same each time one question is filed again, so a retry files nothing twice"}
    if len(rid) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in rid):
        return 400, {"error": "request_id = a token of the script's own: one line of at most 120 characters"}
    sender = sender or "client.py"
    if len(sender) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender):
        return 400, {"error": "sender = the script's own label: one line of at most 80 characters (nightly-job, size-watch)"}
    try:
        _owner_words._sender_not_owner(sender)
    except ToolError as e:
        return 400, {"error": str(e)}
    try:
        recs = _prj.refs(project, _registry("projects"))
    except ValueError as e:         # the project record's id file is damaged (projects.py raises, mints and writes nothing): nothing was filed, say so
        return 503, {"error": f"the project record cannot be read right now, nothing was filed: {e}"}
    if not recs:
        return 404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"}
    if len(recs) > 1:
        return 400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"}
    key = recs[0]["key"]
    front = sorted(_item_read._hub_sessions(key)[3], key=lambda n: (not n.endswith("-main"), n))
    if not front:
        return 409, {"error": f"{key} lists no front agent (a user-facing agent under `agents:` on its page, or its hub's), so there is nobody to take the question after {OWNER} answers; "
                              "a front agent lists itself first (client.py post project-agent)"}
    desc, why = _question_text(text, machine, sender)
    if why:
        return 400, {"error": why}
    try:
        with _QUESTION_LOCK:       # the check of the request map and the write are one step, so two calls with one triple file one item
            _writes.QUESTION.on = True
            try:
                subject = _fit(_svcstore._shown_ids(subject), _subject_max())      # a script's subject is cut to the limit (ids expanded first), never refused: a script's item must not be lost on a 400
                gid, _reply = _create_svc.create_item(subject=subject, description=desc, project=key, owner=front[0], then=front[0], needs=["decision"], ask=ask, options=options,      # the project's -main agent takes it after the owner
                                           by=f"{sender} (a script on {machine})", request_id=f"question\x1f{machine}\x1f{sender}\x1f{rid}")
            finally:
                _writes.QUESTION.on = False
        meta = _svcstore._load(gid).get("metadata") or {}
    except ToolError as e:
        return 400, {"error": str(e)}
    return 200, {"item": _gh.shown(gid), "project": str(meta.get("project") or key), "owner": _sr._session_label(str(meta.get("owner") or "")) or front[0],
                 "repeat": _reply.startswith("already created")}
