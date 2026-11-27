"""`python -m stackshot.frontdoor`: run the front door (or, with --check, read its settings and the files it reads, and serve nothing).

The settings are the `[frontdoor]` table of the instance's config file (`$STACKSHOT_CONFIG`, else the usual places: see docs/configuration.md). Run it with the
server extra: `uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor`.

Exit status: 0 served until stopped (or, with --check, could start and every file it reads at a request can be used), 2 the front door cannot start, or with
--check a secret, a token file or the members file is missing or cannot be used (the reason is on standard error; no secret is ever in it). Serving does not
wait for those files: it reads them at each request.
"""
from __future__ import annotations

import logging
import sys

from stackshot.core import config as _cfg, frontdoor_config as _fc
from stackshot.frontdoor import config as _config


def main(argv: list[str]) -> int:
    check = "--check" in argv
    if [a for a in argv if a != "--check"]:
        print("usage: python -m stackshot.frontdoor [--check]", file=sys.stderr)
        return 2
    settings, problems = _fc.parse()
    for line in problems:
        print(f"note: {line}", file=sys.stderr)
    try:
        settings = _config.load()
    except _config.ConfigError as e:
        print(str(e).splitlines()[0], file=sys.stderr)
        return 2
    if check:
        bad = _config.unusable_files(settings)
        if bad:
            print(f"the front door cannot work as set: {'; '.join(bad)}", file=sys.stderr)
            return 2
        print(f"front door: {settings.host}:{settings.port}, identity header {settings.identity_header}, "
              f"backends {', '.join(f'{b.kind} {b.name}' for b in settings.backends)} (config {_cfg.PATH})")
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from stackshot.frontdoor import app
    app.serve(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
