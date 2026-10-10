from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config

TZINFO = ZoneInfo(config.TZ)


def now() -> datetime:
    """本地(业务时区)naive 时间，库内统一存这个。"""
    return datetime.now(TZINFO).replace(tzinfo=None)


def today() -> str:
    return now().strftime("%Y-%m-%d")


engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False} if config.DB_URL.startswith("sqlite") else {})
if config.DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _pragma(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Platform(Base):
    __tablename__ = "platform"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)  # credentials 表单 / config / timeout
    active_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ScriptVersion(Base):
    __tablename__ = "script_version"
    __table_args__ = (UniqueConstraint("platform_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(String(500), default="")
    author: Mapped[str] = mapped_column(String(64), default="admin")
    parent_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ScriptDraft(Base):
    __tablename__ = "script_draft"
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    base_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("platform_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # 脚本持久 KV
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    platform: Mapped[Platform] = relationship()


class Credential(Base):
    __tablename__ = "credential"
    __table_args__ = (UniqueConstraint("account_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="text")
    value_enc: Mapped[bytes] = mapped_column(LargeBinary)
    filename: Mapped[str] = mapped_column(String(255), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # valid|expired|unknown
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Run(Base):
    __tablename__ = "run"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    script_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))  # schedule|retry|manual|test
    local_date: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|already|failed|need_auth|timeout
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account: Mapped[Account] = relationship()


class RunEvent(Base):
    __tablename__ = "run_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    level: Mapped[str] = mapped_column(String(8), default="info")
    tag: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ApiToken(Base):
    __tablename__ = "api_token"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=lambda: ["credentials:write"])
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)   # 加密后的原文，旧 token 为空（不可复制）


class Setting(Base):
    """键值配置（页面可改）。敏感字段在 value 内已加密。"""
    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:   # 轻量迁移：给已有的 api_token 表补列，详见 docs/sql/20261010_api_token_add_token_enc.sql
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(api_token)")}
        if "token_enc" not in cols:
            conn.exec_driver_sql("ALTER TABLE api_token ADD COLUMN token_enc BLOB")


def get_db():
    with SessionLocal() as s:
        yield s
