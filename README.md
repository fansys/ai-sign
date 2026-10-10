# Sign · AI 工具自动签到服务

内置 Qoder CN / Trae CN / WorkBuddy / Qoder（国际版）四个平台（登录态格式来自第三方公开分析），支持多账号、凭证 API、脚本在线编辑与版本控制。详细设计见 [DESIGN.md](DESIGN.md)。

## 启动服务（uv）

```bash
cd backend
uv sync
SIGN_ADMIN_TOKEN=adm_change_me uv run uvicorn app.main:app --port 8000   # 打开 http://localhost:8000
uv run pytest                                                              # 测试
```

生产用 Docker：`docker compose up -d`（镜像 ghcr.io/fansys/ai-sign，GitHub Actions 自动构建；本地构建把 compose 的 image 换成 `build: .`）。`SIGN_MASTER_KEY`/`SIGN_ADMIN_TOKEN` 可选，缺省在 `./data`（容器内 `/data`）自动生成（`docker compose exec sign cat /data/admin.token` 取管理 token，日志只显示尾 6 位）；务必备份 `./data`。
主密钥 `SIGN_MASTER_KEY` 与 `data/` 必须一起备份。

## 提交登录态（CLI，macOS 优先 / 兼容 Windows）

服务通常跑在 Linux 容器里，读不到本机的客户端文件，所以由 **CLI 在装有客户端的电脑上提取 ticket 并提交**，服务端脚本负责解析与签到。

```bash
cd cli && uv tool install .        # 或 uv run sign-cli …；依赖仅 cryptography（Qoder 本机解密用）
mkdir -p ~/.config/fansy && cat > ~/.config/fansy/sign.conf <<'EOF2'
[server]
url = http://your-host:8000
apikey = sgn_xxxxxxxx
EOF2
sign-cli            # 交互：列出发现的登录态 -> 逐个确认 -> 提交
sign-cli scan       # 只看能发现什么（不读取密钥、不上传）
sign-cli push -y    # 不询问，全部提交（可放进 launchd / cron / 计划任务）
```

apikey 在面板「设置」里创建（仅有“提交凭证”权限）。也可 `sign-cli init` 交互生成配置。

| 平台 | macOS 数据位置 | 说明 |
|---|---|---|
| WorkBuddy | `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/*.info` | 整个 .info 文件原样上传，服务端解密；5.6.2 起若改为 asym-v1 非对称加密，服务端会拒绝并提示 |
| Qoder CN | `~/Library/Application Support/com.qodercn.app.stable/auth.v1.dat` | 口令在钥匙串 “Qoder CN App Safe Storage”，确认提交后才读取并会弹授权框；**密钥只有本机拿得到，所以仅此平台在本地解密**，上传解出的 JSON |
| Trae CN | `~/Library/Application Support/Trae CN/User/globalStorage/storage.json` | 整个 `storage.json` 原样上传（服务端只保留 token），并带上 `tt_net_config.config` 供服务端提取设备 ID |

Windows 路径与原文一致（`%APPDATA%` / `%LOCALAPPDATA%`，Qoder 用 DPAPI 在本机解密）。CLI 一律以 multipart 原文件上传，不做额外处理。Qoder/Trae 在 macOS 上的格式来自第三方公开分析，尚未用真实机器验证。
目录不在默认位置时用 `--qoder-dir / --trae-dir / --workbuddy-dir` 指定。服务端不会刷新 refresh token（会让客户端登出），token 临近过期时先打开客户端让它自己刷新，再 `sign-cli push`。

## 后台常驻服务 + 真实 ticket 验证（macOS，本机运行）

```bash
tools/service.sh start        # 后台启动（脱离终端，调度器开启）；另有 stop/restart/status/logs/token
tools/service.sh install      # 可选：登录后自动启动（launchd）
tools/verify_local.sh         # 提取并提交真实 ticket -> 触发真实签到 -> 打印结果
tools/verify_local.sh -p trae -p workbuddy -y     # 跳过确认、不碰钥匙串（不含 Qoder）
```

默认服务地址 http://127.0.0.1:8765（`SIGN_PORT` / `SIGN_HOST` 可改），数据在 `data/`，管理 token 用 `tools/service.sh token` 查看。验证脚本会在缺少 CLI 配置时自动生成 `~/.config/fansy/sign.conf`，之后日常直接运行 `sign-cli` 即可。真实签到会领取积分，触发前会再确认一次。

## 脚本文件布局

签到脚本以文件保存，数据库只做索引；脚本源码以文件为准：

```
scripts/<平台key>/manifest.json      名称、凭证声明、config(如 api_base)、超时
scripts/<平台key>/current.py         当前启用版本（始终等于启用版本，可直接用编辑器改）
scripts/<平台key>/versions/v<N>.py   历史版本，只增不改
```

- 面板里发布 → 写 `versions/v<N>.py`；启用/回滚 → 覆盖 `current.py`。
- 直接改了 `current.py`：重启或 `POST /api/scripts/sync`，自动登记为新版本并启用。
- 新建一个含 `current.py` 的目录并同步，即成为新平台。Docker 下目录在 `/data/scripts`，首次从镜像内置脚本复制。

## 测试

```bash
cd backend && uv run pytest        # 含 tests/test_live_e2e.py 真实端到端
cd cli && uv run pytest
```

`test_live_e2e.py`：按各客户端的真实格式伪造本机客户端数据 → 真实 `sign-cli` 进程提取（Qoder macOS/Windows 两种本地解密）→ 真实 uvicorn 服务解密入库 → 脚本文件执行签到 → 假平台接口校验必需请求头。

## 其他接口

```
PUT /api/platforms/{key}/accounts/{账号名}/credentials/{凭证名}?create=1   # JSON {"value":..} / multipart file / 原始 body
Authorization: Bearer <api token | admin token>
```

脚本规范：`run(ctx)` 必须；`on_credential(ctx, name, raw)` 可选。模板见面板「平台与脚本」或 `backend/app/builtin/`。
