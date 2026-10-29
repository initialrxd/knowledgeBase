"""Install and manage local services on Windows and macOS using Python 3.11/3.12."""
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
import webbrowser
from pathlib import Path

from platform_paths import venv_executable

PROJECT = Path(__file__).resolve().parent.parent
INSTALL_HELP = "Run Python 3.11/3.12 scripts/manage.py install first."


def run(*args):
    subprocess.run([str(a) for a in args], cwd=PROJECT, check=True)


def install(args):
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        raise RuntimeError("Python 3.11 or 3.12 is required.")
    if args.with_openwebui and sys.platform == "darwin" and platform.machine() == "x86_64":
        raise RuntimeError("Open WebUI 0.12.3 pins ONNX Runtime 1.26.0, which has no Intel macOS wheel. "
                           "Install without --with-openwebui to use the console and HTTP/MCP service.")
    python = venv_executable(PROJECT / ".venv")
    if not python.exists():
        run(sys.executable, "-m", "venv", PROJECT / ".venv")
    # Windows freezes are snapshots of a Windows resolver. Resolve natively on macOS,
    # including architecture-specific constraints for native libraries.
    if sys.platform == "win32" and not args.without_ocr:
        run(python, "-m", "pip", "install", "-r", "requirements.lock.txt")
        run(python, "-m", "pip", "install", "--no-deps", "-e", ".")
    else:
        extra = ".[dev]" if args.without_ocr else ".[dev,ocr]"
        constraints = ["-c", "config/constraints-macos.txt"] if sys.platform == "darwin" else []
        run(python, "-m", "pip", "install", *constraints,
            "--only-binary=lancedb,onnxruntime,pyarrow,pymupdf,numpy", "-e", extra)
    run(python, "-m", "pip", "check")
    run(python, "-m", "knowledge_service.cli", "init")
    run(python, "-c", "from knowledge_service.config import Settings; s=Settings(); s.prepare(); "
        "from knowledge_service.text import encoding; encoding(s.tokenizer); print('Tokenizer ready')")
    if args.with_openwebui:
        web_python = venv_executable(PROJECT / ".venv-webui")
        if not web_python.exists():
            run(sys.executable, "-m", "venv", PROJECT / ".venv-webui")
        if sys.platform == "win32":
            run(web_python, "-m", "pip", "install", "-r", "requirements-webui.lock.txt")
        else:
            constraints = ["-c", "config/constraints-macos.txt"] if sys.platform == "darwin" else []
            run(web_python, "-m", "pip", "install", *constraints, "numpy>=2,<2.3", "open-webui==0.12.3")
        run(web_python, "-m", "pip", "check")
    print("Installed. Configure .env, then run scripts/manage.py start-all.")


def request(port, path, *, token=None, post=False):
    headers = {"Authorization": "Bearer " + token} if token else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers,
                                 method="POST" if post else "GET", data=b"" if post else None)
    # Local service traffic must not go through a machine's HTTP proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=2) as response:
        return json.load(response)


def health(port):
    try:
        return request(port, "/health")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def launch(name, command, port, service, *, background):
    state = health(port)
    if state is not None:
        if not ready(name, state, service):
            raise RuntimeError(f"Port {port} belongs to another application.")
        return
    if not background:
        run(*command)
        return
    logs = PROJECT / "logs"
    logs.mkdir(exist_ok=True)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with (logs / f"{name}.out.log").open("ab") as stdout, (logs / f"{name}.err.log").open("ab") as stderr:
        process = subprocess.Popen([str(a) for a in command], cwd=PROJECT, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, **options)
    (logs / f"{name}.pid").write_text(str(process.pid), encoding="utf-8")
    deadline = time.monotonic() + (180 if name == "openwebui" else 45)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited; see logs/{name}.err.log.")
        state = health(port)
        if state is not None:
            if ready(name, state, service):
                print(f"{name} ready: http://127.0.0.1:{port}")
                return
            raise RuntimeError(f"Port {port} belongs to another application.")
        time.sleep(0.3)
    raise RuntimeError(f"{name} startup timed out; see logs/{name}.err.log (PID {process.pid}).")


