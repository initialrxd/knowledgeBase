from __future__ import annotations

import hashlib
import json
import math
import random
import threading
import time

import httpx

from .config import Settings


class ProviderError(RuntimeError):
    """Only sanitized error messages cross the application boundary."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class Providers:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.client = httpx.Client(timeout=settings.api_timeout, transport=transport, follow_redirects=False)
        self.embedding_calls = 0
        self.chat_calls = 0
        self._slots = threading.BoundedSemaphore(settings.api_concurrency)
        self._embedding_batch_cap = settings.embedding_batch_size

    def close(self):
        self.client.close()

    def _post(self, base: str, path: str, key: str, payload: dict) -> dict:
        if not base or not key:
            raise ProviderError("API URL/key not configured; edit local .env")
        for attempt in range(5):
            try:
                with self._slots:
                    response = self.client.post(base.rstrip("/") + "/" + path.lstrip("/"),
                        headers={"Authorization": "Bearer " + key}, json=payload)
            except httpx.TransportError:
                if attempt == 4:
                    raise ProviderError("API connection failed after 5 attempts; check network and endpoint") from None
                time.sleep(min(2 ** attempt, 16) + random.random())
                continue
            if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < 4:
                delay = response.headers.get("Retry-After", "")
                time.sleep(min(float(delay), 60) if delay.isdigit() else min(2 ** attempt, 16) + random.random())
                continue
            if response.is_error:
                # Provider response bodies may contain prompts, URLs, or echoed credentials.
                raise ProviderError(f"API returned HTTP {response.status_code}; check model, endpoint and quota", response.status_code)
            try:
                return response.json()
            except ValueError:
                raise ProviderError("API returned invalid JSON") from None
        raise ProviderError("API request exhausted retries")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if len(texts) > self._embedding_batch_cap:
            return [vector for start in range(0, len(texts), self._embedding_batch_cap)
                    for vector in self.embed(texts[start:start + self._embedding_batch_cap])]
        if self.settings.demo_mode:
            # Explicit test/demo mode only. These are NOT semantic embeddings.
            result = []
            for text in texts:
                vector = [0.0] * 64
                for char in text.lower():
                    if char.isalnum():
                        vector[hashlib.sha256(char.encode()).digest()[0] % 64] += 1
                norm = math.sqrt(sum(x * x for x in vector)) or 1
                result.append([x / norm for x in vector])
            self.embedding_calls += 1
            return result
        if not self.settings.embedding_model:
            raise ProviderError("KB_EMBEDDING_MODEL is not configured")
        # Send the minimum compatible request. Configured dimensions validate the response,
        # rather than requesting provider-specific dimension reduction.
        payload = {"model": self.settings.embedding_model, "input": texts}
        try:
            response = self._post(self.settings.embedding_base_url, self.settings.embedding_endpoint,
                self.settings.embedding_api_key.get_secret_value(), payload)
        except ProviderError as error:
            if error.status_code in (400, 413) and len(texts) > 1:
                middle = len(texts) // 2
                self._embedding_batch_cap = min(self._embedding_batch_cap, max(1, middle))
                return self.embed(texts[:middle]) + self.embed(texts[middle:])
            raise
        self.embedding_calls += 1
        try:
            items = sorted(response["data"], key=lambda item: item["index"])
            if [item["index"] for item in items] != list(range(len(texts))):
                raise ValueError("Embedding response indexes do not match the input")
            vectors = [[float(x) for x in item["embedding"]] for item in items]
            dimensions = len(vectors[0])
            if not dimensions or any(len(v) != dimensions or not all(math.isfinite(x) for x in v) for v in vectors):
                raise ValueError("Invalid embedding vectors")
            if self.settings.embedding_dimensions and dimensions != self.settings.embedding_dimensions:
                raise ValueError("Embedding dimensions differ from configured dimensions")
            return vectors
        except (KeyError, TypeError, ValueError, IndexError):
            raise ProviderError("API embedding response has an unexpected shape or dimensions") from None

    def chat(self, messages: list[dict], classification=False) -> str:
        s = self.settings
        if s.demo_mode:
            if classification:
                return json.dumps({"category": "待分类", "reason": "Demo mode; configure a classifier API", "confidence": 0})
            raise ProviderError("Demo mode has no answering model; configure a real chat API")
        base = (s.classify_base_url or s.chat_base_url) if classification else s.chat_base_url
        key = (s.classify_api_key.get_secret_value() or s.chat_api_key.get_secret_value()) if classification else s.chat_api_key.get_secret_value()
        model = (s.classify_model or s.chat_model) if classification else s.chat_model
        if not model:
            raise ProviderError("Chat/classification model is not configured")
        response = self._post(base, "/chat/completions", key,
            {"model": model, "messages": messages, "temperature": 0,
             "max_tokens": 1024 if classification else s.chat_max_tokens})
        self.chat_calls += 1
        try:
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Missing text")
            if response["choices"][0].get("finish_reason") == "length":
                raise ProviderError("Chat response was truncated; increase KB_CHAT_MAX_TOKENS")
            if not content.strip():
                raise ProviderError("Chat API returned no answer text; check reasoning/output token budget")
            return content
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("Chat API did not return text") from None
