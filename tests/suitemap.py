#!/usr/bin/env python3
"""tests/suitemap.py — which scenario suites a change needs (Tue Oct 27th 2026). A tool, not a suite.

Until every pull request ran all the tests/*_scenario.py suites, about 8 min of the one CI turn on box-a, for
a docs fix as for a change to server.py. Now a push to main runs every suite MEASURED and keeps what each one touched (a
"map", in GitHub's Actions cache); a pull request runs only the suites whose touched code or files its change reaches, and
the next main run checks that choice against the merged code's own measurement (`audit`). The map is measured, never written:
nobody keeps it by hand.

What a suite touches, at two grains:
  * Python code, by function. coverage.py records the lines every Python process of the suite runs (its subprocesses too);
    a line belongs to the innermost function whose body holds it, to `<main>` in a top-level `if __name__ == "__main__":`,
    or to the module (imports, constants, class bodies, the def lines themselves). A change inside a function body reaches
    the suites that ran that function. A change at module level that only binds names (a def or class, a constant, the
    docstring, an import) reaches the code that READS them, by name (see *names* below): the functions whose bodies name
    them, followed across imports and through the bindings that use them, and the suites whose own file names them. One
    with effects at import (an unknown decorator, a call statement) reaches every suite that ran the file. A registered
    function (@mcp.tool on the module's own object) reaches its callers and whatever lists the registry. A change that is
    only comments and blank lines reaches no suite by code.
  * Files, whole. strace records every tracked file a process of the suite opens, stats, runs or looks for (a failed lookup
    counts: a suite can depend on a file being absent), and the directories it lists. A non-Python file (a shell script,
    stackshot.example.toml, an icon) reaches the suites that touched it; a .py file reaches, whole, the suites that read it
    as text (inspect.getsource, a test that greps server.py) or that loaded it in a Python coverage did not measure (the hooks
    run the system python3). The bytecode is compiled before measuring, so a measured Python opening a .py is a text read.

Usage (run from the checkout; `measure` in the test environment, which has coverage; the rest need only git):
  tests/suitemap.py list                                  every suite, one per line (tests/*_scenario.py)
  tests/suitemap.py measure --map OUT [--prev MAP] [-T secs] [suite…]
                                                          run the suites measured (all when none is named), write the map
                                                          (SUITEMAP_STRACE=0: coverage only, so files are not measured; with
                                                          --prev, strace only the suites the change since that map reaches
                                                          and those traced over 24 h ago, the rest keep their file half);
                                                          exit 1 when a suite fails (a suite that fails only when measured
                                                          passes on a plain rerun: a warning, and the map marks it `ok: false`, keeping the
                                                          earlier clean measurement beside it as `carry` for a reader of the map; release.sh no longer reads it)
  tests/suitemap.py run [-T secs] suite…                  run the suites plainly; exit 1 when one fails
  tests/suitemap.py plan --of N [--map MAP]               the whole plan of main's measured run, made once: `shard0=a b c`, `shard1=…`
                                                          lines (the format of $GITHUB_OUTPUT) for the N shards (see *Shards*)
  tests/suitemap.py shard --of N --index I [--map MAP]   one line of that plan: the suites of shard I (0 to N-1), one per line
  tests/suitemap.py merge --map OUT SHARD…                one map out of the shards' maps (one commit); exit 1 when a suite is
                                                          in two of them or a suite of the checkout is in none (the map is
                                                          still written: a suite it lacks has no clean measurement, so it runs)
  tests/suitemap.py select --map MAP [--to REV]           print `all`, or the suites to run separated by spaces (empty: none);
                                                          the reason for each changed file goes to stderr, and to
                                                          $GITHUB_STEP_SUMMARY when set. The change is git diff <map's commit> <REV>
  tests/suitemap.py audit --old OLD --new NEW --to B     the suites the new map says <old map's commit>..B reaches that the
                                                          old map's choice for the same range skipped, and the suites that
                                                          failed on main that it skipped: exit 1 when there is one, or when
                                                          a commit does not resolve (nothing was checked). A suite the
                                                          new map has no clean measurement for (`ok: false`) is not counted:
                                                          the selection runs it always, so it says nothing about reach

The rules, per changed file F (git diff --name-status -M), the first that applies:
  1. no map, a map of another format, a commit that does not resolve           → all
  2. F is the harness: .github/, tests/run-suite, pyproject.toml, uv.lock, tests/suitemap.py → all;
     F is a link of the DATA table (tests/example_base.toml) → all
  3. F = tests/<suite>_scenario.py                                              → that suite
  4. F ends in .lock (a script's lock: the lock step checks every one)          → none;
     F is tests/*_check.py (a manual check, not in CI)                         → none
  5. F is a new path (added, or a rename's new side) in a directory no measured suite lists, or the map has no strace →
     all: a new path is read by code that names it (its own change selects) or that lists the directory; one no suite
     lists may still be looked up by a name nobody tried before (the import machinery lists the sys.path directories, the
     checkout and tests/, so those are listed by every suite)
  6. F is a .py file → the suites that read it whole, the suites that ran the functions its changed lines are in, and
     those that read the names its module-level changes bind (a new file: whoever imports it changed too; one named like a
     module the suites import, which it could shadow → all)
  7. any other file → the suites that touched it; added, deleted or renamed: also the suites that listed its directory;
     a data file of the DATA table (stackshot.example.toml) is first read by what it holds, not by who touched it: see *The example config*
  A suite the map has no clean measurement for (new since, or `ok: false`) always runs. When the union is every suite: all.
  INNER names the suites that run other suites as their own checks (scratch runs rename, redact, lead and migration to see
  that they leave no folder behind): they pass or fail with them, but the code those inner runs ran is not in the outer
  suite's measurement when the inner suite runs it in a child that coverage does not follow, and a change to that code (a
  scenario that now runs a module in process) shows up in the outer suite's measurement only after the merge. So
  a change that selects an inner suite selects its outer suite too.
  release.sh's retest skip (tools/retest_skip.py, removed when releases moved to GitHub's merge queue) read this map for what each suite reads and used to refuse the whole map for
  one `ok: false` suite. A suite that fails only when measured (the release suite, 4 to 9 times slower measured than plain, timed
  out at the 2400 s limit once, and the map of that run was refused for every PR it served) keeps its last clean measurement
  beside the new one as `carry` (the read sets, when it was traced, and `at`, the commit it was measured at): the skip reads the
  union of the two, takes the drift since `at` as main's news, and refuses a carry older than its own age limit. `ok` stays
  false, so the selection above still runs the suite on every PR.

The example config (Tue Nov 10th 2026). About 150 of the suites read stackshot.example.toml, and only to make the base of their own temp
config, so every change to it (11 of the last 30 PRs, a comment among them) ran about 188 of the 196 suites. Now those suites read it through
the tracked link tests/example_base.toml (-> ../stackshot.example.toml; tests/_instance.py base_toml()), and strace records the path a process
opens as it was written, so the map tells two kinds of reader apart: a DIRECT reader opens the real path (it parses, greps, copies or patches
the example config, or runs code that reads it: about 40 suites, the suitemap scenario among them), a FIXTURE reader opens the link. The DATA
table names the file and its link. A change to the file selects the direct readers ALONE only when it is provably harmless to a fixture suite,
and that is narrow on purpose:
  * every changed line of the file, on the old side and the new, is a whole blank line or a whole comment-only line (outside a multi-line
    string), and a comment line is plain prose: letters, spaces and . , ; : ! ? ( ) ' - only, with no word of it (and no 4-letter-or-longer
    name inside a longer word) that is a name the fixtures patch, read or grep: the table and key names of the file itself (old and new)
    and the constants SETTINGS, KEYWORDS, FLAG_SETTINGS, TABLES and PINNED_TABLES of tests/_instance.py. A comment with `=`, `[`, a quote,
    a digit or an underscore is not plain (a commented-out sample such as `# live = true` or `# session_view = ""` is code to a suite that
    replaces text without anchoring it). → the direct readers
  * the lines from the header of a PINNED_TABLES table ([audit], [anchor_hub]) to its first code line are as they were (a suite's pattern
    takes the header line and the one after it as one text); a comment or a blank line put there is a change. So is a change at, or directly
    after, the first line of the file (stackshot/cli.py anchors `\\A(# stackshot\\.example\\.toml)` on it for the configs it writes; the
    test is wider than that line on purpose, the safe side).
Anything else selects the direct readers AND the fixture readers (the behaviour before this rule): any change to a code line, a trailing
comment or the whitespace before it included; any key, table, inline table or array-of-tables row added, removed or moved; a value
changed; an uncommented sample; a comment that is not plain. What a fixture suite breaks on depends on where a line lands and on text
a suite patches (`re.subn(...); assert n == 1`, a bare str.replace, a regex anchored on a header), and no rule short of "the code is
untouched" has held up against the edits reviewers tried, so none is attempted. A text that does not parse (old or new) → all; the link
itself changes → all (rule 2 above). The names come from ONE place, the constants of tests/_instance.py at the target commit, read by
ast.literal_eval (no import of repo code); the scenario of this tool runs apply() and fails when it changes a name the constants do not
list, which holds for a name in a hardcoded `_set` or append of apply() (a name dropped from a constant and from apply() together is not
caught). A _instance.py that cannot be read this way makes every change to the example count as a change of code.
SUITEMAP_EXAMPLE_RULE=A1 (A2 by default; any other value is an error, checked when a command starts) leaves no cheap case: every change
to the example, a comment included, selects the fixture readers too (the old behaviour of the file), for the day a comment edit is found
to break a fixture suite: no code change, set it in tests.yml's selection step. Until main's next measured run records the link for the
fixture suites, the map lists the real path for every suite that opened it, so the old behaviour (every suite that read the file) holds by
itself. `audit` applies the same rule on both maps.

Docstrings (Wed Nov 11th 2026). A docstring is a line of the function's body, so editing only the docstring of a function every suite calls
selected every suite that ran it (136 of 207 for one edit of waiting.mover_of), though the text can be seen only by code that reads it. Now,
for a MODULE-LEVEL function with no decorator, or only PURE_DECORATORS, whose docstring is alone on its lines (nothing of the def or of
another statement shares them), a change whose changed lines in that function are all docstring lines is not a change of its body:
  * the file's own text readers still run (rule 6: the `whole` of the map: inspect.getsource, a test that greps the file);
  * the suites whose own file names the function (`server.f.__doc__`, `from m import f`) run, found as the suites that read the name (see
    *names*), and the registrations at module level that read the name (a call such as mcp.tool()(f) is an effect that takes the file
    whole). A suite that reads names wide (getattr(module, <not a literal>), a module loaded by a path in a variable) is not chosen by that:
    it does not name the function, and the old rule chose it only if it ran the function;
  * every suite that ran code which reads a docstring itself (an attribute `__doc__`, getattr(x, "__doc__"), getdoc or an alias of it made by
    `from inspect import getdoc as gd`, get_docstring, render_doc, help) or hands a
    function to a registry that builds a description from it (add_tool, from_function, add_resource, add_prompt, mcp.tool(...)(fn)): DOC_CALLS;
    the checkout has none today, so this adds nothing now;
  * not the suites that only ran the body, and not the callers of the function.
A function whose docstring changed together with a line of its code or its def (a signature, a decorator), a decorated function (the decorator
reads the docstring at import: an @mcp.tool's is the description a session reads), a method or a nested function (its name is no key a suite
reads by: `obj.method`), a class, and the module's own docstring (read by name already: `client.__doc__`) are selected as before. So is a
module that calls globals(). Limits, kept honest: a changed line that is blank or starts with `#` inside an undecorated docstring selects nothing (the line loop skips it as
a comment, as it always did); a suite that fetches a function by a variable name (getattr(module, name), inspect.getmembers,
`from m import *`) and then reads its docstring is not reached by name, and a suite's own docstring reads are not a guard (the name rule
handles suites), so help(getattr(m, n)) in a suite is covered by neither. The tripwire in tests/suitemap_scenario.py selects nothing: it
only makes a new use fail that scenario. It scans every Python file of the checkout (a .py file or a script with a python shebang) for the
common forms (.__doc__, getdoc, getmembers, get_docstring, render_doc, help(...), getattr(x, "__doc__"), pydoc, doctest, `import *`, and the
registries add_tool, .tool(, .resource(, .prompt(, .command(, add_api_route, from_function, add_resource, add_prompt, as a call, a bare call
of the double form tool()(f) or a decorator) and pins the number of uses of each form per file, so a new use, in a file with an entry or not,
fails until its author has looked at it. Left out because no code here uses them and they are implausible: vars(fn)["__doc__"],
operator.attrgetter("__doc__"), an eval or exec string, and a registry applied through a variable (click, typer or fastapi by another call
shape). A module-level function a suite reads by one of those is selected only if the suite names it.
SUITEMAP_DOCSTRING_RULE=D1 (D2 by default; any other value is an error, checked when a command starts) gives
the old rule everywhere: a docstring is part of the body. `audit` applies the same rule on both maps.

Imports and annotations (Thu Nov 12th 2026). Two things made an edit of an import line reach far more than it changes. (1) The line bound EVERY
name on it, so adding `Iterable` to `from typing import Any` reached the readers of Any too. (2) A name used only in an annotation counted as a read,
so a def whose parameters were annotated with it reached every suite that called the def (205 suites for one `Iterable` added to the typing import of
stackshot/core/config.py on the map of that day, 22 now, which are the readers of every name of a path-loaded module; the core files all use postponed
annotations). Now:
  * I2: when the two files differ in their module-level imports by names ADDED and by nothing else, a changed import statement binds only the added
    local names (a line reformatted, parenthesised or split binds none). Any other import edit keeps the old rule, every name on the changed line: a
    name removed (the importer may fail with a NameError at import, and what it registers there is then wrong), renamed, taken from another module,
    imported twice, swapped with another import of the same name, or moved below other code (`pure_import_add` compares the imports in order, the
    other statements between them as one marker each run). A statement of one of ours that is not quiet still takes the file whole, and a name read
    in code is read as before. Several statements on one line (`import os; X = 1`) are each a changed statement.
  * An import the file GAINS (a name added, or renamed to) that may not resolve takes the file whole, whatever the narrowing says: the importers would fail
    at import, and an annotation-only name is no read to show it. A name taken from one of our modules is looked up in that module's own bindings (a def,
    a class, an assignment, an import there, a module of that name below it; the module must exist; a bare annotation, a name bound only under
    `if TYPE_CHECKING:` and a deleted name are no binding). A name that is not there, a module whose names are not
    all known (a star import, __getattr__, globals()), a star import added, a relative import that leads to nothing of ours and `import a.b` of a missing
    module of ours are unchecked. A library import is looked up as far as it can be without side effects: a stdlib module must have the name added (as an
    attribute, or as a submodule), a stdlib module this platform does not have (`import msvcrt` on Linux) is unchecked, a top-level package that is neither
    the stdlib's nor installed is unchecked, a stdlib module that does something at import (antigravity, tkinter, ...) and any `__main__` below a package
    (`import unittest.__main__`) are never imported, bare or with `from`, and their import is unchecked, and so is any probe that fails. A bare `import X`
    is only looked up (importlib.util.find_spec), never run. A name from an installed package cannot be looked up: it keeps the I2 narrowing.
  * N2: in a file with `from __future__ import annotations`, the names of an annotation are no read when it annotates (a) a parameter or the return of
    a def with no decorator, or only a decorator that wraps (property, staticmethod, classmethod, abstractmethod, lru_cache, cache, cached_property,
    contextmanager, asynccontextmanager, overload), whose name is only ever CALLED in the whole checkout (a bare identifier used as a value anywhere, in a .py file or a script
    with a python or `uv run` shebang, as an argument, an assignment, a decorator, an attribute read that is not called, or as a string, makes the def's
    annotations read as before: that function object may reach typing.get_type_hints, functools.wraps, a registry; a name imported under another name
    (`from m import f as h`, followed across files) carries it to f; a script that does not parse makes every def count), or (b) a local variable inside a function (never evaluated). The parameters of a class's __init__, __call__, __new__ and __post_init__ are
    read through the class (inspect.signature(Cls), a framework that builds its fields), so they escape with the CLASS's name; a method name of those three (or __post_init__) used as a value anywhere (get_type_hints(C(1).__init__), get_type_hints(OBJ.__call__),
    a class decorator or an __init_subclass__ doing it to cls.__init__) makes every class-keyed name escape. In this repository that
    escape is ON for good: stackshot/cli.py reads `argparse.ArgumentParser.__init__` as a value (line 1007) and tests/package_layout_scenario.py does too
    (line 156), so all the class-keyed names (26 distinct names, in 20 files) always count as reads, which errs toward more suites; the negative control of the scenario
    (ESC7, a class only called) describes a state this checkout never reaches. Everything else that
    annotates keeps counting: the annotations of a def with another decorator (@mcp.tool: the registry evaluates them), of a class body (a dataclass,
    NamedTuple or pydantic model field, a class inside a function included), of a module-level variable, a default value, a decorator, and every
    annotation of a file without postponed annotations (they run at import). A change of the `from __future__ import annotations` line itself takes the
    file whole.
  * The import statement keeps its own dependency: a name taken from another of our modules (`from tmod import Tag`) whose only uses are dropped
    annotations is still needed by the statement, so a change to that name in its module takes the importing file whole (the import fails otherwise).
  * Limits, kept honest: a function fetched by a variable name (getattr(module, name), inspect.getmembers, `from m import *`, globals()) and then handed to
    typing.get_type_hints, inspect.signature with eval_str or a registry is not seen (as for a docstring); the tripwire in tests/suitemap_scenario.py pins the number of uses of those forms per file (get_type_hints,
    get_annotations, __annotations__, __annotate__, eval_str, annotationlib, TypeAdapter, create_model, validate_call, update_wrapper, __wrapped__, wraps,
    a subscript by "__annotations__"), so a new use fails that scenario until its author has looked at it. A name inside a quoted annotation is not a read either way.
SUITEMAP_IMPORT_RULE=I1 and SUITEMAP_ANNOTATION_RULE=N1 give the old selection, plus two differences that are always wider (I2 and N2 by default; any other
value is an error, checked when a command starts): turning postponed annotations on or off takes the file whole under either rule (py_change), and a read of
a name that a try/except fallback or a second line imports twice reads every source of it (ModNames.keys, froms_all). `audit` applies the same rules on both maps.

Route registrations (Thu Nov 12th 2026). A function decorated `@mcp.custom_route(...)` (an HTTP route of the server: /health, /api/..., the pages)
bound the key every registration binds, "<enumerate>", so every suite that reads the registry by ANY enumerating attribute (list_tools, get_tools,
http_app, routes, ...) was selected for a one-line edit of one route (128 suites for one route of stackshot/web/server.py on PR 127). Most of them only
list the tools; a route is no tool. Now (R2):
  * A custom_route binds its OWN key, "<enumerate-routes>" (ENUMERATE_R), and not "<enumerate>". @mcp.tool, @mcp.resource and @mcp.prompt keep binding
    "<enumerate>". A function decorated with both a route and one of those binds both keys.
  * The readers of the routes match it: an attribute read of one of ROUTE_ATTRS (http_app, routes, streamable_http_app, sse_app,
    _additional_http_routes, _get_additional_http_routes, run_async, run_http_async) reads BOTH keys, so it matches a tool edit and a route edit.
    run_async and run_http_async are in the set because a suite that starts the server (`mcp.run_async(transport="http")`, the way _serve does, or a
    subprocess that runs it) serves every route over real HTTP, whether or not it names http_app. list_tools, get_tools and every other attribute of
    ENUMERATE_ATTRS read only "<enumerate>": a suite that lists the tools does not see a route.
  * What stays wide: a reader that names the route's own function (`server.health`) is selected by that name, one that reads the file as text by the map's file half,
    and a function that builds or serves the app (reads one of ROUTE_ATTRS) reaches every suite that ran it by the map, as before. Any
    wildcard reader of a module (getattr(mod, name) with a name that is not a literal, vars(mod), dir(mod), inspect.getmembers(mod), a module loaded by a path) reads
    every name of that module, the route's function included, so it is selected as before. An attribute read of a name in neither set is not an enumeration, as before.
  * Limits, kept honest: `getattr(mcp, name)` with a name that is not a literal, or vars(mcp) / dir(mcp), on an object that is not a module of ours, gives
    no key today for tools either (177 non-literal getattr calls in the checkout, most of them forwarders); a literal `getattr(x, "list_tools")` gives
    none either; `from m import *` is no wildcard read (no star import of our modules exists in the checkout). `.routes` also matches any other object's `.routes` (a false positive, wider). A decorator on a method inside a class body is not
    examined, for tools too.
SUITEMAP_ROUTE_RULE=R1 (R2 by default; any other value is an error, checked when a command starts) gives the old selection: a custom_route binds
"<enumerate>" and ROUTE_ATTRS adds nothing. `audit` applies the same rule on both maps.

Class attributes (Thu Nov 12th 2026). A line inside a class body (`Board._SENT = {...}` in stackshot/web/render.py) is module-level code, so an
edit of one bound the whole class name, and the `own` rule then selected every suite that ran ANY scope of the class (183 suites for web/render.py alone,
most of them running other methods of Board). Now (C2):
  * A changed line that lies only inside direct class-body assignments (`x = <literal>`, plain names, the value `ast.literal_eval`-able) of a plain
    top-level class binds the key (module, ".x"), the ATTRIBUTE, and not the class. A plain class is undecorated, has no keywords and no bases (or only
    `object`). The old tree is read too, so a removed or renamed attribute binds its old name as well; a private name `__x` also binds `_Cls__x`.
  * The readers of `.x` are the suites that run code that reads it: any attribute access `.x` (a load, a store, a delete, an augmented assignment and a
    `case C(x=...)` pattern all read the class value), and any string that names it (`"x"`, as getattr(obj, "x") and a registry do) or holds it as a token
    (a format string `"{x}"`, a dotted string such as `"Cfg.x"`, of any length: a script a suite hands to a subprocess is scanned whole). A string with
    neither a `.` nor a `{` that merely contains the name is not scanned (a limit). A module-level statement that runs at import and reads it takes its file whole, as for a name.
  * The key (".*") is read by every dynamic access to attributes: getattr / setattr / hasattr / delattr / inspect.getattr_static with a name that is not a
    literal (or an argument with `*` or `**`), vars, dir, inspect.getmembers, operator.attrgetter / methodcaller with a non-literal, `.__dict__`,
    `.__getattribute__`, a builtin of that list handed over as a value (map(getattr, ...)), a non-literal eval or exec, `patch.multiple(Cls, **kw)`. It matches every attribute edit.
    The keywords of `patch.multiple(Cls, K=1)` read `.K`.
  * NOT narrowed, the class is bound as before (over-selection is the safe side): a decorated class or one with bases or keywords; a class that defines
    `__getattr__`, `__getattribute__`, `__init_subclass__`, `__set_name__`, `__class_getitem__` or `__slots__`; a class that calls locals / vars / dir /
    globals / eval / exec in its body; a name that is read as a bare Name in the class body (a derived attribute: `B = A + 1`, a decorator, a default, a
    lambda or a comprehension there); a value that is not a literal; an AnnAssign (dataclass and get_type_hints machinery
    reads annotated names without writing them); a dunder name; any changed line that is also part of another kind of statement; an import.
  * Two accesses are no dynamic read: `self.__dict__` and `vars(self)` in a method (an instance's dict holds no class attribute), and getattr / vars on a
    module object. A module object is a name that this file binds only by `import x`, `import x as y`, `m = importlib.import_module(...)`,
    `m = __import__(...)` or `m = sys.modules[...]` (or one of those calls written in place); a name bound any other way, anywhere in the file, is not one.
    A forwarder such as puller.py (`vars(_real)` of an imported module) therefore does not read every attribute of every class.
  * Limits, kept honest: code that reads an attribute by name from the text of a file (a template, a C extension) is not seen (none in the checkout today);
    a method that receives a class as its `self` by hand is taken for an instance; a `self.__dict__` in a class body of its own is the same case. Where
    a use looks like neither, it is a dynamic read.
SUITEMAP_CLASS_RULE=C1 (C2 by default; any other value is an error, checked when a command starts) binds the whole class for every edit inside its body, as
every edit did before C2. It is not simply a superset of C2: the plain `.x` readers in other modules that C2 adds are not looked for under C1.
`audit` applies the same rule on both maps.

Shards (Mon Nov 2nd 2026). Main's measured run was one job on one runner (60 to 80 min) while the pool's other runners sat idle,
and every release waits for it. Now tests.yml runs it as a matrix of SHARDS jobs on the same labels, each `measure` over
`shard --of SHARDS --index I`, and the `suites` job merges their maps (`merge`) and passes only when every shard passed and the
merged map has every suite exactly once. `shard_plan` puts every suite in exactly one shard: with a map, the longest suites
first, each into the shard with the least measured time so far (a suite the map does not know counts as the median; ties go by
name and then the lower shard), so the shards end at about the same time; without a map (or one with no times), a stable hash
of the name. The plan is made ONCE per run, by the `shards` job (`plan`, with the map from the cache, or none: a cache miss gives the hash
plan, for all six lists alike), and handed to the `measure` matrix as job outputs; each shard runs the list it is given and
does not plan, so a cache miss in one shard cannot make it plan differently from the others. `merge` still finds the suite that
is in none or in two, and the run fails.
"""
import argparse, ast, atexit, collections, datetime, difflib, hashlib, json, os, re, shutil, signal, subprocess, sys, tempfile, time, tomllib

