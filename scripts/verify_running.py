"""Verify a running service's HTTP and MCP contracts without displaying secrets."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from knowledge_service.config import Settings  # noqa: E402


async def main():
    s = Settings()
    base = f"http://127.0.0.1:{s.tools_port}"
    headers = {"Authorization": "Bearer " + s.api_token.get_secret_value()}
    async with httpx.AsyncClient(base_url=base, timeout=180) as client:
        assert (await client.get("/v1/categories")).status_code == 401
        schema = (await client.get("/openapi.json")).json()
        operations = [v["operationId"] for path in schema["paths"].values() for v in path.values()]
        assert set(operations) == {"search_knowledge", "get_chunk", "get_document", "list_categories"}
        search = await client.post("/v1/search", json={"query": "TI mmWave radar self calibration"}, headers=headers)
        search.raise_for_status()
        found = search.json()
        assert found["results"] and not found["warnings"]
        first = found["results"][0]
        document = await client.get("/v1/documents/" + first["document_id"],
            params={"page_start": first["page_start"]}, headers=headers)
        document.raise_for_status()
        assert document.json()["pages"]
        answer = await client.post("/v1/ask", json={"question": "TI mmWave 雷达为什么需要校准？请根据资料引用来源。"}, headers=headers)
        answer.raise_for_status()
        answered = answer.json()
        assert answered["citations"] and "citation_validation_failed" not in answered["warnings"]
    async with streamablehttp_client(base + "/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert {tool.name for tool in listed.tools} == set(operations)
            categories = await session.call_tool("list_categories", {})
            assert not categories.isError
    report = {"passed": True, "http_tools": operations, "mcp_verified": True,
        "real_search_results": len(found["results"]), "real_answer_citations": len(answered["citations"]),
        "chat_model": s.chat_model, "embedding_model": s.embedding_model}
    target = s.root / "validation.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
