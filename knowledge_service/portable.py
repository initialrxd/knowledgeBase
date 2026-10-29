"""Versioned, streaming, database-independent export and import."""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import time
import uuid
from pathlib import Path, PurePosixPath

import pyarrow.parquet as pq

from .service import file_hash, json_file
from .text import terms

TABLES = ("categories", "documents", "versions", "chunks", "profiles", "indexed_versions")


def _filesystem_path(path):
    """Keep portable relative names while supporting Windows' extended file paths."""
    path = Path(path).resolve()
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
        return Path(value)
    return path


def export_bundle(service, destination, include_vectors=True):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Export destination must not exist")
    if destination.is_relative_to(service.s.root):
        raise ValueError("Export outside the managed data directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = _filesystem_path(destination.with_name(destination.name + ".partial-" + uuid.uuid4().hex[:8]))
    stage.mkdir()
    active = service.db.get_meta("active_profile")
    with service.write_lock:
        (stage / "catalog").mkdir()
        with service.db.connect() as con:
            con.execute("BEGIN")
            for table in TABLES:
                with (stage / "catalog" / f"{table}.jsonl").open("w", encoding="utf-8") as stream:
                    cursor = con.execute(f"SELECT * FROM {table}")
                    while batch := cursor.fetchmany(1000):
                        for row in batch:
                            stream.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        for name in ("originals", "extracted", "library"):
            shutil.copytree(_filesystem_path(service.s.root / name), stage / name)
        tokenizer_cache = service.s.root / "cache" / "tiktoken"
        if tokenizer_cache.exists():
            shutil.copytree(tokenizer_cache, stage / "tokenizer_cache")
        # Cached vectors include all completed batches, including inactive models, with no secrets.
        if include_vectors:
            (stage / "vectors").mkdir()
            for profile in service.db.rows("SELECT * FROM profiles"):
                folder = stage / "vectors" / profile["id"]
                folder.mkdir()
                for index, batch in enumerate(service.vectors.batches(profile["id"])):
                    pq.write_table(__import__("pyarrow").Table.from_batches([batch]), folder / f"part-{index:06}.parquet")
        for name in ("pyproject.toml", "requirements.lock.txt", "requirements-webui.lock.txt", ".env.example"):
            source = Path(__file__).resolve().parent.parent / name
            if source.exists():
                shutil.copyfile(source, stage / name)
        project = Path(__file__).resolve().parent.parent
        application = stage / "application"
        application.mkdir()
        for name in ("knowledge_service", "scripts", "docs", "config"):
            if (project / name).is_dir():
                shutil.copytree(project / name, application / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("pyproject.toml", "requirements.lock.txt", "requirements-webui.lock.txt", ".env.example", "README.md", "HANDOFF.md", ".gitignore"):
            if (project / name).is_file():
                shutil.copyfile(project / name, application / name)
        (stage / "RESTORE.md").write_text(
            "# Restore\n\nThe application/ folder contains the source and Windows/macOS installer. "
            "Copy application/ to a writable folder, run Python 3.11/3.12 scripts/manage.py install, "
            "configure .env with your own credentials, "
            "start the knowledge service, then run knowledge import <this bundle path> --wait. "
            "Open WebUI users and chat history are backed up separately.\n", encoding="utf-8")
        json_file(stage / "manifest.json", {"format": "portable-knowledge", "version": 1,
            "created": time.time(), "active_profile": active if include_vectors else None,
            "includes_vectors": include_vectors, "source_roots_included": False,
            "processing": {"ocr_mode": service.s.ocr_mode, "chunk_tokens": service.s.chunk_tokens,
                "chunk_overlap": service.s.chunk_overlap, "tokenizer": service.s.tokenizer,
                "pdf_layout": service.s.pdf_layout, "ocr_image_regions": service.s.ocr_image_regions},
            "source_schema": 1})
        with (stage / "checksums.jsonl").open("w", encoding="utf-8") as checksums:
            for path in stage.rglob("*"):
                if path.is_file() and path.name != "checksums.jsonl":
                    checksums.write(json.dumps({"path": path.relative_to(stage).as_posix(),
                        "sha256": file_hash(path), "size": path.stat().st_size}) + "\n")
        (stage / "COMPLETE").write_text("portable-knowledge v1\n", encoding="utf-8")
        stage.replace(_filesystem_path(destination))
    return {"destination": str(destination), "includes_vectors": include_vectors}


def _safe_file(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("Export contains an unsafe relative path")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file() or (root / relative).is_symlink():
        raise ValueError("Export contains a missing or unsafe file")
    return resolved


def import_bundle(service, source):
    source = _filesystem_path(source)
    if not (source / "COMPLETE").is_file():
        raise ValueError("Export is incomplete")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "portable-knowledge" or manifest.get("version") != 1:
        raise ValueError("Unsupported export format version")
    checksums, verified = source / "checksums.jsonl", set()
    with checksums.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            path = _safe_file(source, item["path"])
            if path.stat().st_size != item["size"] or file_hash(path) != item["sha256"]:
                raise ValueError("Export checksum mismatch: " + item["path"])
            verified.add(item["path"])
    actual = {p.relative_to(source).as_posix() for p in source.rglob("*")
              if p.is_file() and p.name not in ("COMPLETE", "checksums.jsonl")}
    if actual != verified:
        raise ValueError("Export has unverified files or an incomplete checksum list")
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Export symlinks are not accepted")
    with service.write_lock:
        if service.db.one("SELECT COUNT(*) n FROM documents")["n"]:
            raise ValueError("Import requires an empty data directory; existing knowledge is never overwritten")
        for name in ("originals", "extracted", "library"):
            shutil.copytree(source / name, _filesystem_path(service.s.root) / name, dirs_exist_ok=True)
        if (source / "tokenizer_cache").is_dir():
            shutil.copytree(source / "tokenizer_cache", service.s.root / "cache" / "tiktoken", dirs_exist_ok=True)
        active = manifest.get("active_profile")
        if manifest.get("includes_vectors"):
            vectors = source / "vectors"
            for profile_dir in vectors.iterdir():
                if not re.fullmatch(r"[a-f0-9]{24}", profile_dir.name):
                    raise ValueError("Invalid vector profile in export")
                for path in sorted(profile_dir.glob("*.parquet")):
                    for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
                        service.vectors.add(profile_dir.name, batch.to_pylist())
        with service.db.connect() as con:
            for table in TABLES:
                path = source / "catalog" / f"{table}.jsonl"
                columns = [row[1] for row in con.execute(f"PRAGMA table_info({table})")]
                if table == "indexed_versions" and not manifest.get("includes_vectors"):
                    continue
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        row = json.loads(line)
                        if set(row) != set(columns):
                            raise ValueError("Catalog schema mismatch: " + table)
                        con.execute(f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                            [row[c] for c in columns])
                        if table == "chunks":
                            con.execute("INSERT INTO chunks_fts VALUES(?,?)", (row["id"], terms(row["text"])))
            if active:
                con.execute("INSERT OR REPLACE INTO meta VALUES('active_profile',?)", (json.dumps(active),))
        # Imported sources are intentionally not registered: old machine paths must not be watched.
        # Rebuild cache entries from portable vectors so unchanged chunks remain reusable on updates.
        if manifest.get("includes_vectors"):
            for profile in service.db.rows("SELECT id FROM profiles"):
                for batch in service.vectors.batches(profile["id"]):
                    with service.db.connect() as con:
                        for vector in batch.to_pylist():
                            chunk = con.execute("SELECT content_hash FROM chunks WHERE id=?", (vector["chunk_id"],)).fetchone()
                            if chunk:
                                values = vector["vector"]
                                con.execute("INSERT OR REPLACE INTO embedding_cache VALUES(?,?,?,?)",
                                    (profile["id"], chunk["content_hash"], len(values), struct.pack(f"<{len(values)}f", *values)))
        # Recreate filename/path bookkeeping so future category changes remove the previous copy.
        for copy in (service.s.root / "library").rglob("*.pdf"):
            identifier = copy.stem.rsplit("__", 1)[-1]
            if re.fullmatch(r"[a-f0-9]{32}", identifier):
                service.db.set_meta("library:" + identifier, copy.relative_to(service.s.root).as_posix())
        return {"imported": True, "active_profile": active,
            "requires_reindex": not manifest.get("includes_vectors"),
            "documents": service.db.one("SELECT COUNT(*) n FROM documents")["n"]}