FORMAT = 1
TRACE_MAX_AGE = 24   # hours: a suite's files are traced again at least this often
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.environ.get("SUITEMAP_ROOT") or os.path.dirname(HERE))
INNER = {"scratch": ("rename", "redact", "lead", "migration")}   # outer suite -> the suites it runs itself (rule above)
HARNESS = (".github/", "tests/run-suite", "pyproject.toml", "uv.lock", "tests/suitemap.py")
# data files the selection reads by what they hold (see *The example config* above): file -> the tracked link the fixture suites read it through.
# Another data file joins by a line here; a change to a link selects everything (the link is what the fixture readers' map entries name).
DATA = {"stackshot.example.toml": "tests/example_base.toml"}
INSTANCE = "tests/_instance.py"   # where the names the fixture suites' config building touches are declared (see *The example config*)


def example_rule():
    """A2 (default): a change of blank lines and plain comments only selects the direct readers; A1: every change to the example selects the fixture readers too"""
    v = os.environ.get("SUITEMAP_EXAMPLE_RULE", "A2").strip().upper()
    if v not in ("A1", "A2"):
        raise SystemExit(f"suitemap: SUITEMAP_EXAMPLE_RULE={os.environ.get('SUITEMAP_EXAMPLE_RULE')!r} is not a rule: the allowed values are A1 and A2")
    return v


def docstring_rule():
    """D2 (default): a change confined to the docstring of a module-level function with no decorator that reads it selects by name, not by
    what ran the function; D1: a docstring is part of the function's body, as before (see *Docstrings*)"""
    v = os.environ.get("SUITEMAP_DOCSTRING_RULE", "D2").strip().upper()
    if v not in ("D1", "D2"):
        raise SystemExit(f"suitemap: SUITEMAP_DOCSTRING_RULE={os.environ.get('SUITEMAP_DOCSTRING_RULE')!r} is not a rule: the allowed values are D1 and D2")
    return v
def import_rule():
    """I2 (default): when a change only ADDS names to the module-level imports, a changed import line binds only the added names; any other import edit (a name removed or
    renamed, taken from another module, moved) binds every name on the changed line, as I1 does; I1: every name on the line, always (see *Imports and annotations*)"""
    v = os.environ.get("SUITEMAP_IMPORT_RULE", "I2").strip().upper()
    if v not in ("I1", "I2"):
        raise SystemExit(f"suitemap: SUITEMAP_IMPORT_RULE={os.environ.get('SUITEMAP_IMPORT_RULE')!r} is not a rule: the allowed values are I1 and I2")
    return v


def route_rule():
    """R2 (default): a route (@mcp.custom_route) binds its own key and only the readers of the routes match it; R1: a route binds <enumerate>, as every
    registered function did, so every reader of any listing attribute matches it (see *Route registrations*)"""
    v = os.environ.get("SUITEMAP_ROUTE_RULE", "R2").strip().upper()
    if v not in ("R1", "R2"):
        raise SystemExit(f"suitemap: SUITEMAP_ROUTE_RULE={os.environ.get('SUITEMAP_ROUTE_RULE')!r} is not a rule: the allowed values are R1 and R2")
    return v


def class_rule():
    """C2 (default): an edit of a literal assignment in the body of a plain class binds the attribute (module, ".name"), and only the readers of that attribute
    match it; C1: it binds the class, as every edit inside a class did before C2, so every suite that ran any scope of the class matches it (the plain `.attr`
    readers in other modules that C2 adds are not looked for) (see *Class attributes*)"""
    v = os.environ.get("SUITEMAP_CLASS_RULE", "C2").strip().upper()
    if v not in ("C1", "C2"):
        raise SystemExit(f"suitemap: SUITEMAP_CLASS_RULE={os.environ.get('SUITEMAP_CLASS_RULE')!r} is not a rule: the allowed values are C1 and C2")
    return v


def annotation_rule():
    """N2 (default): in a file with postponed annotations, a name used only in the annotations of a plain function that is only ever called, or of a
    local variable, is not a read; N1: every annotation name is a read (see *Imports and annotations*)"""
    v = os.environ.get("SUITEMAP_ANNOTATION_RULE", "N2").strip().upper()
    if v not in ("N1", "N2"):
        raise SystemExit(f"suitemap: SUITEMAP_ANNOTATION_RULE={os.environ.get('SUITEMAP_ANNOTATION_RULE')!r} is not a rule: the allowed values are N1 and N2")
    return v


# the methods whose parameter annotations a class's callers read through the class (see ModNames.mark_annotations)
CLASS_CALLS = {"__init__", "__call__", "__new__", "__post_init__"}
SUITE_RE = re.compile(r"tests/(\w+)_scenario\.py$")
# what strace records: the calls that open, stat, run or look for a path, and the forks (to know which program a pid runs)
TRACE = ("open,openat,openat2,creat,execve,execveat,stat,lstat,newfstatat,statx,access,faccessat,faccessat2,readlink,"
         "readlinkat,clone,clone3,fork,vfork")


def git(*a, check=False):
    r = subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout if r.returncode == 0 else None


def suites():
    return sorted(SUITE_RE.match(f).group(1) for f in (git("ls-files", "tests/") or "").split("\n") if SUITE_RE.match(f))


# ---------------------------------------------------------------- scopes
MAIN = "<main>"


def is_main_guard(node):
    t = getattr(node, "test", None)
    return (isinstance(node, ast.If) and isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value == "__main__")


