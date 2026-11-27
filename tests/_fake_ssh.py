"""A stand-in for ssh on PATH, for suites of the reads the server makes on another machine: it records each call's arguments and runs the command in a folder that plays that machine's home folder.
No network, and nothing outside the folder given. The git of that machine records what it is asked too.

    ssh = FakeSsh(folder)          # folder/bin/ssh, folder/home
    with ssh:                      # first on PATH for the block
        ssh.mode("down")           # see below
        ssh.calls()                # [[argument, ...], ...] of ssh since the last clear()
        ssh.gits()                 # [[argument, ...], ...] of the git run over there since then, whether one session ran one or several

Modes ("<text>" picks the commands that hold it; with no text, every command):
    ""                  the command runs and answers
    "down"              no answer (exit 255)
    "fail <text>"       no answer for that command (exit 255)
    "banner <text>"     a line printed before the command's output
    "hang <text>"       nothing at all comes back (a minute, then exit 255): the caller's own time limit has to end it
    "cut <text>"        the first line of the output comes back, then the connection is lost (exit 255)
    "short <text>"      the first line of the output comes back, as from a command that ended there well
    "gitfail <text>"    the machine answers, the git run that holds <text> ends with its own failure (exit 128); the session's other commands run
    "noise <text>"      a line printed ahead of the output of the git run that holds <text>
    "slow <seconds>"    each command answers that much later
    "stuck"             git over there does not end (for STUCK_SECONDS)"""
import json
import os
import pathlib
import shutil
import sys

STUCK_SECONDS = 8      # the "git" of mode "stuck" ends by itself after this long, so none stays behind whatever the code under test does

SCRIPT = '''#!{python}
import json, os, subprocess, sys, time
args = sys.argv[1:]
with open({log!r}, "a") as f:
    f.write(json.dumps(args) + "\\n")
mode = open({mode!r}).read() if os.path.exists({mode!r}) else ""
word, _, text = mode.partition(" ")
host, command = args[-2], args[-1]
if mode == "down" or (word == "fail" and text in command):
    sys.stderr.write("ssh: connect to host %s: Connection timed out\\n" % host)
    sys.exit(255)
if word == "hang" and text in command:
    time.sleep(60)
    sys.exit(255)
if word == "slow":
    time.sleep(float(text))
if word == "banner" and text in command:
    print("Welcome to %s" % host, flush=True)
env = {{**os.environ, "HOME": {home!r}, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}}
env["PATH"] = {there!r} + os.pathsep + env["PATH"]
if mode == "stuck":
    env["PATH"] = {stuck!r} + os.pathsep + env["PATH"]
part = word in ("cut", "short") and text in command
ran = subprocess.run(["sh", "-c", command], cwd={home!r}, env=env, stdout=subprocess.PIPE if part else None)
if part:
    sys.stdout.buffer.write(ran.stdout.split(b"\\n")[0] + b"\\n")
    sys.stdout.flush()
    if word == "short":
        sys.exit(0)
    sys.stderr.write("client_loop: send disconnect: Broken pipe\\n")
    sys.exit(255)
sys.exit(ran.returncode)
'''

GIT = '''#!{python}
import json, os, sys
args = sys.argv[1:]
with open({log!r}, "a") as f:
    f.write(json.dumps(args) + "\\n")
word, _, text = (open({mode!r}).read() if os.path.exists({mode!r}) else "").partition(" ")
if word == "gitfail" and text in " ".join(args):
    sys.stderr.write("fatal: unable to read\\n")
    sys.exit(128)
if word == "noise" and text in " ".join(args):
    print("a line of another program", flush=True)
os.execv({git!r}, ["git", *args])
'''


def _lines(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


class FakeSsh:
    def __init__(self, folder):
        folder = pathlib.Path(folder)
        self.bin, self.home, stuck, there = folder / "bin", folder / "home", folder / "stuck", folder / "there"
        self.log, self.git_log, self.mode_file = folder / "ssh.log", folder / "git.log", folder / "ssh.mode"
        for d in (self.bin, self.home, stuck, there):
            d.mkdir(parents=True, exist_ok=True)
        for exe, body in ((self.bin / "ssh", SCRIPT.format(python=sys.executable, log=str(self.log), mode=str(self.mode_file), home=str(self.home), stuck=str(stuck), there=str(there))),
                          (there / "git", GIT.format(python=sys.executable, log=str(self.git_log), mode=str(self.mode_file), git=shutil.which("git"))),
                          (stuck / "git", f"#!/bin/sh\nexec sleep {STUCK_SECONDS}\n")):
            exe.write_text(body, encoding="utf-8")
            exe.chmod(0o755)
        self._path = None

    def __enter__(self):
        self._path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self._path}"
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self._path
        return False

    def mode(self, value):
        self.mode_file.write_text(value, encoding="utf-8")

    def calls(self):
        return _lines(self.log)

    def gits(self):
        return _lines(self.git_log)

    def clear(self):
        self.log.unlink(missing_ok=True)
        self.git_log.unlink(missing_ok=True)
