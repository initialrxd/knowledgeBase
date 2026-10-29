"""Managed worker: explicit settings in its environment, never in command arguments."""
from __future__ import annotations

import asyncio
import json
import os

from .api import serve
from .config import Settings
from .service import KnowledgeService


def main():
    settings = Settings(_env_file=None, **json.loads(os.environ.pop("KNOWLEDGE_WORKER_SETTINGS")))
    service = KnowledgeService(settings)
    try:
        for path in json.loads(os.environ.pop("KNOWLEDGE_WORKER_SOURCES", "[]")):
            service.add_root(path)
        asyncio.run(serve(service))
    finally:
        service.close()


if __name__ == "__main__":
    main()
