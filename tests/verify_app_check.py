"""Verify the running app: start a scratch instance, check it is worth driving, drive its MCP tools and web pages over real HTTP, print what happened, and take it all down.
The recipe and the map of journeys are the repository skill `.claude/skills/verify-stackshot/`. A manual check, not in the suite loop.

    tests/run-suite verify_app_check doctor                    start, check the instance, stop
    tests/run-suite verify_app_check item answer pages         the named journeys, in that order (`all` = every one)
    tests/run-suite verify_app_check --journey <file.py>       a change's own journey: the file defines `journey(app)` (it may stand beside named ones)

The instance is the one the front door suite builds (frontdoor_board_scenario.setup and serve): fixture data in a scratch folder, [auth] off (the MCP endpoint and the pages are open),
a free local port. On top of that one made-up address may sign in, because the page forms ask for a signed-in viewer even then; [publish] git is off, HOME is a scratch folder, no setting of the caller's instance is read from the environment, and a guard in this process
refuses (and records) every connection that is not to this machine's loopback and every program the server tries to start but a git that reads the scratch folders or this checkout. The server's start-time passes and background threads are
not started. Every run ends with one line, `verify_app_check: PASS|FAIL journeys=... checks=N failed=M`, and exit 0 or 1 (2: the command line)."""
import asyncio, collections, html.parser, http.client, importlib.util, json, logging, os, pathlib, re, socket, sys, time, traceback, urllib.parse

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance

EMAIL = "viewer@example.test"                  # the one address that may sign in to the scratch instance
SENDER = "sparrow"                             # the fixture project's session
TOOLS = {"rules", "brief", "get", "create", "update", "complete"}


def say(line):
    print(line, flush=True)


class Guard:
    """An audit hook: this process connects only to the loopback or to a socket inside its scratch folders, and starts no program but a git that reads a repository in those folders
    or this checkout. What was refused is kept for the transcript."""
    def __init__(self):
        self.refused, self.inside = [], []
        sys.addaudithook(self._hook)

    def _local_git(self, argv):
        return (len(argv) > 3 and os.path.basename(argv[0]) == "git" and argv[1] == "-C" and argv[3] in ("rev-parse", "log")
                and any(os.path.realpath(argv[2]).startswith(os.path.realpath(d)) for d in (*self.inside, STACK)))

    def _hook(self, event, args):
        if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            sock, addr = args[0], args[-1]
            if addr is None:                               # a send on a socket connected already: its connect was judged
                return
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                ok = str(addr[0]) in ("127.0.0.1", "::1")
            else:
                ok = any(str(addr).startswith(d) for d in self.inside)
            what = f"reach {addr}"
        elif event == "socket.getaddrinfo":
            ok, what = str(args[0]) in ("127.0.0.1", "::1", "localhost", "None"), f"look up {args[0]}"
        elif event == "subprocess.Popen":
            argv = [os.fsdecode(a) for a in ([args[1]] if isinstance(args[1], (str, bytes)) else list(args[1] or [args[0]]))]
            ok, what = self._local_git(argv), "start " + " ".join(argv)[:300]
        elif event in ("os.system", "os.exec", "os.posix_spawn", "os.spawn"):
            ok, what = False, f"{event} {str(args[0])[:200]}"
        else:
            return
        if not ok:
            self.refused.append(what)
            raise PermissionError(f"the verification instance refuses to {what}")


class Page(html.parser.HTMLParser):
    """A page as a reader gets it: its visible text, and its forms with the fields a browser would send."""
    def __init__(self, source):
        super().__init__()
        self.words, self.forms, self._hidden, self._form = [], [], 0, None
        self.feed(source)
        self.text = " ".join(" ".join(self.words).split())

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._hidden += 1
        elif tag == "form":
            self._form = {"attrs": a, "hidden": {}, "choices": [], "acts": []}; self.forms.append(self._form)
        elif self._form is not None and tag == "input" and a.get("type") == "hidden":
            self._form["hidden"][a.get("name")] = a.get("value") or ""
        elif self._form is not None and tag == "input" and a.get("type") == "radio" and a.get("name") == "choice":
            self._form["choices"].append(a.get("value") or "")
        elif self._form is not None and tag == "button" and a.get("name") == "act":
            self._form["acts"].append(a.get("value") or "")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._hidden -= 1
        elif tag == "form":
            self._form = None

    def handle_data(self, data):
        if not self._hidden:
            self.words.append(data)

    def form(self, cls):
        return next((f for f in self.forms if cls in (f["attrs"].get("class") or "").split()), None)


