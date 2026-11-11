# -*- coding: utf-8 -*-
"""验证文件库持久化：写入→关闭→重开→读取，权重/事件/版本都在。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.config import load_config
from brainmem.storage.sqlite.db import SqliteStorage
from brainmem.engine.memory_engine import MemoryEngine
from brainmem.interfaces.memory import Memory

path = os.path.join(tempfile.gettempdir(), "brainmem_persist_check.db")
if os.path.exists(path):
    os.remove(path)

cfg = load_config(None)
cfg.sqlite_path = path
st = SqliteStorage(path)
st.init_schema()
m = Memory(cfg, st, MemoryEngine(cfg, st))
r = m.write("持久化")
nid = r["id"]
m.close()

# 重开
st2 = SqliteStorage(path)
m2 = Memory(cfg, st2, MemoryEngine(cfg, st2))
got = m2.get(nid)
evs = st2.iter_events(nid)
print("reopened get:", got["label"], got["weight"], got["state"], "events:", len(evs))
assert got["label"] == "持久化"
assert len(evs) == 1
m2.close()
os.remove(path)
print("PERSISTENCE OK")
