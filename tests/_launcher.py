"""The test launcher: a hook that lets a machine send a test run somewhere else, shared by tests/run-suite and tests/suitemap.py. Not a suite.

A person or an agent on a machine that should not run the tests types the plain command, `tests/run-suite <suite>` or
`python3 tests/suitemap.py <subcommand> ...`, and the run happens where the machine's launcher sends it, with the same output and exit code.
The repository names no machine and no tool: the machine supplies the launcher (a program) and says so in a one-line config file.

  * Config: the file `<XDG config home>/stackshot/test-launcher` (default `~/.config/stackshot/test-launcher`; `STACKSHOT_TEST_LAUNCHER_FILE`
    names another path). Its first line that is not blank and does not start with `#` is the launcher's command, split into words by the
    rules of a POSIX shell (quotes and backslashes; no expansion of any kind). No file, or one without such a line: no launcher.
  * `STACKSHOT_TEST_LAUNCHER`, when set, replaces that line; set to an empty string it means no launcher for this run (a local run on purpose).
  * The call: `<launcher> --git <history|snapshot> -- <the original command and its arguments>`, started in the caller's working directory
    (the checkout's root, for a run from there). `history` when the run reads git (the suites in HISTORY_SUITES, and every suitemap.py subcommand but `run`:
    `list`, `plan`, `measure`, `select` and `audit` ask git for the tracked suites, a commit or a diff), `snapshot` when the files alone are enough
    (`suitemap.py run` of suites that read no history). A far side given `snapshot` may have no git at all. The launcher takes the place of this process (exec): its output and
    exit code are the run's, and nothing is added on stdout. One line on stderr, `running through the test launcher: <launcher>`, says why the
    run is not local; `STACKSHOT_TEST_LAUNCHER_QUIET` set to anything but empty or 0 drops it.
  * The loop guard: the launcher's side is started with `STACKSHOT_TEST_LAUNCHED=1` in the environment, and while that variable is set (non-empty)
    nothing launches again. A launcher whose far side runs the command with the variable carried never loops, and `suitemap.py run`'s calls
    of tests/run-suite stay where the first one ran.
  * `suitemap.py select` with no --map and no fetched map asks `configured` and, where a launcher is named and the run is not launched yet, tries
    `suitemap.py fetch` once before the call, so the map travels with the tree.
  * A launcher that is not there, not executable, or whose line cannot be split is said once on stderr (`test launcher <line> is not executable:
    running here`) and the run is local: a bad config never fails a run.

tests/run-suite asks this file only when a launcher could apply (the variable set and not empty, or the config file present), so a run with no
launcher configured costs it one `test -f`. `python3 tests/_launcher.py resolve <suite>` is that ask: it prints the launcher's command line, quoted
for `eval`, with its `--git` mode, or prints nothing when the run stays here."""
import os
import shlex
import shutil
import sys

LAUNCHED = "STACKSHOT_TEST_LAUNCHED"
HISTORY_SUITES = ("suitemap", "clean_text")       # the suites that read the checkout's git history (a snapshot of the files lacks it)


def config_file():
    path = os.environ.get("STACKSHOT_TEST_LAUNCHER_FILE")
    if path:
        return path
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "stackshot", "test-launcher")


def _line():
    """the launcher's command line as written, or None for no launcher"""
    if os.environ.get(LAUNCHED):
        return None
    if "STACKSHOT_TEST_LAUNCHER" in os.environ:
        return os.environ["STACKSHOT_TEST_LAUNCHER"].strip() or None
    try:
        with open(config_file(), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except (OSError, UnicodeDecodeError):
        pass
    return None


def configured():
    """True when a launcher is named and this run was not started by one: this machine is where such runs are typed (one that cannot be used counts: `begin` says so)"""
    return _line() is not None


def _quiet():
    return os.environ.get("STACKSHOT_TEST_LAUNCHER_QUIET", "") not in ("", "0")


def launcher():
    """the launcher's words, or None when the run stays here (no launcher, the guard set, or a launcher that cannot be used: said once)"""
    line = _line()
    if line is None:
        return None
    try:
        words = shlex.split(line)
    except ValueError:
        print(f"test launcher {line} is not executable: running here", file=sys.stderr)
        return None
    if not words or shutil.which(words[0]) is None:
        print(f"test launcher {words[0] if words else line} is not executable: running here", file=sys.stderr)
        return None
    return words


def mode_for_suites(suites):
    """`history` when one of the suites reads the git history; none named means every suite"""
    return "history" if not suites or any(s in HISTORY_SUITES for s in suites) else "snapshot"


def begin(mode):
    """the argv prefix that starts the launcher for this run (it ends in `--`), or None to run here. Says why the run is not local, once."""
    words = launcher()
    if words is None:
        if _line() is not None:
            os.environ[LAUNCHED] = "1"       # a launcher was meant and cannot be used: the calls this run makes stay here, and say nothing again
        return None
    if not _quiet():
        print(f"running through the test launcher: {shlex.join(words)}", file=sys.stderr, flush=True)
    return [*words, "--git", mode, "--"]


def relaunch(mode, command):
    """take the launcher's place in this process with `command` (a list: the original command line), or return when the run stays here"""
    prefix = begin(mode)
    if prefix is None:
        return
    os.environ[LAUNCHED] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.execvpe(prefix[0], [*prefix, *command], os.environ)
    except OSError:
        print(f"test launcher {prefix[0]} is not executable: running here", file=sys.stderr)
        os.environ.pop(LAUNCHED, None)


def main(argv):
    if len(argv) != 2 or argv[0] != "resolve":
        print("usage: _launcher.py resolve <suite>", file=sys.stderr)
        return 2
    prefix = begin(mode_for_suites([argv[1]]))
    if prefix:
        print(shlex.join(prefix[:-1]))       # run-suite adds the `--` and the command itself
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
