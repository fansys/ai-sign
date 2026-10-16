"""端到端：假服务模拟三个平台接口 + 本地加密凭证样本。"""
import base64
import hashlib
import json
import os
import struct
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

_tmp = tempfile.mkdtemp()
os.environ["SIGN_DATA_DIR"] = _tmp
os.environ["SIGN_SCRIPTS_DIR"] = os.path.join(_tmp, "scripts")  # 从仓库 scripts/ 复制出来，测试不污染源目录
os.environ["SIGN_SCHEDULER"] = "0"
os.environ["SIGN_ADMIN_TOKEN"] = "adm_test"

from cryptography.hazmat.primitives import padding  # noqa: E402
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402,F401
from fastapi.testclient import TestClient  # noqa: E402

from pathlib import Path  # noqa: E402

from samples import qoder_cred, trae_mod, trae_storage, wb_info, wb_mod  # noqa: E402,F401
SCRIPTS = Path(_tmp) / "scripts"

STATE = {"qoder_claimed": False, "trae_checked": False, "wb_checked": False}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/q/sash/api/v1/me/campaigns"):
            if self.headers.get("Authorization") != "Bearer QODER_TOKEN_0123456789":
                return self._send({}, 401)
            st = "CLAIMED" if STATE["qoder_claimed"] else "CLAIMABLE"
            return self._send({"campaigns": [{"campaignId": "c1", "campaignKey": "daily", "actionType": "CLAIM_BENEFIT", "claimStatus": st}]})
        self._send({}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0); self.rfile.read(n)
        p = self.path
        if p == "/q/sash/api/v1/me/campaigns/c1/claim":
            STATE["qoder_claimed"] = True
            return self._send({"status": "CLAIMED", "replayed": False, "benefit": {"kind": "CREDITS", "amount": 100}})
        if p == "/t/status":
            return self._send({"checked_in": STATE["trae_checked"], "enable": True, "credits": 150})
        if p == "/t/claim":
            STATE["trae_checked"] = True
            return self._send({"code": 0, "data": {"credits": 150}})
        if p == "/w/checkin-status":
            return self._send({"code": 0, "data": {"today_checked_in": STATE["wb_checked"]}})
        if p == "/w/daily-checkin":
            if STATE["wb_checked"]:
                return self._send({"code": 10001, "msg": "already"})
            STATE["wb_checked"] = True
            return self._send({"code": 0, "data": {"credit": 100}})
        self._send({}, 404)


@pytest.fixture(scope="module")
def client():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    from app.main import app
    with TestClient(app, headers={"Authorization": "Bearer adm_test"}) as c:
        for key, path in (("qoder", "/q"), ("trae", "/t"), ("workbuddy", "/w")):
            p = next(x for x in c.get("/api/platforms").json() if x["key"] == key)
            m = p["manifest"]; m["config"]["api_base"] = base + path
            assert c.patch(f"/api/platforms/{key}", json={"manifest": m}).status_code == 200
        yield c
    srv.shutdown()


def wait_runs(c, n=1):
    for _ in range(60):
        d = c.get("/api/days/" + time.strftime("%Y-%m-%d")).json()
        if len(d["results"]) >= n and all(r["status"] != "running" for r in d["results"]):
            return d
        time.sleep(0.3)
    return d