def scopes(src):
    """(body_of, header, ddoc, tree) for a module's source, or None when it does not parse. body_of[line] is the qualified
    name of the innermost function whose body holds the line, '<main>' in the body of a top-level `if __name__ ==
    "__main__":` (only a suite that runs the file as a program runs it), '' at module level (imports, constants, class
    bodies, def lines); header[line] = (qualname, decorated) for a function's decorator, def and signature lines; ddoc holds
    the docstring lines of functions with a decorator that may read them (any but PURE_DECORATORS); pdoc maps the docstring
    lines of a module-level function with no such decorator (none, or only PURE_DECORATORS) to the function's name, when
    the docstring is alone on its lines (see *Docstrings* above)."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    n = src.count("\n") + 2
    body_of, header, ddoc, pdoc = [""] * (n + 1), {}, set(), {}
    text = src.split("\n")

    def walk(node, prefix, top):
        for ch in ast.iter_child_nodes(node):
            if top and is_main_guard(ch):
                for st in ch.body:
                    for ln in range(st.lineno, min(st.end_lineno or st.lineno, n) + 1):
                        body_of[ln] = MAIN
                walk(ch, f"{MAIN}.", False)
            elif isinstance(ch, ast.ClassDef):
                walk(ch, f"{prefix}{ch.name}.", False)
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q, b0 = f"{prefix}{ch.name}", ch.body[0]
                for ln in range(b0.lineno, min(ch.end_lineno or b0.lineno, n) + 1):
                    body_of[ln] = q
                for ln in range(min([d.lineno for d in ch.decorator_list] + [ch.lineno]), b0.lineno):
                    header[ln] = (q, bool(ch.decorator_list))
                # a decorator that only wraps (@staticmethod, @functools.wraps) never reads the docstring: it stays the body's
                is_doc = isinstance(b0, ast.Expr) and isinstance(b0.value, ast.Constant) and isinstance(b0.value.value, str)
                if is_doc and any(dotted(d.func if isinstance(d, ast.Call) else d) not in PURE_DECORATORS for d in ch.decorator_list):
                    ddoc.update(range(b0.lineno, (b0.end_lineno or b0.lineno) + 1))
                elif is_doc and not prefix:
                    # a module-level function's docstring on lines of its own: nothing before it on its first line (the def's
                    # tail, a `;`), no statement after it on its last
                    first = text[b0.lineno - 1].encode()[: b0.col_offset] if 0 < b0.lineno <= len(text) else b"x"
                    if first.strip() == b"" and (len(ch.body) == 1 or ch.body[1].lineno > (b0.end_lineno or b0.lineno)):
                        pdoc.update({ln: ch.name for ln in range(b0.lineno, (b0.end_lineno or b0.lineno) + 1)})
                walk(ch, f"{q}.<locals>.", False)
            else:
                walk(ch, prefix, False)

    walk(tree, "", True)
    return body_of, header, ddoc, tree, pdoc


# ---------------------------------------------------------------- names
# A module-level change that only binds names (a def or class without decorators, an assignment to plain names whose value
# only computes, the module docstring, an import of a library) reaches the code that READS those names, not every suite
# that imported the file: the functions whose bodies name them (followed across `import x` and `from x import y`, and on
# through the module-level bindings that use them), what the bound function or class itself runs, and the suites whose own
# file names them (server._start_background). Anything else at module level runs at import with effects no name shows (a
# decorator we do not know, a call statement, an import of one of ours that runs more than bindings): every suite that ran
# the file. Reads no name shows are taken wide: globals() in a module (any of its names), getattr(module, <not a literal>)
# and vars(module) (any of that module's), a module loaded by path (any name of the files it can be).
# A tool parameter constant (Annotated[…, Field(…)]) and HERE = Path(__file__).resolve().parent only bind a name (Field and the
# Path methods are pure on a receiver that starts at Path(…) or __file__: PATH_METHODS); the headers (a def's, a method's) that
# annotate with a constant read it at import. A FastMCP(…) server object, an unknown call, a Path method on any other receiver,
# or a Field(…) holding an impure call stays an effect. The calls inside a function header are not checked.
PURE_CALLS = {
    "re.compile", "frozenset", "set", "dict", "tuple", "list", "str", "int", "float", "bool", "bytes", "len", "sorted", "range",
    "enumerate", "zip", "max", "min", "sum", "any", "all", "repr", "ord", "chr", "object", "isinstance", "pathlib.Path", "Path",
    "Path.home", "pathlib.Path.home", "os.path.join", "os.path.expanduser", "os.path.dirname", "os.path.abspath", "os.path.realpath",
    "os.path.basename", "os.environ.get", "os.getenv", "textwrap.dedent", "dedent", "json.dumps", "json.loads", "threading.Lock",
    "threading.RLock", "threading.Event", "threading.local", "threading.Condition", "queue.Queue", "collections.defaultdict",
    "defaultdict", "collections.OrderedDict", "OrderedDict", "collections.Counter", "Counter", "collections.namedtuple",
    "namedtuple", "logging.getLogger", "datetime.timedelta", "timedelta", "datetime.timezone", "ZoneInfo", "zoneinfo.ZoneInfo",
    "hashlib.sha256", "functools.partial", "partial", "string.Template", "contextvars.ContextVar", "asyncio.Lock", "asyncio.Event",
    "Field", "pydantic.Field"}
PURE_METHODS = {"get", "replace", "split", "rsplit", "join", "strip", "lstrip", "rstrip", "format", "lower", "upper", "title",
                "encode", "decode", "splitlines", "startswith", "endswith", "items", "keys", "values", "copy", "removeprefix",
                "removesuffix", "casefold", "partition", "rpartition", "zfill", "ljust", "rjust", "center", "count", "find"}
# Path methods that only compute a path are pure only on a receiver that is a path: a chain that starts at Path(…), Path.home()
# or __file__. On any other receiver the name says nothing (`_r.resolve()` may be our own method that prints or sets state).
PATH_METHODS = {"resolve", "absolute", "expanduser", "joinpath", "with_name", "with_suffix", "as_posix"}
PATH_ROOTS = {"Path", "pathlib.Path", "Path.home", "pathlib.Path.home"}
# a call to one of our own functions in a module-level assignment computes the value from our code (what that code runs at
# import is the callee's, measured); its effects are its body's, which a change to the call's arguments does not touch
REPO_CALLS_BIND = True
DYN_LOAD = {"spec_from_file_location", "importlib.util.spec_from_file_location", "run_path", "runpy.run_path"}
# decorators that only wrap or describe what they decorate: a change under them is the function's own
PURE_DECORATORS = {"functools.wraps", "wraps", "functools.lru_cache", "lru_cache", "functools.cache", "cache",
                   "functools.cached_property", "cached_property", "property", "staticmethod", "classmethod",
                   "contextlib.contextmanager", "contextmanager", "contextlib.asynccontextmanager", "asynccontextmanager",
                   "dataclasses.dataclass", "dataclass", "typing.overload", "overload", "functools.total_ordering",
                   "total_ordering", "abc.abstractmethod", "abstractmethod", "functools.singledispatch", "singledispatch"}
# decorators under which a def's annotations are still nobody's read (see *Imports and annotations*): they only wrap or describe what they decorate
# and never evaluate the annotations (singledispatch.register does, a registry does, dataclass reads a class's)
PLAIN_DECORATORS = {"property", "staticmethod", "classmethod", "abc.abstractmethod", "abstractmethod", "functools.lru_cache", "lru_cache",
                    "functools.cache", "cache", "functools.cached_property", "cached_property", "contextlib.contextmanager", "contextmanager",
                    "contextlib.asynccontextmanager", "asynccontextmanager", "typing.overload", "overload"}
# A decorator on one of the module's own objects (@mcp.tool, @mcp.custom_route) registers the function there: its name,
# signature and description are read by whoever calls it (it ran the body: measured) and by whatever lists the registry.
# Listing is a call of one of these, on any object (a suite lists tools through its MCP client): the key (*, <enumerate>).
# A route (@mcp.custom_route) is none of tool, resource or prompt: it binds its own key, <enumerate-routes>, and only a reader of the routes
# (ROUTE_ATTRS) matches it (see *Route registrations*). A decorator with both (@mcp.tool and @mcp.custom_route on one function) binds both keys.
# Code that reads a function's docstring, or hands the function to a registry that does (a tool server builds its description from it): a
# docstring-only change reaches every suite that ran such code (see *Docstrings*). None of it exists in the checkout's own code today.
DOC_CALLS = {"getdoc", "get_docstring", "render_doc", "help", "add_tool", "from_function", "add_resource", "add_prompt"}
DOC_REGISTER = {"tool", "resource", "prompt"}   # mcp.tool(...)(fn) called as a function, not as a decorator
ENUMERATE = "<enumerate>"
ENUMERATE_ATTRS = {"list_tools", "get_tools", "_list_tools", "list_resources", "get_resources", "list_prompts", "get_prompts",
                   "list_resource_templates", "_tool_manager", "http_app", "routes"}
ENUMERATE_R = "<enumerate-routes>"
# what reads or serves the route list: the attributes that hand out the ASGI app (http_app; streamable_http_app and sse_app of earlier FastMCP releases), the list
# itself (routes; _additional_http_routes and its getter) and the calls that build the app and serve it (run_async, run_http_async: a suite that starts the server
# as a process and asks it for a page reads every route). Each of them reads BOTH keys (the app and the server serve the tools too, so a tool edit reaches them as well)
ROUTE_ATTRS = {"http_app", "routes", "streamable_http_app", "sse_app", "_additional_http_routes", "_get_additional_http_routes", "run_async", "run_http_async"}
# Class attributes (see *Class attributes*). An edit of `_SENT = {...}` in a class body binds the key (module, "._SENT") instead of the class; a read of it is
# the key ("*", "._SENT"): an attribute access `.x`, a string that names it. ATTR_ANY reads every attribute: a dynamic access by a name that is a value.
ATTR_ANY = ("*", ".*")
# a class that defines one of these is never narrowed: the interpreter or a framework reads its attributes without naming them
ATTR_NEVER = {"__getattr__", "__getattribute__", "__init_subclass__", "__set_name__", "__class_getitem__", "__slots__"}
ATTR_BY_NAME = {"getattr", "setattr", "hasattr", "delattr", "getattr_static"}   # an attribute looked up by a name that is a value (dynamic unless the name is a literal)
ATTR_ALL = {"vars", "dir", "getmembers", "getmembers_static"}                  # all of an object's attributes
ATTR_NAMES = {"attrgetter", "methodcaller"}                                    # operator.attrgetter(name)
ATTR_VALUES = {"getattr", "setattr", "hasattr", "delattr", "vars", "dir"}      # the builtins handed over as a value (map(getattr, objs, names), partial(getattr, obj))
ATTR_DICT = {"__dict__", "__getattribute__"}                                   # a namespace, an explicit lookup by name
ATTR_BODY_CALLS = {"locals", "vars", "dir", "globals", "eval", "exec"}         # in a class body: the class's own namespace, read as a whole
ATTR_TOKEN = re.compile(r"[A-Za-z_]\w*")
SELF_DECORATORS = PLAIN_DECORATORS - {"staticmethod", "classmethod"}            # a method under any other decorator may be a class method: its `self` is not an instance


def modname(path):
    """the name a repo .py file is imported as; tests/ helpers by their bare name (the suites put tests/ on sys.path)"""
    p = path.removesuffix(".py")
    p = p[len("tests/"):] if p.startswith("tests/") else p
    p = p[: -len("/__init__")] if p.endswith("/__init__") else p
    return p.replace("/", ".")


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def eval_nodes(roots):
    """every node under the roots that runs when they are evaluated: a function's header (decorators, defaults, annotations) is part of it, its body is not
    (the body is a scope of its own, with its own reads)"""
    stack = list(roots)
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ar = n.args
            stack.extend(x for x in [*n.decorator_list, *ar.defaults, *ar.kw_defaults, n.returns,
                                     *[a.annotation for a in [*ar.posonlyargs, *ar.args, *ar.kwonlyargs, ar.vararg, ar.kwarg] if a is not None]] if x is not None)
        else:
            stack.extend(ast.iter_child_nodes(n))


def module_bindings(tree):
    """(names, open): the names a module's level binds that can be seen without running it (a def, a class, an assignment, a loop or with target, an
    import alias, anywhere in its statements but inside a function, a class or a comprehension), and whether more may come from where no name shows:
    a star import, a module-level __getattr__, a call of globals(). A name outside the set of an `open` module is not known to be missing.
    A name that fails at runtime is no binding: a bare annotation (`X: int`), a name bound only under `if TYPE_CHECKING:`, a name `del`eted"""
    names, opened, deleted = set(), False, set()

    def children(node):
        if isinstance(node, ast.If) and dotted(node.test) in ("TYPE_CHECKING", "typing.TYPE_CHECKING"):
            return [node.test, *node.orelse]   # the body never runs
        if isinstance(node, ast.AnnAssign) and node.value is None:
            return [node.annotation]           # `X: int` binds nothing
        return ast.iter_child_nodes(node)

    def walk(node):
        nonlocal opened
        for ch in children(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(ch.name)
                if ch.name == "__getattr__":
                    opened = True
            elif isinstance(ch, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                continue
            elif isinstance(ch, ast.Import):
                names.update((a.asname or a.name).split(".")[0] for a in ch.names)
            elif isinstance(ch, ast.ImportFrom):
                for a in ch.names:
                    if a.name == "*":
                        opened = True
                    else:
                        names.add(a.asname or a.name)
            else:
                if isinstance(ch, ast.Name):
                    if isinstance(ch.ctx, ast.Store):
                        names.add(ch.id)
                    elif isinstance(ch.ctx, ast.Del):
                        deleted.add(ch.id)
                    elif ch.id == "globals":
                        opened = True
                elif isinstance(ch, ast.ExceptHandler) and ch.name:
                    names.add(ch.name)
                elif isinstance(ch, (ast.MatchAs, ast.MatchStar)) and ch.name:
                    names.add(ch.name)
                elif isinstance(ch, ast.MatchMapping) and ch.rest:
                    names.add(ch.rest)
                walk(ch)
    walk(tree)
    return names - deleted, opened


class ModNames:
    """what one Python file binds at module level and which names each of its scopes reads, as (module, name) keys;
    (module, '*') reads every name of the module"""

    def __init__(self, path, src, repo_mods):
        self.path, self.mod, self.repo = path, modname(path), repo_mods
        sc = scopes(src)
        self.ok = sc is not None
        self.refs = collections.defaultdict(set)   # scope → keys read
        self.stmts = []                             # (first, last, kind, names, keys read by the statement at import)
        self.functions, self.classes = set(), set()
        self.effect_targets = {}                    # first line of an effect-mod statement → the modules it sets state in
        self.text, self.ddoc, self.pdoc, self.body_of = [], set(), {}, []
        self.docreads = set()                       # scopes that read a docstring, or hand a function to a registry that does
        self.postponed, self.imports, self.import_ids = False, {}, set()   # import_ids: the indexes in stmts of the Import and ImportFrom nodes (`import os; os = 1` holds an import and a plain statement on one line)
        self.annot_skip, self.ann, self.ann_stmt = {}, [], []   # see *Imports and annotations*
        self.class_keyed = set()                     # the class names under which the __init__, __call__ and __new__ annotations wait (mark_annotations)
        self.attrs, self.narrow = False, {}          # class rule C2 (see *Class attributes*): attribute keys are read; narrow[line] = the attribute names of the class-body assignment that holds the line
        self.callees, self.binds, self.mod_objs, self.self_ok = set(), set(), set(), set()   # attr_setup: ids of the callee of every call, the names the file binds, those bound only to modules, ids of `self.__dict__`
        self.attr_values = set()                     # attribute names read without being called, and the names getattr(obj, "name") asks for (Names.settle: C(1).__init__ as a value)
        self.valuse = set()                          # bare names used as a value (not just called): Names.settle
        self.import_seq, self.dropped = [], set()    # the module-level imports in order (None for another statement); (module, name) keys of repo imports whose only use was a dropped annotation
        self.aliases, self.froms, self.toplevel = {}, {}, set()   # set before the early return: reach() reads froms of every file, one that does not parse included
        self.froms_all = collections.defaultdict(list)   # local name → every (module, name) it is imported as: a try/except fallback or a second line binds the same local twice, `froms` keeps the last
        self.repo_tops = {r.split(".")[0] for r in repo_mods}
        self.defined, self.open_names = set(), False   # the names the module level binds, statically; open_names: a name may also come from a star import, __getattr__ or globals()
        if not self.ok:
            return
        self.body_of, _, self.ddoc, tree, self.pdoc = sc
        self.text = src.split("\n")
        self.postponed = any(isinstance(st, ast.ImportFrom) and st.module == "__future__" and not st.level and any(a.name == "annotations" for a in st.names)
                             for st in tree.body)
        imports = collections.defaultdict(set)      # local name → where it comes from, over the module-level import statements
        for st in tree.body:
            if isinstance(st, ast.Import):
                for a in st.names:
                    imports[(a.asname or a.name).split(".")[0]].add(("import", a.name, a.asname))
                    self.import_seq.append(((a.asname or a.name).split(".")[0], ("import", a.name, a.asname)))
            elif isinstance(st, ast.ImportFrom):
                for a in st.names:
                    imports[a.asname or a.name].add(("from", st.level, st.module, a.name, a.asname))
                    self.import_seq.append((a.asname or a.name, ("from", st.level, st.module, a.name, a.asname)))
            else:
                self.import_seq.append(None)
        self.imports = {k: frozenset(v) for k, v in imports.items()}
        if self.postponed and annotation_rule() == "N2":
            self.mark_annotations(tree)
        self.defined, self.open_names = module_bindings(tree)
        pkg = self.mod if path.endswith("/__init__.py") else self.mod.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.aliases[a.asname] = a.name
                    else:
                        self.aliases[a.name.split(".")[0]] = a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    up = pkg.split(".") if pkg else []
                    up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                    base = ".".join([*up, base] if base else up)
                for a in node.names:
                    local = a.asname or a.name
                    if f"{base}.{a.name}" in self.repo:
                        self.aliases[local] = f"{base}.{a.name}"
                    else:
                        self.froms[local] = (base, a.name)
                        self.froms_all[local].append((base, a.name))
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                m = self.literal_import(node.value)
                if m:
                    self.aliases[node.targets[0].id] = m
        for st in tree.body:
            for t in (st.targets if isinstance(st, ast.Assign) else [getattr(st, "target", None)]):
                if isinstance(t, ast.Name):
                    self.toplevel.add(t.id)
        self.attrs = class_rule() == "C2"
        if self.attrs:
            self.attr_setup(tree)
        for st in tree.body:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                self.import_ids.add(len(self.stmts))
            a, b, kind, bound, reads = self.statement(st, st is tree.body[0])
            if self.attrs and kind != "import-repo":
                reads = reads | self.attr_reads(st)   # `X = obj.attr` at import reads the attribute, as `X = obj.f` reads f
            self.stmts.append((a, b, kind, bound, reads))
        for node in ast.walk(tree):
            self.read(node)
        self.value_uses(tree)

    def mark_annotations(self, tree):
        """annot_skip[id(node)] = the def's name (None for a local variable) for every node of an annotation that is no read under N2 (see
        *Imports and annotations*): the parameters and the return of a plain def, and the annotation of a variable inside a function"""
        def visit(node, in_func, cls=None):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if all(dotted(d.func if isinstance(d, ast.Call) else d) in PLAIN_DECORATORS for d in ch.decorator_list):
                        # the annotations of a class's __init__, __call__ and __new__ are read through the CLASS (inspect.signature(Cls), a framework
                        # that builds its fields from them): they escape with the class's name, not the method's
                        key = cls if cls and ch.name in CLASS_CALLS else ch.name
                        if key == cls and cls:
                            self.class_keyed.add(cls)
                        ar = ch.args
                        for e in [ch.returns, *[x.annotation for x in [*ar.posonlyargs, *ar.args, *ar.kwonlyargs, ar.vararg, ar.kwarg] if x is not None]]:
                            if e is not None:
                                for x in ast.walk(e):
                                    self.annot_skip[id(x)] = key
                    visit(ch, True)
                elif isinstance(ch, ast.ClassDef):
                    visit(ch, False, ch.name)
                else:
                    if in_func and isinstance(ch, ast.AnnAssign):
                        for x in ast.walk(ch.annotation):
                            self.annot_skip[id(x)] = None
                    visit(ch, in_func, cls)
        visit(tree, False)

    def value_uses(self, tree):
        """the bare names this file uses as a value, not only as the callee of a call (an argument, an assignment, a decorator, an attribute read
        that is not called, a string that is a name): what makes a function's annotations reachable by a registry or typing.get_type_hints
        (see Names.settle)"""
        callee = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in callee:
                self.valuse.add(n.id)
            elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and id(n) not in callee:
                self.valuse.add(n.attr)
                self.attr_values.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.isidentifier():
                self.valuse.add(n.value)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and dotted(n.func) in ("getattr", "inspect.getattr_static") and len(n.args) > 1 \
                    and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
                self.attr_values.add(n.args[1].value)
        for local, srcs in self.froms_all.items():
            if local in self.valuse:
                self.valuse.update(name for _, name in srcs)            # from m import f as g; get_type_hints(g): f is the one that escapes

    def literal_import(self, call):
        if isinstance(call, ast.Call) and dotted(call.func) in ("__import__", "importlib.import_module") and call.args \
                and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            return call.args[0].value
        return None

    def scope(self, node):
        ln = getattr(node, "lineno", 0)
        return self.body_of[ln] if 0 < ln < len(self.body_of) else ""

    def keys(self, node):
        """the keys an expression reading a name stands for"""
        if isinstance(node, ast.Call):
            m = self.literal_import(node)
            return {(m, "*")} if m else set()
        d = dotted(node)
        if not d:
            return set()
        chain = d.split(".")
        out = {(self.mod, chain[0])}
        mod = None
        if chain[0] in self.froms:
            out.update(self.froms_all[chain[0]])
        elif chain[0] in self.aliases:
            mod = self.aliases[chain[0]]
        if mod is not None:
            rest = chain[1:]
            while rest and f"{mod}.{rest[0]}" in self.repo:
                mod = f"{mod}.{rest[0]}"
                rest = rest[1:]
            out.add((mod, rest[0]) if rest else (mod, "<module>"))   # <module>: the module object itself
            if len(rest) > 1:
                out.add(("~", mod, tuple(rest)))  # server._cfg.CFG: Names follows _cfg through server's own imports
        return out

    def doc_read(self, node):
        """record the scope of a node that reads a docstring (`x.__doc__`, getattr(x, "__doc__"), inspect.getdoc or an alias of it, a registry call: DOC_CALLS)"""
        hit = isinstance(node, ast.Attribute) and node.attr == "__doc__" and isinstance(node.ctx, ast.Load)
        if isinstance(node, ast.Call):
            f = dotted(node.func)
            # a call by its last name, or by an alias made by `from inspect import getdoc as gd`; getattr(x, "__doc__")
            hit = (f is not None and (f.split(".")[-1] in DOC_CALLS or any(n in DOC_CALLS for _, n in self.froms_all.get(f.split(".")[0], ())))) or \
                (f == "getattr" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "__doc__") or \
                (isinstance(node.func, ast.Call) and getattr(node.func.func, "attr", None) in DOC_REGISTER)
        if hit:
            self.docreads.add(self.scope(node))

    def read(self, node):
        self.doc_read(node)
        sc = None
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            sc, ks = self.scope(node), self.keys(node)
            if node.id == "globals":   # locals() is the function's own; vars(module) is the call below
                ks = ks | {(self.mod, "*")}
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            sc, ks = self.scope(node), (self.keys(node) if dotted(node) else set())
            routes_ = node.attr in ROUTE_ATTRS and route_rule() == "R2"
            if node.attr in ENUMERATE_ATTRS or routes_:
                ks = ks | {("*", ENUMERATE)}
            if routes_:
                ks = ks | {("*", ENUMERATE_R)}
        elif isinstance(node, ast.Call):
            f = dotted(node.func)
            ks = set()
            if f == "getattr" and node.args and (len(node.args) < 2 or not isinstance(node.args[1], ast.Constant)):
                ks = {(m, "*") for m, n in self.keys(node.args[0]) if n == "<module>"}
            elif f in ("vars", "dir", "inspect.getmembers") and node.args:
                ks = {(m, "*") for m, n in self.keys(node.args[0]) if n == "<module>"}
            elif f and (f in DYN_LOAD or f.split(".")[-1] in DYN_LOAD):
                # a module loaded by path: every name of the files the call's literal file name can be ("tools",
                # "state_from_fields.py"); no literal .py name: any name at all
                lit = [a.value for a in ast.walk(node) if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.endswith(".py")]
                ks = {(m, "*") for m in self.repo if lit and m.split(".")[-1] == os.path.basename(lit[-1]).removesuffix(".py")} or {("*", "*")}
            else:
                m = self.literal_import(node)
                ks = {(m, "*")} if m else set()
            sc = self.scope(node)
        if sc is not None and ks:
            if id(node) in self.annot_skip:
                self.ann.append((self.annot_skip[id(node)], sc, ks))   # an annotation of a postponed file: Names.settle decides
            else:
                self.refs[sc] |= ks
        if self.attrs:
            ak = self.attr_keys(node)
            if ak:
                self.refs[self.scope(node)] |= ak

    def attr_setup(self, tree):
        """what attr_keys needs to know about the whole file under class rule C2 (see *Class attributes*): the callee of every call, the names the file binds
        and those bound only to module objects, the `self.__dict__` of the methods, and the class-body assignments an edit narrows"""
        self.callees = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.module_objects(tree)
        self.self_dicts(tree)
        self.narrowable(tree)

    def module_value(self, v):
        """True for an expression that holds a module object: importlib.import_module(…), __import__(…), sys.modules[…]"""
        if isinstance(v, ast.Call):
            f = dotted(v.func)
            return f in ("importlib.import_module", "__import__") or (f == "import_module" and any(b == "importlib" for b, _ in self.froms_all.get(f, ())))
        return isinstance(v, ast.Subscript) and dotted(v.value) == "sys.modules"

    def is_module(self, v):
        """True when an expression is a module object: a name this file binds only by `import x` / `import x as y` / `m = importlib.import_module(…)` /
        `m = sys.modules[…]` (any other binding of the same name, in any scope, makes it unknown), or such a call or lookup itself. getattr(<module>, name)
        and vars(<module>) read a name of the module (the module rules follow those); they read no attribute of a class"""
        return isinstance(v, ast.Name) and v.id in self.mod_objs or self.module_value(v)

    def module_objects(self, tree):
        """binds: every name the file binds anywhere; mod_objs: those bound only to module objects"""
        mods, others, good = set(), set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and self.module_value(n.value):
                good |= {id(t) for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {(a.asname or a.name).split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                others |= {a.asname or a.name for a in n.names}
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                others.add(n.name)
            elif isinstance(n, ast.arg):
                others.add(n.arg)
            elif isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
                (mods if id(n) in good else others).add(n.id)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                others.add(n.name)
            elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
                others.add(n.name)
            elif isinstance(n, ast.MatchMapping) and n.rest:
                others.add(n.rest)
        self.binds, self.mod_objs = mods | others, mods - others

    def self_dicts(self, tree):
        """self_ok: the ids of the `self.__dict__` and `vars(self)` nodes in the methods of a class that cannot be handed a class as `self`: the first parameter
        is `self`, the decorators are plain ones (not @classmethod or @staticmethod, or any we do not know), and `self` is not bound again in the method (a nested
        def, lambda or class is not looked into). An instance's own namespace holds no class-body attribute"""
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not fn.args.args or fn.args.args[0].arg != "self" \
                        or not all(dotted(d.func if isinstance(d, ast.Call) else d) in SELF_DECORATORS for d in fn.decorator_list):
                    continue
                nodes, stack = [], list(fn.body)
                while stack:
                    n = stack.pop()
                    nodes.append(n)
                    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                        stack.extend(ast.iter_child_nodes(n))
                if any(isinstance(n, ast.Name) and n.id == "self" and not isinstance(n.ctx, ast.Load) for n in nodes):
                    continue
                for n in nodes:
                    if isinstance(n, ast.Attribute) and n.attr == "__dict__" and isinstance(n.value, ast.Name) and n.value.id == "self":
                        self.self_ok.add(id(n))
                    elif isinstance(n, ast.Call) and dotted(n.func) == "vars" and len(n.args) == 1 and not n.keywords \
                            and isinstance(n.args[0], ast.Name) and n.args[0].id == "self":
                        self.self_ok.add(id(n))

    def narrowable(self, tree):
        """sets self.narrow: line -> the attribute names bound by the class-body assignment(s) that hold the line, for each line whose edit may bind those
        attributes and not the class (see *Class attributes*). A line is in it only if every statement on it is such an assignment: a direct Assign in the
        body of a top-level class that is plain (no decorator, keyword or base but `object`; none of ATTR_NEVER defined; no call of ATTR_BODY_CALLS in the
        body or in a method header), whose targets are plain names (no dunder), whose value is a literal, and whose names the class body does not read bare
        (a derived attribute: `B = A + 1`, a default `def f(self, x=A)`). A line that holds any other statement as well (`X = 1; def …`), or the class line
        itself, is not narrowed: the class is bound as before"""
        holds, plain = collections.Counter(), collections.Counter()
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef) or cls.decorator_list or cls.keywords \
                    or any(not (isinstance(b, ast.Name) and b.id == "object") for b in cls.bases):
                continue
            defined, loaded, whole = set(), set(), False
            for n in eval_nodes(cls.body):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined.add(n.name)
                elif isinstance(n, ast.Name):
                    if isinstance(n.ctx, ast.Store):
                        defined.add(n.id)
                    else:
                        loaded.add(n.id)   # Load and Del: both need the attribute to exist
                elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                    loaded.add(n.target.id)
                elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ATTR_BODY_CALLS:
                    whole = True
            if whole or defined & ATTR_NEVER:
                continue
            rows = []
            for st in cls.body:
                lines = range(st.lineno, (st.end_lineno or st.lineno) + 1)
                names = set()
                if isinstance(st, ast.Assign) and st.lineno > cls.lineno and all(isinstance(t, ast.Name) for t in st.targets):
                    names = {t.id for t in st.targets}
                    try:
                        ast.literal_eval(st.value)
                    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                        names = set()
                    if names & loaded or any(n.startswith("__") and n.endswith("__") for n in names):
                        names = set()
                    # private names are mangled: `__x` in class C is read as `_C__x` outside the class
                    names |= {f"_{cls.name.lstrip('_')}{n}" for n in names if n.startswith("__") and cls.name.strip("_")}
                rows.append((lines, names))
                holds.update(lines)
            for lines, names in rows:
                if names:
                    for ln in lines:
                        plain[ln] += 1
                        self.narrow.setdefault(ln, set()).update(names)
        self.narrow = {ln: frozenset(ns) for ln, ns in self.narrow.items() if plain[ln] == holds[ln]}

    def attr_reads(self, st):
        """the attribute keys a module-level statement reads when it runs (a function's body is its own scope: Names of the functions' scopes read their own)"""
        out = set()
        for n in eval_nodes([st]):
            out |= self.attr_keys(n)
        return out

    def attr_keys(self, node):
        """the keys of the attributes one node reads under class rule C2: ("*", ".name") for an attribute access `.name`, a string that is the name, and a
        string of any length with a `.` or `{` in it that holds it as a whole token (a format string "{a.name}", an attrgetter path, a script handed to a
        subprocess); ATTR_ANY for an access by a name we cannot see: getattr and its kin with a name that is a value, vars, dir, inspect.getmembers,
        `.__dict__` (an instance's own `self.__dict__` and a module's are no read of a class attribute). A match class pattern reads its keyword attributes
        (see *Class attributes*)"""
        if isinstance(node, ast.Attribute):
            ks = {("*", "." + node.attr)}
            if node.attr in ATTR_DICT and id(node) not in self.self_ok and not self.is_module(node.value):
                ks.add(ATTR_ANY)
            return ks
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v.isidentifier():
                return {("*", "." + v)} | ({ATTR_ANY} if v in ATTR_DICT else set())
            if "{" in v or "." in v:
                return {("*", "." + t) for t in ATTR_TOKEN.findall(v)}
            return set()
        if isinstance(node, ast.Name):
            # getattr handed over as a value (map(getattr, objs, names)): the name is in a call we do not see; a local variable called `dir` is no builtin
            if isinstance(node.ctx, ast.Load) and node.id in ATTR_VALUES and id(node) not in self.callees and node.id not in self.binds:
                return {ATTR_ANY}
            return set()
        if isinstance(node, ast.MatchClass):
            return {("*", "." + a) for a in node.kwd_attrs}
        if not isinstance(node, ast.Call):
            return set()
        f, a = node.func, node.args
        fl = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        star = any(isinstance(x, ast.Starred) for x in a) or any(k.arg is None for k in node.keywords)
        lit = lambda x: isinstance(x, ast.Constant) and isinstance(x.value, str)
        if fl in ATTR_BY_NAME:
            return set() if not star and len(a) > 1 and (lit(a[1]) or self.is_module(a[0])) else {ATTR_ANY}
        if fl in ATTR_ALL:
            return set() if not star and (not a or id(node) in self.self_ok or self.is_module(a[0])) else {ATTR_ANY}
        if fl in ATTR_NAMES:
            return set() if not star and all(lit(x) for x in a) else {ATTR_ANY}
        if fl == "multiple" and isinstance(f, ast.Attribute):   # mock.patch.multiple(Cls, K=1): each keyword names an attribute it replaces; **kw is a name we cannot see
            return {ATTR_ANY} if any(k.arg is None for k in node.keywords) else {("*", "." + k.arg) for k in node.keywords}
        if fl in ("eval", "exec") and isinstance(f, ast.Name):
            return set() if not star and a and lit(a[0]) else {ATTR_ANY}   # the code in a literal string is read as a string: its tokens
        return set()

    def statement(self, st, first):
        """(first line, last line, kind, names bound, keys it reads at import); kind: bind (only binds names), effect"""
        a, b = min([d.lineno for d in getattr(st, "decorator_list", [])] + [st.lineno]), st.end_lineno or st.lineno
        reads = set()
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.functions.add(st.name)
            bound = {st.name}
            reads |= self.header_reads(st, a)
            kind, extra = self.decorators(st, reads)
            return a, b, kind, bound | extra, reads
        if isinstance(st, ast.ClassDef):
            self.classes.add(st.name)
            kind, extra = self.decorators(st, reads)
            if kind != "bind":
                return a, b, kind, {st.name}, reads
            # a method's header runs when the class body does: its defaults and annotations are the class statement's reads
            # (as a module-level def's are); the calls in a header are not checked for purity, as for a def
            for x in st.body:
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    reads |= self.header_reads(x, a)
            for part in [*st.bases, *[k.value for k in st.keywords],
                         *[x for x in st.body if not isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]]:
                for x in ast.walk(part):
                    if isinstance(x, ast.Call) and not self.pure_call(x):
                        return a, b, "effect", {st.name}, reads
                    reads |= self.keys(x) if isinstance(x, (ast.Name, ast.Attribute)) else set()
            return a, b, "bind", {st.name} | extra, reads
        if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            names = set()
            for t in targets:
                for x in ([t] if isinstance(t, (ast.Name, ast.Attribute)) else t.elts if isinstance(t, (ast.Tuple, ast.List)) else [None]):
                    if isinstance(x, ast.Name):
                        names.add(x.id)
                        continue
                    # _ho.SERVER = NAME: a name of another of our modules, bound from here
                    other = [k for k in (self.keys(x) if isinstance(x, ast.Attribute) else ()) if k[0] != self.mod and k[0] in self.repo and k[1] != "<module>" and len(k) == 2]
                    if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and other:
                        names |= set(other)
                        continue
                    return a, b, "effect", names, reads
            if isinstance(st, ast.AnnAssign):
                for x in ast.walk(st.annotation):
                    if isinstance(x, (ast.Name, ast.Attribute)):
                        reads |= self.keys(x)
            if st.value is not None:
                for x in ast.walk(st.value):
                    if isinstance(x, ast.Call) and not self.pure_call(x):
                        return a, b, "effect", names, reads
                    if isinstance(x, (ast.Name, ast.Attribute)):
                        reads |= self.keys(x)
            if isinstance(st, ast.AugAssign):
                reads |= {(self.mod, n) for n in names}
            return a, b, "bind", names, reads
        if first and isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            return a, b, "bind", {"__doc__"}, reads
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            names = {(x.asname or x.name).split(".")[0] for x in st.names}
            ours = [m for m in self.imported(st) if m.split(".")[0] in self.repo_tops]
            if ours:
                # one of ours: importing it runs its module level in every importer; `selection` decides (import-repo)
                return a, b, "import-repo", names, set(ours)
            return a, b, "bind", names, reads
        if is_main_guard(st):
            return a, b, "main", set(), reads
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            # _router_live.configure(…): a call into one of our modules sets that module's state: its file, whole
            ks = self.keys(st.value.func) if dotted(st.value.func) else set()
            mods = {k[0] for k in ks if len(k) == 2 and k[0] != self.mod and k[0] in self.repo}
            if mods and isinstance(st.value.func, ast.Attribute) and dotted(st.value.func.value) in self.aliases:
                for x in ast.walk(st.value):
                    if isinstance(x, (ast.Name, ast.Attribute)):
                        reads |= self.keys(x)
                self.effect_targets[a] = mods
                return a, b, "effect-mod", set(), reads
        return a, b, "effect", set(), reads

    def header_reads(self, fn, first):
        """the keys a function's header reads when its def runs: the defaults and the annotations (a tool parameter's
        Annotated[…, Field(…)] constant is read there). The annotations of a plain def in a postponed file are not returned: they wait in
        ann_stmt (the statement's first line, the def's name, the keys) for Names.settle"""
        ar, reads = fn.args, set()
        for d in [*ar.defaults, *ar.kw_defaults, fn.returns, *[x.annotation for x in [*ar.posonlyargs, *ar.args, *ar.kwonlyargs, ar.vararg, ar.kwarg] if x is not None]]:
            if d is not None:
                for x in ast.walk(d):
                    ks = self.keys(x) if isinstance(x, (ast.Name, ast.Attribute)) else set()
                    if ks and id(x) in self.annot_skip:
                        self.ann_stmt.append((first, self.annot_skip[id(x)], ks))
                    else:
                        reads |= ks
        return reads

    def decorators(self, st, reads):
        """('bind', extra names) when every decorator only wraps (PURE_DECORATORS) or registers on one of this module's
        own objects (@mcp.tool: extra = <enumerate>; @mcp.custom_route: extra = <enumerate-routes>, or <enumerate> under route rule R1);
        ('effect', set()) for any other"""
        extra = set()
        for d in st.decorator_list:
            for x in ast.walk(d):
                if isinstance(x, (ast.Name, ast.Attribute)):
                    reads |= self.keys(x)
            f = dotted(d.func if isinstance(d, ast.Call) else d)
            if f in PURE_DECORATORS:
                continue
            if f and "." in f and f.split(".")[0] in self.toplevel:
                extra.add(ENUMERATE_R if f.endswith(".custom_route") and route_rule() == "R2" else ENUMERATE)
                continue
            return "effect", set()
        return "bind", extra

    def stmt_at(self, ln):
        for st in self.stmts:
            if st[0] <= ln <= st[1]:
                return st
        return None

    def stmts_at(self, ln):
        """every module-level statement that has the line, with its index in stmts (`import os; X = 1` is two)"""
        return [(i, st) for i, st in enumerate(self.stmts) if st[0] <= ln <= st[1]]

    def resolve_from(self, level, module):
        """the module a `from … import` names, resolved against this file's package"""
        base = module or ""
        if level:
            pkg = self.mod if self.path.endswith("/__init__.py") else self.mod.rpartition(".")[0]
            up = pkg.split(".") if pkg else []
            up = up[: len(up) - (level - 1)] if level > 1 else up
            base = ".".join([*up, base] if base else up)
        return base

    def imported(self, st):
        """the modules an import statement loads, resolved against this file's package"""
        if isinstance(st, ast.Import):
            return [x.name for x in st.names]
        base = st.module or ""
        if st.level:
            pkg = self.mod if self.path.endswith("/__init__.py") else self.mod.rpartition(".")[0]
            up = pkg.split(".") if pkg else []
            up = up[: len(up) - (st.level - 1)] if st.level > 1 else up
            base = ".".join([*up, base] if base else up)
        return [f"{base}.{x.name}" if f"{base}.{x.name}" in self.repo else base for x in st.names]

    def only_binds(self):
        """True when importing this module only binds names (every module-level statement does)"""
        return self.ok and all(k in ("bind", "main") for _, _, k, _, _ in self.stmts)

    def pure_call(self, call):
        f = dotted(call.func)
        if f in PURE_CALLS:
            return True
        if isinstance(call.func, ast.Attribute):
            if call.func.attr in PURE_METHODS:
                return True
            if call.func.attr in PATH_METHODS and self.path_receiver(call.func.value):
                return True
        if f is None:
            return False
        if REPO_CALLS_BIND:
            head = f.split(".")[0]
            if head in self.functions or head in self.classes:
                return True
            if head in self.aliases and self.aliases[head] in self.repo or any(b in self.repo for b, _ in self.froms_all.get(head, ())):
                return True
        return False

    def path_receiver(self, node):
        """True when an expression is a path by its root: Path(…), pathlib.Path(…), Path.home() or __file__, through attributes
        (.parent), subscripts (.parents[1]) and method calls on it (those calls are checked as the walk reaches them)"""
        while True:
            if isinstance(node, (ast.Attribute, ast.Subscript)):
                node = node.value
            elif isinstance(node, ast.Call):
                if dotted(node.func) in PATH_ROOTS:
                    return True
                if not isinstance(node.func, ast.Attribute):
                    return False
                node = node.func.value
            else:
                return isinstance(node, ast.Name) and node.id == "__file__"


