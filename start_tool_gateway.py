#!/usr/bin/env python3
"""Start the SteelMind gateway, wait until ready, then open its web UI."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
HOST = os.environ.get("STEELMIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("STEELMIND_PORT", "8000"))
BASE_URL = f"http://{HOST}:{PORT}"
STARTUP_TIMEOUT_SECONDS = 60


def gateway_is_ready() -> bool:
    try:
        connection = http.client.HTTPConnection(HOST, PORT, timeout=2)
        connection.request("GET", "/health")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        if response.status != 200 or payload.get("ok") is not True:
            return False

        connection = http.client.HTTPConnection(HOST, PORT, timeout=2)
        connection.request("GET", "/")
        page = connection.getresponse()
        is_agent_page = page.status == 200 and page.getheader("Content-Type", "").startswith("text/html")
        page.read()
        connection.close()
        return is_agent_page
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def open_agent() -> None:
    agent_url = BASE_URL + "/"
    print(f"SteelMind 网页已就绪：{agent_url}", flush=True)
    try:
        if not webbrowser.open_new_tab(agent_url):
            print("未能自动调用浏览器，请复制上方网址打开。", flush=True)
    except webbrowser.Error as exc:
        print(f"未能自动调用浏览器：{exc}；请复制上方网址打开。", flush=True)


def main() -> int:
    if not (BACKEND / "app.py").is_file():
        print(f"找不到网关入口：{BACKEND / 'app.py'}", file=sys.stderr)
        return 1

    if gateway_is_ready():
        print(f"检测到已有 SteelMind 网关运行于 {BASE_URL}，直接打开网页。", flush=True)
        open_agent()
        return 0

    command = [
        sys.executable, "-m", "uvicorn", "app:app", "--app-dir", str(BACKEND),
        "--host", HOST, "--port", str(PORT),
    ]
    print(f"正在启动 SteelMind 网关：{BASE_URL}", flush=True)
    process = subprocess.Popen(command, cwd=ROOT)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

    try:
        while time.monotonic() < deadline:
            if gateway_is_ready():
                open_agent()
                return process.wait()
            if process.poll() is not None:
                print(
                    f"网关进程已退出（代码 {process.returncode}）。请检查上方启动日志；"
                    "若提示端口被占用，请关闭占用该端口的旧服务。",
                    file=sys.stderr,
                )
                return process.returncode or 1
            time.sleep(0.5)

        print(f"等待网关就绪超时，请检查 {BASE_URL}/health。", file=sys.stderr)
        process.terminate()
        return 1
    except KeyboardInterrupt:
        print("正在停止 SteelMind 网关…", flush=True)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
