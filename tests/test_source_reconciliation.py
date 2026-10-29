import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledge_service.api import admin_app


@pytest.mark.parametrize("failed", [False, True])
def test_scan_cancels_deleted_first_import_and_restores_same_job(service, make_pdf, failed):
    pdf = make_pdf("source/pending.pdf")
    root = service.add_root(pdf.parent)
    service.scan()
    job = service.db.one("SELECT * FROM jobs WHERE kind='ingest'")
    contents, stat = pdf.read_bytes(), pdf.stat()
    if failed:
        service.db.execute("UPDATE jobs SET status='failed',error='Provider unavailable' WHERE id=?", (job["id"],))
    pdf.unlink()

    service.scan()
    cancelled = service.db.one("SELECT * FROM jobs WHERE id=?", (job["id"],))
    assert cancelled["status"] == "cancelled"
    assert cancelled["error"] is None
    assert json.loads(cancelled["result"])["reason"] == "source_missing"
    assert service.status()["index_jobs_summary"]["unresolved_failures"] == 0
    assert service.db.rows("SELECT * FROM sources") == []
    assert service.run_job(job["id"])["status"] == "cancelled"
    assert service.providers.embedding_calls == 0

    # Reappearance with the same signature must reactivate the original queue entry.
    pdf.write_bytes(contents)
    os.utime(pdf, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert service.scan()["enqueued"] == 1
    assert service.db.one("SELECT COUNT(*) n FROM jobs")["n"] == 1
    assert service.run_job(job["id"])["status"] == "indexed"
    assert service.db.one("SELECT root_id FROM sources")["root_id"] == root["id"]


def test_worker_cancels_file_deleted_after_scan(service, make_pdf, monkeypatch):
    pdf = make_pdf("source/removed.pdf")
    service.add_root(pdf.parent)
    service.scan()
    job = service.db.one("SELECT id FROM jobs")
    pdf.unlink()
    monkeypatch.setattr(service, "ingest", lambda *args: pytest.fail("Deleted source must not be ingested"))
    assert service.run_job(job["id"])["reason"] == "source_missing"
    row = service.db.one("SELECT status,attempts FROM jobs WHERE id=?", (job["id"],))
    assert row == {"status": "cancelled", "attempts": 0}


def test_worker_handles_deletion_during_import(service, make_pdf, monkeypatch):
    pdf = make_pdf("source/race.pdf")
    service.add_root(pdf.parent)
    service.scan()
    job = service.db.one("SELECT id FROM jobs")
    ingest = service.ingest

    def remove_before_ingest(*args):
        pdf.unlink()
        return ingest(*args)

    monkeypatch.setattr(service, "ingest", remove_before_ingest)
    assert service.run_job(job["id"])["reason"] == "source_missing"
    assert service.db.one("SELECT status,error FROM jobs") == {"status": "cancelled", "error": None}


@pytest.mark.parametrize("single_job", [False, True])
def test_retry_refreshes_directory_and_preserves_real_failures(service, make_pdf, single_job):
    removed = make_pdf("source/removed.pdf")
    retained = make_pdf("source/retained.pdf")
    service.add_root(removed.parent)
    service.scan()
    service.db.execute("UPDATE jobs SET status='failed',error='Provider unavailable'")
    jobs = {json.loads(j["payload"])["path"]: j["id"] for j in service.db.rows("SELECT id,payload FROM jobs")}
    removed.unlink()
    added = make_pdf("source/added.pdf")

    service.retry(jobs[str(removed)] if single_job else None)
    states = {j["id"]: j["status"] for j in service.db.rows("SELECT id,status FROM jobs")}
    assert states[jobs[str(removed)]] == "cancelled"
    assert states[jobs[str(retained)]] == ("failed" if single_job else "queued")
    assert any(json.loads(j["payload"])["path"] == str(added) and j["status"] == "queued"
               for j in service.db.rows("SELECT payload,status FROM jobs"))
    assert service.status()["index_jobs_summary"]["unresolved_failures"] == int(single_job)
    service.retry()
    assert service.db.one("SELECT status FROM jobs WHERE id=?", (jobs[str(removed)],))["status"] == "cancelled"


@pytest.mark.parametrize("unavailable", [False, True])
def test_incomplete_or_offline_directory_does_not_cancel_jobs(service, make_pdf, monkeypatch, unavailable):
    pdf = make_pdf("source/retained.pdf")
    service.add_root(pdf.parent)
    service.scan()
    service.db.execute("UPDATE jobs SET status='failed',error='Provider unavailable'")
    if unavailable:
        pdf.parent.rename(pdf.parent.with_name("offline"))
    else:
        rglob = Path.rglob

        def incomplete_scan(path, pattern):
            if path == pdf.parent:
                raise PermissionError("Temporarily inaccessible")
            return rglob(path, pattern)

        monkeypatch.setattr(Path, "rglob", incomplete_scan)
    service.scan()
    assert service.db.one("SELECT status FROM jobs")["status"] == "failed"
    assert service.status()["last_scan"]["errors"]
    service.retry()
    assert service.db.one("SELECT status FROM jobs")["status"] == "queued"


def test_resume_scans_before_unpausing(service, make_pdf):
    removed = make_pdf("source/removed.pdf")
    service.add_root(removed.parent)
    service.scan()
    service.db.set_meta("paused", True)
    removed.unlink()
    added = make_pdf("source/added.pdf")
    with TestClient(admin_app(service)) as client:
        response = client.post("/admin/actions", json={"action": "resume"},
                               headers={"Authorization": "Bearer test-admin-token"})
    assert response.status_code == 200
    assert response.json() == {"paused": False}
    jobs = {json.loads(j["payload"])["path"]: j["status"] for j in service.db.rows("SELECT payload,status FROM jobs")}
    assert jobs == {str(removed): "cancelled", str(added): "queued"}
