"""Platform selection and real background readiness without touching local data."""
from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledge_service.manager_runtime import available_port


@pytest.fixture
def scripts(monkeypatch):
    directory = Path(__file__).resolve().parent.parent / "scripts"
    monkeypatch.syspath_prepend(str(directory))

    def load(name):
        spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return load


@pytest.mark.parametrize("platform,folder,executable", [
    ("win32", "Scripts", "python.exe"), ("darwin", "bin", "python"), ("linux", "bin", "python")])
def test_environment_paths(scripts, tmp_path, platform, folder, executable):
    paths = scripts("platform_paths")
    root = tmp_path / "中文 project" / ".venv"
    assert paths.venv_executable(root, platform=platform) == root / folder / executable


@pytest.mark.parametrize("platform,without_ocr", [("win32", False), ("win32", True), ("darwin", False)])
def test_install_selects_native_dependencies(scripts, tmp_path, monkeypatch, platform, without_ocr):
    manage = scripts("manage")
    monkeypatch.setattr(manage, "PROJECT", tmp_path)
    monkeypatch.setattr(manage.sys, "platform", platform)
    monkeypatch.setattr(manage.platform, "machine", lambda: "arm64" if platform == "darwin" else "AMD64")
    calls = []
    monkeypatch.setattr(manage, "run", lambda *args: calls.append([str(a) for a in args]))
    manage.install(SimpleNamespace(without_ocr=without_ocr, with_openwebui=True))
    dependencies = [c for c in calls if "pip" in c and "install" in c]
    if platform == "win32" and not without_ocr:
        assert "requirements.lock.txt" in dependencies[0]
    else:
        assert (".[dev]" if without_ocr else ".[dev,ocr]") in dependencies[0]
        assert "requirements.lock.txt" not in dependencies[0]
    if platform == "darwin":
        assert "config/constraints-macos.txt" in dependencies[0]
        assert all("requirements-webui.lock.txt" not in c for c in dependencies)
    assert sum("check" in c and "pip" in c for c in calls) == 2


def test_install_stops_after_dependency_failure(scripts, monkeypatch):
    manage = scripts("manage")
    calls = []

    def fail(*args):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(manage, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        manage.install(SimpleNamespace(without_ocr=False, with_openwebui=True))
    assert len(calls) == 1


def test_intel_mac_webui_fails_before_installing(scripts, monkeypatch):
    manage = scripts("manage")
    monkeypatch.setattr(manage.sys, "platform", "darwin")
    monkeypatch.setattr(manage.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(manage, "run", lambda *args: pytest.fail("Must explain unsupported dependency first"))
    with pytest.raises(RuntimeError, match="no Intel macOS wheel"):
        manage.install(SimpleNamespace(without_ocr=False, with_openwebui=True))


def test_background_service_readiness(scripts, tmp_path, monkeypatch):
    manage = scripts("manage")
    project = tmp_path / "中文 project"
    project.mkdir()
    monkeypatch.setattr(manage, "PROJECT", project)
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(manage.subprocess, "Popen", capture)
    port = available_port()
    code = (
        "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  self.send_response(200);self.end_headers();self.wfile.write(b'{\"service\":\"test-service\"}')\n"
        f"HTTPServer(('127.0.0.1',{port}),Handler).serve_forever()\n"
    )
    try:
        manage.launch("test", [sys.executable, "-u", "-c", code], port, "test-service", background=True)
        assert manage.health(port) == {"service": "test-service"}
        assert int((project / "logs" / "test.pid").read_text()) == processes[0].pid
        manage.launch("test", [], port, "test-service", background=True)
        assert len(processes) == 1
        with pytest.raises(RuntimeError, match="another application"):
            manage.launch("test", [], port, "different-service", background=True)
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=10)


def test_webui_does_not_accept_unrelated_health(scripts):
    manage = scripts("manage")
    assert not manage.ready("openwebui", {"service": "other"}, None)
    assert manage.ready("openwebui", {"status": True}, None)


def test_foreground_manager_does_not_bootstrap_after_exit(scripts, tmp_path, monkeypatch):
    manage = scripts("manage")
    monkeypatch.setattr(manage, "PROJECT", tmp_path)
    static = tmp_path / "knowledge_service" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("ok")
    monkeypatch.setattr(manage, "launch", lambda *args, **kwargs: None)
    monkeypatch.setattr(manage, "request", lambda *args, **kwargs: pytest.fail("Server has exited"))
    manage.start_manager(SimpleNamespace(background=False, no_browser=False, port=8767), "python")


def test_macos_webui_exec_and_stop(scripts, tmp_path, monkeypatch):
    webui = scripts("run_openwebui")
    manage = scripts("manage")
    monkeypatch.setattr(webui.sys, "platform", "darwin")
    monkeypatch.setattr(webui, "PROJECT", tmp_path)
    monkeypatch.setattr(manage, "PROJECT", tmp_path)
    executable = tmp_path / ".venv-webui" / "bin" / "open-webui"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(webui, "Settings", lambda: SimpleNamespace(prepare=lambda: None))
    monkeypatch.setattr(webui, "environment", lambda settings: {"TEST": "1"})

    class Executed(Exception):
        pass

    def execute(path, argv, env):
        assert path == str(executable)
        assert argv[1:] == ["serve", "--host", "127.0.0.1", "--port", "8080"]
        assert env == {"TEST": "1"}
        raise Executed

    monkeypatch.setattr(webui.os, "execve", execute, raising=False)
    with pytest.raises(Executed):
        webui.main()
    pid_file = tmp_path / "logs" / "openwebui-child.pid"
    pid = int(pid_file.read_text())
    command = SimpleNamespace(returncode=0, stdout=f"python {executable} serve")
    monkeypatch.setattr(manage.subprocess, "run", lambda *args, **kwargs: command)
    signals = []
    monkeypatch.setattr(manage.os, "kill", lambda *args: signals.append(args))
    manage.stop_webui()
    assert signals == [(pid, signal.SIGTERM)]
    command.stdout = "another program"
    with pytest.raises(RuntimeError, match="refusing to stop"):
        manage.stop_webui()
    assert len(signals) == 1


def test_windows_webui_stop_validates_identity(scripts, tmp_path, monkeypatch):
    manage = scripts("manage")
    monkeypatch.setattr(manage.sys, "platform", "win32")
    monkeypatch.setattr(manage, "PROJECT", tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "openwebui-child.pid").write_text("1234")
    monkeypatch.setattr(manage.subprocess, "check_output", lambda *args, **kwargs: json.dumps("other.exe"))
    monkeypatch.setattr(manage.os, "kill", lambda *args: pytest.fail("Unrelated process must survive"))
    with pytest.raises(RuntimeError, match="refusing to stop"):
        manage.stop_webui()
