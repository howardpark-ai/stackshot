"""brief.py — the item brief: a short view of one item for deciding, beside the item's own page (the detail view).

article() is the one drawing, from the item's own fields: the head, what the item asks or the step, a draft to paste, the outcome or the wait, the first lines of its description,
the answer box and the last answers. page() is that article as a page of its own (GET /items/<key>/brief); the home page's panel reads the same page and takes the article out
(ui/brief_assets.py). Nothing here writes, and nothing here decides who may answer: the answer box is the item page's own (Board.item_html hands it over), posting to the one answer route.
"""
from __future__ import annotations

import re
from typing import Any

from stackshot.core import config as _cfg, members as _members
from stackshot.github import ghsync as _gh
from stackshot.model import option_labels as _ol
from stackshot.web.i18n import t as _t
from stackshot.web.ui import answer_frame as _frame, brief_assets as _assets, explain as _xp, render as _r, under

esc = _r.esc
_LEAD = 5                  # the pieces of the description shown before the rest folds
_PAST = 3                  # the last answers listed
_TOP = re.compile(r"(?:[-*+]|\d{1,9}[.)])\s|#{1,6}\s")      # a line at the margin that starts a piece of its own: a bullet, a numbered line, a heading
_FENCE = re.compile(r"\s*(```|~~~)")


def pieces(text: str) -> list[str]:
    """A description cut where it can be: one piece per bullet or numbered line at the margin (with what is indented under it), per heading and per paragraph; a fenced block is never cut."""
    out: list[list[str]] = []
    fence = ""
    blank = False
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence:
            out[-1].append(line)
            if m and m.group(1) == fence:
                fence = ""
            continue
        if not line.strip():
            blank = True
            continue
        indented = line[0] in " \t"
        if not out or (not indented and (blank or _TOP.match(line) or (m and out[-1]))):
            out.append([line])
        else:
            if blank:
                out[-1].append("")
            out[-1].append(line)
        blank = False
        if m:
            fence = m.group(1)
    return ["\n".join(p) for p in out]


def _join(parts: list[str]) -> str:
    """The pieces back as one text: list lines stay one list, anything else is a paragraph of its own."""
    text = ""
    for p in parts:
        if text:
            last = text.rsplit("\n\n", 1)[-1]
            text += "\n" if _TOP.match(p) and not p.startswith("#") and _TOP.match(last) and not last.startswith("#") else "\n\n"
        text += p
    return text


def _section(cls: str, head: str, body: str) -> str:
    return f'<section class="bsec {cls}"><h3>{esc(head)}</h3>{body}</section>'


def _background(board: Any, r: dict[str, Any]) -> str:
    desc = (r.get("description") or "").strip()
    if not desc or desc == r["subject"]:
        return ""
    md = lambda part: f'<div class="desc md">{board.md_html(_join(part), r["gid"])}</div>'
    cut = pieces(desc)
    body = md(cut[:_LEAD])
    rest = cut[_LEAD:]
    if rest:
        label = _t("brief.more_one" if len(rest) == 1 else "brief.more", n=len(rest))
        body += f'<details class="bmore"><summary>{esc(label)}</summary>{md(rest)}</details>'
    return _section("bbg", _t("brief.background"), body)


def _ask(board: Any, r: dict[str, Any], p: dict[str, Any], cards: bool) -> str:
    """What the item asks, shorter than on its page: the recommendation is left to the card that carries its badge, and a date line that says there is none is left out.
    Whether there is anything to show is the page's own rule (p["ask"] is empty when the item asks this viewer nothing)."""
    if not p["ask"] or not p["pa"]:
        return p["ask"]
    pa, gid = p["pa"], r["gid"]
    badged = cards and 'class="badge rec"' in p["box"]
    rows = []
    for key, label in (("decide", "item.ask.decide"), ("recommend", "item.ask.recommend"), ("stakes", "item.ask.stakes"), ("by", "item.ask.by")):
        value = pa[key]
        if (key == "recommend" and badged) or (key == "by" and value.strip().rstrip(".").lower() in ("", "no date")):
            continue
        link = _r.mockup_link(r, _r.open_ask(r)) if key == "decide" else ""
        rows.append(f'<dt>{_t(label)}</dt><dd>{board.linkify(value, gid)}{link}</dd>')
    listed = f'<b class="osub">{_t("home.options")}</b>{p["ol"]}' if p["ol"] and not cards else ""      # no cards drawn: the options are listed here, as on the item's page
    return f'<div class="iask"><b>{_t("item.ask")}</b><dl>{"".join(rows)}</dl>{listed}</div>'


def _step(step: str, key: str) -> str:
    """The page's step block and form, with the line about Send note behind a "?" instead of a hover title."""
    head, mark, tail = step.partition(" data-needs-text>")
    if not mark:
        return step
    hint = _t("home.step_send_note_hint")
    head = head.replace(f' title="{esc(hint)}" data-hint="{esc(hint)}"', "")
    label, close, rest = tail.partition("</button>")
    return head + mark + label + close + _xp.explain(f"brief-note-{key}", hint, _t("home.step_send_note")) + rest