class Names:
    """the name index of one revision: every repo Python file and every suite's file"""

    def __init__(self, rev):
        files = [f for f in (git("ls-tree", "-r", "--name-only", rev) or "").split("\n") if f.endswith(".py")]
        self.repo = {modname(f) for f in files if not SUITE_RE.match(f) and not f.endswith("_check.py")}
        srcs = cat_files(rev, files)
        self.files = {f: ModNames(f, srcs[f], self.repo) for f in files if f in srcs}
        self.by_mod = {m.mod: m for f, m in self.files.items() if not SUITE_RE.match(f)}
        self.settle(rev)
        for m in self.files.values():
            for sc in m.refs:
                m.refs[sc] = self.resolve(m.refs[sc])
            m.stmts = [(a, b, k, n, r if k == "import-repo" else self.resolve(r)) for a, b, k, n, r in m.stmts]

    def scripts(self, rev):
        """{path: ModNames} for the tracked files that are not .py but start with a python or a `uv run` shebang (`#!/usr/bin/env -S uv run --script`), or
        None when git could not say or a script does not parse (a shebang that names uv may start something that is not Python: then any def may be reached)"""
        r = subprocess.run(["git", "-C", ROOT, "grep", "-lI", "-E", "^#!.*(python|uv )", rev, "--", ".", ":!*.py"], capture_output=True, text=True)
        if r.returncode not in (0, 1):
            return None
        paths = [x[len(rev) + 1:] for x in r.stdout.split("\n") if x.startswith(rev + ":")]
        out = {}
        for p, src in cat_files(rev, paths).items():
            m = ModNames(p, src, self.repo)
            if not m.ok:
                return None
            out[p] = m
        return out

    def settle(self, rev):
        """decide the annotations that wait in each file (ModNames.ann, ann_stmt; see *Imports and annotations*): one of a plain def counts as a read
        unless the def's name is only ever called in the checkout; one of a local variable never does"""
        scripts = self.scripts(rev)
        everyone = [*self.files.values(), *(scripts or {}).values()]
        self.escaped = set().union(*(m.valuse for m in everyone)) if everyone else set()
        # a name used as a value escapes the function it is a name OF: follow `from m import f as g` (a re-export under another name) across files to a
        # fixed point (mod.py def f; pkg/__init__.py `from mod import f as h`; use.py `from pkg import h; get_type_hints(h)`: h, and so f, escape)
        grew = True
        while grew:
            grew = False
            for m in everyone:
                for local, srcs in m.froms_all.items():
                    for _, name in srcs:
                        if local in self.escaped and name not in self.escaped:
                            self.escaped.add(name)
                            grew = True
        # the parameters of a class's __init__, __call__ and __new__ wait under the CLASS's name, but they are also reached through the method itself
        # (get_type_hints(C(1).__init__), get_type_hints(OBJ.__call__), a class decorator or __init_subclass__ doing get_type_hints(cls.__init__)): a method
        # name read as an attribute without being called anywhere (or asked of getattr) escapes every class-keyed name. The tripwire pins each get_type_hints use
        if any(m.attr_values & CLASS_CALLS for m in everyone):
            for m in everyone:
                self.escaped |= m.class_keyed
        self.blind = scripts is None   # could not list the scripts: any function may be reached by one

        def skippable(m, fname):
            return fname is None or not (self.blind or fname in self.escaped)
        for m in self.files.values():
            if not m.ok:
                continue
            # a name taken from another of our modules is still needed by the import statement (an ImportError at import), whatever the annotation does
            imported = {k for srcs in m.froms_all.values() for k in srcs if k[0] in m.repo}
            for fname, sc, ks in m.ann:
                if not skippable(m, fname):
                    m.refs[sc] |= ks
                else:
                    m.dropped |= ks & imported
            extra = collections.defaultdict(set)
            for first, fname, ks in m.ann_stmt:
                if not skippable(m, fname):
                    extra[first] |= ks
            if extra:
                m.stmts = [(a, b, k, n, r | extra[a] if a in extra else r) for a, b, k, n, r in m.stmts]

    def resolve(self, keys):
        """keys with each attribute chain on a module ("~", module, (a, b, …)) followed through that module's own imports"""
        out = set()
        for k in keys:
            if k[0] != "~":
                out.add(k)
                continue
            mod, rest = k[1], list(k[2])
            while rest:
                out.add((mod, rest[0]))
                m = self.by_mod.get(mod)
                nxt = None
                if m is not None and rest[0] in m.aliases:
                    nxt = m.aliases[rest[0]]
                elif m is not None and rest[0] in m.froms:
                    out.update(m.froms_all[rest[0]])
                    fm, fa = m.froms[rest[0]]
                    nxt = f"{fm}.{fa}" if f"{fm}.{fa}" in self.repo else None
                if nxt is None:
                    break
                mod, rest = nxt, rest[1:]
                while rest and f"{mod}.{rest[0]}" in self.repo:
                    mod, rest = f"{mod}.{rest[0]}", rest[1:]
        return out


