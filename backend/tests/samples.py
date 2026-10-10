"""按各客户端公开分析的真实格式生成各客户端的本地登录态样本（与客户端加密方式一致）。"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO = Path(__file__).resolve().parents[2]


def load_script(key):
    spec = importlib.util.spec_from_file_location(key, REPO / "scripts" / key / "current.py")
    m = importlib.util.module_from_spec(spec)
    m.__dict__.update(CredentialError=Exception, AuthExpired=Exception)
    spec.loader.exec_module(m)
    return m


trae_mod, wb_mod = load_script("trae"), load_script("workbuddy")

QODER_AUTH = {"token": "QODER_TOKEN_0123456789", "refreshToken": "REFRESH_SECRET_000000", "expiresAt": "2099-01-01T00:00:00Z",
              "user": {"id": "u1", "name": "alice"}}
TRAE_TOKEN, WB_TOKEN = "TRAE_TOKEN_ABCDEFGHIJ", "WB_TOKEN_ABCDEFGHIJKL"


def qoder_cred():
    return dict(QODER_AUTH)


def qoder_dat_windows(key: bytes, auth=QODER_AUTH) -> bytes:
    """v10 + 12B nonce + 密文 + 16B tag（AES-256-GCM）"""
    nonce = os.urandom(12)
    return b"v10" + nonce + AESGCM(key).encrypt(nonce, json.dumps(auth).encode(), None)


def qoder_dat_mac(password: str, auth=QODER_AUTH) -> bytes:
    """Electron safeStorage：PBKDF2-SHA1(saltysalt,1003)->16B，AES-128-CBC，IV=16*0x20"""
    key = hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, 16)
    pad = padding.PKCS7(128).padder()
    data = pad.update(json.dumps(auth).encode()) + pad.finalize()
    e = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return b"v10" + e.update(data) + e.finalize()


def trae_storage(token=TRAE_TOKEN, extra=None):
    """storage.json：iCubeAuthInfo = 6B 头 + 32B key + AES-CBC(64B hmac + JSON)"""
    key = os.urandom(32)
    h = hashlib.sha512(hashlib.sha512(key).digest() + bytes(a ^ b for a, b in zip(trae_mod.URE, trae_mod.DRE))).digest()
    plain = b"\0" * 64 + json.dumps({"token": token, "userRegion": {"region": "CN"}, **(extra or {})}).encode()
    pad = padding.PKCS7(128).padder()
    data = pad.update(plain) + pad.finalize()
    enc = Cipher(algorithms.AES(h[:16]), modes.CBC(h[16:32])).encryptor()
    ct = enc.update(data) + enc.finalize()
    return {trae_mod.AUTH_KEY: base64.b64encode(b"\0" * 6 + key + ct).decode(), "other.setting": "unrelated-data"}


def wb_info(exp_ms, token=WB_TOKEN, uid="u9"):
    """WorkBuddy 5.6.0+ .info：accessToken 为 $wbEncrypted AES-256-GCM 信封"""
    nonce = os.urandom(12)
    kid = wb_mod._KEY_ID
    ct = AESGCM(wb_mod._KEY).encrypt(nonce, token.encode(), wb_mod._aad(kid, 1))
    env = {"keyId": kid, "suite": 1, "nonce": base64.b64encode(nonce).decode(),
           "ciphertext": base64.b64encode(ct[:-16]).decode(), "authTag": base64.b64encode(ct[-16:]).decode()}
    return {"account": {"uid": uid}, "auth": {"domain": "d.example", "expiresAt": exp_ms,
            "accessToken": {"$wbEncrypted": 1, "scheme": "sym-v1", "envelope": base64.b64encode(json.dumps(env).encode()).decode()}}}
