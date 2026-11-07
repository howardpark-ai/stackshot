#!/usr/bin/env bash
# project-page.sh <verb> — the page gate's hook entry: forwards to pages.py in this checkout (touch on PostToolUse of the
# connector's write tools, nag on UserPromptSubmit, check on Stop, keeper on SessionStart). Wired by `./stackshot client install`.
# The hook's JSON arrives on stdin and goes straight through. No Python 3.11 on this box: the hook does nothing (exit 0).
HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKOUT="$(cd "$HOOKS/../.." && pwd)"
. "$HOOKS/_python.sh"
[ -n "$PY" ] || exit 0
exec $PY "$CHECKOUT/pages.py" "$@"
