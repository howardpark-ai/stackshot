"""ghmigrate.py — move a board store's open items onto GitHub Issues (the move itself is ghsync.migrate).

In id order, each open item becomes the repo's next issue (title, body with its marker; no labels, no history comment since an earlier change), its file moves to <letter>/<n>.json under the issue number, and its old id stays as an alias in
<store>/github.json. Closed items stay where they are. A second run creates nothing. Both --store and --repo are required:
the tool never takes them from the config, so a run on the live store is a deliberate one (a one-time cutover).

  ghmigrate.py --store <dir> --repo <owner/name> [--dry-run] [--limit N] [--pace S] [--token-file F] [--api URL]

The config (STACKSHOT_CONFIG) still supplies the instance name, timezone and board URL the bodies and comments carry, and
the letter ([github] issues_letter, default g). The publisher commits the moved files and the map at its next run; this tool
runs no git. Writes are paced ([github] min_interval_seconds, default 1.5 s; --pace overrides). When --repo is the config's
[github] issues_repo and [github] issues_repo_id is set, the calls go to /repositories/<id>/... (the id survives a transfer).
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import sys
from pathlib import Path

from stackshot.github import ghsync as _gh  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="move a board store's open items onto GitHub Issues")
    ap.add_argument("--store", required=True, help="the store directory (<letter>/<n>.json files)")
    ap.add_argument("--repo", required=True, help="owner/name of the board repo")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; create nothing, move nothing")
    ap.add_argument("--limit", type=int, default=0, help="create at most this many issues this run (0 = all)")
    ap.add_argument("--pace", type=float, default=None, help="seconds between two writes (default [github] min_interval_seconds)")
    ap.add_argument("--token-file", default="", help="a file with the token (default [github] token_file, else `gh auth token`)")
    ap.add_argument("--api", default="", help="the API base (default [github] api_url, else https://api.github.com)")
    a = ap.parse_args()
    store = Path(a.store).expanduser().resolve()
    if not store.is_dir():
        return f"no such store: {store}"
    tok = _gh.token(a.token_file) if a.token_file else _gh.token()
    if not tok and not a.dry_run:
        return "no token: set [github] token_file, pass --token-file, or sign in with `gh auth login`"
    name = a.repo.strip().strip("/")
    rid = _gh.repo_id() if name.lower() == _gh.repo().lower() else 0      # the configured issues repo: by [github] issues_repo_id when set
    gh = _gh.GitHub(name, a.api, tok, pace=a.pace, repo_id_=rid)
    try:
        r = _gh.migrate(store, gh, dry_run=a.dry_run, limit=a.limit)
    except _gh.GitHubDown as e:
        return f"GitHub is not answering ({e}); run again later: what was created is in the map and the markers, nothing is made twice"
    except _gh.GitHubError as e:
        return f"GitHub refused ({e})"
    for line in r["plan"]:
        print("  " + line)
    print(f"{'plan' if a.dry_run else 'done'}: {r['items']} open item(s); {r['created']} issue(s) created, {r['skipped']} already there, "
          f"{r['moved']} file(s) moved; {gh.writes} write(s) to GitHub")
    return 0


if __name__ == "__main__":
    sys.exit(main())
