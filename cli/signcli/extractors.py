"""从本机发现并读取登录态（macOS 优先，兼容 Windows）。只读，不打印 token。
原则：能在服务端解析的一律原样上传（Trae/WorkBuddy）；
唯独 Qoder 的密钥只能在本机取到（Windows DPAPI / macOS 钥匙串），所以只有它在本地解密后上传 JSON。

流程分两步，便于交互确认：
  discover_*()  只做文件发现（不触发钥匙串/DPAPI），返回 Ticket 描述
  ticket.load() 用户确认后才真正读取/解密，返回 {凭证名: 文本}
凭证名对应服务端平台 manifest 声明的名字（auth / device_id）。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class ExtractError(Exception):
    pass


@dataclass
class Ticket:
    platform: str
    account: str
    source: str                 # 来源文件，仅用于显示
    size: int                   # 数据文件大小
    loader: Callable[[], dict]   # -> {凭证名: (文件名, bytes)}
    warn: str = ""              # 需要提前告知用户的事（如会弹钥匙串授权）

    def load(self) -> dict:
        return self.loader()


IS_MAC, IS_WIN = sys.platform == "darwin", sys.platform == "win32"


def _support() -> Path:
    """Electron 的 userData 根：mac=~/Library/Application Support，win=%APPDATA%，linux=~/.config"""
    if IS_WIN:
        return Path(os.environ.get("APPDATA", ""))
    if IS_MAC:
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _local_support() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) if IS_WIN else _support()


# ---------- DPAPI (Windows) / Keychain (macOS) ----------
def dpapi_unprotect(data: bytes) -> bytes:
    if not IS_WIN:
        raise ExtractError("DPAPI 仅 Windows 可用")
    import ctypes
    import ctypes.wintypes as wt

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    inp, out = Blob(), Blob()
    inp.cbData = len(data)
    inp.pbData = ctypes.create_string_buffer(data)
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ExtractError("CryptUnprotectData 失败：请在客户端所属的 Windows 用户交互会话中运行")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# 国内版 / 国际版 Qoder 共用一套格式，只有数据目录和钥匙串项名称不同
QODER_PRODUCTS = {
    "qoder": {"dir": "com.qodercn.app.stable", "label": "Qoder CN",
              "keychain_service": "Qoder CN App Safe Storage", "keychain_account": "Qoder CN App Key"},
    "qoder-intl": {"dir": "com.qoder.app.stable", "label": "Qoder",
                   "keychain_service": "Qoder App Safe Storage", "keychain_account": "Qoder App Key"},
}
KEYCHAIN_SERVICE = QODER_PRODUCTS["qoder"]["keychain_service"]
KEYCHAIN_ACCOUNT = QODER_PRODUCTS["qoder"]["keychain_account"]


def keychain_password(service: str = KEYCHAIN_SERVICE, account: str = KEYCHAIN_ACCOUNT) -> str:
    """读取 Electron safeStorage 口令；首次会弹出 macOS 钥匙串授权框。"""
    for extra in (["-a", account], []):
        try:
            r = subprocess.run(["security", "find-generic-password", "-w", "-s", service, *extra],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ExtractError(f"调用 security 失败: {e}")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    raise ExtractError(f"钥匙串中没有 “{service}”，或你拒绝了授权")


# ---------- Qoder ----------
def decrypt_gcm(blob: bytes, key: bytes) -> bytes:
    """Windows：v10 + 12B nonce + 密文 + 16B tag，AES-256-GCM，key 为 DPAPI 解出的 32B。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        return AESGCM(key).decrypt(blob[3:15], blob[15:], None)
    except Exception:
        raise ExtractError("auth.v1.dat 解密失败（密钥不匹配？）")


def decrypt_mac(blob: bytes, password: str) -> bytes:
    """macOS：Electron safeStorage。PBKDF2-SHA1(saltysalt,1003)->16B，AES-128-CBC，IV=16*0x20，PKCS7。"""
    import hashlib
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, 16)
    try:
        d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        un = padding.PKCS7(128).unpadder()
        return un.update(d.update(blob[3:]) + d.finalize()) + un.finalize()
    except Exception:
        raise ExtractError("auth.v1.dat 解密失败（钥匙串口令不匹配？）")


