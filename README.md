# brainmem 记忆库 · 本机部署与使用

已在本机部署好。**双击桌面快捷方式「仿脑记忆数据库」** 即可使用（或双击本目录 `run.bat`）。

## 一、部署（换机器 / 首次安装）

交付包已自带 `.venv` 与全部依赖，**拷过去双击 `run.bat` 即可用**。若要在新机器重建环境或修复：

```bat
:: 环境自检（默认）——检查 Python / venv / 依赖 / 包 / 数据 / DSH 接入
python deploy.py --check

:: 修复：缺 .venv 或缺依赖时，自动创建虚拟环境并安装依赖
python deploy.py --repair

:: 自动接入 DSH（把 brainmem-mcp 写进 ~/.dsh/profiles/desktop/cordis.patch.yml）
python deploy.py --register-dsh
```

- `deploy.py` 是自包含的：没有 venv 时可用**系统 Python** 运行 `--repair`。
- 自检退出码 0 = 全部通过；任何 FAIL 会提示修复命令。
- 菜单里的 `[9] 部署/环境自检` 等价于 `python deploy.py --check`。

## 二、目录

```
Desktop\brainmem\
├── run.bat        ← 启动入口（双击）
├── deploy.py      ← 部署与环境工具（--check / --repair / --register-dsh）
├── launcher.py    ← 菜单程序（演示/CLI/服务/自检）
├── mcp_server.py  ← MCP 服务（HTTP 方式手动起时用）
├── config.json    ← 固定配置（库路径钉死到 %LOCALAPPDATA%\brainmem\data\brainmem.db）
├── skills\        ← brainmem-upload 技能（AI 上传流程）
├── .venv\         ← 独立 Python 环境（依赖已装齐）
├── app\           ← 源码与脚本
└── README.md      ← 本文件
```

数据文件：`%LOCALAPPDATA%\brainmem\data\brainmem.db`（SQLite 单文件，删除即清空）。

## 三、怎么看「记忆之间的联系 / 权重 / 一条记忆的全部数据」

| 想看什么 | 菜单 | 命令行 |
|---|---|---|
| **所有记忆 + 各自权重/状态/连接数** | `[6]` | `cli list` |
| **关系图（谁和谁相连、边权多粗）** | `[7]` | `cli graph --out xxx.html --open` |
| **一条记忆的全部数据 + 所有关联** | `[8]` 输 id | `cli inspect <id>` |

- **关系图**是可交互 HTML（桌面 `brainmem_关系图.html`）：节点=记忆，颜色=状态（绿FULL/蓝NORMAL/橙CONDENSED/红VESTIGE），大小=连接数；连线=关联，粗细=边权；悬停看详情、点击复制 id。
- **`inspect`** 给出：字段全量、当前权重（含 bp）、状态、稳固度、剩余寿命、指纹、来源、所有关联边（对端/边权/共激活）、完整事件流。

## 四、启动后菜单

```
[1] 自检与初始化（依赖检查 + 84 测试 + 预置示例数据）
[2] 演示 Demo（写入→衰减→强化→解释→对账）
[3] 命令行 CLI（ingest / search / stats / explain）
[4] 启动 MCP 服务（HTTP，供不支持 stdio 的客户端临时接入 :8770）
[5] 查看说明 README
[6] 查看全部记忆 + 权重（列表）
[7] 查看记忆关系图（生成并打开交互图）
[8] 查看一条记忆的全部数据（需输入 id）
[9] 部署/环境自检（deploy.py --check）
[0] 退出
```

## 五、已接入 DeepSeek Harness（DSH）

已通过 DSH 的 `@deepseek-ai/dsh-mcp-client` 插件接入（**stdio 方式**，DSH 按需自动拉起，无需常驻端口）：
- 配置：`~/.dsh/profiles/desktop/cordis.patch.yml` 里的 `brainmem-mcp`
- 重启 DSH 后，对话里应出现 15 个 `mcp__brainmem__*` 工具（写入用 `memory_ingest`）
- **跨对话共享**：所有会话读同一个 `brainmem.db`，新对话也能查到旧记忆
- 换机器可用 `python deploy.py --register-dsh` 自动登记

