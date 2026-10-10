"""业务逻辑：种子数据、凭证入库、签到执行、待签到选择、通知。"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, notify, security
from . import scripts_store
from .db import (Account, Credential, Platform, Run, RunEvent, ScriptVersion, SessionLocal,
                 now, today)
from .runner.executor import execute

_sem = asyncio.Semaphore(config.MAX_CONCURRENCY)
_running: set[int] = set()  # 账号级互斥
OK = ("success", "already")


class ServiceError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


# ---------- 种子：脚本目录 -> 数据库 ----------
def seed(db: Session):
    for c in scripts_store.sync(db):
        print(f"[sign] scripts: {c}", flush=True)


# ---------- 脚本版本 ----------
def check_source(src: str):
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise ServiceError(f"语法错误: 第 {e.lineno} 行 {e.msg}")
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "run" not in names:
        raise ServiceError("脚本必须定义 run(ctx)")


def publish(db: Session, pf: Platform, source: str, note: str, author="admin", activate=False, write_files=True) -> ScriptVersion:
    check_source(source)
    sha = hashlib.sha256(source.encode()).hexdigest()
    last = db.scalar(select(ScriptVersion).where(ScriptVersion.platform_id == pf.id).order_by(ScriptVersion.version.desc()))
    if last and last.sha256 == sha:
        raise ServiceError("内容与最新版本相同，无需发布", 409)
    v = ScriptVersion(platform_id=pf.id, version=(last.version + 1) if last else 1, source=source, sha256=sha,
                      note=note, author=author, parent_version_id=pf.active_version_id)
    db.add(v)
    db.flush()
    if activate:
        pf.active_version_id = v.id
    if write_files:  # 脚本以文件为准：versions/v<N>.py 只增不改，启用则同步 current.py
        scripts_store.write_version(pf.key, v.version, source)
        if activate:
            scripts_store.write_current(pf.key, source)
    return v


def resolve_version(db: Session, acc: Account) -> ScriptVersion:
    vid = acc.platform.active_version_id
    v = db.get(ScriptVersion, vid) if vid else None
    if not v:
        raise ServiceError("平台没有启用的脚本版本")
    return v


# ---------- 凭证 ----------
def _ctx_base(acc: Account, is_test=False, creds=None) -> dict:
    return {"platform": acc.platform.key, "account": acc.name, "today": today(),
            "now": now().isoformat(), "is_test": is_test,
            "config": (acc.platform.manifest or {}).get("config") or {},
            "state": acc.state or {}, "credentials": creds or {}}


def load_creds(db: Session, acc: Account) -> dict:
    out = {}
    for c in db.scalars(select(Credential).where(Credential.account_id == acc.id)):
        out[c.name] = {"b64": base64.b64encode(security.decrypt(c.value_enc)).decode(), "kind": c.kind}
    return out


def _parse_dt(s):
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo:
        from .db import TZINFO
        d = d.astimezone(TZINFO).replace(tzinfo=None)
    return d


async def _hook(acc, ver, name, raw, creds=None):
    r = await execute("credential", ver.source, _ctx_base(acc, creds=creds), {"name": name, "raw_b64": base64.b64encode(raw).decode()},
                      timeout=20)
    res = r["result"]
    if r["timed_out"] or not res:
        raise ServiceError("凭证解析超时/失败: " + (r["stderr"][-300:] or "无输出"), 422)
    if res["status"] == "rejected":
        raise ServiceError(res["message"], 422)
    if res["status"] != "ok":
        raise ServiceError(res.get("message") or "凭证解析失败", 422)
    return base64.b64decode(res["value_b64"]), res.get("meta") or {}, _parse_dt(res.get("expires_at"))


async def store_credential_async(db: Session, acc: Account, name: str, raw: bytes, filename="", kind=None) -> Credential:
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise ServiceError("凭证过大", 413)
    schema = {c["name"]: c for c in (acc.platform.manifest or {}).get("credentials", [])}
    if schema and name not in schema:
        raise ServiceError(f"平台未声明凭证 {name}，可用: {', '.join(schema)}")
    kind = kind or schema.get(name, {}).get("kind", "text")
    value, meta, expires = raw, {}, None
    vid = acc.platform.active_version_id
    ver = db.get(ScriptVersion, vid) if vid else None
    if ver:
        value, meta, expires = await _hook(acc, ver, name, raw, load_creds(db, acc))  # 钩子可读取该账号已提交的其他凭证
    return _save(db, acc, name, value, kind, filename, meta, expires)


def resolve_account(db: Session, acc: Account, cred: Credential) -> Account:
    """自动命名：凭证钩子在 meta 里给出 identity（稳定 ID）和 label（账号名）。
    同平台已有相同 identity 的账号 -> 并入该账号；否则把 acc 改名为 label。重名时追加 identity 尾号。"""
    ident, label = (cred.meta or {}).get("identity"), (cred.meta or {}).get("label")
    if not ident or not label:
        return acc
    same = [c for c in db.scalars(select(Credential).join(Account).where(Account.platform_id == acc.platform_id, Account.id != acc.id))
            if (c.meta or {}).get("identity") == ident]
    target = acc
    if same:
        target = db.get(Account, same[0].account_id)
        for c in db.scalars(select(Credential).where(Credential.account_id == acc.id)):
            for old in db.scalars(select(Credential).where(Credential.account_id == target.id, Credential.name == c.name)):
                db.delete(old)
            db.flush()
            c.account_id = target.id
        db.flush()
        db.delete(db.get(Account, acc.id))
    name, n = label, 1
    while db.scalar(select(Account).where(Account.platform_id == target.platform_id, Account.name == name, Account.id != target.id)):
        name, n = f"{label} ·{str(ident)[-4:]}" + ("" if n == 1 else f"{n}"), n + 1
    target.name = name
    db.commit()
    return target


def _save(db, acc, name, value: bytes, kind, filename, meta, expires) -> Credential:
    c = db.scalar(select(Credential).where(Credential.account_id == acc.id, Credential.name == name))
    if not c:
        c = Credential(account_id=acc.id, name=name)
        db.add(c)
    c.kind, c.filename, c.size = kind, filename, len(value)
    c.value_enc = security.encrypt(value)
    c.meta, c.expires_at, c.updated_at = meta, expires, now()
    c.status = "expired" if expires and expires < now() else ("valid" if expires else "unknown")
    db.commit()
    return c


# ---------- 执行 ----------
def last_runs_today(db: Session) -> dict[int, Run]:
    d = {}
    for r in db.scalars(select(Run).where(Run.local_date == today(), Run.trigger != "test").order_by(Run.id)):
        d[r.account_id] = r
    return d


def pending_account_ids(db: Session) -> list[int]:
    """今日尚无 success/already 的启用账号；need_auth 且凭证未更新的跳过。"""
    last = last_runs_today(db)
    out = []
    q = select(Account).join(Platform).where(Account.enabled.is_(True), Platform.enabled.is_(True))
    for acc in db.scalars(q):
        r = last.get(acc.id)
        if r and r.status in OK:
            continue
        if r and r.status == "need_auth":
            newest = max((c.updated_at for c in db.scalars(select(Credential).where(Credential.account_id == acc.id))), default=None)
            if not newest or newest <= (r.finished_at or r.started_at):
                continue
        out.append(acc.id)
    return out


async def run_account(account_id: int, trigger: str, source_override: str | None = None) -> int:
    """执行一次签到并落库，返回 run_id。"""
    if account_id in _running:
        raise ServiceError("该账号正在执行中", 409)
    _running.add(account_id)
    try:
        async with _sem:
            with SessionLocal() as db:
                acc = db.get(Account, account_id)
                if not acc:
                    raise ServiceError("账号不存在", 404)
                is_test = trigger == "test"
                ver = resolve_version(db, acc) if not source_override else None
                n = db.query(Run).filter(Run.account_id == acc.id, Run.local_date == today(), Run.trigger != "test").count()
                run = Run(account_id=acc.id, script_version_id=ver.id if ver else None, trigger=trigger,
                          local_date=today(), attempt_no=n + 1)
                db.add(run)
                db.commit()
                run_id = run.id
                timeout = (acc.platform.manifest or {}).get("timeout_sec", config.DEFAULT_TIMEOUT)
                source = source_override or ver.source
                ctx = _ctx_base(acc, is_test, load_creds(db, acc))
                t0 = now()
            r = await execute("run", source, ctx, timeout=timeout)
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                acc = db.get(Account, account_id)
                for lg in r["logs"]:
                    db.add(RunEvent(run_id=run_id, level=lg.get("level", "info"), tag=lg.get("tag", ""),
                                    message=lg.get("message", ""), data=lg.get("data")))
                res = r["result"]
                if r["timed_out"]:
                    run.status, run.message = "timeout", "脚本执行超时"
                elif not res:
                    run.status, run.message = "failed", "脚本无结果: " + r["stderr"][-300:]
                else:
                    run.status = res["status"] if res["status"] in ("success", "already", "failed", "need_auth") else "failed"
                    run.message = (res.get("message") or "")[:1000]
                    pts = res.get("points")
                    run.points = int(pts) if isinstance(pts, (int, float)) or (isinstance(pts, str) and pts.isdigit()) else None
                if not is_test:
                    for name, b64 in r["saved_creds"].items():
                        _save(db, acc, name, base64.b64decode(b64), "json", "", {}, None)
                    if r["state"]:
                        acc.state = {**(acc.state or {}), **r["state"]}
                    if run.status == "need_auth":
                        for c in db.scalars(select(Credential).where(Credential.account_id == acc.id)):
                            c.status = "expired"
                run.finished_at = now()
                run.duration_ms = int((run.finished_at - t0).total_seconds() * 1000)
                db.commit()
                label, status, message, points = f"{acc.platform.name}/{acc.name}", run.status, run.message, run.points
                first_ok = status == "success" and not db.scalar(select(Run.id).where(
                    Run.account_id == acc.id, Run.local_date == run.local_date, Run.status == "success", Run.id != run.id))
            if not is_test:
                if status in ("failed", "need_auth", "timeout"):
                    await send_webhook(f"[{label}] {status}: {message}")
                    if status == "need_auth":   # 脚本仅在服务端返回 401/403 或本地凭证已过期时才给出 need_auth
                        await notify.send("需要重新授权", f"{label}\n{message}", kind="auth")
                    else:
                        await notify.send("签到失败", f"{label}\n{message}", kind="failure")
                elif first_ok:   # 仅当天首次签到成功才推送
                    await notify.send("签到成功", f"{label}\n{message}" + (f"\n积分 +{points}" if points else ""), kind="success")
            return run_id
    finally:
        _running.discard(account_id)


async def run_many(ids: list[int], trigger: str):
    await asyncio.gather(*(run_account(i, trigger) for i in ids), return_exceptions=True)


async def run_pending(trigger: str):
    with SessionLocal() as db:
        ids = pending_account_ids(db)
    await run_many(ids, trigger)


async def run_all(trigger: str):
    with SessionLocal() as db:
        ids = [a.id for a in db.scalars(select(Account).join(Platform).where(Account.enabled.is_(True), Platform.enabled.is_(True)))]
    await run_many(ids, trigger)


def recover_interrupted():
    with SessionLocal() as db:
        for r in db.scalars(select(Run).where(Run.status == "running")):
            r.status, r.message, r.finished_at = "failed", "服务重启，执行被中断", now()
        db.commit()


async def send_webhook(text: str):
    if not config.WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(config.WEBHOOK_URL, json={"text": text, "msg": text})
    except Exception:
        pass
