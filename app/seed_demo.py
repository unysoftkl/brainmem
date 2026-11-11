# -*- coding: utf-8 -*-
"""给桌面环境预置一批示例记忆（SQLite 单机库），方便直接试用。
产出：%LOCALAPPDATA%\\brainmem\\data\\brainmem.db
用法： .venv\\Scripts\\python.exe app\\seed_demo.py
"""
import os

from brainmem.config import load_config
from brainmem.interfaces.memory import Memory
from brainmem.storage.factory import make_storage

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "brainmem", "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "brainmem.db")

SEEDS = [
    "数学", "几何", "物理", "化学", "张三", "北京市", "清华大学",
    "圆规", "三角尺", "微积分", "番茄", "菜谱",
]
NOTES = [("买书记录", "张三在北京市海淀区买了三本书")]  # 带原文记忆（标题入库、原文冷存）
EDGES = [("数学", "几何"), ("数学", "微积分"), ("几何", "圆规"),
         ("几何", "三角尺"), ("张三", "北京市"), ("张三", "清华大学")]


def main():
    cfg = load_config(None)
    cfg.storage = "sqlite"
    cfg.sqlite_path = DB
    m = Memory(cfg, make_storage(cfg))
    # 写入唯一入口：AI 拆好的原子（不建边），再显式建边
    r = m.ingest(SEEDS, text=None)
    ids = {a["text"]: a["id"] for a in r["atoms"]}
    m.link_many([{"src": ids[a], "dst": ids[b], "relation": "ASSOCIATED"}
                 for a, b in EDGES])  # 连谁由 AI 决定，权重库给
    for title, content in NOTES:
        m.write_note(title, content)  # 带原文记忆（标题入库、原文冷存）
    print("seeded:", m.stats())
    print("db:", DB)
    m.close()


if __name__ == "__main__":
    main()
