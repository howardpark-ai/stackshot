#!/usr/bin/env python3
"""tools/next_report.py — the daily audit's check of the Next rules (the Next design: "Lists any item breaking N1 to N7 as a finding. Closed items are left as they are").

Reads the open items in the store and lists those whose checklist breaks a rule that stored data can show. Read only: it changes no item, refuses nothing and needs no server. Stdlib plus the repo's modules, Python 3.11+.

  N1  an open step opens with no actor (`<session>:`, `<owner>:` or the outside party's name), or with a label such as `Status:`
  N2  the item waits on the owner (needs decision, your-call, your-step) and no open step of his says what he is to do
  N3  an open step that grows from a step which left the list with no mark (no `by`, no `at`: the shape steps.view gives a line dropped from next unmarked): the old words plus new ones, the rewrite
      that carries progress. A step marked dropped, with its writer and time, and replaced by a longer one is allowed (note d) and is no finding
  N4  a step of his marked done by someone other than him, ticked since part 1 went live (PART1_LIVE; earlier ticks are history, the fill-in leaves them as they are), unless the item carries his own
      recorded words at or before the mark: a checked Acked-by or Suggested-by said entry, or an answer of his on the board (metadata.answers, with a choice or text); or a checked said entry
      of kind acted dated at or before the mark and no more than ACTED_WINDOW before it (tag Done-by: a message he sent while a session worked, a queued_command attachment of human origin,
      said.verify_acted), which proves the steps of his ticked within that window after its date. An acted entry counts here only, never as his words
  N5  an open step of his on an item that does not wait on him (an alive item with a session or an outside party as the mover)
  N6  an open item, held ones too, with no open step (a parked item needs the step its wake leads to); not counted again when the item waits on the owner, which N2 says
  N7  an open step of a session that reads as a report (a commit hash, a test count, a past-tense result, an "at work since" stamp)
  (N8, a close settles the steps, is kept by the server's close and is not read from stored data.)

  tools/next_report.py                 the findings, one line each (id, project, mover, rule, what is wrong), then the counts per rule
  tools/next_report.py --line          the one line the brief carries ("Next rules: 5 item(s) break a rule · N1 2 · N6 3")
  tools/next_report.py --json          {"open", "closed", "items", "rules": {rule: count}, "findings": [{id, project, mover, category, rule, detail}]}
  tools/next_report.py --store DIR     read the items from DIR (a copy of the store) instead of [paths] store

The audit calls it for the full list. Exit 0."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import config as _cfg  # noqa: E402
import waiting as _wt  # noqa: E402
import owner_steps as _hs  # noqa: E402
import model as _model  # noqa: E402
import model_guards as _mg  # noqa: E402
import next_rules as _nr  # noqa: E402
import said as _said  # noqa: E402
import steps as _steps  # noqa: E402

CATEGORY = "next rules"
PART1_LIVE = 1700000000.0       # (epoch): part 1 of the next rules went live; N4 reports only his steps a session ticked from then on
RULES = ("N1", "N2", "N3", "N4", "N5", "N6", "N7")


def load_all(store: Path | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in sorted((store or _cfg.path("paths", "store")).glob("*/*.json")):
        gid = p.parent.name + p.stem
        if not re.fullmatch(r"[a-z]\d+", gid):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out[gid] = d
    return out


def shown(gid: str) -> str:
    return f"board#{gid[1:]}" if re.fullmatch(r"[a-z]\d+", gid) else gid


def num(gid: str) -> int:
    return int(re.sub(r"\D", "", gid) or 0)


def _clip(text: Any, n: int = 70) -> str:
    t = " ".join(_steps.first_line(text).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


ACTED_WINDOW = 24 * 3600.0      # seconds an acted entry clears his ticked steps after its own date: the pasted result and the tick that follows it belong to one piece of work, so a tick a day or more later is not covered by it
OWNER_SAID_TAGS = ("Acked-by", "Suggested-by")      # the said tags that record his answer or his request; Reported-by records a fault he saw, not an answer


def owner_words_by(meta: dict[str, Any], at: float) -> str:
    """What shows the owner's own recorded words on the item at or before `at` (epoch seconds), "" when none does: "an Acked-by said entry" (or Suggested-by) checked against a
    transcript and dated at or before `at`, else "a board answer" (metadata.answers, a decision or a comment with a choice or text) dated at or before `at`. A record dated after `at`,
    or an unchecked said entry (a transcript the box could not read), is none. Uses said.entries_of and render.answers_of, the readers the server and the pages use."""
    for e in _said.entries_of(meta):
        if e["kind"] == _said.WORDS and e["tag"] in OWNER_SAID_TAGS and e["checked"] and 0 < e["ts"] <= at:
            return f"a {e['tag']} said entry"
    import render as _render  # noqa: PLC0415  (heavy; only an N4 candidate needs it)
    for a in _render.answers_of({"metadata": meta}):
        if (a.get("text") or a.get("choice")) and 0 < _float(a.get("ts")) <= at:
            return "a board answer"
    return ""


def owner_acted_by(meta: dict[str, Any], at: float) -> str:
    """What proves the owner's ticked step on the item at `at` (epoch seconds, the mark of the tick), "" when nothing does: a checked said entry of kind acted (tag Done-by: a queued_command
    attachment entry of human origin, checked against a transcript by said.verify_acted) dated at or before `at` and no more than ACTED_WINDOW before it; it is not tied to one step, so it
    clears every step of his ticked inside that window. Unchecked, dated after `at`, or dated longer before it, is none. Read by N4 only: it is never his words (owner_words_by does not read it)
    and never his decision."""
    for e in _said.entries_of(meta):
        if e["kind"] == _said.ACTED and e["checked"] and 0 < e["ts"] <= at <= e["ts"] + ACTED_WINDOW:
            return f"a {_said.ACTED_TAG} said entry (kind {_said.ACTED})"
    return ""


def _mover(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any] | None = None) -> str:
    try:
        mv = _model.derive(item, None, after_open).mover
    except Exception:  # noqa: BLE001
        mv = ""
    return mv or _model.clean((item.get("metadata") or {}).get("mover"))


def check_item(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any] | None = None) -> list[tuple[str, str]]:
    """[(rule, what is wrong)] for one OPEN item, in rule order; [] for a closed item or one that breaks none. `after_open(item)` says which of the items it waits after are still open, as the model reads it."""
    if item.get("status") != "open":
        return []
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    cl = _steps.view(meta, keeper=str(meta.get("owner") or ""))
    opens = [s for s in cl if s["status"] == _steps.OPEN]
    out: list[tuple[str, str]] = []
    for s in opens:                                                                       # N1
        if _steps.is_bare(s["text"]):
            continue                                                                      # a sub-step of the one above
        nm = _steps.opener(s["text"])
        if not nm or _mg.not_actor(nm):
            out.append(("N1", f"the open step names no one: {_clip(s['text'])}"))
    his_open = [s for s in opens if _hs.is_named(s["text"])]
    on_him = _model.stood_his(item, after_open)
    if on_him and not his_open:                                                           # N2
        out.append(("N2", f"the item waits on {_cfg.owner()} but no open step of his says what he is to do"))
    for d in (s for s in cl if s["status"] == _steps.DROPPED and not s.get("by") and not s.get("at")):      # N3: a marked drop (by, at) may be replaced by a longer step
        g = next((o for o in opens if _nr.grows(_steps.first_line(d["text"]), _steps.first_line(o["text"]))), None)
        if g is not None:
            out.append(("N3", f"an open step is a step left out of next unmarked, with words added: {_clip(d['text'], 40)} → {_clip(g['text'], 40)}"))
    for s in cl:                                                                          # N4
        if s["status"] == _steps.DONE and _hs.is_named(s["text"]) and s.get("by") and not _model.is_owner(s["by"]) and _float(s.get("at")) >= PART1_LIVE \
                and not owner_words_by(meta, _float(s.get("at"))) and not owner_acted_by(meta, _float(s.get("at"))):   # his own recorded words at or before the mark are his answer, however the step came to be ticked; a checked acted entry dated at or before the mark, within ACTED_WINDOW of it, proves his steps ticked in that window
            out.append(("N4", f"his step was marked done by {s['by']}: {_clip(s['text'])}"))
    if his_open and not on_him:                                                           # N5
        try:
            alive = _model.derive(item, None, after_open).state == _model.ALIVE
        except Exception:  # noqa: BLE001
            alive = False
        if alive:
            out.append(("N5", f"an open step of his, and the item does not wait on him: {_clip(his_open[0]['text'])}"))
    if not opens and not on_him:                                                          # N6 (an item on him is N2's)
        out.append(("N6", "a parked item has no step for its wake" if meta.get("hold") else "the item is open and has no open step"))
    for s in opens:                                                                       # N7
        if _hs.is_named(s["text"]):
            continue                                                                      # his step is the server's wording of his ask
        sig = _nr.report_signals(_nr.link_free(_steps.first_line(s["text"])))
        if sig:
            out.append(("N7", f"the open step reads as a report ({', '.join(sig)}): {_clip(s['text'])}"))
    order = {r: i for i, r in enumerate(RULES)}
    return sorted(out, key=lambda x: order.get(x[0], 9))


def scan(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """{"open", "closed", "items" (with a finding), "rules": {rule: count of items}, "findings": [{id, project, mover, category, rule, detail}]}. Reads only."""
    findings: list[dict[str, str]] = []

    def after_open(it: dict[str, Any]) -> list[str]:
        return [g for g in _wt.after_of(it.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
    rules = {r: 0 for r in RULES}
    n_open = n_closed = n_items = 0
    for gid in sorted(items, key=num):
        it = items[gid]
        if it.get("status") != "open":
            n_closed += 1
            continue
        n_open += 1
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        hits = check_item(it, after_open)
        if hits:
            n_items += 1
        seen: set[str] = set()
        for rule, detail in hits:
            if rule not in seen:
                rules[rule] += 1
                seen.add(rule)
            findings.append({"id": shown(gid), "project": str(meta.get("project") or ""), "mover": _mover(it, after_open), "category": CATEGORY, "rule": rule, "detail": detail})
    return {"open": n_open, "closed": n_closed, "items": n_items, "rules": rules, "findings": findings}


def line(rep: dict[str, Any]) -> str:
    if not rep["items"]:
        return "Next rules: no open item breaks one"
    per = " · ".join(f"{r} {n}" for r, n in rep["rules"].items() if n)
    return f"Next rules: {rep['items']} item(s) break a rule · {per}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="The open items that break the Next rules N1 to N7 (read only).")
    ap.add_argument("--line", action="store_true", help="the one line of counts the brief carries")
    ap.add_argument("--json", action="store_true", help="the report as JSON")
    ap.add_argument("--store", help="read the items from this folder (a copy of the store) instead of [paths] store")
    a = ap.parse_args(argv)
    store = Path(a.store).expanduser() if a.store else None
    if store is not None and not store.is_dir():
        print(f"--store {store}: not a folder", file=sys.stderr)
        return 2
    rep = scan(load_all(store))
    if a.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    elif a.line:
        print(line(rep))
    else:
        for f in rep["findings"]:
            print(f"{f['id']} | {f['project'] or '-'} | mover {f['mover'] or '-'} | {f['rule']} | {f['detail']}")
        print()
        print(f"{line(rep)} (of {rep['open']} open; {rep['closed']} closed left as they are; read only)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
