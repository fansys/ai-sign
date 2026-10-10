"""打包 cli/ 为 zip 供面板下载，并写入 signcli/_default.py 内置服务地址。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

CLI_DIR = Path(__file__).resolve().parents[2] / "cli"
_INCLUDE = ("pyproject.toml",)


def normalize_server(url: str) -> str:
    u = urlsplit((url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc or any(c in url for c in " \t\r\n\"'\\"):
        raise ValueError("无效的服务地址")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


def build_zip(server: str) -> bytes:
    server = normalize_server(server)
    if not CLI_DIR.is_dir():
        raise FileNotFoundError("服务端未包含 cli 目录")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in _INCLUDE:
            z.write(CLI_DIR / name, f"sign-cli/{name}")
        for f in sorted((CLI_DIR / "signcli").rglob("*.py")):
            if f.name != "_default.py" and "__pycache__" not in f.parts:
                z.write(f, f"sign-cli/{f.relative_to(CLI_DIR).as_posix()}")
        z.writestr("sign-cli/signcli/_default.py", f"SERVER_URL = {server!r}\n")
        z.writestr("sign-cli/README.txt",
                   f"安装：pip install ./sign-cli   （或 uv tool install ./sign-cli）\n"
                   f"已内置服务地址：{server}\n"
                   f"配置 apikey：运行 sign-cli init（面板 → 设置 创建 API Token）\n")
    return buf.getvalue()
