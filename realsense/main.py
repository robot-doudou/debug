"""LAN 文件浏览 (HTTP). 从当前目录起服务, 方便远程看 out/ 下抓帧结果.

默认 0.0.0.0:8001, 浏览器打开 http://<本机IP>:8001/ 即可.
用法:
    uv run main.py                  # 默认 0.0.0.0:8001
    uv run main.py -p 8080
    uv run main.py -b 127.0.0.1     # 仅本机
"""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer, test


def main():
    p = argparse.ArgumentParser(description="LAN 文件浏览")
    p.add_argument("-p", "--port", type=int, default=8001)
    p.add_argument("-b", "--bind", default="0.0.0.0")
    args = p.parse_args()
    test(
        HandlerClass=SimpleHTTPRequestHandler,
        ServerClass=ThreadingHTTPServer,
        port=args.port,
        bind=args.bind,
    )


if __name__ == "__main__":
    main()
