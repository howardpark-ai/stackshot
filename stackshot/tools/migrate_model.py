"""tools/migrate_model.py — the migration of every item onto the item model (the plan is migration.py, the design docs/design).

The script PLANS and the server WRITES: it reads the store (read only), asks the cold call what the items' own fields do not say, and hands the planned writes to the running server (POST
/client/migrate, this machine's token), which applies each through the normal save path (the guards, the GitHub mirror, History, the search) as the author `migration`. It never opens the
store for writing, so there is no second writer beside the server. While it runs the server holds the board-wide pause itself (no wake, no wait ends, no hand-off clock, no notice); at the
end the pause lifts and what came due fires in one batched pass.

  tools/migrate_model.py --dry-run --store <copy>   the whole pass on a COPY of the store, and nothing live: <copy> is a directory made from the live store (items, state, pages, links) that holds
                                                    its own stackshot.toml with [paths] inside it and [github] sync = false. The script imports the server module against that copy, so the
                                                    guards and the save path are the real ones, and applies the writes through it. The cold call runs for real only for the --sample closed items
                                                    (default 20) and for the hidden-wait reads; the other back-fills are counted and left unwritten. GitHub is read only (`gh api`, the close
                                                    reasons of the sampled items). Writes the report (JSON and markdown) to --report-dir.
  tools/migrate_model.py --apply --sender <you>     the real pass, through the live server. Without --backfill-closed the closed items are only counted; with it, every closed item without an
                                                    outcome is read by the cold call and written. Run it only on the owner's word: it changes the live board. The pass SENDS NOTHING: the
                                                    server keeps one generated text per owner under the pass's id (the rows whose write was made, and not already SENT by an earlier run), and
                                                    the script writes wake.txt, to read, with the rows (written before the end is called) to <run-dir>/<pass id>/.
  tools/migrate_model.py --send-wake <dir> --sender <you> [--note "one line"]   sends the texts the server stored for the pass in <dir>, one message per owner, plus the note; no other text goes. The
                                                    server marks each owner sent and refuses a second send; a recipient already sent is skipped and a failed one is tried again by running it
                                                    again. After a crash the texts are rebuilt from rows.json. The route must be on ([model] migration = true), as for the pass.

Mode, residue and the numbers are described in the report: counts by state transition and by guard (before and after), the residue for hand setting (item, kind, why), the hidden-wait proposals
with their confidence, and the sample of closed back-fills with outcome and reason. Exit 0 · 1 when a write could not be made or the pass could not begin."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS = Path.home() / ".local" / "share" / "stackshot-runs" / "migration-dryrun"
DEFAULT_RUN = Path.home() / ".local" / "share" / "stackshot-runs" / "migration-run"
BATCH = 40
RUNNER: Any = None        # the cold call's runner: None = router.run_call (the signed-in lane); --no-cold and the tests put another here


def _no_cold(_message: str) -> dict[str, Any]:
    return {"status": "off", "note": "the cold call was switched off (--no-cold)"}


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------------------------------- the copy a dry run works on
def point_at_copy(store: str) -> Path:
    """Aim every reader of this process at the copy before anything imports config: <copy>/stackshot.toml must exist and keep every path of [paths] inside <copy>; it may not be the live
    config's store and may not mirror to GitHub. → the copy's directory."""
    import tomllib
    d = Path(store).expanduser().resolve()
    cfg_path = d / "stackshot.toml"
    if not cfg_path.is_file():
        raise SystemExit(f"--store {d}: no stackshot.toml in it; a copy is a directory with the store, the state and its own stackshot.toml")
    cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    paths = cfg.get("paths") or {}
    for key in ("repo", "store", "markdown", "brain", "state", "secrets"):
        p = Path(str(paths.get(key) or "")).expanduser()
        if not str(paths.get(key) or "") or not p.resolve().is_relative_to(d):
            raise SystemExit(f"--store {d}: [paths] {key} = {paths.get(key)!r} is not inside the copy; refusing to run against anything but a copy")
    live = Path(os.environ.get("STACKSHOT_CONFIG") or "~/.config/stackshot/stackshot.toml").expanduser()
    if live.is_file():
        lp = tomllib.loads(live.read_text(encoding="utf-8")).get("paths") or {}
        if Path(str(lp.get("store") or "x")).expanduser().resolve() == Path(str(paths["store"])).expanduser().resolve():
            raise SystemExit(f"--store {d}: its store is the live store")
    if (cfg.get("github") or {}).get("sync"):
        raise SystemExit(f"--store {d}: [github] sync is on in the copy's config; a dry run never mirrors (set it to false)")
    if (cfg.get("paths") or {}).get("git") or (cfg.get("publish") or {}).get("git"):
        raise SystemExit(f"--store {d}: the copy's config would commit or push; turn it off")
    os.environ["STACKSHOT_CONFIG"] = str(cfg_path)
    os.environ["STACKSHOT_AUTH"] = "off"
    os.environ.pop("STACKSHOT_URL", None)
    return d


# ---------------------------------------------------------------------------------------------------------------- reading the store
def load_all() -> dict[str, dict[str, Any]]:
    from stackshot.core import config as _cfg
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(_cfg.path("paths", "store").glob("*/*.json")):
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


def sample_of(ids: list[str], n: int) -> list[str]:
    """n of the ids spread evenly over the list (sorted by item number), the same ones on every run over the same store."""
    if n >= len(ids):
        return list(ids)
    if n <= 0:
        return []
    return [ids[int(i * len(ids) / n)] for i in range(n)]


# ---------------------------------------------------------------------------------------------------------------- GitHub, read only
def gh_read(repo: str, number: int) -> tuple[dict[str, Any], list[str]]:
    """The close facts of an issue and its last comments, by `gh api` (read only). ({}, []) when it could not be read."""
    def api(path: str) -> Any:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:160] or f"gh exit {r.returncode}")
        return json.loads(r.stdout)
    try:
        iss = api(f"repos/{repo}/issues/{number}")
        facts = {"state": iss.get("state"), "state_reason": iss.get("state_reason"), "closed_at": iss.get("closed_at"), "closed_by": (iss.get("closed_by") or {}).get("login")}
        comments: list[str] = []
        if int(iss.get("comments") or 0):
            cs = api(f"repos/{repo}/issues/{number}/comments?per_page=100")
            comments = [str(c.get("body") or "") for c in cs[-6:]]
        return facts, comments
    except Exception as e:  # noqa: BLE001
        say(f"gh: issue {number} not read: {type(e).__name__}: {e}")
        return {}, []


# ---------------------------------------------------------------------------------------------------------------- the cold call's two reads
def read_hidden(gid: str, items: dict[str, Any], env: Any, want: dict[str, Any], today: dt.date, runner: Any = None) -> dict[str, Any]:
    from stackshot.model import cold_call as _cold
    from stackshot.model import migration as M
    runner = runner or RUNNER
    it = items[gid]
    mod = env.derive(gid, it)
    choices = env.choices(gid, it, mod)
    project = M.clean((it.get("metadata") or {}).get("project"))
    anchors = env.scoped(project, gid)
    text = " ".join(str(x) for x in (it.get("subject"), it.get("description"), (it.get("metadata") or {}).get("next"), (it.get("metadata") or {}).get("ask")))
    flagged = [str(x) for x in want.get("lines", [])]
    msg = _cold.build_hidden_message(M.shown(gid), it, flagged, today, list(choices), anchors, want.get("why", ""))
    status, ans, note, _res = _cold.run_with(msg, _cold.HIDDEN_RUBRIC, _cold.parse_hidden, runner)
    out: dict[str, Any] = {"status": status, "answer": None, "why": note, "asked": want.get("why", "")}
    if ans is not None:
        valid, why = _cold.validate_hidden(ans, today, list(choices), gid, env.resolve, anchors, text)
        out["answer"], out["why"] = valid, why
        if valid and valid.get("wait") == "yes":
            out["raw_confidence"] = ans.get("confidence")
    return out


def read_closed(gid: str, items: dict[str, Any], env: Any, repo: str, runner: Any = None) -> dict[str, Any]:
    from stackshot.model import cold_call as _cold
    from stackshot.model import migration as M
    runner = runner or RUNNER
    it = items[gid]
    from stackshot.github import ghsync as _ghs
    num = _ghs.issue_of(gid)          # the issue that mirrors the item (an item from before the mirror kept its old id and was given a number then)
    facts, comments = gh_read(repo, num) if repo and num else ({}, [])
    msg = _cold.build_backfill_message(M.shown(gid), it, facts, comments)
    status, ans, note, _res = _cold.run_with(msg, _cold.BACKFILL_RUBRIC, _cold.parse_backfill, runner)
    if ans is None:           # a call that failed or answered with no usable JSON is asked once more
        status, ans, note, _res = _cold.run_with(msg, _cold.BACKFILL_RUBRIC, _cold.parse_backfill, runner)
    out: dict[str, Any] = {"status": status, "answer": None, "why": note, "github": facts}
    if ans is not None:
        valid, why = _cold.validate_backfill(ans, gid, env.resolve)
        out["answer"], out["why"] = valid, why
    return out


def threaded(fn: Any, jobs: list[Any], workers: int) -> list[Any]:
    if not jobs:
        return []
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(fn, jobs))


# ---------------------------------------------------------------------------------------------------------------- applying a plan
class DryApplier:
    """The server module imported against the copy: the writes go through its own `_migrate_write`, so the guards and the save path are the real ones; nothing is published or sent."""

    def __init__(self, sender: str) -> None:
        import logging
        from stackshot.web import server
        logging.disable(logging.INFO)
        self.server = server
        server._publish = lambda: None
        self.sender = sender
        if server._gh.enabled():
            raise SystemExit("the copy's config has the GitHub mirror on; refusing")

    def call(self, body: dict[str, Any]) -> tuple[int, Any]:
        try:
            return 200, self.server._migrate_write({**body, "sender": self.sender}, "dry-run")
        except self.server.ToolError as e:
            return 400, {"error": str(e)}


class LiveApplier:
    def __init__(self, sender: str) -> None:
        from stackshot.fleet import client as _client
        self.client = _client
        self.sender = sender

    def call(self, body: dict[str, Any]) -> tuple[int, Any]:
        return self.client.post("migrate", {**body, "sender": self.sender}, 300.0)


def apply_writes(app: Any, writes: list[Any], rows_for: Any = None, dry: bool = False, before_end: Any = None) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """begin, the writes in batches, end → (the per-item results, what begin said, what end said). The end is in a `finally`: a pass that stops on an error or an interrupt still lifts the hold and
    has the server write the wake texts down (a dry run only lifts the hold). `rows_for(results)` gives the residue rows the end is handed: those whose write was made. `before_end(pass_id, rows)`
    writes them to the run directory before the end is called, so that nothing is lost when the end is not. The end sends nothing."""
    st, begin = app.call({"op": "begin"})
    if st != 200:
        raise SystemExit(f"the pass could not begin: [{st}] {begin.get('error') if isinstance(begin, dict) else begin}")
    results: list[dict[str, Any]] = []
    end_state: dict[str, Any] = {}
    try:
        for i in range(0, len(writes), BATCH):
            chunk = writes[i:i + BATCH]
            st, d = app.call({"op": "apply", "writes": [w.as_body() for w in chunk]})
            if st != 200:
                say(f"a batch was refused as a whole: [{st}] {d.get('error') if isinstance(d, dict) else d}")
                results += [{"item": w.as_body()["item"], "action": "refused", "why": str(d.get("error") if isinstance(d, dict) else d)} for w in chunk]
                continue
            results += d.get("results") or []
    finally:
        if dry:
            app.server._watch.release()
        else:
            try:
                rows = rows_for(results) if rows_for else []
                if before_end:
                    try:
                        before_end(str(begin.get("pass_id") or ""), rows)
                    except Exception as e:  # noqa: BLE001
                        say(f"the wake rows could not be written down before the end: {type(e).__name__}: {e}")
                st, end_state = app.call({"op": "end", "residue": rows})
                if st != 200:
                    say(f"the pass could not be ended: [{st}] {end_state}; the server's hold lapses by itself within the hour")
                    end_state = {}
            except Exception as e:  # noqa: BLE001
                say(f"the pass could not be ended: {type(e).__name__}: {e}; the server's hold lapses by itself within the hour")
    return results, begin, end_state


# ---------------------------------------------------------------------------------------------------------------- the GitHub writes the pass makes
def github_cost(gid: str, before: dict[str, Any], after: dict[str, Any], names: dict[str, str], synced: dict[str, str]) -> dict[str, int]:
    """What one written item with an issue costs GitHub, from the item before and as the write leaves it, with the mirror's own function (ghsync.mirrored): since an earlier change the issue carries the subject,
    open or closed and the description alone, so the write costs one issue edit when one of those changes and nothing otherwise (no comment, no typed field, no blocked-by link). A piece that cannot be
    computed counts as one write (an upper bound), and `bound` says so."""
    from stackshot.github import ghsync as _G
    out = {"edit": 0, "bound": 0}
    try:
        out["edit"] = 1 if _G.mirrored(before) != _G.mirrored(after) else 0
    except Exception:  # noqa: BLE001
        out["edit"], out["bound"] = 1, out["bound"] + 1
    return out


def _gh_context() -> tuple[dict[str, str], dict[str, str]]:
    from stackshot.github import ghsync as _G
    try:
        synced = _G._synced()
    except Exception:  # noqa: BLE001
        synced = {}
    return _G._names(), synced


def select_writes(writes: list[Any], cap: int, items: dict[str, Any]) -> tuple[list[Any], list[Any], int]:
    """The writes this run makes under the cap on GitHub writes an hour (--max-writes): those of an item with no issue first in their order (the server never mirrors them: no GitHub write at all), then
    the items with an issue in order, each at its cost (github_cost on the item as the write would leave it), until the next would pass the cap. → (the writes to make, in the plan's order; the writes left
    for a run an hour later; the GitHub writes the selected make)."""
    from stackshot.github import ghsync as _G
    from stackshot.model import migration as M
    names, synced = _gh_context()
    take: list[Any] = []
    left: list[Any] = []
    used = 0
    for w in writes:
        if not _G.issue_of(w.gid):
            take.append(w)
            continue
        if left:
            left.append(w)
            continue
        c = github_cost(w.gid, items[w.gid], M.after_state(items[w.gid], w.set, w.drop), names, synced)
        cost = c["edit"]
        if used + cost > cap:
            left.append(w)
            continue
        used += cost
        take.append(w)
    return take, left, used


def github_made(applied: list[str], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What the writes applied cost GitHub, summed per item with an issue (github_cost on the store before and after). An item with no issue costs nothing."""
    from stackshot.github import ghsync as _G
    names, synced = _gh_context()
    out = {"items_with_issue": 0, "items_no_issue": 0, "edits": 0, "bound_pieces": 0}
    for g in applied:
        if not _G.issue_of(g):
            out["items_no_issue"] += 1
            continue
        c = github_cost(g, before.get(g) or {}, after.get(g) or {}, names, synced)
        out["items_with_issue"] += 1
        out["edits"] += c["edit"]; out["bound_pieces"] += c["bound"]
    out["total"] = out["edits"]
    return out


