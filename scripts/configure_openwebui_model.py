"""Configure native KB tools for an existing model using the Open WebUI model store.

Run with .venv-webui/Scripts/python.exe; defaults to a read-only preview.
The external PDF corpus is not stored in Open WebUI's native knowledge tables.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT = Path(__file__).resolve().parent.parent


async def configure(model_id: str, database: Path, apply: bool, enable_native: bool = False) -> dict:
    if not database.is_file():
        raise FileNotFoundError(f"Open WebUI database does not exist: {database}")
    os.environ["DATA_DIR"] = str(database.parent)
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    os.environ["ENABLE_DB_MIGRATIONS"] = "false"
    os.environ["USE_SLIM_DOCKER"] = "true"
    secret = database.parent / ".webui_secret_key"
    if secret.is_file():
        os.environ["WEBUI_SECRET_KEY"] = secret.read_text(encoding="utf-8").strip()
    if not os.environ.get("WEBUI_SECRET_KEY"):
        raise ValueError("Use the existing Open WebUI secret file or set WEBUI_SECRET_KEY")

    from open_webui.internal.db import async_engine
    from open_webui.models.models import ModelForm, Models

    try:
        current = await Models.get_model_by_id(model_id)
        if current is None:
            raise ValueError(f"Model does not exist: {model_id}")
        meta = deepcopy(current.meta.model_dump())
        builtin = meta.setdefault("builtinTools", {})
        if builtin.get("knowledge") is enable_native:
            return {"model_id": model_id, "changed": False, "native_knowledge_tools": enable_native}
        builtin["knowledge"] = enable_native
        result = {"model_id": model_id, "changed": False, "apply": apply,
                  "native_knowledge_tools": enable_native}
        if not apply:
            return result

        backups = database.parent / "model-backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = backups / f"{stamp}-{uuid4().hex}.json"
        with backup.open("x", encoding="utf-8") as handle:
            json.dump(current.model_dump(), handle, ensure_ascii=False, indent=2)

        # Omit access_grants so the model store preserves the existing grants.
        form = ModelForm(id=current.id, base_model_id=current.base_model_id,
            name=current.name, meta=meta, params=current.params, is_active=current.is_active,
            commit_message=f"Set native knowledge tools: {enable_native}")
        updated = await Models.update_model_by_id(current.id, form, user_id=current.user_id)
        if updated is None:
            raise RuntimeError("Open WebUI did not return the updated model")
        assert updated.meta.model_dump()["builtinTools"]["knowledge"] is enable_native
        assert updated.access_grants == current.access_grants
        assert updated.params == current.params
        result.update(changed=True, backup=str(backup), version_id=updated.version_id)
        return result
    finally:
        await async_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--database", type=Path, default=PROJECT / "openwebui-data" / "webui.db")
    parser.add_argument("--apply", action="store_true", help="Save the model change after backing it up")
    parser.add_argument("--enable-native-knowledge", action="store_true",
        help="Enable native tools when using Open WebUI's own knowledge base")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(configure(args.model_id, args.database.resolve(), args.apply,
        args.enable_native_knowledge)),
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
