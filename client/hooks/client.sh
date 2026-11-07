#!/usr/bin/env bash
# client.sh <register|seen|drain> — client.py's hook verbs, for a machine with no puller: register on SessionStart,
# seen on Stop, drain on UserPromptSubmit (prints what waits in the server's inbox, so it reaches the session with the prompt).
# Wired by `./stackshot client install --no-puller`. client.py answers within seconds and exits 0 whatever happened; no
# Python 3.11 on this box: the hook does nothing (exit 0).
HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKOUT="$(cd "$HOOKS/../.." && pwd)"
. "$HOOKS/_python.sh"
[ -n "$PY" ] || exit 0
exec $PY "$CHECKOUT/client.py" "$@"
