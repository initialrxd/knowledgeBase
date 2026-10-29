from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import portalocker
import uvicorn

from .config import Settings, initialize
from .manager_api import management_app
from .manager_runtime import Manager


async def run(manager, app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=manager.port, access_log=False))
    task = asyncio.create_task(server.serve())
    while not task.done() and not manager.shutdown_event.is_set():
        await asyncio.sleep(0.2)
    server.should_exit = True
    await task


def main():
    parser = argparse.ArgumentParser(description="本机多知识库管理台")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    initialize()
    project = Path(__file__).resolve().parent.parent
    manager = Manager(project, Settings(), port=args.port)
    try:
        with portalocker.Lock(str(manager.registry.directory / "manager.lock"), timeout=0):
            app = management_app(manager)
            # Bootstrap is local-only and consumed once. Never log permanent credentials.
            manager.registry.secret("bootstrap", manager.login_token)
            manager.registry.secret("manager_admin", manager.base.admin_token.get_secret_value())
            print(f"知识库管理台 http://127.0.0.1:{args.port}；使用 scripts/manage.py start-manager --background 打开登录链接", flush=True)
            asyncio.run(run(manager, app))
    except portalocker.exceptions.LockException:
        raise SystemExit("管理台已在运行，请使用现有实例") from None


if __name__ == "__main__":
    main()
