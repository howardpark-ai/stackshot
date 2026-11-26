"""A stand-in for ssh on PATH, for suites of the reads the server makes on another machine: it records each call's arguments and runs the command in a folder that plays that machine's home folder.
No network, and nothing outside the folder given.

    ssh = FakeSsh(folder)          # folder/bin/ssh, folder/home
    with ssh:                      # first on PATH for the block
        ssh.mode("down")           # see below
        ssh.calls()                # [[argument, ...], ...] since the last clear()

Modes ("<text>" picks the commands that hold it; with no text, every command):
    ""                  the command runs and answers
    "down"              no answer (exit 255)
    "fail <text>"       no answer for that command (exit 255)
    "banner <text>"     a line printed before the command's output
    "hang <text>"       nothing at all comes back (a minute, then exit 255): the caller's own time limit has to end it
    "cut <text>"        the first line of the output comes back, then the connection is lost (exit 255)
    "gitfail <text>"    the machine answers, the command ends with git's own failure (exit 128)
    "slow <seconds>"    each command answers that much later
    "stuck"             git over there does not end (for STUCK_SECONDS)"""
import json
import os
import pathlib
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
if word == "gitfail" and text in command:
    sys.stderr.write("fatal: unable to read\\n")
    sys.exit(128)
if word == "slow":
    time.sleep(float(text))
if word == "banner" and text in command:
    print("Welcome to %s" % host, flush=True)
env = {{**os.environ, "HOME": {home!r}, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}}
if mode == "stuck":
    env["PATH"] = {stuck!r} + os.pathsep + env["PATH"]
cut = word == "cut" and text in command
ran = subprocess.run(["sh", "-c", command], cwd={home!r}, env=env, stdout=subprocess.PIPE if cut else None)
if cut:
    sys.stdout.buffer.write(ran.stdout.split(b"\\n")[0] + b"\\n")
    sys.stdout.flush()
    sys.stderr.write("client_loop: send disconnect: Broken pipe\\n")
    sys.exit(255)
sys.exit(ran.returncode)
'''


class FakeSsh:
    def __init__(self, folder):
        folder = pathlib.Path(folder)
        self.bin, self.home, stuck = folder / "bin", folder / "home", folder / "stuck"
        self.log, self.mode_file = folder / "ssh.log", folder / "ssh.mode"
        for d in (self.bin, self.home, stuck):
            d.mkdir(parents=True, exist_ok=True)
        for exe, body in ((self.bin / "ssh", SCRIPT.format(python=sys.executable, log=str(self.log), mode=str(self.mode_file), home=str(self.home), stuck=str(stuck))),
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
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def clear(self):
        self.log.unlink(missing_ok=True)
