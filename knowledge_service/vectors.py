from __future__ import annotations

import re
import threading
from pathlib import Path

import lancedb
import pyarrow as pa


class Vectors:
    def __init__(self, path: Path):
        self.db = lancedb.connect(str(path))
        self.lock = threading.RLock()
        self.changes = {}
        self.operations = {}

    @staticmethod
    def name(profile: str):
        if not re.fullmatch(r"[a-f0-9]{24}", profile):
            raise ValueError("Invalid embedding profile")
        return "vectors_" + profile

    def table(self, profile, dimensions=None):
        name = self.name(profile)
        try:
            return self.db.open_table(name)
        except ValueError:
            if dimensions is None:
                return None
            schema = pa.schema([
                ("chunk_id", pa.string()), ("document_id", pa.string()),
                ("version_id", pa.string()), ("vector", pa.list_(pa.float32(), dimensions)),
            ])
            return self.db.create_table(name, schema=schema, exist_ok=True)

    def add(self, profile: str, rows: list[dict]):
        if not rows:
            return
        with self.lock:
            table = self.table(profile, len(rows[0]["vector"]))
            # Retrying an interrupted write must never duplicate chunk vectors.
            table.merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(rows)
            self.changes[profile] = self.changes.get(profile, 0) + len(rows)
            self.operations[profile] = self.operations.get(profile, 0) + 1

    def search(self, profile, vector, limit=100, document_id=None, document_ids=None, version_ids=None):
        with self.lock:
            table = self.table(profile)
            if table is None:
                return []
            query = table.search(vector).distance_type("cosine").limit(limit)
            filters = []
            if document_id:
                filters.append("document_id = '" + document_id.replace("'", "''") + "'")
            elif document_ids is not None:
                if not document_ids:
                    return []
                values = ",".join("'" + identifier.replace("'", "''") + "'" for identifier in document_ids)
                filters.append("document_id IN (" + values + ")")
            if version_ids is not None:
                if not version_ids:
                    return []
                values = ",".join("'" + identifier.replace("'", "''") + "'" for identifier in version_ids)
                filters.append("version_id IN (" + values + ")")
            if filters:
                query = query.where(" AND ".join(filters), prefilter=True)
            return query.select(["chunk_id", "_distance"]).to_list()

    def has_chunks(self, profile, version_id, chunk_ids):
        """Check actual coverage, including tables pruned by older application versions."""
        with self.lock:
            table = self.table(profile)
            if table is None:
                return False
            rows = (table.search().where("version_id = '" + version_id.replace("'", "''") + "'")
                    .select(["chunk_id"]).limit(None).to_list())
            return {row["chunk_id"] for row in rows} == set(chunk_ids)

    def prune_document(self, profile, document_id, keep_version=None):
        with self.lock:
            table = self.table(profile)
            if table is None:
                return
            where = f"document_id = '{document_id}'"
            if keep_version:
                where += f" AND version_id != '{keep_version}'"
            table.delete(where)

    def optimize(self, profile, force=False):
        with self.lock:
            table = self.table(profile)
            if table is None:
                return
            count = table.count_rows()
            indexes = table.list_indices()
            if count >= 10000 and not any("vector" in idx.columns for idx in indexes):
                # IVF_FLAT supports arbitrary embedding dimensions, with no PQ divisibility restriction.
                partitions = max(1, min(1024, int(count ** 0.5), count // 256))
                table.create_index(metric="cosine", index_type="IVF_FLAT", num_partitions=partitions)
            if force or self.changes.get(profile, 0) >= 10000 or self.operations.get(profile, 0) >= 20:
                table.optimize()
                self.changes[profile] = 0
                self.operations[profile] = 0

    def batches(self, profile, batch_size=1000):
        table = self.table(profile)
        if table is not None:
            yield from table.search().limit(None).to_batches(batch_size=batch_size)

    def close(self):
        close = getattr(self.db, "close", None)
        if close:
            close()
        self.db = None
