#!/usr/bin/env bash
# 后台常驻服务管理（macOS / Linux）。
#   tools/service.sh start|stop|restart|status|logs|token
#   tools/service.sh install     登录后自动启动（macOS launchd）
#   tools/service.sh uninstall
# 环境变量：SIGN_PORT(8765) SIGN_HOST(127.0.0.1) SIGN_DATA_DIR(<repo>/data)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${SIGN_PORT:-8765}"; HOST="${SIGN_HOST:-127.0.0.1}"
DATA="${SIGN_DATA_DIR:-$ROOT/data}"
PID="$DATA/server.pid"; LOG="$DATA/server.log"; URL="http://127.0.0.1:$PORT"
LABEL="com.fansy.sign"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$DATA"
[ -f "$DATA/admin.token" ] || echo "adm_$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 24)" > "$DATA/admin.token"
chmod 600 "$DATA/admin.token"
ADMIN="$(cat "$DATA/admin.token")"

alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }
healthy() { curl -fs -m 2 -H "Authorization: Bearer $ADMIN" "$URL/api/status" >/dev/null 2>&1; }
env_run() {
  cd "$ROOT/backend"
  SIGN_DATA_DIR="$DATA" SIGN_SCRIPTS_DIR="$DATA/scripts" SIGN_BUILTIN_SCRIPTS_DIR="$ROOT/scripts" SIGN_ADMIN_TOKEN="$ADMIN" "$@"
}

start() {
  command -v uv >/dev/null || { echo "需要先安装 uv：brew install uv"; exit 1; }
  if alive && healthy; then echo "已在运行：$URL (pid $(cat "$PID"))"; return; fi
  (cd "$ROOT/backend" && uv sync -q)
  # nohup + 后台 + 重定向：脱离当前终端，关闭终端不影响；调度器开启（10:05 签到，11-23 点补签）
  ( env_run nohup uv run uvicorn app.main:app --host "$HOST" --port "$PORT" >>"$LOG" 2>&1 < /dev/null & echo $! > "$PID" )
  for _ in $(seq 1 60); do healthy && break; sleep 0.5; done
  healthy || { echo "启动失败，日志："; tail -20 "$LOG"; exit 1; }
  echo "已启动：$URL (pid $(cat "$PID"))  日志：$LOG"
  echo "管理 token：$ADMIN"
}
stop() {
  if alive; then
    P="$(cat "$PID")"; pkill -P "$P" 2>/dev/null || true; kill "$P" 2>/dev/null || true; rm -f "$PID"; echo "已停止"
  else echo "未在运行"; fi
}
case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) if alive && healthy; then echo "运行中：$URL (pid $(cat "$PID"))"; elif healthy; then echo "运行中：${URL}（launchd 托管）"; else echo "未运行"; exit 1; fi ;;
  logs) tail -n 100 -f "$LOG" ;;
  token) echo "$ADMIN" ;;
  install)
    command -v uv >/dev/null || { echo "需要先安装 uv"; exit 1; }
    UV="$(command -v uv)"; mkdir -p "$(dirname "$PLIST")"
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>WorkingDirectory</key><string>$ROOT/backend</string>
<key>ProgramArguments</key><array><string>$UV</string><string>run</string><string>uvicorn</string><string>app.main:app</string><string>--host</string><string>$HOST</string><string>--port</string><string>$PORT</string></array>
<key>EnvironmentVariables</key><dict>
<key>SIGN_DATA_DIR</key><string>$DATA</string><key>SIGN_SCRIPTS_DIR</key><string>$DATA/scripts</string>
<key>SIGN_BUILTIN_SCRIPTS_DIR</key><string>$ROOT/scripts</string><key>SIGN_ADMIN_TOKEN</key><string>$ADMIN</string>
<key>PATH</key><string>$(dirname "$UV"):/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin</string></dict>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG</string><key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PL
    stop >/dev/null 2>&1 || true
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "已安装开机自启：$PLIST" ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true; rm -f "$PLIST"; echo "已卸载自启" ;;
  *) echo "用法: $0 start|stop|restart|status|logs|token|install|uninstall"; exit 2 ;;
esac
