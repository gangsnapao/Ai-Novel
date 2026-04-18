"""
AI 小说生成平台 — 开发服务器启动脚本

同时启动前端 (Vite :5173) 和后端 (Uvicorn :8000)，Ctrl+C 统一停止。

用法:
    python start.py                     # 启动前后端
    python start.py --port 9000         # 后端端口 (前端代理自动同步)
    python start.py --host 0.0.0.0      # 后端监听地址
    python start.py --no-reload         # 关闭后端热重载
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _kill_tree(pid: int) -> None:
    """终止进程及其全部子进程。"""
    if sys.platform == "win32":
        subprocess.call(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        import signal as _sig

        try:
            os.killpg(os.getpgid(pid), _sig.SIGTERM)
        except ProcessLookupError:
            pass


def main() -> None:
    root = Path(__file__).resolve().parent
    backend_dir = root / "backend"
    frontend_dir = root / "frontend"

    for label, d in [("backend", backend_dir), ("frontend", frontend_dir)]:
        if not d.is_dir():
            print(f"错误: 未找到 {label} 目录: {d}", file=sys.stderr)
            sys.exit(1)

    # ── 后端虚拟环境 ──
    venv_python = backend_dir / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not venv_python.is_file():
        print(f"错误: 未找到后端虚拟环境: {venv_python}", file=sys.stderr)
        sys.exit(1)

    # ── npm ──
    if not shutil.which("npm"):
        print("错误: 未找到 npm，请安装 Node.js", file=sys.stderr)
        sys.exit(1)

    if not (frontend_dir / "node_modules").is_dir():
        print("正在安装前端依赖 (npm install) ...\n")
        if subprocess.call("npm install", cwd=str(frontend_dir), shell=True) != 0:
            print("npm install 失败", file=sys.stderr)
            sys.exit(1)

    # ── 参数 ──
    backend_port = os.environ.get("PORT", "8000")
    backend_host = "127.0.0.1"
    reload_on = True

    it = iter(sys.argv[1:])
    for arg in it:
        if arg == "--port":
            backend_port = next(it, "8000")
        elif arg == "--host":
            backend_host = next(it, "127.0.0.1")
        elif arg == "--no-reload":
            reload_on = False
        else:
            print(f"未知参数: {arg}", file=sys.stderr)
            print("用法: python start.py [--port PORT] [--host HOST] [--no-reload]", file=sys.stderr)
            sys.exit(1)

    frontend_port = os.environ.get("VITE_DEV_PORT", "5173")

    # ── 命令 ──
    backend_cmd = [
        str(venv_python), "-m", "uvicorn",
        "app.main:app",
        "--host", backend_host,
        "--port", backend_port,
    ]
    if reload_on:
        backend_cmd.append("--reload")

    # 后端端口变化时同步给 vite 代理 (vite.config.ts 读 VITE_API_PROXY_TARGET)
    frontend_env = {**os.environ, "VITE_API_PROXY_TARGET": f"http://{backend_host}:{backend_port}"}

    print(f"  后端  http://{backend_host}:{backend_port}  (reload={'ON' if reload_on else 'OFF'})")
    print(f"  前端  http://127.0.0.1:{frontend_port}")
    print("  Ctrl+C 停止全部\n")

    procs: list[subprocess.Popen] = []
    try:
        procs.append(subprocess.Popen(backend_cmd, cwd=str(backend_dir)))
        procs.append(subprocess.Popen("npm run dev", cwd=str(frontend_dir), shell=True, env=frontend_env))

        # 任一进程退出则结束
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                _kill_tree(p.pid)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
