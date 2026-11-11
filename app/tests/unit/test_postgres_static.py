"""阶段6：PostgreSQL 存储静态校验（无 PG 服务时可跑）+ 存储契约对齐。"""
import os

import pytest

psycopg = pytest.importorskip("psycopg")
from brainmem.storage.postgres.db import PostgresStorage, _vec_literal  # noqa: E402
from brainmem.storage.base import Storage  # noqa: E402

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "..", "src", "brainmem",
                      "storage", "postgres", "schema.sql")


def _schema_text():
    with open(SCHEMA, encoding="utf-8") as f:
        return f.read()


def test_schema_has_partitions_hnsw_pgvector():
    s = _schema_text()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in s
    assert "PARTITION BY HASH (tenant_id)" in s
    assert s.count("PARTITION OF memory_node") >= 4
    assert "USING hnsw" in s and "vector_cosine_ops" in s
    assert "vector(256)" in s
    # 六表齐全
    for t in ("memory_node", "memory_edge", "weight_event", "memory_version",
              "consolidation_run", "schema_registry"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in s, t


def test_vec_literal_format():
    assert _vec_literal([1.0, 2.5, -0.25]) == "[1.000000,2.500000,-0.250000]"


def test_postgres_implements_storage_protocol():
    # Protocol 方法都应在 PostgresStorage 上存在
    proto_methods = [m for m in dir(Storage) if not m.startswith("_")]
    missing = [m for m in proto_methods if not hasattr(PostgresStorage, m)]
    assert not missing, f"PostgresStorage 缺方法: {missing}"
