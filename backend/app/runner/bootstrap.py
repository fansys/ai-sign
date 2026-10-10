"""在隔离子进程内运行签到脚本。

协议：
  stdin  : 一个 JSON 对象 {mode, source, ctx, hook}
  stdout : JSON Lines（仅本文件写入；脚本里的 print 被重定向到 stderr）
           {"t":"log"|"save_cred"|"state"|"result", ...}
凭证只经 stdin 进入进程，不落盘、不进环境变量。
"""
import asyncio
import base64
import json
import os
import sys
import traceback

_proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr  # 脚本 print 不污染协议通道


def emit(**kw):
    _proto.write(json.dumps(kw, ensure_ascii=False, default=str) + "\n")
    _proto.flush()


class CredentialError(Exception):
    """on_credential 中抛出：拒绝保存该凭证。"""


class AuthExpired(Exception):
    """run 中抛出：登录态失效，需要重新提交凭证（不再重试）。"""


class _Log:
    def __init__(self, ctx):
        self._ctx = ctx

    def _w(self, level, tag, msg, **data):
        emit(t="log", level=level, tag=tag, message=self._ctx._mask(str(msg)), data=data or None)

    def info(self, tag, msg="", **d):
        self._w("info", tag, msg, **d)

    def warn(self, tag, msg="", **d):
        self._w("warn", tag, msg, **d)

    def error(self, tag, msg="", **d):
        self._w("error", tag, msg, **d)


class _State:
    def __init__(self, d):
        self._d = dict(d or {})

    def get(self, k, default=None):
        return self._d.get(k, default)

    def set(self, k, v):
        self._d[k] = v
        emit(t="state", key=k, value=v)


class Ctx:
    def __init__(self, raw):
        self.platform = raw.get("platform", "")
        self.account = raw.get("account", "")
        self.today = raw["today"]
        self.now = raw["now"]
        self.is_test = bool(raw.get("is_test"))
        self.config = raw.get("config") or {}
        self.state = _State(raw.get("state"))
        self._creds = {k: base64.b64decode(v["b64"]) for k, v in (raw.get("credentials") or {}).items()}
        self._secrets = set()
        for b in self._creds.values():
            self._collect_secrets(b)
        self.log = _Log(self)
        self._http = None

    # ---- 日志脱敏：凭证里的长字符串在日志中只留尾 6 位 ----
    def _collect_secrets(self, b: bytes):
        try:
            txt = b.decode("utf-8")
        except UnicodeDecodeError:
            return
        try:
            def walk(o):
                if isinstance(o, dict):
                    [walk(v) for v in o.values()]
                elif isinstance(o, list):
                    [walk(v) for v in o]
                elif isinstance(o, str) and len(o) >= 16:
                    self._secrets.add(o)
            walk(json.loads(txt))
        except ValueError:
            if len(txt) >= 16:
                self._secrets.add(txt.strip())

    def _mask(self, s: str) -> str:
        for sec in self._secrets:
            if sec in s:
                s = s.replace(sec, "…" + sec[-6:])
        return s

    def add_secret(self, s: str):
        if s and len(s) >= 16:
            self._secrets.add(s)

    # ---- 凭证 ----
    def has_cred(self, name) -> bool:
        return name in self._creds

    def cred_bytes(self, name, default=None) -> bytes:
        return self._creds.get(name, default)

    def cred(self, name, default=None) -> str:
        b = self._creds.get(name)
        return default if b is None else b.decode("utf-8")

    def cred_json(self, name, default=None):
        b = self._creds.get(name)
        return default if b is None else json.loads(b.decode("utf-8"))

    def save_cred(self, name, value):
        if not isinstance(value, (str, bytes)):
            value = json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            value = value.encode()
        self._creds[name] = value
        emit(t="save_cred", name=name, b64=base64.b64encode(value).decode())

    # ---- HTTP ----
    @property
    def http(self):
        if self._http is None:
            import httpx

            def on_resp(r):
                r.read()
                u = r.request.url
                self.log.info("http", f"{r.request.method} {u.scheme}://{u.host}{u.path} -> {r.status_code}")

            self._http = httpx.Client(timeout=30, follow_redirects=True,
                                      event_hooks={"response": [on_resp]})
        return self._http


def main():
    req = json.loads(sys.stdin.read())
    ctx = Ctx(req["ctx"])
    ns = {"__name__": "sign_script", "CredentialError": CredentialError, "AuthExpired": AuthExpired}
    try:
        exec(compile(req["source"], "<script>", "exec"), ns)
    except SyntaxError as e:
        emit(t="result", status="failed", message=f"脚本语法错误: {e}")
        return

    def call(fn, *a):
        r = fn(*a)
        if asyncio.iscoroutine(r):
            r = asyncio.run(r)
        return r

    mode = req["mode"]
    try:
        if mode == "credential":
            hook = ns.get("on_credential")
            raw = base64.b64decode(req["hook"]["raw_b64"])
            name = req["hook"]["name"]
            if hook is None:
                emit(t="result", status="ok", value_b64=base64.b64encode(raw).decode(), meta={}, expires_at=None)
                return
            out = call(hook, ctx, name, raw) or {}
            v = out.get("value", raw)
            if not isinstance(v, (str, bytes)):
                v = json.dumps(v, ensure_ascii=False)
            if isinstance(v, str):
                v = v.encode()
            emit(t="result", status="ok", value_b64=base64.b64encode(v).decode(),
                 meta=out.get("meta") or {}, expires_at=out.get("expires_at"))
        else:
            fn = ns.get("run")
            if fn is None:
                emit(t="result", status="failed", message="脚本未定义 run(ctx)")
                return
            out = call(fn, ctx) or {}
            emit(t="result", status=out.get("status", "failed"), points=out.get("points"),
                 message=ctx._mask(str(out.get("message", ""))), data=out.get("data"))
    except CredentialError as e:
        emit(t="result", status="rejected", message=str(e))
    except AuthExpired as e:
        emit(t="result", status="need_auth", message=ctx._mask(str(e)) or "登录态失效，请重新提交凭证")
    except Exception as e:  # noqa
        tb = ctx._mask(traceback.format_exc(limit=6))
        emit(t="log", level="error", tag="exception", message=tb, data=None)
        emit(t="result", status="failed", message=ctx._mask(f"{type(e).__name__}: {e}"))


if __name__ == "__main__":
    main()