def cat_files(rev, paths):
    """{path: text} for many files of one revision in one git process"""
    if not paths:
        return {}
    r = subprocess.run(["git", "-C", ROOT, "cat-file", "--batch"], input="".join(f"{rev}:{p}\n" for p in paths).encode(),
                       capture_output=True)
    out, data, i = {}, r.stdout, 0
    for p in paths:
        nl = data.index(b"\n", i)
        head = data[i:nl].split()
        i = nl + 1
        if len(head) < 3 or head[1] != b"blob":
            continue
        size = int(head[2])
        out[p] = data[i:i + size].decode("utf-8", "replace")
        i += size + 1
    return out


def touches(reads, hit):
    """True when a set of keys read meets the keys hit: the same key, a read of every name of a module with a hit
    (module, *), a read of one name in any module (*, name), or a read of every attribute (*, .*) with a hit on an attribute (module, .name)"""
    mods, names = {k[0] for k in hit}, {k[1] for k in hit}
    attrs = ATTR_ANY in reads and any(n.startswith(".") for n in names)
    return attrs or any(k in hit or (k[1] == "*" and (k[0] in mods or k[0] == "*")) or (k[0] == "*" and k[1] in names) for k in reads)


def reach(names_list, seeds, ran=None):
    """(keys, whole): the keys a change to the seed keys reaches through module-level bindings that read them, to a fixed
    point; and the files where a module-level statement with effects (a decorator, a call) reads one: whole files. Only the
    files some suite ran (ran: the map's measured files) count: one no suite imports (a manual check, a script run by hand)
    sets nothing at import in any suite, and a module that imported it would have run it"""
    hit, whole = set(seeds), set()
    while True:
        grew = False
        for N in names_list:
            for m in N.files.values():
                if SUITE_RE.match(m.path) or (ran is not None and m.path not in ran):
                    continue
                # from x import n (as k): a name re-exported from here is the same object under (this module, k)
                for local, srcs in m.froms_all.items():
                    if any(src in hit for src in srcs) and (m.mod, local) not in hit:
                        hit.add((m.mod, local))
                        grew = True
                if m.dropped and touches(m.dropped, hit) and m.path not in whole:
                    whole.add(m.path)   # an annotation-only name taken from a changed module: the import statement needs it (see *Imports and annotations*)
                for a, b, kind, bound, reads in m.stmts:
                    if kind == "import-repo" or not reads or not touches(reads, hit):
                        continue
                    if kind == "effect":
                        whole.add(m.path)
                    if kind == "effect-mod":
                        whole |= {N.by_mod[x].path for x in m.effect_targets.get(a, ()) if x in N.by_mod}
                    for n in bound:
                        k = n if isinstance(n, tuple) else (m.mod, n)
                        if k not in hit:
                            hit.add(k)
                            grew = True
        if not grew:
            return hit, whole


