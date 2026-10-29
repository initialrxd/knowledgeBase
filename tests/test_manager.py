from __future__ import annotations

import json
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from knowledge_service.manager_api import management_app
from knowledge_service.manager_gateway import Gateway, gateway_app
from knowledge_service.manager_runtime import Manager
from knowledge_service.manager_store import Registry
from knowledge_service.providers import ProviderError


@pytest.fixture
def manager(tmp_path, settings):
    instance = Manager(tmp_path, settings)
    yield instance
    instance.pool.shutdown(wait=True)
    instance.status_pool.shutdown(wait=True)


def headers():
    return {"Authorization": "Bearer test-admin-token"}


def test_session_origin_and_secret_redaction(manager):
    profile = manager.registry.list("embedding")[0]
    manager.registry.secret(profile["id"], "sensitive-model-key")
    app = management_app(manager, auto_start=False)
    client = TestClient(app)
    assert client.get("/manager/api/state").status_code == 401
    token = manager.login_token
    assert client.post("/manager/api/login", json={"token": token}).status_code == 200
    assert client.post("/manager/api/login", json={"token": token}).status_code == 401
    response = client.get("/manager/api/state")
    assert response.status_code == 200
    for secret in ("sensitive-model-key", "test-admin-token", "test-read-token"):
        assert secret not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/manager/api/bootstrap", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/manager/api/logout").status_code == 200
    assert client.get("/manager/api/state").status_code == 401
    assert client.get("/manager/api/state", headers=headers()).status_code == 200


def test_registry_and_storage_isolation(manager, tmp_path):
    profile = manager.registry.list("embedding")[0]
    first = manager.save_kb({"name": "技术 文档", "embedding_id": profile["id"], "auto_start": False})
    second = manager.save_kb({"name": "产品资料", "embedding_id": profile["id"], "auto_start": False})
    assert first["data_dir"] != second["data_dir"]
    assert manager.registry.worker_settings(first).api_token != manager.registry.worker_settings(second).api_token
    assert Registry(manager.registry.directory).get("kb", first["id"])["name"] == "技术 文档"
    with pytest.raises(ValueError, match="重叠"):
        manager.save_kb({"name": "nested", "data_dir": first["data_dir"] + "/inside",
                         "embedding_id": profile["id"], "auto_start": False})
    with pytest.raises(ValueError, match="整个项目"):
        manager.save_kb({"name": "project", "data_dir": str(tmp_path), "embedding_id": profile["id"], "auto_start": False})
    with pytest.raises(ValueError, match="不能直接更改"):
        manager.save_kb({"name": "move", "data_dir": str(tmp_path / "elsewhere"),
                         "embedding_id": profile["id"], "auto_start": False}, first["id"])


def test_embedding_key_update_and_profile_identity(manager):
    value = {"name": "cloud", "base_url": "https://example.test/v1", "endpoint": "/embeddings", "model": "model-a",
             "dimensions": 0, "revision": "default", "batch_size": 8, "api_key": "first-key"}
    profile = manager.save_embedding(value.copy())["profile"]
    kb = manager.save_kb({"name": "one", "embedding_id": profile["id"], "auto_start": False})
    first = manager.registry.worker_settings(kb).profile
    value["api_key"] = "second-key"
    manager.save_embedding(value.copy(), profile["id"])
    assert manager.registry.worker_settings(kb).profile == first
    assert manager.registry.secret(profile["id"]) == "second-key"
    value.update(model="model-b", api_key="")
    manager.save_embedding(value.copy(), profile["id"])
    assert manager.registry.worker_settings(kb).profile != first
    assert manager.registry.secret(profile["id"]) == "second-key"
    assert "first-key" not in manager.registry.path.read_bytes().decode("latin1")


def test_readiness_and_full_queue_accounting(manager, service, make_pdf, monkeypatch):
    kb = manager.registry.get("kb", "default")
    monkeypatch.setattr(manager, "request", lambda *a, **kw: service.status())
    assert manager.snapshot(kb)["index_status"] == "empty"
    service.ingest(make_pdf())
    service.scan()
    profile = manager.registry.get("embedding", kb["embedding_id"])
    profile.update(test_ok=True, tested_at=time.time())
    manager.registry.put("embedding", profile)
    assert manager.snapshot(kb)["availability"] == "ready"
    service.enqueue("export", {"destination": "not-executed"})
    assert manager.snapshot(kb)["availability"] == "ready"
    failed = service.enqueue("ingest", {"path": "missing.pdf"})
    service.db.execute("UPDATE jobs SET status='failed' WHERE id=?", (failed["id"],))
    for i in range(60):
        job = service.enqueue("benchmark", {"path": str(i)})
        service.db.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))
    assert not any(j["status"] == "failed" for j in service.status()["jobs"])
    assert manager.snapshot(kb)["index_status"] == "failed"
    assert manager.snapshot(kb)["availability"] != "ready"
    service.db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (failed["id"],))
    profile.update(test_ok=False, tested_at=time.time())
    manager.registry.put("embedding", profile)
    assert manager.snapshot(kb)["availability"] == "degraded"


