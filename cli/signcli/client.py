"""仅用标准库的服务端客户端。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(f"HTTP {status}: {msg}")
        self.status = status


class Client:
    def __init__(self, server: str, token: str, timeout: int = 30):
        self.server, self.token, self.timeout = server.rstrip("/"), token, timeout

    def _req(self, method, path, body=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.server + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail", "")
            except Exception:
                detail = e.reason
            raise ApiError(e.code, detail)
        except urllib.error.URLError as e:
            raise ApiError(0, f"无法连接 {self.server}: {e.reason}")

    def put_credential(self, platform: str, account: str, name: str, filename: str, data: bytes) -> dict:
        """以 multipart 原样上传文件，不做任何处理。"""
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        path = (f"/api/platforms/{urllib.parse.quote(platform)}/accounts/{urllib.parse.quote(account)}"
                f"/credentials/{urllib.parse.quote(name)}?create=1")
        return self._req("PUT", path, raw=body, ctype=f"multipart/form-data; boundary={boundary}")
