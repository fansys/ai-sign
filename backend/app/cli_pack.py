"""打包 cli/ 为免安装 zip 供面板下载，并写入 signcli/_default.py 内置服务地址。"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
_MAIN = "from signcli.cli import main\nraise SystemExit(main())\n"


def normalize_server(url: str) -> str:
    u = urlsplit((url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc or any(c in url for c in " \t\r\n\"'\\"):
        raise ValueError("无效的服务地址")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


_SH = """#!/bin/sh
d=$(cd "$(dirname "$0")" && pwd)
export PYTHONPATH="$d${PYTHONPATH:+:$PYTHONPATH}"
if command -v python3 >/dev/null 2>&1; then exec python3 -m signcli "$@"; fi
exec python -m signcli "$@"
"""
_BAT = """@echo off
setlocal
set "PYTHONPATH=%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m signcli %*) else (python -m signcli %*)
exit /b %errorlevel%
"""
_README = """sign-cli（免安装，需要 Python 3.9+）

  macOS / Linux:  ./sign-cli.sh            （首次若无执行权限：chmod +x sign-cli.sh）
  Windows:        sign-cli.bat

常用命令： (无参数) 交互提交 | scan 只列出发现的登录态 | push -y 全部提交 | -h 帮助

服务地址与 apikey 已写入同目录 sign.conf（仅有“提交凭证”权限，面板「设置」里可删除/重新生成）。
请勿把本目录分享给他人。提取 Qoder 登录态需另装 cryptography：pip install cryptography
"""


def _entry(z: zipfile.ZipFile, name: str, data: str, mode: int):
    zi = zipfile.ZipInfo(f"sign-cli/{name}", date_time=time.localtime()[:6])
    zi.external_attr, zi.compress_type = mode << 16, zipfile.ZIP_DEFLATED
    z.writestr(zi, data)


def build_zip(server: str, apikey: str) -> bytes:
    """免安装 zip：signcli/ + sign-cli.sh/.bat + sign.conf（内置服务地址与 apikey）。"""
    server = normalize_server(server)
    pkg = CLI_DIR / "signcli"
    if not pkg.is_dir():
        raise FileNotFoundError("服务端未包含 cli 目录")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pkg.rglob("*.py")):
            if "__pycache__" not in f.parts:
                z.write(f, f"sign-cli/signcli/{f.relative_to(pkg).as_posix()}")
        _entry(z, "sign-cli.sh", _SH, 0o100755)
        _entry(z, "sign-cli.bat", _BAT.replace("\n", "\r\n"), 0o100644)
        _entry(z, "sign.conf", f"[server]\nurl = {server}\napikey = {apikey}\n", 0o100600)
        _entry(z, "README.txt", _README, 0o100644)
    return buf.getvalue()
