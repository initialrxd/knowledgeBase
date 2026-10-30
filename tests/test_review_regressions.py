"""Failure and configuration transitions identified in the 2026-10-30 code review."""
from __future__ import annotations

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from knowledge_service.api import admin_app
from knowledge_service.db import Database
from knowledge_service.manager_runtime import Manager
from knowledge_service.providers import ProviderError


def switch_profile(service, revision):
    service.s = service.s.model_copy(update={"embedding_revision": revision})
    service.providers.settings = service.s


def test_completed_reindex_can_run_again_through_admin_api(service, make_pdf):
    service.ingest(make_pdf())
    with TestClient(admin_app(service)) as client:
        headers = {"Authorization": "Bearer test-admin-token"}
        first = client.post("/admin/actions", headers=headers, json={"action": "reindex"}).json()
        service.run_job(first["id"])
        switch_profile(service, "second-model")
        second = client.post("/admin/actions", headers=headers, json={"action": "reindex"}).json()
        assert second["status"] == "queued"
        assert second["id"] != first["id"]
        assert client.post("/admin/actions", headers=headers, json={"action": "reindex"}).json() == second
        service.run_job(second["id"])
    assert service.db.get_meta("active_profile") == service.s.profile
    assert service.db.rows("SELECT status,attempts FROM jobs ORDER BY created") == [
        {"status": "done", "attempts": 1}, {"status": "done", "attempts": 1}]


def test_concurrent_enqueue_deduplicates_active_tasks_and_keeps_history(service):
    def enqueue(_):
        return service.enqueue("reindex", {})["id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        identifiers = set(pool.map(enqueue, range(24)))
    assert len(identifiers) == 1
    first = identifiers.pop()
    service.db.execute("UPDATE jobs SET status='done',result='{}' WHERE id=?", (first,))
    with ThreadPoolExecutor(max_workers=8) as pool:
        identifiers = set(pool.map(enqueue, range(24)))
    assert len(identifiers) == 1
    assert first not in identifiers
    assert service.db.one("SELECT COUNT(*) n FROM jobs")["n"] == 2


def test_retry_does_not_duplicate_a_replacement_task(service):
    first = service.enqueue("reindex", {})
    service.db.execute("UPDATE jobs SET status='failed',error='offline' WHERE id=?", (first["id"],))
    second = service.enqueue("reindex", {})
    service.retry()
    assert service.db.rows("SELECT id FROM jobs WHERE status='queued'") == [{"id": second["id"]}]


def test_version_one_database_upgrade_preserves_all_job_fields(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    jobs = [(str(i), "reindex", json.dumps({"i": i}), status, i, "reason", '{"progress":2}', 10., 20.)
            for i, status in enumerate(("queued", "running", "done", "failed", "cancelled"))]
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,"
                    "status TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,"
                    "error TEXT,result TEXT,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(kind,payload))")
        con.executemany("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)", jobs)
        con.execute("PRAGMA user_version=1")
    db = Database(path)
    with db.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert [tuple(row) for row in con.execute("SELECT * FROM jobs ORDER BY id")] == jobs
        # A new execution with the same arguments must now be representable.
        con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)", ("new", *jobs[2][1:]))
    assert len(Database(path).rows("SELECT * FROM jobs")) == 6


