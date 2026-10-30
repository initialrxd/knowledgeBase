"""Real subprocess/listener smoke test; explicit demo mode makes this fully offline."""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from knowledge_service.manager_gateway import start_mcp, stop_mcp, test_mcp as probe_mcp
from knowledge_service.manager_runtime import Manager, available_port
from knowledge_service.manager_api import management_app


@pytest.mark.asyncio
async def test_managed_workers_and_real_mcp(tmp_path, settings, make_pdf):
    settings = settings.model_copy(update={"port": available_port(), "tools_port": available_port()})
    manager = Manager(tmp_path / "console", settings, port=available_port())
    default = manager.registry.get("kb", "default")
    first_profile = manager.registry.get("embedding", default["embedding_id"])
    second_profile = manager.save_embedding({"name": "second-model", "base_url": "https://offline.example/v1",
        "endpoint": "/embeddings", "model": "demo-other-model", "dimensions": 0, "revision": "v2",
        "batch_size": 8, "api_key": "offline-test-key"})["profile"]
    pdf = make_pdf("共享来源 文档/radar.pdf")
    second = manager.save_kb({"name": "第二个知识库", "embedding_id": second_profile["id"], "auto_start": False,
        "source_dirs": [str(pdf.parent)], "data_dir": str(tmp_path / "向量化 存储")})
    instance = manager.save_mcp({"name": "多库检索", "port": available_port(),
        "knowledge_base_ids": ["default", second["id"]], "auto_start": False, "token": "multi-library-test-token"})
    one = manager.save_mcp({"name": "单库检索", "port": available_port(),
        "knowledge_base_ids": ["default"], "auto_start": False, "token": "single-library-test-token"})
    try:
        for kb in (default, second):
            await asyncio.to_thread(manager.start_worker, kb["id"])
            if kb["id"] == "default":
                await asyncio.to_thread(manager.root_action, kb["id"], {"path": str(pdf.parent)})
            await asyncio.to_thread(manager.kb_action, kb["id"], "scan")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            states = await asyncio.to_thread(manager.list_kbs)
            if all(s["index_status"] == "complete" for s in states):
                break
            await asyncio.sleep(0.3)
        assert all(s["index_status"] == "complete" for s in states), states
        await asyncio.to_thread(manager.test_embedding, first_profile["id"])
        await asyncio.to_thread(manager.test_embedding, second_profile["id"])
        assert all(s["availability"] == "ready" for s in await asyncio.to_thread(manager.list_kbs))
        await start_mcp(manager, instance["id"])
        await start_mcp(manager, one["id"])
        assert (await probe_mcp(manager, instance["id"]))["ok"]
        api = httpx.AsyncClient(transport=httpx.ASGITransport(app=management_app(manager, auto_start=False)),
                               base_url="http://testserver", headers={"Authorization": "Bearer test-admin-token"})
        async with api:
            changed = {"name": "改名后的单库 MCP", "port": available_port(), "knowledge_base_ids": ["default"],
                       "auto_start": True, "token": "edited-listener-token"}
            response = await api.put(f"/manager/api/mcp-instances/{one['id']}", json=changed)
            assert response.status_code == 200, response.text
            one = response.json()
            assert one["name"] == changed["name"]
            assert (await probe_mcp(manager, one["id"]))["ok"]
            import socket
            with socket.socket() as occupied:
                occupied.bind(("127.0.0.1", 0))
                occupied.listen()
                failed = {**changed, "name": "must-rollback", "port": occupied.getsockname()[1], "token": "bad-new-token"}
                response = await api.put(f"/manager/api/mcp-instances/{one['id']}", json=failed)
                assert response.status_code == 400
            assert manager.registry.get("mcp", one["id"])["name"] == changed["name"]
            assert manager.registry.secret("mcp:" + one["id"]) == "edited-listener-token"
            assert (await probe_mcp(manager, one["id"]))["ok"]
        async with httpx.AsyncClient(trust_env=False) as client:
            base = f"http://127.0.0.1:{instance['port']}"
            auth = {"Authorization": "Bearer multi-library-test-token"}
            assert (await client.post(base + "/v1/search", json={"query": "radar"})).status_code == 401
            response = await client.post(base + "/v1/search", headers=auth, json={"query": "radar"})
            assert response.status_code == 200, response.text
            results = response.json()["results"]
            assert {r["knowledge_base_id"] for r in results} == {"default", second["id"]}
            row = results[0]
            response = await client.get(base + "/v1/chunks/" + row["id"], headers=auth)
            assert response.status_code == 400
            response = await client.get(base + "/v1/chunks/" + row["id"], headers=auth,
                                        params={"knowledge_base_id": row["knowledge_base_id"]})
            assert response.status_code == 200
            single_base = f"http://127.0.0.1:{one['port']}"
            response = await client.post(single_base + "/v1/search", headers={"Authorization": "Bearer edited-listener-token"},
                                        json={"query": "radar", "knowledge_base_id": second["id"]})
            assert response.status_code == 403
            await asyncio.to_thread(manager.stop_worker, second["id"])
            response = await client.post(base + "/v1/search", headers=auth, json={"query": "radar"})
            assert response.status_code == 200 and response.json()["warnings"]
            assert {r["knowledge_base_id"] for r in response.json()["results"]} == {"default"}
            await stop_mcp(manager, one["id"])
            manager.registry.secret("mcp:" + one["id"], "rotated-test-token")
            await start_mcp(manager, one["id"])
            assert (await client.get(single_base + "/v1/categories", headers={"Authorization": "Bearer edited-listener-token"})).status_code == 401
            assert (await client.get(single_base + "/v1/categories", headers={"Authorization": "Bearer rotated-test-token"})).status_code == 200
        await asyncio.to_thread(manager.stop_worker, "default")
        await asyncio.to_thread(manager.start_worker, "default")
        restored = await asyncio.to_thread(manager.request, "default", "GET", "/admin/status")
        assert restored["counts"]["live_documents"] == 1
    finally:
        for identifier in list(manager.listeners):
            await stop_mcp(manager, identifier)
        for identifier in list(manager.processes):
            await asyncio.to_thread(manager.stop_worker, identifier)
        manager.pool.shutdown(wait=True)
        manager.status_pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_orphaned_worker_restarts_after_global_model_change(tmp_path, settings):
    settings = settings.model_copy(update={"port": available_port(), "tools_port": available_port(),
                                           "chat_model": "chat-old", "classify_model": "classifier-old"})
    first = Manager(tmp_path / "console", settings, port=available_port())
    second = None
    try:
        started = await asyncio.to_thread(first.start_worker, "default")
        # Simulate a manager restart while its original worker is still alive.
        updated = settings.model_copy(update={"chat_model": "chat-new", "classify_model": "classifier-new"})
        second = Manager(tmp_path / "console", updated, port=first.port)
        restarted = await asyncio.to_thread(second.start_worker, "default")
        assert not restarted.get("reattached")
        assert restarted["pid"] != started["pid"]
        state = await asyncio.to_thread(second.request, "default", "GET", "/admin/status")
        assert state["chat_model"] == "chat-new"
        assert state["classification_model"] == "classifier-new"
        # Once the new settings are applied, starting again safely reattaches.
        assert (await asyncio.to_thread(second.start_worker, "default"))["reattached"]
    finally:
        for manager in (second, first):
            if manager:
                for identifier in list(manager.processes):
                    await asyncio.to_thread(manager.stop_worker, identifier)
                manager.pool.shutdown(wait=True)
                manager.status_pool.shutdown(wait=True)
