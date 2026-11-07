#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["google-auth-oauthlib>=1.2", "google-api-python-client>=2.150"]
#
# [tool.uv]
# exclude-newer = "2026-10-03T04:00:00Z"
# ///
"""One-time Google authorization for anchor-hub (read-only Drive + Gmail), one account at a time.

  anchor-hub-google-auth.py <label>     label = a key of stackshot.toml [anchor_hub] google_oauth_envs (picks the Workspace instance's
                                        OAuth client id/secret from its env file; same GCP project)

Run it THROUGH an SSH port-forward from the machine whose browser will sign in, so the loopback
redirect lands on the host and no code or token passes through a chat:
  ssh -t -L 8765:localhost:8765 <host> 'uv run --script <checkout>/anchor-hub-google-auth.py <instance>'
Then open the printed URL in that browser, sign in as the matching account, approve. Token lands in
<secrets>/anchor-hub/google/<email>.json (chmod 600; paths.secrets in stackshot.toml). Requires http://localhost:8765/ registered as an
authorized redirect URI on that OAuth client (register it once on the OAuth client).
"""
import os, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/userinfo.email", "openid"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as _cfg  # noqa: E402  (stackshot.toml: paths.secrets, anchor_hub.google_oauth_envs)
OUT = str(_cfg.secrets("anchor-hub", "google"))
ENVS = {str(k): str(v) for k, v in (_cfg.get("anchor_hub", "google_oauth_envs") or {}).items()}   # label → the Workspace instance's oauth.env
PORT = 8765

def main():
    if not ENVS:
        sys.exit("stackshot.toml [anchor_hub] google_oauth_envs names no Workspace instance (label = path to its oauth.env)")
    label = sys.argv[1] if len(sys.argv) > 1 else next(iter(ENVS))
    if label not in ENVS:
        sys.exit(f"unknown label {label!r}; known: {', '.join(ENVS)}")
    env = dict(l.split("=", 1) for l in open(os.path.expanduser(ENVS[label])).read().splitlines() if "=" in l and not l.startswith("#"))
    cfg = {"web": {"client_id": env["GOOGLE_OAUTH_CLIENT_ID"].strip(), "client_secret": env["GOOGLE_OAUTH_CLIENT_SECRET"].strip(),
                   "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}
    flow = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=f"http://localhost:{PORT}/")
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
    got = {}
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.end_headers()
            self.wfile.write(b"anchor-hub: authorized, you can close this tab." if "code" in q else b"anchor-hub: no code in callback")
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", PORT), H)
    print(f"\nOpen this URL in the browser on the machine you ran ssh from, signed in as the {label} account:\n\n{url}\n\nwaiting for the callback on localhost:{PORT} …", flush=True)
    srv.handle_request()
    if "code" not in got: sys.exit(f"callback had no code: {got.get('error')}")
    flow.fetch_token(code=got["code"])
    creds = flow.credentials
    email = build("oauth2", "v2", credentials=creds).userinfo().get().execute()["email"]
    os.makedirs(OUT, mode=0o700, exist_ok=True)
    path = os.path.join(OUT, f"{email}.json")
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(creds.to_json())
    print(f"stored refresh token for {email} → {path}  (scopes: drive.readonly, gmail.readonly)")

if __name__ == "__main__": main()
