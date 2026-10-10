"""sign-cli：提取本机 AI 工具的 ticket 并提交到签到服务（macOS / Windows）。

配置文件（服务端下载包自带 ./sign.conf；否则 ~/.config/fansy/sign.conf）：
    [server]
    url    = http://your-host:8000
    apikey = sgn_xxxxxxxx

用法：
    sign-cli            交互：发现本机登录态 -> 逐个确认 -> 提交
    sign-cli push -y    不询问，全部提交（适合定时任务）
    sign-cli scan       只列出能发现的登录态，不读取、不上传
    sign-cli init       交互式生成配置文件
"""
from __future__ import annotations

import argparse
import configparser
import os
import sys
from pathlib import Path

from . import __version__, extractors
from .client import ApiError, Client

def _conf_path() -> Path:
    """配置文件：SIGN_CLI_CONFIG > 程序目录下的 sign.conf（服务端下载包自带）> ~/.config/fansy/sign.conf"""
    if os.environ.get("SIGN_CLI_CONFIG"):
        return Path(os.environ["SIGN_CLI_CONFIG"])
    bundled = Path(__file__).resolve().parent.parent / "sign.conf"
    return bundled if bundled.is_file() else Path.home() / ".config" / "fansy" / "sign.conf"


CONF = _conf_path()
NAMES = {"qoder": "Qoder CN", "qoder-intl": "Qoder", "trae": "Trae CN", "workbuddy": "WorkBuddy"}


# ---------- 配置 ----------
def load_conf() -> dict:
    cp = configparser.ConfigParser()
    cp.read(CONF, encoding="utf-8")
    s = cp["server"] if cp.has_section("server") else {}
    return {"url": (s.get("url") or "").strip(), "apikey": (s.get("apikey") or "").strip()}


def save_conf(url: str, apikey: str):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    cp = configparser.ConfigParser()
    cp["server"] = {"url": url, "apikey": apikey}
    with open(CONF, "w", encoding="utf-8") as f:
        cp.write(f)
    try:
        os.chmod(CONF, 0o600)
    except OSError:
        pass


