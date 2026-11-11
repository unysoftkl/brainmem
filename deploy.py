# -*- coding: utf-8 -*-
"""brainmem 部署与环境工具（自包含，可在缺依赖时用系统 Python 运行）。

用法（在交付包根目录）：
  python deploy.py            # 环境自检（默认）
  python deploy.py --check    # 同上
  python deploy.py --repair   # 缺 venv/依赖时自动创建并安装
  python deploy.py --register-dsh  # 把 brainmem MCP 接入 DSH（写 cordis.patch.yml）

检查项：
  1. Python 版本 >= 3.11
  2. .venv 存在且解释器可运行
  3. 关键依赖可 import（pydantic/numpy/typer/fastmcp/jieba …）
  4. app/src 可导入 brainmem
  5. 数据目录可写、SQLite schema 可初始化、config.json 可用
  6. （可选）DSH 是否已登记 brainmem-mcp
退出码 0 = 全部通过；1 = 有失败项。
"""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE, "app")
VENV = os.path.join(BASE, ".venv")
VPY = os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")
CONFIG = os.path.join(BASE, "config.json")

REQUIRED = ["pydantic", "numpy", "typer", "yaml", "fastmcp", "jieba", "ulid"]
OPTIONAL = ["psycopg", "igraph", "leidenalg", "networkx"]

PASS, FAIL, WARN = "[PASS]", "[FAIL]", "[WARN]"
_fails = []


def ok(name, detail=""):
    print(f"{PASS} {name}" + (f"  ({detail})" if detail else ""))


def bad(name, detail=""):
    _fails.append(name)
    print(f"{FAIL} {name}" + (f"  ({detail})" if detail else ""))


def warn(name, detail=""):
    print(f"{WARN} {name}" + (f"  ({detail})" if detail else ""))


def check_python_version():
    v = sys.version_info
    if v >= (3, 11):
        ok("Python 版本", f"{v.major}.{v.minor}.{v.micro}")
    else:
        bad("Python 版本", f"需 >=3.11，当前 {v.major}.{v.minor}")


def check_venv():
    if os.path.exists(VPY):
        try:
            out = subprocess.run([VPY, "-c", "import sys;print(sys.version.split()[0])"],
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0:
                ok("虚拟环境 .venv", out.stdout.strip())
            else:
                bad("虚拟环境 .venv", out.stderr.strip()[:80])
        except Exception as e:  # noqa: BLE001
            bad("虚拟环境 .venv", str(e)[:80])
    else:
        bad("虚拟环境 .venv", f"缺失：{VPY}")


def _run_in_venv(code: str):
    return subprocess.run([VPY, "-c", code], cwd=APP, capture_output=True, text=True, timeout=60)


def check_deps():
    if not os.path.exists(VPY):
        bad("关键依赖", "无 venv，跳过（先 --repair）")
        return
    missing = []
    for mod in REQUIRED:
        r = _run_in_venv(f"import {mod}")
        if r.returncode != 0:
            missing.append(mod)
    if missing:
        bad("关键依赖", "缺失: " + ", ".join(missing))
    else:
        ok("关键依赖", ", ".join(REQUIRED))
    missing_opt = [m for m in OPTIONAL if _run_in_venv(f"import {m}").returncode != 0]
    if missing_opt:
        warn("可选依赖", "缺失(不影响核心): " + ", ".join(missing_opt))
    else:
        ok("可选依赖", ", ".join(OPTIONAL))


def check_package():
    if not os.path.exists(VPY):
        bad("brainmem 包", "无 venv")
        return
    r = _run_in_venv("import brainmem;print(brainmem.__version__)")
    if r.returncode == 0:
        ok("brainmem 包可导入", "v" + r.stdout.strip())
    else:
        bad("brainmem 包可导入", r.stderr.strip()[:120])


def check_data():
    if not os.path.exists(VPY):
        bad("数据/配置", "无 venv")
        return
    if not os.path.exists(CONFIG):
        bad("配置文件", f"缺失：{CONFIG}")
        return
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        ok("配置文件", f"storage={cfg.get('storage')} path={cfg.get('sqlite_path')}")
    except Exception as e:  # noqa: BLE001
        bad("配置文件解析", str(e)[:80])
        return
    code = (
        "from brainmem.config import load_config;"
        "from brainmem.storage.factory import make_storage;"
        "cfg=load_config(r'" + CONFIG + "');"
        "st=make_storage(cfg);"
        "print('schema ok, nodes=', st.count_nodes(cfg.tenant));"
        "st.close()"
    )
    r = _run_in_venv(code)
    if r.returncode == 0:
        ok("数据目录/schema", r.stdout.strip())
    else:
        bad("数据目录/schema", r.stderr.strip()[-160:])


def _dsh_cordis_path():
    home = os.path.expanduser("~")
    return os.path.join(home, ".dsh", "profiles", "desktop", "cordis.patch.yml")


def check_dsh(verbose=True):
    p = _dsh_cordis_path()
    if not os.path.exists(p):
        if verbose:
            warn("DSH 接入", "未找到 cordis.patch.yml（非必需）")
        return False
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    if "brainmem-mcp" in txt:
        ok("DSH 已登记 brainmem-mcp", p)
        return True
    warn("DSH 未登记 brainmem-mcp", "可用 --register-dsh 自动接入")
    return False


def repair():
    print("== 修复模式 ==")
    if not os.path.exists(VPY):
        print("创建虚拟环境 .venv …")
        r = subprocess.run([sys.executable, "-m", "venv", VENV])
        if r.returncode != 0:
            print(f"{FAIL} 创建 venv 失败")
            return 1
    print("安装依赖（app 可编辑安装 + 可选 extras）…")
    reqs = ["-e", APP + "[postgres,graph,dev]"]
    r = subprocess.run([VPY, "-m", "pip", "install", "--upgrade", "pip"], capture_output=True, text=True)
    r = subprocess.run([VPY, "-m", "pip", "install", *reqs], cwd=BASE)
    if r.returncode != 0:
        print(f"{FAIL} 依赖安装失败（可尝试联网后重试）")
        return 1
    print(f"{PASS} 依赖安装完成")
    return 0


def register_dsh():
    p = _dsh_cordis_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    block = f"""
# ===== brainmem MCP（stdio，DSH 按需拉起）=====
- insert:
    - id: brainmem-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: brainmem
        transport: stdio
        command: '{VPY}'
        args: [ '-m', 'brainmem.interfaces.mcp_server' ]
        env:
          BRAINMEM_CONFIG: '{CONFIG}'
          PYTHONUTF8: '1'
          PYTHONIOENCODING: 'utf-8'
        cwd: '{APP}'
        toolCallTimeoutMs: 60000
        failOnStartupError: false
"""
    existing = ""
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            existing = f.read()
    if "brainmem-mcp" in existing:
        print(f"{PASS} 已登记，跳过（{p}）")
        return 0
    with open(p, "a", encoding="utf-8") as f:
        f.write(block)
    print(f"{PASS} 已写入 {p}；重启 DSH 后生效。")
    return 0


def main(argv):
    if "--repair" in argv:
        return repair()
    if "--register-dsh" in argv:
        return register_dsh()
    print("=" * 56)
    print("        brainmem 部署与环境自检")
    print("=" * 56)
    check_python_version()
    check_venv()
    check_deps()
    check_package()
    check_data()
    check_dsh()
    print("=" * 56)
    if _fails:
        print(f"❌ {len(_fails)} 项失败：{_fails}")
        print("   修复：python deploy.py --repair")
        return 1
    print("✅ 环境自检全部通过，可以正常使用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
