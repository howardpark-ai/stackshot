#!/usr/bin/env python3
"""tools/goal_pass.py — the one-time goal pass: does each OPEN item's subject and first bullet name an outcome wanted?

The goal-unclear audit check (audit_run.py) judges only items that carry a `Goal:` first bullet and whose subject or Goal sentence is new. The items filed before the form have no such bullet; this
report asks the same judge, with the same rubric, model and lane (`[audit] model`, `[audit] lane`), about EVERY open item once, so the owner can see how many titles describe a symptom.

REPORT ONLY: it files nothing, edits nothing, sends no message and changes no item or record (the audit's records are not touched, no stamp is kept). One model call per item, one at a time, under the audit's
`[audit] max_minutes` limit; a call that fails leaves its item "not judged". Stdlib plus the repo's modules, Python 3.11+.

  tools/goal_pass.py                 judge every open item; print one block per item and the counts, and write the same text to <paths.state>/audit/goal-pass-<date>-<HHMMSS>.txt
  tools/goal_pass.py --dry-run       list the items it would judge (id, subject, first bullet); no model call, no file
  tools/goal_pass.py --max-calls N   judge the first N open items (lowest id first) only; 0 (the default) is all of them
  tools/goal_pass.py --out FILE      write the report to FILE instead
  tools/goal_pass.py --store DIR     read the items from DIR (a copy of the store) instead of [paths] store

A block:   <id> · unclear · <the judge's one-line reason>      (verdict: unclear / clear / not judged)
             subject: <the item's subject>
             first bullet: <the first `- ` bullet, or "(none)">
Exit 0."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import audit_run as AR  # noqa: E402
import bullet_text as _bt  # noqa: E402
import config as _cfg  # noqa: E402

CHECK = "goal-unclear"


def candidates(items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One suspect per open item, lowest id first, in the shape `audit_run.judge` takes. The evidence is the subject and the Goal sentence, or, for an item with no Goal bullet, its first bullet."""
    import board_report as _br  # noqa: PLC0415
    import next_report as _nr  # noqa: PLC0415
    out = []
    for gid in sorted((g for g, it in items.items() if it.get("status") == "open"), key=_nr.num):
        it = items[gid]
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        subject, desc = str(it.get("subject") or ""), str(it.get("description") or "")
        goal, first = _bt.goal_of(desc), _bt.first_bullet(desc)
        if goal:
            line = f"the subject and the Goal bullet, judged once for the pass: subject: {AR._clip(subject, 120)} | Goal: {AR._clip(goal, 200)}"
        else:
            line = f"the item has no Goal bullet (filed before the form): subject: {AR._clip(subject, 120)} | first bullet: {AR._clip(first, 200) if first else '(none)'}"
        out.append({"id": _nr.shown(gid), "gid": gid, "project": str(meta.get("project") or ""), "checks": [CHECK], "evidence": {CHECK: line}, "write": _br._last_write(it), "priority": 3, "sig": "", "context": [],
                    "first": first or ""})
    return out


def block(sus: dict[str, Any], item: dict[str, Any], entry: dict[str, Any] | None) -> str:
    verdict = "not judged" if entry is None else ("unclear" if entry.get("verdict") == "yes" else "clear")
    reason = "" if entry is None else str(entry.get("reason") or "")
    return "\n".join([f"{sus['id']} · {verdict}" + (f" · {reason}" if reason else ""),
                      f"  subject: {' '.join(str(item.get('subject') or '').split())}",
                      f"  first bullet: {' '.join(sus['first'].split()) if sus['first'] else '(none)'}"])


def run(items: dict[str, dict[str, Any]], *, env: AR.Env | None = None, rubric: str | None = None, max_calls: int = 0, dry: bool = False, now: float | None = None,
        out: Callable[[str], None] | None = None) -> dict[str, Any]:
    """The pass on `items` ({gid: item}); `out(line)` gets each report line. → {"text", "counts": {"open", "judged", "unclear", "clear", "not_judged"}, "calls"}. Nothing is written or sent here."""
    say = out or (lambda s: print(s, flush=True))
    now = time.time() if now is None else now
    env = env or AR.Env()
    picked = candidates(items)
    if max_calls > 0:
        picked = picked[:max_calls]
    lines: list[str] = []

    def emit(s: str) -> None:
        lines.append(s)
        say(s)
    if dry:
        emit(f"goal pass dry run: {len(picked)} open item(s) would be judged, one call each; no call made, nothing written")
        for s in picked:
            emit(f"{s['id']} · {' '.join(str(items[s['gid']].get('subject') or '').split())} · first bullet: {' '.join(s['first'].split()) if s['first'] else '(none)'}")
        return {"text": "\n".join(lines), "counts": {"open": len(picked), "judged": 0, "unclear": 0, "clear": 0, "not_judged": 0}, "calls": {"made": 0}}
    rubric = rubric if rubric is not None else AR.RUBRIC.read_text(encoding="utf-8").replace("{owner}", _cfg.owner())
    _found, entries, calls = AR.judge(items, picked, now, env, rubric, now)
    n_yes = n_no = 0
    emit(f"goal pass: {len(picked)} open item(s), one call each ({calls['made']} made, {calls['failed']} failed) · report only: nothing filed, no message sent")
    for s in picked:
        e = entries.get(s["id"])
        n_yes += bool(e and e.get("verdict") == "yes")
        n_no += bool(e and e.get("verdict") != "yes")
        emit(block(s, items[s["gid"]], e))
    n_none = len(picked) - n_yes - n_no
    emit(f"counts: {n_yes} unclear · {n_no} clear · {n_none} not judged" + (" · " + "; ".join(calls["notes"]) if calls["notes"] else ""))
    return {"text": "\n".join(lines), "counts": {"open": len(picked), "judged": n_yes + n_no, "unclear": n_yes, "clear": n_no, "not_judged": n_none}, "calls": calls}


def main(argv: list[str], *, env: AR.Env | None = None, items: dict[str, dict[str, Any]] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="goal_pass.py", description="report-only: does each open item's subject and first bullet name an outcome wanted?")
    ap.add_argument("--dry-run", action="store_true", help="list the items it would judge; no model call, no file")
    ap.add_argument("--max-calls", type=int, default=0, help="judge the first N open items only (0 = all)")
    ap.add_argument("--out", default="", help="write the report here instead of <paths.state>/audit/goal-pass-<stamp>.txt")
    ap.add_argument("--store", default="", help="read the items from this directory instead of [paths] store")
    a = ap.parse_args(argv)
    import next_report as _nr  # noqa: PLC0415
    if items is None:
        items = _nr.load_all(Path(a.store).expanduser() if a.store else None)
    now = time.time()
    res = run(items, env=env, max_calls=max(a.max_calls, 0), dry=a.dry_run, now=now)
    if not a.dry_run:
        import audit as _audit  # noqa: PLC0415
        path = Path(a.out).expanduser() if a.out else _audit.state_dir() / f"goal-pass-{AR._stamp_of(now)}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(res["text"] + "\n", encoding="utf-8")
        print(f"report written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