## 六、职责边界（重要）

**记忆库只做一件事：权重** —— 给记忆加权重、算权重衰减、权重清零自动遗忘（+ 边的权重规则）。
**其它全归 AI**：拆分、简写、录入、**建立连接**。

- **写入**：`memory_ingest(atoms, text?, note_title?)` —— AI 把内容拆成若干字原子后批量入库（字数自定，不建边）。
- **连接**：`memory_link` / `memory_link_many` —— 连谁由 AI 判断，权重由库给（不传 weight）。
- **用进废退（自动强化）**：没有"睡觉整理"机制了。**每次检索/取用记忆，命中的记忆自动 +权重、
  走过的连接自动 +权重并记一次共激活**（`memory_search` / `memory_get` 默认 `use=True`）。
  多用就记牢、不用就衰减。想额外巩固某条可 `memory_reinforce`。
- **简写 / 合并**：需要精简时 AI 主动 `memory_simplify`（压成更短内核）/ `memory_merge`（合并，
  需先有强连接：边权≥8、共激活≥5、寿命≥365天）。
- **遗忘**：权重衰减到 0 自动物理删除（也可 `memory_forget` 手动删）。
- 配套 skill：`skills/brainmem-upload`（拆分简写/建连接/用进废退的完整提示词）。

## 七、跨对话共享的前提（重要）

记忆库是**一个 SQLite 文件**，谁连同一个文件就共享同一批记忆。本环境已把路径钉死为
`%LOCALAPPDATA%\brainmem\data\brainmem.db`（`config.json` + DSH 配置都指向它）。

## 八、接入其它 MCP 客户端

- stdio 命令：`...\brainmem\.venv\Scripts\python.exe -m brainmem.interfaces.mcp_server`
  （工作目录 `...\brainmem\app`，环境变量 `BRAINMEM_CONFIG=...\brainmem\config.json`）
- HTTP（先手动起 `mcp_server.py`）：`http://127.0.0.1:8770/mcp`

## 九、设计说明：为什么没有“夜间加固 / 全局归一化”

本库**不提供** `global_normalize`（全局乘性归一：把所有记忆按同一系数放大、
把整体均值拉回 4.0）。`normalize` 命令行与 `Memory.normalize` 均已移除。

原因：
1. 它会把**本该遗忘的条目**一起“复活”，违背“用进废退”的核心设计；
2. 人脑睡眠是**选择性巩固**（显著、近期、强关联的先巩固），不是等比例放大；
3. “把平均权重维持在 4.0”没有任何生理学依据，纯属工程兜底。

**保留的巩固能力**：`consolidate`（社区检测 + 软合并）。它的前置条件是强连接
（边权 ≥ 8、共激活 ≥ 5、边寿命 ≥ 365 天），只合并“真正反复用过”的记忆，
**不会改变整体权重分布**。

**想让某条记忆更牢，正确做法**（都是 AI 主动动作，库只算权重）：
- `memory_reinforce(node_id)` —— 强化一条（约 +1.9，并提升稳固度，衰减更慢）
- `memory_feedback(node_id, signal="positive")` —— “这条有用”，连带加强其邻边
- `memory_simplify(node_id, new_text)` —— 压成更短内核（字越少，初始权重越高）
- 隔 5 分钟以上重复 `memory_ingest` 同一句 —— 自动识别为重复并强化旧节点

## 十、常见问题

- 自检不过：`python deploy.py --check` 看哪一项 FAIL，按 `python deploy.py --repair`。
- 想清空记忆：删 `%LOCALAPPDATA%\brainmem\data\brainmem.db`，或菜单选 1。
- 卸载：删掉 `Desktop\brainmem`；数据库在 `%LOCALAPPDATA%`，需一并删除。
- 记忆越来越弱怎么办：用 `memory_reinforce` / `memory_feedback` 主动巩固（见第九节）。
