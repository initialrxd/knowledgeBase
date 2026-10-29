from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .providers import ProviderError


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000, description="Natural-language question or search terms")
    limit: int = Field(default=10, ge=1, le=50)
    category: str | None = Field(default=None, max_length=1000, description="Optional category path; includes descendants")
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    category: str | None = Field(default=None, max_length=1000)


class Action(BaseModel):
    action: Literal["ingest", "add_root", "update_root", "scan", "retry", "pause", "resume", "classify", "delete",
        "export", "import", "reindex", "benchmark"]
    args: dict = Field(default_factory=dict)


class GateMiddleware:
    """ASGI auth works with streaming MCP responses, unlike buffering HTTP middleware."""
    def __init__(self, app, token: str, limit=60):
        self.app, self.token, self.limit = app, token, limit
        self.calls = deque()
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in ("/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        provided = headers.get(b"authorization", b"")
        expected = ("Bearer " + self.token).encode("utf-8")
        if not self.token or not secrets.compare_digest(provided, expected):
            response = JSONResponse({"detail": "Authentication required"}, status_code=401,
                headers={"WWW-Authenticate": "Bearer"})
            return await response(scope, receive, send)
        with self.lock:
            now = time.monotonic()
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            limited = len(self.calls) >= self.limit
            if not limited:
                self.calls.append(now)
        if limited:
            return await JSONResponse({"detail": "Rate limit exceeded"}, status_code=429,
                headers={"Retry-After": "60"})(scope, receive, send)
        return await self.app(scope, receive, send)


def _errors(app):
    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": "Requested document, chunk, or job was not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(ProviderError)
    async def provider(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)


def tools_app(service):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    allowed_hosts = ["127.0.0.1:*", "localhost:*", "testserver"]
    if service.s.public_base_url:
        from urllib.parse import urlparse
        allowed_hosts.append(urlparse(service.s.public_base_url).netloc)
    mcp = FastMCP("Portable Knowledge", instructions="Search documents before answering. Cite title and PDF page numbers.",
        stateless_http=True, json_response=True, streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts))

    @mcp.tool()
    def search_knowledge(query: str, limit: int = 10, category: str | None = None,
                         document_id: str | None = None, mode: str = "hybrid") -> dict:
        """Search the PDF corpus. Returns evidence with document IDs, chunk IDs and PDF page numbers."""
        body = SearchRequest(query=query, limit=limit, category=category, document_id=document_id, mode=mode)
        return service.search(**body.model_dump())

    @mcp.tool()
    def get_chunk(chunk_id: str) -> dict:
        """Read a current evidence chunk with its document title, section and PDF page numbers."""
        return service.get_chunk(chunk_id)

    @mcp.tool()
    def get_document(document_id: str, page_start: int = 1, page_end: int | None = None) -> dict:
        """Read document metadata and up to ten PDF pages. Page numbering starts at 1."""
        return service.get_document(document_id, page_start, page_end)

    @mcp.tool()
    def list_categories() -> list[dict]:
        """List category paths and document counts for narrowing a search."""
        return service.categories()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Portable Knowledge Tools", version="0.1.0", lifespan=lifespan,
        description="Read-only evidence tools for Open WebUI. All page numbers are PDF physical pages (1-based).")
    app.state.mcp = mcp
    auth = HTTPBearer(auto_error=False)

    def security_schema(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
        # Authentication is enforced by GateMiddleware, including MCP requests.
        return None

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "service": "knowledge-tools", "demo_mode": service.s.demo_mode}

    @app.post("/v1/search", operation_id="search_knowledge", dependencies=[Depends(security_schema)])
    def search(body: SearchRequest):
        return service.search(**body.model_dump())

    @app.get("/v1/chunks/{chunk_id}", operation_id="get_chunk", dependencies=[Depends(security_schema)])
    def chunk(chunk_id: str):
        return service.get_chunk(chunk_id)

    @app.get("/v1/documents/{document_id}", operation_id="get_document", dependencies=[Depends(security_schema)])
    def document(document_id: str, page_start: int = Query(1, ge=1), page_end: int | None = Query(None, ge=1)):
        return service.get_document(document_id, page_start, page_end)

    @app.get("/v1/categories", operation_id="list_categories", dependencies=[Depends(security_schema)])
    def categories():
        return service.categories()

    # /ask is available to applications, but not advertised as a model tool: Open WebUI answers itself.
    @app.post("/v1/ask", include_in_schema=False)
    def ask(body: AskRequest):
        return service.ask(body.question, body.category)

    _errors(app)
    app.mount("/", mcp.streamable_http_app())
    app.add_middleware(GateMiddleware, token=service.s.api_token.get_secret_value(),
        limit=service.s.requests_per_minute)
    return app


