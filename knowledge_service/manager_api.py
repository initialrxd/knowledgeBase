"""Same-origin local console API and static frontend."""
from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from .api import _errors
from .manager_gateway import start_mcp, stop_mcp, test_mcp


class Named(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class KnowledgeBaseInput(Named):
    data_dir: str = Field(default="", max_length=2000)
    embedding_id: str
    auto_start: bool = True


class CreateKnowledgeBaseInput(KnowledgeBaseInput):
    data_dir: str = Field(min_length=1, max_length=2000)
    source_dirs: list[str] = Field(min_length=1, max_length=100)

    @field_validator("data_dir")
    @classmethod
    def required_storage(cls, value):
        if not value.strip():
            raise ValueError("请填写向量化存储目录")
        return value.strip()

    @field_validator("source_dirs")
    @classmethod
    def required_sources(cls, value):
        if any(not path.strip() or len(path) > 2000 for path in value):
            raise ValueError("请填写有效的数据源目录")
        return [path.strip() for path in value]


class EmbeddingInput(Named):
    base_url: str = Field(max_length=2000)
    endpoint: str = Field(default="/embeddings", pattern=r"^/[^?#]*$", max_length=300)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=4000)
    dimensions: int = Field(default=0, ge=0, le=65536)
    revision: str = Field(default="default", min_length=1, max_length=100)
    batch_size: int = Field(default=8, ge=1, le=256)


class McpInput(Named):
    port: int = Field(ge=1024, le=65535)
    knowledge_base_ids: list[str] = Field(min_length=1, max_length=100)
    token: str = Field(default="", max_length=4000)
    auto_start: bool = False


class WorkerAction(BaseModel):
    action: Literal["start", "stop", "restart", "scan", "pause", "resume", "retry", "reindex"]
    args: dict = Field(default_factory=dict)


class RootInput(BaseModel):
    path: str | None = Field(default=None, max_length=2000)
    id: str | None = None
    enabled: bool | None = None
    remove: bool = False


class LoginInput(BaseModel):
    token: str = Field(min_length=1, max_length=4000)


class McpAction(BaseModel):
    action: Literal["start", "stop", "restart", "test", "rotate_token"]


async def supervise(manager):
    for kb in manager.registry.list("kb"):
        if kb["auto_start"]:
            try:
                await asyncio.to_thread(manager.start_worker, kb["id"])
            except Exception:
                manager.worker_states[kb["id"]] = "error"
    for instance in manager.registry.list("mcp"):
        if instance["auto_start"]:
            try:
                await start_mcp(manager, instance["id"])
            except ValueError:
                pass
    while not manager.closing:
        active = {k["embedding_id"] for k in manager.registry.list("kb")
                  if manager.worker_states.get(k["id"]) == "running"}
        for identifier in active:
            if time.time() - manager.probe_after.get(identifier, 0) >= 300:
                manager.probe_after[identifier] = time.time()
                manager.submit(manager.test_embedding, identifier)
        await asyncio.sleep(5)


