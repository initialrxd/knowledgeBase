import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from knowledge_service.api import tools_app
from knowledge_service.config import IngestionTuning, LibraryTuning, RetrievalTuning
from knowledge_service.manager_api import management_app
from knowledge_service.manager_gateway import Gateway
from knowledge_service.manager_runtime import Manager
from knowledge_service.manager_store import Registry


@pytest.fixture
def manager(tmp_path, settings):
    instance = Manager(tmp_path / "console", settings)
    yield instance
    instance.pool.shutdown(wait=True)
    instance.status_pool.shutdown(wait=True)


def test_tuning_persists_without_changing_other_library_or_vector_profile(manager, monkeypatch):
    original = manager.registry.get("kb", "default")
    sibling = manager.save_kb({"name": "sibling", "embedding_id": original["embedding_id"], "auto_start": False})
    before = manager.registry.worker_settings(original)
    tuning = LibraryTuning.from_settings(before).model_dump()
    tuning.update(chunk_tokens=1000, chunk_overlap=60, api_concurrency=4, ocr_mode="off",
                  search_limit=5, search_mode="keyword", search_category="技术")
    manager.worker_states["default"] = "running"
    restarts = []
    monkeypatch.setattr(manager, "restart_worker", lambda identifier: restarts.append(identifier))
    assert manager.save_tuning("default", tuning)["restarted"]
    assert restarts == ["default"]
    restored = Registry(manager.registry.directory)
    after = restored.worker_settings(restored.get("kb", "default"))
    assert after.chunk_tokens == 1000 and after.search_limit == 5 and after.search_mode == "keyword"
    assert after.api_concurrency == 4 and after.ocr_mode == "off"
    assert after.profile == before.profile
    assert after.parser_profile != before.parser_profile
    assert restored.worker_settings(sibling).chunk_tokens == before.chunk_tokens
    assert restored.worker_settings(sibling).search_limit == before.search_limit
    assert not manager.save_tuning("default", tuning)["restarted"]
    assert restarts == ["default"]
    with pytest.raises(ValidationError):
        manager.save_tuning("default", {**tuning, "chunk_overlap": 1000})
    assert restored.get("kb", "default")["tuning"] == tuning


def test_tuning_api_validation_roundtrip_and_search_proxy(manager, monkeypatch):
    client = TestClient(management_app(manager, auto_start=False))
    auth = {"Authorization": "Bearer test-admin-token"}
    tuning = LibraryTuning.from_settings(manager.registry.worker_settings(manager.registry.get("kb", "default"))).model_dump()
    route = "/manager/api/knowledge-bases/default"
    assert client.put(route + "/tuning", json=tuning).status_code == 401
    for invalid in ({"chunk_overlap": 8000}, {"api_concurrency": 17}, {"search_mode": "wrong"},
                    {"search_limit": 0}, {"search_document_id": "wrong"}, {"api_token": "unexpected"}):
        assert client.put(route + "/tuning", json={**tuning, **invalid}, headers=auth).status_code == 422
    tuning.update(search_limit=5, search_mode="keyword")
    operation = client.put(route + "/tuning", json=tuning, headers=auth).json()
    deadline = time.monotonic() + 5
    while operation["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.01)
        operation = client.get("/manager/api/operations/" + operation["id"], headers=auth).json()
    assert operation["status"] == "done", operation
    state = client.get("/manager/api/state", headers=auth).json()
    assert state["knowledge_bases"][0]["tuning"] == tuning
    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return {"results": [], "warnings": []}
    monkeypatch.setattr(manager, "request", request)
    assert client.post(route + "/search", json={"query": "radar"}, headers=auth).status_code == 200
    assert calls[0][0] == ("default", "POST", "/v1/search")
    assert calls[0][1]["json"]["mode"] is None
    assert client.post(route + "/search", json={"query": ""}, headers=auth).status_code == 422


def test_search_defaults_and_explicit_overrides(service, make_pdf, monkeypatch):
    first = service.ingest(make_pdf("one.pdf", pages=["Radar calibration one."]))
    service.ingest(make_pdf("two.pdf", pages=["Radar calibration two."]))
    service.set_category(first["document_id"], "technical/radar")
    service.s.search_mode = "keyword"
    service.s.search_limit = 1
    service.s.search_category = "technical"
    service.s.search_document_id = first["document_id"]
    def unexpected_embed(*args):
        raise AssertionError("Keyword default must skip cloud embedding")
    monkeypatch.setattr(service.providers, "embed", unexpected_embed)
    with TestClient(tools_app(service)) as client:
        auth = {"Authorization": "Bearer test-read-token"}
        found = client.post("/v1/search", json={"query": "radar"}, headers=auth).json()
        assert len(found["results"]) == 1 and found["results"][0]["document_id"] == first["document_id"]
        found = client.post("/v1/search", json={"query": "radar", "limit": 5, "mode": "keyword",
            "category": "", "document_id": ""}, headers=auth).json()
        assert len(found["results"]) == 2
    service.s.search_category = "missing"
    assert service.ask("radar")["citations"] == []


def test_gateway_respects_library_defaults_and_explicit_request_limit(manager, monkeypatch):
    kb = manager.registry.get("kb", "default")
    tuning = LibraryTuning.from_settings(manager.registry.worker_settings(kb)).model_dump()
    tuning.update(search_limit=2, search_mode="keyword")
    manager.save_tuning("default", tuning)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs["json"])
        return {"results": [{"id": str(i), "text": "radar"} for i in range(6)], "warnings": []}
    monkeypatch.setattr(manager, "request", request)
    gateway = Gateway(manager, manager.registry.get("mcp", "default"))
    assert len(gateway.search("radar")["results"]) == 2
    assert calls[-1]["mode"] is None and calls[-1]["limit"] is None
    assert len(gateway.search("radar", limit=4, mode="vector", category="", document_id="")["results"]) == 4
    assert calls[-1]["mode"] == "vector" and calls[-1]["category"] == ""


