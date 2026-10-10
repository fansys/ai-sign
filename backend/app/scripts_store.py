"""脚本的文件存储与同步。

目录约定（每个平台一个目录，目录名 = 平台 key）：
    scripts/<key>/manifest.json      平台名称、凭证声明、config、超时
    scripts/<key>/current.py         当前启用版本（始终与 active 版本一致，可直接用编辑器改）
    scripts/<key>/versions/v<N>.py   历史版本，只增不改

数据库只做索引与运行记录；脚本源码以文件为准：
  - 发布版本  -> 写 versions/v<N>.py
  - 启用/回滚 -> 覆盖 current.py
  - 手工改了 current.py 后重启或 POST /api/scripts/sync -> 自动登记为新版本并启用
  - 新建一个含 current.py 的目录，同步后即成为新平台
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import Platform, ScriptVersion

MANIFEST = "manifest.json"


def pdir(key: str) -> Path:
    return config.SCRIPTS_DIR / key


def write_version(key: str, n: int, source: str):
    d = pdir(key) / "versions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"v{n}.py").write_text(source, encoding="utf-8")


def write_current(key: str, source: str):
    pdir(key).mkdir(parents=True, exist_ok=True)
    (pdir(key) / "current.py").write_text(source, encoding="utf-8")


def write_manifest(pf: Platform):
    pdir(pf.key).mkdir(parents=True, exist_ok=True)
    doc = {"name": pf.name, **(pf.manifest or {})}
    (pdir(pf.key) / MANIFEST).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_manifest(d: Path, key: str) -> tuple[str, dict]:
    f = d / MANIFEST
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    name = doc.pop("name", key)
    doc.setdefault("credentials", [{"name": "auth", "kind": "text", "required": True, "label": "凭证"}])
    doc.setdefault("config", {})
    return name, doc


def _seed_dirs():
    """首次运行：把内置脚本目录里缺失的平台复制到 SCRIPTS_DIR。"""
    config.SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    if config.BUILTIN_SCRIPTS_DIR.resolve() == config.SCRIPTS_DIR.resolve() or not config.BUILTIN_SCRIPTS_DIR.is_dir():
        return
    for d in config.BUILTIN_SCRIPTS_DIR.iterdir():
        if d.is_dir() and not (config.SCRIPTS_DIR / d.name).exists():
            shutil.copytree(d, config.SCRIPTS_DIR / d.name)


def sync(db: Session) -> list[str]:
    """文件 -> 数据库。返回本次发生的变更说明。"""
    from . import services  # 避免循环导入
    _seed_dirs()
    changes = []
    for d in sorted(p for p in config.SCRIPTS_DIR.iterdir() if p.is_dir()):
        key = d.name
        cur = d / "current.py"
        vers = sorted((d / "versions").glob("v*.py"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)) if (d / "versions").is_dir() else []
        if not cur.exists() and not vers:
            continue
        pf = db.scalar(select(Platform).where(Platform.key == key))
        if not pf:
            name, man = _read_manifest(d, key)
            pf = Platform(key=key, name=name, manifest=man)
            db.add(pf)
            db.flush()
            changes.append(f"{key}: 新平台")
        has = db.scalar(select(ScriptVersion).where(ScriptVersion.platform_id == pf.id))
        if not has:  # 首次导入：历史版本按序登记
            for f in vers:
                try:
                    services.publish(db, pf, f.read_text(encoding="utf-8"), f"导入 {f.name}", author="file", activate=True, write_files=False)
                    changes.append(f"{key}: 导入 {f.name}")
                except services.ServiceError:
                    pass
        active = db.get(ScriptVersion, pf.active_version_id) if pf.active_version_id else None
        if cur.exists():
            src = cur.read_text(encoding="utf-8")
            if not active or src != active.source:
                try:
                    v = services.publish(db, pf, src, "同步 current.py", author="file", activate=True, write_files=True)
                    changes.append(f"{key}: current.py 已登记为 v{v.version} 并启用")
                except services.ServiceError as e:
                    if e.code == 409:  # 与最新版相同但未启用 => 启用最新版
                        last = db.scalar(select(ScriptVersion).where(ScriptVersion.platform_id == pf.id).order_by(ScriptVersion.version.desc()))
                        pf.active_version_id = last.id
                    else:
                        changes.append(f"{key}: current.py 无效，已忽略（{e}）")
        elif active:
            write_current(key, active.source)
        if not (d / MANIFEST).exists():
            write_manifest(pf)
    db.commit()
    return changes