def _box(form: str, key: str) -> str:
    """The page's answer box laid out for the brief: the box's words as its placeholder, and under option cards a foot (what is picked, the note, Send) that stays in view."""
    if not form:
        return ""
    cards = " data-cards " in form
    words = "home.note_optional" if cards else "answer.write_answer" if 'value="answer"' in form else "answer.write_comment"
    form = form.replace('<textarea id="atext" name="text" rows="3" maxlength="4000"></textarea>',
                        f'<textarea id="atext" name="text" rows="3" maxlength="4000" placeholder="{esc(_t(words))}"></textarea>', 1)
    if not cards:
        return form
    why = _xp.explain(f"brief-pick-{key}", _t("home.pick_hint"), _t("home.send"))
    form = form.replace('<span class="ahint" hidden>', why + '<span class="ahint" hidden>', 1)
    head, mark, tail = form.partition('<label class="anote"')
    if not mark or not tail.endswith("</form>"):
        return form
    picked = esc(_t("js.brief.picked", what=_t("js.brief.none")))
    return f'{head}<div class="bfoot"><p class="bpicked" aria-live="polite">{picked}</p>{mark}{tail[:-len("</form>")]}</div></form>'


def _past(board: Any, r: dict[str, Any]) -> str:
    """The last answers on the item, newest last, folded: when, who (on a board of several members), the pick and the words."""
    recs = [a for a in _r.answers_of(r) if a.get("kind") in ("decision", "step-reply")][-_PAST:]
    if not recs:
        return ""
    several = len(_members.members()) > 1
    lines = []
    for a in recs:
        try:
            when = board.when(float(a["ts"]))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            when = ""
        head = " · ".join(x for x in (when, _members.recorded_by(a) if several else "") if x)
        pick = _ol.pick_words(str(a.get("choice") or ""), str(a.get("letter") or ""))
        words = " — ".join(x for x in (pick, str(a.get("text") or "").strip()) if x)
        lines.append("<li>" + " · ".join(x for x in (esc(head), board.linkify(words, r["gid"])) if x) + "</li>")
    return f'<section class="bsec"><details class="bmore"><summary>{esc(_t("brief.past", n=len(recs)))}</summary><ul class="bpast">{"".join(lines)}</ul></details></section>'


def article(board: Any, gid: str, answer: dict[str, Any] | None, heading: str = "h2") -> tuple[str, str]:
    """(the brief of one item, its subject as plain text). `answer` is what the item's page takes ({"action", "token", "sent", "member"}; None for a viewer who is not signed in).
    KeyError for an unknown id."""
    p: dict[str, Any] = {}
    board.item_html(gid, answer=answer, parts=p)
    r = p["r"]
    m = r["metadata"]
    title = board.bare(r["subject"])
    key = _gh.href_id(r["gid"])
    cards = " data-cards " in p["box"]
    outcome = str(m.get("outcome_text") or "").strip() if r.get("status") == "completed" else ""
    who = board.row_line(r)
    head = (f'<header class="bhead">' + (f'<p class="bwho">{who}</p>' if who else "")
            + f'<{heading} class="btitle" id="brief-title"><span class="ir-id">{esc(_r.rid(r))}</span> {board.mentions(esc(title), r["gid"])}</{heading}>'
            + f'<p class="bstate">{p["state"]}</p></header>')
    top = _ask(board, r, p, cards) + _step(p["step"], key) + p["draft"]
    middle = ((_section("boutcome", _t("item.outcome"), f'<div class="desc md">{board.md_html(outcome, r["gid"])}</div>') if outcome else "")
              + p["wait"] + _background(board, r) + _box(p["box"], key) + _past(board, r))
    code = str((answer or {}).get("sent") or "")
    known = board.sent_keys().get(code)
    sent = f'<div class="bsent" data-ok="{1 if known[0] == "ok" else 0}">{p["sent"]}</div>' if known else ""
    attrs = (f' data-key="{esc(key)}" data-fp="{_r._blk_fp(head + top + middle)}"'
             f' data-keep="{" ".join(_frame._QUIET)}"')      # the notices that mean nothing was written, so the box stays as it is
    return f'<article class="bitem"{attrs}>{head}<div class="bbody">{sent}{top}{middle}</div></article>', title


def page(board: Any, gid: str, answer: dict[str, Any] | None) -> str:
    """The brief as a page of its own, under the board's header and beside the summary panel, with the way home and to the detail view. KeyError for an unknown id."""
    drawn, title = article(board, gid, answer, heading="h1")
    r = board.item(gid)
    font = str(_cfg.get("instance", "font_css") or "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow">'
            f'<title>{esc(_r.rid(r))} · {esc(title)}</title><link rel="icon" href="{_r.icon_href("favicon.svg")}" type="image/svg+xml">'
            + (f'<link rel="stylesheet" href="{esc(font)}">' if font else "")
            + _r._THEME_HEAD + _r._FOLD_HEAD + _r._APP_HEAD + f'<style>{board._css()}</style></head>'
            + _r._PANEL_BODY + '<div id="layout"><main class="briefpage" id="top">' + board.page_header()
            + f'<nav class="bpbar"><a class="b" href="{under("/")}">{esc(_t("brief.home"))}</a><a class="b" href="{esc(_r.item_href(r))}">{esc(_t("brief.detail"))}</a></nav>'
            + f'<div id="brief-page">{drawn}</div></main>' + board.panel_tail() + _r._FAB_PAIR + _r._THEME_JS + _r._RELOAD_JS + _r._TOTOP_JS + _r._COPY_JS + _r._BFCACHE_JS
            + _r._CARDS_JS + f'<script>{_r._ABOX_JS}</script>' + _r._SENDKEY_JS + f'<script>{_assets.JS}</script></body></html>')
