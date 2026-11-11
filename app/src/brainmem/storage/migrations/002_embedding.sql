-- 002_embedding.sql · 阶段2：向量表（用于语义召回）
CREATE TABLE IF NOT EXISTS memory_embedding (
  node_id  TEXT PRIMARY KEY REFERENCES memory_node(id),
  tenant_id TEXT NOT NULL DEFAULT 'default',
  dim      INTEGER NOT NULL,
  vector   BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emb_tenant ON memory_embedding(tenant_id);

INSERT INTO schema_meta(key, value) VALUES ('schema_version', '2')
  ON CONFLICT(key) DO UPDATE SET value='2';