def readers(names_list, hit):
    """(scopes, suites): the (file, scope) pairs of our code whose function bodies read a key in hit (module level is
    reach's), and the suites whose own file reads one anywhere"""
    scopes_, suites_ = set(), set()
    for N in names_list:
        for f, m in N.files.items():
            ms = SUITE_RE.match(f)
            for sc, ks in m.refs.items():
                if (ms or sc) and touches(ks, hit):
                    if ms:
                        suites_.add(ms.group(1))
                    else:
                        scopes_.add((f, sc))
    return scopes_, suites_


def doc_readers(names_list, hit):
    """the suites whose own file reads one of the keys in hit by its name (`mod.f`, `from mod import f`, a binding that holds it), not
    those that read names wide (getattr(module, <not a literal>), a module loaded by a path in a variable): a suite can see a
    function's docstring through the name, or through the file's text (the map's `whole`), and the reading of names wide is no
    sign of a docstring read (see *Docstrings*)"""
    names, out = {k[1] for k in hit}, set()
    for N in names_list:
        for f, m in N.files.items():
            ms = SUITE_RE.match(f)
            if ms and any(k in hit or (k[0] == "*" and k[1] in names) for ks in m.refs.values() for k in ks):
                out.add(ms.group(1))
    return out


# ---------------------------------------------------------------- measure
def coveragerc(datadir):
    rc = os.path.join(datadir, "coveragerc")
    with open(rc, "w") as f:
        f.write(f"""[run]
parallel = true
patch = subprocess, _exit, execv, fork
sigterm = true
include = {ROOT}/*
omit = {ROOT}/tests/*_scenario.py
    {ROOT}/tests/*_check.py
disable_warnings = no-data-collected, module-not-imported, module-not-measured, include-ignored, couldnt-parse, already-imported
""")
    return rc


def run_suite(name, timeout, env=None, wrap=()):
    """run one suite through the checkout's tests/run-suite. A hung suite gets SIGINT at its limit, so it fails on its own
    with the traceback of where it sat, and the suites after it still run (github's pacer waiting out the hour).
    A CI cancel signals the step's top process alone, never its process group (actions/runner ProcessInvoker.cs: SIGINT,
    SIGTERM 7.5 s later, a kill 2.5 s after that); the step execs uv, which forwards both here. The suite runs in a process
    group of its own (timeout, strace, run-suite, uv, the suite). The first INT, TERM or HUP that comes while it runs goes to
    `timeout`, which passes it to that group once; any later one goes to the group from here, since uutils' timeout (Ubuntu
    26.04's) passes on only the first signal it gets and then waits with the rest blocked. So the suite and run-suite end and
    clean up now, not at the job's orphan sweep; then no further suite runs. strace (`wrap`) sits inside timeout and blocks
    fatal signals itself (-o FILE: its -I3), which leaves the traced suite to get them from the group.
    timeout ends once its child has, and run-suite once its suite has (its traps wait), so the wait here outlasts the suite;
    a last TERM to the group, and up to 2 s for it to be gone, cover a timeout that ended first all the same."""
    t0 = time.monotonic()
    p, stopped, sent = None, [], 0

    def pass_on(sig=None, _frame=None):
        nonlocal sent
        if sig is not None:
            stopped.append(sig)
        while p is not None and sent < len(stopped):   # one that came before Popen returned is passed on once it has
            first, sig = sent == 0, stopped[sent]
            sent += 1
            try:
                p.send_signal(sig) if first else os.killpg(p.pid, sig)
            except ProcessLookupError:
                pass
    old = {s: signal.signal(s, pass_on) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        p = subprocess.Popen(["timeout", "-s", "INT", str(timeout), *wrap, os.path.join(ROOT, "tests", "run-suite"), name],
                             cwd=ROOT, env=env, process_group=0)
        pass_on()
        rc = p.wait()
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    if stopped:
        end = time.monotonic() + 2
        try:
            os.killpg(p.pid, signal.SIGTERM)
            while time.monotonic() < end:
                time.sleep(0.05)
                os.killpg(p.pid, 0)
        except ProcessLookupError:
            pass
        print(f"== {name}: stopped by {signal.Signals(stopped[0]).name} (a cancel); no further suite runs", flush=True)
        sys.exit(128 + stopped[0])
    if rc == 124:
        print(f"== {name}: timed out after {timeout}s", flush=True)
    return rc, time.monotonic() - t0


def read_coverage(datadir):
    """{repo-relative file: set of lines run} over every data file of the suite, and the pids that left data."""
    import coverage
    lines, pids = collections.defaultdict(set), set()
    for f in os.listdir(datadir):
        m = re.match(r"\.coverage\..*?\.pid(\d+)\.", f)
        if not m:
            continue
        pids.add(m.group(1))
        d = coverage.CoverageData(basename=os.path.join(datadir, f))
        try:
            d.read()
        except Exception as e:  # a data file cut off by a killed process: what it holds is lost, its pid is not measured
            print(f"suitemap: unreadable coverage data {f}: {e}", file=sys.stderr)
            pids.discard(m.group(1))
            continue
        for mf in d.measured_files():
            rel = os.path.relpath(os.path.realpath(mf), ROOT)
            if not rel.startswith(".."):
                lines[rel] |= set(d.lines(mf) or ())
    return lines, pids


def read_strace(path, tracked, tdirs, datapids):
    """(files, whole, dirs, unmeasured) from one suite's strace log: the tracked non-Python files touched; the .py files
    a process read as text or loaded unmeasured (whole); the tracked directories listed; the pids of unmeasured Pythons."""
    prog, tg, pending = {}, {}, {}
    files, whole, dirs = set(), set(), set()
    pyopen, pystat = collections.defaultdict(set), collections.defaultdict(set)
    first = None
    with open(path, errors="replace") as f:
        for line in f:
            m = re.match(r"(\d+) +(\w+)\((.*)", line)
            if not m:
                # a call cut in two by another process's: `<pid> <... clone3 resumed>…) = <child>`; the flags were on the first half
                r = re.match(r"(\d+) +<\.\.\. (clone3?|fork|vfork) resumed>.*= (\d+)", line)
                if r and r.group(1) in pending:
                    pid, c = r.group(1), r.group(3)
                    g = tg.get(pid, pid)
                    if "CLONE_THREAD" in pending.pop(pid):
                        tg[c] = g
                    else:
                        tg[c] = c
                        prog[c] = prog.get(g, "")
                continue
            pid, call, rest = m.groups()
            if first is None:
                first = pid
            g = tg.get(pid, pid)
            if call in ("clone", "clone3", "fork", "vfork"):
                if "<unfinished ...>" in line:
                    pending[pid] = line
                    continue
                r = re.search(r"= (\d+)(?:<[^>]*>)?\s*$", line)
                if r:
                    c = r.group(1)
                    if "CLONE_THREAD" in line:
                        tg[c] = g
                    else:
                        tg[c] = c
                        prog[c] = prog.get(g, "")
                continue
            r = re.match(r'(?:(?:AT_FDCWD|-?\d+)<([^>]*)>, )?"((?:[^"\\]|\\.)*)"', rest)
            if not r:
                continue
            base, p = r.groups()
            full = os.path.normpath(p if p.startswith("/") else os.path.join(base or "/", p))
            rel = os.path.relpath(full, ROOT)
            if call in ("execve", "execveat") and re.search(r"= 0\s*$", line):
                prog[g] = full
            if rel.startswith(".."):
                continue
            rel = "" if rel == "." else rel
            if call.startswith("open") and "O_DIRECTORY" in rest:
                if rel in tdirs:
                    dirs.add(rel)
                continue
            if rel not in tracked:
                continue
            if rel.endswith(".py"):
                (pyopen if call.startswith(("open", "creat")) else pystat)[g].add(rel)
            else:
                files.add(rel)
    unmeasured = []
    for g in set(pyopen) | set(pystat):
        exe = os.path.basename(prog.get(g, ""))
        if g in datapids:
            whole |= pyopen[g]  # a measured Python opened the source: a text read (the bytecode was compiled beforehand)
        elif exe.startswith("python"):
            whole |= pyopen[g] | pystat[g]  # a Python that left no coverage data (system python3, or killed): whole files
            unmeasured.append(g)
        else:
            whole |= pyopen[g]  # read by another program (cat, grep, bash -n)
    return files, whole, dirs, unmeasured


CARRY_KEYS = ("py", "files", "whole", "dirs", "traced")


def carried(prev, name):
    """what the earlier map knew of suite `name` that is worth keeping beside a measurement that is not clean: its last clean
    measurement ({py, files, whole, dirs, traced} and `at`, the commit it was made at), or the carry it already had; else None"""
    e = ((prev or {}).get("suites") or {}).get(name)
    if not isinstance(e, dict):
        return None
    if e.get("ok") and not e.get("failed") and all(k in e for k in CARRY_KEYS) and prev.get("commit"):
        return {**{k: e[k] for k in CARRY_KEYS}, "at": prev["commit"]}
    c = e.get("carry")
    return c if isinstance(c, dict) and all(k in c for k in (*CARRY_KEYS, "at")) else None


def measure(args):
    names = args.suites or suites()
    commit = git("rev-parse", "HEAD").strip()
    tracked = set((git("ls-files") or "").split("\n")) - {""}
    tdirs = {os.path.dirname(f) for f in tracked} | {""}
    use_strace = shutil.which("strace") is not None and os.environ.get("SUITEMAP_STRACE", "1") != "0"
    if not use_strace:
        print("suitemap: strace off or missing: files are not measured, so every non-Python change runs every suite", file=sys.stderr)
    # strace is the cost of measuring (coverage on Python 3.14 is close to free; strace makes a suite up to twice as slow).
    # So with an earlier map, only the suites this commit's change reaches are traced again, and any suite traced more than
    # TRACE_MAX_AGE ago; the others keep the file half of their earlier measurement.
    prev = load_map(args.prev) if args.prev else None
    now = datetime.datetime.now(datetime.timezone.utc)
    trace = set(names) if use_strace else set()
    if use_strace and prev and prev.get("strace") and have(prev["commit"]):
        reached, _ = selection(prev, prev["commit"], commit)
        trace = set(names) if reached == "all" else set(reached)
        for n in names:
            e = prev["suites"].get(n, {})
            try:
                old = now - datetime.datetime.fromisoformat(e["traced"]) > datetime.timedelta(hours=TRACE_MAX_AGE)
            except (KeyError, ValueError, TypeError):
                old = True
            if old or "files" not in e:
                trace.add(n)
        print(f"suitemap: tracing {len(trace)} of {len(names)} suites (the change since {prev['commit'][:12]} reaches them, or "
              f"their files were traced over {TRACE_MAX_AGE} h ago); the others keep their earlier file measurement", file=sys.stderr)
    # compile the bytecode first: a measured Python then opens a .py only to read it as text
    subprocess.run([sys.executable, "-m", "compileall", "-q", "-x", r"/tests/.*_(scenario|check)\.py$", ROOT],
                   capture_output=True)
    out = {"format": FORMAT, "commit": commit, "strace": use_strace,
           "measured": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "suites": {}}
    fail = 0
    for name in names:
        print(f"== {name}", flush=True)
        d = tempfile.mkdtemp(prefix=f"suitemap-{name}-")
        atexit.register(shutil.rmtree, d, True)   # also when the run ends early (an exception, a signal that raises); removed again below when the suite is read
        # a measurement of its own: nothing of an outer coverage run (this tool's self-test is measured on main) carries over
        env = {k: v for k, v in os.environ.items() if not k.startswith("COVERAGE_")}
        env.update(COVERAGE_PROCESS_START=coveragerc(d), COVERAGE_FILE=os.path.join(d, ".coverage"))
        wrap = ("strace", "-f", "-y", "-qq", "--seccomp-bpf", "-e", f"trace={TRACE}", "-o", os.path.join(d, "strace")) if name in trace else ()
        rc, secs = run_suite(name, args.timeout, env, wrap)
        entry = {"ok": rc == 0, "seconds": round(secs, 1)}
        if rc != 0:
            prc, psecs = run_suite(name, args.timeout)
            if prc != 0:
                print(f"== {name}: FAILED", flush=True)
                fail = 1
                entry["failed"] = True
            else:
                print(f"::warning::{name} failed only when measured; it passes plainly. The map runs it on every PR until a clean measurement.", flush=True)
            entry["seconds"] = round(psecs, 1)
            entry["measured_seconds"] = round(secs, 1)   # what the measured run took (the limit, when it timed out): the shard plan balances by this, not by the plain time
        lines, pids = read_coverage(d)
        py = {}
        for rel, ls in sorted(lines.items()):
            try:
                src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            sc = scopes(src)
            if sc is not None:
                py[rel] = sorted({sc[0][l] if l < len(sc[0]) else "" for l in ls})
        entry["py"] = py
        if not entry["ok"] and not entry.get("failed") and carried(prev, name):
            entry["carry"] = carried(prev, name)   # failed only when measured (a timeout of a slow suite): this measurement is partial, the last clean one is not lost
        if name in trace:
            files, whole, dirs, unm = read_strace(os.path.join(d, "strace"), tracked, tdirs, pids)
            entry.update(files=sorted(files), whole=sorted(whole), dirs=sorted(dirs), unmeasured=len(unm),
                         traced=now.isoformat(timespec="seconds"))
        elif use_strace:
            e = prev["suites"][name]
            entry.update({k: e[k] for k in ("files", "whole", "dirs", "unmeasured", "traced") if k in e})
        out["suites"][name] = entry
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.map)), exist_ok=True)
    with open(args.map, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"suitemap: wrote {args.map} for {commit[:12]} ({len(names)} suites, strace {'on' if use_strace else 'off'})", file=sys.stderr)
    return fail


def have(commit):
    """True when the commit is in the checkout, fetching it once when it is not (CI checks out one commit)"""
    if git("cat-file", "-e", f"{commit}^{{commit}}") is None:
        git("fetch", "--quiet", "--no-tags", "--depth=1", "origin", commit)
    return git("cat-file", "-e", f"{commit}^{{commit}}") is not None


def run(args):
    fail = 0
    for name in args.suites:
        print(f"== {name}", flush=True)
        rc, _ = run_suite(name, args.timeout)
        if rc != 0:
            print(f"== {name}: FAILED", flush=True)
            fail = 1
    return fail


# ---------------------------------------------------------------- shards
SHARDS = 6   # main's measured run: the matrix in tests.yml lists 0 .. SHARDS-1 and passes --of SHARDS (suitemap_scenario.py checks both)


