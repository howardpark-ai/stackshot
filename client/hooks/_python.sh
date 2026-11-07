# _python.sh — sourced by the hooks: set $PY to a Python 3.11+ (STACKSHOT_PYTHON wins; then python3, python, py -3).
# Plain bash, no GNU-only flags: it runs under Git Bash on Windows too, where `python3` can be the Microsoft Store alias.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
PY=""
for c in ${STACKSHOT_PYTHON:+"$STACKSHOT_PYTHON"} python3 python "py -3"; do
    if $c -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then PY="$c"; break; fi
done
