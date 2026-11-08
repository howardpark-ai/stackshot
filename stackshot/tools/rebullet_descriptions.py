"""tools/rebullet_descriptions.py — re-bullet the descriptions of the open items (a description is never one thick text block:
it is broken down into short bullet lists, each bullet concise yet informative). Stdlib only, Python 3.11+.

A thin model call (router.run_call: `claude -p` on the signed-in lane, ANTHROPIC_API_KEY unset, a Haiku-class model) turns a thick description into short `- ` bullets. CODE then
decides whether the rewrite may stand (rebullet.py): every URL, number, date, code span and quoted span of the old text must be in the new one, every line a bullet, at most
[description] max_lines lines, each at most line_max characters. A rewrite that fails is refused and the item is left as it is. Closed items are never touched.

Which open items are touched (the candidates): with [description] require_bullets = true (the default) an open item is a candidate when the server's
own write gate, bullet_text.judge(description, max_lines, line_max), refuses its description: a line that is not a `- ` bullet (reason "marker"), a bullet over line_max characters
as it reads (reason "long") or more than max_lines lines (reason "lines"), so the next edit of an item the pass skipped would be refused. With require_bullets = false the older test
stands: a "thick block" (model_guards.description_problem: a paragraph over 300 characters, or a text over 400 with no bullet; reason "thick"). The dry run names the
test it used and counts the candidates per reason. /client/rebullet has no candidate check of its own; it judges each rewrite with rebullet.verdict, which uses the same judge.

  tools/rebullet_descriptions.py                        dry run (the default): the open items it would touch and how many, the longest first; no model call, nothing written
  tools/rebullet_descriptions.py --sample N --store DIR the first N of those (the longest) run through the model, before and after as markdown on stdout (or --out FILE); DIR is
                                                        a COPY of the store (<letter>/<n>.json); nothing is written, to the copy or anywhere
  --sample ... --out F.md                               also saves every rewrite (item, old text, new text, status, verdict) as F.json (or --json FILE) beside the markdown
  tools/rebullet_descriptions.py --apply --from F.json  writes exactly the rewrites marked ok in that file, with no model call: the texts someone read. Each is checked again against
                                                        the item as it is now (open, description still the old text, today's checks); an item not in the file is never written
  (--only IDS or --except IDS, with any of the three: board#N,board#M; narrows the candidates to those ids, or to all but them)
  --apply is the real pass and always takes --from: for each saved rewrite ONE write through the live server (POST /client/rebullet with this machine's token): a normal update by
  the author `rebullet`, so the old text stays as the earlier revision in History, and the mirror and the search follow as for any write. The server checks again (the item open,
  its description still the text the rewrite was made from, nothing lost); the write keeps the state clock and the confirm (the `updated` time moves) and tells no one

--model sets the call's model (default haiku). --sender sets the name the record keeps ("<sender> via a script on <machine>"; default rebullet). The config is the usual one
($STACKSHOT_CONFIG or ~/.config/stackshot/stackshot.toml). Exit 0 · 1 when --apply could not write something."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parents[2]
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.model import bullet_text as _bt  # noqa: E402
from stackshot.model import model_guards as _mg  # noqa: E402
from stackshot.model import rebullet as _rb  # noqa: E402


def load_all(store: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(store.glob("*/*.json")):
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


def prose_len(text: str) -> int:
    return sum(len(u) for u in _mg.description_units(text)[0])


def parse_ids(text: str) -> list[str]:
    """The ids of a `--only` / `--except` list: board#N, #7, g7 or 7, separated by commas or spaces. A token that is none of these raises ValueError."""
    out = []
    for tok in re.split(r"[\s,]+", str(text or "").strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(?:board)?#?(\d+)|g(\d+)", tok, re.I)
        if not m:
            raise ValueError(tok)
        out.append("g" + (m.group(1) or m.group(2)))
    return out


def load_saved(path: Path) -> dict[str, dict[str, Any]]:
    """The rewrites saved by `--sample` as JSON ({"rewrites": [{"item", "gid", "old", "new", "status", ...}]}), the ones marked ok, by gid. OSError for an unreadable file, ValueError for a
    file that is not that shape or names an item twice."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("rewrites") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError('not a rewrites file (no "rewrites" list)')
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict) or not re.fullmatch(r"[a-z]\d+", str(r.get("gid") or "")) or not isinstance(r.get("old"), str) or not isinstance(r.get("new"), str):
            raise ValueError(f"a rewrite lacks gid, old or new: {str(r)[:80]}")
        if r["gid"] in out:
            raise ValueError(f"{r['gid']} appears twice")
        if r.get("status") == "ok" and r["new"].strip():
            out[r["gid"]] = r
    if not out:
        raise ValueError("no rewrite marked ok")
    return out


def reason(description: Any, *, strict: bool = True, max_lines: int = 8, line_max: int = 120) -> str:
    """Why a description needs the pass, or "" when it does not. strict (require_bullets = true): the server's write gate, bullet_text.judge, refuses it: "marker" (a line is not a
    `- ` bullet), "long" (a bullet reads over line_max characters) or "lines" (more than max_lines). Not strict (require_bullets = false): the older test, a thick block
    (model_guards.description_problem), reason "thick"."""
    if strict:
        bad = _bt.judge(str(description or ""), max_lines, line_max)
        return bad[0] if bad else ""
    return "thick" if _mg.description_problem(description) else ""


def candidates(items: dict[str, dict[str, Any]], *, strict: bool = True, max_lines: int = 8, line_max: int = 120) -> list[str]:
    """The ids of the open items the pass would rewrite, the longest first: with strict (require_bullets = true) those whose description bullet_text.judge refuses with max_lines
    and line_max, else those the older thick-block test (model_guards.description_problem) calls thick. A closed item is never one, and an item that already passes is skipped."""
    ids = [g for g, it in items.items() if it.get("status") == "open" and reason(it.get("description"), strict=strict, max_lines=max_lines, line_max=line_max)]
    return sorted(ids, key=lambda g: (-prose_len(str(items[g].get("description") or "")), int(g[1:])))


def test_name(strict: bool, max_lines: int, line_max: int) -> str:
    """The candidate test in words, for the dry run's summary line."""
    if strict:
        return f"bullet_text.judge (require_bullets = true; max_lines {max_lines}, line_max {line_max})"
    return "thick block, model_guards.description_problem (require_bullets = false; a paragraph over 300 characters, or over 400 with no bullet)"