def shard_plan(names, n, m=None):
    """names split into n lists, every name in exactly one; balanced by the map's measured seconds when it has any, else by a stable hash"""
    if n < 1:
        raise ValueError("a shard plan needs at least one shard")
    names = sorted(set(names))
    secs = {}
    for k, e in ((m or {}).get("suites") or {}).items():
        try:
            v = max(float(e.get("seconds") or 0), float(e.get("measured_seconds") or 0))   # a suite that failed only when measured: the plain time is far under what its shard spends on it
        except (AttributeError, TypeError, ValueError):
            continue
        if v > 0:
            secs[k] = v
    known = sorted(secs[k] for k in names if k in secs)
    out = [[] for _ in range(n)]
    if not known:
        for k in names:
            out[int(hashlib.sha256(k.encode()).hexdigest(), 16) % n].append(k)
        return out
    median = known[len(known) // 2]
    load = [0.0] * n
    for k in sorted(names, key=lambda k: (-secs.get(k, median), k)):
        i = min(range(n), key=lambda i: (load[i], i))
        out[i].append(k)
        load[i] += secs.get(k, median)
    return [sorted(x) for x in out]


def shard(args):
    if not 0 <= args.index < args.of:
        print(f"suitemap: --index {args.index} is not a shard of {args.of}", file=sys.stderr)
        return 2
    plan = shard_plan(suites(), args.of, load_map(args.map) if args.map else None)
    if plan[args.index]:
        print("\n".join(plan[args.index]))
    return 0


def plan(args):
    """the whole plan, one `shardI=names` line a shard (names separated by spaces: a suite's name has none), as a job's outputs"""
    if args.of < 1:
        print("suitemap: --of must be at least 1", file=sys.stderr)
        return 2
    for i, names in enumerate(shard_plan(suites(), args.of, load_map(args.map) if args.map else None)):
        print(f"shard{i}={' '.join(names)}")
    return 0


def merge(args):
    maps = []
    for p in args.shards:
        m = load_map(p)
        if m is None:
            print(f"::error::suitemap merge: {p} is not a map", flush=True)
            return 2
        maps.append(m)
    if not maps or len({m["commit"] for m in maps}) != 1:
        print(f"::error::suitemap merge: the shards' maps are not of one commit ({', '.join(sorted({m['commit'][:12] for m in maps})) or 'none'})", flush=True)
        return 2
    out = {"format": FORMAT, "commit": maps[0]["commit"], "strace": all(m.get("strace") for m in maps),
           "measured": max(m.get("measured") or "" for m in maps), "suites": {}}
    twice = set()
    for m in maps:
        for k, e in m["suites"].items():
            if k in out["suites"]:
                twice.add(k)
            out["suites"][k] = e
    missing = sorted(set(suites()) - set(out["suites"]))
    os.makedirs(os.path.dirname(os.path.abspath(args.map)), exist_ok=True)
    with open(args.map, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"suitemap: merged {len(maps)} shard map(s) of {out['commit'][:12]} into {args.map} ({len(out['suites'])} suites)", file=sys.stderr)
    rc = 0
    if twice:
        print(f"::error::suitemap merge: in more than one shard: {', '.join(sorted(twice))}", flush=True)
        rc = 1
    if missing:
        print(f"::error::suitemap merge: in no shard's map (not measured): {', '.join(missing)}", flush=True)
        rc = 1
    return rc


# ---------------------------------------------------------------- select
def load_map(path):
    try:
        with open(path) as f:
            m = json.load(f)
        return m if m.get("format") == FORMAT and isinstance(m.get("suites"), dict) and m.get("commit") else None
    except (OSError, ValueError, AttributeError):
        return None


def show(rev, path):
    return git("show", f"{rev}:{path}")


def changed_lines(a, b, old, new):
    d = git("diff", "-U0", "--no-color", a, b, "--", *sorted({p for p in (old, new) if p})) or ""
    ol, nl = set(), set()
    for h in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", d, re.M):
        x, xl, y, yl = int(h.group(1)), int(h.group(2) or 1), int(h.group(3)), int(h.group(4) or 1)
        ol.update(range(x, x + xl))
        nl.update(range(y, y + yl))
    return ol, nl


def shadowable():
    """the top-level names a new module at an import root could shadow: the stdlib's and the installed packages'"""
    import importlib.metadata
    names = set(sys.stdlib_module_names)
    try:
        names |= set(importlib.metadata.packages_distributions())
    except Exception:
        pass
    return names


def py_change(names, S, a, b, old, new):
    """(fns, bound, own, whole, docs) for one changed Python file: the (file, scope) pairs whose bodies changed, the (module,
    name) keys whose module-level binding changed, the (file, name) defs and classes among them (what they run counts),
    the files to take whole (a module-level change with effects, a file that does not parse, an added, deleted or
    renamed file: whoever ran it), and the (module, name) keys of the functions whose docstring alone changed"""
    fns, bound, own, whole, docs = set(), set(), set(), set(), set()
    ol, nl = changed_lines(a, b, old, new)
    if not old or not new or old != new:
        whole |= {p for p in (old, new) if p}
    mo, mw = names[0].files.get(old) if old else None, names[1].files.get(new) if new else None
    if mo is not None and mw is not None and mo.ok and mw.ok and mo.postponed != mw.postponed:
        whole |= {old, new}   # postponed annotations on or off: every annotation of the file changes meaning (see *Imports and annotations*)
    added = pure_import_add(mo, mw) if import_rule() == "I2" else None
    if import_rule() == "I2" and mo is not None and mw is not None and mo.ok and mw.ok and unchecked_imports(names[1], mw, new_imports(mo, mw)):
        # an import the new file gained that may not resolve (see unchecked_imports): the importers fail at import, and no name on the line is read in
        # code that a suite runs (an annotation-only name is no read): the file whole, as the old rule had it
        whole.add(new)
    for side, (N, p, ls) in enumerate(((names[0], old, ol), (names[1], new, nl))):
        mn = N.files.get(p) if p else None
        if p is None:
            continue
        if mn is None or not mn.ok:
            whole.add(p)
            continue
        dyn = any((mn.mod, "*") in ks for ks in mn.refs.values())  # globals(): any of its names may be looked up by string
        for ln in sorted(ls):
            t = mn.text[ln - 1].strip() if 0 < ln <= len(mn.text) else ""
            if not t or t.startswith("#"):
                continue
            sc = mn.body_of[ln] if ln < len(mn.body_of) else ""
            if ln in mn.pdoc and not dyn and docstring_rule() == "D2":
                docs.add((p, mn.pdoc[ln], mn.mod))   # the docstring of an undecorated function: not code (see *Docstrings*)
                continue
            if ln in mn.ddoc:
                # a decorated function's docstring: its decorator reads it at import, so it counts as the def statement's
                st = mn.stmt_at(ln)
                sc = "" if st is not None and st[3] and sc in {n for n in st[3] if isinstance(n, str)} else None
                if sc is None:
                    whole.add(p)
                    continue
            if sc:
                fns.add((p, sc))
                continue
            sts = mn.stmts_at(ln)   # `import os; X = 1` has two statements on one line: each is changed
            if not sts or dyn:
                whole.add(p)
                continue
            if ln in mn.narrow and len(sts) == 1 and sts[0][1][2] == "bind" and sts[0][0] not in mn.import_ids:
                # a literal assigned in the body of a plain class (class rule C2): the attribute is bound, not the class (see *Class attributes*)
                bound |= {(mn.mod, "." + n) for n in mn.narrow[ln]}
                continue
            for si, st in sts:
                _, _, kind, bnames, extra = st
                if kind == "import-repo" and all(quiet_import(N, S, p, mod) for mod in extra):
                    kind = "bind"
                if kind == "effect-mod":
                    if any(p in e.get("py", {}) for e in S.values()):   # a file no suite ran sets no state in one
                        whole |= {N.by_mod[x].path for x in mn.effect_targets.get(st[0], ()) if x in N.by_mod}
                    continue
                if kind != "bind":
                    whole.add(p)
                    continue
                if si in mn.import_ids and added is not None:
                    # the two files differ in their imports by names ADDED, and by nothing else (not a removal, a rename, a name taken from another
                    # module, an order or a position): an import statement binds only the added names, a line reformatted or split included. Any
                    # other import edit keeps the old rule: every name on the line (see *Imports and annotations*)
                    bnames = {n for n in bnames if n in added}
                bound |= {n if isinstance(n, tuple) else (mn.mod, n) for n in bnames}
                own |= {(p, n) for n in bnames if isinstance(n, str) and n in mn.functions | mn.classes}
    # a function whose code or def line changed too is selected as before: only a function whose changed lines are all docstring
    # keeps the name rule. The code that reads a docstring is reached either way
    docs = {(p, fn, mod) for p, fn, mod in docs if (p, fn) not in fns and (mod, fn) not in bound}
    if docs:
        for N in names:
            for f, m in N.files.items():
                if SUITE_RE.match(f):
                    continue   # a suite that reads a docstring names the function: the name rule has it
                for sc in m.docreads:
                    if sc:
                        fns.add((f, sc))
                    else:
                        whole.add(f)
    return fns, bound, own, whole, {(mod, fn) for _, fn, mod in docs}


def new_imports(mo, mw):
    """the module-level imports the new file has and the old one does not, as (local name, where it comes from)"""
    return {x for x in mw.import_seq if x} - {x for x in mo.import_seq if x}


def pure_import_add(mo, mw):
    """the set of local names a new file adds to its module-level imports when adding names is all it does to them, else None. Each import is
    (local name, where it comes from) and the files' lists are compared in order, a statement that is not an import counting as a marker, so a name
    removed, renamed, taken from another module, imported twice, moved below other code or swapped with another import of the same name is no pure
    addition (it may change which object the name is, or when). A star import added is none either: the names it brings are not on the line"""
    if mo is None or mw is None or not mo.ok or not mw.ok:
        return None
    new = new_imports(mo, mw)
    if any(src[0] == "from" and src[3] == "*" for _, src in new):
        return None
    def runs(seq):   # the other statements between the imports count as one marker each run, so code added or removed elsewhere changes nothing
        return [x for i, x in enumerate(seq) if x is not None or i == 0 or seq[i - 1] is not None]
    if runs([x for x in mw.import_seq if x not in new]) != runs(mo.import_seq):
        return None
    return {l for l, _ in new}


def unchecked_imports(N, m, items):
    """True when one of the imports a file gained (new_imports) may not resolve, so that importing the file fails (an ImportError) and every importer
    with it: the old rule took the file whole, and so does this. An import from one of OUR modules is checked against that module's bindings: the module
    must exist and bind the name (a def, a class, an assignment, an import there, or a module of that name below it); one that does not, a module whose
    names are not all known (a star import, __getattr__, globals()), a star import added and a relative import that resolves to nothing of ours are
    unchecked. An import of a library is checked as far as it can be without side effects (library_unresolved): a stdlib module must have the name
    (an attribute, or a submodule of that name), a top-level package that is neither the stdlib's nor installed is unchecked, and a failed probe is
    unchecked; an installed package's names cannot be looked up, so its narrowing stays (I2). A bare `import X` of a library is only looked up
    (importlib.util.find_spec), never run; a dotted `import a.b` and a `from a import b` import the stdlib module they name. Any name with a __main__
    in it, and a stdlib module in NO_PROBE (one whose import does something), is never imported or looked up, and is unchecked"""
    repo = m.repo
    for _, src in items:
        if src[0] == "import":
            full = src[1]
            if full.split(".")[0] in m.repo_tops and full not in repo and not any(r.startswith(full + ".") for r in repo):
                return True
            if full.split(".")[0] not in m.repo_tops:
                head, _, last = full.rpartition(".")
                if (library_unresolved(head, last, True) if head else library_unresolved(last, None)):
                    return True
            continue
        _, level, module, name, _ = src
        if name == "*":
            return True
        base = m.resolve_from(level, module)
        if f"{base}.{name}" in repo:
            continue
        target = N.by_mod.get(base)
        if target is not None:
            if not target.ok or name not in target.defined:
                return True
        elif level or base.split(".")[0] in m.repo_tops:
            return True   # a module of ours that is not there, or a relative import that leads nowhere we know
        elif library_unresolved(base, name):
            return True
    return False


# stdlib modules whose import does something (opens a browser, prints, starts a GUI toolkit, runs a demo): never imported or looked up here, the import is
# unchecked. __hello__, __phello__, lib2to3 and test are not in the stdlib_module_names of 3.14 (they never get this far there, a top-level name that is
# neither the stdlib's nor installed is unchecked anyway) and stay for an older interpreter; a __main__ below a package is refused by name (library_unresolved)
NO_PROBE = {"antigravity", "this", "idlelib", "turtledemo", "tkinter", "turtle", "__hello__", "__phello__", "test", "lib2to3", "pydoc_data"}
_LIB = {}


def library_unresolved(module, name, as_module=False):
    """True when `from module import name` (`import module.name` with as_module, `import module` alone with name None) of a library may fail at import, or
    cannot be told: a top-level package that is neither the stdlib's nor installed (a suite could not import it either), a stdlib module that is not there
    (find_spec finds no `import msvcrt` on Linux; the module is not run), a stdlib module that has the name neither as an attribute nor as a submodule (as a
    submodule only, with as_module), and any failure of the probe. A stdlib module in NO_PROBE and any name with a __main__ in it (`import unittest.__main__`
    would run unittest, `import venv.__main__` would make a directory) is never imported or looked up: unchecked. Only a stdlib module is ever imported;
    an installed package keeps the narrowing (I2)"""
    top = module.split(".")[0]
    if top not in sys.stdlib_module_names:
        return top not in shadowable()
    if top in NO_PROBE or "__main__" in module.split(".") or name == "__main__":
        return True
    key = (module, name, as_module)
    if key not in _LIB:
        import importlib, importlib.util

        def tries(fn):   # a probe that fails (SystemExit included) is no proof that the name is there
            try:
                return bool(fn())
            except KeyboardInterrupt:
                raise
            except BaseException:
                return False
        if name is None:
            ok = tries(lambda: importlib.util.find_spec(module))   # `import msvcrt`: where the module is is all that is asked, it is not run
        elif as_module:
            ok = tries(lambda: importlib.import_module(f"{module}.{name}"))   # `import os.path`: a stdlib module, no side effect at import
        else:
            ok = tries(lambda: hasattr(importlib.import_module(module), name)) or tries(lambda: importlib.util.find_spec(f"{module}.{name}"))
        _LIB[key] = not ok
    return _LIB[key]


def quiet_import(N, S, path, mod):
    """True when a changed import of one of our modules adds nothing at import: the module only binds names and some suite
    ran it already, or every suite that runs the importing file runs the imported one already"""
    m = N.by_mod.get(mod)
    if m is None:
        return False
    if m.only_binds():
        # only binds names, but a module no suite ran yet is new to every importer: its calls (a local function at module
        # level) now run there, so the importer's own suites must run (readonly.py reached connectors this way)
        return any(m.path in e.get("py", {}) for e in S.values())
    return all(m.path in e.get("py", {}) for e in S.values() if path in e.get("py", {}))


def toml_items(text):
    """a set of (dotted path, value as typed JSON) for a TOML text: every table is (its path, "{}"), every other value its JSON (80 and
    80.0, true and 1 differ); None when the text does not parse"""
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError, TypeError):
        return None
    items = set()

    def walk(node, path):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, dict):
                items.add((p, "{}"))
                walk(v, p)
            else:
                items.add((p, json.dumps(v, sort_keys=True, default=str)))
    walk(data, "")
    return items


def instance_names(rev):
    """(paths, pinned) from tests/_instance.py at rev, read as data: `paths` the dotted paths of the settings apply() sets (SETTINGS, KEYWORDS,
    FLAG_SETTINGS) and of the tables it appends (TABLES: a table that holds a value of its own, an array of tables); `pinned` PINNED_TABLES.
    None when the file or one of the constants cannot be read as a literal"""
    return names_from_source(show(rev, INSTANCE))


