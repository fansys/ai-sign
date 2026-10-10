"""WorkBuddy 签到（兼容 5.6.0+ 的 $wbEncrypted AES-256-GCM 字段加密）。

凭证 auth：上传 %LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth\\*.info 的文件内容。
on_credential 解出 accessToken 后只保留 {uid, domain, accessToken, expiresAt}。
密钥由客户端构建期内嵌常量派生，同版本通用；客户端升级后若 keyId 不匹配，会在上传时被拒绝并提示。
"""
import base64
import hashlib
import json
import struct
import time
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

API = "https://copilot.tencent.com/v2/billing/meter"
_SECRET = "Sik9U5aXhCdwTVEwsEySDOmDoB9r9ntFxHF1fst9LQI="
_KEY = hashlib.sha256(_SECRET.encode()).digest()
_KEY_ID = hashlib.sha256(_KEY).hexdigest()[:16]


def _aad(key_id: str, suite: int) -> bytes:
    tag = b"WBEV1"
    return b"".join([b"WB-AAD\x00", b"\x01", struct.pack(">I", len(tag)) + tag,
                     struct.pack(">I", 6) + b"sym-v1", struct.pack(">I", suite),
                     struct.pack(">I", len(key_id)) + key_id.encode(), bytes([2]), b"\x00", b"\x00"])


def _open_field(v):
    if not isinstance(v, dict) or v.get("$wbEncrypted") != 1:
        return v
    if v.get("scheme") not in (None, "sym-v1"):
        raise CredentialError(f"不支持的加密方案 {v.get('scheme')}，请重新登录 WorkBuddy")
    env = json.loads(base64.b64decode(v["envelope"]))
    if env.get("keyId") != _KEY_ID:
        raise CredentialError(f"密钥不匹配(keyId={env.get('keyId')})，WorkBuddy 版本可能已更新，需更新脚本")
    ct = base64.b64decode(env["ciphertext"]) + base64.b64decode(env["authTag"])
    try:
        return AESGCM(_KEY).decrypt(base64.b64decode(env["nonce"]), ct, _aad(env["keyId"], env["suite"])).decode()
    except Exception:
        raise CredentialError("accessToken 解密失败")


def on_credential(ctx, name, raw):
    try:
        s = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise CredentialError("需要上传 .info 文件的 JSON 内容")
    auth = s.get("auth") or {}
    token = _open_field(auth.get("accessToken"))
    uid = (s.get("account") or {}).get("uid")
    if not token or not uid:
        raise CredentialError("登录态缺少 accessToken 或 account.uid，请重新登录")
    exp = auth.get("expiresAt") or 0
    norm = {"uid": uid, "domain": auth.get("domain", ""), "accessToken": token, "expiresAt": exp}
    try:
        nick = _open_field((s.get("account") or {}).get("nickname"))
    except CredentialError:
        nick = None
    return {"value": norm, "meta": {"uid": uid, "domain": auth.get("domain", ""), "identity": uid, "label": nick},
            "expires_at": datetime.fromtimestamp(exp / 1000, timezone.utc).isoformat() if exp else None}


def _post(ctx, api, path, a):
    h = {"Authorization": f"Bearer {a['accessToken']}", "X-User-Id": a["uid"],
         "X-Domain": a.get("domain", ""), "Content-Type": "application/json"}
    r = ctx.http.post(f"{api}/{path}", headers=h, json={})
    if r.status_code in (401, 403):
        raise AuthExpired(f"accessToken 失效(HTTP {r.status_code})")
    return r.json()


def run(ctx):
    a = ctx.cred_json("auth")
    if not a:
        raise AuthExpired("尚未提交 auth 凭证")
    if (a.get("expiresAt") or 0) / 1000 < time.time():
        raise AuthExpired("accessToken 已过期，需启动 WorkBuddy 刷新登录态后重新提交")
    api = ctx.config.get("api_base", API)
    st = _post(ctx, api, "checkin-status", a)
    if st.get("code") != 0:
        return {"status": "failed", "message": f"查询签到状态异常: {st.get('msg')}"}
    if (st.get("data") or {}).get("today_checked_in"):
        return {"status": "already", "message": "今日已签到"}
    if ctx.is_test:
        return {"status": "success", "message": "[试运行] 今日未签到，未领取", "points": 0}
    c = _post(ctx, api, "daily-checkin", a)
    if c.get("code") == 0:
        return {"status": "success", "points": (c.get("data") or {}).get("credit"), "message": "今日已签到"}
    if c.get("code") == 10001:
        return {"status": "already", "message": "今日已签到"}
    return {"status": "failed", "message": f"签到失败: {c.get('msg')}"}
