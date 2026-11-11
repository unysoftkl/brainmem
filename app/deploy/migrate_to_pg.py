#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SQLite → PostgreSQL 迁移一键脚本（阶段6）。

用法：
  export BRAINMEM_PG_DSN=postgresql://brainmem:brainmem@127.0.0.1:5432/brainmem
  python deploy/migrate_to_pg.py --sqlite path/to/brainmem.db   [--tenant default]
先建 PG schema → 导出 SQLite → 导入 PG → 按事件对账（必须 0 误差）。
退出码 0 = 成功且 0 不一致；非 0 = 对账失败或异常。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.storage.sqlite.db import SqliteStorage  # noqa: E402
from brainmem.storage.migrate import export_sqlite, import_postgres, write_export  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="SQLite 数据库文件路径")
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--dump", default=None, help="可选：把导出 JSON 落盘路径")
    args = ap.parse_args()

    dsn = os.environ.get("BRAINMEM_PG_DSN")
    if not dsn:
        print("ERROR: 需设置 BRAINMEM_PG_DSN", file=sys.stderr)
        return 2

    src = SqliteStorage(args.sqlite)
    data = export_sqlite(src, args.tenant)
    src.close()
    print(f"exported: nodes={len(data['nodes'])} edges={len(data['edges'])} "
          f"events={len(data['events'])}")
    if args.dump:
        write_export(data, args.dump)
        print(f"dump written: {args.dump}")

    res = import_postgres(dsn, data)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    ok = res["mismatched"] == 0
    print("MIGRATION OK (0 mismatch)" if ok else "MIGRATION FAILED (mismatch>0)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