def test_roots_detach_preserves_documents(service, make_pdf):
    pdf = make_pdf("中文 来源/sample.pdf")
    root = service.add_root(pdf.parent)
    service.ingest(pdf, root["id"])
    pending = service.enqueue("ingest", {"path": str(pdf), "root_id": root["id"]})
    service.db.set_meta("paused", True)
    service.start()
    service.update_root(root["id"], enabled=False)
    assert service.db.one("SELECT enabled FROM roots WHERE id=?", (root["id"],))["enabled"] == 0
    assert service.db.one("SELECT status FROM jobs WHERE id=?", (pending["id"],))["status"] == "cancelled"
    assert service.db.one("SELECT COUNT(*) n FROM documents")["n"] == 1
    service.update_root(root["id"], remove=True)
    assert service.db.rows("SELECT * FROM roots") == []
    assert service.search("radar")["results"]


def test_federation_scopes_rank_and_partial_failure(manager, monkeypatch):
    default = manager.registry.get("kb", "default")
    second = manager.save_kb({"name": "second", "embedding_id": default["embedding_id"], "auto_start": False})
    instance = manager.save_mcp({"name": "federated", "port": 18780,
        "knowledge_base_ids": ["default", second["id"]], "auto_start": False, "token": "gateway-token"})

    def request(identifier, method, path, **kwargs):
        return {"results": [{"id": "same-id", "document_id": "same-document", "score": 1 if identifier == "default" else 999,
                             "citation": "page 1", "text": identifier}], "warnings": []}
    monkeypatch.setattr(manager, "request", request)
    gateway = Gateway(manager, instance)
    results = gateway.search("radar")["results"]
    assert len(results) == 2
    assert results[0]["score"] == results[1]["score"]
    assert len({r["knowledge_base_id"] for r in results}) == 2
    with pytest.raises(ValueError, match="knowledge_base_id"):
        gateway.read("/v1/documents/same-document")
    with pytest.raises(HTTPException) as exception:
        gateway.search("radar", knowledge_base_id="unauthorized")
    assert exception.value.status_code == 403

    def partial(identifier, *args, **kwargs):
        if identifier == second["id"]:
            raise ProviderError("offline")
        return request(identifier, *args, **kwargs)
    monkeypatch.setattr(manager, "request", partial)
    result = gateway.search("radar")
    assert len(result["results"]) == 1 and "second: offline" in result["warnings"]
    monkeypatch.setattr(manager, "request", lambda *a, **k: (_ for _ in ()).throw(ProviderError("offline")))
    with pytest.raises(ProviderError, match="所有"):
        gateway.search("radar")


def test_gateway_auth_port_conflicts_and_rotation(manager):
    value = {"name": "one", "port": 18790, "knowledge_base_ids": ["default"], "auto_start": False, "token": "one-token"}
    instance = manager.save_mcp(value.copy())
    with pytest.raises(ValueError, match="端口"):
        manager.save_mcp(value.copy())
    client = TestClient(gateway_app(manager, instance))
    assert client.get("/v1/categories").status_code == 401
    schema = client.get("/openapi.json").json()
    assert len(schema["paths"]) == 4
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    app = TestClient(management_app(manager, auto_start=False))
    route = f"/manager/api/mcp-instances/{instance['id']}"
    response = app.post(route + "/actions", json={"action": "rotate_token"}, headers=headers())
    assert response.status_code == 200
    assert manager.registry.secret("mcp:" + instance["id"]) != "one-token"
    config = app.post(route + "/client-config", headers=headers()).json()
    assert config["mcpServers"]["one"]["headers"]["Authorization"].startswith("Bearer ")
    state = app.get("/manager/api/state", headers=headers()).text
    assert "one-token" not in state
    assert "Authorization" not in state


