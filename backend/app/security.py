"""主密钥加密(Fernet)、管理 token、API token 哈希。"""
import hashlib
import os
import secrets
from cryptography.fernet import Fernet

from . import config


def _load_or_create(env_name: str, filename: str, factory) -> str:
    v = os.environ.get(env_name)
    if v:
        return v
    p = config.DATA_DIR / filename
    if p.exists():
        return p.read_text().strip()
    v = factory()
    p.write_text(v)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return v


_master = _load_or_create("SIGN_MASTER_KEY", "master.key", lambda: Fernet.generate_key().decode())
_fernet = Fernet(_master.encode())
ADMIN_TOKEN = _load_or_create("SIGN_ADMIN_TOKEN", "admin.token", lambda: "adm_" + secrets.token_urlsafe(24))


def encrypt(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt(blob: bytes) -> bytes:
    return _fernet.decrypt(blob)


def hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def new_api_token() -> str:
    return "sgn_" + secrets.token_urlsafe(24)
