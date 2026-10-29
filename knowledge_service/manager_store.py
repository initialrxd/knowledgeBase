"""Local registry. Credentials live outside portable knowledge bundles."""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import SecretStr

from .config import Settings


def settings_values(settings: Settings) -> dict:
    return {name: value.get_secret_value() if isinstance(value, SecretStr)
            else str(value) if isinstance(value, Path) else value
            for name, value in settings.__dict__.items() if name in Settings.model_fields}


class Registry:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.path = self.directory / "manager.sqlite3"
        self.secret_path = self.directory / "secrets.json"
        with self.connection() as con:
            con.execute("CREATE TABLE IF NOT EXISTS entities(kind TEXT,id TEXT,value TEXT,PRIMARY KEY(kind,id))")
        self.credentials = json.loads(self.secret_path.read_text("utf-8")) if self.secret_path.exists() else {}

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list(self, kind):
        with self.connection() as con:
            return [json.loads(r[0]) for r in con.execute("SELECT value FROM entities WHERE kind=? ORDER BY rowid", (kind,))]

    def get(self, kind, identifier):
        with self.connection() as con:
            row = con.execute("SELECT value FROM entities WHERE kind=? AND id=?", (kind, identifier)).fetchone()
        if row is None:
            raise KeyError("Configuration not found")
        return json.loads(row[0])

    def put(self, kind, value):
        with self.lock, self.connection() as con:
            con.execute("INSERT OR REPLACE INTO entities VALUES(?,?,?)", (kind, value["id"], json.dumps(value)))
        return value

    def delete(self, kind, identifier):
        self.get(kind, identifier)
        with self.lock, self.connection() as con:
            con.execute("DELETE FROM entities WHERE kind=? AND id=?", (kind, identifier))

    def secret(self, key, value=None):
        with self.lock:
            if value is not None:
                self.credentials[key] = value
                temporary = self.secret_path.with_suffix(".tmp")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(self.credentials, stream)
                temporary.replace(self.secret_path)
            return self.credentials.get(key, "")

    def seed(self, settings: Settings):
        if self.list("kb"):
            return
        values = settings_values(settings)
        profile = {"id": uuid.uuid4().hex, "name": "默认 Embedding", "tested_at": None, "test_ok": None}
        for field in ("base_url", "endpoint", "model", "dimensions", "revision", "batch_size"):
            profile[field] = values["embedding_" + field]
        self.secret(profile["id"], values["embedding_api_key"])
        self.put("embedding", profile)
        kb = {"id": "default", "name": "默认知识库", "data_dir": str(settings.root),
              "embedding_id": profile["id"], "auto_start": True, "admin_port": settings.port,
              "tools_port": 0, "legacy": True}
        self.secret("settings:default", values)
        self.put("kb", kb)
        self.put("mcp", {"id": "default", "name": "默认知识库 MCP", "port": settings.tools_port,
                         "knowledge_base_ids": ["default"], "auto_start": True})
        self.secret("mcp:default", values["api_token"] or secrets.token_urlsafe(32))

    def worker_settings(self, kb):
        values = dict(self.secret("settings:" + kb["id"]))
        profile = self.get("embedding", kb["embedding_id"])
        for field in ("base_url", "endpoint", "model", "dimensions", "revision", "batch_size"):
            values["embedding_" + field] = profile[field]
        values.update(kb.get("tuning", {}))
        values.update(embedding_api_key=self.secret(profile["id"]), data_dir=kb["data_dir"],
                      port=kb["admin_port"], tools_port=kb["tools_port"], host="127.0.0.1", public_base_url="")
        return Settings(_env_file=None, **values)

    def sync_default_environment(self, project: Path):
        """Keep standalone legacy serve compatible with the default library's UI settings."""
        env_file = project / ".env"
        if not env_file.exists():
            return
        try:
            kb = self.get("kb", "default")
            profile = self.get("embedding", kb["embedding_id"])
        except KeyError:
            return
        text = env_file.read_text("utf-8")
        fields = {"KB_EMBEDDING_" + name.upper(): profile[name]
                  for name in ("base_url", "endpoint", "model", "dimensions", "revision", "batch_size")}
        fields["KB_EMBEDDING_API_KEY"] = self.secret(profile["id"])
        fields.update({"KB_" + name.upper(): value for name, value in kb.get("tuning", {}).items()})
        updated = text
        for key, value in fields.items():
            line = key + "=" + json.dumps(str(value), ensure_ascii=False)
            pattern = re.compile(r"^" + key + r"=.*$", re.MULTILINE)
            updated = pattern.sub(lambda match: line, updated) if pattern.search(updated) else updated.rstrip() + "\n" + line + "\n"
        if updated != text:
            temporary = self.directory / "env-sync.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(updated)
            temporary.replace(env_file)
