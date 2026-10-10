"""真实端到端：本机客户端数据文件 -> sign-cli(真实进程) -> 真实 uvicorn 服务 -> 解密入库 -> 脚本文件执行签到 -> 假平台接口。

覆盖三个平台：
  Qoder CN  : macOS(钥匙串口令+AES-128-CBC) 与 Windows(DPAPI 密钥+AES-256-GCM) 两种 auth.v1.dat，CLI 本地解密
  Trae CN   : storage.json 原样上传，服务端解 iCubeAuthInfo
  WorkBuddy : .info 原样上传，服务端解 $wbEncrypted
"""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

import samples

ROOT = Path(__file__).resolve().parents[2]
ADMIN = "adm_live_e2e"
QODER_MAC_TOKEN, QODER_WIN_TOKEN = "QODER_TOKEN_MAC_0123456789", "QODER_TOKEN_WIN_0123456789"
DEVICE_ID = "7777001"


# ---------------- 假平台接口：校验必需请求头 ----------------
class Platforms(BaseHTTPRequestHandler):
    state = {"claimed": set(), "trae": set(), "wb": set()}
    calls = []

    def log_message(self, *a): pass

    def _j(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self): self._h()
    def do_POST(self): self._h()

    def _h(self):
        body = self._body() if self.command == "POST" else {}
        p, H = self.path, self.headers
        Platforms.calls.append((self.command, p))
        if p.startswith("/q/"):
            tok = (H.get("Authorization") or "").removeprefix("Bearer ")
            if tok not in (QODER_MAC_TOKEN, QODER_WIN_TOKEN):
                return self._j({"code": "TOKEN_INVALID"}, 401)          # 裸 token / 无 Bearer 都会 401
            if p == "/q/sash/api/v1/me/campaigns":
                if H.get("Cosy-ClientType") != "10":
                    return self._j({"campaigns": []})                   # 缺 Cosy-ClientType：200 但空数组（文中的坑）
                st = "CLAIMED" if tok in self.state["claimed"] else "CLAIMABLE"
                return self._j({"campaigns": [{"campaignId": "c1", "campaignKey": "daily", "actionType": "CLAIM_BENEFIT", "claimStatus": st}]})
            if p == "/q/sash/api/v1/me/campaigns/c1/claim" and self.command == "POST":
                replay = tok in self.state["claimed"]
                self.state["claimed"].add(tok)
                return self._j({"grantId": "g1", "status": "CLAIMED", "replayed": replay, "benefit": {"kind": "CREDITS", "amount": 100}})
        elif p.startswith("/t/"):
            if H.get("Authorization") != f"Cloud-IDE-JWT {samples.TRAE_TOKEN}" or H.get("x-device-id") != DEVICE_ID:
                return self._j({"message": "bad auth/device"}, 401)
            if body.get("req_source") != 1:
                return self._j({"message": "bad body"}, 400)
            if p == "/t/status":
                return self._j({"code": 0, "data": {"checked_in": "t" in self.state["trae"], "enable": True, "credits": 150}})
            if p == "/t/claim":
                self.state["trae"].add("t")
                return self._j({"code": 0, "data": {"credits": 50}})
        elif p.startswith("/w/"):
            if (H.get("Authorization") != f"Bearer {samples.WB_TOKEN}" or H.get("X-User-Id") != "u9" or H.get("X-Domain") != "d.example"):
                return self._j({"code": 401, "msg": "unauthorized"}, 401)
            if p == "/w/checkin-status":
                return self._j({"code": 0, "data": {"today_checked_in": "w" in self.state["wb"]}})
            if p == "/w/daily-checkin":
                if "w" in self.state["wb"]:
                    return self._j({"code": 10001, "msg": "already"})
                self.state["wb"].add("w")
                return self._j({"code": 0, "data": {"credit": 100}})
        self._j({"msg": "not found"}, 404)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("live")
    fake = ThreadingHTTPServer(("127.0.0.1", 0), Platforms)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    fake_base = f"http://127.0.0.1:{fake.server_port}"

    # ---- 1. 伪造“用户电脑”上三个客户端的真实格式数据文件 ----
    home = tmp / "client"
    mac = home / "mac" / "com.qodercn.app.stable"; mac.mkdir(parents=True)
    (mac / "auth.v1.dat").write_bytes(samples.qoder_dat_mac("keychain-pass", {**samples.QODER_AUTH, "token": QODER_MAC_TOKEN}))
    win = home / "win" / "com.qodercn.app.stable"; win.mkdir(parents=True)
    import base64
    dpapi_key = os.urandom(32)
    (win / "Local State").write_text(json.dumps({"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI" + b"\x01" * 40).decode()}}))
    (win / "auth.v1.dat").write_bytes(samples.qoder_dat_windows(dpapi_key, {**samples.QODER_AUTH, "token": QODER_WIN_TOKEN}))
    trae = home / "Trae CN"; (trae / "User" / "globalStorage").mkdir(parents=True); (trae / "ahanet").mkdir()
    (trae / "User" / "globalStorage" / "storage.json").write_text(json.dumps(samples.trae_storage()))
    (trae / "ahanet" / "tt_net_config.config").write_text(json.dumps({"device_id": int(DEVICE_ID)}))
    wb = home / "auth"; wb.mkdir()
    (wb / "workbuddy-desktop.info").write_text(json.dumps(samples.wb_info(4102444800000)))

    # ---- 2. 启动真实服务（独立进程、独立数据目录、脚本目录从仓库复制）----
    port = free_port()
    data, scripts = tmp / "data", tmp / "scripts"
    srv_env = {**os.environ, "SIGN_DATA_DIR": str(data), "SIGN_SCRIPTS_DIR": str(scripts), "SIGN_BUILTIN_SCRIPTS_DIR": str(ROOT / "scripts"),
               "SIGN_ADMIN_TOKEN": ADMIN, "SIGN_SCHEDULER": "0"}
    log = open(tmp / "server.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                            cwd=ROOT / "backend", env=srv_env, stdout=log, stderr=log)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(base + "/api/status", headers={"Authorization": f"Bearer {ADMIN}"}).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        proc.kill(); pytest.fail("server did not start:\n" + (tmp / "server.log").read_text())

    adm = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {ADMIN}"}, timeout=30)
    for key, path in (("qoder", "/q"), ("trae", "/t"), ("workbuddy", "/w")):   # 指向假平台
        m = next(p for p in adm.get("/api/platforms").json() if p["key"] == key)["manifest"]
        m["config"]["api_base"] = fake_base + path
        assert adm.patch(f"/api/platforms/{key}", json={"manifest": m}).status_code == 200
    apikey = adm.post("/api/tokens", json={"name": "cli"}).json()["token"]

    conf = tmp / "sign.conf"
    conf.write_text(f"[server]\nurl = {base}\napikey = {apikey}\n")
    yield dict(tmp=tmp, adm=adm, base=base, home=home, conf=conf, scripts=scripts, data=data, apikey=apikey, dpapi_key=dpapi_key)
    proc.terminate(); proc.wait(5); fake.shutdown()


def run_cli(env, *args, mode):
    """真实运行 sign-cli；mode=mac/win 只用于在 Linux 上模拟平台判断与本机密钥来源（钥匙串/DPAPI）。"""
    wrapper = f'''
import sys
sys.path.insert(0, {str(ROOT / "cli")!r})
from signcli import extractors, cli
mode = {mode!r}
extractors.IS_MAC, extractors.IS_WIN = (mode == "mac"), (mode == "win")
orig = extractors.discover_qoder
extractors.discover_qoder = lambda *a, **k: orig(*a, unprotect=lambda b: bytes.fromhex({env["dpapi_key"].hex()!r}), get_password=lambda: "keychain-pass", **k)
sys.exit(cli.main(sys.argv[1:]))
'''
    r = subprocess.run([sys.executable, "-c", wrapper, *args], capture_output=True, text=True,
                       env={**os.environ, "SIGN_CLI_CONFIG": str(env["conf"])}, timeout=60)
    return r


def wait_results(adm, n, status_not="running"):
    day = time.strftime("%Y-%m-%d")
    for _ in range(80):
        d = adm.get(f"/api/days/{day}").json()
        if len(d["results"]) >= n and all(r["status"] != status_not for r in d["results"]):
            return d
        time.sleep(0.25)
    return d


def test_1_cli_extracts_decrypts_and_uploads(env):
    h = env["home"]
    # scan 只发现，不触碰钥匙串
    r = run_cli(env, "scan", "-p", "qoder", "--qoder-dir", str(h / "mac" / "com.qodercn.app.stable"), mode="mac")
    assert r.returncode == 0 and "Qoder CN" in r.stdout
    out = ""
    for args, mode in (
        (["-y", "-p", "qoder", "-a", "mac-account", "--qoder-dir", str(h / "mac" / "com.qodercn.app.stable")], "mac"),
        (["-y", "-p", "qoder", "-a", "win-account", "--qoder-dir", str(h / "win" / "com.qodercn.app.stable")], "win"),
        (["-y", "-p", "trae", "--trae-dir", str(h / "Trae CN")], "mac"),
        (["-y", "-p", "workbuddy", "--workbuddy-dir", str(h / "auth")], "mac"),
    ):
        r = run_cli(env, "push", *args, mode=mode)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[OK]" in r.stdout
        out += r.stdout + r.stderr
    # CLI 输出不泄露任何 token / 口令
    for secret in (QODER_MAC_TOKEN, QODER_WIN_TOKEN, samples.TRAE_TOKEN, samples.WB_TOKEN, "keychain-pass", env["apikey"]):
        assert secret not in out

    accs = {(a["platform"], a["name"]): a for a in env["adm"].get("/api/accounts").json()}
    assert set(accs) == {("qoder", "mac-account"), ("qoder", "win-account"), ("trae", "default"), ("workbuddy", "default")}
    for (plat, _), a in accs.items():
        st = {c["name"]: c["status"] for c in a["credentials"]}["auth"]
        assert st == ("unknown" if plat == "trae" else "valid")      # Trae 登录态不带到期时间 -> unknown
    # 服务端解密成功：meta 来自解出的内容
    assert accs[("qoder", "mac-account")]["credentials"][0]["meta"]["user"] == "alice"
    assert accs[("workbuddy", "default")]["credentials"][0]["meta"]["uid"] == "u9"
    # Trae 的 device_id 由服务端从 tt_net_config.config 提取
    trae_creds = {c["name"]: c for c in accs[("trae", "default")]["credentials"]}
    assert set(trae_creds) == {"auth", "device_id"}


def test_2_credentials_encrypted_at_rest(env):
    blob = b"".join(open(p, "rb").read() for p in env["data"].glob("sign.db*"))
    for secret in (QODER_MAC_TOKEN, QODER_WIN_TOKEN, samples.TRAE_TOKEN.encode().decode(), samples.WB_TOKEN, "REFRESH_SECRET_000000", "unrelated-data"):
        assert secret.encode() not in blob, secret
    # 接口不回显明文
    assert samples.WB_TOKEN not in env["adm"].get("/api/accounts").text


def test_3_scripts_checkin_via_files(env):
    adm = env["adm"]
    # 脚本以文件形式存在，current.py 为启用版本
    for k in ("qoder", "trae", "workbuddy"):
        d = env["scripts"] / k
        assert (d / "current.py").read_text() == (d / "versions" / "v1.py").read_text()
        assert json.loads((d / "manifest.json").read_text())["config"]["api_base"].startswith("http://127.0.0.1")
    assert adm.post("/api/runs", json={}).status_code == 200
    d = wait_results(adm, 4)
    res = {(r["platform"], r["account"]): r for r in d["results"]}
    assert {k: v["status"] for k, v in res.items()} == {
        ("Qoder CN", "mac-account"): "success", ("Qoder CN", "win-account"): "success",
        ("Trae CN", "default"): "success", ("WorkBuddy", "default"): "success"}, d
    assert res[("Qoder CN", "mac-account")]["points"] == 100 and res[("Qoder CN", "win-account")]["points"] == 100
    assert res[("Trae CN", "default")]["points"] == 50 and res[("WorkBuddy", "default")]["points"] == 100
    assert not any("refresh" in p for _, p in Platforms.calls)            # 绝不调用刷新接口
    # 运行日志中 token 已脱敏
    ev = adm.get(f"/api/runs/{d['actions'][0]['id']}").text
    for secret in (QODER_MAC_TOKEN, QODER_WIN_TOKEN, samples.TRAE_TOKEN, samples.WB_TOKEN):
        assert secret not in ev
    # 日历：当天全部成功
    cal = adm.get("/api/calendar", params={"month": time.strftime("%Y-%m")}).json()
    assert cal["days"][-1]["status"] == "success" and cal["days"][-1]["count"] == 4


def test_4_idempotent_second_run(env):
    adm = env["adm"]
    before = len(adm.get(f"/api/days/{time.strftime('%Y-%m-%d')}").json()["actions"])
    adm.post("/api/runs", json={})
    day = time.strftime("%Y-%m-%d")
    for _ in range(80):
        d = adm.get(f"/api/days/{day}").json()
        if all(r["attempts"] == 2 and r["status"] != "running" for r in d["results"]):
            break
        time.sleep(0.25)
    assert {r["status"] for r in d["results"]} == {"already"}              # replayed / checked_in / 10001 都归为 already
    assert d["success"] == 4


def test_5_online_edit_versions_and_rollback_on_disk(env):
    adm, sc = env["adm"], env["scripts"]
    src = adm.get("/api/platforms/workbuddy/draft").json()["source"]
    new = src.replace('"今日已签到"', '"v2: 今日已签到"')
    assert new != src
    v = adm.post("/api/platforms/workbuddy/publish", json={"source": new, "note": "改文案", "activate": True}).json()
    assert v["version"] == 2
    assert (sc / "workbuddy" / "versions" / "v2.py").read_text() == new == (sc / "workbuddy" / "current.py").read_text()
    # 试运行用的是新版本，且不计入日历
    aid = next(a["id"] for a in adm.get("/api/accounts").json() if a["platform"] == "workbuddy")
    t = adm.post("/api/platforms/workbuddy/test", json={"account_id": aid}).json()
    assert t.get("trigger") == "test" and t["status"] == "already", t
    # 回滚：current.py 回到 v1，v2 历史保留
    v1 = adm.get("/api/platforms/workbuddy/versions").json()["versions"][-1]["id"]
    adm.post("/api/platforms/workbuddy/activate", json={"version_id": v1})
    assert (sc / "workbuddy" / "current.py").read_text() == src and (sc / "workbuddy" / "versions" / "v2.py").exists()


def test_6_expired_ticket_needs_reauth(env):
    """token 过期的 WorkBuddy：上传即标记 expired，签到返回 need_auth，且不会进入补签队列。"""
    adm, h = env["adm"], env["home"]
    (h / "auth2").mkdir()
    (h / "auth2" / "old.info").write_text(json.dumps(samples.wb_info(1000)))
    r = run_cli(env, "push", "-y", "-p", "workbuddy", "--workbuddy-dir", str(h / "auth2"), mode="mac")
    assert r.returncode == 0 and "状态=expired" in r.stdout
    aid = next(a["id"] for a in adm.get("/api/accounts").json() if a["platform"] == "workbuddy" and a["name"] == "default")
    adm.post("/api/runs", json={"account_id": aid})
    d = wait_results(adm, 5)
    assert next(x for x in d["results"] if x["platform"] == "WorkBuddy" and x["account"] == "default")["status"] == "need_auth"


def test_7_bad_ticket_rejected_by_server(env):
    h = env["home"]
    (h / "auth3").mkdir()
    (h / "auth3" / "bad.info").write_text('{"auth":{"accessToken":"plain-but-no-uid"}}')
    r = run_cli(env, "push", "-y", "-p", "workbuddy", "--workbuddy-dir", str(h / "auth3"), mode="mac")
    assert r.returncode == 1 and "422" in r.stderr
