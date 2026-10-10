"""Qoder（国际版）签到。

凭证 auth：CLI 在本机解密 com.qoder.app.stable/auth.v1.dat（密钥只有本机拿得到：Windows DPAPI / macOS 钥匙串）后上传的 JSON，
字段含 token / expiresAt / user；on_credential 归一化并丢弃 refreshToken。
只读不刷新：refresh token 一次一换，服务端绝不调用刷新接口。
"""
import json
from datetime import datetime, timezone

API = "https://openapi.qoder.sh"


def _parse_exp(v):
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _fetch_userinfo(ctx, token):
    """账号信息以官方 API 为准（只读）；失败返回 {}，由调用方回退到本地 ticket 里的字段。"""
    try:
        r = ctx.http.get(ctx.config.get("api_base", API) + "/api/v1/userinfo", timeout=10,
                         headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
        d = r.json() if r.status_code == 200 else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def on_credential(ctx, name, raw):
    try:
        auth = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise CredentialError("需要 JSON（含 token 的登录态）；请用 sign-cli 提交")
    token = auth.get("token")
    if not token:
        raise CredentialError("登录态中没有 token，请先在客户端登录")
    exp = _parse_exp(auth.get("expiresAt"))
    user = dict(auth.get("user") or {})
    info = _fetch_userinfo(ctx, token)
    for k, src in (("id", "id"), ("name", "name"), ("phone", "security_mobile"), ("email", "email")):
        if info.get(src):
            user[k] = info[src]
    norm = {"token": token, "expiresAt": auth.get("expiresAt"), "user": {"id": user.get("id"), "name": user.get("name")}}
    label = f"{user['name']} ({user['email']})" if user.get("name") and user.get("email") else user.get("name")
    meta = {"user": user.get("name"), "expiresAt": auth.get("expiresAt"), "identity": user.get("id"), "label": label}
    return {"value": norm, "meta": meta,
            "expires_at": exp.isoformat() if exp else None}


def _headers(ctx, token):
    cfg = ctx.config
    return {"Accept": "application/json", "User-Agent": "Qoder", "Authorization": f"Bearer {token}",
            "Cosy-ClientType": str(cfg.get("client_type", "10")), "Cosy-Version": str(cfg.get("version", "0.3.4"))}


def run(ctx):
    auth = ctx.cred_json("auth")
    if not auth:
        raise AuthExpired("尚未提交 auth 凭证")
    exp = _parse_exp(auth.get("expiresAt"))
    if exp and exp < datetime.now(timezone.utc):
        raise AuthExpired("token 已过期，请打开 Qoder 客户端刷新登录态后重新提交")
    api = ctx.config.get("api_base", API)
    h = _headers(ctx, auth["token"])
    r = ctx.http.get(api + "/sash/api/v1/me/campaigns", headers=h)
    if r.status_code in (401, 403):
        raise AuthExpired(f"登录态失效(HTTP {r.status_code})，请在客户端重新登录后重新提交")
    if r.status_code != 200:
        return {"status": "failed", "message": f"活动列表失败 HTTP {r.status_code}"}
    campaigns = r.json().get("campaigns") or []
    if not campaigns:
        return {"status": "already", "message": "当前没有可展示的活动"}
    targets = [c for c in campaigns if c.get("claimStatus") == "CLAIMABLE" and c.get("actionType") == "CLAIM_BENEFIT"]
    if not targets:
        return {"status": "already", "message": "今日已签到"}
    if ctx.is_test:
        return {"status": "success", "message": f"[试运行] 将领取 {len(targets)} 条活动", "points": 0}
    got, claimed, replayed = 0, False, False
    for c in targets:
        rr = ctx.http.post(f"{api}/sash/api/v1/me/campaigns/{c['campaignId']}/claim", headers=h)
        try:
            body = rr.json()
        except ValueError:
            body = {}
        ctx.log.info("claim", f"{c.get('campaignKey')} HTTP {rr.status_code} status={body.get('status')} replayed={body.get('replayed')}")
        if rr.status_code == 200 and body.get("status") == "CLAIMED":
            if body.get("replayed"):
                replayed = True
            else:
                claimed = True
                got += int((body.get("benefit") or {}).get("amount") or 0)
        elif rr.status_code in (401, 403):
            raise AuthExpired("领取时登录态失效")
    if claimed:
        return {"status": "success", "points": got, "message": "今日已签到"}
    if replayed:
        return {"status": "already", "message": "今日已签到（replayed）"}
    return {"status": "failed", "message": "领取未成功"}
