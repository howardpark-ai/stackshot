"""Scenario test for how long the board's own sign-in lasts and what it asks of the person (server.py, ui/render.py, ui/runners.py) — fixture data, no live store, no network.

Covers:
  * a visit renews the session: the cookie of a signed-in person who opens a page (a browser navigation) is written again with the full days from now, on a clock the test sets; a
    session that was renewed every few weeks never runs out, one left alone for longer than its days does; the cookie is not rewritten on every page load (only after an hour of its
    days are used), not by a script's fetch (a tab left polling does not keep a session alive), not on the sign-in's own /ui/ routes (logout), not on an error;
  * a session that has run out does not renew, nor does a forged one, nor one of an address that is no longer allowed;
  * the Allow page: the board's own sign-in (the client the board registered for itself, its own callback) goes from /authorize to Google with no Allow page, and the consent binding
    cookie is set; another client (claude.ai's callback), and a client that registers itself with the board's callback, still get the Allow page;
  * a lapsed tab does not retry: a script's request (Sec-Fetch-Mode other than navigate) without a session is a plain 401, never a redirect to the sign-in, and /ui/login answers it with
    a 401 too, starting nothing (no OAuth client registered, no flow cookie); a page the browser opens still goes to the sign-in. The page's polling script, run in node on a stub page,
    stops asking after the first 401 (focus, online, a timer: no more requests) and shows "Signed out"; the Runners page's script stops too.

    tests/run-suite ui_signin         -> exit 0 / 1"""
import json, logging, os, pathlib, re, shutil, subprocess, sys, time
from urllib.parse import parse_qs, urlparse

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="uisessiontest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("base_url", "https://stackshot.test")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^ui_open = (true|false)", "ui_open = false", toml); assert n == 1
toml, n = re.subn(r"(?m)^allowed_emails = .*$", 'allowed_emails = ["you@example.com"]', toml); assert n == 1
toml, n = re.subn(r'(?m)^mode = "google"', 'mode = "google"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com", STACKSHOT_GOOGLE_CLIENT_SECRET="test-secret")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
for d in ("store/a", "state/site", "secrets"): (T / d).mkdir(parents=True)          # the rest is made where it is first written
(T / "names.tsv").write_text("# hostname\tfleet\tletter\n")
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""), flush=True)

from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.auth import signin as _signin
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
from starlette.testclient import TestClient

EMAIL, DAY = "you@example.com", 86400
NAV, FETCH = {"Sec-Fetch-Mode": "navigate"}, {"Sec-Fetch-Mode": "cors"}
T0 = 1_800_000_000.0                                    # the test's clock: a fixed moment the sign-in code reads through _signin._ui_now
CLOCK = [T0]
_signin._ui_now = lambda: CLOCK[0]
DAYS = _signin._ui_days()
def cookie(email=EMAIL, exp=None): return _signin._ui_sign(json.dumps({"email": email, "exp": (CLOCK[0] + DAYS * DAY) if exp is None else exp}))
def set_cookies(r, name):
    """The Set-Cookie lines of a response that set `name` (a deletion included)."""
    return [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith(name + "=")]
def renewed(r):
    """The expiry the response's session cookie carries, None when it set none."""
    ls = [v for v in set_cookies(r, "stackshot_ui") if "max-age=0" not in v.lower() and not v.startswith("stackshot_ui=;") and not v.startswith('stackshot_ui="";')]
    return json.loads(_signin._ui_unsign(ls[0].split(";")[0].split("=", 1)[1].strip('"')))["exp"] if ls else None

