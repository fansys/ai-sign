"""打包 cli/ 为单文件 .pyz 供面板下载，并写入 signcli/_default.py 内置服务地址。"""
from __future__ import annotations

import io
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


def build_pyz(server: str) -> bytes:
    """单文件可执行 zipapp（`python3 sign-cli.pyz` 或 chmod +x 后直接运行），已内置服务地址。"""
    server = normalize_server(server)
    pkg = CLI_DIR / "signcli"
    if not pkg.is_dir():
        raise FileNotFoundError("服务端未包含 cli 目录")
    buf = io.BytesIO(b"#!/usr/bin/env python3\n")
    buf.seek(0, io.SEEK_END)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("__main__.py", _MAIN)
        for f in sorted(pkg.rglob("*.py")):
            if f.name != "_default.py" and "__pycache__" not in f.parts:
                z.write(f, f"signcli/{f.relative_to(pkg).as_posix()}")
        z.writestr("signcli/_default.py", f"SERVER_URL = {server!r}\n")
    return buf.getvalue()