class App:
    """The running scratch instance, driven the way a session (MCP) and a person (the pages) drive it. A journey gets one."""
    def __init__(self, tmp, port, cookie, guard):
        self.tmp, self.port, self.guard = tmp, port, guard
        self.base = f"http://127.0.0.1:{port}"
        self._cookie = cookie
        self.ran, self.fails = 0, []

    # ---- checks
    def check(self, name, cond, got=None):
        self.ran += 1
        say(("  ok   " if cond else "  FAIL ") + name + ("" if cond or got is None else f": {str(got)[:800]}"))
        if not cond:
            self.fails.append(name)
        return bool(cond)

    # ---- the MCP endpoint
    def _mcp(self, use):
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        async def run():
            async with Client(StreamableHttpTransport(self.base + "/mcp"), timeout=60) as c:
                return await use(c)
        return asyncio.run(run())

    def tools(self):
        """the names of the tools the MCP endpoint lists"""
        async def use(c):
            return {t.name for t in await c.list_tools()}
        return self._mcp(use)

    def call(self, tool, **args):
        """Call a tool as a client does. → (True, the reply's text), or (False, the refusal's text)."""
        from fastmcp.exceptions import ToolError
        say(f"  mcp> {tool} {json.dumps(args, ensure_ascii=False)}")
        async def use(c):
            return "\n".join(getattr(p, "text", "") for p in (await c.call_tool(tool, args)).content)
        try:
            ok, text = True, self._mcp(use)
        except ToolError as e:
            ok, text = False, str(e)
        lines = text.splitlines()
        for line in lines[:12]:
            say(f"  {'   ' if ok else 'ERR'}< {line[:220]}")
        if len(lines) > 12:
            say(f"     < ... {len(lines) - 12} more lines")
        return ok, text

    # ---- the pages
    def request(self, method, path, *, signed=True, body=None, headers=None):
        """One HTTP request, no redirect followed. → (status, headers, text)."""
        h = dict(headers or {})
        if signed:
            h["Cookie"] = self._cookie
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            c.request(method, path, body=body, headers=h)
            r = c.getresponse()
            status, got, text = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read().decode("utf-8", "replace")
        finally:
            c.close()
        say(f"  http> {method} {path}{'' if signed else ' (signed out)'} -> {status} {len(text)} chars" + (f", location {got['location']}" if "location" in got else ""))
        return status, got, text

    def page(self, path, *, signed=True):
        """GET a page → (status, Page)."""
        status, _h, text = self.request("GET", path, signed=signed)
        return status, Page(text)

    def shows(self, name, page, *words):
        """check that each of `words` is in the page's visible text, and print the text around it"""
        for w in words:
            at = page.text.find(w)
            if self.check(f"{name}: shows {w!r}", at >= 0, page.text[:600]):
                say(f"       | {page.text[max(0, at - 60):at + len(w) + 60]}")

    def post_form(self, path, fields, *, origin=None, signed=True):
        """POST a form as a browser does: url-encoded, with the Origin of the page it stands on. → (status, headers, text)."""
        say(f"  form> {json.dumps({k: ('<token>' if k == 'token' else v) for k, v in fields.items()}, ensure_ascii=False)}")
        return self.request("POST", path, signed=signed, body=urllib.parse.urlencode(fields),
                            headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": origin or self.base})

    # ---- what the write left behind
    def item(self, key):
        """The stored record of an item named by its shown id (`s12`), read from the store file: the second view of a write."""
        m = re.fullmatch(r"([a-z])(\d+)", key)
        return json.loads((self.tmp / "store" / m[1] / f"{m[2]}.json").read_text(encoding="utf-8"))

    def items(self):
        return sorted(str(p.relative_to(self.tmp / "store")) for p in (self.tmp / "store").glob("?/*.json"))


# ================================================================ the journeys (the skill's features/ files describe each)
def sample(outcome):
    """the subject and description of a made-up item, in the shape the store's own write rules ask: both open with the finished outcome"""
    return {"subject": f"[home] The sample {outcome}", "description": f"- Goal: the sample {outcome}.\n- Done when: the sample {outcome}."}


def created(app, **args):
    """create an item and → its shown id, or None (the failed check says why)"""
    ok, reply = app.call("create", sender=SENDER, project="projects/alpha", **args)
    new = re.search(r"\bcreated \[([a-z]\d+)\]", reply) if ok else None
    app.check("create: the reply names the new item", new, reply[:400])
    return new[1] if new else None


def journey_item(app):
    before = app.items()
    step = {"next": f"{SENDER}: write the first line", "mover": SENDER}
    ok, reply = app.call("create", sender=SENDER, project="projects/none", **sample("refusal is recorded"), **step)
    app.check("create: an unknown project is refused, and the refusal says so", not ok and "names no page" in reply, reply)
    app.check("create: the refused call wrote no item", app.items() == before, app.items())
    key = created(app, **sample("line is written"), **step)
    if not key:
        return
    ok, got = app.call("get", item_id=key)
    app.check("get: returns the subject and the step", ok and "The sample line is written" in got and "write the first line" in got, got)
    ok, reply = app.call("update", item_id=key, sender=SENDER, next=f"{SENDER}: write the second line")
    app.check("update: accepted", ok, reply)
    stored = app.item(key)
    app.check("update: the store holds the new step", "write the second line" in json.dumps(stored["metadata"].get("next")), stored["metadata"])
    status, page = app.page(f"/items/{key}")
    app.check("item page: 200", status == 200, status)
    app.shows("item page", page, "The sample line is written", "write the second line")
    status, page = app.page("/projects/alpha")
    app.shows("project page", page, "The sample line is written")
    ok, reply = app.call("complete", item_id=key, sender=SENDER, outcome="done", reason="the sample line is written", outcome_text="- The second line was written.")
    app.check("complete: accepted", ok, reply)
    stored = app.item(key)
    app.check("complete: the store holds a closed item", stored["status"] == "completed", stored)
    status, page = app.page("/closed")
    app.check("closed page: 200", status == 200, status)
    app.shows("closed page", page, "The sample line is written")


def journey_answer(app):
    ask = "Decide: whether to ship the sample · Recommend: Ship · Stakes: none either way · By: no date"
    options = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
    key = created(app, **sample("release is decided"), needs=["decision"], ask=ask, options=options, then=SENDER)
    if not key:
        return
    status, page = app.page("/")
    app.shows("home", page, "The sample release is decided")
    status, page = app.page(f"/items/{key}")
    form = page.form("ianswer")
    if not app.check("item page: the answer form offers both options", status == 200 and form and sorted(form["choices"]) == ["Ship", "Wait"], (status, form)):
        return
    action = form["attrs"]["action"]
    fields = {**form["hidden"], "choice": "Wait", "text": "after the holiday", "act": form["acts"][0]}
    status, page = app.page(f"/items/{key}", signed=False)
    app.check("signed out: the item page offers no answer form", status == 200 and not page.form("ianswer"), (status, page.form("ianswer")))
    for label, kw, f in (("signed out", {"signed": False}, fields), ("from another origin", {"origin": "https://elsewhere.example"}, fields), ("with another token", {}, {**fields, "token": "0" * 64})):
        status, _h, text = app.post_form(action, f, **kw)
        app.check(f"answer {label}: refused with 403", status == 403, (status, text[:200]))
    app.check("the refused answers recorded nothing", not app.item(key)["metadata"].get("answers"), app.item(key)["metadata"])
    status, headers, text = app.post_form(action, fields)
    app.check("answer: 303 back to the item with its notice code", status == 303 and headers.get("location") == f"/items/{key}?sent=decision", (status, headers.get("location"), text[:200]))
    stored = app.item(key)["metadata"]
    answers = stored.get("answers") or [{}]
    app.check("answer: the store records the choice and the note", len(answers) == 1 and answers[0].get("choice") == "Wait" and answers[0].get("text") == "after the holiday", answers)
    app.check("answer: the item no longer needs a decision", "decision" not in (stored.get("needs") or []), stored.get("needs"))
    status, page = app.page(f"/items/{key}?sent=decision")
    app.shows("page after", page, "Sent: your answer is on the item")
    app.check("page after: no option is offered again", not (page.form("ianswer") or {}).get("choices"), page.form("ianswer"))
    ok, got = app.call("get", item_id=key)
    app.check("get: the session reads the answer", ok and "Wait" in got and "after the holiday" in got, got)


def journey_pages(app):
    ok, text = app.call("rules")
    app.check("rules: serves the instance's rulebook", ok and "a rule the connector serves" in text, text[:300])
    ok, text = app.call("brief")
    app.check("brief: answers", ok and text.strip(), text[:300])
    ok, text = app.call("get", item_id="a1")
    app.check("get: reads the seeded item", ok and "door fixture item" in text, text[:300])
    for path, words in (("/", ("door fixture item",)), ("/projects", ("Projects",)), ("/projects/alpha", ("door fixture item",)), ("/items/a1", ("door fixture item",)),
                        ("/search?q=fixture", ("door fixture item",)), ("/closed", ()), ("/audits", ())):
        status, page = app.page(path)
        app.check(f"{path}: 200", status == 200, (status, page.text[:300]))
        app.shows(path, page, *words)
    status, _page = app.page("/items/a999")
    app.check("an item that does not exist: 404", status == 404, status)


JOURNEYS = {"item": journey_item, "answer": journey_answer, "pages": journey_pages}


# ================================================================ launch, doctor, teardown
def launch(guard):
    """→ (App, stop). An empty scratch folder to a served instance: the config and the seed data, the guard's sockets, one render of the site, the HTTP app on a port this run holds."""
    for name in [n for n in os.environ if n.startswith(("STACKSHOT_", "BOARD_MCP_", "ANCHOR_")) and not n.startswith(("STACKSHOT_XLOCK", "STACKSHOT_TEST_"))]:
        del os.environ[name]
    home = _scratch.mkdtemp(prefix="verifyhome-")
    os.environ.update(HOME=home, XDG_CONFIG_HOME=f"{home}/.config", XDG_CACHE_HOME=f"{home}/.cache", XDG_STATE_HOME=f"{home}/.state", FASTMCP_HOME=f"{home}/fastmcp")
    from frontdoor_board_scenario import serve, setup, stop
    tmp, _secret, _paths = setup("off")
    guard.inside += [str(tmp), home]
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    conf = tmp / "stackshot.toml"
    toml = _instance.set_person(conf.read_text(encoding="utf-8"))
    for pattern, line in ((r'(?m)^board_url = "[^"]*"', f'board_url = "{base}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{base}"'),
                          (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^git = true', "git = false")):
        toml, n = re.subn(pattern, line, toml)
        assert n == 1, f"the example config no longer has one line for {pattern}"
    conf.write_text(toml, encoding="utf-8")
    logging.disable(logging.INFO)
    from stackshot.web import publish, server
    from stackshot.web.auth import signin
    publish._publish_now()                                 # the site files a start publishes: /healthz among them
    srv, thread, sock, port = serve(server.mcp.http_app(), sock)
    # a viewer signs in through Google; this run signs its own cookie with the board's key, as the browser checks do
    cookie = f"{signin._UI_COOKIE}={signin._ui_sign(json.dumps({'email': EMAIL, 'exp': time.time() + 3600}))}"
    def end():
        stop(srv, thread, sock)
        timer = publish._PUB_TIMER                         # a write's debounced publish must not run into the folders' removal
        if timer is not None:
            timer.cancel(); timer.join(60)
    return App(tmp, port, cookie, guard), end


def doctor(app):
    """Read only: is this instance the one this run built, from this checkout, and does it answer?"""
    import stackshot
    from stackshot.core import config as cfg
    code = pathlib.Path(stackshot.__file__).resolve()
    app.check("doctor: the code under test is this checkout's", code.is_relative_to(pathlib.Path(STACK).resolve()), code)
    roots = (str(app.tmp), os.environ["HOME"])
    outside = {k: str(cfg.path("paths", k)) for k in ("repo", "store", "markdown", "brain", "state", "secrets", "rules", "project_touch") if not str(cfg.path("paths", k)).startswith(roots)}
    app.check("doctor: the config is the scratch one and its paths are inside the scratch folders", str(cfg.PATH) == str(app.tmp / "stackshot.toml") and not outside, (cfg.PATH, outside))
    app.check("doctor: publish runs no git and the GitHub mirror is off", cfg.get("publish", "git") is False and cfg.get("github", "sync") is False, (cfg.get("publish", "git"), cfg.get("github", "sync")))
    status, _h, text = app.request("GET", "/healthz")
    app.check("doctor: /healthz answers ok", status == 200 and text.startswith("ok"), (status, text[:100]))
    tools = app.tools()
    app.check(f"doctor: the MCP endpoint lists {', '.join(sorted(TOOLS))}", TOOLS <= tools, sorted(TOOLS - tools))
    signed, unsigned = app.page("/items/a1"), app.page("/items/a1", signed=False)
    got = (signed[0], bool(signed[1].form("iwatch")), unsigned[0], bool(unsigned[1].form("iwatch")))
    app.check("doctor: the instance takes this run's sign-in (a signed-in viewer's forms are on the seeded item's page, a signed-out one's are not)", got == (200, True, 200, False), got)
    n = len(app.guard.refused)
    try:
        socket.create_connection(("192.0.2.1", 443), timeout=1)
        stopped = False
    except PermissionError:
        stopped = True
    except OSError:
        stopped = False
    app.check("doctor: a connection off this machine is refused by the guard", stopped)
    del app.guard.refused[n:]                              # the probe itself is no finding


def from_file(path):
    """The journey `journey(app)` of a file, loaded when it is driven: after the launch, so it sees the scratch instance's config, and under the guard."""
    def run(app):
        spec = importlib.util.spec_from_file_location("change_journey", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.journey(app)
    return run


def parse(argv):
    """→ [(name, journey)]; SystemExit(2) with the usage for anything else"""
    wanted, it = [], iter(argv)
    for a in it:
        if a == "--journey":
            path = next(it, "")
            if not os.path.isfile(path):
                sys.exit(usage(f"no such journey file: {path!r}"))
            wanted.append((path, from_file(os.path.abspath(path))))
        elif a == "all":
            wanted += list(JOURNEYS.items())
        elif a in JOURNEYS:
            wanted.append((a, JOURNEYS[a]))
        elif a != "doctor":
            sys.exit(usage(f"no such journey: {a!r}"))
    if not argv:
        sys.exit(usage("name what to run"))
    return wanted


def usage(why):
    print(f"verify_app_check: {why}\nusage: tests/run-suite verify_app_check doctor | all | {' | '.join(JOURNEYS)} ... [--journey <file.py>]", file=sys.stderr)
    return 2


def main(argv):
    wanted = parse(argv)
    names = ",".join(n for n, _ in wanted) or "doctor"
    guard = Guard()
    app, stop, ran, fails = None, None, 0, ["the run did not finish"]
    try:
        say("== launch")
        app, stop = launch(guard)
        say(f"  ready: {app.base} (MCP at /mcp), scratch {app.tmp}")
        try:
            say("== doctor")
            doctor(app)
            if app.fails:
                say("  the doctor failed: nothing is driven")
            else:
                for name, journey in wanted:
                    say(f"== journey {name}")
                    before = app.ran
                    try:
                        journey(app)
                        if app.ran == before:
                            app.check(f"journey {name}: makes at least one check", False)
                    except Exception:      # noqa: BLE001  (one journey's crash is its failure; the next still runs)
                        traceback.print_exc(file=sys.stdout)
                        app.check(f"journey {name}: ran to its end", False)
        finally:
            ran, fails = app.ran, app.fails
    except BaseException:      # noqa: BLE001  (a launch or a doctor that raised: said, and the teardown still runs)
        traceback.print_exc(file=sys.stdout)
        fails = [*fails, "the run raised"]
    finally:
        say("== teardown")
        if stop:
            stop()
        say(f"  refused by the guard (nothing left this process): {len(guard.refused)}")
        for what, times in collections.Counter(guard.refused).items():
            say(f"    - {what}" + (f"   (x{times})" if times > 1 else ""))
        _scratch.cleanup()
        if app:
            with socket.socket() as s:
                closed = s.connect_ex(("127.0.0.1", app.port)) != 0
            gone = not app.tmp.exists() and not os.path.exists(os.environ["HOME"])
            say(f"  server stopped: {'yes' if closed else 'NO'}; scratch folders removed: {'yes' if gone else 'NO'}")
            if not (closed and gone):
                fails = [*fails, "teardown left something behind"]
        say(f"verify_app_check: {'FAIL' if fails else 'PASS'} journeys={names} checks={ran} failed={len(fails)}")
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
