-- 004_wide_label.sql · 放宽标签字数上限 10 -> 100
-- 背景：AI 自行决定简写到几个字，记忆库只按字数给权重；不再死限 10 字。
-- memory_node 的 char_len 有 CHECK(1..10)，SQLite 无法直接改约束，需重建表。
-- 注意：由 db.py 在检测到旧约束时才执行本脚本（幂等保护）。

CREATE TABLE IF NOT EXISTS memory_node_new (
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

-- 保留 rowid（FTS 外部内容表按 rowid 对齐）
INSERT INTO memory_node_new
  (rowid, id, tenant_id, label, label_norm, char_len, kind, weight_bp, stability,
   peak_bp, state, fidelity, gist, verbatim_ref, fingerprint, salience, born_at,
   last_touch_at, source_kind, source_id, deleted_at)
SELECT
   rowid, id, tenant_id, label, label_norm, char_len, kind, weight_bp, stability,
   peak_bp, state, fidelity, gist, verbatim_ref, fingerprint, salience, born_at,
   last_touch_at, source_kind, source_id, deleted_at
FROM memory_node;

DROP TABLE memory_node;
ALTER TABLE memory_node_new RENAME TO memory_node;

CREATE INDEX IF NOT EXISTS idx_node_tenant_state ON memory_node(tenant_id, state);
CREATE INDEX IF NOT EXISTS idx_node_weight       ON memory_node(tenant_id, weight_bp);
CREATE INDEX IF NOT EXISTS idx_node_fp           ON memory_node(tenant_id, fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS uq_node_norm   ON memory_node(tenant_id, label_norm);

-- 重建 FTS 触发器（DROP TABLE 会连带删掉）
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

INSERT INTO schema_meta(key, value) VALUES ('schema_version', '4')
  ON CONFLICT(key) DO UPDATE SET value='4';
