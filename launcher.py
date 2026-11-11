# -*- coding: utf-8 -*-
"""仿脑记忆数据库 · 桌面启动器（Python 菜单，规避 cmd 批处理的中文/路径问题）。

由 run.bat 用 venv 的 python 启动。
- 主菜单：输 1-5 执行，0 退出。
- 命令行模式：输子命令（write/search/stats/explain…）；输 q 回菜单；
  也可直接输数字 1-5 切到对应功能（免得用户以为在菜单里）。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE, "app")
PY = sys.executable
DB = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                  "brainmem", "data", "brainmem.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)

ENV = dict(os.environ)
ENV["BRAINMEM_DB"] = DB
ENV["PYTHONIOENCODING"] = "utf-8"
ENV["PYTHONUTF8"] = "1"


def run(args, title=""):
    if title:
        print("\n" + "=" * 56 + f"\n{title}\n" + "=" * 56)
    try:
        subprocess.run([PY, *args], cwd=APP, env=ENV, check=False)
    except KeyboardInterrupt:
        print("\n[已中断]")
    except Exception as e:  # noqa: BLE001
        print(f"[执行出错] {type(e).__name__}: {e}")


def self_check():
    run(["-c", "import brainmem,fastmcp,psycopg,jieba,igraph;"
              "print('[deps] OK, brainmem', brainmem.__version__)"], "1) 依赖检查")
    run(["-m", "pytest", "-q"], "2) 运行 84 个测试")
    run(["seed_demo.py"], "3) 预置示例数据")


def deploy_check():
    """环境与部署自检（调用 deploy.py --check）。"""
    try:
        subprocess.run([PY, os.path.join(BASE, "deploy.py"), "--check"], cwd=BASE, env=ENV)
    except Exception as e:  # noqa: BLE001
        print(f"[执行出错] {type(e).__name__}: {e}")


def show_menu():
    print("\n" + "=" * 56)
    print("            仿 脑 记 忆 数 据 库")
    print("=" * 56)
    print("  [1] 自检与初始化（依赖检查 + 84 测试 + 预置示例数据）")
    print("  [2] 演示 Demo（写入→衰减→强化→解释→对账）")
    print("  [3] 命令行 CLI（ingest / search / stats / explain）")
    print("  [4] 启动 MCP 服务（供 AI 客户端接入 :8770，Ctrl+C 停止）")
    print("  [5] 查看说明 README")
    print("  [6] 查看全部记忆 + 权重（列表）")
    print("  [7] 查看记忆关系图（生成并打开交互图）")
    print("  [8] 查看一条记忆的全部数据（需输入 id）")
    print("  [9] 部署/环境自检（deploy.py --check）")
    print("  [0] 退出")
    print("=" * 56)


def inspect_one():
    nid = input("请输入记忆 id（可用 [6] 列表或 [7] 关系图里点节点复制）：").strip()
    if not nid:
        return
    run(["-m", "brainmem.interfaces.cli", "inspect", nid], "记忆全部数据")


def open_graph():
    # 生成到桌面并自动打开（桌面不存在则放本目录）
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desk):
        outp = os.path.join(desk, "brainmem_关系图.html")
    else:
        outp = os.path.join(BASE, "relationship.html")
    run(["-m", "brainmem.interfaces.cli", "graph", "--out", outp, "--open"], "关系图")


def dispatch(ch):
    """执行一个菜单动作。返回 False=退出，True=继续。"""
    if ch == "1":
        self_check()
    elif ch == "2":
        run(["demo.py"], "演示 Demo")
    elif ch == "3":
        cli_repl()
    elif ch == "4":
        print("\n正在启动 MCP 服务…（Ctrl+C 停止并回到菜单）")
        run(["-m", "brainmem.interfaces.mcp_server", "--transport", "http"], "MCP 服务 :8770")
    elif ch == "5":
        try:
            os.startfile(os.path.join(BASE, "README.md"))  # type: ignore[attr-defined]
        except Exception:
            print("请手动打开:", os.path.join(BASE, "README.md"))
    elif ch == "6":
        run(["-m", "brainmem.interfaces.cli", "list"], "全部记忆（含权重/状态/连接数）")
    elif ch == "7":
        open_graph()
    elif ch == "8":
        inspect_one()
    elif ch == "9":
        deploy_check()
    elif ch == "0":
        return False
    else:
        print("无效输入，请输入 0-9。")
    return True


def cli_repl():
    print("\n" + "=" * 56)
    print("命令行模式（操作你自己的库）：直接输入子命令，例如")
    print("  ingest 六点钟起床差点迟到,吃了两个包子出门")
    print("  search 起床 --top-k 3")
    print("  stats")
    print("  explain <某条id>")
    print("输 q 返回菜单（也可直接输 0-9 切换功能）")
    print("=" * 56)
    while True:
        try:
            line = input("brainmem> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if line == "":
            continue
        if line.lower() in ("q", "quit", "exit"):
            return
        # 命令行里直接输菜单序号 → 切到对应功能
        if line in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
            if not dispatch(line):
                raise SystemExit(0)
            continue
        run(["-m", "brainmem.interfaces.cli", *line.split()])


def menu():
    while True:
        show_menu()
        try:
            ch = input("请输入序号并回车：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not dispatch(ch):
            return


if __name__ == "__main__":
    try:
        menu()
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"\n[启动器异常] {type(e).__name__}: {e}")
        input("按回车退出...")
