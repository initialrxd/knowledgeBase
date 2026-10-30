"""Worker supervision and per-library configuration. No shared vector stores."""
from __future__ import annotations

import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

import httpx
import portalocker

from .config import IngestionTuning, LibraryTuning, RetrievalTuning, Settings
from .manager_store import Registry, settings_values
from .providers import ProviderError, Providers


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Manager:
    def __init__(self, project: Path, settings: Settings, port=8767, seed=True):
        self.project, self.base, self.port = project.resolve(), settings, port
        self.registry = Registry(self.project / "manager-data")
        if seed:
            self.registry.seed(settings)
            self.registry.sync_default_environment(self.project)
        self.registry.refresh_model_settings(settings)
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="manager")
        self.status_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="manager-status")
        self.operations = {}
        self.processes = {}
        self.worker_states = {}
        self.worker_locks = {}
        self.listeners = {}
        self.listener_errors = {}
        self.probe_locks = {}
        self.probe_after = {}
        self.closing = False
        self.shutdown_event = threading.Event()
        self._lock = threading.RLock()

    def submit(self, function, *args):
        identifier = uuid.uuid4().hex
        row = {"id": identifier, "status": "queued", "created": time.time()}
        self.operations[identifier] = row

        def run():
            row["status"] = "running"
            try:
                row["result"] = function(*args)
                row["status"] = "done"
            except Exception as error:
                row["error"] = str(error) if isinstance(error, (ValueError, KeyError, ProviderError)) else type(error).__name__
                row["status"] = "failed"
            row["updated"] = time.time()
        self.pool.submit(run)
        # Keep operation polling bounded without discarding operations still in progress.
        completed = [key for key, value in list(self.operations.items()) if value["status"] in ("done", "failed")]
        for key in completed[:-200]:
            self.operations.pop(key, None)
        return dict(row)

    def request(self, kb_id, method, path, *, tools=False, **kwargs):
        kb = self.registry.get("kb", kb_id)
        settings = self.registry.worker_settings(kb)
        port = kb["tools_port"] if tools else kb["admin_port"]
        if not port:
            raise ProviderError("知识库尚未启动")
        token = settings.api_token if tools else settings.admin_token
        try:
            with httpx.Client(timeout=kwargs.pop("timeout", 10), trust_env=False) as client:
                response = client.request(method, f"http://127.0.0.1:{port}{path}",
                    headers={"Authorization": "Bearer " + token.get_secret_value()}, **kwargs)
            if response.is_error:
                if response.status_code in (400, 404, 422):
                    raise ValueError(str(response.json().get("detail", "Invalid worker request"))[:1000])
                raise ProviderError(f"知识库服务返回 HTTP {response.status_code}")
            return response.json()
        except httpx.HTTPError:
            raise ProviderError("无法连接知识库服务，请检查运行状态") from None

    def _worker_lock(self, identifier):
        with self._lock:
            return self.worker_locks.setdefault(identifier, threading.RLock())

    def _free_worker_port(self):
        reserved = {self.port, *(m["port"] for m in self.registry.list("mcp"))}
        for kb in self.registry.list("kb"):
            reserved.update((kb["admin_port"], kb["tools_port"]))
        for _ in range(100):
            port = available_port()
            if port not in reserved:
                return port
        raise ValueError("未能分配知识库内部端口")

    def start_worker(self, identifier):
        with self._worker_lock(identifier):
            kb = self.registry.get("kb", identifier)
            self.worker_states[identifier] = "starting"
            try:
                # Reattach workers left running after an interrupted manager session.
                if kb["tools_port"]:
                    try:
                        state = self.request(identifier, "GET", "/admin/status", timeout=2)
                        self.request(identifier, "GET", "/v1/categories", tools=True, timeout=2)
                        if state.get("data_dir") and Path(state["data_dir"]).resolve() != Path(kb["data_dir"]):
                            raise ValueError("内部端口属于另一个知识库")
                        profile = self.registry.get("embedding", kb["embedding_id"])
                        if (state["configured_profile"] == self.registry.worker_settings(kb).profile
                                and kb.get("applied_embedding_version") == profile.get("version")
                                and kb.get("applied_settings_version") == kb.get("settings_version")):
                            known = {Path(root["path"]).resolve() for root in state.get("roots", [])}
                            for path in kb.get("pending_source_dirs", []):
                                if Path(path).resolve() not in known:
                                    self.request(identifier, "POST", "/admin/actions",
                                                 json={"action": "add_root", "args": {"path": path}})
                            if kb.get("pending_source_dirs"):
                                kb["pending_source_dirs"] = []
                                self.registry.put("kb", kb)
                            self.worker_states[identifier] = "running"
                            return {"running": True, "reattached": True}
                        self.stop_worker(identifier)
                        self.worker_states[identifier] = "starting"
                    except (ValueError, ProviderError):
                        pass
                if kb.get("legacy") and not kb["tools_port"]:
                    # The valid existing admin credential authorizes graceful ownership transfer.
                    try:
                        self.request(identifier, "GET", "/admin/status", timeout=2)
                    except (ValueError, ProviderError):
                        pass
                    else:
                        self.request(identifier, "POST", "/admin/shutdown")
                        self._wait_unlocked(kb)
                with self._lock:
                    kb["admin_port"] = kb["admin_port"] or self._free_worker_port()
                    self.registry.put("kb", kb)
                    kb["tools_port"] = kb["tools_port"] or self._free_worker_port()
                    self.registry.put("kb", kb)
                settings = self.registry.worker_settings(kb)
                env = os.environ.copy()
                env["KNOWLEDGE_WORKER_SETTINGS"] = json.dumps(settings_values(settings))
                env["KNOWLEDGE_WORKER_SOURCES"] = json.dumps(kb.get("pending_source_dirs", []))
                env["TIKTOKEN_CACHE_DIR"] = os.environ.get("TIKTOKEN_CACHE_DIR", str(self.base.root / "cache" / "tiktoken"))
                env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
                env["PYTHONUTF8"] = "1"
                log_dir = self.registry.directory / "logs"
                log_dir.mkdir(exist_ok=True)
                with (log_dir / f"{identifier}.log").open("ab") as output:
                    process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "knowledge_service.worker"],
                        cwd=self.project, env=env, stdout=output, stderr=output,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.processes[identifier] = process
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise ValueError("知识库启动失败，请检查端口冲突或数据目录占用；详情见本机 worker 日志")
                    try:
                        self.request(identifier, "GET", "/admin/status", timeout=1)
                        self.request(identifier, "GET", "/v1/categories", tools=True, timeout=1)
                        self.worker_states[identifier] = "running"
                        kb["applied_embedding_version"] = self.registry.get("embedding", kb["embedding_id"]).get("version")
                        kb["applied_settings_version"] = kb.get("settings_version")
                        kb["pending_source_dirs"] = []
                        self.registry.put("kb", kb)
                        return {"running": True, "pid": process.pid}
                    except (ValueError, ProviderError):
                        time.sleep(0.25)
                raise ValueError("知识库启动超时，请检查本机 worker 日志")
            except Exception:
                self.worker_states[identifier] = "error"
                raise

    def _wait_unlocked(self, kb):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                with portalocker.Lock(str(Path(kb["data_dir"]) / "service.lock"), timeout=0):
                    return
            except portalocker.exceptions.LockException:
                time.sleep(0.3)
        raise ValueError("服务仍在保存当前批次，尚未释放目录；请等待后重试，未强制结束进程")

    def stop_worker(self, identifier):
        with self._worker_lock(identifier):
            kb = self.registry.get("kb", identifier)
            self.worker_states[identifier] = "stopping"
            try:
                self.request(identifier, "POST", "/admin/shutdown", timeout=3)
            except ProviderError:
                pass
            self._wait_unlocked(kb)
            process = self.processes.pop(identifier, None)
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise ValueError("知识库进程仍在退出，请稍后重试") from None
            self.worker_states[identifier] = "stopped"
            return {"stopped": True}

    def restart_worker(self, identifier):
        with self._worker_lock(identifier):
            self.stop_worker(identifier)
            return self.start_worker(identifier)

    def _validate_storage(self, path, exclude=None):
        if path == self.project or self.project.is_relative_to(path):
            raise ValueError("存储目录不能包含整个项目")
        reserved = [self.registry.directory, self.project / "knowledge_service", self.project / "frontend"]
        reserved += [Path(k["data_dir"]) for k in self.registry.list("kb") if k["id"] != exclude]
        for other in reserved:
            if path.is_relative_to(other) or other.is_relative_to(path):
                raise ValueError("知识库存储目录不能与其他库或应用目录重叠")
        for kb in self.registry.list("kb"):
            metadata = Path(kb["data_dir"]) / "metadata.sqlite3"
            if not metadata.is_file():
                continue
            try:
                with closing(sqlite3.connect(metadata.as_uri() + "?mode=ro", uri=True, timeout=5)) as con:
                    sources = con.execute("SELECT path FROM roots").fetchall()
            except sqlite3.Error:
                raise ValueError("无法检查已有知识库的来源目录，请先修复其元数据") from None
            if any(path.is_relative_to(Path(row[0]).resolve()) or Path(row[0]).resolve().is_relative_to(path) for row in sources):
                raise ValueError("存储目录不能与已有知识库的来源目录重叠")
        if path.exists() and any(path.iterdir()):
            raise ValueError("新知识库的存储目录必须为空；已有默认库通过接管接入")

    def save_kb(self, value, identifier=None):
        restart = False
        start = False
        with self._lock:
            self.registry.get("embedding", value["embedding_id"])
            if identifier:
                kb = self.registry.get("kb", identifier)
                changed = kb["embedding_id"] != value["embedding_id"]
                if value.get("data_dir") and Path(value["data_dir"]).resolve() != Path(kb["data_dir"]):
                    raise ValueError("已有库的存储目录不能直接更改，请使用导出/恢复迁移")
                kb.update(name=value["name"], embedding_id=value["embedding_id"], auto_start=value["auto_start"])
                self.registry.put("kb", kb)
                restart = changed and self.worker_states.get(identifier) == "running"
            else:
                identifier = uuid.uuid4().hex
                path = Path(value.get("data_dir") or self.project / "knowledge-bases" / identifier).resolve()
                self._validate_storage(path)
                source_dirs = self._validate_source_dirs(value.get("source_dirs", []), path)
                path.mkdir(parents=True, exist_ok=True)
                kb = {"id": identifier, "name": value["name"], "embedding_id": value["embedding_id"],
                      "auto_start": value["auto_start"], "data_dir": str(path), "admin_port": 0, "tools_port": 0,
                      "source_dirs": source_dirs, "pending_source_dirs": source_dirs}
                settings = settings_values(self.base)
                settings.update(api_token=secrets.token_urlsafe(32), admin_token=secrets.token_urlsafe(32))
                self.registry.secret("settings:" + identifier, settings)
                self.registry.put("kb", kb)
                start = kb["auto_start"]
        # Never acquire a worker lock while holding the registry coordination lock.
        if restart:
            self.restart_worker(identifier)
        elif start:
            self.start_worker(identifier)
        if identifier == "default":
            self.registry.sync_default_environment(self.project)
        return kb

    def save_tuning(self, identifier, value, scope=None):
        models = {None: LibraryTuning, "ingestion": IngestionTuning, "retrieval": RetrievalTuning}
        if scope not in models:
            raise ValueError("Unknown settings scope")
        patch = models[scope].model_validate(value).model_dump()
        with self._lock:
            kb = self.registry.get("kb", identifier)
            previous = LibraryTuning.from_settings(self.registry.worker_settings(kb)).model_dump()
            tuning = LibraryTuning.model_validate({**previous, **patch}).model_dump()
            kb["tuning"] = tuning
            self.registry.put("kb", kb)
            restart = tuning != previous and self.worker_states.get(identifier) == "running"
        if restart:
            self.restart_worker(identifier)
        if identifier == "default":
            self.registry.sync_default_environment(self.project)
        return {"tuning": tuning, "restarted": restart}

    def _validate_source_dirs(self, source_dirs, storage):
        sources = []
        reserved = [Path(k["data_dir"]) for k in self.registry.list("kb")] + [self.registry.directory, storage]
        for value in source_dirs:
            if not str(value).strip():
                raise ValueError("请填写数据源目录")
            path = Path(value).resolve()
            if not path.is_dir():
                raise ValueError("数据源目录不存在或不是文件夹：" + str(path))
            if any(path.is_relative_to(p) or p.is_relative_to(path) for p in reserved):
                raise ValueError("数据源目录与向量化存储目录不能重叠，也不能包含其他库的托管数据")
            if any(path.is_relative_to(p) or p.is_relative_to(path) for p in sources):
                raise ValueError("数据源目录不能重复或相互嵌套")
            sources.append(path)
        return [str(path) for path in sources]

    def save_embedding(self, value, identifier=None):
        with self._lock:
            old = self.registry.get("embedding", identifier) if identifier else None
            identifier = identifier or uuid.uuid4().hex
            key = value.pop("api_key", "")
            profile = {**value, "id": identifier, "version": uuid.uuid4().hex, "tested_at": None, "test_ok": None}
            parsed = urlparse(profile["base_url"])
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("请输入有效的 HTTP(S) API 地址，凭据请填写在 API Key 中")
            profile["base_url"] = profile["base_url"].rstrip("/")
            if not key and not self.registry.secret(identifier):
                raise ValueError("请配置 API Key")
            self.registry.put("embedding", profile)
            if key:
                self.registry.secret(identifier, key)
            self.probe_after[identifier] = 0
            self.registry.sync_default_environment(self.project)
        # Drain and restart only libraries affected by this shared configuration.
        affected = [k for k in self.registry.list("kb") if k["embedding_id"] == identifier]
        if old:
            for kb in affected:
                if self.worker_states.get(kb["id"]) == "running":
                    self.restart_worker(kb["id"])
        return {"profile": profile, "affected_knowledge_bases": [k["id"] for k in affected]}

    def test_embedding(self, identifier):
        lock = self.probe_locks.setdefault(identifier, threading.Lock())
        with lock:
            profile = self.registry.get("embedding", identifier)
            values = settings_values(self.base)
            for field in ("base_url", "endpoint", "model", "dimensions", "revision", "batch_size"):
                values["embedding_" + field] = profile[field]
            values.update(embedding_api_key=self.registry.secret(identifier), api_timeout=15)
            provider = Providers(Settings(_env_file=None, **values))
            started = time.monotonic()
            try:
                vector = provider.embed(["knowledge base connection test"])[0]
                profile.update(test_ok=True, test_error=None, measured_dimensions=len(vector),
                               latency_ms=round((time.monotonic() - started) * 1000))
            except (ProviderError, ValueError) as error:
                profile.update(test_ok=False, test_error=str(error))
            finally:
                provider.close()
            profile["tested_at"] = time.time()
            with self._lock:
                current = self.registry.get("embedding", identifier)
                if current.get("version") != profile.get("version"):
                    return current
                self.registry.put("embedding", profile)
            return profile

    def kb_action(self, identifier, action, args=None):
        if action == "start":
            return self.start_worker(identifier)
        if action == "stop":
            return self.stop_worker(identifier)
        if action == "restart":
            return self.restart_worker(identifier)
        return self.request(identifier, "POST", "/admin/actions", json={"action": action, "args": args or {}}, timeout=180)

    def root_action(self, identifier, args):
        if "path" in args:
            path = Path(args["path"]).resolve()
            reserved = [Path(k["data_dir"]) for k in self.registry.list("kb")] + [self.registry.directory]
            if any(path.is_relative_to(p) or p.is_relative_to(path) for p in reserved):
                raise ValueError("来源目录不能包含任何知识库的托管数据，也不能位于其中")
            result = self.kb_action(identifier, "add_root", {"path": str(path)})
        else:
            result = self.kb_action(identifier, "update_root", args)
        state = self.request(identifier, "GET", "/admin/status")
        with self._lock:
            kb = self.registry.get("kb", identifier)
            kb["source_dirs"] = [root["path"] for root in state["roots"]]
            self.registry.put("kb", kb)
        return result

    def snapshot(self, kb):
        lifecycle = self.worker_states.get(kb["id"], "stopped")
        tuning = LibraryTuning.from_settings(self.registry.worker_settings(kb)).model_dump()
        base = {**kb, "tuning": tuning, "vector_dir": str(Path(kb["data_dir"]) / "vectors"),
                "runtime": lifecycle, "index_status": "unknown", "availability": "not_ready",
                "reason": "知识库未运行", "state": None}
        if lifecycle in ("starting", "stopping"):
            base["reason"] = "正在启动" if lifecycle == "starting" else "正在保存检查点并停止"
            return base
        try:
            state = self.request(kb["id"], "GET", "/admin/status", timeout=2)
        except (ProviderError, ValueError):
            if lifecycle == "running":
                base.update(runtime="error", reason="无法连接知识库进程")
            return base
        self.worker_states[kb["id"]] = "running"
        profile = self.registry.get("embedding", kb["embedding_id"])
        desired_profile = self.registry.worker_settings(kb).profile
        jobs = state.get("index_jobs_summary", state.get("jobs_summary", {}))
        failures = jobs.get("unresolved_failures", jobs.get("failed", 0))
        live = state["counts"].get("live_documents", 0)
        complete = (state["configured_profile"] == desired_profile and live > 0 and state.get("indexed_documents", 0) == live
                    and state["active_profile"] == state["configured_profile"] and state.get("has_vector_index"))
        pending = jobs.get("queued", 0) + jobs.get("running", 0)
        indexed = state.get("indexed_documents", 0)
        if state["paused"]:
            index = "paused"
        elif pending or state.get("scan_pending"):
            index = "indexing"
        elif failures:
            index = "failed"
        elif state["active_profile"] and state["active_profile"] != state["configured_profile"]:
            index = "stale"
        elif complete:
            index = "complete"
        elif live:
            index = "pending"
        else:
            index = "empty"
        availability, reason = "not_ready", "尚无可用索引"
        if state.get("has_vector_index") and live:
            availability, reason = "degraded", "存在可检索内容，索引或模型连接尚未就绪"
            if complete and not pending and not failures and not state.get("scan_pending"):
                if profile.get("test_ok") and time.time() - (profile.get("tested_at") or 0) < 600:
                    availability, reason = "ready", "索引完整，Embedding 连接检测通过"
                elif profile.get("test_ok") is None or time.time() - (profile.get("tested_at") or 0) >= 600:
                    availability, reason = "unknown", "索引完整，等待验证 Embedding 连接"
                else:
                    reason = "Embedding 连接失败；可尝试关键词检索"
        scan = state.get("last_scan")
        if availability == "ready" and (not scan or scan.get("errors") or state.get("missing_sources")):
            availability, reason = "degraded", "索引可用，但来源目录待扫描、缺失或扫描不完整"
        base.update(runtime="running", state=state, index_status=index, availability=availability, reason=reason,
                    indexed_documents=indexed, checked_at=time.time())
        return base

    def list_kbs(self):
        return list(self.status_pool.map(self.snapshot, self.registry.list("kb")))

    def validate_mcp(self, value, identifier=None):
        with self._lock:
            for kb_id in value["knowledge_base_ids"]:
                self.registry.get("kb", kb_id)
            if not value["knowledge_base_ids"]:
                raise ValueError("请至少关联一个知识库")
            identifier = identifier or uuid.uuid4().hex
            reserved = {self.port}
            for kb in self.registry.list("kb"):
                reserved.update((kb["admin_port"], kb["tools_port"]))
            reserved.update(m["port"] for m in self.registry.list("mcp") if m["id"] != identifier)
            if value["port"] in reserved:
                raise ValueError("端口已被管理台、知识库或其他 MCP 配置使用")

    def save_mcp(self, value, identifier=None):
        with self._lock:
            self.validate_mcp(value, identifier)
            identifier = identifier or uuid.uuid4().hex
            if identifier in self.listeners:
                raise ValueError("请先停止 MCP，再修改配置或令牌")
            token = value.pop("token", "") or self.registry.secret("mcp:" + identifier) or secrets.token_urlsafe(32)
            result = {**value, "id": identifier}
            result["knowledge_base_ids"] = list(dict.fromkeys(result["knowledge_base_ids"]))
            self.registry.secret("mcp:" + identifier, token)
            return self.registry.put("mcp", result)

    def list_mcps(self, kbs=None):
        kbs = kbs if kbs is not None else self.list_kbs()
        by_id = {k["id"]: k for k in kbs}
        result = []
        for instance in self.registry.list("mcp"):
            runtime = self.listeners.get(instance["id"])
            running = bool(runtime and runtime[0].started and not runtime[1].done())
            states = [by_id[k]["availability"] for k in instance["knowledge_base_ids"] if k in by_id]
            ready = running and len(states) == len(instance["knowledge_base_ids"]) and all(s == "ready" for s in states)
            result.append({**instance, "runtime": "running" if running else "stopped", "ready": ready,
                           "availability": "ready" if ready else "degraded" if running else "not_ready",
                           "error": self.listener_errors.get(instance["id"]), "token_set": True,
                           "url": f"http://127.0.0.1:{instance['port']}/mcp"})
        return result