app = server.mcp.http_app()
with TestClient(app) as c:
    # ============================================================= 1. a visit renews the session
    check("the session is 30 days by default (the test reads the setting, not a number)", DAYS == 30, DAYS)
    old = cookie(exp=T0 + 20 * DAY)                      # signed in 10 days ago
    r = c.get("/", cookies={"stackshot_ui": old}, headers=NAV, follow_redirects=False)
    check("a visit (a browser opening the page) renews the session: the cookie is written again, 30 days from now", r.status_code == 200 and renewed(r) == T0 + DAYS * DAY, (r.status_code, renewed(r)))
    attrs = (set_cookies(r, "stackshot_ui") or [""])[0].lower()
    check("…with the attributes the sign-in gave it (HttpOnly, Secure, SameSite=Lax, the whole site, 30 days)", "httponly" in attrs and "secure" in attrs and "samesite=lax" in attrs
          and "path=/" in attrs and f"max-age={DAYS * DAY}" in attrs, attrs)
    check("…for the same address", bool(set_cookies(r, "stackshot_ui")) and json.loads(_signin._ui_unsign(set_cookies(r, "stackshot_ui")[0].split(";")[0].split("=", 1)[1]))["email"] == EMAIL)
    r = c.get("/", cookies={"stackshot_ui": old}, follow_redirects=False)
    check("a client that says nothing about how it opens the page (a tool) is a visit too", renewed(r) == T0 + DAYS * DAY, renewed(r))
    r = c.get("/", cookies={"stackshot_ui": cookie(exp=T0 + DAYS * DAY - 600)}, headers=NAV, follow_redirects=False)
    check("a session renewed ten minutes ago is not written again (an hour of its days has to be used first)", r.status_code == 200 and renewed(r) is None, renewed(r))
    r = c.get("/", cookies={"stackshot_ui": cookie(exp=T0 + DAYS * DAY - 7200)}, headers=NAV, follow_redirects=False)
    check("…two hours old is", renewed(r) == T0 + DAYS * DAY, renewed(r))
    r = c.get("/render-stamp", cookies={"stackshot_ui": old}, headers=FETCH, follow_redirects=False)
    check("a script's fetch (the open tab's polling) does not renew: a tab left open does not keep a session alive by itself", r.status_code in (200, 503) and renewed(r) is None, (r.status_code, renewed(r)))
    r = c.get("/ui/logout", cookies={"stackshot_ui": old}, headers=NAV, follow_redirects=False)
    check("signing out is not undone by the renewal (the /ui/ routes are left alone)", r.status_code == 200 and renewed(r) is None and set_cookies(r, "stackshot_ui"), set_cookies(r, "stackshot_ui"))
    r = c.get("/items/nothing-here", cookies={"stackshot_ui": old}, headers=NAV, follow_redirects=False)
    check("a page that is an error (404) does not renew", r.status_code >= 400 and renewed(r) is None, (r.status_code, renewed(r)))
    r = c.get("/favicon.svg?v=1", cookies={"stackshot_ui": old}, headers=NAV, follow_redirects=False)
    check("a public file (the icon) carries no cookie", r.status_code == 200 and not set_cookies(r, "stackshot_ui"), dict(r.headers))
    r = c.get("/", headers=NAV, follow_redirects=False)
    check("nobody signed in: the sign-in, and no cookie", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2F" and not set_cookies(r, "stackshot_ui"))

    # a person who visits every three weeks stays signed in for months; one who is away longer than the days is asked again
    ck, seen = cookie(), []
    for visit in range(1, 8):                                       # seven visits, 21 days apart: 147 days in all
        CLOCK[0] = T0 + visit * 21 * DAY
        r = c.get("/", cookies={"stackshot_ui": ck}, headers=NAV, follow_redirects=False)
        seen.append(r.status_code)
        got = set_cookies(r, "stackshot_ui")
        if got: ck = got[0].split(";")[0].split("=", 1)[1].strip('"')
    check("visits every 21 days for 147 days: signed in at each (the 30 days restart at each visit)", seen == [200] * 7, seen)
    CLOCK[0] += (DAYS + 1) * DAY
    r = c.get("/", cookies={"stackshot_ui": ck}, headers=NAV, follow_redirects=False)
    check("…and 31 days away from the board: the session has run out, and the visit goes to the sign-in without renewing it", r.status_code == 302 and r.headers["location"].startswith("/ui/login") and renewed(r) is None, (r.status_code, r.headers.get("location")))
    CLOCK[0] = T0

    # ============================================================= 2. what does not renew
    r = c.get("/", cookies={"stackshot_ui": cookie(exp=T0 - 5)}, headers=NAV, follow_redirects=False)
    check("a session that has run out is not renewed by a visit: the sign-in, and no cookie", r.status_code == 302 and renewed(r) is None and not set_cookies(r, "stackshot_ui"))
    good = cookie(exp=T0 + 20 * DAY)
    forged = good[:-1] + ("0" if good[-1] != "0" else "1")
    r = c.get("/", cookies={"stackshot_ui": forged}, headers=NAV, follow_redirects=False)
    check("a forged cookie is not renewed", r.status_code == 302 and renewed(r) is None)
    r = c.get("/", cookies={"stackshot_ui": cookie("left@example.com", T0 + 20 * DAY)}, headers=NAV, follow_redirects=False)
    check("a cookie of an address that is no longer allowed is not renewed", r.status_code == 302 and renewed(r) is None)
    legacy = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": T0 + 25 * DAY}))                # the cookie as it was written before (email and exp only) is read and renewed
    r = c.get("/", cookies={"stackshot_ui": legacy}, headers=NAV, follow_redirects=False)
    check("a cookie written by the earlier release still works and is renewed", r.status_code == 200 and renewed(r) == T0 + DAYS * DAY, (r.status_code, renewed(r)))
    server._cfg.CFG["auth"]["ui_open"] = True
    r = c.get("/", cookies={"stackshot_ui": old}, headers=NAV, follow_redirects=False)
    check("ui_open true (an access proxy decides who reaches the board): no session cookie is written", r.status_code == 200 and not set_cookies(r, "stackshot_ui"))
    server._cfg.CFG["auth"]["ui_open"] = False

    # ============================================================= 3. the Allow page
    def ui_http(method, path, data, form=False):
        r = c.post(path, data=data) if form else c.post(path, json=data)
        try: return r.status_code, r.json()
        except Exception: return r.status_code, {}
    _signin._ui_http = ui_http
    _signin._UI_CLIENT.clear()
    r = c.get("/ui/login?next=/projects", headers=NAV, follow_redirects=False)
    auth_url = r.headers.get("location", "")
    r = c.get(auth_url.replace("https://stackshot.test", ""), follow_redirects=False)
    consent_url = r.headers.get("location", "")
    check("the board's sign-in: /authorize hands on to the server's /consent step", r.status_code == 302 and "/consent?txn_id=" in consent_url, (r.status_code, consent_url[:100]))
    r = c.get(consent_url.replace("https://stackshot.test", ""), headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False)
    check("…which goes on to Google with no Allow page (also when the board was reached from a link on another site)", r.status_code == 302 and r.headers.get("location", "").startswith("https://accounts.google.com/"), (r.status_code, r.headers.get("location", "")[:80], r.text[:100]))
    check("…and sets the consent binding cookie that the Google callback checks", any("consent_binding" in v.lower() or "binding" in v.lower() for v in [h for k, h in r.headers.multi_items() if k == "set-cookie"]),
          [h.split("=")[0] for k, h in r.headers.multi_items() if k == "set-cookie"])
    txn_id = parse_qs(urlparse(consent_url).query)["txn_id"][0]
    r2 = c.get("/auth/callback?code=x&state=" + txn_id, follow_redirects=False)
    check("…and the Google callback of a browser without that cookie is refused (the board's flow keeps the binding)", r2.status_code == 403, (r2.status_code, r2.text[:100]))

    def authorize(client_id, redirect_uri):
        q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "code_challenge": "x" * 43, "code_challenge_method": "S256", "state": "s1", "scope": "openid"}
        from urllib.parse import urlencode
        a = c.get("/authorize?" + urlencode(q), follow_redirects=False)
        loc = a.headers.get("location", "")
        return a, (c.get(loc.replace("https://stackshot.test", ""), follow_redirects=False) if "/consent?txn_id=" in loc else None)
    cl = c.post("/register", json={"client_name": "A connector", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"], "grant_types": ["authorization_code"],
                                    "response_types": ["code"], "token_endpoint_auth_method": "none"})
    a, ct = authorize(cl.json().get("client_id", ""), "https://claude.ai/api/mcp/auth_callback")
    check("another client (a connector) still gets the Allow page", ct is not None and ct.status_code == 200 and "Allow Access" in ct.text, (cl.status_code, a.status_code, ct and ct.status_code))
    fake = c.post("/register", json={"client_name": "stackshot board", "redirect_uris": ["https://stackshot.test/ui/callback"], "grant_types": ["authorization_code"],
                                      "response_types": ["code"], "token_endpoint_auth_method": "none"})
    a, ct = authorize(fake.json().get("client_id", ""), "https://stackshot.test/ui/callback")
    check("…and so does a client that registers itself under the board's name with the board's callback", fake.status_code in (200, 201) and ct is not None and ct.status_code == 200 and "Allow Access" in ct.text,
          (fake.status_code, a.status_code, ct and ct.status_code, ct and ct.text[:80]))
    check("the board's own client is told apart by the id it registered, not by its name or callback", _signin._ui_is_board_client(_signin._UI_CLIENT["id"], "https://stackshot.test/ui/callback")
          and not _signin._ui_is_board_client(fake.json().get("client_id", "x"), "https://stackshot.test/ui/callback")
          and not _signin._ui_is_board_client(_signin._UI_CLIENT["id"], "https://claude.ai/api/mcp/auth_callback")
          and not _signin._ui_is_board_client("", "https://stackshot.test/ui/callback"))

    # ============================================================= 4. a lapsed tab does not retry
    _signin._UI_CLIENT.clear()
    regs = []
    _signin._ui_http = lambda *a, **k: (regs.append(a), ui_http(*a, **k))[1]
    r = c.get("/render-stamp", headers=FETCH, follow_redirects=False)
    check("a script's request with no session (the open tab's poll) is a plain 401 with the text, not a redirect to the sign-in", r.status_code == 401 and "location" not in r.headers
          and "signed out" in r.text and r.headers.get("cache-control") == "no-store", (r.status_code, dict(r.headers)))
    r = c.get("/runners.json", headers=FETCH, follow_redirects=False); r2 = c.get("/audit/status", headers={"Sec-Fetch-Mode": "same-origin"}, follow_redirects=False)
    check("…the same for the Runners page's poll and the audit status", r.status_code == 401 and r2.status_code == 401, (r.status_code, r2.status_code))
    r = c.get("/render-stamp", cookies={"stackshot_ui": cookie(exp=T0 - 5)}, headers=FETCH, follow_redirects=False)
    check("…and for a session that has run out", r.status_code == 401)
    r = c.get("/ui/login?next=/", headers=FETCH, follow_redirects=False)
    check("/ui/login asked by a script starts nothing: 401, no OAuth client registered, no flow cookie, no redirect", r.status_code == 401 and not regs and not set_cookies(r, "stackshot_ui_flow") and "location" not in r.headers, (r.status_code, regs, dict(r.headers)))
    r = c.get("/", headers=NAV, follow_redirects=False); r2 = c.get("/ui/login?next=/", headers=NAV, follow_redirects=False)
    fl = set_cookies(c.get("/ui/login?next=/", headers=NAV, follow_redirects=False), "stackshot_ui_flow")
    check("the sign-in's flow cookie runs ten minutes on the same clock the callback reads", bool(fl) and json.loads(_signin._ui_unsign(fl[0].split(";")[0].split("=", 1)[1].strip('"')))["exp"] == T0 + 600, fl)
    check("a page the browser opens still goes to the sign-in, and the sign-in starts", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2F" and r2.status_code == 302 and set_cookies(r2, "stackshot_ui_flow") and regs)
    r = c.get("/render-stamp", cookies={"stackshot_ui": cookie()}, headers=FETCH, follow_redirects=False)
    check("a script's request with a good session is served as before", r.status_code in (200, 503), r.status_code)
    r = c.get("/receivers.json", headers=FETCH, follow_redirects=False)
    check("the receivers poll with no session is a 401 too", r.status_code == 401, r.status_code)
    HOME = c.get("/", cookies={"stackshot_ui": cookie()}, headers=NAV, follow_redirects=False).text          # the page as drawn, for its scripts

# ================================================================= 5. the page's scripts, run
import stackshot.web.ui.render as R; import stackshot.web.ui.runners as RN
NODE = shutil.which("node")
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(0, 'utf8');
const answers = JSON.parse(process.argv[1]);            // the status the stub answers, per call, then the last one repeats
const calls = [], timers = [], listeners = {}, docListeners = {}, events = [];
function el() { return new Proxy(function(){}, { get: (t, k) => k === 'className' ? (t.className || '') : k === 'hidden' ? !!t.hidden : (k in t ? t[k] : (k === 'addEventListener' ? () => {} : k === 'querySelector' ? () => el() : k === 'getAttribute' ? () => null : k === 'content' ? '100' : () => el())), set: (t, k, v) => { t[k] = v; return true; } }); }
const conn = el(); conn.className = 'conn'; const connState = () => conn.className + '|' + (conn.hidden ? 'hidden' : 'shown');
const doc = { querySelector: (s) => /stackshot-rendered/.test(s) ? { content: '100' } : /stackshot-shell|stackshot-blocks/.test(s) ? { content: 'x' } : null, querySelectorAll: () => [],
  getElementById: (id) => id === 'conn' ? conn : el(), addEventListener: (n, f) => { (docListeners[n] = docListeners[n] || []).push(f) }, dispatchEvent: (e) => { events.push(e.type); (docListeners[e.type] || []).forEach(f => f(e)); return true }, activeElement: null, hidden: false };
const win = { addEventListener: (n, f) => { (listeners[n] = listeners[n] || []).push(f) }, scrollY: 0, getSelection: () => '' };
let i = 0;
const ctx = { document: doc, window: win, location: { pathname: '/', search: '', reload() {} }, Event: function(n) { this.type = n }, sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  DOMParser: function() { this.parseFromString = () => ({}) }, Date, JSON, Object, String, Math, Promise, isNaN, parseInt,
  fetch: (u) => { calls.push(u); const st = answers[Math.min(i++, answers.length - 1)]; return Promise.resolve({ ok: st >= 200 && st < 300, status: st, redirected: false, json: () => Promise.resolve({ ts: 100 }), text: () => Promise.resolve('') }) },
  setTimeout: (f, ms) => { timers.push([f, ms]); return timers.length }, clearTimeout: () => {}, setInterval: () => 0, console };
vm.createContext(ctx);
vm.runInContext(src, ctx);
const tick = () => new Promise(r => setImmediate(r));
(async () => {
  for (let n = 0; n < 5; n++) await tick();
  const first = calls.length, state1 = connState();
  for (const ev of ['focus', 'online']) (listeners[ev] || []).forEach(f => f({}));
  (docListeners['visibilitychange'] || []).forEach(f => f({}));
  (listeners['pageshow'] || []).forEach(f => f({ persisted: true }));
  timers.slice().forEach(([f]) => { try { f() } catch (e) {} });
  for (let n = 0; n < 5; n++) await tick();
  console.log(JSON.stringify({ first, total: calls.length, state1, state2: connState(), timers: timers.length, urls: calls, events }));
})();
"""
def run_live(statuses):
    js = R._LIVE_JS.replace("@ROOT@", "")
    p = subprocess.run([NODE, "-e", HARNESS, json.dumps(statuses)], input=js, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[:500]
    return json.loads(p.stdout.strip().splitlines()[-1])
if NODE:
    out = run_live([401])
    check("the page's polling script: the first 401 stops it (one request; focus, online, visibility, pageshow and every timer ask for no more)", out["first"] == 1 and out["total"] == 1, out)
    check("…it shows the Signed out line, and no timer is set to ask again", "out|shown" in out["state2"] and out["timers"] == 0, out)
    check("…and tells the page's other scripts once (stackshot:signedout)", out["events"].count("stackshot:signedout") == 1, out["events"])
    out = run_live([200])
    check("the polling script still polls while signed in (the stub's first answer 200: later asks are made)", out["total"] > out["first"] >= 1, out)
    out = run_live([500, 500, 500])
    check("…and a server that is only unreachable (500) is retried, as before, with the can't-reach line", out["total"] > 1 and "down|shown" in out["state2"], out)
else:
    print("note: node is not installed, the page script's checks are skipped")
if NODE:
    m = re.search(r"<script>((?:(?!</script>).)*?receivers\.json(?:(?!</script>).)*?)</script>", HOME, re.S)
    check("the home page carries the receivers script", bool(m))
    RC = r"""
const fs = require('fs'), vm = require('vm'); const calls = [], ints = [], dl = {}; const mode = process.argv[1];
function el(){ return new Proxy(function(){}, { get: (t,k)=> k in t ? t[k] : (k==='getAttribute' ? ()=> null : k==='querySelector' ? ()=> null : k==='classList' ? {toggle(){}} : ()=> el()), set:(t,k,v)=>{t[k]=v;return true} }) }
const ctx = { window: { addEventListener(){} }, document: { querySelector: ()=> null, querySelectorAll: ()=> [], getElementById: ()=> null, documentElement: el(), body: el(), addEventListener:(n,f)=>{(dl[n]=dl[n]||[]).push(f)}, hidden:false }, Intl, Date, RegExp, String, Math, Object, JSON, parseInt, isNaN,
  fetch:(u)=>{ calls.push(u); return Promise.resolve(mode==='signedout' ? {ok:true,status:200,json:()=>Promise.resolve({})} : {ok:false,status:401,json:()=>Promise.resolve(null)}) },
  setTimeout:(f,ms)=>0, clearTimeout:()=>{}, setInterval:(f,ms)=>{ints.push(f);return 1}, console };
vm.createContext(ctx); vm.runInContext(fs.readFileSync(0,'utf8'), ctx);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{ for(let n=0;n<5;n++) await tick(); const first=calls.length;
  if(mode==='signedout') (dl['stackshot:signedout']||[]).forEach(f=>f({type:'stackshot:signedout'}));
  ints.forEach(f=>f()); (dl['stackshot:swapped']||[]).forEach(f=>f()); for(let n=0;n<5;n++) await tick();
  console.log(JSON.stringify({first,total:calls.length,ints:ints.length})) })();