def test_full_flow(client):
    c = client
    # 创建账号 + 上传凭证（三种形态：json、multipart、raw）
    for key, aname, body in (("qoder", "alice", qoder_cred()), ("trae", "bob", None), ("workbuddy", "carol", None)):
        c.post("/api/accounts", json={"platform": key, "name": aname})
    r = c.put("/api/platforms/qoder/accounts/alice/credentials/auth", json={"value": json.dumps(qoder_cred())})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["user"] == "alice" and r.json()["status"] == "valid"
    r = c.put("/api/platforms/trae/accounts/bob/credentials/auth", files={"file": ("storage.json", json.dumps(trae_storage()))})
    assert r.status_code == 200, r.text
    r = c.put("/api/platforms/workbuddy/accounts/carol/credentials/auth", content=json.dumps(wb_info(4102444800000)),
              headers={"content-type": "application/octet-stream"})
    assert r.status_code == 200, r.text

    # 凭证接口不回显明文
    accs = c.get("/api/accounts").json()
    assert "QODER_TOKEN" not in json.dumps(accs)
    q = next(a for a in accs if a["platform"] == "qoder")                      # 复制凭证：仅管理员可取明文
    r = c.get(f"/api/accounts/{q['id']}/credentials/auth/value")
    assert r.status_code == 200 and "QODER_TOKEN" in r.text and r.headers["cache-control"] == "no-store"
    assert c.get(f"/api/accounts/{q['id']}/credentials/nope/value").status_code == 404
    assert c.get(f"/api/accounts/{q['id']}/credentials/auth/value", headers={"Authorization": "Bearer bad"}).status_code == 401

    # 立即签到
    assert c.post("/api/runs", json={}).status_code == 200
    d = wait_runs(c, 3)
    st = {r["platform"]: r for r in d["results"]}
    assert st["Qoder CN"]["status"] == "success" and st["Qoder CN"]["points"] == 100
    assert st["Trae CN"]["status"] == "success" and st["Trae CN"]["points"] == 150
    assert st["WorkBuddy"]["status"] == "success" and st["WorkBuddy"]["points"] == 100
    assert d["success"] == 3

    # 再次签到 => 幂等 already
    c.post("/api/runs", json={"platform": "qoder"}); time.sleep(2)
    d = wait_runs(c, 3)
    assert {r["platform"]: r for r in d["results"]}["Qoder CN"]["status"] == "already"
    assert {r["platform"]: r for r in d["results"]}["Qoder CN"]["attempts"] == 2

    # 日历
    cal = c.get("/api/calendar", params={"month": time.strftime("%Y-%m")}).json()
    assert cal["days"][-1]["status"] == "success"

    # 日志脱敏：事件里不应出现完整 token
    run = c.get(f"/api/runs/{d['actions'][0]['id']}").json()
    assert "QODER_TOKEN_0123456789" not in json.dumps(run)


def test_reject_bad_credential(client):
    r = client.put("/api/platforms/qoder/accounts/alice/credentials/auth", json={"value": "not json"})
    assert r.status_code == 422
    r = client.put("/api/platforms/workbuddy/accounts/carol/credentials/auth", content=b'{"auth":{}}',
                   headers={"content-type": "application/octet-stream"})
    assert r.status_code == 422


def test_expired_token_need_auth(client):
    c = client
    c.post("/api/accounts", json={"platform": "workbuddy", "name": "old"})
    r = c.put("/api/platforms/workbuddy/accounts/old/credentials/auth", content=json.dumps(wb_info(1000)),
              headers={"content-type": "application/octet-stream"})
    assert r.json()["status"] == "expired"
    aid = next(a["id"] for a in c.get("/api/accounts").json() if a["name"] == "old")
    c.post("/api/runs", json={"account_id": aid}); time.sleep(2)
    d = wait_runs(c, 4)
    old = [r for r in d["results"] if r["account"] == "old"][0]
    assert old["status"] == "need_auth"
    # need_auth 且凭证未更新：不进入补签队列
    from app.db import SessionLocal
    from app import services
    with SessionLocal() as db:
        assert aid not in services.pending_account_ids(db)