def test_invalid_inputs_and_safe_unlink(manager):
    client = TestClient(management_app(manager, auto_start=False))
    assert client.post("/manager/api/mcp-instances", headers=headers(), json={"name": "x", "port": 80,
        "knowledge_base_ids": ["default"]}).status_code == 422
    assert client.delete("/manager/api/knowledge-bases/default", headers=headers()).status_code == 400
    assert client.delete("/manager/api/mcp-instances/default", headers=headers()).status_code == 400
    profile = manager.registry.list("embedding")[0]
    assert client.delete("/manager/api/embedding-profiles/" + profile["id"], headers=headers()).status_code == 400
    assert "test-admin-token" not in json.dumps(manager.registry.list("kb"))


def test_reenabled_directory_resumes_queued_imports(service, make_pdf):
    pdf = make_pdf("new directory/unindexed.pdf")
    root = service.add_root(pdf.parent)
    service.scan()
    job = service.db.one("SELECT id FROM jobs WHERE kind='ingest'")
    service.update_root(root["id"], enabled=False)
    assert service.db.one("SELECT status FROM jobs WHERE id=?", (job["id"],))["status"] == "cancelled"
    service.update_root(root["id"], enabled=True)
    service.scan()
    assert service.db.one("SELECT status FROM jobs WHERE id=?", (job["id"],))["status"] == "queued"


def test_default_configuration_sync_preserves_other_environment_fields(manager):
    env_file = manager.project / ".env"
    env_file.write_text("# Local settings\nKB_CHAT_MODEL=keep-chat\nKB_ADMIN_TOKEN=keep-admin\nKB_EMBEDDING_API_KEY=old\n", "utf-8")
    profile = manager.registry.list("embedding")[0]
    manager.registry.secret(profile["id"], "new-key")
    manager.registry.sync_default_environment(manager.project)
    text = env_file.read_text("utf-8")
    assert "KB_CHAT_MODEL=keep-chat" in text and "KB_ADMIN_TOKEN=keep-admin" in text
    assert 'KB_EMBEDDING_API_KEY="new-key"' in text
    assert "KB_EMBEDDING_MODEL" in text


def test_new_storage_cannot_be_nested_in_existing_source(manager, service, make_pdf):
    pdf = make_pdf("existing source/sample.pdf")
    service.add_root(pdf.parent)
    profile = manager.registry.list("embedding")[0]
    with pytest.raises(ValueError, match="来源目录重叠"):
        manager.save_kb({"name": "nested", "data_dir": str(pdf.parent / "new-data"),
                         "embedding_id": profile["id"], "auto_start": False})


def test_create_requires_both_locations_and_keeps_sources_when_stopped(manager, tmp_path):
    client = TestClient(management_app(manager, auto_start=False))
    profile = manager.registry.list("embedding")[0]
    value = {"name": "with-locations", "embedding_id": profile["id"], "auto_start": False}
    assert client.post("/manager/api/knowledge-bases", headers=headers(), json=value).status_code == 422
    source = tmp_path / "资料 来源"
    source.mkdir()
    value.update(source_dirs=[str(source)], data_dir=str(tmp_path / "向量 存储"))
    response = client.post("/manager/api/knowledge-bases", headers=headers(), json=value)
    assert response.status_code == 200
    operation = response.json()
    deadline = time.monotonic() + 5
    while operation["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.02)
        operation = manager.operations[operation["id"]]
    assert operation["status"] == "done", operation
    kb = operation["result"]
    assert kb["source_dirs"] == [str(source.resolve())]
    snapshot = manager.snapshot(kb)
    assert snapshot["source_dirs"] == kb["source_dirs"]
    assert snapshot["vector_dir"].endswith("vectors")
    response = client.delete("/manager/api/knowledge-bases/" + kb["id"], headers=headers())
    operation = response.json()
    deadline = time.monotonic() + 5
    while operation["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.02)
        operation = manager.operations[operation["id"]]
    assert operation["status"] == "done", operation
    assert source.is_dir()
    assert (tmp_path / "向量 存储").is_dir()


def test_source_validation_happens_before_creating_storage(manager, tmp_path):
    profile = manager.registry.list("embedding")[0]
    output = tmp_path / "should-not-exist"
    value = {"name": "invalid", "embedding_id": profile["id"], "auto_start": False,
             "data_dir": str(output), "source_dirs": [str(tmp_path / "missing-source")]}
    before = len(manager.registry.list("kb"))
    with pytest.raises(ValueError, match="数据源目录不存在"):
        manager.save_kb(value)
    assert not output.exists()
    assert len(manager.registry.list("kb")) == before
    source = tmp_path / "source"
    source.mkdir()
    value.update(source_dirs=[str(source)], data_dir=str(source / "nested-output"))
    with pytest.raises(ValueError, match="不能重叠"):
        manager.save_kb(value)
