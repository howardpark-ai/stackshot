#!/usr/bin/env python3
"""tools/restore_close_descriptions.py — the one-off repair of the descriptions that a close replaced.

Until a close kept the description, `complete` told the closing session to rewrite the description to the end state, so a closed item no longer said what it was about; the old
text survives only in the item's History (the store's git). A close now stores its summary in `metadata.outcome_text` and leaves the description alone. This restores the
items closed in the last 14 days (`--days` changes it): the description of the revision just before the close goes back as the description, and the text the close wrote
moves into the outcome text. Left as they are: an item that already has an outcome text (counted as "has outcome text"), one whose description is already the earlier one (a
close that did not rewrite it), one whose description was edited after the close (that edit stays), and one with no earlier revision. Clocks, mover and every other field stay as they were.

    tools/restore_close_descriptions.py --store <copy>          the dry run (the default): reads the copy's items and its git, prints every item it would restore, writes nothing.
    tools/restore_close_descriptions.py --store <copy> --apply  writes the restores into the COPY (a rehearsal of the repair itself).
    tools/restore_close_descriptions.py --live                  the dry run against the live store: read only, allowed while the server runs.
    tools/restore_close_descriptions.py --live --apply          refused while the server is running (the user unit stackshot.service is not `inactive` or `failed`, or systemd cannot say): the item lock
                                                                does not reach a second process. Stop the service, run this, start it again.

It is a tool and not a pass at server start on purpose: it runs once, over a window of days that the history of a repository reaches only while the store is committed, and a
description the owner reads should change when someone has looked at the dry run first, not at whichever restart comes next. It is safe to run twice (a restored item is left
by the next run), so a run that was cut short is simply run again.

<copy> is a directory made from the live store's repository (the store is a folder of that git repository, and the history is read from its commits): the repository with its
.git, and its own stackshot.toml with every [paths] entry inside the copy and [github] sync = false (the same shape tools/migrate_model.py takes). A dry run against the live
store (--live without --apply) is read only too. Exit 0; 1 when the arguments are wrong or --live --apply is refused."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
        raise SystemExit("restore_close_descriptions: fastmcp is missing and uv was not found")
    os.execve(uv, [uv, "run", "--locked", "--project", str(ROOT / "tests"), "python", str(Path(__file__).resolve()), *sys.argv[1:]], env)


def service_running() -> bool | None:
    """Is the server's user unit stackshot.service stopped for good? False only when its ActiveState is `inactive` or `failed` (safe to write); True for `active`, `activating`,
    `deactivating` and the other in-between states, where a server may still hold the store (`is-active` answers non-zero for those too, so the state itself is read); None when
    systemd cannot say (no systemctl, no answer, or a state that is none of these): the caller treats that as running."""
    try:
        r = subprocess.run(["systemctl", "--user", "show", "-p", "ActiveState", "--value", "stackshot.service"], timeout=15, check=False, capture_output=True, text=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    state = r.stdout.strip()
    if state in ("inactive", "failed"):
        return False
    return True if state in ("active", "activating", "deactivating", "reloading", "maintenance", "refreshing") else None


def point_at_copy(store: str) -> Path:
    """Aim every reader of this process at the copy before anything imports config: <copy>/stackshot.toml must keep every path of [paths] inside <copy>, may not be the live config's
    store and may not mirror to GitHub. → the copy's directory."""
    d = Path(store).expanduser().resolve()
    cfg_path = d / "stackshot.toml"
    if not cfg_path.is_file():
        raise SystemExit(f"--store {d}: no stackshot.toml in it; a copy is a directory with the store's repository and its own stackshot.toml")
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


def short(text: str, n: int = 80) -> str:
    """A description on one line, cut to n characters with an ellipsis."""
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="restore_close_descriptions.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", help="a COPY of the live store's repository (a directory with its own stackshot.toml)")
    ap.add_argument("--live", action="store_true", help="work on the live store (the config this process is pointed at)")
    ap.add_argument("--apply", action="store_true", help="write the restores (default: a dry run)")
    ap.add_argument("--days", type=float, default=14.0, help="restore the items closed in the last DAYS days (default 14)")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON")
    a = ap.parse_args(argv)
    if bool(a.store) == bool(a.live):
        print("restore_close_descriptions: pass exactly one of --store <copy> and --live", file=sys.stderr)
        return 1
    if a.days <= 0:
        print("restore_close_descriptions: --days must be above 0", file=sys.stderr)
        return 1
    if a.live and a.apply:
        running = service_running()
        if running is not False:
            print("restore_close_descriptions: --live --apply is refused while the stackshot server may be running (" + ("systemctl could not say" if running is None else "stackshot.service is active, starting or stopping")
                  + "): the item lock does not reach a second process. Stop the service, run this again, start the service. --store <copy> rehearses it.", file=sys.stderr)
            return 1
    ensure_env()      # first: it may start this process again, and the copy's config must not be taken for the live one on the second start
    if a.store:
        point_at_copy(a.store)
    elif not a.apply:
        os.environ.setdefault("STACKSHOT_AUTH", "off")
    sys.path.insert(0, str(ROOT))
    import server  # noqa: PLC0415
    rows, skipped = server._close_description_repair(apply=a.apply, days=a.days)
    if a.json:
        print(json.dumps({"rows": rows, "skipped": skipped}, indent=1, default=str, ensure_ascii=False))
        return 0
    verb = "restored" if a.apply else "would restore"
    for r in rows:
        print(f"{r['shown']}: {verb} the description\n    now:    {short(r['before'])}\n    before: {short(r['after'])}"
              + "\n    the text the close wrote becomes the outcome text")
    from close_repair import SKIP_WHY  # noqa: PLC0415
    left = "".join(f"\n  {SKIP_WHY.get(k, k)}: {n}" for k, n in sorted(skipped.items()))
    print(f"{len(rows)} item(s) {verb} their description (each gets an outcome text from the close's description)" + (f"\nleft as they are:{left}" if left else "")
          + ("" if a.apply else "\n(dry run: nothing was written; --apply writes)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
