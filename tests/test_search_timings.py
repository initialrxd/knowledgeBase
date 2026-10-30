from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import knowledge_service.service as service_module
from knowledge_service.api import tools_app
from knowledge_service.providers import ProviderError


class Clock:
    def __init__(self):
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def timed_search(service, make_pdf, monkeypatch):
    service.ingest(make_pdf())
    clock = Clock()
    # Patch only this module's clock, without altering provider/library clocks.
    monkeypatch.setattr(service_module, "time", SimpleNamespace(perf_counter=lambda: clock.now))

    def instrument(owner, name, delay):
        original = getattr(owner, name)

        def call(*args, **kwargs):
            clock.advance(delay)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, call)

    instrument(service_module, "fts_query", 0.001)
    instrument(service.providers, "embed", 0.020)
    instrument(service.vectors, "search", 0.003)
    instrument(service, "_current_chunks", 0.004)
    instrument(service.db, "get_meta", 0.005)
    return service, clock


def assert_totals(timings):
    assert set(timings) == {"total_ms", "embedding_ms", "keyword_ms", "vector_ms", "results_ms", "other_ms"}
    assert all(value is None or value >= 0 for value in timings.values())
    assert timings["total_ms"] == pytest.approx(sum(value or 0 for key, value in timings.items() if key != "total_ms"))


@pytest.mark.parametrize("mode,expected", [
    ("keyword", {"total_ms": 10, "keyword_ms": 1, "embedding_ms": None, "vector_ms": None, "results_ms": 4, "other_ms": 5}),
    ("vector", {"total_ms": 37, "keyword_ms": None, "embedding_ms": 20, "vector_ms": 3, "results_ms": 8, "other_ms": 6}),
    ("hybrid", {"total_ms": 37, "keyword_ms": 1, "embedding_ms": 20, "vector_ms": 3, "results_ms": 8, "other_ms": 5}),
])
def test_phase_accounting_and_skips(timed_search, mode, expected):
    service, _ = timed_search
    found = service.search("calibration", mode=mode)
    assert found["results"]
    assert found["timings_ms"] == pytest.approx(expected)
    assert_totals(found["timings_ms"])


def test_no_keyword_matches_still_records_execution(timed_search):
    service, _ = timed_search
    found = service.search("unmatcheduniqueterm", mode="keyword")
    assert found["results"] == []
    assert found["timings_ms"]["keyword_ms"] == pytest.approx(1)
    assert_totals(found["timings_ms"])


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_missing_vector_index_skips_embedding_and_vector(service, mode):
    found = service.search("calibration", mode=mode)
    assert found["results"] == []
    assert found["timings_ms"]["embedding_ms"] is None
    assert found["timings_ms"]["vector_ms"] is None
    assert ("No active vector index" in found["warnings"]) == (mode == "vector")
    assert_totals(found["timings_ms"])


def test_failed_embedding_is_timed_in_hybrid_fallback(timed_search, monkeypatch):
    service, clock = timed_search

    def fail(texts):
        clock.advance(0.120)
        raise ProviderError("embedding unavailable")

    monkeypatch.setattr(service.providers, "embed", fail)
    found = service.search("calibration", mode="hybrid")
    assert found["results"]
    assert "keyword-only retrieval used" in found["warnings"][0]
    assert found["timings_ms"]["embedding_ms"] == pytest.approx(120)
    assert found["timings_ms"]["vector_ms"] is None
    assert_totals(found["timings_ms"])
    with pytest.raises(ProviderError, match="embedding unavailable"):
        service.search("calibration", mode="vector")


def test_vector_filter_and_both_result_reads_are_in_correct_phases(timed_search, monkeypatch):
    service, clock = timed_search
    original = service.db.rows

    def rows(sql, *args, **kwargs):
        if sql.startswith("SELECT d.id FROM documents"):
            clock.advance(0.007)
        return original(sql, *args, **kwargs)

    monkeypatch.setattr(service.db, "rows", rows)
    found = service.search("calibration", mode="hybrid", category="missing")
    assert found["results"] == []
    assert found["timings_ms"]["vector_ms"] == pytest.approx(10)
    assert found["timings_ms"]["results_ms"] == pytest.approx(8)
    assert_totals(found["timings_ms"])


def test_http_success_exposes_timings_and_failures_stay_errors(service, make_pdf, monkeypatch):
    service.ingest(make_pdf())
    with TestClient(tools_app(service)) as client:
        headers = {"Authorization": "Bearer test-read-token"}
        response = client.post("/v1/search", json={"query": "calibration", "mode": "keyword"}, headers=headers)
        assert response.status_code == 200
        assert_totals(response.json()["timings_ms"])

        def fail(texts):
            raise ProviderError("embedding unavailable")

        monkeypatch.setattr(service.providers, "embed", fail)
        response = client.post("/v1/search", json={"query": "calibration", "mode": "vector"}, headers=headers)
        assert response.status_code == 503
        assert "timings_ms" not in response.json()
        assert client.post("/v1/search", json={"query": ""}, headers=headers).status_code == 422
