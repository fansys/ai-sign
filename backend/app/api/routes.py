from __future__ import annotations

import calendar as _cal
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from .. import config, notify, scripts_store, security, services
from ..db import (Account, ApiToken, Credential, Platform, Run, RunEvent, ScriptDraft, ScriptVersion, get_db,
                  now, today)
from ..services import ServiceError

router = APIRouter(prefix="/api")


# ---------------- 鉴权 ----------------
def _auth(request: Request, db: Session, scope: str | None):
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else ""
    if tok and tok == security.ADMIN_TOKEN:
        return "admin"
    if tok and scope:
        t = db.scalar(select(ApiToken).where(ApiToken.token_hash == security.hash_token(tok), ApiToken.revoked_at.is_(None)))
        if t and scope in (t.scopes or []):
            t.last_used_at = now()
            db.commit()
            return f"token:{t.name}"
    raise HTTPException(401, "未授权")


def admin(request: Request, db: Session = Depends(get_db)):
    return _auth(request, db, None)


def cred_writer(request: Request, db: Session = Depends(get_db)):
    return _auth(request, db, "credentials:write")


def _err(e: ServiceError):
    return HTTPException(e.code, str(e))


def _platform(db, key) -> Platform:
    p = db.scalar(select(Platform).where(Platform.key == key))
    if not p:
        raise HTTPException(404, "平台不存在")
    return p


def _account(db, aid) -> Account:
    a = db.get(Account, aid)
    if not a:
        raise HTTPException(404, "账号不存在")
    return a


def _p(p: Platform):
    return {"id": p.id, "key": p.key, "name": p.name, "enabled": p.enabled, "manifest": p.manifest,
            "active_version_id": p.active_version_id}


def _a(a: Account):
    return {"id": a.id, "platform": a.platform.key, "platform_name": a.platform.name, "name": a.name,
            "enabled": a.enabled}


