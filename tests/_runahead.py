"""tests/_runahead.py: run the release suites' scenarios a few at a time instead of one after the other (a helper module, not a suite).

release_scenario.py and release_queue_scenario.py are long lists of `s = scenario(...)` followed by `check(...)`. A scenario is one run of release.sh in a folder of its own,
about a second of process starts, and the suite waits for each before it reads the next. Nearly all of the suites' time is those waits.

Run-ahead starts the scenarios that are coming while the suite reads the one it is at. It reads the suite's own source (the `__main__` file), and when the suite arrives at a
top-level `s = scenario(...)` (or `fast`, `inc`, `grp`, `q`, which only fill in arguments) it looks at the statements that follow, and starts the scenarios of the next ones on a
few threads. When the suite gets to such a statement it makes the same call, finds a started run with the same name and arguments and takes its result: the check that follows
reads exactly what it read before, in the same order, with the same arguments. Nothing is skipped, nothing is reordered, no check is evaluated early.

A scenario is started early only when that cannot change what it does:
  * the statement is a plain call of one of those functions, with names bound by the suite and literal arguments, and no `reuse=` (it continues another scenario's folder),
    `lockhook=`, `side=` or lambda in it (they carry state of the run before);
  * every name it reads is bound by now: no statement between the one the suite is at and this one (nor the one it is at) assigns it, so the value read early is the value read later;
  * everything between the two is inert: another such call, a `check(...)`, a `def`, an import, or an assignment, built from calls that only read (the lists below). The first
    statement that could change something a later scenario reads (a loop, a `with`, a call that writes, a helper that is not on the lists) ends the look-ahead, and the scenarios
    after it start when the suite reaches it;
  * a started run is taken only by a call with the same name and the same arguments (their repr); a mismatch is a wasted run, never a wrong result.
The scenarios share nothing but their own folders (each is made under the suite's scratch folder with a name of its own, a run's stubs read only that folder), so two at once
cannot see each other.

RELEASE_SUITE_PAR sets how many run at once (default: the CPUs, at most 4); 1 turns this off, and the suites run exactly as they did, one scenario at a time.
"""
import ast, concurrent.futures, os, sys, threading

WRAPPERS = {"scenario", "fast", "inc", "grp", "q"}   # the calls that start a scenario (fast, inc, grp and q only fill arguments in, then call scenario)
STATEFUL_KW = {"reuse", "lockhook", "side"}   # a call with one of these continues something the run before left: never started early
READERS = {"check", "len", "any", "all", "sorted", "set", "list", "tuple", "dict", "sum", "str", "int", "oct", "repr", "min", "max", "range", "enumerate", "zip", "isinstance", "bool", "abs",
           # the suites' own readers of a result (each only reads the folder of the result it is given)
           "gl", "at_gh", "at_has", "regen_calls", "red", "lock_views", "enqueues", "deletes", "refchecks", "merges", "plain_merges", "lock_free", "at", "recycled", "pick_reads",
           "prlog", "glog", "handed", "started_args", "pr_reads", "run_lists", "fetches", "gh_checks", "wait_", "paused_group", "polls_over", "QF"}
READER_ATTRS = {"startswith", "endswith", "count", "index", "split", "splitlines", "rstrip", "lstrip", "strip", "join", "replace", "exists", "is_dir", "is_file", "read_text", "read_bytes",
                "stat", "glob", "iterdir", "joinpath", "isdigit", "get", "search", "match", "lower", "upper", "format", "keys", "values", "items", "partition"}
READER_DOTTED = {"re.search", "re.match", "re.findall", "os.path.exists", "os.path.join", "os.path.isdir", "_scratch.mkdtemp", "json.dumps", "json.loads", "pathlib.Path", "_h.without_coverage"}


def _reads_only(node):
    """every call inside the node is one that only reads, and it binds nothing with :="""
    for n in ast.walk(node):
        if isinstance(n, ast.NamedExpr): return False
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in READERS: continue
            if isinstance(f, ast.Lambda): continue   # (lambda d: ...)(x): its body is walked on its own
            if isinstance(f, ast.Attribute) and (f.attr in READER_ATTRS or ast.unparse(f) in READER_DOTTED): continue
            return False
    return True


def _names(node, ctx):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ctx)}


def _stores(st):
    names = _names(st, ast.Store)
    if isinstance(st, (ast.FunctionDef, ast.ClassDef)): names.add(st.name)
    if isinstance(st, (ast.Import, ast.ImportFrom)): names |= {(a.asname or a.name).split(".")[0] for a in st.names}
    return names


def _bound_to_names(t):
    """an assignment target made of names only: `s`, `a, b`, `a, *b`"""
    return isinstance(t, ast.Name) or isinstance(t, ast.Starred) and _bound_to_names(t.value) or isinstance(t, (ast.Tuple, ast.List)) and all(_bound_to_names(e) for e in t.elts)


def _scenario_call(st):
    """`s = scenario(...)` or a bare `scenario(...)`: a call of a WRAPPERS function whose arguments only read"""
    if not (isinstance(st, ast.Assign) and all(_bound_to_names(t) for t in st.targets) or isinstance(st, ast.Expr)): return False
    c = st.value
    if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in WRAPPERS): return False
    return all(_reads_only(a) for a in (*c.args, *(k.value for k in c.keywords)))


