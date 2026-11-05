"""Bounded, read-only access to local service logs for the management console."""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote, quote_plus

from pydantic import SecretStr


TAIL_BYTES = 128 * 1024
TAIL_LINES = 1000
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CREDENTIAL = re.compile(
    r"(?i)(\b(?:bearer|basic)\s+)[^\s\"',;<>]+|"
    r"(\b(?:[\w-]*api[-_]?key|[\w-]*token|password|knowledge_manager)[\"']?\s*[:=]\s*[\"']?)"
    r"[^\s\"',;&<>]+"
)


def sources(manager):
    for service, name in (("manager", "管理台 / MCP"), ("knowledge", "独立知识库服务"), ("openwebui", "Open WebUI")):
        for stream, label in (("err", "诊断输出"), ("out", "标准输出")):
            identifier = f"{service}.{stream}"
            yield identifier, f"{name} · {label}", Path("logs") / f"{identifier}.log"
    for kb in manager.registry.list("kb"):
        identifier = kb["id"]
        if re.fullmatch(r"default|[0-9a-f]{32}", identifier):
            yield f"worker-{identifier}", f"知识库 · {kb['name']}", Path("manager-data/logs") / f"{identifier}.log"


def redact(manager, content):
    fields = {key for key, value in vars(manager.base).items() if isinstance(value, SecretStr)}
    secrets = {getattr(manager.base, key).get_secret_value() for key in fields}
    with manager.registry.lock:
        for value in manager.registry.credentials.values():
            if isinstance(value, str):
                secrets.add(value)
            elif isinstance(value, dict):
                secrets.update(value.get(key, "") for key in fields)
    secrets.add(getattr(manager, "login_token", ""))
    variants = {encoded for value in secrets if isinstance(value, str) and value
                for encoded in (value, quote(value, safe=""), quote_plus(value))}
    if variants:
        pattern = "|".join(map(re.escape, sorted(variants, key=len, reverse=True)))
        content = re.sub(pattern, "[已隐藏]", content)
    return CREDENTIAL.sub(lambda match: (match[1] or match[2]) + "[已隐藏]", content)


def tail(manager, relative_path):
    path = manager.project / relative_path
    try:
        if path.resolve() != path or not path.is_file():
            return {"status": "missing", "lines": [], "truncated": False}
        with path.open("rb") as log:
            stat = os.fstat(log.fileno())
            offset = max(0, stat.st_size - TAIL_BYTES)
            log.seek(offset)
            raw = log.read(min(stat.st_size, TAIL_BYTES))
    except FileNotFoundError:
        return {"status": "missing", "lines": [], "truncated": False}
    except (OSError, RuntimeError):
        return {"status": "unreadable", "lines": [], "truncated": False}
    if offset:
        # Drop the partial first line, which could contain a split credential.
        raw = raw.partition(b"\n")[2]
    content = ANSI_ESCAPE.sub("", raw.decode("utf-8", errors="replace"))
    lines = redact(manager, content).splitlines()
    return {"status": "ok", "lines": lines[-TAIL_LINES:], "truncated": bool(offset or len(lines) > TAIL_LINES),
            "updated_at": stat.st_mtime}
