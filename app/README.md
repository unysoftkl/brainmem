# brainmem · 仿脑记忆数据库（阶段 0–6）

以「权重生命周期 + 事件溯源 + 图联想」为核心的 AI 长期记忆内核，可通过 MCP 协议被任意支持 MCP 的 AI 客户端调用。

## 安装

```bash
pip install -e .                 # 基础（SQLite 单机 + MCP）
pip install -e ".[postgres]"     # + PostgreSQL 存储
pip install -e ".[graph]"        # + Leiden 社区检测（缺省退回 networkx Louvain）
pip install -e ".[dev]"          # + 测试
```

## 快速开始（SQLite 单机）

```bash
python -m pytest -q                       # 运行测试
python demo.py                            # 端到端演示：写入→衰减→强化→解释→对账
python -m brainmem.interfaces.cli write "数学"
python -m brainmem.interfaces.cli search "数学"
python -m brainmem.interfaces.mcp_server  # 启动 MCP Server（stdio）
```

## 生产部署（PostgreSQL + pgvector）

见 `deploy/README.md`：一键起库（Docker）、迁移、压测、备份恢复。

## 目录

```
src/brainmem/
  core/       权重引擎（整数 bp）·解析解衰减·强化·状态机·边权·模型·枚举
  storage/    Storage 协议 · SQLite · PostgreSQL · 迁移 · 工厂 · migrations/
  engine/     写入管线·检索·巩固合并·事件复算·编排
  services/   嵌入·相似度·图·分块·实体·压缩·冷存·合并·监控
  interfaces/ Memory 门面 · MCP Server · CLI
tests/        unit / property / integration（73 用例）
bench/        各阶段验收脚本
deploy/       PostgreSQL 部署工具包
```