def _candidate(st):
    """a scenario call that may be started early: nothing in it continues the state of the run before"""
    if not _scenario_call(st): return False
    c = st.value
    if any(k.arg is None or k.arg in STATEFUL_KW for k in c.keywords): return False
    return not any(isinstance(n, (ast.Lambda, ast.NamedExpr, ast.Await, ast.Yield)) for n in ast.walk(c))


def _inert(st):
    """a statement that changes nothing a later scenario could read (a scenario call counts: it only touches the folder it makes or the one it is given)"""
    if isinstance(st, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)): return True
    if _scenario_call(st): return True
    if isinstance(st, (ast.Assign, ast.AugAssign)):
        ts = st.targets if isinstance(st, ast.Assign) else [st.target]
        return all(_bound_to_names(t) for t in ts) and _reads_only(st.value)
    if isinstance(st, ast.Expr):
        c = st.value
        if isinstance(c, ast.Constant): return True
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "check": return _reads_only(c)
        return isinstance(c, ast.Call) and ast.unparse(c.func) == "dirs.append" and all(_reads_only(a) for a in c.args)   # the harness keeps the folders it made to remove them
    if isinstance(st, ast.For): return isinstance(st.target, (ast.Name, ast.Tuple)) and _bound_to_names(st.target) and _reads_only(st.iter) and all(_inert(b) for b in (*st.body, *st.orelse))
    if isinstance(st, ast.If): return _reads_only(st.test) and all(_inert(b) for b in (*st.body, *st.orelse))
    if isinstance(st, (ast.Break, ast.Continue, ast.Pass)): return True
    return False


class RunAhead:
    def __init__(self, run, workers, ahead=8):
        self.run, self.ahead = run, ahead
        self.lock, self.tl = threading.Lock(), threading.local()
        self.futs = {}      # key of a call -> the started runs of it, oldest first
        self.started = {}   # index of a suite statement -> the key of the run started for it
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="runahead")
        self.main = sys.modules.get("__main__")
        self.body = None
        try:
            tree = ast.parse(open(self.main.__file__, encoding="utf-8").read())
            self.body = tree.body
            self.cand = [_candidate(st) for st in self.body]
            self.inert = [_inert(st) for st in self.body]
            self.stores = [_stores(st) for st in self.body]
            self.loads = [_names(st.value, ast.Load) if c else set() for st, c in zip(self.body, self.cand)]
        except Exception:
            self.body = None   # no source to read: no run-ahead, the suite runs as before

    @staticmethod
    def key(name, pos, kw): return repr((name, pos, tuple(kw.items())))

    def call(self, name, pos, kw):
        """the scenario() of the harness: a run started early when there is one for exactly this call, else the run itself"""
        if getattr(self.tl, "spec", False):   # evaluating an upcoming statement: only start its run
            key = self.key(name, pos, kw)
            fut = self.pool.submit(self.run, name, *pos, **kw)
            with self.lock: self.futs.setdefault(key, []).append(fut)
            self.tl.last = key
            return None
        key = self.key(name, pos, kw)
        with self.lock:
            lst = self.futs.get(key); fut = lst.pop(0) if lst else None
        if threading.current_thread() is threading.main_thread(): self._look_ahead()
        return fut.result() if fut is not None else self.run(name, *pos, **kw)

    def _at(self):
        """the index of the top-level statement of the suite that is running, None when the call does not come straight from one"""
        f = sys._getframe(2)
        while f is not None and not (f.f_globals is self.main.__dict__ and f.f_code.co_name == "<module>"): f = f.f_back
        if f is None: return None
        return next((i for i, st in enumerate(self.body) if st.lineno <= f.f_lineno <= st.end_lineno), None)

    def _look_ahead(self):
        if self.body is None: return
        i = self._at()
        if i is None or not self.inert[i]: return   # the suite is inside something that could change what a later scenario reads
        bound = set(self.stores[i])   # names that hold an older value than the suite will see when it gets to the statement
        for j in range(i + 1, len(self.body)):
            if sum(1 for k in self.started if k > i) >= self.ahead: return
            if self.cand[j]:
                if j not in self.started and not (self.loads[j] & bound): self._start(j)
                bound |= self.stores[j]
            elif self.inert[j]: bound |= self.stores[j]
            else: return

    def _start(self, j):
        """make the call of statement j now, with the harness told to start its run and return nothing"""
        st = self.body[j]
        code = compile(ast.Expression(body=st.value), self.main.__file__, "eval")
        self.tl.spec, self.tl.last = True, None
        try: eval(code, self.main.__dict__)
        except Exception: pass   # a name not bound yet, a call that does not like its arguments: the run starts when the suite gets there
        finally: self.tl.spec = False
        if self.tl.last is not None: self.started[j] = self.tl.last

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


def make(run):
    """a RunAhead for this process, or None when RELEASE_SUITE_PAR is 1 (or the suite's source cannot be read)"""
    try: n = int(os.environ.get("RELEASE_SUITE_PAR", "") or min(4, os.cpu_count() or 1))
    except ValueError: n = 1
    if n < 2: return None
    ra = RunAhead(run, n)
    return ra if ra.body is not None else None