def management_app(manager, auto_start=True):
    manager.login_token = secrets.token_urlsafe(32)
    manager.sessions = {}
    manager.login_attempts = []

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(supervise(manager)) if auto_start else None
        try:
            yield
        finally:
            manager.closing = True
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await asyncio.to_thread(manager.pool.shutdown, wait=True, cancel_futures=True)
            for identifier in list(manager.listeners):
                await stop_mcp(manager, identifier)
            await asyncio.gather(*(asyncio.to_thread(manager.stop_worker, k["id"])
                for k in manager.registry.list("kb") if manager.worker_states.get(k["id"]) in ("running", "starting")),
                return_exceptions=True)
            manager.status_pool.shutdown(wait=True)

    app = FastAPI(title="知识库管理台", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    _errors(app)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        path = request.url.path
        if path.startswith("/manager/api/"):
            if manager.closing:
                return JSONResponse({"detail": "管理台正在停止并保存状态"}, 503)
            origin = request.headers.get("origin")
            if origin and origin not in (f"http://127.0.0.1:{manager.port}", f"http://localhost:{manager.port}"):
                return JSONResponse({"detail": "仅允许同源管理请求"}, 403)
            if path != "/manager/api/login":
                session = request.cookies.get("knowledge_manager", "")
                bearer = request.headers.get("authorization", "")
                admin = manager.base.admin_token.get_secret_value()
                permitted = bool(admin and secrets.compare_digest(bearer, "Bearer " + admin))
                if not permitted and manager.sessions.get(session, 0) < time.time():
                    return JSONResponse({"detail": "请使用启动脚本提供的本机登录链接"}, 401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if path.startswith("/manager/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "knowledge-manager", "pid": os.getpid()}

    @app.post("/manager/api/login")
    def login(body: LoginInput):
        manager.login_attempts = [t for t in manager.login_attempts if time.time() - t < 60]
        if len(manager.login_attempts) >= 20:
            raise HTTPException(429, "登录尝试过多，请稍后再试")
        manager.login_attempts.append(time.time())
        admin = manager.base.admin_token.get_secret_value()
        bootstrap = bool(manager.login_token and secrets.compare_digest(body.token, manager.login_token))
        if not bootstrap and not (admin and secrets.compare_digest(body.token, admin)):
            raise HTTPException(401, "登录令牌无效或已使用")
        if bootstrap:
            manager.login_token = ""
        session = secrets.token_urlsafe(32)
        manager.sessions = {s: expiry for s, expiry in manager.sessions.items() if expiry > time.time()}
        manager.sessions[session] = time.time() + 86400
        response = JSONResponse({"ok": True})
        response.set_cookie("knowledge_manager", session, max_age=86400, httponly=True, samesite="strict")
        return response

    @app.post("/manager/api/logout")
    def logout(request: Request):
        manager.sessions.pop(request.cookies.get("knowledge_manager", ""), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie("knowledge_manager")
        return response

    @app.post("/manager/api/bootstrap")
    def bootstrap():
        manager.login_token = secrets.token_urlsafe(32)
        return {"token": manager.login_token}

    @app.get("/manager/api/state")
    def state():
        kbs = manager.list_kbs()
        embeddings = [{**p, "key_set": bool(manager.registry.secret(p["id"])),
                       "knowledge_base_ids": [k["id"] for k in kbs if k["embedding_id"] == p["id"]]}
                      for p in manager.registry.list("embedding")]
        return {"knowledge_bases": kbs, "embedding_profiles": embeddings, "mcp_instances": manager.list_mcps(kbs),
                "checked_at": time.time(), "demo_mode": manager.base.demo_mode}

    @app.get("/manager/api/operations/{identifier}")
    def operation(identifier: str):
        if identifier not in manager.operations:
            raise KeyError("Operation not found")
        return manager.operations[identifier]

    @app.post("/manager/api/knowledge-bases")
    def create_kb(body: CreateKnowledgeBaseInput):
        return manager.submit(manager.save_kb, body.model_dump())

    @app.put("/manager/api/knowledge-bases/{identifier}")
    def update_kb(identifier: str, body: KnowledgeBaseInput):
        manager.registry.get("kb", identifier)
        return manager.submit(manager.save_kb, body.model_dump(), identifier)

    @app.post("/manager/api/knowledge-bases/{identifier}/actions")
    def kb_action(identifier: str, body: WorkerAction):
        manager.registry.get("kb", identifier)
        return manager.submit(manager.kb_action, identifier, body.action, body.args)

    @app.post("/manager/api/knowledge-bases/{identifier}/roots")
    def roots(identifier: str, body: RootInput):
        manager.registry.get("kb", identifier)
        args = body.model_dump(exclude_none=True)
        if not body.path and not body.id:
            raise ValueError("请选择目录或提供来源 ID")
        return manager.submit(manager.root_action, identifier, args)

    @app.delete("/manager/api/knowledge-bases/{identifier}")
    def detach_kb(identifier: str):
        if identifier == "default":
            raise ValueError("默认知识库不能移除")
        if any(identifier in m["knowledge_base_ids"] for m in manager.registry.list("mcp")):
            raise ValueError("请先解除 MCP 对此知识库的关联")

        def detach():
            manager.stop_worker(identifier)
            manager.registry.delete("kb", identifier)
            return {"removed": True, "data_preserved": True}
        return manager.submit(detach)

    @app.post("/manager/api/embedding-profiles")
    def create_embedding(body: EmbeddingInput):
        return manager.submit(manager.save_embedding, body.model_dump())

    @app.put("/manager/api/embedding-profiles/{identifier}")
    def update_embedding(identifier: str, body: EmbeddingInput):
        manager.registry.get("embedding", identifier)
        return manager.submit(manager.save_embedding, body.model_dump(), identifier)

    @app.post("/manager/api/embedding-profiles/{identifier}/test")
    def probe(identifier: str):
        manager.registry.get("embedding", identifier)
        manager.probe_after[identifier] = time.time()
        return manager.submit(manager.test_embedding, identifier)

    @app.delete("/manager/api/embedding-profiles/{identifier}")
    def delete_embedding(identifier: str):
        if any(k["embedding_id"] == identifier for k in manager.registry.list("kb")):
            raise ValueError("仍有知识库引用此配置")
        manager.registry.delete("embedding", identifier)
        manager.registry.secret(identifier, "")
        return {"removed": True}

    @app.post("/manager/api/mcp-instances")
    def create_mcp(body: McpInput):
        return manager.save_mcp(body.model_dump())

    @app.put("/manager/api/mcp-instances/{identifier}")
    async def update_mcp(identifier: str, body: McpInput):
        from .manager_gateway import update_mcp as apply_mcp
        return await apply_mcp(manager, identifier, body.model_dump())

    @app.post("/manager/api/mcp-instances/{identifier}/actions")
    async def mcp_action(identifier: str, body: McpAction):
        manager.registry.get("mcp", identifier)
        if body.action == "stop":
            return await stop_mcp(manager, identifier)
        if body.action == "restart":
            await stop_mcp(manager, identifier)
        if body.action in ("start", "restart"):
            return await start_mcp(manager, identifier)
        if body.action == "test":
            return await test_mcp(manager, identifier)
        if identifier in manager.listeners:
            raise ValueError("请先停止 MCP，再更换令牌")
        token = secrets.token_urlsafe(32)
        manager.registry.secret("mcp:" + identifier, token)
        return {"rotated": True}

    @app.post("/manager/api/mcp-instances/{identifier}/client-config")
    def client_config(identifier: str):
        instance = manager.registry.get("mcp", identifier)
        return {"mcpServers": {instance["name"]: {"type": "http",
            "url": f"http://127.0.0.1:{instance['port']}/mcp",
            "headers": {"Authorization": "Bearer " + manager.registry.secret("mcp:" + identifier)}}}}

    @app.delete("/manager/api/mcp-instances/{identifier}")
    async def delete_mcp(identifier: str):
        if identifier == "default":
            raise ValueError("默认 MCP 保留用于旧客户端兼容，可停止或编辑")
        await stop_mcp(manager, identifier)
        manager.registry.delete("mcp", identifier)
        manager.registry.secret("mcp:" + identifier, "")
        return {"removed": True}

    @app.post("/manager/api/shutdown")
    def shutdown():
        manager.shutdown_event.set()
        return {"stopping": True}

    static = Path(__file__).parent / "static"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/")
    @app.get("/embedding")
    @app.get("/mcp")
    def index():
        if not (static / "index.html").exists():
            return JSONResponse({"detail": "请先在 frontend 目录执行 npm install 和 npm run build"}, 503)
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app