def test_failed_large_update_keeps_vector_search_of_published_version(service, make_pdf, monkeypatch):
    updating = False
    completed = 0
    old_id = None

    def embed(texts):
        nonlocal completed
        if texts == ["calibration"]:
            return [[1., 0.]]
        if updating:
            completed += len(texts)
            if completed > 256:
                # Check availability while unpublished batches are already present.
                assert service.search("calibration", mode="vector", limit=1)["results"][0]["document_id"] == old_id
                raise ProviderError("Injected outage after a persisted batch")
        return [[0.8, 0.2] if "oldpublishedtoken" in text else [1., 0.] for text in texts]

    monkeypatch.setattr(service.providers, "embed", embed)
    source = make_pdf(pages=["Calibration oldpublishedtoken reference."])
    old = service.ingest(source)
    old_id = old["document_id"]
    service.set_category(old_id, "Radar/Calibration")
    source.unlink()
    make_pdf(pages=[f"Calibration updated reference page {i:04} with unique value {i:04}." for i in range(264)])
    updating = True
    with pytest.raises(ProviderError, match="outage"):
        service.ingest(source)
    assert service.vectors.table(service.s.profile).count_rows() == 257
    assert service.get_document(old_id)["current_version"] == old["version_id"]
    for filters in ({}, {"category": "Radar"}, {"document_id": old_id},
                    {"category": "Radar", "document_id": old_id}):
        found = service.search("calibration", mode="vector", limit=1, **filters)
        assert [row["version_id"] for row in found["results"]] == [old["version_id"]]
    assert service.search("calibration", mode="vector", category="Other", document_id=old_id)["results"] == []


def test_duplicate_sources_split_when_only_one_copy_changes(service, make_pdf):
    source = make_pdf("a.pdf", pages=["Uniquetermold calibration reference."])
    other = source.with_name("b.pdf")
    shutil.copyfile(source, other)
    original = service.ingest(source)
    assert service.ingest(other)["document_id"] == original["document_id"]
    source.unlink()
    make_pdf("a.pdf", pages=["Uniquetermnew updated specifications."])
    updated = service.ingest(source)
    assert updated["document_id"] != original["document_id"]
    assert service.ingest(other)["status"] == "unchanged"
    assert service.scan()["enqueued"] == 0
    assert service.search("Uniquetermold", mode="keyword")["results"][0]["document_id"] == original["document_id"]
    assert service.search("Uniquetermnew", mode="keyword")["results"][0]["document_id"] == updated["document_id"]
    assert service.status()["counts"]["live_documents"] == 2


def test_split_update_resumes_without_overwriting_original_or_losing_category(service, make_pdf, monkeypatch):
    source = make_pdf("a.pdf")
    other = source.with_name("b.pdf")
    shutil.copyfile(source, other)
    original = service.ingest(source)
    service.ingest(other)
    service.set_category(original["document_id"], "Radar/Manual")
    source.unlink()
    make_pdf("a.pdf", pages=["Updated calibration reference."])
    embed = service.providers.embed

    def fail(texts):
        raise ProviderError("Injected outage")

    monkeypatch.setattr(service.providers, "embed", fail)
    with pytest.raises(ProviderError):
        service.ingest(source)
    assert service.db.one("SELECT document_id FROM sources WHERE path=?", (str(source),))["document_id"] == original["document_id"]
    folders = set((service.s.root / "extracted").iterdir())
    monkeypatch.setattr(service.providers, "embed", embed)
    updated = service.ingest(source)
    assert set((service.s.root / "extracted").iterdir()) == folders
    assert updated["document_id"] != original["document_id"]
    assert service.get_document(original["document_id"])["current_version"] == original["version_id"]
    assert service.get_document(updated["document_id"])["category"] == "Radar/Manual"
    assert service.get_document(updated["document_id"])["category_locked"]


def test_reindex_after_reverting_document_and_switching_back_model(service, make_pdf):
    source = make_pdf(pages=["Radar original reference."])
    original_bytes = source.read_bytes()
    first = service.ingest(source)
    source.unlink()
    make_pdf(pages=["Radar updated reference."])
    service.ingest(source)
    assert not service.db.one("SELECT 1 FROM indexed_versions WHERE profile=? AND version_id=?",
                              (service.s.profile, first["version_id"]))
    switch_profile(service, "model-two")
    service.reindex()
    source.write_bytes(original_bytes)
    service.ingest(source)
    switch_profile(service, "default")
    calls = service.providers.embedding_calls
    service.reindex()
    assert service.providers.embedding_calls == calls  # Rebuild from the existing cache.
    assert service.status()["has_vector_index"]
    assert service.search("Radar", mode="vector")["results"][0]["version_id"] == first["version_id"]