def test_script_versioning(client):
    c = client
    base = c.get("/api/platforms/trae/versions").json()
    assert len(base["versions"]) == 1
    src = c.get("/api/platforms/trae/draft").json()["source"]
    # 语法错误被拒
    assert c.post("/api/platforms/trae/publish", json={"source": "def run(:", "note": "x"}).status_code == 400
    new_src = src.replace('"今日已签到"', '"v2 今日已签到"', 1) + "\n# v2\n"
    assert c.put("/api/platforms/trae/draft", json={"source": new_src}).status_code == 200
    # 试运行（不计入日历、不领取）
    aid = next(a["id"] for a in c.get("/api/accounts").json() if a["name"] == "bob")
    t = c.post("/api/platforms/trae/test", json={"account_id": aid}).json()
    assert t["trigger"] == "test" and t["status"] in ("already", "success")
    v = c.post("/api/platforms/trae/publish", json={"note": "v2", "activate": True}).json()
    assert v["version"] == 2
    assert c.get("/api/platforms/trae/versions").json()["active_version_id"] == v["id"]
    # 文件落盘：versions/v2.py 新增，current.py 等于启用的 v2
    assert (SCRIPTS / "trae" / "versions" / "v2.py").read_text() == new_src
    assert (SCRIPTS / "trae" / "current.py").read_text() == new_src
    # 回滚到 v1
    v1 = base["versions"][0]["id"]
    assert c.post("/api/platforms/trae/activate", json={"version_id": v1}).status_code == 200
    assert (SCRIPTS / "trae" / "current.py").read_text() == src                  # current.py 跟随回滚
    assert (SCRIPTS / "trae" / "versions" / "v2.py").exists()                    # 历史版本保留
    # 相同内容拒绝重复发布
    assert c.post("/api/platforms/trae/publish", json={"source": new_src, "note": "dup"}).status_code == 409


