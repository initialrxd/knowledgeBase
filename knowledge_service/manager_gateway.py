"""Token-scoped MCP/REST federation; vectors are generated within each library."""
from __future__ import annotations

import asyncio
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .api import AskRequest, GateMiddleware, SearchRequest, _errors
from .providers import ProviderError


class Gateway:
    def __init__(self, manager, instance):
        self.manager, self.instance = manager, instance

    def selected(self, knowledge_base_id=None, single=False):
        allowed = self.instance["knowledge_base_ids"]
        if knowledge_base_id:
            if knowledge_base_id not in allowed:
                raise HTTPException(403, "此 MCP 无权访问该知识库")
            return [knowledge_base_id]
        if single and len(allowed) != 1:
            raise ValueError("多库 MCP 读取文档/片段时必须提供 knowledge_base_id")
        return allowed

    def search(self, query, limit=None, category=None, document_id=None, mode=None, knowledge_base_id=None):
        body = SearchRequest(query=query, limit=limit, category=category, document_id=document_id, mode=mode)
        selected = self.selected(knowledge_base_id, single=bool(document_id))
        # Each worker applies its own defaults; the merged cap uses the largest library limit.
        merged_limit = limit if limit is not None else max(
            self.manager.registry.worker_settings(self.manager.registry.get("kb", identifier)).search_limit
            for identifier in selected)

        def fetch(identifier):
            try:
                return identifier, self.manager.request(identifier, "POST", "/v1/search", tools=True,
                    json=body.model_dump(), timeout=150), None
            except (ProviderError, ValueError) as error:
                return identifier, None, str(error)
        with ThreadPoolExecutor(max_workers=min(8, len(selected))) as pool:
            responses = list(pool.map(fetch, selected))
        warnings, results, successful = [], [], 0
        for identifier, response, error in responses:
            name = self.manager.registry.get("kb", identifier)["name"]
            if error:
                warnings.append(f"{name}: {error}")
                continue
            successful += 1
            warnings.extend(f"{name}: {w}" for w in response.get("warnings", []))
            for rank, row in enumerate(response["results"], 1):
                results.append({**row, "knowledge_base_id": identifier, "knowledge_base_name": name,
                                "score": 1 / (60 + rank), "citation": f"[{name}] " + row.get("citation", "")})
        if not successful:
            raise ProviderError("所有关联知识库均不可用")
        results.sort(key=lambda r: (-r["score"], r["knowledge_base_id"], r["id"]))
        return {"query": query, "results": results[:merged_limit], "warnings": warnings,
                "demo_mode": self.manager.base.demo_mode}

    def read(self, path, knowledge_base_id=None, **params):
        identifier = self.selected(knowledge_base_id, single=True)[0]
        value = self.manager.request(identifier, "GET", path, tools=True, params=params, timeout=30)
        return {**value, "knowledge_base_id": identifier,
                "knowledge_base_name": self.manager.registry.get("kb", identifier)["name"]}

    def categories(self, knowledge_base_id=None):
        results = []
        for identifier in self.selected(knowledge_base_id):
            rows = self.manager.request(identifier, "GET", "/v1/categories", tools=True)
            results.extend({**r, "knowledge_base_id": identifier,
                            "knowledge_base_name": self.manager.registry.get("kb", identifier)["name"]} for r in rows)
        return results


class GatewaySearch(SearchRequest):
    knowledge_base_id: str | None = None


