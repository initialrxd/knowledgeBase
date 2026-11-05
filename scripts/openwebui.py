"""Install and manage the optional Open WebUI validation client independently."""
from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from platform_paths import venv_executable

PROJECT = Path(__file__).resolve().parent.parent
PORT = 8080


def run(*args):
    subprocess.run([str(a) for a in args], cwd=PROJECT, check=True)


def install():
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError("Python 3.11 or 3.12 is required.")
    if sys.platform == "darwin" and platform.machine() == "x86_64":
        raise RuntimeError("Open WebUI 0.12.3 pins ONNX Runtime 1.26.0, which has no Intel macOS wheel.")
    python = venv_executable(PROJECT / ".venv-webui")
    if not python.exists():
        run(sys.executable, "-m", "venv", PROJECT / ".venv-webui")
    if sys.platform == "win32":
        run(python, "-m", "pip", "install", "-r", "requirements-webui.lock.txt")
    else:
        constraints = ["-c", "config/constraints-macos.txt"] if sys.platform == "darwin" else []
        run(python, "-m", "pip", "install", *constraints, "numpy>=2,<2.3", "open-webui==0.12.3")
    run(python, "-m", "pip", "check")
    print("Optional Open WebUI client installed. Start it separately with scripts/openwebui.py start.")


def health():
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{PORT}/health")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def start(background):
    state = health()
    if state is not None:
        if state.get("status") is not True:
            raise RuntimeError(f"Port {PORT} belongs to another application.")
        print(f"Open WebUI is already running: http://127.0.0.1:{PORT}")
        return
    core_python = venv_executable(PROJECT / ".venv")
    executable = venv_executable(PROJECT / ".venv-webui", "open-webui")
    if not core_python.exists():
        raise RuntimeError("Install the knowledge service first; Open WebUI uses its public connection settings.")
    if not executable.exists():
        raise RuntimeError("Install Open WebUI separately with scripts/openwebui.py install first.")
    command = [str(core_python), "-X", "utf8", str(PROJECT / "scripts" / "run_openwebui.py")]
    if not background:
        run(*command)
        return
    logs = PROJECT / "logs" / "openwebui"
    logs.mkdir(parents=True, exist_ok=True)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with (logs / "stdout.log").open("ab") as stdout, (logs / "stderr.log").open("ab") as stderr:
        process = subprocess.Popen(command, cwd=PROJECT, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, **options)
    (logs / "launcher.pid").write_text(str(process.pid), encoding="utf-8")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Open WebUI exited; see logs/openwebui/stderr.log.")
        state = health()
        if state is not None:
            if state.get("status") is True:
                print(f"Open WebUI ready: http://127.0.0.1:{PORT}")
                return
            raise RuntimeError(f"Port {PORT} belongs to another application.")
        time.sleep(0.3)
    raise RuntimeError("Open WebUI startup timed out; see logs/openwebui/stderr.log.")


def stop():
    pid_file = PROJECT / "openwebui-data" / "openwebui.pid"
    if not pid_file.exists():
        print("Open WebUI is not running.")
        return
    pid = int(pid_file.read_text("utf-8").strip())
    if pid <= 0:
        raise RuntimeError("Invalid Open WebUI PID.")
    if sys.platform == "win32":
        command = subprocess.check_output(["powershell", "-NoProfile", "-Command",
            f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | "
            "Select-Object -ExpandProperty CommandLine | ConvertTo-Json"], text=True).strip()
        command = json.loads(command) if command else ""
    else:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
        if result.returncode not in (0, 1):
            raise RuntimeError("Cannot verify Open WebUI process identity.")
        command = result.stdout.strip()
    if not command:
        pid_file.unlink(missing_ok=True)
        print("Open WebUI is not running.")
        return
    expected = str(venv_executable(PROJECT / ".venv-webui", "open-webui"))
    if expected not in command:
        raise RuntimeError("PID no longer belongs to this Open WebUI; refusing to stop it.")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    print("Open WebUI shutdown requested.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install")
    launch = commands.add_parser("start")
    launch.add_argument("--background", action="store_true")
    commands.add_parser("stop")
    args = parser.parse_args()
    os.chdir(PROJECT)
    os.environ["PYTHONUTF8"] = "1"
    if args.command == "install":
        install()
    elif args.command == "start":
        start(args.background)
    else:
        stop()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