# ---------------------------------------------------------------------------------------------------------------- the report
def guard_counts(rep: Any, mg: Any) -> dict[str, int]:
    out = {k: rep.count(k) for k in mg.GUARDS}
    out[mg.CLOSED_NO_OUTCOME] = rep.count(mg.CLOSED_NO_OUTCOME)
    return out


def reading(items: dict[str, Any], ctx: Any, anchors: dict[str, Any], M: Any) -> dict[str, dict[str, str]]:
    """What the model reads of every open item: its state, its mover (or post-wake mover for a wait), the wait's kind. What a page shows follows from it."""
    env = M.Env(items, ctx, anchors)
    out: dict[str, dict[str, str]] = {}
    for gid, it in items.items():
        if it.get("status") != "open":
            continue
        mod = env.derive(gid, it)
        out[gid] = {"state": mod.state, "mover": mod.mover or "", "post": mod.wait.mover if mod.wait else "", "kind": mod.wait.kind if mod.wait else "",
                    "today": mod.today or ""}
    return out


def residue_wake_rows(residue: list[Any]) -> list[dict[str, Any]]:
    """The residue the owners are told about at the end of the pass: what a person must set (a field named), the defaults the pass stored for them to replace, and the notices already on an anchor."""
    return [r.as_dict() for r in residue if (r.hand and r.fields) or r.kind in ("default_end", "anchor_seen")]


