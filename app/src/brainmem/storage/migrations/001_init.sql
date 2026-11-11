-- 001_init.sql · 六张核心表 + 索引 + FTS5（《记忆语义规范》第 2 节 / 设计书附录 B.1）
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_node (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT 'default',
  label           TEXT NOT NULL,
  label_norm      TEXT NOT NULL,
  char_len        INTEGER NOT NULL CHECK (char_len BETWEEN 1 AND 100),
  kind            TEXT NOT NULL DEFAULT 'ATOM',
  weight_bp       INTEGER NOT NULL,
  stability       INTEGER NOT NULL DEFAULT 0,
  peak_bp         INTEGER NOT NULL,
  state           TEXT NOT NULL,
  fidelity        INTEGER NOT NULL DEFAULT 100,
  gist            TEXT,
  verbatim_ref    TEXT,
  fingerprint     TEXT NOT NULL,
  salience        INTEGER NOT NULL DEFAULT 50,
  born_at         REAL NOT NULL,
  last_touch_at   REAL NOT NULL,
  source_kind     TEXT NOT NULL DEFAULT 'HUMAN',
  source_id       TEXT,
  deleted_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_node_tenant_state ON memory_node(tenant_id, state);
CREATE INDEX IF NOT EXISTS idx_node_weight       ON memory_node(tenant_id, weight_bp);
CREATE INDEX IF NOT EXISTS idx_node_fp           ON memory_node(tenant_id, fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS uq_node_norm   ON memory_node(tenant_id, label_norm);

CREATE TABLE IF NOT EXISTS memory_edge (
  id              TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT 'default',
  src_id          TEXT NOT NULL REFERENCES memory_node(id),
  dst_id          TEXT NOT NULL REFERENCES memory_node(id),
  relation        TEXT NOT NULL DEFAULT 'ASSOCIATED',
  weight_bp       INTEGER NOT NULL,
  coactivation    INTEGER NOT NULL DEFAULT 0,
  state           TEXT NOT NULL DEFAULT 'ACTIVE',
  confidence      REAL NOT NULL DEFAULT 1.0,
  provenance      TEXT,
  created_at      REAL NOT NULL,
  last_touch_at   REAL NOT NULL,
  UNIQUE (tenant_id, src_id, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_edge_src ON memory_edge(src_id, weight_bp);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON memory_edge(dst_id, weight_bp);

CREATE TABLE IF NOT EXISTS weight_event (
  seq             INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id       TEXT NOT NULL DEFAULT 'default',
  entity_kind     TEXT NOT NULL,
  entity_id       TEXT NOT NULL,
  event_type      TEXT NOT NULL,
  delta_bp        INTEGER NOT NULL,
  before_bp       INTEGER NOT NULL,
  after_bp        INTEGER NOT NULL,
  reason          TEXT NOT NULL,
  actor           TEXT NOT NULL,
  at_day          REAL NOT NULL,
  at_real         INTEGER NOT NULL,
  trace_id        TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_entity ON weight_event(entity_kind, entity_id, seq);
CREATE INDEX IF NOT EXISTS idx_event_time   ON weight_event(at_real);

CREATE TABLE IF NOT EXISTS memory_version (
  id              TEXT PRIMARY KEY,
  node_id         TEXT NOT NULL REFERENCES memory_node(id),
  version_no      INTEGER NOT NULL,
  gist            TEXT,
  verbatim_ref    TEXT,
  diff            TEXT,
  created_at      REAL NOT NULL,
  created_by      TEXT NOT NULL,
  reason          TEXT,
  UNIQUE (node_id, version_no)
);

CREATE TABLE IF NOT EXISTS consolidation_run (
  id              TEXT PRIMARY KEY,
  run_type        TEXT NOT NULL,
  started_at      INTEGER NOT NULL,
  finished_at     INTEGER,
  sampled         INTEGER DEFAULT 0,
  changed         INTEGER DEFAULT 0,
  params          TEXT,
  report          TEXT
);

CREATE TABLE IF NOT EXISTS schema_registry (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  template        TEXT NOT NULL,
  created_at      REAL NOT NULL
);

-- 全文索引（外部内容表，rowid 对齐 memory_node）
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  label, gist, content='memory_node', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS trg_node_ai AFTER INSERT ON memory_node BEGIN
  INSERT INTO memory_fts(rowid, label, gist) VALUES (new.rowid, new.label, coalesce(new.gist,''));
END;
CREATE TRIGGER IF NOT EXISTS trg_node_ad AFTER DELETE ON memory_node BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, label, gist) VALUES ('delete', old.rowid, old.label, coalesce(old.gist,''));
END;
CREATE TRIGGER IF NOT EXISTS trg_node_au AFTER UPDATE ON memory_node BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, label, gist) VALUES ('delete', old.rowid, old.label, coalesce(old.gist,''));
  INSERT INTO memory_fts(rowid, label, gist) VALUES (new.rowid, new.label, coalesce(new.gist,''));
END;

INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')
  ON CONFLICT(key) DO UPDATE SET value='1';
