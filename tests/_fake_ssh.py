"""A stand-in for ssh on PATH, for suites of the reads the server makes on another machine: it records each call's arguments and runs the command in a folder that plays that machine's home folder.
No network, and nothing outside the folder given.

    ssh = FakeSsh(folder)          # folder/bin/ssh, folder/home
    with ssh:                      # first on PATH for the block
        ssh.mode("down")           # "" answers · "down" no answer (exit 255) · "fail <text>" no answer for a command holding <text> · "banner" a line printed before the command's output
        ssh.calls()                # [[argument, ...], ...] since the last clear()"""
import json
import os
import pathlib
import sys

SCRIPT = '''#!{python}
import json, os, subprocess, sys
args = sys.argv[1:]
with open({log!r}, "a") as f:
    f.write(json.dumps(args) + "\\n")
mode = open({mode!r}).read() if os.path.exists({mode!r}) else ""
host, command = args[-2], args[-1]
if mode == "down" or (mode.startswith("fail ") and mode[5:] in command):
    sys.stderr.write("ssh: connect to host %s: Connection timed out\\n" % host)
    sys.exit(255)
if mode == "banner":
    print("Welcome to %s" % host, flush=True)
env = {{**os.environ, "HOME": {home!r}, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}}
sys.exit(subprocess.run(["sh", "-c", command], cwd={home!r}, env=env).returncode)
'''


class FakeSsh:
    def __init__(self, folder):
        folder = pathlib.Path(folder)
        self.bin, self.home = folder / "bin", folder / "home"
        self.log, self.mode_file = folder / "ssh.log", folder / "ssh.mode"
        for d in (self.bin, self.home):
            d.mkdir(parents=True, exist_ok=True)
        exe = self.bin / "ssh"
        exe.write_text(SCRIPT.format(python=sys.executable, log=str(self.log), mode=str(self.mode_file), home=str(self.home)), encoding="utf-8")
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
