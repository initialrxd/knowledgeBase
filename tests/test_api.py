from fastapi.testclient import TestClient

from knowledge_service.api import admin_app, tools_app


def test_tool_schema_is_query_only_and_protected(service, make_pdf):
    service.ingest(make_pdf())
    with TestClient(tools_app(service)) as client:
        schema = client.get("/openapi.json").json()
        names = {op["operationId"] for methods in schema["paths"].values() for op in methods.values()}
        assert names == {"search_knowledge", "get_chunk", "get_document", "list_categories"}
        assert client.get("/v1/categories").status_code == 401
        headers = {"Authorization": "Bearer test-read-token"}
        assert client.get("/v1/categories", headers=headers).status_code == 200
        assert client.post("/admin/actions", json={"action": "delete"}, headers=headers).status_code == 404
        result = client.post("/v1/search", json={"query": "calibration", "mode": "keyword"}, headers=headers)
        assert result.status_code == 200
        assert result.json()["results"][0]["page_start"] == 1


def test_admin_token_is_distinct_from_read_token(service):
    with TestClient(admin_app(service)) as client:
        assert client.get("/admin/status", headers={"Authorization": "Bearer test-read-token"}).status_code == 401
        assert client.get("/admin/status", headers={"Authorization": "Bearer test-admin-token"}).status_code == 200


def test_query_validation_and_mcp_auth(service):
    with TestClient(tools_app(service)) as client:
        headers = {"Authorization": "Bearer test-read-token"}
        assert client.post("/v1/search", json={"query": ""}, headers=headers).status_code == 422
        assert client.post("/mcp", json={}).status_code == 401
        assert client.get("/v1/documents/not-found", headers=headers).status_code == 404


def test_rate_limit_and_local_shutdown(service):
    service.s.requests_per_minute = 1
    with TestClient(tools_app(service)) as client:
        headers = {"Authorization": "Bearer test-read-token"}
        assert client.get("/v1/categories", headers=headers).status_code == 200
        assert client.get("/v1/categories", headers=headers).status_code == 429
    with TestClient(admin_app(service)) as client:
        assert client.post("/admin/shutdown", headers={"Authorization": "Bearer test-read-token"}).status_code == 401
        assert client.post("/admin/shutdown", headers={"Authorization": "Bearer test-admin-token"}).status_code == 200
        assert service.stop_event.is_set()
