from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, FileResponse
import os

# 大文件下载路径（测试文件生成方法见 android/server/nginx_download.conf）
# export BIG_BIN_PATH="/var/www/html/big.bin"   (Linux/macOS)
# $env:BIG_BIN_PATH="C:\nginx\html\big.bin"     (Windows PowerShell)
BIG_BIN_PATH = os.environ.get("BIG_BIN_PATH", "/var/www/html/big.bin")

app = FastAPI()


@app.get("/connection_test")
def health():
    return PlainTextResponse("Server is connected.\n")


@app.post("/sample_upload")
async def upload_sink(request: Request):
    async for _ in request.stream():
        pass
    return Response(status_code=204)


@app.get("/sample_download")
def big_file():
    return FileResponse(BIG_BIN_PATH, media_type="application/octet-stream")