@pytest.mark.parametrize("remove_all", [False, True])
def test_reindex_repairs_legacy_markers_with_missing_vectors(service, make_pdf, remove_all):
    first = service.ingest(make_pdf(pages=["Radar calibration reference.", "Sensor temperature correction."]))
    chunks = service.db.rows("SELECT id FROM chunks WHERE version_id=?", (first["version_id"],))
    table = service.vectors.table(service.s.profile)
    table.delete("true" if remove_all else f"chunk_id = '{chunks[0]['id']}'")
    assert service.db.one("SELECT 1 FROM indexed_versions WHERE version_id=?", (first["version_id"],))
    calls = service.providers.embedding_calls
    service.reindex()
    assert service.providers.embedding_calls == calls
    assert service.vectors.has_chunks(service.s.profile, first["version_id"], [row["id"] for row in chunks])
    assert service.search("Radar", mode="vector")["results"]


def test_manager_restart_refreshes_global_models_but_preserves_library_configuration(tmp_path, settings):
    initial = settings.model_copy(update={"chat_model": "chat-old", "classify_model": "classifier-old",
                                         "chat_api_key": "old-chat-key", "classify_api_key": "old-classifier-key"})
    first = Manager(tmp_path, initial)
    second = None
    try:
        default = first.registry.get("kb", "default")
        sibling = first.save_kb({"name": "sibling", "embedding_id": default["embedding_id"], "auto_start": False})
        first.save_tuning("default", {"search_mode": "keyword", "search_limit": 7}, "retrieval")
        old = {kb["id"]: first.registry.worker_settings(kb) for kb in first.registry.list("kb")}
        refreshed = initial.model_copy(update={"chat_model": "chat-new", "chat_api_key": "new-chat-key",
                                               "classify_model": "", "classify_api_key": "",
                                               "chat_max_tokens": 4096, "max_context_tokens": 6000})
        second = Manager(tmp_path, refreshed)
        for identifier in ("default", sibling["id"]):
            kb = second.registry.get("kb", identifier)
            effective = second.registry.worker_settings(kb)
            assert effective.chat_model == "chat-new"
            assert effective.chat_api_key.get_secret_value() == "new-chat-key"
            assert effective.classify_model == ""  # Clearing restores fallback to the chat configuration.
            assert effective.classify_api_key.get_secret_value() == ""
            assert effective.chat_max_tokens == 4096
            assert effective.max_context_tokens == 6000
            assert effective.api_token == old[identifier].api_token
            assert effective.admin_token == old[identifier].admin_token
            assert effective.profile == old[identifier].profile
            assert effective.search_limit == old[identifier].search_limit
            assert kb["settings_version"] != kb.get("applied_settings_version")
    finally:
        for manager in (first, second):
            if manager:
                manager.pool.shutdown(wait=True)
                manager.status_pool.shutdown(wait=True)


def test_interrupted_model_refresh_is_retried_on_next_manager_start(tmp_path, settings, monkeypatch):
    first = Manager(tmp_path, settings.model_copy(update={"chat_model": "chat-old"}))
    second = None
    try:
        updated = settings.model_copy(update={"chat_model": "chat-new"})

        def fail(kind, value):
            raise OSError("Injected registry write interruption")

        monkeypatch.setattr(first.registry, "put", fail)
        with pytest.raises(OSError, match="interruption"):
            first.registry.refresh_model_settings(updated)
        second = Manager(tmp_path, updated)
        kb = second.registry.get("kb", "default")
        assert second.registry.worker_settings(kb).chat_model == "chat-new"
        assert kb["settings_version"] != kb.get("applied_settings_version")
    finally:
        for manager in (first, second):
            if manager:
                manager.pool.shutdown(wait=True)
                manager.status_pool.shutdown(wait=True)
