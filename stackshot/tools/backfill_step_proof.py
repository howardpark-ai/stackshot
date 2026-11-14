"""tools/backfill_step_proof.py — the one-off fill-in after a step's proof (step_proof.py) arrived before the server could see it.

An open step that names the event which finishes it (`release PR #4`, `merge PR #4`, or a `step_proof` on the item) is ticked by the server when the event happens. Items written before
that ticking existed still carry such steps although the pull request is long since merged and live. This finds them and says what the server would do for each, exactly as the server's
own pass would (it runs the server's `sweep_proofs` (service/proofs.py) in-process, on a COPY of the store, so nothing live is read for writing or written):

  tools/backfill_step_proof.py                      dry run (the default, also `--dry-run`): one line per item, then the counts; writes nothing, needs no server
  tools/backfill_step_proof.py --json               the same as JSON ({"counts", "head", "good", "items": [{item, action, kind, pr, step, ...}]})
  tools/backfill_step_proof.py --store DIR          read the items from DIR (a copy of the store, `anchors.json` beside them) instead of [paths] store
  tools/backfill_step_proof.py --config FILE        the stackshot.toml to read (default: $STACKSHOT_CONFIG, then ~/.config/stackshot/stackshot.toml)
  tools/backfill_step_proof.py --checkout DIR       the git checkout whose merges count (default: the checkout this file is in); its `origin` says which repository's pull requests are "this one's"
  tools/backfill_step_proof.py --state DIR          the state folder that holds `releases/last-good` (default: [paths] state)
  tools/backfill_step_proof.py --github            also read, from GitHub, the pull requests git cannot answer for (another repository's, or not fetched here): read-only GETs
  tools/backfill_step_proof.py --apply              write them: asks the running server to do it (`client.py sweep-step-proof`, this machine's token), which ticks, tells movers and closes
                                                    exactly what the dry run listed. Refused together with --store/--config/--checkout/--state (those only point a dry run at a copy).

What a dry run reads: git (the checkout's HEAD and `origin/main`, and the last-good commit release.sh records) for this repository's merges and releases. By default it makes no GitHub call, so a pull
request of another repository, or one this checkout has not fetched, reads as "not merged yet" and is listed at the end as not read; `--github` reads those too (read-only GETs with the machine's own
GitHub login, as the server's pass does). A pull request closed without a merge ticks nothing. Items on hold, waiting on a decision, or whose needs name a session other than the mover are listed as left alone, with why.

Exit 0 · 1 when --apply could not run. Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing (as tools/tool_text.py does)."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH_KEYS = ("repo", "store", "markdown", "rules", "brain", "fleet_names", "state", "secrets", "claude_credentials", "project_touch")


def ensure_env() -> None:
    try:
        import fastmcp  # noqa: F401, PLC0415
        return
    except ImportError:
        pass
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    env = dict(os.environ)
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "stackshot" / "test-venv"))
    if not Path(uv).exists():
        raise SystemExit("backfill_step_proof: fastmcp is missing and uv was not found: run it from the tests' environment, or install uv")
    os.execve(uv, [uv, "run", "--locked", "--project", str(ROOT), "--only-group", "tests", "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


def config_text(path: Path | None) -> tuple[str, Path]:
    cands = [path] if path else [Path(p).expanduser() for p in (os.environ.get("STACKSHOT_CONFIG"), os.environ.get("BOARD_MCP_CONFIG"), "~/.config/stackshot/stackshot.toml") if p]
    for c in cands:
        if c and c.exists():
            return c.read_text(encoding="utf-8"), c
    raise SystemExit("backfill_step_proof: no stackshot.toml found: pass --config FILE")


def paths_of(toml: str) -> dict[str, str]:
    """The [paths] values of a config text, as written."""
    out: dict[str, str] = {}
    sect = ""
    for ln in toml.splitlines():
        m = re.match(r"^\[([^\]]+)\]", ln)
        if m:
            sect = m.group(1)
        elif sect == "paths":
            k = re.match(r'^(\w+)\s*=\s*"([^"]*)"', ln)
            if k:
                out[k.group(1)] = k.group(2)
    return out


def throwaway_config(toml: str, tmp: Path, store: Path) -> str:
    """The config text with every [paths] folder moved under `tmp` (the store to the copy `store`): the server imported on it can touch nothing of the instance's."""
    sect = ""
    out = []
    for ln in toml.splitlines():
        m = re.match(r"^\[([^\]]+)\]", ln)
        if m:
            sect = m.group(1)
        k = re.match(r'^(\w+)(\s*=\s*)"[^"]*"', ln) if sect == "paths" else None
        if k and k.group(1) in PATH_KEYS:
            val = str(store) if k.group(1) == "store" else str(tmp) if k.group(1) == "repo" else str(tmp / k.group(1))     # the store lies inside the repo folder, as publish.py requires
            ln = f'{k.group(1)} = "{val}"'
        out.append(ln)
    return "\n".join(out) + "\n"


