"""拉起隔离子进程执行脚本，解析事件流。"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

BOOTSTRAP = str(Path(__file__).with_name("bootstrap.py"))


def _limits(timeout: int):
    def f():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 10, timeout + 10))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
        except (ValueError, OSError):
            pass
        os.setsid()
    return f


async def execute(mode: str, source: str, ctx: dict, hook: dict | None = None, timeout: int = 60) -> dict:
    """返回 {result, logs, saved_creds, state, timed_out, stderr}"""
    payload = json.dumps({"mode": mode, "source": source, "ctx": ctx, "hook": hook}).encode()
    out = {"result": None, "logs": [], "saved_creds": {}, "state": {}, "timed_out": False, "stderr": ""}
    with tempfile.TemporaryDirectory(prefix="sign-run-") as tmp:
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": tmp, "LANG": "C.UTF-8",
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        if sys.platform == "win32":  # 开发机兜底，生产在 Linux 容器
            env = {**os.environ}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", BOOTSTRAP, cwd=tmp, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limits(timeout) if sys.platform != "win32" else None)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
        except asyncio.TimeoutError:
            out["timed_out"] = True
            try:
                os.killpg(proc.pid, 9)
            except Exception:
                proc.kill()
            await proc.wait()
            return out
    out["stderr"] = stderr.decode("utf-8", "replace")[-2000:]
    for line in stdout.decode("utf-8", "replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("t")
        if t == "log":
            out["logs"].append(ev)
        elif t == "save_cred":
            out["saved_creds"][ev["name"]] = ev["b64"]
        elif t == "state":
            out["state"][ev["key"]] = ev["value"]
        elif t == "result":
            out["result"] = ev
    return out