def discover_qoder(profile_dir: str | None = None, account: str = "default",
                   unprotect=dpapi_unprotect, get_password=None, product: str = "qoder") -> list[Ticket]:
    prod = QODER_PRODUCTS[product]
    get_password = get_password or (lambda: keychain_password(prod["keychain_service"], prod["keychain_account"]))
    d = Path(profile_dir) if profile_dir else _support() / prod["dir"]
    dat = d / "auth.v1.dat"
    if not dat.exists():
        opt = "--qoder-dir" if product == "qoder" else "--qoder-intl-dir"
        raise ExtractError(f"未找到 {dat}（请先登录 {prod['label']}；非默认位置用 {opt} 指定）")

    def load():
        # Qoder 的密钥只能在本机取到，所以解密留在本地；解出的 ticket(JSON) 原样上传
        blob = dat.read_bytes()
        if blob[:3] != b"v10":
            raise ExtractError("auth.v1.dat 不是 v10 信封")
        if IS_MAC or (not IS_WIN and not (d / "Local State").exists()):
            plain = decrypt_mac(blob, get_password())
        else:
            ls = d / "Local State"
            if not ls.exists():
                raise ExtractError(f"缺少 {ls}")
            raw = base64.b64decode(json.loads(ls.read_text(encoding="utf-8"))["os_crypt"]["encrypted_key"])
            if raw[:5] != b"DPAPI":
                raise ExtractError("Local State 的 encrypted_key 前缀不是 DPAPI")
            plain = decrypt_gcm(blob, unprotect(raw[5:]))
        return {"auth": ("auth.json", plain)}

    warn = "将读取 macOS 钥匙串（会弹出授权框，请点“允许”）" if IS_MAC else ""
    return [Ticket(product, account, str(dat), dat.stat().st_size, load, warn)]


# ---------- Trae ----------
def discover_trae(app_dirs: list[str] | None = None, account: str = "default") -> list[Ticket]:
    dirs = [Path(x) for x in app_dirs] if app_dirs else [_support() / "Trae CN"]
    out = []
    for d in dirs:
        sf = d / "User" / "globalStorage" / "storage.json"
        if not sf.exists():
            continue
        def load(sf=sf, d=d):
            creds = {"auth": ("storage.json", sf.read_bytes())}       # 整个文件原样上传，服务端解析
            cfg = d / "ahanet" / "tt_net_config.config"
            if cfg.exists():
                creds["device_id"] = ("tt_net_config.config", cfg.read_bytes())
            return creds
        out.append(Ticket("trae", account if len(dirs) == 1 else d.name, str(sf), sf.stat().st_size, load))
    if not out:
        raise ExtractError("未找到 Trae 登录态（请先登录 Trae CN；非默认位置用 --trae-dir 指定）")
    return out


# ---------- WorkBuddy ----------
def _wb_dirs() -> list[Path]:
    c = [_local_support() / "CodeBuddyExtension" / "Data" / "Public" / "auth"]
    if not IS_WIN:
        c += [Path.home() / ".config" / "CodeBuddyExtension" / "Data" / "Public" / "auth"]
    return c


def discover_workbuddy(auth_dir: str | None = None) -> list[Ticket]:
    dirs = [Path(auth_dir)] if auth_dir else _wb_dirs()
    out = []
    for d in dirs:
        files = sorted(d.glob("*.info")) if d.is_dir() else []
        for p in files:
            name = "default" if len(files) == 1 else p.stem      # 单个登录态交给服务端按用户信息命名；多个才用文件名区分
            out.append(Ticket("workbuddy", name, str(p), p.stat().st_size,
                              lambda p=p: {"auth": (p.name, p.read_bytes())}))
    if not out:
        raise ExtractError(f"未找到 WorkBuddy 登录态（{dirs[0]}/*.info；请先登录 WorkBuddy，或用 --workbuddy-dir 指定）")
    return out


PLATFORMS = ("qoder", "qoder-intl", "trae", "workbuddy")