def admin_app(service):
    app = FastAPI(title="Knowledge Local Administration", version="0.1.0")

    @app.get("/health", include_in_schema=False)
    def health():
        import os
        return {"status": "ok", "service": "knowledge-admin", "pid": os.getpid()}

    @app.post("/admin/shutdown", include_in_schema=False)
    def shutdown():
        service.stop_event.set()
        service.wake.set()
        return {"stopping": True, "note": "Current extraction/embedding batch is checkpointed before exit"}

    @app.get("/admin/status")
    def status():
        return service.status()

    @app.get("/admin/jobs/{job_id}")
    def job(job_id: str):
        row = service.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise KeyError("Job not found")
        return row

    @app.get("/admin/documents")
    def documents(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
        return service.db.rows("SELECT d.*,c.path category FROM documents d JOIN categories c ON c.id=d.category_id "
            "ORDER BY d.updated DESC LIMIT ? OFFSET ?", (limit, offset))

    @app.get("/admin/documents/{document_id}/pdf")
    def original(document_id: str):
        doc = service.db.one("SELECT d.filename,v.file_hash FROM documents d JOIN versions v "
            "ON v.id=d.current_version WHERE d.id=?", (document_id,))
        if not doc:
            raise KeyError("Document not found")
        return FileResponse(service.s.root / "originals" / (doc["file_hash"] + ".pdf"),
            media_type="application/pdf", filename=doc["filename"])

    @app.post("/admin/actions")
    def action(body: Action):
        args = body.args
        try:
            if body.action == "ingest":
                from pathlib import Path
                path = Path(args["path"]).resolve()
                if not path.is_file() or path.suffix.lower() != ".pdf":
                    raise ValueError("Provide an existing PDF path")
                stat = path.stat()
                return service.enqueue("ingest", {"path": str(path), "signature": [stat.st_size, stat.st_mtime_ns]})
            if body.action == "add_root":
                return service.add_root(args["path"])
            if body.action == "update_root":
                with service.write_lock:
                    return service.update_root(args["id"], args.get("enabled"), args.get("remove", False))
            if body.action == "scan":
                return service.scan(args.get("verify", False))
            if body.action == "retry":
                return service.retry(args.get("job_id"))
            if body.action in ("pause", "resume"):
                if body.action == "resume":
                    service.scan()
                service.db.set_meta("paused", body.action == "pause")
                return {"paused": body.action == "pause"}
            if body.action == "classify":
                service.set_category(args["document_id"], args["category"], args.get("locked", True))
                return {"updated": args["document_id"]}
            if body.action == "delete":
                return service.delete_document(args["document_id"])
            return service.enqueue(body.action, args)
        except KeyError:
            raise HTTPException(400, "Missing required action argument") from None

    _errors(app)
    app.add_middleware(GateMiddleware, token=service.s.admin_token.get_secret_value(), limit=600)
    return app


async def serve(service):
    import uvicorn
    if not service.s.api_token.get_secret_value() or not service.s.admin_token.get_secret_value():
        raise ValueError("Both KB_API_TOKEN and KB_ADMIN_TOKEN are required. Run knowledge init")
    service.start()
    admin = uvicorn.Server(uvicorn.Config(admin_app(service), host="127.0.0.1", port=service.s.port, access_log=False))
    tools = uvicorn.Server(uvicorn.Config(tools_app(service), host=service.s.host,
        port=service.s.tools_port, access_log=False))
    # Propagate stop to both listeners when either exits (including bind failures).
    tasks = [asyncio.create_task(admin.serve()), asyncio.create_task(tools.serve())]
    async def wait_for_stop():
        while not service.stop_event.is_set():
            await asyncio.sleep(0.2)
    stop_task = asyncio.create_task(wait_for_stop())
    try:
        await asyncio.wait([*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_task.cancel()
        admin.should_exit = tools.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


def run_stdio(settings):
    """MCP stdio proxy: the one service process retains exclusive ownership of all storage."""
    import httpx
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("Portable Knowledge")
    url = f"http://127.0.0.1:{settings.tools_port}"
    client = httpx.Client(base_url=url, headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()}, timeout=120)

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    @mcp.tool()
    def search_knowledge(query: str, limit: int = 10, category: str | None = None) -> dict:
        """Search PDFs and retrieve cited evidence."""
        return request("POST", "/v1/search", json={"query": query, "limit": limit, "category": category})

    @mcp.tool()
    def get_chunk(chunk_id: str) -> dict:
        """Read a current evidence chunk."""
        return request("GET", "/v1/chunks/" + chunk_id)

    @mcp.tool()
    def get_document(document_id: str, page_start: int = 1, page_end: int | None = None) -> dict:
        """Read up to ten document pages, using physical PDF page numbers starting at 1."""
        params = {"page_start": page_start}
        if page_end is not None:
            params["page_end"] = page_end
        return request("GET", "/v1/documents/" + document_id, params=params)

    @mcp.tool()
    def list_categories() -> list[dict]:
        """List available categories."""
        return request("GET", "/v1/categories")

    try:
        mcp.run(transport="stdio")
    finally:
        client.close()
