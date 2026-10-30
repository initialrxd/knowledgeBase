from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories(
 id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, reason TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL, category_id TEXT NOT NULL,
 current_version TEXT, category_locked INTEGER NOT NULL DEFAULT 0,
 deleted INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS versions(
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL, file_hash TEXT NOT NULL,
 parser_profile TEXT NOT NULL, page_count INTEGER NOT NULL, warnings TEXT NOT NULL,
 created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS versions_document ON versions(document_id);
CREATE INDEX IF NOT EXISTS versions_hash ON versions(file_hash,parser_profile);
CREATE TABLE IF NOT EXISTS chunks(
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version_id TEXT NOT NULL,
 content_hash TEXT NOT NULL, text TEXT NOT NULL, token_count INTEGER NOT NULL,
 page_start INTEGER NOT NULL, page_end INTEGER NOT NULL, section TEXT NOT NULL,
 method TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_version ON chunks(version_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, tokens);
CREATE TABLE IF NOT EXISTS roots(
 id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sources(
 path TEXT PRIMARY KEY, root_id TEXT NOT NULL, document_id TEXT NOT NULL,
 file_hash TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 missing INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS sources_document ON sources(document_id);
CREATE TABLE IF NOT EXISTS embedding_cache(
 profile TEXT NOT NULL, content_hash TEXT NOT NULL, dimensions INTEGER NOT NULL,
 vector BLOB NOT NULL, PRIMARY KEY(profile,content_hash));
CREATE TABLE IF NOT EXISTS profiles(
 id TEXT PRIMARY KEY, spec TEXT NOT NULL, dimensions INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS indexed_versions(
 profile TEXT NOT NULL, version_id TEXT NOT NULL, PRIMARY KEY(profile,version_id));
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Database schema is newer than this application")
            con.executescript(SCHEMA)
            # Version 1 deduplicated completed tasks forever. Rebuild only the queue,
            # retaining IDs, progress, failures and history in one transaction.
            with con:
                con.execute("BEGIN IMMEDIATE")
                if version == 1:
                    con.execute("ALTER TABLE jobs RENAME TO jobs_v1")
                    con.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,"
                                "status TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,"
                                "error TEXT,result TEXT,created REAL NOT NULL,updated REAL NOT NULL)")
                    con.execute("INSERT INTO jobs SELECT * FROM jobs_v1")
                    con.execute("DROP TABLE jobs_v1")
                con.execute("CREATE INDEX IF NOT EXISTS jobs_lookup ON jobs(kind,payload,created)")
                con.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
        try:
            with con:
                yield con
        finally:
            con.close()

    def rows(self, sql: str, args=()) -> list[dict]:
        with self.connect() as con:
            return [dict(row) for row in con.execute(sql, args)]

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql: str, args=()):
        with self.connect() as con:
            con.execute(sql, args)

    def set_meta(self, key: str, value):
        self.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value)))

    def get_meta(self, key: str, default=None):
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def recover_jobs(self):
        self.execute("UPDATE jobs SET status='queued',updated=? WHERE status='running'", (time.time(),))
