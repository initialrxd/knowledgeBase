"""Launch isolated Open WebUI using local configuration, without copying API secrets into code."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from platform_paths import venv_executable

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from knowledge_service.config import Settings  # noqa: E402


def environment(settings):
    env = os.environ.copy()
    data = PROJECT / "openwebui-data"
    data.mkdir(exist_ok=True)
    secret = data / ".webui_secret_key"
    if not secret.exists():
        secret.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    env.update({
        "PYTHONUTF8": "1", "DATA_DIR": str(data),
        "WEBUI_SECRET_KEY": secret.read_text(encoding="utf-8").strip(),
        "ENABLE_OLLAMA_API": "false", "ENABLE_OPENAI_API": "true",
        # Standard mode supports native PDF uploads and embedded vector storage.
        # Embeddings and chat still use the configured cloud APIs.
        "USE_SLIM_DOCKER": str(settings.webui_slim).lower(),
        "VECTOR_DB": env.get("VECTOR_DB", "pgvector" if settings.webui_slim else "chroma"),
        "OPENAI_API_BASE_URL": settings.chat_base_url,
        "OPENAI_API_BASE_URLS": settings.chat_base_url,
        "OPENAI_API_KEY": settings.chat_api_key.get_secret_value(),
        "OPENAI_API_KEYS": settings.chat_api_key.get_secret_value(),
        "DEFAULT_MODELS": settings.chat_model,
        "RAG_EMBEDDING_ENGINE": "openai", "RAG_EMBEDDING_MODEL": settings.embedding_model,
        "RAG_OPENAI_API_BASE_URL": settings.embedding_base_url,
        "RAG_OPENAI_API_KEY": settings.embedding_api_key.get_secret_value(),
        "RAG_EMBEDDING_MODEL_AUTO_UPDATE": "false", "RAG_RERANKING_MODEL_AUTO_UPDATE": "false",
        "WHISPER_MODEL_AUTO_UPDATE": "false", "ENABLE_VERSION_UPDATE_CHECK": "false",
        "DO_NOT_TRACK": "true", "ANONYMIZED_TELEMETRY": "false", "SCARF_NO_ANALYTICS": "true",
        "TIKTOKEN_CACHE_DIR": str(settings.root / "cache" / "tiktoken"),
        "ENABLE_TOOL_SERVERS": "true",
        "TOOL_SERVER_CONNECTIONS": json.dumps([{
            "type": "openapi", "url": f"http://127.0.0.1:{settings.tools_port}",
            "path": "openapi.json", "auth_type": "bearer",
            "key": settings.api_token.get_secret_value(),
            "config": {"enable": True},
            "info": {"id": "portable_knowledge", "name": "本地 PDF 知识库",
                "description": "搜索本机 PDF 资料，读取片段与页码，回答时引用来源。"},
        }], ensure_ascii=False),
    })
    return env


def main():
    settings = Settings()
    settings.prepare()
    executable = venv_executable(PROJECT / ".venv-webui", "open-webui")
    if not executable.exists():
        raise SystemExit("Open WebUI is not installed; run scripts/manage.py install --with-openwebui")
    pid = PROJECT / "logs" / "openwebui-child.pid"
    pid.parent.mkdir(exist_ok=True)
    if sys.platform != "win32":
        # Replace the wrapper so SIGTERM reaches the actual server on macOS.
        pid.write_text(str(os.getpid()), encoding="utf-8")
        os.execve(str(executable), [str(executable), "serve", "--host", "127.0.0.1", "--port", "8080"],
                  environment(settings))
    child = subprocess.Popen([str(executable), "serve", "--host", "127.0.0.1", "--port", "8080"],
        cwd=PROJECT, env=environment(settings))
    pid.write_text(str(child.pid), encoding="utf-8")
    try:
        raise SystemExit(child.wait())
    except KeyboardInterrupt:
        child.terminate()
        child.wait(timeout=30)


if __name__ == "__main__":
    main()
