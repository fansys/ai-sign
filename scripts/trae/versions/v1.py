"""Trae CN / TRAE SOLO CN 签到。

凭证 auth 接受：storage.json 全文 / iCubeAuthInfo 密文(base64) / 已解密 JSON({token, userRegion})。
可选凭证 device_id：x-device-id，上传数字或 ahanet/tt_net_config.config 原文均可（服务端提取）。
"""
import base64
import hashlib
import json
import re
from datetime import datetime, timezone

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

API = "https://api.trae.cn/trae/api/v2/ug/checkin_credits"
AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
HDR_LEN, KEY_LEN, HMAC_LEN = 6, 32, 64
URE = bytes([82,9,106,213,48,54,165,56,191,64,163,158,129,243,215,251,124,227,57,130,155,47,255,135,52,142,67,68,196,222,233,203,84,123,148,50,166,194,35,61,238,76,149,11,66,250,195,78,8,46,161,102,40,217,36,178,118,91,162,73,109,139,209,37])
DRE = bytes([31,221,168,51,136,7,199,49,177,18,16,89,39,128,236,95,96,81,127,169,25,181,74,13,45,229,122,159,147,201,156,239,160,224,59,77,174,42,245,176,200,235,187,60,131,83,153,97,23,43,4,126,186,119,214,38,225,105,20,99,85,33,12,125])


def _decrypt(b64_text: str) -> dict:
    t = base64.b64decode(b64_text)
    key = t[HDR_LEN:HDR_LEN + KEY_LEN]
    sha = hashlib.sha512(key).digest()
    xor = bytes(a ^ b for a, b in zip(URE, DRE))
    h = hashlib.sha512(sha + xor).digest()
    aes_key, iv = h[:16], h[16:32]
    dec = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded = dec.update(t[HDR_LEN + KEY_LEN:]) + dec.finalize()
    un = padding.PKCS7(128).unpadder()
    plain = un.update(padded) + un.finalize()
    return json.loads(plain[HMAC_LEN:].decode("utf-8"))


def _iso(v):
    """客户端给的 ISO 到期时间（如 2026-10-22T11:18:03.245Z）-> ISO；无法解析返回 None。"""
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).isoformat() if v else None
    except ValueError:
        return None


def _jwt_exp(token):
    """JWT payload 的 exp（秒）-> ISO 时间；不是 JWT 或没有 exp 返回 None。只解码，不校验、不记录。"""
    try:
        seg = token.split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))).get("exp")
        return datetime.fromtimestamp(float(exp), timezone.utc).isoformat() if exp else None
    except Exception:
        return None


def _fetch_userinfo(ctx, token):
    """账号信息以官方 API 为准（只读）；失败返回 {}，由调用方回退到本地 ticket 里的字段。"""
    try:
        r = ctx.http.post("https://api.trae.cn/cloudide/api/v3/trae/GetUserInfo", timeout=10,
                          headers={"Content-Type": "application/json", "x-cloudide-token": token},
                          json={"ReqSource": "IDE"})
        d = (r.json() or {}).get("Result") if r.status_code == 200 else None
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def on_credential(ctx, name, raw):
    txt = raw.decode("utf-8", "ignore").strip()
    if name == "device_id":  # 可直接是数字，也可是 ahanet/tt_net_config.config 原文
        m = re.search(r"device_id[^\w]*(\d+)", txt) or re.fullmatch(r"(\d+)", txt)
        if not m:
            raise CredentialError("未能在内容中找到 device_id")
        return {"value": m.group(1), "meta": {}, "expires_at": None}
    try:
        doc = json.loads(txt)
    except ValueError:
        doc = None
    try:
        if isinstance(doc, dict) and AUTH_KEY in doc:
            auth = _decrypt(doc[AUTH_KEY])
        elif isinstance(doc, dict) and "token" in doc:
            auth = doc
        else:
            auth = _decrypt(txt)
    except CredentialError:
        raise
    except Exception as e:
        raise CredentialError(f"解析 iCubeAuthInfo 失败: {type(e).__name__}")
    if not auth.get("token"):
        raise CredentialError("登录态中没有 token，请重新登录客户端")
    region = (auth.get("userRegion") or {}).get("region")
    acc = auth.get("account") or {}
    info = _fetch_userinfo(ctx, auth["token"])
    username = info.get("ScreenName") or acc.get("username")
    mobile = info.get("NonPlainTextMobile") or acc.get("nonPlainTextMobile")
    label = " ".join(x for x in (username, f"({mobile})" if mobile else "") if x) or None
    meta = {"region": region, "identity": info.get("UserID") or auth.get("userId"), "label": label}
    return {"value": {"token": auth["token"], "region": region}, "meta": meta,
            "expires_at": _iso(auth.get("expiredAt")) or _jwt_exp(auth["token"])}


def _post(ctx, url, auth, device_id):
    h = {"Authorization": f"Cloud-IDE-JWT {auth['token']}", "Content-Type": "application/json", "x-device-id": device_id}
    if auth.get("region"):
        h["X-User-Region"] = auth["region"]
    r = ctx.http.post(url, headers=h, json={"req_source": 1})
    if r.status_code in (401, 403):
        raise AuthExpired(f"登录态可能过期(HTTP {r.status_code})")
    r.raise_for_status()
    return r.json()


def _unwrap(resp):
    if "checked_in" not in resp and isinstance(resp.get("data"), dict) and "checked_in" in resp["data"]:
        return resp["data"]
    return resp


def run(ctx):
    auth = ctx.cred_json("auth")
    if not auth:
        raise AuthExpired("尚未提交 auth 凭证")
    api = ctx.config.get("api_base", API)
    dev = ctx.cred("device_id", "").strip()
    status = _unwrap(_post(ctx, f"{api}/status", auth, dev))
    if status.get("checked_in"):
        return {"status": "already", "message": "今日已签到", "points": None, "data": {"credits": status.get("credits")}}
    if not status.get("enable"):
        return {"status": "failed", "message": "签到不可用: " + json.dumps(status, ensure_ascii=False)[:200]}
    if ctx.is_test:
        return {"status": "success", "message": "[试运行] 签到可用，未领取", "points": 0}
    claim = _post(ctx, f"{api}/claim", auth, dev)
    if claim.get("code") == 0:
        after = {}
        try:
            after = _unwrap(_post(ctx, f"{api}/status", auth, dev))
        except Exception:
            pass
        d = claim.get("data") or {}
        pts = d.get("credits") or d.get("credit") or d.get("amount")
        return {"status": "success", "message": "今日已签到", "points": pts, "data": {"credits": after.get("credits")}}
    return {"status": "failed", "message": str(claim.get("message") or json.dumps(claim, ensure_ascii=False)[:200])}
