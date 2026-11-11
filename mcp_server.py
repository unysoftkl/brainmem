# -*- coding: utf-8 -*-
"""brainmem MCP 服务：单实例看守 + 固定库路径（供 DSH / 任意 MCP 客户端接入）。

- 已在监听则直接退出（保证只有一个实例、一份库）。
- 否则用固定 config.json 启动 streamable-http 服务，监听 127.0.0.1:8770。
启动命令（venv 的 python）： .venv\\Scripts\\python.exe mcp_server.py
"""
import os
import socket
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE, "app")
CONFIG = os.path.join(BASE, "config.json")
PY = sys.executable
PORT = 8770
HOST = "127.0.0.1"


def is_up(host=HOST, port=PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def main() -> int:
    if is_up():
        print(f"[brainmem] MCP 已在 {HOST}:{PORT} 运行，复用现有实例。")
        return 0
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["BRAINMEM_CONFIG"] = CONFIG
    log_path = os.path.join(BASE, "mcp_server.log")
    print(f"[brainmem] 启动 MCP 服务 {HOST}:{PORT}（config={CONFIG}）")
    # 子进程输出重定向到日志文件（隐藏窗口/无控制台时 stdio 可能无效）
    logf = open(log_path, "a", encoding="utf-8")
    logf.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    logf.flush()
    proc = subprocess.Popen(
        [PY, "-m", "brainmem.interfaces.mcp_server", "--transport", "http"],
        cwd=APP, env=env, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
    )
    # 等端口就绪（最多 60 秒），随后常驻
    for _ in range(120):
        if is_up():
            print(f"[brainmem] 就绪：http://{HOST}:{PORT}/mcp")
            break
        if proc.poll() is not None:
            print("[brainmem] 启动失败，退出码", proc.returncode, "，详见", log_path)
            logf.close()
            return proc.returncode or 1
        time.sleep(0.5)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
