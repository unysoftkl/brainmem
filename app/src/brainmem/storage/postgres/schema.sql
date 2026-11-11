-- PostgreSQL 16 + pgvector 生产 schema（阶段6）。对应 SQLite 六表 + 向量 + 合并快照。
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 记忆节点：按 tenant 哈希分区
CREATE TABLE IF NOT EXISTS memory_node (
  id              TEXT NOT NULL,
  tenant_id       TEXT NOT NULL DEFAULT 'default',
  label           VARCHAR(40) NOT NULL,
  label_norm      VARCHAR(40) NOT NULL,
  char_len        SMALLINT NOT NULL CHECK (char_len BETWEEN 1 AND 10),
  kind            VARCHAR(16) NOT NULL DEFAULT 'ATOM',
  weight_bp       INTEGER NOT NULL,
  stability       SMALLINT NOT NULL DEFAULT 0,
  peak_bp         INTEGER NOT NULL,
  state           VARCHAR(16) NOT NULL,
  fidelity        SMALLINT NOT NULL DEFAULT 100,
  gist            TEXT,
  verbatim_ref    TEXT,
  fingerprint     CHAR(64) NOT NULL,
  salience        SMALLINT NOT NULL DEFAULT 50,
  born_at         DOUBLE PRECISION NOT NULL,
  last_touch_at   DOUBLE PRECISION NOT NULL,
  source_kind     VARCHAR(16) NOT NULL DEFAULT 'HUMAN',
  source_id       TEXT,
  deleted_at      DOUBLE PRECISION,
  embedding       vector(256),
  PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

CREATE TABLE IF NOT EXISTS memory_node_p0 PARTITION OF memory_node FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE IF NOT EXISTS memory_node_p1 PARTITION OF memory_node FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE IF NOT EXISTS memory_node_p2 PARTITION OF memory_node FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE IF NOT EXISTS memory_node_p3 PARTITION OF memory_node FOR VALUES WITH (MODULUS 4, REMAINDER 3);

CREATE UNIQUE INDEX IF NOT EXISTS uq_node_norm ON memory_node (tenant_id, label_norm);
CREATE INDEX IF NOT EXISTS idx_node_tenant_state ON memory_node (tenant_id, state, weight_bp);
-- 向量 ANN 索引（HNSW，余弦）
CREATE INDEX IF NOT EXISTS idx_node_emb_hnsw ON memory_node
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS memory_edge (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT 'default',
  src_id          TEXT NOT NULL,
  dst_id          TEXT NOT NULL,
  relation        TEXT NOT NULL DEFAULT 'ASSOCIATED',
  weight_bp       INTEGER NOT NULL,
  coactivation    INTEGER NOT NULL DEFAULT 0,
  state           TEXT NOT NULL DEFAULT 'ACTIVE',
  confidence      REAL NOT NULL DEFAULT 1.0,
  provenance      TEXT,
  created_at      DOUBLE PRECISION NOT NULL,
  last_touch_at   DOUBLE PRECISION NOT NULL,
  UNIQUE (tenant_id, src_id, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_edge_src ON memory_edge (src_id, weight_bp);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON memory_edge (dst_id, weight_bp);

CREATE TABLE IF NOT EXISTS weight_event (
  seq             BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT 'default',
  entity_kind     TEXT NOT NULL,
  entity_id       TEXT NOT NULL,
  event_type      TEXT NOT NULL,
  delta_bp        INTEGER NOT NULL,
  before_bp       INTEGER NOT NULL,
  after_bp        INTEGER NOT NULL,
  reason          TEXT NOT NULL,
  actor           TEXT NOT NULL,
  at_day          DOUBLE PRECISION NOT NULL,
  at_real         BIGINT NOT NULL,
  trace_id        TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_entity ON weight_event (entity_kind, entity_id, seq);
CREATE INDEX IF NOT EXISTS idx_event_time ON weight_event (at_real);

CREATE TABLE IF NOT EXISTS memory_version (
  id              TEXT PRIMARY KEY,
  node_id         TEXT NOT NULL,
  version_no      INTEGER NOT NULL,
  gist            TEXT,
  verbatim_ref    TEXT,
  diff            TEXT,
  created_at      DOUBLE PRECISION NOT NULL,
  created_by      TEXT NOT NULL,
  reason          TEXT,
  UNIQUE (node_id, version_no)
);

CREATE TABLE IF NOT EXISTS consolidation_run (
  id              TEXT PRIMARY KEY,
  run_type        TEXT NOT NULL,
  started_at      BIGINT NOT NULL,
  finished_at     BIGINT,
  sampled         INTEGER DEFAULT 0,
  changed         INTEGER DEFAULT 0,
  params          TEXT,
  report          TEXT
);

CREATE TABLE IF NOT EXISTS schema_registry (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  template        TEXT NOT NULL,
  created_at      DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS merge_snapshot (
  batch_id      TEXT NOT NULL,
  parent_id     TEXT NOT NULL,
  member_id     TEXT NOT NULL,
  old_weight_bp INTEGER NOT NULL,
  created_at    DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (batch_id, parent_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_merge_batch ON merge_snapshot (batch_id);

INSERT INTO schema_meta(key, value) VALUES ('schema_version', '3')
  ON CONFLICT (key) DO UPDATE SET value = '3';
