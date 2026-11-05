from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KB_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8765
    tools_port: int = 8766
    api_token: SecretStr = SecretStr("")
    admin_token: SecretStr = SecretStr("")
    embedding_base_url: str = ""
    embedding_endpoint: str = "/embeddings"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=0, ge=0)
    embedding_revision: str = "default"
    embedding_batch_size: int = Field(default=8, ge=1, le=256)
    chat_base_url: str = ""
    chat_api_key: SecretStr = SecretStr("")
    chat_model: str = ""
    chat_max_tokens: int = Field(default=8192, ge=512, le=32768)
    classify_base_url: str = ""
    classify_api_key: SecretStr = SecretStr("")
    classify_model: str = ""
    ocr_mode: Literal["auto", "off", "force"] = "auto"
    ocr_image_regions: bool = False
    pdf_layout: Literal["native", "structured"] = "native"
    chunk_tokens: int = Field(default=800, ge=64, le=8000)
    chunk_overlap: int = Field(default=100, ge=0)
    scan_interval: int = Field(default=300, ge=5)
    file_settle_seconds: float = Field(default=3, ge=0)
    api_concurrency: int = Field(default=2, ge=1, le=16)
    requests_per_minute: int = Field(default=60, ge=1)
    demo_mode: bool = False
    public_base_url: str = ""
    api_timeout: float = 120
    max_context_tokens: int = 12000
    search_limit: int = Field(default=10, ge=1, le=50)
    search_mode: Literal["hybrid", "keyword", "vector"] = "hybrid"
    search_category: str = Field(default="", max_length=1000)
    search_document_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    tokenizer: str = "cl100k_base"
    unclassified_names: list[str] = ["inbox", "unclassified", "未分类", "待分类"]

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        return self

    @property
    def root(self) -> Path:
        return self.data_dir.resolve()

    @property
    def embedding_spec(self) -> dict:
        return {
            "base_url": self.embedding_base_url.rstrip("/"),
            "endpoint": self.embedding_endpoint,
            "model": self.embedding_model,
            "dimensions": self.embedding_dimensions,
            "revision": self.embedding_revision,
            "normalization": "none",
            "input_version": 1,
            "demo": self.demo_mode,
        }

    @property
    def profile(self) -> str:
        return hashlib.sha256(json.dumps(self.embedding_spec, sort_keys=True).encode()).hexdigest()[:24]

    @property
    def parser_profile(self) -> str:
        return hashlib.sha256(json.dumps({"parser": 3, "ocr": self.ocr_mode,
            "image_regions": self.ocr_image_regions, "layout": self.pdf_layout,
            "tokens": self.chunk_tokens, "overlap": self.chunk_overlap,
            "tokenizer": self.tokenizer}, sort_keys=True).encode()).hexdigest()[:24]

    def prepare(self):
        for name in ("originals", "library", "extracted", "vectors", "staging", "exports", "cache"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(self.root / "cache" / "tiktoken"))


class IngestionTuning(BaseModel):
    """Ingestion settings saved without changing retrieval defaults."""

    model_config = ConfigDict(extra="forbid")
    chunk_tokens: int = Field(default=800, ge=64, le=8000)
    chunk_overlap: int = Field(default=100, ge=0)
    ocr_mode: Literal["auto", "off", "force"] = "auto"
    pdf_layout: Literal["native", "structured"] = "native"
    ocr_image_regions: bool = False
    api_concurrency: int = Field(default=2, ge=1, le=16)

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("重叠长度必须小于切片长度")
        return self


class RetrievalTuning(BaseModel):
    """Retrieval defaults; preview requests can override these without saving."""

    model_config = ConfigDict(extra="forbid")
    search_limit: int = Field(default=10, ge=1, le=50)
    search_mode: Literal["hybrid", "keyword", "vector"] = "hybrid"
    search_category: str = Field(default="", max_length=1000)
    search_document_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")


class LibraryTuning(IngestionTuning, RetrievalTuning):
    """Public, credential-free settings editable independently for each library."""

    @classmethod
    def from_settings(cls, settings: Settings):
        return cls.model_validate(settings.model_dump(include=set(cls.model_fields)))


def initialize(env_file: Path = Path(".env")) -> bool:
    """Create local configuration once, never overwrite existing credentials."""
    if env_file.exists():
        return False
    example = Path(__file__).resolve().parent.parent / ".env.example"
    text = example.read_text(encoding="utf-8")
    text = text.replace("KB_API_TOKEN=\n", f"KB_API_TOKEN={secrets.token_urlsafe(32)}\n")
    text = text.replace("KB_ADMIN_TOKEN=\n", f"KB_ADMIN_TOKEN={secrets.token_urlsafe(32)}\n")
    env_file.write_text(text, encoding="utf-8")
    return True
