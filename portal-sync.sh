#!/usr/bin/env bash
# portal-sync.sh [server-id …] — ask the owner's MCP Portal (Cloudflare) to re-read an upstream's tool list.
# Default server: stackshot. Runs from stackshot-portal-sync.service after every stackshot (re)start,
# so a running claude.ai session behind the portal finds a new tool on its next search (Code Mode).
# Account, server id and token file: stackshot.toml [portal] (the token is never printed).
# Afterwards `connectors.py build` regenerates the connector catalog ([portal] catalog_file): the portal's entries
# joined with the CLI's connector names, which the page hooks read; a failure there is reported, never fatal to the sync.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"   # `claude` (the connector list) for the catalog build, also under the user unit
ACCT=$(python3 "$HERE/config.py" get portal.account_id)
TOK=$(cat "${CF_API_TOKEN_FILE:-$(python3 "$HERE/config.py" path portal.token_file)}")
DEFAULT_SID=$(python3 "$HERE/config.py" get portal.server_id)
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
for sid in "${@:-$DEFAULT_SID}"; do
  code=$(curl -sS -m 60 -o "$tmp" -w '%{http_code}' -X POST -H "Authorization: Bearer $TOK" \
    "https://api.cloudflare.com/client/v4/accounts/$ACCT/access/ai-controls/mcp/servers/$sid/sync" || echo 000)
  n=$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1])); r=d.get("result") or {}
print(len(r.get("tools_raw") or r.get("tools") or []))' "$tmp" 2>/dev/null || echo "?")
  echo "portal-sync: $sid http=$code tools=$n"
done
python3 "$HERE/connectors.py" build || echo "portal-sync: the connector catalog was not rebuilt (connectors.py build exited $?)"
