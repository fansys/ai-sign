"""打印当天签到结果与每次运行的日志（token 已在服务端脱敏）。用法：report.py URL ADMIN_TOKEN"""
import json
import sys
import time
import urllib.request

url, tok = sys.argv[1].rstrip("/"), sys.argv[2]


def get(p):
    r = urllib.request.Request(url + p, headers={"Authorization": "Bearer " + tok})
    return json.load(urllib.request.urlopen(r, timeout=30))


day = get("/api/status")["today"]
for _ in range(120):  # 最多等 60 秒
    d = get(f"/api/days/{day}")
    if d["results"] and all(r["status"] != "running" for r in d["results"]):
        break
    time.sleep(0.5)
ICON = {"success": "✅ 签到成功", "already": "✅ 今日已签到", "need_auth": "🔑 需重新授权", "failed": "❌ 失败", "timeout": "❌ 超时"}
print(f"\n===== {day} 结果 =====")
for r in d["results"]:
    print(f"{r['platform']:10} {r['account']:18} {ICON.get(r['status'], r['status']):14} 积分={r['points']}  {r['message']}")
print("\n===== 运行日志 =====")
for a in d["actions"]:
    run = get(f"/api/runs/{a['id']}")
    print(f"\n[{run['platform']}/{run['account']}] #{run['id']} {run['status']} v{run['version_id']}")
    for e in run["events"]:
        print(f"  {e['ts']} [{e['level']}] {e['tag']} {e['message']}")
sys.exit(0 if d["results"] and all(r["status"] in ("success", "already") for r in d["results"]) else 1)