def reason_counts(items: dict[str, dict[str, Any]], ids: list[str], *, strict: bool, max_lines: int, line_max: int) -> str:
    """The candidates counted per reason, every reason of the test in use named even at zero: "marker 3, long 1, lines 0" (or "thick 3")."""
    kinds = ("marker", "long", "lines") if strict else ("thick",)
    n = Counter(reason(items[g].get("description"), strict=strict, max_lines=max_lines, line_max=line_max) for g in ids)
    return ", ".join(f"{k} {n.get(k, 0)}" for k in kinds)


def render_sample(rows: list[dict[str, Any]], total: int, open_n: int, model: str, store: str, today: str, max_lines: int = 8, test: str = "") -> str:
    """The sample as markdown: per item its subject, the old description, and the new one (or why the checks refused it)."""
    ok = sum(1 for r in rows if r["status"] == "ok")
    out = [f"# Re-bullet sample, {today}", "",
           f"- Model: `{model}` through `claude -p` on the signed-in lane; the store is a copy (`{store}`), nothing was written.",
           f"- {open_n} open items; {total} are candidates by {test or 'the thick-block test'}, and the pass would touch those.",
           f"- Line ceiling for the output: {max_lines} lines (`[description] max_lines`, or `--max-lines` for a sample).",
           f"- Sample: the {len(rows)} longest. {ok} rewrites passed the checks (every link, number, date and quote kept; every line a bullet), {len(rows) - ok} were refused.", ""]
    for r in rows:
        out += [f"## {r['shown']}: {r['subject']}", ""]
        out += [f"**Before** ({r['before_len']} characters, {r['before_lines']} line{'s' if r['before_lines'] != 1 else ''})", ""]
        out += [("> " + ln) if ln.strip() else ">" for ln in r["before"].splitlines()] + [""]
        if r["status"] == "ok":
            out += [f"**After** ({len(r['after'])} characters, {len([x for x in r['after'].splitlines() if x.strip()])} lines; checks passed{', on the second try' if r['note'] == 'second try' else ''})", "", r["after"], ""]
        else:
            out += [f"**After: refused, {r['note']}**", ""]
            if r.get("after"):
                out += ["```text", r["after"], "```", ""]
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str], runner: Callable[[str, str], dict[str, Any]] | None = None, poster: Callable[[str, dict, float], tuple[int, Any]] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Re-bullet the open items whose description the write gate refuses (bullet_text.judge; with require_bullets = false, the thick-block test). Dry run by default.")
    ap.add_argument("--store", default="", help="the item store to read (a COPY for --sample); default: the configured store, read only")
    ap.add_argument("--sample", type=int, default=0, metavar="N", help="run the N longest candidates through the model and print before and after as markdown; writes nothing")
    ap.add_argument("--out", default="", help="with --sample: write the markdown to this file instead of stdout")
    ap.add_argument("--apply", action="store_true", help="the real pass: rewrite through the live server's /client/rebullet route")
    ap.add_argument("--only", default=None, metavar="IDS", help="touch only these items (board#N,board#M or gN,gM; commas or spaces); any of them that is not a candidate is said and skipped. An empty list is an error")
    ap.add_argument("--except", dest="except_", default=None, metavar="IDS", help="touch every candidate except these items. An empty list is an error")
    ap.add_argument("--json", default="", metavar="FILE", help="with --sample: also save every rewrite (item, old text, new text, verdict) as JSON in this file; with --out and no --json, FILE is the --out name with .json")
    ap.add_argument("--from", dest="from_", default="", metavar="FILE", help="with --apply: write exactly the rewrites saved in this JSON file (no model call); an item not in the file is never written")
    ap.add_argument("--model", default=_rb.MODEL, help="the call's model (default: a Haiku-class one)")
    ap.add_argument("--sender", default="rebullet", help="the author the record keeps (default rebullet)")
    ap.add_argument("--max-lines", type=int, default=0, metavar="N", help="the line ceiling of the output (default: [description] max_lines). With --sample it shows what another ceiling gives; "
                                                                        "--apply refuses a value other than the config's, since the server's write would refuse a longer text")
    a = ap.parse_args(argv)
    if a.apply and (a.store or a.sample):
        ap.error("--apply writes through the live server and takes neither --store nor --sample")
    if a.apply and not a.from_:
        ap.error("--apply needs --from FILE: it writes only the rewrites saved by --sample (the texts someone read), never a fresh model answer")
    if a.from_ and (not a.apply or a.sample or a.store or a.json):
        ap.error("--from goes with --apply alone: it writes the saved rewrites as they are (no model call, no --sample, --store or --json)")
    if a.json and not a.sample:
        ap.error("--json goes with --sample")
    if a.sample < 0:
        ap.error("--sample is a positive number")
    if a.sample and not a.store:
        ap.error("--sample works on a copy of the store: pass --store <the copy>")
    store = Path(a.store).expanduser() if a.store else _cfg.path("paths", "store")
    items = load_all(store)
    open_n = sum(1 for it in items.values() if it.get("status") == "open")
    max_lines = int(_cfg.get("description", "max_lines", default=8))
    line_max = int(_cfg.get("description", "line_max", default=120))       # the write gate's bullet length and form
    strict = bool(_cfg.get("description", "require_bullets", default=True))
    if a.max_lines:
        if a.apply and a.max_lines != max_lines:
            ap.error(f"--apply uses the config's [description] max_lines ({max_lines}); --max-lines is for a sample")
        max_lines = a.max_lines
    forbid = [str(x) for x in (_cfg.get("description", "forbid_tokens", default=[]) or [])]
    ids = candidates(items, strict=strict, max_lines=max_lines, line_max=line_max)
    saved: dict[str, dict[str, Any]] = {}
    if a.from_:
        try:
            saved = load_saved(Path(a.from_).expanduser())
        except (OSError, ValueError) as e:
            ap.error(f"--from {a.from_}: {e}")
        ids = list(saved)
    try:
        only, skip = parse_ids(a.only or ""), parse_ids(a.except_ or "")
    except ValueError as e:
        ap.error(f"not an item id: {e} (write board#N, #N, gN or N)")
    if a.only is not None and not only:
        ap.error("--only was given an empty list of ids: an empty list would mean every item, so it is refused")
    if a.except_ is not None and not skip:
        ap.error("--except was given an empty list of ids: pass the ids, or leave the option out")
    if only and skip:
        ap.error("--only and --except are one or the other")
    if only or skip:
        for g in only + skip:
            if g not in ids:
                print(f"note: {shown(g)} is not a candidate (not open, or its description already passes the test)")
        ids = [g for g in ids if (g in only if only else g not in skip)]
        print(f"{'--only' if only else '--except'}: {len(ids)} candidate(s) left")
    if not a.sample and not a.apply:
        print(f"{open_n} open items: {len(ids)} are candidates by {test_name(strict, max_lines, line_max)}: {reason_counts(items, ids, strict=strict, max_lines=max_lines, line_max=line_max)}; "
              f"{open_n - len(ids)} pass and are skipped; closed items are never touched")
        for g in ids:
            d = str(items[g].get("description") or "")
            why = reason(d, strict=strict, max_lines=max_lines, line_max=line_max)
            print(f"  {shown(g)}: {why}, {prose_len(d)} characters, {len([x for x in d.splitlines() if x.strip()])} line(s): {str(items[g].get('subject') or '')[:70]}")
        print("DRY RUN: no model was called and nothing was written. --sample N --store <copy of the store> shows before and after; --apply writes through the server.")
        return 0
    if runner is None and not a.from_:
        from stackshot.router import router as _router  # noqa: E402  — only a model call needs the router's runner
        runner = lambda message, system: _router.run_call(message, system, model_name=a.model)  # noqa: E731
    run = ids[: a.sample] if a.sample else ids
    rows: list[dict[str, Any]] = []
    bad = 0
    post = poster
    if a.apply and post is None:
        from stackshot.fleet import client as _client  # noqa: E402  — only an apply needs this machine's token and the server's address
        post = _client.post
    for g in run:
        if a.from_:
            it, old, new = items.get(g) or {}, saved[g]["old"], saved[g]["new"]
            if it.get("status") != "open":
                bad += 1
                print(f"left alone {shown(g)}: the item is not open (or not in the store)")
                continue
            if str(it.get("description") or "") != old:
                bad += 1
                print(f"left alone {shown(g)}: its description changed since the sample was read")
                continue
            note = _rb.verdict(old, new, max_lines=max_lines, forbid=forbid, subject=str(it.get("subject") or ""), line_max=line_max, strict=strict)
            if note:
                bad += 1
                print(f"left alone {shown(g)}: the current checks refuse the saved text: {note}")
                continue
            status = "ok"
        else:
            it = items[g]
            old = str(it.get("description") or "")
            status, new, note = _rb.rewrite(shown(g), it, runner, max_lines=max_lines, forbid=forbid, line_max=line_max, strict=strict)
        if a.sample:
            rows.append({"shown": shown(g), "gid": g, "subject": str(it.get("subject") or "")[:120], "full_subject": str(it.get("subject") or ""), "before": old, "before_len": prose_len(old),
                         "before_lines": len([x for x in old.splitlines() if x.strip()]), "status": status, "after": new, "note": note})
            continue
        if status != "ok":
            bad += 1
            print(f"left alone {shown(g)}: {note}")
            continue
        code, d = post("rebullet", {"item": shown(g), "sender": a.sender.strip(), "old": old, "description": new}, 60.0)
        if code == 200 and isinstance(d, dict):
            print(f"written {shown(g)}: {d.get('action')}")
        else:
            bad += 1
            print(f"NOT written {shown(g)}: [{code}] {d.get('error') if isinstance(d, dict) else d}")
            if code == 0:
                print("the server could not be reached: stopping")
                break
    if a.sample:
        import datetime as _dt
        text = render_sample(rows, len(ids), open_n, a.model, str(store), _dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d"), max_lines, test_name(strict, max_lines, line_max))
        jpath = a.json or (str(Path(a.out).expanduser().with_suffix(".json")) if a.out else "")
        if jpath:
            doc = {"generated": _dt.datetime.now(_cfg.tz()).isoformat(timespec="seconds"), "model": a.model, "max_lines": max_lines, "store": str(store),
                   "rewrites": [{"item": r["shown"], "gid": r["gid"], "subject": r["full_subject"], "old": r["before"], "new": r["after"], "status": r["status"],
                                 "verdict": "" if r["status"] == "ok" else r["note"]} for r in rows]}
            Path(jpath).expanduser().write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"wrote {jpath}: {len(rows)} rewrites as JSON (`--apply --from` writes the ones marked ok)")
        if a.out:
            Path(a.out).expanduser().write_text(text, encoding="utf-8")
            print(f"wrote {a.out}: {len(rows)} items, {sum(1 for r in rows if r['status'] == 'ok')} passed the checks")
        else:
            sys.stdout.write(text)
        return 0
    print(f"APPLY: {len(run)} item(s) tried, {len(run) - bad} written, {bad} left alone or not written")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
