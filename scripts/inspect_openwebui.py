"""Read local Open WebUI configuration without displaying API keys or token values."""
import json
import sqlite3
from pathlib import Path

path = Path("openwebui-data/webui.db").resolve()
db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
db.row_factory = sqlite3.Row
try:
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%config%'")]
    result = {"tables": names, "users": db.execute('SELECT COUNT(*) FROM user').fetchone()[0]}
    for name in names:
        columns = [r[1] for r in db.execute('PRAGMA table_info("' + name + '")')]
        result[name + "_columns"] = columns
        if "key" in columns and "value" in columns:
            for row in db.execute('SELECT key,value FROM "' + name + '" WHERE key IN (?,?,?)',
                    ("tool_server.connections", "models.default_models", "ui.default_models")):
                value = json.loads(row["value"]) if isinstance(row["value"], str) else None
                if row["key"] == "tool_server.connections" and isinstance(value, list):
                    result["tool_servers"] = [{"type": c.get("type"), "url": c.get("url"),
                        "name": c.get("info", {}).get("name"), "enabled": c.get("config", {}).get("enable"),
                        "has_token": bool(c.get("key"))} for c in value]
                elif value is not None:
                    result[row["key"]] = value
    print(json.dumps(result, ensure_ascii=True, indent=2))
finally:
    db.close()