def names_from_source(src):
    """instance_names() of the text of tests/_instance.py"""
    want = ("SETTINGS", "KEYWORDS", "FLAG_SETTINGS", "TABLES", "PINNED_TABLES")
    try:
        c = {}
        for node in ast.parse(src).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in want:
                c[node.targets[0].id] = ast.literal_eval(node.value)
        if set(c) != set(want):
            return None
        paths = {f"{s}.{k}" for d in (c["SETTINGS"], c["KEYWORDS"], *c["FLAG_SETTINGS"].values()) for s, keys in d.items() for k in keys}
        tables = tomllib.loads(c["TABLES"])

        def walk(node, path):
            if any(not isinstance(v, dict) and not (isinstance(v, list) and v and all(isinstance(x, dict) for x in v)) for v in node.values()):
                paths.add(path)
            for k, v in node.items():
                p = f"{path}.{k}" if path else k
                if isinstance(v, dict):
                    walk(v, p)
                elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    paths.add(p)
        walk(tables, "")
        pinned = c["PINNED_TABLES"]
        if not isinstance(pinned, (tuple, list, set, frozenset)) or not all(isinstance(x, str) for x in pinned):
            return None
        return paths, set(pinned)
    except (TypeError, ValueError, SyntaxError, KeyError, AttributeError, tomllib.TOMLDecodeError):
        return None


def code_lines(text):
    """(raw lines, [(index of the raw line, its code)]): a line's code is the line without its trailing comment (and the blanks before
    it); whole-line comments and blank lines have none and are left out. A line inside a multi-line string is code as it stands."""
    raw = text.split("\n")
    out, state = [], None            # state: the quote that is open at the start of a line ('"""' or "'''"), else None
    for n, line in enumerate(raw):
        started_in_string = state is not None
        i, cut = 0, None
        while i < len(line):
            if state is None:
                if line[i] == "#":
                    cut = i
                    break
                for q in ('"""', "'''", '"', "'"):
                    if line.startswith(q, i):
                        state, i = q, i + len(q) - 1
                        break
            elif state in ('"""', '"') and line[i] == "\\":
                i += 1
            elif line.startswith(state, i):
                i += len(state) - 1
                state = None
            i += 1
        if state in ('"', "'"):         # a one-line string left open at the end of its line: not TOML, the parse above has refused it already
            state = None
        code = line if cut is None else line[:cut].rstrip()
        if started_in_string or code.strip():
            out.append((n, code))
    return raw, out


PLAIN_COMMENT = re.compile(r"[A-Za-z .,;:!?()'-]*")


def name_words(paths, items):
    """the lowercase words of every name a fixture suite may patch, read or grep: the dotted paths of the constants of tests/_instance.py and
    of every table and key of the example (old and new)"""
    words = set()
    for p in list(paths) + [p for p, _ in items]:
        words |= set(re.findall(r"[a-z]+", p.lower()))
    return words


def plain_comment(line, words):
    """True for a blank line, or a whole-line comment of plain prose that names no setting (see *The example config*)"""
    s = line.strip()
    if not s:
        return True
    if not s.startswith("#"):
        return False
    text = s.lstrip("#").strip()
    if not PLAIN_COMMENT.fullmatch(text):
        return False
    low = text.lower()
    return not (set(re.findall(r"[a-z]+", low)) & words) and not any(w in low for w in words if len(w) >= 4)


def layout_only(ot, nt, pinned, words):
    """True when the two texts differ only in whole blank lines and plain whole-line comments (outside a multi-line string), the lines from a
    pinned table's header to its first code line are as they were, and no change starts at, or directly after, the first line (stackshot/cli.py anchors
    `\\A(# stackshot\\.example\\.toml)` on it; the test is wider than that line on purpose). Every other line is equal and in order, so the code is untouched."""
    oraw, oc = code_lines(ot)
    nraw, nc = code_lines(nt)

    def anchors(raw, cl):
        found = {}
        for k, (n, code) in enumerate(cl):
            m = re.match(r"\s*\[\s*([\w.-]+)\s*\]\s*$", code)
            if m and m.group(1) in pinned:
                end = cl[k + 1][0] if k + 1 < len(cl) else len(raw) - 1
                found[m.group(1)] = tuple(raw[n:end + 1])
        return found
    if anchors(oraw, oc) != anchors(nraw, nc) or oraw[:1] != nraw[:1]:
        return False
    ofree = set(range(len(oraw))) - {n for n, _ in oc}
    nfree = set(range(len(nraw))) - {n for n, _ in nc}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, oraw, nraw, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if i1 <= 1:      # a hunk that starts at old line 0 or 1: above the first line, or the first line itself
            return False
        for raw, free, lo, hi in ((oraw, ofree, i1, i2), (nraw, nfree, j1, j2)):
            if any(n not in free or not plain_comment(raw[n], words) for n in range(lo, hi)):
                return False
    return True


def data_change(a, b, old, new):
    """how the data file changed between a and b: 'same' (blank lines and plain comments only: see layout_only), 'changed' (anything else,
    the file added, deleted or renamed included), or None (a text that does not parse: the caller selects everything). Only 'same' is
    cheap; anything that does not classify is 'changed'."""
    if not (old and new):
        return "changed"
    ot, nt = show(a, old), show(b, new)
    if ot is None or nt is None:
        return None
    oi, ni = toml_items(ot), toml_items(nt)
    if oi is None or ni is None:
        return None
    names = instance_names(b)
    if names is None:
        return "changed"
    return "same" if layout_only(ot, nt, names[1], name_words(names[0], oi | ni)) else "changed"


def selection(m, a, b, pathspec=()):
    """(set of suites or 'all', [(file, reason)]) for the change a..b under map m"""
    if m is None:
        return "all", [("-", "no usable map")]
    if git("rev-parse", "--verify", "--quiet", f"{a}^{{commit}}") is None or git("rev-parse", "--verify", "--quiet", f"{b}^{{commit}}") is None:
        return "all", [("-", f"cannot resolve {a[:12]}..{b[:12]}")]
    S = m["suites"]
    now = set(suites_at(b))
    always = {s for s in now if s not in S or not S[s].get("ok")}
    sel, why = set(always), [(s, "no clean measurement: runs always") for s in sorted(always)]
    ns = git("diff", "--name-status", "-M", "--no-color", a, b, "--", *pathspec)
    if ns is None:
        return "all", [("-", "git diff failed")]
    shadow = names = None
    for row in ns.strip().split("\n"):
        if not row:
            continue
        st, *paths = row.split("\t")
        old, new = (None, paths[0]) if st[0] == "A" else (paths[0], None) if st[0] == "D" else (paths[0], paths[-1])
        f = new or old
        if any(p.startswith(HARNESS[0]) or p in HARNESS[1:] for p in (old, new) if p):
            return "all", why + [(f, "the harness or the gate itself")]
        if any(p in DATA.values() for p in (old, new)):
            return "all", why + [(f, "the link the fixture suites read the example config through: every suite")]
        ms = SUITE_RE.match(f)
        if ms:
            if ms.group(1) in now:
                sel.add(ms.group(1))
            why.append((f, "the suite itself"))
            continue
        if f.endswith(".lock"):
            why.append((f, "a script's lock: the lock step checks it"))
            continue
        if re.match(r"tests/\w+_check\.py$", f):
            why.append((f, "a manual check, not a CI suite"))
            continue
        added = new if st[0] == "A" or (st[0] == "R" and new != old) else None
        if added:
            # a new path is read only by code that names it (whose own change selects) or lists its directory (the listers,
            # below); a directory no measured suite lists may still be read by a name we never saw tried: fail open
            if not m.get("strace"):
                return "all", why + [(f, "a new file, and the map has no file measurement (no strace)")]
            d = os.path.dirname(added)
            if not any(d in e.get("dirs", ()) for e in S.values()):
                return "all", why + [(f, f"a new file in a directory no measured suite lists ({d + '/' if d else 'the top'})")]
        hit = set()
        if f.endswith(".py"):
            hit |= {s for s, e in S.items() if any(p in e.get("whole", ()) for p in (old, new) if p)}
            if names is None:
                names = (Names(a), Names(b))
            fns, bound, own, whole, docs = py_change(names, S, a, b, old, new)
            reached = 0
            ranfiles = {p for e in S.values() for p in e.get("py", {})}
            if bound:
                keys, w = reach(names, bound, ranfiles)
                whole |= w
                sc, direct = readers(names, keys)
                fns |= sc
                hit |= direct
                reached = len(keys)
            if docs:
                # a docstring alone: the suites whose own file names the function (or a binding that holds it), and a module-level
                # registration that reads it; not the callers' scopes, not what ran the body (the code that reads a docstring is in fns)
                keys, w = reach(names, docs, ranfiles)
                whole |= w
                hit |= doc_readers(names, keys)
            for s, e in S.items():
                py = e.get("py", {})
                if any(p in py for p in whole) or any(q in py.get(p, ()) for p, q in fns) \
                        or any(r == n or r.startswith(f"{n}.") for p, n in own for r in py.get(p, ())):
                    hit.add(s)
            if new and not old:
                # a new module at an import root (the checkout, tests/: the suites put both on sys.path) named like the
                # stdlib's or an installed package's would shadow it for every importer
                parts = new.removeprefix("tests/").split("/")
                if (new.startswith("tests/") and len(parts) == 1) or "/" not in new or not git("ls-tree", a, parts[0]):
                    if shadow is None:
                        shadow = shadowable()
                    top = parts[0].removesuffix(".py")
                    if top in shadow:
                        return "all", why + [(f, f"a new module named {top!r}, like one the suites import")]
            why.append((f, (f"whole ({', '.join(sorted(whole))})" if whole else
                            f"{len(fns)} function(s), {len(bound)} name(s) bound, {reached} reached"
                            + (f", {len(docs)} docstring(s) alone" if docs else "")) + f" → {len(hit)} suite(s)"))
        else:
            if not m.get("strace"):
                return "all", why + [(f, "the map has no file measurement (no strace)")]
            probe, note = [p for p in (old, new) if p], ""
            dp = next((p for p in probe if p in DATA), None)
            if dp:
                kind = data_change(a, b, old, new)
                if kind is None:
                    return "all", why + [(f, "does not parse, in the old text or the new: every suite")]
                if kind == "changed" or example_rule() == "A1":
                    probe.append(DATA[dp])
                note = ("blank lines and plain comments only: its direct readers" + (" and the fixture readers (rule A1)" if example_rule() == "A1" else "") if kind == "same" else
                        "a code line, a setting, a name or a comment that names one changed: its direct readers and the fixture readers") + "; "
            for s, e in S.items():
                if any(p in e.get("files", ()) for p in probe):
                    hit.add(s)
                if st[0] in "ADR":
                    if any(os.path.dirname(p) in e.get("dirs", ()) for p in (old, new) if p):
                        hit.add(s)
            why.append((f, note + (f"touched by {len(hit)} suite(s)" if hit else "no suite touches it")))
        sel |= hit & now
    for outer, inner in INNER.items():
        if outer in now and outer not in sel and sel & set(inner):
            sel.add(outer); why.append((outer, f"runs {', '.join(sorted(sel & set(inner)))} itself"))
    return ("all" if sel >= now else sel), why


def suites_at(rev):
    out = git("ls-tree", "-r", "--name-only", rev, "tests/") or ""
    return sorted(SUITE_RE.match(f).group(1) for f in out.split("\n") if SUITE_RE.match(f))


def summary(lines):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write("\n".join(lines) + "\n")


def select(args):
    m = load_map(args.map)
    to = args.to
    a = m["commit"] if m else to
    if m:
        have(a)
    sel, why = selection(m, a, to)
    total = len(suites_at(to))
    for f, r in why:
        print(f"suitemap: {f}: {r}", file=sys.stderr)
    if sel == "all":
        print("all")
        head = f"**Suites: all {total}** (map {a[:12] if m else 'none'})"
    else:
        print(" ".join(sorted(sel)))
        S = m["suites"]
        secs = sum(S.get(s, {}).get("seconds", 0) for s in sel)
        full = sum(S.get(s, {}).get("seconds", 0) for s in suites_at(to))
        head = (f"**Suites: {len(sel)} of {total}** (about {secs:.0f}s of {full:.0f}s; map of {a[:12]}): "
                + (", ".join(sorted(sel)) or "none"))
    summary(["### Suite selection", head, "", "| changed | reason |", "|---|---|"] + [f"| `{f}` | {r} |" for f, r in why])
    return 0


def audit(args):
    old, new = load_map(args.old), load_map(args.new)
    if old is None or new is None:
        print(f"suitemap: audit skipped: {'no earlier map' if old is None else 'no new map'}", file=sys.stderr)
        return 0
    # both sides over the same range, the old map's commit..to: a push's `before` can be later (a queued main run replaced
    # by a newer one leaves no map for it), and the change in between would go unchecked
    frm = old["commit"]
    gone = [what for what, c in (("the old map's commit", frm), ("the pushed commit", args.to)) if not have(c)]
    if gone:
        msg = f"the audit could not check: {' and '.join(gone)} ({frm[:12]}..{args.to[:12]}) does not resolve"
        print(f"::error::{msg}")
        summary(["### Selection audit", f"**{msg}**"])
        return 1
    ran, _ = selection(old, frm, args.to)
    should, why = selection(new, frm, args.to)
    if ran == "all":
        print("suitemap: audit: the change ran every suite", file=sys.stderr)
        return 0
    should = set(suites_at(args.to)) if should == "all" else should
    # a suite the new map has no clean measurement for (it failed only when measured, or timed out) is in `should` because the
    # selection always runs it, not because the change reaches it, and its partial measurement says nothing about reach: it is
    # no miss of the old choice (a real failure is `broke`, below)
    unclean = {s for s, e in new["suites"].items() if not e.get("ok")}
    missed = sorted(should - ran - unclean)
    # a suite that failed on main (measured, and again plainly) that the choice skipped: the miss itself, not a sign of one
    broke = sorted({s for s, e in new["suites"].items() if e.get("failed")} - ran)
    if broke:
        msg = (f"selection miss: {', '.join(broke)} failed on main after {frm[:12]}..{args.to[:12]}, and the map of "
               f"{old['commit'][:12]} did not choose it for that change")
        print(f"::error::{msg}")
        summary(["### Selection audit", f"**{msg}**"])
        return 1
    if missed:
        msg = (f"selection miss: {frm[:12]}..{args.to[:12]} reaches {', '.join(missed)} by the merged code's own measurement, "
               f"but the map of {old['commit'][:12]} chose {', '.join(sorted(ran)) or 'none'}")
        print(f"::error::{msg}")
        summary(["### Selection audit", f"**{msg}**", "", "| changed | reason (new map) |", "|---|---|"] + [f"| `{f}` | {r} |" for f, r in why])
        return 1
    print(f"suitemap: audit: no miss ({len(ran)} chosen, {len(should - unclean)} reached)", file=sys.stderr)
    summary(["### Selection audit", f"No miss: the map of {old['commit'][:12]} chose {len(ran)} suite(s); the merged code reaches {len(should - unclean)}."])
    return 0


def main():
    ap = argparse.ArgumentParser(prog="tests/suitemap.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("measure"); p.add_argument("--map", required=True); p.add_argument("--prev"); p.add_argument("-T", "--timeout", type=int, default=900); p.add_argument("suites", nargs="*")
    p = sub.add_parser("run"); p.add_argument("-T", "--timeout", type=int, default=600); p.add_argument("suites", nargs="*")
    p = sub.add_parser("plan"); p.add_argument("--of", type=int, required=True); p.add_argument("--map")
    p = sub.add_parser("shard"); p.add_argument("--of", type=int, required=True); p.add_argument("--index", type=int, required=True); p.add_argument("--map")
    p = sub.add_parser("merge"); p.add_argument("--map", required=True); p.add_argument("shards", nargs="+")
    p = sub.add_parser("select"); p.add_argument("--map", required=True); p.add_argument("--to", default="HEAD")
    p = sub.add_parser("audit"); p.add_argument("--old", required=True); p.add_argument("--new", required=True); p.add_argument("--to", required=True)
    args = ap.parse_args()
    example_rule()   # a typo in SUITEMAP_EXAMPLE_RULE is an error at once, not a silent default
    docstring_rule()
    import_rule()
    annotation_rule()
    route_rule()
    class_rule()
    if args.cmd == "list":
        print("\n".join(suites()))
        return 0
    return {"measure": measure, "run": run, "plan": plan, "shard": shard, "merge": merge, "select": select, "audit": audit}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