def ready(name, state, service):
    return state.get("status") is True if name == "openwebui" else state.get("service") == service


def start_manager(args, python):
    if not (PROJECT / "knowledge_service" / "static" / "index.html").is_file():
        raise RuntimeError("Build the UI first: run npm ci and npm run build in frontend/.")
    launch("manager", [python, "-X", "utf8", "-m", "knowledge_service.manager", "--port", str(args.port)],
           args.port, "knowledge-manager", background=args.background)
    if args.background and not args.no_browser:
        secrets = json.loads((PROJECT / "manager-data" / "secrets.json").read_text("utf-8"))
        login = request(args.port, "/manager/api/bootstrap", token=secrets["manager_admin"], post=True)
        webbrowser.open(f"http://127.0.0.1:{args.port}/#login={login['token']}")


def stop_webui():
    pid_file = PROJECT / "logs" / "openwebui-child.pid"
    if not pid_file.exists():
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
        return
    expected = str(venv_executable(PROJECT / ".venv-webui", "open-webui"))
    if expected not in command:
        raise RuntimeError("PID no longer belongs to this Open WebUI; refusing to stop it.")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    # Keep the PID record until the next start (or absence check), including while
    # graceful shutdown is in progress. Never force-kill a database writer.
    print("Open WebUI shutdown requested.")


def stop_all(args, python):
    state = health(args.port)
    if state is not None:
        if state.get("service") != "knowledge-manager":
            raise RuntimeError(f"Port {args.port} belongs to another application.")
        secrets = json.loads((PROJECT / "manager-data" / "secrets.json").read_text("utf-8"))
        request(args.port, "/manager/api/shutdown", token=secrets["manager_admin"], post=True)
        print("Manager is saving checkpoints and stopping managed services.")
    else:
        sys.path.insert(0, str(PROJECT))
        from knowledge_service.config import Settings
        settings = Settings()
        if health(settings.port) is not None:
            request(settings.port, "/admin/shutdown", token=settings.admin_token.get_secret_value(), post=True)
            print("Knowledge service shutdown requested.")
    stop_webui()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("install")
    setup.add_argument("--with-openwebui", action="store_true")
    setup.add_argument("--without-ocr", action="store_true")
    for name in ("start-manager", "start-knowledge", "start-openwebui", "start-all", "stop-all"):
        command = commands.add_parser(name)
        command.add_argument("--port", type=int, default=8767, help="Manager port (default: 8767)")
        command.add_argument("--no-browser", action="store_true")
        command.add_argument("--background", action="store_true")
    args = parser.parse_args()
    os.chdir(PROJECT)
    os.environ["PYTHONUTF8"] = "1"
    if args.command == "install":
        install(args)
        return
    python = venv_executable(PROJECT / ".venv")
    if not python.exists():
        raise RuntimeError(INSTALL_HELP)
    # Keep imports and subprocesses in the project's environment, even when this
    # entry point was invoked with a global Python.
    if Path(sys.prefix).resolve() != (PROJECT / ".venv").resolve():
        run(python, "-X", "utf8", Path(__file__).resolve(), *sys.argv[1:])
        return
    if args.command == "stop-all":
        stop_all(args, python)
        return
    if args.command == "start-all":
        if not venv_executable(PROJECT / ".venv-webui", "open-webui").exists():
            raise RuntimeError("Install with --with-openwebui first, or use start-manager alone.")
        args.background = True
    if args.command in ("start-manager", "start-all"):
        start_manager(args, python)
    if args.command == "start-knowledge":
        sys.path.insert(0, str(PROJECT))
        from knowledge_service.config import Settings
        launch("knowledge", [python, "-X", "utf8", "-m", "knowledge_service.cli", "serve"],
               Settings().port, "knowledge-admin", background=args.background)
    if args.command in ("start-openwebui", "start-all"):
        if not venv_executable(PROJECT / ".venv-webui", "open-webui").exists():
            raise RuntimeError("Install with --with-openwebui first.")
        launch("openwebui", [python, "-X", "utf8", PROJECT / "scripts" / "run_openwebui.py"],
               8080, None, background=args.background)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