def run(a: argparse.Namespace) -> dict:
    toml, cfg = config_text(a.config)
    real = paths_of(toml)
    src = Path(a.store).expanduser() if a.store else Path(os.path.expanduser(real.get("store", "~/stackshot-data/board-data")))
    state = Path(a.state).expanduser() if a.state else Path(os.path.expanduser(real.get("state", "~/.local/state/stackshot")))
    if not src.is_dir():
        raise SystemExit(f"backfill_step_proof: the store {src} is not a folder")
    with tempfile.TemporaryDirectory(prefix="stepproof-") as t:
        tmp = Path(t)
        store = tmp / "store"
        shutil.copytree(src, store, ignore=shutil.ignore_patterns(".git"))       # a copy: the dry run reads this one
        for d in ("state/releases", "fleet", "secrets", "brain"):
            (tmp / d).mkdir(parents=True, exist_ok=True)
        lg = state / "releases" / "last-good"
        if lg.exists():
            shutil.copy(lg, tmp / "state/releases/last-good")
        (tmp / "stackshot.toml").write_text(throwaway_config(toml, tmp, store), encoding="utf-8")
        os.environ.update(STACKSHOT_CONFIG=str(tmp / "stackshot.toml"), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(tmp / "fleet"))
        os.environ.pop("STACKSHOT_URL", None)
        import logging
        logging.disable(logging.INFO)
        from stackshot.service import checks as _checks, proofs as _proofs, released as _released, released_live as _live  # noqa: PLC0415
        from stackshot.web import server  # noqa: PLC0415, F401  — importing it fills the hook tables the service modules read
        from stackshot.web import publish as _web_publish  # noqa: PLC0415
        _web_publish._publish = lambda: None
        _live.HERE = Path(a.checkout).expanduser().resolve() if a.checkout else ROOT
        _released._OWN_REPO[:] = []
        unread: set[str] = set()
        if not a.github:
            def _offline(ref: str, now: float, gh_st: dict) -> tuple[bool, str]:
                unread.add(_checks.check_ref(ref))
                return False, "not read (no --github)"
            _checks.pr_merged = _offline
        out = _proofs.sweep_proofs(dry=True)
        out["unread"] = sorted(unread)
        return out


def describe(x: dict) -> str:
    act = {"closed": "would close", "ticked": "would tick", "told": "would tell the mover", "left": "would leave"}.get(str(x.get("action")), str(x.get("action")))
    pr = x.get("ref") or (f"PR #{x['pr']}" if x.get("pr") else "PR")
    ev = "closed unmerged" if x.get("dead") else "released" if x.get("kind") == "pr_released" else "merged"
    tail = {"closed": "the item (its only open step)", "ticked": "the step" + (", nobody told (every other open step waits on another PR)" if x.get("quiet") else f", and tell {x.get('mover') or 'its mover'} the next step: {x.get('next_step') or '(none)'}"),
            "told": (f"{x.get('mover') or 'its mover'}: the pull request was closed without a merge, so the step can never be ticked by it" if x.get("dead")
                     else f"{x.get('mover') or 'its mover'}: the step names more than the {'release' if x.get('kind') == 'pr_released' else 'merge'} or a condition, so it stays open"),
            "left": str(x.get("why") or "")}.get(str(x.get("action")), "")
    return f"{x.get('shown') or x.get('item')}  {act}  [{pr} {ev}]  step: {x.get('step') or '-'}  → {tail}  — {x.get('subject') or ''}"[:420]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="settle the open steps whose proof already happened (see this file's docstring); a dry run unless --apply")
    ap.add_argument("--dry-run", action="store_true", help="the default: write nothing")
    ap.add_argument("--apply", action="store_true", help="ask the running server to do it (client.py sweep-step-proof)")
    ap.add_argument("--github", action="store_true", help="read, from GitHub, the pull requests git cannot answer for")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--store")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--checkout")
    ap.add_argument("--state")
    a = ap.parse_args(argv)
    if a.apply and a.dry_run:
        print("backfill_step_proof: --apply and --dry-run exclude each other", file=sys.stderr)
        return 1
    if a.apply:
        if a.store or a.config or a.checkout or a.state or a.github:
            print("backfill_step_proof: --apply goes through the running server; --store, --config, --checkout, --state and --github only point a dry run at a copy", file=sys.stderr)
            return 1
        return subprocess.run([sys.executable, str(ROOT / "stackshot" / "fleet" / "client.py"), "sweep-step-proof"]).returncode
    ensure_env()
    d = run(a)
    rows = d.get("items") or []
    counts = {k: sum(1 for r in rows if r.get("action") == k) for k in ("closed", "ticked", "told", "left")}
    counts["items"] = len({r["item"] for r in rows})
    if a.json:
        print(json.dumps({"counts": counts, "head": d.get("head"), "good": d.get("good"), "unread": d.get("unread") or [], "items": rows}, indent=1, sort_keys=True))
        return 0
    print(f"dry run: nothing written, nobody told. last-good {str(d.get('good') or '-')[:7]}, checkout {str(d.get('head') or '-')[:7]}")
    for r in rows:
        print(describe(r))
    print(f"{counts['items']} items: {counts['closed']} to close, {counts['ticked']} to tick, {counts['told']} to tell, {counts['left']} left alone")
    if d.get("unread"):
        print(f"not read (git cannot say, no --github): {', '.join(d['unread'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
