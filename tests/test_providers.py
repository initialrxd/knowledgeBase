import httpx
import pytest

from knowledge_service.providers import ProviderError, Providers


def test_embedding_response_indices_are_respected(settings):
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})
    settings = settings.model_copy(update={"demo_mode": False, "embedding_base_url": "https://example.test/v1",
        "embedding_api_key": __import__("pydantic").SecretStr("private"), "embedding_model": "test"})
    provider = Providers(settings, httpx.MockTransport(handler))
    try:
        assert provider.embed(["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]
    finally:
        provider.close()


def test_provider_errors_never_echo_response_body(settings):
    provider = Providers(settings, httpx.MockTransport(lambda request: httpx.Response(401, text="private-key-echo")))
    try:
        with pytest.raises(ProviderError) as caught:
            provider._post("https://example.test", "/embeddings", "private-key", {})
        assert "private-key" not in str(caught.value)
        assert "401" in str(caught.value)
    finally:
        provider.close()


def test_embedding_batch_limit_is_adapted(settings):
    import json
    from pydantic import SecretStr
    sizes = []
    def handler(request):
        inputs = json.loads(request.content)["input"]
        sizes.append(len(inputs))
        if len(inputs) > 2:
            return httpx.Response(400, json={"error": "batch too large"})
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [1.0, 0.0]} for i in range(len(inputs))]})
    settings = settings.model_copy(update={"demo_mode": False, "embedding_base_url": "https://example.test/v1",
        "embedding_api_key": SecretStr("private"), "embedding_model": "test"})
    provider = Providers(settings, httpx.MockTransport(handler))
    try:
        assert len(provider.embed(["a", "b", "c", "d"])) == 4
        assert sizes == [4, 2, 2]
    finally:
        provider.close()
