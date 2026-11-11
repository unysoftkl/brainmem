-- 003_merge.sql · 阶段4：软合并快照（支持一键回滚）
CREATE TABLE IF NOT EXISTS merge_snapshot (
  batch_id      TEXT NOT NULL,
  parent_id     TEXT NOT NULL,
  member_id     TEXT NOT NULL,
  old_weight_bp INTEGER NOT NULL,
  created_at    REAL NOT NULL,
  PRIMARY KEY (batch_id, parent_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_merge_batch ON merge_snapshot(batch_id);

INSERT INTO schema_meta(key, value) VALUES ('schema_version', '3')
  ON CONFLICT(key) DO UPDATE SET value='3';