"""
    def run_rcv(mode):
        p = subprocess.run([NODE, "-e", RC, mode], input=m.group(1), capture_output=True, text=True, timeout=60)
        return json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else {"error": p.stderr[-400:]}
    o = run_rcv("alone")
    check("the receivers poll stops at its first 401 (the interval and the swap event ask for no more)", o.get("first") == 1 and o.get("total") == 1, o)
    o = run_rcv("signedout")
    check("…and, working until the page's own poll says signed out, it asks no more after that (the interval and the swap event)", o.get("first") == 1 and o.get("total") == 1 and o.get("ints", 0) >= 1, o)
check("the audit-now click and the panel-order save read a 401 as signed out (the old redirect wording)",
      "if(r.redirected||r.status===401)return[0,'']" in R._AUDIT_JS and "(e===403||e===401?'panel.order_signin':'panel.order_failed')" in pathlib.Path(STACK, "stackshot/web/ui/render.py").read_text(encoding="utf-8")
      and __import__("stackshot.web.i18n", fromlist=["t"]).t("panel.order_signin", "en") == "The order is changed on this page but was not saved: sign in to the board to keep it.")     # the sentence is in the string table now; the script picks it by a 401/403
check("the page's banner has a Signed out line with a link that opens the page again (a visit signs in)", '<span class="c-out">Signed out — <a href="/" id="conn-signin">sign in again</a></span>' in HOME
      and ".conn.out .c-out{display:inline}" in HOME and 'href=""' not in HOME)
check("the Runners page's script stops asking after a 401 (it keeps a flag, and neither the timer nor the visibility event asks again)", "if(r.status===401)throw 'login'" in RN._JS and "if(busy||gone)return" in RN._JS and "if(e==='login')gone=true" in RN._JS)
if NODE:
    rjs = RN._JS % (json.dumps("UTC"), json.dumps("UTC"))
    rjs = re.sub(r"^<script>|</script>$", "", rjs)
    # The real head defines window.SST/SSD/SSI before any page script (the stub's window is not its global, so SST is also put on the global as a browser has it).
    rjs = re.sub(r"^<script>|</script>$", "", R._SST_HEAD) + ";var SST=window.SST;" + rjs
    RH = r"""
