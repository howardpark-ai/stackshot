"""tools/backfill_contact.py — the one-off fill-in of every open item's contact (contact.py: the front agent the person the board is for talks to about the item).

An item made before the field existed has none. The rule (contact.plan): an open item without a live contact gets its creator when the creator was a front agent (a user-facing agent of any
project), else its project's -main agent; an item whose stored contact is no front agent any more gets the -main agent too; a project that names no -main agent leaves the item without one;
a closed item is a record and is left. The dry run runs the server's own pass in-process on a COPY of the store, so nothing live is read for writing or written:

  tools/backfill_contact.py                      dry run (the default, also `--dry-run`): the counts by rule, then one line per item that would change; writes nothing, needs no server
  tools/backfill_contact.py --json               the same as JSON ({"counts", "items": [{item, project, rule, was, to}]})
  tools/backfill_contact.py --store DIR          read the items from DIR (a copy of the store, `projects.json` beside them) instead of [paths] store
  tools/backfill_contact.py --config FILE        the stackshot.toml to read (default: $STACKSHOT_CONFIG, then ~/.config/stackshot/stackshot.toml); only its [paths] and the fleet's session registry are used
  tools/backfill_contact.py --apply              write them: asks the running server to do it (`client.py backfill-contact --apply`, this machine's token), one filing write per item, as the
                                                 author `migration`; no state, clock, hand-off or page moves. Refused together with --store/--config (those only point a dry run at a copy).

The registry that tells a front agent from a background one is the store's `projects.json` (the page registry), and the sessions are resolved by the fleet tool's session registry under
[client] session_links, read only. Exit 0 · 1 when --apply could not run. Python 3.12 or later; it runs itself in the tests' uv environment when fastmcp is missing."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from stackshot.tools import backfill_step_proof as _bsp  # noqa: E402  — the sibling dry run: the throwaway config and the uv environment are the same


def ensure_env() -> None:
    """Re-run this script in the tests' uv environment when fastmcp (which the server imports) is missing (as backfill_step_proof.py does, for this file)."""
    try:
        import fastmcp  # noqa: F401, PLC0415
        return
    except ImportError:
        pass
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    env = dict(os.environ)
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "stackshot" / "test-venv"))
    if not Path(uv).exists():
        raise SystemExit("backfill_contact: fastmcp is missing and uv was not found: run it from the tests' environment, or install uv")
    os.execve(uv, [uv, "run", "--locked", "--project", str(ROOT), "--only-group", "tests", "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


def run(a: argparse.Namespace) -> dict:
    toml, _cfg = _bsp.config_text(a.config)
    real = _bsp.paths_of(toml)
    src = Path(a.store).expanduser() if a.store else Path(os.path.expanduser(real.get("store", "~/stackshot-data/board-data")))
    if not src.is_dir():
        raise SystemExit(f"backfill_contact: the store {src} is not a folder")
    with tempfile.TemporaryDirectory(prefix="contactfill-") as t:
        tmp = Path(t)
        store = tmp / "store"
        shutil.copytree(src, store, ignore=shutil.ignore_patterns(".git"))       # a copy: the dry run reads this one
        for d in ("state", "fleet", "secrets", "brain"):
            (tmp / d).mkdir(parents=True, exist_ok=True)
        (tmp / "stackshot.toml").write_text(_bsp.throwaway_config(toml, tmp, store), encoding="utf-8")
        os.environ.update(STACKSHOT_CONFIG=str(tmp / "stackshot.toml"), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(tmp / "fleet"))
        os.environ.pop("STACKSHOT_URL", None)
        import logging
        logging.disable(logging.INFO)
        from stackshot.web import server  # noqa: PLC0415
        from stackshot.web import publish as _web_publish  # noqa: PLC0415
        _web_publish._publish = lambda: None
        return server._contact_backfill(dry=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fill in the contact of every open item (see this file's docstring); a dry run unless --apply")
    ap.add_argument("--dry-run", action="store_true", help="the default: write nothing")
    ap.add_argument("--apply", action="store_true", help="ask the running server to do it (client.py backfill-contact --apply)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--store")
    ap.add_argument("--config", type=Path)
    a = ap.parse_args(argv)
    if a.apply and a.dry_run:
        print("backfill_contact: --apply and --dry-run exclude each other", file=sys.stderr)
        return 1
    if a.apply:
        if a.store or a.config:
            print("backfill_contact: --apply goes through the running server; --store and --config only point a dry run at a copy", file=sys.stderr)
            return 1
        return subprocess.run([sys.executable, str(ROOT / "stackshot" / "fleet" / "client.py"), "backfill-contact", "--apply"]).returncode
    ensure_env()
    d = run(a)
    if a.json:
        print(json.dumps({"counts": d["counts"], "items": d["items"]}, indent=1, sort_keys=True))
        return 0
    print("dry run: nothing written, nobody told")
    for r in d["items"]:
        print(f"{r['item']}  {r['rule']}  {r['was'] or '-'} → {r['to'] or '-'}  ({r['project']})")
    print("counts by rule: " + ", ".join(f"{k} {v}" for k, v in d["counts"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
