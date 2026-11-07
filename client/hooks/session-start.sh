#!/usr/bin/env bash
# session-start.sh — the SessionStart hook: put the board's brief in front of the session, then show a page's keeper the Current
# state of its pages (pages.py keeper), both as plain text on stdout. Wired by `./stackshot client install`.
# The brief comes from the server through the client API with this machine's token (client.py get brief); on the server box,
# when the server cannot be reached, publish.py renders it from the store itself. Silent where neither works.
# Always exits 0: a hook that ends on a false test shows as "SessionStart hook error".
HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKOUT="$(cd "$HOOKS/../.." && pwd)"
. "$HOOKS/_python.sh"
[ -n "$PY" ] || exit 0
PAYLOAD="$(cat)"
if brief="$($PY "$CHECKOUT/client.py" get brief 2>/dev/null)"; then      # on a failure client.py prints its error on stdout: never shown
    printf '%s\n' "$brief"
else
    store="$($PY "$CHECKOUT/config.py" path paths.store 2>/dev/null)"
    [ -n "$store" ] && [ -d "$store" ] && $PY "$CHECKOUT/publish.py" brief 2>/dev/null
fi
# pages.py keeper answers with a hookSpecificOutput JSON envelope; one hook's stdout is either JSON or plain text, so the
# envelope is unwrapped and its context printed as text after the brief (a setup can run the two as separate hooks).
printf '%s' "$PAYLOAD" | $PY "$CHECKOUT/pages.py" keeper 2>/dev/null | $PY -c '
import json, sys
raw = sys.stdin.read()
try: print(json.loads(raw)["hookSpecificOutput"]["additionalContext"])
except Exception: sys.stdout.write(raw)
' 2>/dev/null || true
exit 0
