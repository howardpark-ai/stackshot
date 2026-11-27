"""brief.py — the item brief: a short view of one item for deciding, beside the item's own page (the detail view).

article() is the one drawing, from the item's own fields, and it is lean: the item's id and title as the link to the detail view; what the item asks in one line, with the
recommendation under it, or the step; a draft to paste; and the answer box with its choices. No section has a heading. A "?" beside the question or the step holds the rest
of what bears on it: the stakes, the date it is wanted by and the first lines of the description. An item that asks this viewer nothing shows its state line instead.
Everything else (project and people, outcome, wait, past answers, the whole description) is on the detail view alone. page() is that article as a page of its own
(GET /items/<key>/brief); the home page's panel reads the same page and takes the article out (ui/brief_assets.py). Nothing here writes, and nothing here decides who may
answer: the answer box is the item page's own (Board.item_html hands it over), posting to the one answer route.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.web.i18n import t as _t
from stackshot.web.ui import answer_frame as _frame, brief_assets as _assets, explain as _xp, render as _r

esc = _r.esc
_LEAD = 5                  # the pieces of the description the "?" holds; "…" says there are more
_TOP = re.compile(r"(?:[-*+]|\d{1,9}[.)])\s|#{1,6}\s")      # a line at the margin that starts a piece of its own: a bullet, a numbered line, a heading
_FENCE = re.compile(r"\s*(`{3,}|~{3,})(.*)$")      # a fence line: its marks and what follows them (CommonMark: nothing follows a closing fence, and no backtick follows a backtick fence)


def pieces(text: str) -> list[str]:
    """A description cut where it can be: one piece per bullet or numbered line at the margin (with what is indented under it), per heading and per paragraph; a fenced block is never cut."""
    out: list[list[str]] = []
    fence = ""
    blank = False
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence:
            out[-1].append(line)
            if m and m.group(1).startswith(fence) and not m.group(2).strip():
                fence = ""
            continue
        if not line.strip():
            blank = True
            continue
        if m and m.group(1)[0] == "`" and "`" in m.group(2):      # ```a word``` on a line of its own is text, and opens nothing
            m = None
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


def _plain(markup: str) -> str:
    """Drawn item text as the plain lines a "?" holds: the words a reader sees, a bullet kept as a bullet, no button's label."""
    text = re.sub(r"<button\b.*?</button>", "", markup, flags=re.S)
    text = re.sub(r"<li\b[^>]*>", "\n• ", text)
    text = re.sub(r"</(?:p|li|h[1-6]|pre|tr|div|ul|ol|blockquote)>|<br\s*/?>", "\n", text)
    text = _html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(line.strip() for line in text.split("\n") if line.strip() not in ("", "•"))


def _more(board: Any, r: dict[str, Any], pa: dict[str, str] | None, key: str) -> str:
    """The "?" that holds what bears on the item and is not drawn: the ask's stakes and date (`pa`, None when the item asks this viewer nothing in the set form), then the
    first pieces of the description. A date line that says there is none is left out; "" when there is nothing to hold."""
    gid = r["gid"]
    lines = []
    for field, label in (("stakes", "item.ask.stakes"), ("by", "item.ask.by")):
        value = (pa or {}).get(field, "").strip()
        if value and not (field == "by" and value.rstrip(".").lower() == "no date"):
            lines.append(f"{_t(label)}: {_plain(board.linkify(value, gid))}")
    desc = (r.get("description") or "").strip()
    if desc and desc != r["subject"]:
        cut = pieces(desc)
        lines.append(_plain(board.md_html(_join(cut[:_LEAD]), gid)) + ("\n…" if len(cut) > _LEAD else ""))
    return _xp.explain(f"brief-more-{key}", "\n\n".join(lines), _t("item.details")) if lines else ""


def _ask(board: Any, r: dict[str, Any], p: dict[str, Any], cards: bool, more: str) -> str:
    """What the item asks, in one line with its "?" (`more`), and the recommendation with its reason on a line under it. Where no cards are drawn the options are listed, as on
    the item's page. Called when the item asks this viewer something, which is the page's own rule (p["ask"])."""
    gid = r["gid"]
    pa, raw = p["pa"], _r.open_ask(r)
    words = pa["decide"] if pa else re.sub(r"^Decide:\s*", "", raw)      # an ask in no set form is its whole line, without the label
    if not pa and p["ol"]:      # …cut as the home row cuts it where its options are drawn below, so they are not said twice
        words = _r.decide_words(raw)
    question = board.linkify(words, gid) + _r.mockup_link(r, raw) if raw else ""
    line = f'<p class="bq"><span>{question}</span>{more}</p>' if question or more else ""      # the words in a box of their own, so the "?" stands beside them and opens no gap between their lines
    why = pa["recommend"].strip() if pa else ""
    reco = f'<p class="breco"><b>{esc(_t("item.ask.recommend"))}</b> {board.linkify(why, gid)}</p>' if why else ""
    listed = "" if cards else p["ol"]
    return f'<div class="iask">{line}{reco}{listed}</div>'


