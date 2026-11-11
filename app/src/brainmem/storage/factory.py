"""存储工厂。"""
from brainmem.config import Config
from brainmem.storage.sqlite.db import SqliteStorage


def make_storage(cfg: Config):
    if cfg.storage == "sqlite":
        st = SqliteStorage(cfg.sqlite_path)
        st.init_schema()
        return st
    if cfg.storage == "postgres":
        from brainmem.storage.postgres.db import PostgresStorage

        st = PostgresStorage()  # DSN 从 BRAINMEM_PG_DSN 读取
        st.init_schema()
        return st
    raise ValueError(f"unsupported storage: {cfg.storage}")
