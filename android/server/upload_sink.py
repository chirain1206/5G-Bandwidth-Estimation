#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上行带宽测试接收端 (Upload Sink)

与 Android 端 LoggingService.runUploadPhase() 配合使用：
App 会以 chunked 编码持续 POST 数据到本服务，本服务读取并丢弃数据，
实时打印接收速率，请求结束后返回 204 No Content。

用法:
    python3 upload_sink.py [port]

默认监听 0.0.0.0:8081，仅依赖 Python 标准库。
"""

import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8081


class UploadSinkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        """健康检查，确认服务存活"""
        body = b"upload sink ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """读取并丢弃上传的数据，统计实时吞吐量，返回 204 No Content"""
        received = 0
        start = time.monotonic()
        try:
            length = self.headers.get("Content-Length")
            if length is not None:
                # 定长 body
                remaining = int(length)
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    received += len(chunk)
            else:
                # chunked 传输 (Android setChunkedStreamingMode)
                while True:
                    size_line = self.rfile.readline()
                    if not size_line:
                        break
                    size = int(size_line, 16)
                    if size == 0:
                        self.rfile.readline()  # 消费最后的空行
                        break
                    data = self.rfile.read(size)
                    self.rfile.readline()     # 消费 chunk 末尾 CRLF
                    received += len(data)
        except (ConnectionError, OSError, ValueError):
            pass  # 客户端到时间主动断开，属于正常情况

        elapsed = time.monotonic() - start
        mbps = (received * 8) / (elapsed * 1e6) if elapsed > 0 else 0.0
        print("[%s] received %.2f MB in %.2fs (~%.2f Mbps)"
              % (time.strftime("%H:%M:%S"), received / 1e6, elapsed, mbps),
              flush=True)

        # Android 端期望 204 No Content
        self.send_response(204)
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # 关闭默认请求日志，只保留吞吐量统计输出


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), UploadSinkHandler)
    print("Upload sink listening on 0.0.0.0:%d (POST /sample_upload)" % PORT,
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye")
