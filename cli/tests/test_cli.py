import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from signcli import cli, extractors
from signcli.cli import main


AUTH = {"token": "T" * 20, "refreshToken": "r", "user": {"name": "al"}}


def test_qoder_mac_decrypts_locally(tmp_path, monkeypatch):
    import hashlib
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    monkeypatch.setattr(extractors, "IS_MAC", True)
    key = hashlib.pbkdf2_hmac("sha1", b"pw", b"saltysalt", 1003, 16)
    pad = padding.PKCS7(128).padder(); data = pad.update(json.dumps(AUTH).encode()) + pad.finalize()
    e = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    (tmp_path / "auth.v1.dat").write_bytes(b"v10" + e.update(data) + e.finalize())
    called = []
    t = extractors.discover_qoder(str(tmp_path), get_password=lambda: called.append(1) or "pw")[0]
    assert not called and t.warn                       # 发现阶段不碰钥匙串
    fn, content = t.load()["auth"]
    assert fn == "auth.json" and json.loads(content) == AUTH


def test_qoder_intl_uses_own_dir_and_keychain(tmp_path, monkeypatch):
    monkeypatch.setattr(extractors, "IS_MAC", True)
    monkeypatch.setattr(extractors, "_support", lambda: tmp_path)
    (tmp_path / "com.qoder.app.stable").mkdir(); (tmp_path / "com.qoder.app.stable" / "auth.v1.dat").write_bytes(b"v10x")
    t = extractors.discover_qoder(product="qoder-intl")[0]
    assert t.platform == "qoder-intl" and "com.qoder.app.stable" in t.source
    with pytest.raises(extractors.ExtractError, match="--qoder-intl-dir"):          # 国内版目录不存在时不会误取国际版
        extractors.discover_qoder("/nonexistent", product="qoder-intl")
    seen = []
    monkeypatch.setattr(extractors.subprocess, "run", lambda cmd, **k: seen.append(cmd) or type("R", (), {"returncode": 1, "stdout": ""})())
    with pytest.raises(extractors.ExtractError, match="Qoder App Safe Storage"):
        t.load()
    assert all("Qoder App Safe Storage" in c for c in seen)


def test_qoder_windows_decrypts_locally(tmp_path, monkeypatch):
    import base64, os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    monkeypatch.setattr(extractors, "IS_MAC", False); monkeypatch.setattr(extractors, "IS_WIN", True)
    key, nonce = os.urandom(32), os.urandom(12)
    (tmp_path / "Local State").write_text(json.dumps({"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI" + b"K" * 32).decode()}}))
    (tmp_path / "auth.v1.dat").write_bytes(b"v10" + nonce + AESGCM(key).encrypt(nonce, json.dumps(AUTH).encode(), None))
    t = extractors.discover_qoder(str(tmp_path), unprotect=lambda b: key)[0]
    assert json.loads(t.load()["auth"][1]) == AUTH


def test_trae_uploads_raw_files(tmp_path):
    app = tmp_path / "Trae CN"
    (app / "User" / "globalStorage").mkdir(parents=True); (app / "ahanet").mkdir()
    (app / "ahanet" / "tt_net_config.config").write_text('{"device_id": 12345}')
    raw = json.dumps({"iCubeAuthInfo://icube.cloudide": "ENC", "other": "x"})
    (app / "User" / "globalStorage" / "storage.json").write_text(raw)
    c = extractors.discover_trae([str(app)])[0].load()
    assert c["auth"] == ("storage.json", raw.encode()) and b"12345" in c["device_id"][1]       # 原样上传，由服务端解析


def test_workbuddy_full_file_multi(tmp_path):
    (tmp_path / "a.info").write_text('{"x":1}'); (tmp_path / "b.info").write_text("{}")
    ts = extractors.discover_workbuddy(str(tmp_path))
    assert [t.account for t in ts] == ["a", "b"] and ts[0].load()["auth"] == ("a.info", b'{"x":1}')


def test_workbuddy_single_file_left_to_server_naming(tmp_path):
    (tmp_path / "workbuddy-desktop.info").write_text("{}")
    assert [t.account for t in extractors.discover_workbuddy(str(tmp_path))] == ["default"]


def test_config_file_and_interactive_push(tmp_path, monkeypatch, capsys):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_PUT(self):
            body = self.rfile.read(int(self.headers["content-length"]))
            seen.append((self.path, self.headers["Authorization"], body, self.headers["Content-Type"]))
            out = b'{"status":"valid","expires_at":null}'
            self.send_response(200); self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    conf = tmp_path / "x" / "sign.conf"
    monkeypatch.setattr(cli, "CONF", conf)
    cli.save_conf(f"http://127.0.0.1:{srv.server_port}", "sgn_secret")
    assert "apikey = sgn_secret" in conf.read_text() and cli.load_conf()["url"].startswith("http://127")
    d = tmp_path / "auth"; d.mkdir(); (d / "u1.info").write_text('{"auth":{}}'); (d / "u2.info").write_text("{}")
    answers = iter(["y", "n"])                                   # u1 提交，u2 跳过
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert main(["-p", "workbuddy", "--workbuddy-dir", str(d)]) == 0   # 无子命令 = 交互 push
    assert [s[0] for s in seen] == ["/api/platforms/workbuddy/accounts/u1/credentials/auth?create=1"]
    assert seen[0][1] == "Bearer sgn_secret" and seen[0][3].startswith("multipart/form-data")
    assert b'filename="u1.info"' in seen[0][2] and b'{"auth":{}}' in seen[0][2]
    assert "sgn_secret" not in capsys.readouterr().out
