"""全局配置，全部来自环境变量，带合理默认值。"""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("SIGN_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.environ.get("SIGN_DB_URL", f"sqlite:///{DATA_DIR / 'sign.db'}")
TZ = os.environ.get("SIGN_TZ", "Asia/Shanghai")

# 调度：每天 DAILY_AT 签到；RETRY_HOURS 内每个整点补签尚未成功的账号
DAILY_AT = os.environ.get("SIGN_DAILY_AT", "10:05")
RETRY_HOURS = os.environ.get("SIGN_RETRY_HOURS", "11-23")
SCHEDULER_ENABLED = os.environ.get("SIGN_SCHEDULER", "1") == "1"

MAX_CONCURRENCY = int(os.environ.get("SIGN_MAX_CONCURRENCY", "3"))
DEFAULT_TIMEOUT = int(os.environ.get("SIGN_SCRIPT_TIMEOUT", "60"))
MAX_UPLOAD_BYTES = int(os.environ.get("SIGN_MAX_UPLOAD", str(5 * 1024 * 1024)))

WEBHOOK_URL = os.environ.get("SIGN_WEBHOOK_URL", "")  # 失败/需重新授权时 POST JSON

# 签到脚本以文件形式保存：scripts/<平台key>/{manifest.json, current.py, versions/v<N>.py}
_repo_scripts = Path(__file__).resolve().parents[2] / "scripts"
SCRIPTS_DIR = Path(os.environ.get("SIGN_SCRIPTS_DIR", _repo_scripts))
BUILTIN_SCRIPTS_DIR = Path(os.environ.get("SIGN_BUILTIN_SCRIPTS_DIR", _repo_scripts))  # 缺失的平台目录从这里复制
