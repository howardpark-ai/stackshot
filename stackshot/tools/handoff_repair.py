"""tools/handoff_repair.py — the one-off repair of hand-off records that name a mover the item no longer has.

An item has one hand-off record (metadata.handoff, handoff.py). Until the record followed the mover, a mover that changed by any path but a session's own hand-off (a wake that made
the post-wake mover the mover, an event wake, a script's save, a close, a wait) left the old record open, naming a mover the item had left: `get` and the brief then said the item was
"handed to X, not yet taken" while Y moved it. The record follows the mover from now on (service/handoff.py `handoff_follow`, on every save); this repairs the ones already stored.

    tools/handoff_repair.py --store <copy>          the dry run (the default): reads the copy's items and prints every item whose OPEN record (nobody has taken it) names someone
                                                    other than the item's effective mover, with what the repair would do to it: end the record into the item's history. Writes nothing.
    tools/handoff_repair.py --store <copy> --apply  writes those endings into the COPY (a test of the repair itself).
    tools/handoff_repair.py --live                  the dry run against the live store: read only, allowed while the server runs.
    tools/handoff_repair.py --live --apply          refused while the server is running (the user unit stackshot.service is active): stop the service, or just let it start: the server runs
                                                    this same repair itself once on every start (service/handoff.py `handoff_repair_pass`, idempotent, before any thread starts), so this is only for
                                                    a repair by hand with the service stopped.

The rehearsal is the --store run on a copy: its dry run lists what the start-time pass will end, and --apply on the copy shows the result.

<copy> is a directory made from the live store: a copy of the live stackshot.toml with every [paths] entry (repo, store, markdown, brain, state, secrets) rewritten to a place inside the copy,
the store kept inside `repo` (importing the server fails otherwise: with repo = <copy>, the items go in <copy>/store), and [github] sync = false. A copy of the store alone is not enough,
and a config that still points at the live paths is refused here. A dry run against the live store (--live without --apply) is read only too. Nothing new is recorded: no notice was ever
sent to the mover the item holds now, so a fresh record would show a hand-off that never happened.
Exit 0; 1 when the arguments are wrong or --live --apply is refused."""
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
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ensure_env() -> None:
    """Importing server.py needs fastmcp: run again in the tests' uv environment (as tests/run-suite does) when bare python3 has none."""
    try:
        import fastmcp  # noqa: F401, PLC0415
        return
    except ImportError:
        pass
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    env = dict(os.environ)
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "stackshot" / "test-venv"))
    if not Path(uv).exists():
        raise SystemExit("handoff_repair: fastmcp is missing and uv was not found")
    os.execve(uv, [uv, "run", "--locked", "--project", str(ROOT), "--only-group", "tests", "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


def service_running() -> bool | None:
    """Is the server's user unit stackshot.service active? True / False; None when systemd cannot say (no systemctl, or it did not answer): the caller treats that as running."""
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "stackshot.service"], timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode == 0 if r.returncode in (0, 3, 4) else None      # 0 active; 3 inactive; 4 no such unit on this box


def point_at_copy(store: str) -> Path:
    """Aim every reader of this process at the copy before anything imports config: <copy>/stackshot.toml must keep every path of [paths] inside <copy>, may not be the live config's
    store and may not mirror to GitHub. → the copy's directory."""
    d = Path(store).expanduser().resolve()
    cfg_path = d / "stackshot.toml"
    if not cfg_path.is_file():
        raise SystemExit(f"--store {d}: no stackshot.toml in it; a copy is a directory with the store and its own stackshot.toml")
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
        raise SystemExit(f"--store {d}: [github] sync is on in the copy's config; set it to false")
    os.environ["STACKSHOT_CONFIG"] = str(cfg_path)
    os.environ["STACKSHOT_AUTH"] = "off"
    os.environ.pop("STACKSHOT_URL", None)
    return d


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="handoff_repair.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", help="a COPY of the live store (a directory with its own stackshot.toml)")
    ap.add_argument("--live", action="store_true", help="work on the live store (the config this process is pointed at)")
    ap.add_argument("--apply", action="store_true", help="write the endings (default: a dry run)")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    a = ap.parse_args(argv)
    if bool(a.store) == bool(a.live):
        print("handoff_repair: pass exactly one of --store <copy> and --live", file=sys.stderr)
        return 1
    if a.live and a.apply:
        running = service_running()
        if running is not False:
            print("handoff_repair: --live --apply is refused while the stackshot server may be running (" + ("systemctl could not say" if running is None else "stackshot.service is active")
                  + "): the item lock does not reach a second process. Stop the service, or let it start: the server runs this repair itself on every start. --store <copy> rehearses it.", file=sys.stderr)
            return 1
    ensure_env()      # first: it may start this process again, and the copy's config must not be taken for the live one on the second start
    if a.store:
        point_at_copy(a.store)
    elif not a.apply:
        os.environ.setdefault("STACKSHOT_AUTH", "off")
    from stackshot.web import server  # noqa: PLC0415,F401  (importing the server installs the hooks the hand-off passes use)
    from stackshot.service import handoff  # noqa: PLC0415
    rows = handoff.handoff_repair(apply=a.apply)
    if a.json:
        print(json.dumps(rows, indent=1, default=str))
        return 0
    verb = "ended" if a.apply else "would end"
    by: dict[str, int] = {}
    for r in rows:
        key = f"{r['status']}, mover {'none' if not r['mover'] else 'set'}"
        by[key] = by.get(key, 0) + 1
        print(f"{r['shown']}: {verb} the record to {r['record_to']!r} (from {r['record_from']!r}, {'delivered' if r['delivered'] else 'not delivered'}"
              f"{', recovery asked' if r['recovery'] else ''}); the item's mover is {r['mover'] or 'none'} ({r['status']})")
    print(f"{len(rows)} item(s) {verb} a stale record" + ("".join(f"\n  {k}: {n}" for k, n in sorted(by.items())) if rows else "") + ("" if a.apply else "\n(dry run: nothing was written; --apply writes)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