def test_api_token_scope(client):
    c = client
    tok = c.post("/api/tokens", json={"name": "cli"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    assert anon.get("/api/accounts").status_code == 401
    assert anon.get("/api/accounts", headers=h).status_code == 401  # 无管理权限
    r = anon.put("/api/platforms/trae/accounts/bob/credentials/auth", headers=h, json={"value": json.dumps(trae_storage())})
    assert r.status_code == 200



def test_file_edit_sync_and_new_platform(client):
    c = client
    cur = SCRIPTS / "workbuddy" / "current.py"
    cur.write_text(cur.read_text() + "\n# hand edit\n")
    ch = c.post("/api/scripts/sync").json()["changes"]
    assert any("workbuddy" in x and "current.py" in x for x in ch), ch
    vs = c.get("/api/platforms/workbuddy/versions").json()
    assert vs["versions"][0]["version"] == 2 and vs["active_version_id"] == vs["versions"][0]["id"]
    assert (SCRIPTS / "workbuddy" / "versions" / "v2.py").read_text().endswith("# hand edit\n")
    assert c.post("/api/scripts/sync").json()["changes"] == []                  # 幂等
    # 新建目录 = 新平台
    d = SCRIPTS / "demo"; d.mkdir()
    (d / "current.py").write_text("def run(ctx):\n    return {'status': 'success', 'message': 'ok'}\n")
    (d / "manifest.json").write_text(json.dumps({"name": "Demo", "credentials": [{"name": "auth", "kind": "text"}]}))
    assert any("demo" in x for x in c.post("/api/scripts/sync").json()["changes"])
    assert any(p["key"] == "demo" and p["name"] == "Demo" for p in c.get("/api/platforms").json())


def test_trae_jwt_exp_becomes_expires_at():
    import base64 as b64, json as js
    seg = lambda o: b64.urlsafe_b64encode(js.dumps(o).encode()).decode().rstrip("=")
    jwt = f"{seg({'alg': 'none'})}.{seg({'exp': 4102444800})}.sig"
    out = trae_mod.on_credential(None, "auth", js.dumps(trae_storage(token=jwt)).encode())
    assert out["expires_at"].startswith("2100-01-01")
    assert trae_mod.on_credential(None, "auth", js.dumps(trae_storage(token="not-a-jwt")).encode())["expires_at"] is None


def test_api_token_masked_and_copyable(client):
    c = client
    r = c.post("/api/tokens", json={"name": "copy-me"}).json()
    row = next(t for t in c.get("/api/tokens").json() if t["id"] == r["id"])
    assert row["copyable"] and "*" in row["masked"] and r["token"] not in json.dumps(row)
    assert c.get(f"/api/tokens/{r['id']}/value").text == r["token"]
    assert c.get(f"/api/tokens/{r['id']}/value", headers={"Authorization": "Bearer " + r["token"]}).status_code == 401


def test_auto_account_naming_and_merge_by_identity(client):
    c = client
    put = lambda extra: c.put("/api/platforms/trae/accounts/default/credentials/auth?create=1",
                              files={"file": ("storage.json", json.dumps(trae_storage(extra=extra)))}).json()
    r = put({"userId": 777, "account": {"username": "alice", "nonPlainTextMobile": "173******54"}, "expiredAt": "2100-01-01T00:00:00.000Z"})
    assert r["account"] == "alice (173******54)" and r["expires_at"].startswith("2100-01-01")
    r2 = put({"userId": 777, "account": {"username": "alice2", "nonPlainTextMobile": "173******54"}})   # 改昵称：并入同一账号并更名，不产生新账号
    assert r2["account"] == "alice2 (173******54)"
    names = [a["name"] for a in c.get("/api/accounts").json() if a["platform"] == "trae"]
    assert "alice2 (173******54)" in names and "alice (173******54)" not in names and "default" not in names
    # 后续凭证（device_id）用返回的账号名提交，不会再产生 default
    assert c.put(f"/api/platforms/trae/accounts/{r2['account']}/credentials/device_id", content="123456").status_code == 200
    r3 = put({"userId": 888, "account": {"username": "alice2", "nonPlainTextMobile": "173******54"}})   # 另一人同名：加尾号区分
    assert r3["account"] != r2["account"] and r3["account"].startswith("alice2 (173******54)")


def test_qoder_cn_label_masks_phone(client):
    c = client
    cred = qoder_cred(); cred["user"] = {"id": "u-cn-1", "name": "carol", "phone": "13800001234"}
    r = c.put("/api/platforms/qoder/accounts/default/credentials/auth?create=1", content=json.dumps(cred),
              headers={"content-type": "application/octet-stream"}).json()
    assert r["account"] == "carol (138****1234)" and "13800001234" not in json.dumps(r)


def test_api_token_regenerate_and_delete(client):
    c = client
    r = c.post("/api/tokens", json={"name": "rg"}).json()
    new = c.post(f"/api/tokens/{r['id']}/regenerate").json()
    assert new["id"] == r["id"] and new["token"] != r["token"]
    assert c.get(f"/api/tokens/{r['id']}/value").text == new["token"]
    assert c.delete(f"/api/tokens/{r['id']}").status_code == 200
    assert all(t["id"] != r["id"] for t in c.get("/api/tokens").json())
    assert c.post(f"/api/tokens/{r['id']}/regenerate").status_code == 404


def test_bark_settings(client):
    r = client.put("/api/settings/bark", json={"server": "https://bark.example.com/", "key": "abcdef123456"})
    assert r.status_code == 200 and r.json()["key_masked"] == "***3456" and r.json()["server"] == "https://bark.example.com"
    r = client.put("/api/settings/bark", json={"server": "https://bark.example.com", "key": ""})
    assert r.json()["configured"]
    assert client.put("/api/settings/bark", json={"server": "ftp://x"}).status_code == 400


def test_cli_download_zip_runs_without_install(client, tmp_path):
    import io, os, subprocess, sys, zipfile
    r = client.get("/api/cli/download", params={"server": "https://sign.example.com/"})
    assert r.status_code == 200
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(tmp_path)
    d = tmp_path / "sign-cli"
    conf = (d / "sign.conf").read_text()
    assert "url = https://sign.example.com\n" in conf and "apikey = sgn_" in conf
    modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in zipfile.ZipFile(io.BytesIO(r.content)).infolist()}
    assert modes["sign-cli/sign.conf"] == 0o600 and modes["sign-cli/sign-cli.sh"] == 0o755
    # 直接运行 sh（不安装）：配置取自同目录 sign.conf，未设 SIGN_CLI_CONFIG
    env = {k: v for k, v in os.environ.items() if k not in ("SIGN_CLI_CONFIG", "SIGN_SERVER", "SIGN_APIKEY", "PYTHONPATH")}
    sh = d / "sign-cli.sh"
    out = subprocess.run(["sh", str(sh), "--version"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and out.stdout.strip(), out.stderr
    code = "import sys;sys.path.insert(0, sys.argv[1]);from signcli import cli;print(cli.CONF.resolve(), cli.load_conf()['url'])"
    out = subprocess.run([sys.executable, "-I", "-c", code, str(d)], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert out.stdout.split() == [str((d / "sign.conf").resolve()), "https://sign.example.com"], out.stderr
    # 重复下载复用同一个 token，不堆积
    r2 = client.get("/api/cli/download", params={"server": "https://sign.example.com"})
    z2 = zipfile.ZipFile(io.BytesIO(r2.content)).read("sign-cli/sign.conf")
    assert z2 == (d / "sign.conf").read_bytes()
    assert sum(1 for t in client.get("/api/tokens").json() if t["name"] == "cli-download") == 1
    assert client.get("/api/cli/download", params={"server": "javascript:alert(1)"}).status_code == 400


def test_run_row_reports_script_version_number(client):
    """流水里的版本号应是脚本版本号(v1/v2…)，而不是 script_version 表的自增 id。"""
    c = client
    c.post("/api/accounts", json={"platform": "workbuddy", "name": "carol"})
    c.put("/api/platforms/workbuddy/accounts/carol/credentials/auth", content=json.dumps(wb_info(4102444800000)),
          headers={"content-type": "application/octet-stream"})
    c.post("/api/runs", json={"platform": "workbuddy"})
    d = wait_runs(c)
    vers = c.get("/api/platforms/workbuddy/versions").json()["versions"]
    act = d["actions"][0]
    assert act["version_id"] is not None
    assert act["version"] == next(v["version"] for v in vers if v["id"] == act["version_id"])


def test_round_push_is_merged_and_filtered():
    from app import notify
    cfg = {"on_success": True, "on_failure": True, "on_auth": False}
    items = [{"kind": "failure", "label": "Trae/b", "message": "boom", "points": None},
             {"kind": "success", "label": "Qoder/a", "message": "ok", "points": 5},
             {"kind": "auth", "label": "WB/c", "message": "expired", "points": None}]
    title, body = notify.build_round(items, cfg)
    assert title == "签到成功 1 · 失败 1"
    assert body.splitlines() == ["[成功] Qoder/a +5积分", "[失败] Trae/b：boom"]   # 成功在前；on_auth 关闭则不出现
    assert notify.build_round(items[2:], cfg) is None


def test_run_many_pushes_once_per_round(monkeypatch):
    import asyncio
    from app import notify, services
    sent = []

    async def fake_run(i, trigger, source_override=None, collector=None):
        collector.append({"kind": "success", "label": f"P/{i}", "message": "", "points": 1})

    async def fake_send(items):
        sent.append(list(items))

    monkeypatch.setattr(services, "run_account", fake_run)
    monkeypatch.setattr(notify, "send_round", fake_send)
    asyncio.run(services.run_many([1, 2, 3], "schedule"))
    assert len(sent) == 1 and len(sent[0]) == 3      # 一轮三个账号 → 一次推送
    asyncio.run(services.run_many([4], "manual"))
    assert len(sent) == 2 and len(sent[1]) == 1       # 单独签到一个也推送