def ask(prompt: str, default: bool = True, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        a = input(prompt + suffix).strip().lower()
    except EOFError:
        return False
    return default if not a else a in ("y", "yes", "是")


def resolve_server(args) -> tuple[str, str]:
    conf = load_conf()
    url = args.server or os.environ.get("SIGN_SERVER") or conf["url"]
    key = args.apikey or os.environ.get("SIGN_APIKEY") or conf["apikey"]
    if not url or not key:
        print(f"未配置服务地址/apikey。请编辑 {CONF}：\n[server]\nurl = http://host:8000\napikey = sgn_xxx\n或运行 sign-cli init", file=sys.stderr)
        raise SystemExit(2)
    return url, key


# ---------- 发现 ----------
def discover(args) -> tuple[list, list]:
    tickets, errors = [], []
    acct = args.account or "default"
    for p in (args.platform or list(extractors.PLATFORMS)):
        try:
            if p in ("qoder", "qoder-intl"):
                d = args.qoder_dir if p == "qoder" else args.qoder_intl_dir
                tickets += extractors.discover_qoder(d, account=acct, product=p)
            elif p == "trae":
                tickets += extractors.discover_trae([args.trae_dir] if args.trae_dir else None, account=acct)
            elif p == "workbuddy":
                tickets += extractors.discover_workbuddy(args.workbuddy_dir)
        except extractors.ExtractError as e:
            errors.append((p, str(e)))
        except Exception as e:  # noqa
            errors.append((p, f"{type(e).__name__}: {e}"))
    return tickets, errors


def fmt(t) -> str:
    return f"{NAMES[t.platform]:10} 账号={t.account:14} {t.size:>7}B  {t.source}"


# ---------- 命令 ----------
def cmd_init(args):
    cur = load_conf()
    url = input(f"服务地址 [{cur['url'] or 'http://localhost:8000'}]: ").strip() or cur["url"] or "http://localhost:8000"
    key = input(f"apikey（面板→设置 创建）[{'…' + cur['apikey'][-4:] if cur['apikey'] else ''}]: ").strip() or cur["apikey"]
    save_conf(url, key)
    print(f"已写入 {CONF}")
    return 0


def cmd_scan(args):
    tickets, errors = discover(args)
    for t in tickets:
        print("[发现]", fmt(t))
    for p, e in errors:
        print(f"[缺失] {NAMES[p]}: {e}")
    return 0 if tickets else 1


def cmd_push(args):
    url, key = (None, None) if args.dry_run else resolve_server(args)
    tickets, errors = discover(args)
    for p, e in errors:
        print(f"[缺失] {NAMES[p]}: {e}", file=sys.stderr)
    if not tickets:
        print("没有发现可提交的登录态", file=sys.stderr)
        return 1
    print(f"\n发现 {len(tickets)} 个登录态：")
    for i, t in enumerate(tickets, 1):
        print(f"  {i}. {fmt(t)}")
    print()
    chosen = []
    for t in tickets:
        note = f"（{t.warn}）" if t.warn else ""
        if ask(f"提交 {NAMES[t.platform]} / {t.account}{note}？", True, args.yes):
            chosen.append(t)
    if not chosen:
        print("未选择任何项，退出。")
        return 0
    cli = None if args.dry_run else Client(url, key)
    fails = 0
    for t in chosen:
        try:
            creds = t.load()
        except Exception as e:  # noqa
            fails += 1
            print(f"[失败] {t.platform}/{t.account} 读取失败: {e}", file=sys.stderr)
            continue
        acct = t.account
        for name, (fn, data) in creds.items():
            tag = f"{t.platform}/{acct}/{name}"
            if args.dry_run:
                print(f"[dry-run] {tag} {fn} {len(data)}B")
                continue
            try:
                r = cli.put_credential(t.platform, acct, name, fn, data)
                acct = r.get("account", acct)          # 服务端按 ticket 用户信息自动命名后，同一登录态的其余凭证沿用
                tag = f"{t.platform}/{acct}/{name}"
                print(f"[OK] {tag}  状态={r['status']}" + (f" 到期={r['expires_at']}" if r.get("expires_at") else ""))
            except ApiError as e:
                fails += 1
                print(f"[失败] {tag}  {e}", file=sys.stderr)
    return 1 if fails else 0


def build_parser():
    ap = argparse.ArgumentParser(prog="sign-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("-p", "--platform", action="append", choices=extractors.PLATFORMS, help="可多次指定；默认全部")
        p.add_argument("-a", "--account", help="服务端账号名（Qoder/Trae 默认 default；WorkBuddy 用 .info 文件名）")
        p.add_argument("--qoder-dir", help="Qoder CN 数据目录（含 auth.v1.dat）")
        p.add_argument("--qoder-intl-dir", help="Qoder（国际版）数据目录（含 auth.v1.dat）")
        p.add_argument("--trae-dir", help="Trae 数据目录（含 User/globalStorage）")
        p.add_argument("--workbuddy-dir", help="WorkBuddy 的 auth 目录（含 *.info）")

    sub.add_parser("init", help="生成配置文件").set_defaults(fn=cmd_init)
    s = sub.add_parser("scan", help="只列出可发现的登录态")
    common(s)
    s.set_defaults(fn=cmd_scan)
    u = sub.add_parser("push", help="交互确认后提取并提交（默认命令）")
    common(u)
    u.add_argument("--server"), u.add_argument("--apikey")
    u.add_argument("-y", "--yes", action="store_true", help="不询问，全部提交")
    u.add_argument("--dry-run", action="store_true", help="只演练，不读取密钥、不上传")
    u.set_defaults(fn=cmd_push)
    return ap


def main(argv=None) -> int:
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv = ["push", *argv]  # 无子命令 = 交互 push
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())
