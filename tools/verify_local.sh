#!/usr/bin/env bash
# 用真实 ticket 验证：确保后台服务在运行 -> sign-cli 提取并提交 -> 触发真实签到 -> 打印结果。
# 服务由 tools/service.sh 常驻后台，本脚本不会启停它。凭证只发给本机服务和平台官方接口。
#   tools/verify_local.sh [sign-cli push 的参数，如 -p trae -p workbuddy -y]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SVC="$ROOT/tools/service.sh"
PORT="${SIGN_PORT:-8765}"; URL="http://127.0.0.1:$PORT"

"$SVC" status >/dev/null 2>&1 || "$SVC" start
ADMIN="$("$SVC" token)"
(cd "$ROOT/cli" && uv sync -q)

# 没有 CLI 配置时自动创建只有“提交凭证”权限的 apikey，写入 ~/.config/fansy/sign.conf（之后日常直接 sign-cli 即可）
CONF="${SIGN_CLI_CONFIG:-$HOME/.config/fansy/sign.conf}"
if [ ! -s "$CONF" ]; then
  APIKEY="$(curl -fs -X POST -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"name":"cli"}' "$URL/api/tokens" \
    | uv run --project "$ROOT/backend" python -c 'import sys,json;print(json.load(sys.stdin)["token"])')"
  mkdir -p "$(dirname "$CONF")"
  printf '[server]\nurl = %s\napikey = %s\n' "$URL" "$APIKEY" > "$CONF"; chmod 600 "$CONF"
  echo "▶ 已生成 CLI 配置 $CONF"
fi
export SIGN_CLI_CONFIG="$CONF"

echo "▶ 提取并提交 ticket（会逐个询问；Qoder 会弹出 macOS 钥匙串授权框）"
(cd "$ROOT/cli" && uv run sign-cli push ${@+"$@"}) || echo "（部分提交失败，见上方；继续用已提交的账号验证）"

read -r -p "▶ 现在用真实接口触发签到？会真实领取积分 [Y/n] " ok || ok=n
case "${ok:-Y}" in n|N) echo "已跳过签到。"; exit 0;; esac
curl -fs -X POST -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{}' "$URL/api/runs" >/dev/null
uv run --project "$ROOT/backend" python "$ROOT/tools/report.py" "$URL" "$ADMIN"