def gateway_app(manager, instance):
    gateway = Gateway(manager, instance)
    mcp = FastMCP(instance["name"], stateless_http=True, json_response=True, streamable_http_path="/mcp",
        instructions="Search documents first. Cite knowledge_base_name, title and PDF pages. "
        "Pass the returned knowledge_base_id when reading a document or chunk.",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "testserver"]))

    @mcp.tool()
    def search_knowledge(query: str, limit: int | None = None, category: str | None = None,
                         document_id: str | None = None, mode: str | None = None,
                         knowledge_base_id: str | None = None) -> dict:
        """Search the allowed knowledge bases; results include source library IDs and citations."""
        return gateway.search(query, limit, category, document_id, mode, knowledge_base_id)

    @mcp.tool()
    def get_chunk(chunk_id: str, knowledge_base_id: str | None = None) -> dict:
        """Read evidence. Supply knowledge_base_id from the search result for a multi-library MCP."""
        return gateway.read(f"/v1/chunks/{chunk_id}", knowledge_base_id)

    @mcp.tool()
    def get_document(document_id: str, page_start: int = 1, page_end: int | None = None,
                     knowledge_base_id: str | None = None) -> dict:
        """Read PDF pages from the specified source library."""
        params = {"page_start": page_start}
        if page_end is not None:
            params["page_end"] = page_end
        return gateway.read(f"/v1/documents/{document_id}", knowledge_base_id, **params)

    @mcp.tool()
    def list_categories(knowledge_base_id: str | None = None) -> list[dict]:
        """List categories with their source knowledge base."""
        return gateway.categories(knowledge_base_id)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title=instance["name"], lifespan=lifespan)
    _errors(app)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": "knowledge-tools", "instance_id": instance["id"]}

    @app.post("/v1/search", operation_id="search_knowledge")
    def search(body: GatewaySearch):
        return gateway.search(**body.model_dump())

    @app.get("/v1/chunks/{chunk_id}", operation_id="get_chunk")
    def chunk(chunk_id: str, knowledge_base_id: str | None = None):
        return get_chunk(chunk_id, knowledge_base_id)

    @app.get("/v1/documents/{document_id}", operation_id="get_document")
    def document(document_id: str, page_start: int = Query(1, ge=1), page_end: int | None = Query(None, ge=1),
                 knowledge_base_id: str | None = None):
        return get_document(document_id, page_start, page_end, knowledge_base_id)

    @app.get("/v1/categories", operation_id="list_categories")
    def categories(knowledge_base_id: str | None = None):
        return gateway.categories(knowledge_base_id)

    @app.post("/v1/ask", include_in_schema=False)
    def ask(body: AskRequest):
        identifier = gateway.selected(single=True)[0]
        return manager.request(identifier, "POST", "/v1/ask", tools=True, json=body.model_dump(), timeout=180)

    # Keep the Open WebUI tool schema limited to evidence tools, as in the legacy service.
    schema = app.openapi()
    schema["components"].setdefault("securitySchemes", {})["HTTPBearer"] = {"type": "http", "scheme": "bearer"}
    for path in schema["paths"].values():
        for operation in path.values():
            operation["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = schema
    app.mount("/", mcp.streamable_http_app())
    app.add_middleware(GateMiddleware, token=manager.registry.secret("mcp:" + instance["id"]),
                       limit=manager.base.requests_per_minute)
    return app


async def start_mcp(manager, identifier):
    if identifier in manager.listeners:
        server, task = manager.listeners[identifier]
        if not task.done():
            return {"running": server.started}
        manager.listeners.pop(identifier)
    instance = manager.registry.get("mcp", identifier)
    sock = socket.socket()
    try:
        # POSIX listeners must reuse TIME_WAIT addresses after a graceful restart.
        # Windows SO_REUSEADDR can instead steal a live listener's port.
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", instance["port"]))
        sock.listen(128)
        server = uvicorn.Server(uvicorn.Config(gateway_app(manager, instance), host="127.0.0.1",
                                             port=instance["port"], access_log=False, log_level="warning"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        manager.listeners[identifier] = (server, task)
        for _ in range(100):
            if server.started:
                manager.listener_errors.pop(identifier, None)
                return {"running": True}
            if task.done():
                raise ValueError("MCP 启动失败")
            await asyncio.sleep(0.05)
        server.should_exit = True
        await task
        raise ValueError("MCP 启动超时")
    except (OSError, ValueError) as error:
        sock.close()
        manager.listeners.pop(identifier, None)
        manager.listener_errors[identifier] = "MCP 端口占用或启动失败"
        raise ValueError("MCP 端口占用或启动失败") from error


async def stop_mcp(manager, identifier):
    runtime = manager.listeners.get(identifier)
    if runtime:
        runtime[0].should_exit = True
        await runtime[1]
        manager.listeners.pop(identifier, None)
    return {"stopped": True}


async def update_mcp(manager, identifier, value):
    """Apply an editable listener configuration, restoring the old listener on failure."""
    old = manager.registry.get("mcp", identifier)
    manager.validate_mcp(value, identifier)
    old_token = manager.registry.secret("mcp:" + identifier)
    runtime = manager.listeners.get(identifier)
    was_running = bool(runtime and not runtime[1].done())
    if was_running:
        await stop_mcp(manager, identifier)
    try:
        result = manager.save_mcp(dict(value), identifier)
        if was_running:
            await start_mcp(manager, identifier)
        return result
    except Exception:
        await stop_mcp(manager, identifier)
        manager.registry.put("mcp", old)
        manager.registry.secret("mcp:" + identifier, old_token)
        if was_running:
            try:
                await start_mcp(manager, identifier)
            except ValueError:
                raise ValueError("新配置应用失败，已恢复原配置；原端口当前不可用，请检查后重新启动") from None
        raise ValueError("新配置应用失败，已恢复原配置" + ("及运行状态" if was_running else "")) from None


async def test_mcp(manager, identifier):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    instance = manager.registry.get("mcp", identifier)
    token = manager.registry.secret("mcp:" + identifier)
    try:
        async with asyncio.timeout(15):
            async with streamablehttp_client(f"http://127.0.0.1:{instance['port']}/mcp",
                    headers={"Authorization": "Bearer " + token}) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
        return {"ok": True, "tools": [t.name for t in result.tools]}
    except Exception:
        raise ValueError("MCP 初始化或工具列表检查失败，请检查启动状态和令牌") from None