def row_key(r: dict[str, Any]) -> str:
    return "|".join([str(r.get("item")), str(r.get("kind")), ",".join(r.get("fields") or []), str(r.get("default") or "")])


def rows_that_stand(rows: list[dict[str, Any]], planned: set[str], results: list[dict[str, Any]], told: set[str]) -> list[dict[str, Any]]:
    """The wake rows that describe what happened: the plan says "stored ask_by=… as a default", and that holds only for an item whose write returned `set`. A row about an item whose planned write was
    deferred, refused, moved or crashed is dropped (the item is as it was; the report lists it as such); a row about an item with no write at all stays; a row already in an earlier run's texts
    (`told`: the run directory's ledger) is not repeated. The server checks each row once more against the item as stored."""
    action = {r["item"]: r["action"] for r in results}
    out = []
    for r in rows:
        if row_key(r) in told:
            continue
        a = action.get(r["item"])
        if r["item"] in planned:
            if r.get("kind") in ("default_end", "anchor_seen") and a != "set":
                continue
            if a not in ("set", "already"):
                continue
        out.append(r)
    return out


LEDGER = "wake-ledger.json"      # the rows an owner has been SENT (never the rows only written down): a later run does not repeat them


def ledger_of(run_dir: Path) -> set[str]:
    try:
        return set(json.loads((run_dir / LEDGER).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def ledger_add(run_dir: Path, keys: list[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / LEDGER).write_text(json.dumps(sorted(ledger_of(run_dir) | set(keys)), indent=1) + "\n", encoding="utf-8")


def write_rows(run_dir: Path, pass_id: str, rows: list[dict[str, Any]]) -> Path:
    """Before the pass is ended: the pass's id and the wake rows that stand, in <run-dir>/<pass id>/, so that a script that dies, or an `end` whose answer is lost, leaves them where --send-wake finds
    them and has the server build the texts from them."""
    d = run_dir / pass_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "pass.json").write_text(json.dumps({"pass_id": pass_id}) + "\n", encoding="utf-8")
    (d / "rows.json").write_text(json.dumps({"pass_id": pass_id, "rows": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return d


def write_reading(d: Path, owners: dict[str, Any]) -> None:
    """wake.txt: the texts the server holds for the pass, to read, with whether each went. The files in the directory are for reading only: what is sent is the server's stored text."""
    def mark(o: dict[str, Any]) -> str:
        sent = o.get("sent")
        return f"sent {sent.get('at') if isinstance(sent, dict) else sent}" if sent else "not sent yet"
    (d / "wake.txt").write_text("\n\n".join(f"== to {who} ({mark(o)})\n{o.get('text', '')}" for who, o in sorted(owners.items())) + "\n", encoding="utf-8")


def send_wake(dirp: Path, sender: str, note: str = "") -> int:
    """--send-wake <dir>: send the texts the server stored for the pass in <dir>, one message per owner, with an optional one-line note. The server's mark is the truth of what was sent: an owner it
    has marked is skipped (and its rows go into the ledger if a crash left them out), the rest are sent, and a failed owner can be tried again by running this again. A pass whose `end` did not
    complete has the texts built from the rows written down before it."""
    from stackshot.model import migration as M
    try:
        pass_id = json.loads((dirp / "pass.json").read_text(encoding="utf-8"))["pass_id"]
        rows = json.loads((dirp / "rows.json").read_text(encoding="utf-8")).get("rows") or []
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"{dirp} is not a pass directory (pass.json, rows.json): {e}")
    app = LiveApplier(sender)
    st, r = app.call({"op": "wake_text", "pass_id": pass_id, "rows": rows})
    if st != 200 or not isinstance(r, dict):
        raise SystemExit(f"the texts of pass {pass_id} could not be read: [{st}] {r.get('error') if isinstance(r, dict) else r}")
    owners = r.get("owners") or {}
    run_dir = dirp.parent
    keys_of = lambda o: [row_key(x) for x in rows if x["item"] in {M.shown(g) for g in o.get("gids") or []}]
    bad = 0
    for label, o in sorted(owners.items()):
        if o.get("sent"):
            ledger_add(run_dir, keys_of(o))
            say(f"{label}: already sent; skipped")
            continue
        if not o.get("sid"):
            say(f"{label}: nobody to send to; left unsent")
            continue
        body = {"op": "send_wake", "pass_id": pass_id, "owner": label}
        if note:
            body["note"] = note
        st, r2 = app.call(body)
        if st != 200 or not isinstance(r2, dict) or r2.get("sent") is not True:
            bad += 1
            say(f"{label}: NOT sent: " + (f"[{st}] {r2.get('error')}" if st != 200 and isinstance(r2, dict) else str(r2.get("why") if isinstance(r2, dict) else r2)) + "; run --send-wake again to retry it")
            continue
        o["sent"] = {"at": r2.get("at") or ""}
        ledger_add(run_dir, keys_of(o))             # the mark is made after the send: a crash between them is found again by the server's mark
        say(f"{label}: sent ({len(o.get('gids') or [])} item(s))")
    write_reading(dirp, owners)
    return 1 if bad else 0


def summary_of(plan: Any, after_reading: dict[str, dict[str, str]], residue: list[Any], env: Any, items: dict[str, Any], M: Any) -> dict[str, Any]:
    """The counts the hand-back names: the open items by state and the waits by kind (as the model reads them after the pass), the backstops added, the relay waits' post-wake movers by where the
    record had them and by what they are, and the items whose mover was replaced (the pass keeps the last mover as recorded: it replaces only a gone one that is no front agent)."""
    states: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for r in after_reading.values():
        states[r["state"]] = states.get(r["state"], 0) + 1
        if r["kind"]:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    by_src: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for g, (who, src) in plan.relay_post.items():
        by_src[src] = by_src.get(src, 0) + 1
        proj = M.clean(((items.get(g) or {}).get("metadata") or {}).get("project"))
        role = "nobody" if not who else M._model.owner_display() if M._model.is_owner(who) else "a front agent" if env.is_front(who, proj) else "a background agent" if env.ctx.background_of(who, proj) else "another session (the board's owner or a live session)"
        by_role[role] = by_role.get(role, 0) + 1
    return {"open_by_state": dict(sorted(states.items())), "waits_by_kind": dict(sorted(kinds.items())), "backstops_added": [M.shown(r.gid) for r in residue if r.kind == "default_end"],
            "relay_post_by_source": dict(sorted(by_src.items())), "relay_post_by_role": dict(sorted(by_role.items())), "relay_post_owner": by_role.get(M._model.owner_display(), 0), "owner_name": M._model.owner_display(),
            "reassigned": [M.shown(g) for g in plan.reassigned]}


def md_table(rows: list[list[str]], head: list[str]) -> str:
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]])


def write_report(rep: dict[str, Any], d: Path, stamp: str, tag: str) -> tuple[Path, Path]:
    d.mkdir(parents=True, exist_ok=True)
    jp, mp = d / f"{stamp}-{tag}.json", d / f"{stamp}-{tag}.md"
    jp.write_text(json.dumps(rep, indent=1, ensure_ascii=False, sort_keys=False), encoding="utf-8")
    c = rep["counts"]
    lines = [f"# Item model migration, {rep['mode']}, {rep['when']}", "",
             f"{c['open']} open items, {c['closed']} closed ({c['closed_without_outcome']} without an outcome). {c['writes']} planned writes: {c['applied']} applied, {c['already']} already so, "
             f"{c['moved']} moved since planned, {c['refused']} refused by the guards.", ""]
    lines += ["## State transitions (open items)", "", md_table([[k, str(len(v)), ", ".join(v[:8]) + (" ..." if len(v) > 8 else "")] for k, v in rep["transitions"].items()], ["transition", "items", "which"]), ""]
    lines += ["## Guards, before and after", "", md_table([[k, str(rep["guards_before"].get(k, 0)), str(rep["guards_after"].get(k, 0))] for k in rep["guards_before"]], ["guard", "before", "after"]), ""]
    kinds: dict[str, int] = {}
    for r in rep["residue"]:
        kinds[r["kind"] + (" (listed, hand setting)" if r["hand"] else " (dealt with)")] = kinds.get(r["kind"] + (" (listed, hand setting)" if r["hand"] else " (dealt with)"), 0) + 1
    lines += ["## Residue by kind", "", md_table([[k, str(v)] for k, v in sorted(kinds.items())], ["kind", "items"]), ""]
    lines += ["## Residue", "", md_table([[r["item"], r["kind"], "hand" if r["hand"] else "done", r["why"]] for r in rep["residue"]], ["item", "kind", "left for", "why"]), ""]
    if rep["proposals"]:
        lines += ["## Hidden-wait reads", "", md_table([[p["item"], p.get("kind", ""), p.get("confidence", ""), "set" if p.get("applied") else "listed", p.get("why", "")] for p in rep["proposals"]],
                                                     ["item", "kind", "confidence", "result", "why"]), ""]
    lines += ["## Closed items without an outcome", "", f"{c['closed_without_outcome']} in all; {len(rep['closed_all'])} read by the cold call; "
              f"{rep['closed_unwritten']} counted and left unwritten.", ""]
    if rep["closed_outcomes"]:
        lines += [md_table([[k, str(v)] for k, v in rep["closed_outcomes"].items()], ["outcome written", "items"]), ""]
    if rep["closed_sample"]:
        lines += [md_table([[s["item"], s["title"], s.get("read", "").replace("_", " "), s.get("confidence", ""), s["outcome"], s["reason"], s.get("github", "")] for s in rep["closed_sample"]],
                           ["item", "title", "the call read", "confidence", "written", "the call's reason", "GitHub close"]), ""]
    gh = rep.get("github") or {}
    if gh:
        lines += ["## GitHub writes", "", f"{gh['items_with_issue']} written items have an issue; {gh['items_no_issue']} have none and are never mirrored (no write, and no issue created). "
                  f"Issue edits where the subject, open or closed, or the description changes (the only things the issue carries): {gh['edits']}. **Total {gh['total']}** (cap {gh['cap']} an hour"
                  + (f"; {gh['bound_pieces']} piece(s) counted at their upper bound" if gh.get("bound_pieces") else "") + ")."
                  + (f" Left for a later run: {', '.join(gh['deferred'])}." if gh.get("deferred") else ""), ""]
    if rep["reading_changes"]:
        lines += ["## What the model reads differently after", "", md_table([[x["item"], x["before"], x["after"], x["why"]] for x in rep["reading_changes"]], ["item", "before", "after", "why"]), ""]
    sm = rep.get("summary")
    if sm:
        lines += ["## Counts", "", md_table([[k, str(v)] for k, v in sm["open_by_state"].items()], ["open items by state after the pass", "items"]), "",
                  md_table([[k, str(v)] for k, v in sm["waits_by_kind"].items()], ["waits by kind", "items"]), "",
                  f"Backstops added (a default ask_by for its mover to replace): {len(sm['backstops_added'])} ({', '.join(sm['backstops_added']) or 'none'}).", "",
                  md_table([[k, str(v)] for k, v in sm["relay_post_by_source"].items()], ["a relay wait's post-wake mover is taken from", "items"]), "",
                  md_table([[k, str(v)] for k, v in sm["relay_post_by_role"].items()], ["…and it is", "items"]), "",
                  f"Relay waits with {sm['owner_name']} as post-wake mover: {sm['relay_post_owner']}. Items whose mover was replaced by another session: {len(sm['reassigned'])}"
                  + (f" ({', '.join(sm['reassigned'])})" if sm["reassigned"] else "") + ".", ""]
    if rep.get("mid_pass_paths"):
        lines += ["## What still notifies while the pass runs", "", "The pass holds the wake pass, the waits' watchers, the hand-off clock, the idle clock, the checks and the For you ticks. These events "
                  "are not held, since each is a person's or a session's own act, and an item one of them moves is reported `moved` (never overwritten):", "", *[f"- {x}" for x in rep["mid_pass_paths"]], ""]
    if rep.get("wake"):
        lines += ["## The batched wake: what each recipient is told to set by hand", ""]
        for who, text in sorted(rep["wake"].items()):
            lines += [f"### {who}", "", "```", text, "```", ""]
    if rep.get("wake_preview"):
        lines += ["## What fires when the pause lifts", "", ", ".join(rep["wake_preview"]) or "nothing", ""]
    mp.write_text("\n".join(lines), encoding="utf-8")
    return jp, mp


# ---------------------------------------------------------------------------------------------------------------- main
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Migrate every item onto the item model: the script plans, the server writes.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="the whole pass on a copy of the store (--store); nothing live is touched")
    mode.add_argument("--apply", action="store_true", help="the real pass through the live server (needs --sender); only on the owner's word")
    mode.add_argument("--send-wake", default="", metavar="DIR", help="send the wake texts the server stored for the real pass whose directory is DIR (after reading wake.txt there); a recipient already sent is skipped")
    ap.add_argument("--note", default="", help="with --send-wake: one line (at most 200 characters) added to each text")
    ap.add_argument("--store", default="", help="with --dry-run: the copy's directory (it holds its own stackshot.toml)")
    ap.add_argument("--sender", default="", help="the session that runs the pass (one of [model] migration_senders); needed with --apply and --send-wake")
    ap.add_argument("--sample", type=int, default=20, help="without --backfill-closed (a dry run only): how many closed items the cold call reads (default 20); the rest are counted and left unwritten")
    ap.add_argument("--backfill-closed", action="store_true", help="read and write the outcome of every closed item that has none (done | dropped | superseded | unrecorded); the real pass's whole back-fill")
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORTS))
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN), help="the real pass: where the batched wake's text is kept (a dry run keeps it beside its report)")
    ap.add_argument("--max-writes", type=int, default=150, help="the most GitHub writes this run may make (the pass stays under the hour's budget): items with no issue cost none; an item with an issue costs one "
                    "issue edit where its subject, open or closed, or description changes; what does not fit is left for a run an hour later (default 150)")
    ap.add_argument("--no-cold", action="store_true", help="never start the cold call: every read it would make is listed as unread (a smoke run)")
    ap.add_argument("--workers", type=int, default=3, help="cold calls at a time")
    a = ap.parse_args(argv)
    if (a.apply or a.send_wake) and not a.sender.strip():
        ap.error("--apply and --send-wake need --sender <the session that runs the pass>")
    if a.send_wake:
        return send_wake(Path(a.send_wake).expanduser(), a.sender, a.note)
    global RUNNER
    if a.no_cold:
        RUNNER = _no_cold
    if a.dry_run:
        if not a.store:
            ap.error("--dry-run needs --store <a copy of the store>")
        copy = point_at_copy(a.store)
    else:
        copy = None
    from stackshot.core import config as _cfg
    from stackshot.model import migration as M
    from stackshot.model import model_guards as _mg
    from stackshot.model import states as _states
    tz = _cfg.tz()
    now = dt.datetime.now(tz)
    today = now.date()
    stamp = now.strftime("%Y-%m-%d")
    items = load_all()
    ctx = _mg.Ctx(shown=M.shown)
    from stackshot.anchors import anchors as _anc
    anchors = _anc.load()
    one_mover = bool(_cfg.get("model", "one_mover", default=True))
    repo = str(_cfg.get("github", "issues_repo", default="") or "")
    before_rep = _mg.report(items, ctx, anchors=anchors, one_mover=one_mover)
    before_reading = reading(items, ctx, anchors, M)
    say(f"{before_rep.open} open and {before_rep.closed} closed items read from {_cfg.path('paths', 'store')}")

    # ---- the plan, in two passes: what the fields say, then what the cold call reads
    env1 = M.Env(items, ctx, anchors, today, one_mover=one_mover)
    plan1 = M.plan_items(items, env1)
    reads: dict[str, dict[str, Any]] = {}
    jobs = sorted(plan1.wants_read.items(), key=lambda kv: M._num(kv[0]))
    say(f"cold call: {len(jobs)} hidden-wait read(s)")
    for (gid, _w), r in zip(jobs, threaded(lambda kv: read_hidden(kv[0], items, env1, kv[1], today), jobs, a.workers)):
        reads[gid] = r
    env2 = M.Env(items, ctx, anchors, today, reads=reads, one_mover=one_mover)
    plan = M.plan_items(items, env2)

    # ---- the closed items
    nooutcome = M.closed_without_outcome(items)
    if a.backfill_closed:
        picked = list(nooutcome)
    else:
        picked = sample_of(nooutcome, a.sample) if a.dry_run else []
    say(f"cold call: {len(picked)} closed back-fill read(s) of {len(nooutcome)}")
    closed_reads = dict(zip(picked, threaded(lambda g: read_closed(g, items, env2, repo), picked, a.workers)))
    closed_plan = M.Plan()
    for g in picked:
        M.plan_closed(g, items[g], closed_reads[g], closed_plan)
    sample_rows = [{"item": M.shown(g), "title": str(items[g].get("subject") or ""), "outcome": ((closed_reads[g].get("answer") or {}).get("read") or "unread").replace("_", " "),
                    "reason": (closed_reads[g].get("answer") or {}).get("call_said") or (closed_reads[g].get("answer") or {}).get("reason") or closed_reads[g].get("why") or "",
                    "github": ((closed_reads[g].get("github") or {}).get("state_reason") or ((closed_reads[g].get("github") or {}).get("state") or "no issue read"))}
                   for g in picked]
    closed_all = {M.shown(g): {"title": str(items[g].get("subject") or ""), "outcome": (closed_reads[g].get("answer") or {}).get("outcome") or "unread",
                               "reason": (closed_reads[g].get("answer") or {}).get("reason") or closed_reads[g].get("why") or "", "superseded_by": (closed_reads[g].get("answer") or {}).get("superseded_by", ""),
                               "call_said": (closed_reads[g].get("answer") or {}).get("call_said", ""), "confidence": (closed_reads[g].get("answer") or {}).get("confidence", ""),
                               "read": (closed_reads[g].get("answer") or {}).get("read", "")} for g in picked}
    unsure = {M.shown(r.gid) for r in closed_plan.residue if r.kind == "closed_unsure"}
    wrote = {M.shown(w.gid): w.set["outcome"] for w in closed_plan.writes}
    for g_, row in closed_all.items():        # `outcome` is what the pass writes (the call's read stays in `read` and its confidence beside it): done | dropped | superseded | unrecorded, or listed or unread
        row["outcome"] = wrote.get(g_) or ("listed" if g_ in unsure else "unread")
    keep = {M.shown(g) for g in sample_of(picked, a.sample)}         # the table shows an even spread of --sample items; closed_all holds every one
    sample_rows = [dict(r, outcome=closed_all[r["item"]]["outcome"], confidence=closed_all[r["item"]]["confidence"], read=closed_all[r["item"]]["read"]) for r in sample_rows if r["item"] in keep]
    planned_writes = [*plan.writes, *closed_plan.writes]
    from stackshot.github import ghsync as _G
    for w in planned_writes:          # what an answer or a comment changes without moving `updated`: the server checks it again with each write
        w.sig = M.activity_sig(items[w.gid], 0)     # the owner's comments on GitHub are answers on the item (via github): the second place is 0 since the mirror keeps no copy of the issue's comments
    planned = {M.shown(w.gid) for w in planned_writes}
    writes, deferred, gh_bound = select_writes(planned_writes, a.max_writes, items)
    residue = [*plan.residue, *closed_plan.residue]
    for w in deferred:
        residue.append(M.Residue(w.gid, "deferred", f"not written in this run: the cap of {a.max_writes} GitHub writes an hour was met; run the pass again an hour later and it plans what is left"))

    # ---- apply: the server's own save path, on the copy or on the live server
    results: list[dict[str, Any]] = []
    begin: dict[str, Any] = {}
    end_state: dict[str, Any] = {}
    wake_preview: list[str] = []
    wake: dict[str, str] = {}
    wake_detail: dict[str, Any] = {}
    kept_rows: list[dict[str, Any]] = []
    run_dir = Path(a.run_dir).expanduser()
    if a.dry_run:
        app: Any = DryApplier(a.sender or "dry-run")
        if writes:
            results, begin, _ = apply_writes(app, writes, dry=True)
        # the pass ends: what the lift of the pause would fire (read only; nothing is sent in a dry run), and the text of the residue wake each owner would get (rows whose write was made, as the real pass keeps them)
        kept_rows = rows_that_stand(residue_wake_rows(residue), planned, results, set())
        wake_detail = app.server._migrate_wake(kept_rows)
        wake = {k: v["text"] for k, v in wake_detail.items()}
        after_items = load_all()
        for gid, it in sorted(after_items.items(), key=lambda kv: M._num(kv[0])):
            if it.get("status") != "open":
                continue
            try:
                if app.server._watch.watches(it) and app.server._watch.due(it, time.time(), env2.after_open(it)):
                    wake_preview.append(M.shown(gid))
            except Exception:  # noqa: BLE001
                continue
    else:
        app = LiveApplier(a.sender)
        if writes:
            told = ledger_of(run_dir)

            def rows_for(res: list[dict[str, Any]]) -> list[dict[str, Any]]:
                kept_rows[:] = rows_that_stand(residue_wake_rows(residue), planned, res, told)
                return kept_rows
            results, begin, end_state = apply_writes(app, writes, rows_for, before_end=lambda pid, rows: write_rows(run_dir, pid, rows))
            wake_detail = dict(end_state.get("wake_detail") or {})
            wake = {k: v["text"] for k, v in wake_detail.items()}
        else:
            say("nothing to write")
        after_items = load_all()

    # ---- what happened
    by_action: dict[str, int] = {}
    for r in results:
        by_action[r["action"]] = by_action.get(r["action"], 0) + 1
    gid_of = {M.shown(w.gid): w.gid for w in writes}
    for r in results:
        if r["action"] in ("refused", "moved"):
            residue.append(M.Residue(gid_of.get(r["item"], r["item"]), r["action"], r["why"]))
    after_ctx = _mg.Ctx(shown=M.shown)
    after_rep = _mg.report(after_items, after_ctx, anchors=_anc.load(), one_mover=one_mover)
    after_reading = reading(after_items, after_ctx, _anc.load(), M)
    changes: list[dict[str, str]] = []
    notes = {M.shown(r.gid): r.why for r in residue if r.kind in ("snooze_alive", "mover_gone")}
    for gid, b in before_reading.items():
        af = after_reading.get(gid)
        if af is None:
            continue
        key = lambda x: (x["state"], x["mover"].casefold(), x["post"].casefold(), x["kind"])
        if key(b) != key(af):
            describe = lambda x: f"{x['state']}" + (f", {env2.label(x['mover'])}" if x["mover"] else "") + (f", waits ({x['kind']}) then {env2.label(x['post'])}" if x["kind"] else "")
            changes.append({"item": M.shown(gid), "before": describe(b), "after": describe(af), "why": notes.get(M.shown(gid), "a hidden wait set, or a mover replaced")})
    gb, ga = guard_counts(before_rep, _mg), guard_counts(after_rep, _mg)
    applied_gids = [gid_of[r["item"]] for r in results if r["action"] == "set" and r["item"] in gid_of]
    github = github_made(applied_gids, items, after_items)
    github.update(cap=a.max_writes, bound_selected=gh_bound, deferred=[M.shown(w.gid) for w in deferred])
    report = {
        "mode": "dry run on a copy" if a.dry_run else "real pass", "when": now.strftime("%a %b %d %H:%M %Z"), "store": str(_cfg.path("paths", "store")),
        "counts": {"open": before_rep.open, "closed": before_rep.closed, "closed_without_outcome": len(nooutcome), "writes": len(writes), "applied": by_action.get("set", 0),
                   "already": by_action.get("already", 0), "moved": by_action.get("moved", 0), "refused": by_action.get("refused", 0)},
        "transitions": {k: [M.shown(g) for g in v] for k, v in sorted(plan.transitions().items())},
        "transition_outcome": {M.shown(g): o for g, o in plan.outcome.items()},
        "guards_before": gb, "guards_after": ga,
        "residue": [r.as_dict() for r in sorted(residue, key=lambda r: (r.kind, M._num(r.gid)))],
        "proposals": [{"item": p["item"], "kind": (p.get("answer") or {}).get("kind", ""), "confidence": (p.get("answer") or {}).get("confidence", ""), "applied": p.get("applied"), "why": p.get("why", ""),
                       "reason": (p.get("answer") or {}).get("reason", ""), "asked": p.get("asked", "")} for p in plan.proposals],
        "closed_sample": sample_rows, "closed_unwritten": len(nooutcome) - len(picked) if a.dry_run else len([g for g in nooutcome if g not in picked]),
        "closed_unread": [r.as_dict() for r in closed_plan.residue],
        "apply": {"by_action": by_action, "results": results, "begin": begin, "end": end_state},
        "reading_changes": changes, "wake_preview": wake_preview, "wake": wake, "github": github, "mid_pass_paths": list(M.MID_PASS_PATHS),
        "summary": summary_of(plan, after_reading, residue, env2, items, M),
        "closed_outcomes": dict(sorted({o: sum(1 for v in closed_all.values() if v["outcome"] == o) for o in {v["outcome"] for v in closed_all.values()}}.items())), "closed_all": closed_all,
    }
    d = Path(a.report_dir).expanduser()
    jp, mp = write_report(report, d, stamp, "migration-dryrun" if a.dry_run else "migration-pass")
    say(f"report: {jp} and {mp}")
    if wake and a.dry_run:
        d.mkdir(parents=True, exist_ok=True)
        wp = d / f"{stamp}-migration-dryrun-residue-wake.txt"
        wp.write_text("(a dry run: nothing was sent)\n\n" + "\n\n".join(f"== to {who}\n{text}" for who, text in sorted(wake.items())) + "\n", encoding="utf-8")
        report["wake_file"] = str(wp)
        jp.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        say(f"residue wake text: {wp}")
    elif wake:
        wd = run_dir / str(begin.get("pass_id") or "")
        write_reading(wd, {k: {**v, "sent": None} for k, v in wake_detail.items()})
        report["wake_dir"] = str(wd)
        jp.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        say(f"residue wake texts kept on the server and written for reading, NOT sent: {wd} (read wake.txt, then: tools/migrate_model.py --send-wake {wd} --sender <you> [--note \"one line\"])")
    print(json.dumps({"report": str(mp), "json": str(jp), "counts": report["counts"], "guards_before": gb, "guards_after": ga}, indent=1))
    bad = by_action.get("refused", 0) if not a.dry_run else 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
