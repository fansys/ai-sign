"""Bark 推送。配置存 setting 表（key=bark），device key 加密保存。"""
import httpx

from . import security
from .db import SessionLocal, Setting

DEFAULT_SERVER = "https://api.day.app"
_DEFAULTS = {"server": DEFAULT_SERVER, "key_enc": "", "on_success": True, "on_failure": True, "on_auth": True}


def _load() -> dict:
    with SessionLocal() as db:
        row = db.get(Setting, "bark")
        return {**_DEFAULTS, **(row.value if row else {})}


def _key(cfg: dict) -> str:
    return security.decrypt(cfg["key_enc"].encode()).decode() if cfg["key_enc"] else ""


def get_public() -> dict:
    cfg, k = _load(), _key(_load())
    return {"server": cfg["server"], "key_masked": ("***" + k[-4:]) if k else "", "configured": bool(k),
            "on_success": cfg["on_success"], "on_failure": cfg["on_failure"], "on_auth": cfg["on_auth"]}


def save(server: str, key: str | None, on_success: bool, on_failure: bool, on_auth: bool) -> None:
    """key 为空串表示保持原值；传 None 同样保持。"""
    server = (server or DEFAULT_SERVER).strip().rstrip("/")
    if not server.startswith(("http://", "https://")):
        raise ValueError("服务器地址须以 http:// 或 https:// 开头")
    cfg = _load()
    if key and key.strip():
        cfg["key_enc"] = security.encrypt(key.strip().encode()).decode()
    with SessionLocal() as db:
        db.merge(Setting(key="bark", value={"server": server, "key_enc": cfg["key_enc"],
                                            "on_success": bool(on_success), "on_failure": bool(on_failure),
                                            "on_auth": bool(on_auth)}))
        db.commit()


_LABEL = {"success": "成功", "failure": "失败", "auth": "需重新授权"}


def build_round(items: list[dict], cfg: dict) -> tuple[str, str] | None:
    """把一轮的结果按开关过滤后合成 (标题, 正文)；没有需要推送的内容返回 None。"""
    items = [i for i in items if cfg[f"on_{i['kind']}"]]
    if not items:
        return None
    title = "签到" + " · ".join(f"{_LABEL[k]} {n}" for k in _LABEL if (n := sum(i["kind"] == k for i in items)))
    lines = []
    for i in sorted(items, key=lambda x: list(_LABEL).index(x["kind"])):
        extra = f" +{i['points']}积分" if i["kind"] == "success" and i.get("points") else ""
        lines.append(f"[{_LABEL[i['kind']]}] {i['label']}{extra}" + (f"：{i['message']}" if i["kind"] != "success" and i["message"] else ""))
    return title, "\n".join(lines)


async def send_round(items: list[dict]) -> str | None:
    """一轮签到结束后统一推送一条。未配置/无内容返回 None。"""
    cfg = _load()
    msg = build_round(items, cfg) if _key(cfg) else None
    return await send(*msg, kind="test") if msg else None


async def send(title: str, body: str, *, kind: str = "test") -> str | None:
    """kind: success|failure|auth|test。未配置或该类通知已关闭返回 None；成功返回空串；失败返回错误信息。"""
    cfg = _load()
    key = _key(cfg)
    if not key or (kind != "test" and not cfg[f"on_{kind}"]):
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{cfg['server']}/push", json={"device_key": key, "title": title, "body": body, "group": "sign"})
        return "" if r.status_code == 200 else f"Bark 返回 {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return f"发送失败: {type(e).__name__}"