def _c(c: Credential):
    return {"name": c.name, "kind": c.kind, "status": c.status, "size": c.size, "filename": c.filename,
            "meta": c.meta, "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            "updated_at": c.updated_at.isoformat()}


def _v(v: ScriptVersion, with_src=False):
    d = {"id": v.id, "version": v.version, "note": v.note, "author": v.author, "sha256": v.sha256[:12],
         "created_at": v.created_at.isoformat(), "parent_version_id": v.parent_version_id}
    if with_src:
        d["source"] = v.source
    return d


# ---------------- 状态 ----------------
@router.get("/status")
def status(_=Depends(admin)):
    return {"today": today(), "now": now().strftime("%Y-%m-%d %H:%M:%S"), "daily_at": config.DAILY_AT,
            "retry_hours": config.RETRY_HOURS, "tz": config.TZ}


# ---------------- 平台 ----------------
@router.get("/platforms")
def list_platforms(db: Session = Depends(get_db), _=Depends(admin)):
    return [_p(p) for p in db.scalars(select(Platform).order_by(Platform.id))]


@router.patch("/platforms/{key}")
def patch_platform(key: str, body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    for f in ("name", "enabled", "manifest"):
        if f in body:
            setattr(p, f, body[f])
    scripts_store.write_manifest(p)
    db.commit()
    return _p(p)


# ---------------- 脚本版本 ----------------
@router.post("/scripts/sync")
def sync_scripts(db: Session = Depends(get_db), _=Depends(admin)):
    """手工改了 scripts/ 下的文件后，重新扫描：新目录=新平台，改过的 current.py=新版本。"""
    return {"changes": scripts_store.sync(db)}



@router.get("/platforms/{key}/versions")
def versions(key: str, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    vs = db.scalars(select(ScriptVersion).where(ScriptVersion.platform_id == p.id).order_by(ScriptVersion.version.desc()))
    return {"active_version_id": p.active_version_id, "versions": [_v(v) for v in vs]}


@router.get("/platforms/{key}/versions/{vid}")
def version_detail(key: str, vid: int, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    v = db.get(ScriptVersion, vid)
    if not v or v.platform_id != p.id:
        raise HTTPException(404)
    return _v(v, True)


@router.get("/platforms/{key}/draft")
def get_draft(key: str, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    d = db.get(ScriptDraft, p.id)
    if d:
        return {"source": d.source, "base_version_id": d.base_version_id, "is_draft": True}
    v = db.get(ScriptVersion, p.active_version_id) if p.active_version_id else None
    return {"source": v.source if v else "", "base_version_id": v.id if v else None, "is_draft": False}


@router.put("/platforms/{key}/draft")
def put_draft(key: str, body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    d = db.get(ScriptDraft, p.id) or ScriptDraft(platform_id=p.id, source="")
    d.source, d.base_version_id = body["source"], body.get("base_version_id", p.active_version_id)
    db.add(d)
    db.commit()
    return {"ok": True}


@router.delete("/platforms/{key}/draft")
def del_draft(key: str, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    d = db.get(ScriptDraft, p.id)
    if d:
        db.delete(d)
        db.commit()
    return {"ok": True}


@router.post("/platforms/{key}/publish")
def publish(key: str, body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    src = body.get("source")
    if src is None:
        d = db.get(ScriptDraft, p.id)
        if not d:
            raise HTTPException(422, "没有草稿可发布")
        src = d.source
    if not (body.get("note") or "").strip():
        raise HTTPException(422, "发布说明必填")
    try:
        v = services.publish(db, p, src, body["note"], activate=bool(body.get("activate")))
    except ServiceError as e:
        raise _err(e)
    d = db.get(ScriptDraft, p.id)
    if d:
        db.delete(d)
    db.commit()
    return _v(v)


@router.post("/platforms/{key}/activate")
def activate(key: str, body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, key)
    v = db.get(ScriptVersion, body["version_id"])
    if not v or v.platform_id != p.id:
        raise HTTPException(404, "版本不存在")
    p.active_version_id = v.id
    scripts_store.write_current(p.key, v.source)   # current.py 始终等于启用版本
    db.commit()
    return {"active_version_id": v.id}


@router.post("/platforms/{key}/test")
async def test_script(key: str, body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    """试运行：source 缺省则用草稿；不计入日历；ctx.is_test=True。"""
    p = _platform(db, key)
    acc = _account(db, body["account_id"])
    if acc.platform_id != p.id:
        raise HTTPException(422, "账号不属于该平台")
    src = body.get("source")
    if src is None and body.get("version_id"):
        v = db.get(ScriptVersion, body["version_id"])
        src = v.source if v else None
    if src is None:
        d = db.get(ScriptDraft, p.id)
        src = d.source if d else None
    if src is None:  # 无草稿也未指定版本：试运行当前启用版本
        v = db.get(ScriptVersion, p.active_version_id) if p.active_version_id else None
        src = v.source if v else None
    if src is None:
        raise HTTPException(422, "没有可试运行的源码")
    try:
        services.check_source(src)
        rid = await services.run_account(acc.id, "test", source_override=src)
    except ServiceError as e:
        raise _err(e)
    return _run_detail(db, rid)


# ---------------- 账号 ----------------
@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), _=Depends(admin)):
    out = []
    for a in db.scalars(select(Account).order_by(Account.id)):
        d = _a(a)
        d["credentials"] = [_c(c) for c in db.scalars(select(Credential).where(Credential.account_id == a.id))]
        out.append(d)
    return out


@router.post("/accounts")
def create_account(body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    p = _platform(db, body.get("platform", ""))
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name 必填")
    if db.scalar(select(Account).where(Account.platform_id == p.id, Account.name == name)):
        raise HTTPException(409, "账号已存在")
    a = Account(platform_id=p.id, name=name)
    db.add(a)
    db.commit()
    return _a(a)


@router.patch("/accounts/{aid}")
def patch_account(aid: int, body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    a = _account(db, aid)
    for f in ("name", "enabled"):
        if f in body:
            setattr(a, f, body[f])
    db.commit()
    return _a(a)


@router.delete("/accounts/{aid}")
def delete_account(aid: int, db: Session = Depends(get_db), _=Depends(admin)):
    a = _account(db, aid)
    db.delete(a)
    db.commit()
    return {"ok": True}


# ---------------- 凭证 ----------------
async def _read_body(request: Request):
    ct = request.headers.get("content-type", "")
    if ct.startswith("multipart/form-data"):
        form = await request.form()
        f = form.get("file")
        if f is None:
            raise HTTPException(422, "multipart 需要 file 字段")
        return await f.read(), getattr(f, "filename", "") or ""
    if ct.startswith("application/json"):
        body = await request.json()
        v = body.get("value") if isinstance(body, dict) and "value" in body else body
        return (v.encode() if isinstance(v, str) else json.dumps(v, ensure_ascii=False).encode()), ""
    return await request.body(), ""


async def _put(db, acc, name, request):
    raw, fn = await _read_body(request)
    if not raw:
        raise HTTPException(422, "凭证内容为空")
    try:
        c = await services.store_credential_async(db, acc, name, raw, fn)
    except ServiceError as e:
        raise _err(e)
    return _c(c)


@router.put("/accounts/{aid}/credentials/{name}")
async def put_cred(aid: int, name: str, request: Request, db: Session = Depends(get_db), _=Depends(cred_writer)):
    return await _put(db, _account(db, aid), name, request)


@router.put("/platforms/{key}/accounts/{aname}/credentials/{name}")
async def put_cred_by_name(key: str, aname: str, name: str, request: Request, create: int = 0,
                           db: Session = Depends(get_db), _=Depends(cred_writer)):
    p = _platform(db, key)
    a = db.scalar(select(Account).where(Account.platform_id == p.id, Account.name == aname))
    if not a:
        if not create:
            raise HTTPException(404, "账号不存在，加 ?create=1 可自动创建")
        a = Account(platform_id=p.id, name=aname)
        db.add(a)
        db.commit()
    out = await _put(db, a, name, request)
    if aname == "default":   # 自动命名：以 ticket 里的用户信息为账号名（脚本 meta 的 label/identity）
        cred = db.scalar(select(Credential).where(Credential.account_id == a.id, Credential.name == name))
        if cred:
            a = services.resolve_account(db, a, cred)
    return {**out, "account": a.name}


@router.get("/accounts/{aid}/credentials/{name}/value")
def get_cred_value(aid: int, name: str, db: Session = Depends(get_db), _=Depends(admin)):
    """复制凭证：返回明文，仅管理员 token（API token 不可用），禁止缓存。"""
    from fastapi.responses import PlainTextResponse
    c = db.scalar(select(Credential).where(Credential.account_id == aid, Credential.name == name))
    if not c:
        raise HTTPException(404, "凭证不存在")
    return PlainTextResponse(security.decrypt(c.value_enc).decode("utf-8", "replace"), headers={"Cache-Control": "no-store"})


# ---------------- CLI 下载 ----------------
CLI_TOKEN_NAME = "cli-download"


def _cli_token(db: Session) -> str:
    """下载包内置的 apikey：复用名为 cli-download 的未吊销 token，没有则新建（仅“提交凭证”权限）。"""
    t = db.scalars(select(ApiToken).where(ApiToken.name == CLI_TOKEN_NAME, ApiToken.revoked_at.is_(None),
                                          ApiToken.token_enc.is_not(None)).order_by(ApiToken.id)).first()
    if t:
        return security.decrypt(t.token_enc).decode()
    tok = security.new_api_token()
    db.add(ApiToken(name=CLI_TOKEN_NAME, token_hash=security.hash_token(tok), scopes=["credentials:write"],
                    token_enc=security.encrypt(tok.encode())))
    db.commit()
    return tok


@router.get("/cli/download")
def cli_download(request: Request, server: str = "", db: Session = Depends(get_db), _=Depends(admin)):
    """下载免安装 cli（zip，含 sign.conf：服务地址 + apikey）。地址优先 ?server=（前端传浏览器所见地址），否则按请求头推断。"""
    from fastapi.responses import Response
    from .. import cli_pack
    if not server:
        h = request.headers
        host = h.get("x-forwarded-host") or h.get("host") or request.url.netloc
        server = f"{h.get('x-forwarded-proto') or request.url.scheme}://{host}"
    try:
        cli_pack.normalize_server(server)
        data = cli_pack.build_zip(server, _cli_token(db))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="sign-cli.zip"', "Cache-Control": "no-store"})


# ---------------- 执行 ----------------
@router.post("/runs")
async def trigger_run(body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    """立即签到：account_id / platform / 都不传=全部启用账号（忽略已成功的账号以外一律重跑）。后台执行。"""
    import asyncio
    q = select(Account).join(Platform).where(Account.enabled.is_(True))
    if body.get("account_id"):
        q = q.where(Account.id == body["account_id"])
    elif body.get("platform"):
        q = q.where(Platform.key == body["platform"])
    ids = [a.id for a in db.scalars(q)]
    if not ids:
        raise HTTPException(404, "没有可执行的账号")
    asyncio.create_task(services.run_many(ids, "manual"))
    return {"accepted": ids}


def _run_detail(db, rid):
    r = db.get(Run, rid)
    evs = db.scalars(select(RunEvent).where(RunEvent.run_id == rid).order_by(RunEvent.id))
    return {**_run_row(r), "events": [{"ts": e.ts.strftime("%H:%M:%S"), "level": e.level, "tag": e.tag, "message": e.message} for e in evs]}


def _run_row(r: Run):
    sv = object_session(r).get(ScriptVersion, r.script_version_id) if r.script_version_id else None
    return {"version": sv.version if sv else None, "id": r.id, "account_id": r.account_id, "platform": r.account.platform.name, "account": r.account.name,
            "trigger": r.trigger, "status": r.status, "points": r.points, "message": r.message,
            "attempt_no": r.attempt_no, "version_id": r.script_version_id,
            "started_at": r.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": r.finished_at.strftime("%Y-%m-%d %H:%M:%S") if r.finished_at else None}


@router.get("/runs/{rid}")
def run_detail(rid: int, db: Session = Depends(get_db), _=Depends(admin)):
    if not db.get(Run, rid):
        raise HTTPException(404)
    return _run_detail(db, rid)


# ---------------- 日历 / 明细 ----------------
def _day_status(last: dict[int, Run], pending: int) -> str:
    st = [r.status for r in last.values()]
    if any(s in ("failed", "need_auth", "timeout") for s in st):
        return "failed"
    ok = sum(s in services.OK for s in st)
    if ok and (pending or ok < len(st)):
        return "partial"
    if ok:
        return "success"
    return "none"


@router.get("/calendar")
def calendar(month: str, db: Session = Depends(get_db), _=Depends(admin)):
    y, m = map(int, month.split("-"))
    first = f"{y:04d}-{m:02d}-01"
    last_d = f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"
    runs = db.scalars(select(Run).where(Run.local_date >= first, Run.local_date <= last_d, Run.trigger != "test").order_by(Run.id))
    by_day: dict[str, dict[int, Run]] = {}
    for r in runs:
        by_day.setdefault(r.local_date, {})[r.account_id] = r
    pend_today = len(services.pending_account_ids(db)) if first <= today() <= last_d else 0
    out = []
    for d, last in sorted(by_day.items()):
        out.append({"date": d, "status": _day_status(last, pend_today if d == today() else 0), "count": len(last)})
    return {"month": month, "days": out, "recorded_days": len(out)}


@router.get("/days/{date}")
def day(date: str, db: Session = Depends(get_db), _=Depends(admin)):
    runs = list(db.scalars(select(Run).where(Run.local_date == date, Run.trigger != "test").order_by(Run.id)))
    last: dict[int, Run] = {}
    cnt: dict[int, int] = {}
    for r in runs:
        last[r.account_id] = r
        cnt[r.account_id] = cnt.get(r.account_id, 0) + 1
    results = []
    for aid, r in last.items():
        d = _run_row(r)
        d["attempts"] = cnt[aid]
        d["time"] = (r.finished_at or r.started_at).strftime("%H:%M:%S")
        results.append(d)
    results.sort(key=lambda x: x["time"], reverse=True)
    actions: list[dict] = []
    for r in sorted(runs, key=lambda x: x.id, reverse=True):
        row = _run_row(r)
        p = actions[-1] if actions else None
        if p and (p["account_id"], p["status"], p["message"], p["trigger"]) == (row["account_id"], row["status"], row["message"], row["trigger"]):
            p["repeat"] += 1
            continue
        row["repeat"] = 1
        actions.append(row)
    ok = sum(1 for r in last.values() if r.status in services.OK)
    return {"date": date, "success": ok, "actions_count": len(runs), "results": results, "actions": actions}


# ---------------- API Token ----------------
@router.get("/tokens")
def tokens(db: Session = Depends(get_db), _=Depends(admin)):
    return [{"id": t.id, "name": t.name, "scopes": t.scopes, "created_at": t.created_at.isoformat(),
             "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None, "revoked": bool(t.revoked_at),
             "masked": _mask_token(t), "copyable": bool(t.token_enc)}
            for t in db.scalars(select(ApiToken).order_by(ApiToken.id))]


def _mask_token(t: ApiToken) -> str:
    """列表里只给带星号的形式（保留前缀与尾 6 位）；旧 token 只有哈希，原文已无法找回。"""
    if not t.token_enc:
        return "（旧 token，原文不可见）"
    tok = security.decrypt(t.token_enc).decode()
    return tok[:4] + "*" * 12 + tok[-6:]


@router.get("/tokens/{tid}/value")
def token_value(tid: int, db: Session = Depends(get_db), _=Depends(admin)):
    from fastapi.responses import PlainTextResponse
    t = db.get(ApiToken, tid)
    if not t or not t.token_enc:
        raise HTTPException(404, "该 token 没有保存原文（创建于此功能之前），请新建一个")
    return PlainTextResponse(security.decrypt(t.token_enc).decode(), headers={"Cache-Control": "no-store"})


@router.post("/tokens")
def create_token(body: dict, db: Session = Depends(get_db), _=Depends(admin)):
    tok = security.new_api_token()
    t = ApiToken(name=body.get("name") or "cli", token_hash=security.hash_token(tok), scopes=["credentials:write"],
                 token_enc=security.encrypt(tok.encode()))
    db.add(t)
    db.commit()
    return {"id": t.id, "token": tok}


@router.post("/tokens/{tid}/regenerate")
def regenerate_token(tid: int, db: Session = Depends(get_db), _=Depends(admin)):
    """换一个新的 token 原文（名称/权限不变，旧值立即失效；已吊销的会恢复可用）。"""
    t = db.get(ApiToken, tid)
    if not t:
        raise HTTPException(404, "token 不存在")
    tok = security.new_api_token()
    t.token_hash, t.token_enc, t.revoked_at, t.last_used_at = security.hash_token(tok), security.encrypt(tok.encode()), None, None
    db.commit()
    return {"id": t.id, "token": tok}


@router.delete("/tokens/{tid}")
def delete_token(tid: int, db: Session = Depends(get_db), _=Depends(admin)):
    t = db.get(ApiToken, tid)
    if t:
        db.delete(t)
        db.commit()
    return {"ok": True}


# ---------------- 推送(Bark) ----------------
@router.get("/settings/bark")
def get_bark(_=Depends(admin)):
    return notify.get_public()


@router.put("/settings/bark")
def put_bark(body: dict, _=Depends(admin)):
    try:
        notify.save(body.get("server", ""), body.get("key"), body.get("on_success", True), body.get("on_failure", True),
                    body.get("on_auth", True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return notify.get_public()


@router.post("/settings/bark/test")
async def test_bark(_=Depends(admin)):
    if not notify.get_public()["configured"]:
        raise HTTPException(400, "请先保存 device key")
    err = await notify.send("Sign 测试推送", "收到这条说明 Bark 配置正确", kind="test")
    if err:
        raise HTTPException(502, err)
    return {"ok": True}
