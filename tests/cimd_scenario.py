"""Scenario test for the CIMD fallback (cimd.py, wired in stackshot/web/auth/oauth.py `_auth()`; a failed fetch of
the client's metadata document was refused and the client dropped the connector grant for every pane)
— fake fetchers and a patched transport, no network, no Google credentials.

Covers: a fetch that fails twice and then succeeds returns the document and keeps a copy on disk; a fetch that keeps failing
serves the in-process cached document, else the copy on disk, else raises the last error; fastmcp's own fetcher behind its
CIMDClientManager, its transport failing with an expired cache entry, still yields a client.

    tests/run-suite cimd        → exit 0 / 1"""
import asyncio, hashlib, logging, os, pathlib, sys, tempfile, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="cimdtest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.web.auth import cimd
from fastmcp.server.auth import cimd as fcimd
from fastmcp.server.auth.cimd import CIMDDocument, CIMDFetchError, CIMDValidationError, _CIMDCacheEntry
from fastmcp.server.auth.ssrf import SSRFFetchError
slept = []
async def _nosleep(s): slept.append(s)
cimd.asyncio.sleep = _nosleep                                   # the retries' back-off, without the wait

URL = "https://claude.ai/oauth/mcp-oauth-client-metadata"
doc = lambda name: CIMDDocument(client_id=URL, redirect_uris=["https://claude.ai/api/mcp/auth_callback"], client_name=name)
disk = lambda store: store / (hashlib.sha256(URL.encode()).hexdigest()[:16] + ".json")
entry = lambda d: _CIMDCacheEntry(doc=d, etag=None, last_modified=None, expires_at=time.time() - 60, freshness_lifetime=300, must_revalidate=False)

class Log(logging.Handler):
    def __init__(self): super().__init__(); self.lines = []
    def emit(self, r): self.lines.append((r.levelno, r.getMessage()))
def logger(name):
    lg = logging.getLogger(f"cimdtest.{name}"); lg.propagate = False; h = Log(); lg.addHandler(h); lg.setLevel(logging.DEBUG); return lg, h

class Fetcher:
    """fails `fails` times (alternating the two error kinds fastmcp raises), then returns `doc`; None = never succeeds"""
    def __init__(self, fails, d=None): self.fails, self.d, self.calls, self._cache = fails, d, 0, {}
    async def fetch(self, url):
        self.calls += 1
        if self.fails is None or self.calls <= self.fails:
            raise (CIMDFetchError if self.calls % 2 else CIMDValidationError)(f"boom {self.calls}")
        return self.d
run = asyncio.run

# (a) fails twice, then succeeds: the document, after two back-offs, and a copy on disk
store = T / "a"; f = Fetcher(2, doc("fresh")); lg, h = logger("a"); slept.clear()
cimd._harden_cimd(f, store, lg); got = run(f.fetch(URL))
check("a: the third attempt's document is returned", got.client_name == "fresh" and f.calls == 3, (got, f.calls))
check("a: back-off 1.5 s then 3 s", slept == [1.5, 3.0], slept)
check("a: the document is kept on disk", disk(store).exists() and CIMDDocument.model_validate_json(disk(store).read_text()).client_name == "fresh")
check("a: nothing warned", not [m for lv, m in h.lines if lv >= logging.WARNING], h.lines)

# (b) always fails, a cache entry present: the cached document, with a warning
store = T / "b"; f = Fetcher(None); f._cache[URL] = entry(doc("cached")); lg, h = logger("b"); slept.clear()
cimd._harden_cimd(f, store, lg); got = run(f.fetch(URL))
check("b: the cached document is served", got.client_name == "cached" and f.calls == 3, (got, f.calls))
check("b: one warning naming the cache and the last error", [m for lv, m in h.lines if lv == logging.WARNING] == [f"CIMD fetch failed for {URL} (boom 3): serving the cached document"], h.lines)
check("b: no back-off after the last attempt", slept == [1.5, 3.0], slept)

# (c) always fails, no cache, a copy on disk: the copy
store = T / "c"; store.mkdir(); disk(store).write_text(doc("on disk").model_dump_json())
f = Fetcher(None); lg, h = logger("c"); cimd._harden_cimd(f, store, lg); got = run(f.fetch(URL))
check("c: the document kept on disk is served", isinstance(got, CIMDDocument) and got.client_name == "on disk", got)
check("c: the warning names the disk copy", [m for lv, m in h.lines if lv == logging.WARNING] == [f"CIMD fetch failed for {URL} (boom 3): serving the document kept on disk"], h.lines)

# (d) always fails, nothing anywhere: the last error is raised
store = T / "d"; f = Fetcher(None); lg, h = logger("d"); cimd._harden_cimd(f, store, lg)
try: run(f.fetch(URL)); got = "no error"
except (CIMDFetchError, CIMDValidationError) as e: got = e
check("d: the last error is raised", isinstance(got, CIMDFetchError) and str(got) == "boom 3", repr(got))

# (d2) an unreadable disk copy is no fallback: still the fetch error, which fastmcp turns into a clean refusal
store = T / "d2"; store.mkdir(); disk(store).write_text("{not json")
f = Fetcher(None); lg, h = logger("d2"); cimd._harden_cimd(f, store, lg)
try: run(f.fetch(URL)); got = "no error"
except (CIMDFetchError, CIMDValidationError) as e: got = e
check("d2: an unreadable disk copy raises the fetch error", isinstance(got, CIMDFetchError), repr(got))

# (e) fastmcp's own fetcher behind its manager: transport down, cache entry expired → a client all the same (the names are fastmcp 4.0's)
async def _down(*a, **k): raise SSRFFetchError("connection refused")
fcimd.ssrf_safe_fetch_response = _down
mgr = fcimd.CIMDClientManager(); real = mgr._fetcher
check("e: the manager carries the fetcher with its cache", isinstance(real, fcimd.CIMDFetcher) and isinstance(real._cache, dict))
real._cache[URL] = entry(doc("expired"))
store = T / "e"; lg, h = logger("e"); cimd._harden_cimd(real, store, lg); logging.getLogger("fastmcp").setLevel(logging.CRITICAL)
client = run(mgr.get_client(URL))
check("e: get_client returns a client instead of None", client is not None and str(client.client_id) == URL, client)
real._cache.clear(); client = run(mgr.get_client(URL))
check("e: with nothing to fall back on, get_client still returns None", client is None, client)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
check("hermetic: nothing here read the host's sala session registry (CI runs on a box that has one)", "sessions_registry" not in sys.modules)
print(("ok" if not fails else "FAILED") + f": cimd scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