def test_default_tuning_syncs_to_standalone_environment(manager):
    env = manager.project / ".env"
    env.write_text("KB_CHAT_MODEL=keep\n", encoding="utf-8")
    kb = manager.registry.get("kb", "default")
    tuning = LibraryTuning.from_settings(manager.registry.worker_settings(kb)).model_dump()
    tuning.update(search_limit=5, ocr_image_regions=True)
    manager.save_tuning("default", tuning)
    from knowledge_service.config import Settings
    standalone = Settings(_env_file=env)
    assert standalone.search_limit == 5 and standalone.ocr_image_regions is True
    assert standalone.chat_model == "keep"


def test_separate_saves_preserve_the_other_group(manager):
    initial = manager.registry.worker_settings(manager.registry.get("kb", "default"))
    ingestion = IngestionTuning.model_validate(initial.model_dump(include=set(IngestionTuning.model_fields))).model_dump()
    retrieval = RetrievalTuning.model_validate(initial.model_dump(include=set(RetrievalTuning.model_fields))).model_dump()
    ingestion.update(chunk_tokens=1200, chunk_overlap=60)
    manager.save_tuning("default", ingestion, "ingestion")
    after_ingestion = manager.registry.worker_settings(manager.registry.get("kb", "default"))
    assert after_ingestion.chunk_tokens == 1200
    assert after_ingestion.search_limit == initial.search_limit
    retrieval.update(search_limit=3, search_mode="keyword")
    manager.save_tuning("default", retrieval, "retrieval")
    after_retrieval = manager.registry.worker_settings(manager.registry.get("kb", "default"))
    assert after_retrieval.chunk_tokens == 1200 and after_retrieval.chunk_overlap == 60
    assert after_retrieval.search_limit == 3 and after_retrieval.search_mode == "keyword"
    ingestion.update(api_concurrency=4)
    manager.save_tuning("default", ingestion, "ingestion")
    after_second_ingestion = manager.registry.worker_settings(manager.registry.get("kb", "default"))
    assert after_second_ingestion.search_limit == 3 and after_second_ingestion.search_mode == "keyword"


def test_scoped_save_routes_reject_fields_from_the_other_group(manager):
    client = TestClient(management_app(manager, auto_start=False))
    auth = {"Authorization": "Bearer test-admin-token"}
    route = "/manager/api/knowledge-bases/default/tuning/"
    assert client.put(route + "ingestion", json={"search_limit": 3}, headers=auth).status_code == 422
    assert client.put(route + "retrieval", json={"chunk_tokens": 1000}, headers=auth).status_code == 422
    for scope, payload, expected in (("ingestion", {"chunk_tokens": 1000}, "chunk_tokens"),
                                     ("retrieval", {"search_limit": 3}, "search_limit")):
        assert client.put(route + scope, json=payload).status_code == 401
        operation = client.put(route + scope, json=payload, headers=auth).json()
        deadline = time.monotonic() + 5
        while operation["status"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(0.01)
            operation = client.get("/manager/api/operations/" + operation["id"], headers=auth).json()
        assert operation["status"] == "done", operation
        assert operation["result"]["tuning"][expected] == payload[expected]
    persisted = manager.registry.worker_settings(manager.registry.get("kb", "default"))
    assert persisted.chunk_tokens == 1000 and persisted.search_limit == 3


def test_preview_applies_unsaved_values_without_changing_defaults(manager, service, make_pdf, monkeypatch):
    first = service.ingest(make_pdf("preview-one.pdf", pages=["Radar calibration preview one."]))
    service.ingest(make_pdf("preview-two.pdf", pages=["Radar calibration preview two."]))
    service.set_category(first["document_id"], "technical/radar")
    retrieval = RetrievalTuning(search_mode="keyword", search_limit=1,
        search_category="technical", search_document_id=first["document_id"]).model_dump()
    manager.save_tuning("default", retrieval, "retrieval")
    for key, value in retrieval.items():
        setattr(service.s, key, value)
    before = manager.registry.get("kb", "default")
    restarts = []
    monkeypatch.setattr(manager, "restart_worker", lambda *args: restarts.append(args))
    worker_responses = []
    def request(identifier, method, path, **kwargs):
        assert path == "/v1/search"
        found = service.search(**kwargs["json"])
        worker_responses.append(found)
        return found
    monkeypatch.setattr(manager, "request", request)
    client = TestClient(management_app(manager, auto_start=False))
    response = client.post("/manager/api/knowledge-bases/default/search",
        json={"query": "radar", "mode": "keyword", "limit": 5, "category": "", "document_id": ""},
        headers={"Authorization": "Bearer test-admin-token"})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert response.json()["timings_ms"] == worker_responses[0]["timings_ms"]
    assert response.json()["timings_ms"]["embedding_ms"] is None
    assert len(service.search("radar")["results"]) == 1
    assert manager.registry.get("kb", "default") == before
    assert service.s.search_limit == 1 and service.s.search_category == "technical"
    assert restarts == []