def _step(step: str, key: str, more: str) -> str:
    """The page's step block and form without the block's heading, with `more` beside the step and the line about Send note behind a "?" instead of a hover title."""
    step = step.replace(f'<b>{_t("item.your_step")}</b>', "", 1)
    if more:      # the block ends where its form starts, or where the step ends for a viewer with no box
        block, cut, form = step.partition('<form class="ianswer" data-step')
        step = block.removesuffix("</div>") + more + "</div>" + cut + form
    head, mark, tail = step.partition(" data-needs-text>")
    if not mark:
        return step
    hint = _t("home.step_send_note_hint")
    head = head.replace(f' title="{esc(hint)}" data-hint="{esc(hint)}"', "")
    label, close, rest = tail.partition("</button>")
    return head + mark + label + close + _xp.explain(f"brief-note-{key}", hint, _t("home.step_send_note")) + rest


def _box(form: str, key: str) -> str:
    """The page's answer box laid out for the brief: no heading, the box's words as its placeholder, and under option cards a foot (the note, Send) that stays in view."""
    if not form:
        return ""
    form = re.sub(r"\A(<form\b[^>]*>)<b>[^<]*</b>", r"\1", form)
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
    return f'{head}<div class="bfoot">{mark}{tail[:-len("</form>")]}</div></form>'


def article(board: Any, gid: str, answer: dict[str, Any] | None, heading: str = "h2") -> tuple[str, str]:
    """(the brief of one item, its subject as plain text). `answer` is what the item's page takes ({"action", "token", "sent", "member"}; None for a viewer who is not signed in).
    KeyError for an unknown id."""
    p: dict[str, Any] = {}
    board.item_html(gid, answer=answer, parts=p)
    r = p["r"]
    title = board.bare(r["subject"])
    key = _gh.href_id(r["gid"])
    cards = " data-cards " in p["box"]
    whole = "" if p["ask"] or p["step"] else " bwhole"      # with no question and no step, the title is what says what the item is: it wraps instead of being cut at one line
    head = (f'<header class="bhead{whole}"><{heading} class="btitle" id="brief-title"><a href="{esc(_r.item_href(r))}"><span class="ir-id">{esc(_r.rid(r))}</span> {esc(title)}</a>'
            f'</{heading}></header>')      # the item's link, drawn once: nothing else leads to the detail view
    more = _more(board, r, p["pa"] if p["ask"] else None, key)
    if p["ask"]:
        top = _ask(board, r, p, cards, more)
    elif p["step"]:
        top = _step(p["step"], key, more)
    else:
        top = f'<p class="bstate">{p["state"]}{more}</p>'
    top += p["draft"]
    middle = _box(p["box"], key)
    code = str((answer or {}).get("sent") or "")
    codes = board.sent_keys()
    known = codes.get(code)
    recorded = " ".join(c for c, v in codes.items() if v[0] == "ok" or c == "askedback")      # askedback warns, and the answer and the note are kept on the item
    sent = f'<div class="bsent" data-ok="{1 if known[0] == "ok" else 0}">{p["sent"]}</div>' if known else ""
    attrs = (f' data-key="{esc(key)}" data-fp="{_r._blk_fp(head + top + middle)}"'
             f' data-keep="{" ".join(_frame._QUIET)}"'      # the notices that mean nothing was written, so the box stays as it is
             f' data-recorded="{recorded}"')      # the notices that mean something was written, so the draft ends
    return f'<article class="bitem"{attrs}>{head}<div class="bbody">{sent}{top}{middle}</div></article>', title


def page(board: Any, gid: str, answer: dict[str, Any] | None) -> str:
    """The brief as a page of its own, under the board's header (whose title is the way home) and beside the summary panel. KeyError for an unknown id."""
    drawn, title = article(board, gid, answer, heading="h1")
    r = board.item(gid)
    font = str(_cfg.get("instance", "font_css") or "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow">'
            f'<title>{esc(_r.rid(r))} · {esc(title)}</title><link rel="icon" href="{_r.icon_href("favicon.svg")}" type="image/svg+xml">'
            + (f'<link rel="stylesheet" href="{esc(font)}">' if font else "")
            + _r._THEME_HEAD + _r._FOLD_HEAD + _r._APP_HEAD + f'<style>{board._css()}</style></head>'
            + _r._PANEL_BODY + '<div id="layout"><main class="briefpage" id="top">' + board.page_header()
            + f'<div id="brief-page">{drawn}</div></main>' + board.panel_tail() + _r._FAB_PAIR + _r._THEME_JS + _r._RELOAD_JS + _r._TOTOP_JS + _r._COPY_JS + _r._BFCACHE_JS
            + _r._CARDS_JS + f'<script>{_r._ABOX_JS}</script>' + _r._SENDKEY_JS + f'<script>{_assets.JS}</script></body></html>')