const fs = require('fs'), vm = require('vm'); const calls = []; const intervals = []; const dl = {};
function el(){ return new Proxy(function(){}, { get: (t,k)=> k in t ? t[k] : (k==='getAttribute' ? ()=> '0' : k==='hasAttribute' ? ()=> false : k==='classList' ? {contains:()=>false} : ()=> el()), set:(t,k,v)=>{t[k]=v;return true} }) }
const ctx = { window: {}, document: { getElementById: ()=> el(), addEventListener:(n,f)=>{(dl[n]=dl[n]||[]).push(f)}, hidden:false }, Intl, Date, URLSearchParams, FormData: function(){}, AbortController: undefined,
  fetch:(u)=>{ calls.push(u); return Promise.resolve({ok:false,status:401,headers:{get:()=>'text/plain'},text:()=>Promise.resolve('')}) },
  setTimeout:(f,ms)=>0, clearTimeout:()=>{}, setInterval:(f,ms)=>{intervals.push(f);return 1}, console };
vm.createContext(ctx); vm.runInContext(fs.readFileSync(0,'utf8'), ctx);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{ intervals.forEach(f=>f()); for(let n=0;n<5;n++) await tick(); const first=calls.length;
  intervals.forEach(f=>f()); (dl['visibilitychange']||[]).forEach(f=>f()); for(let n=0;n<5;n++) await tick();
  console.log(JSON.stringify({first,total:calls.length})) })();
"""
    p = subprocess.run([NODE, "-e", RH], input=rjs, capture_output=True, text=True, timeout=60)
    ok = p.returncode == 0
    res = json.loads(p.stdout.strip().splitlines()[-1]) if ok and p.stdout.strip() else {}
    check("the Runners page's script, run on a stub page: after the first 401 the interval and the visibility event ask for no more", ok and res.get("first") == 1 and res.get("total") == 1, (p.stderr[:300], res))

shutil.rmtree(tmp, ignore_errors=True)
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed", flush=True)
if fails:
    print("FAILED:", *fails, sep="\n  ", flush=True); os._exit(1)
os._exit(0)
