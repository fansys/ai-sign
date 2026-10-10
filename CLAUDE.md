# Sign · AI 工具自动签到服务（项目上下文）

Qoder CN / Trae CN / WorkBuddy 的每日签到服务。设计见 DESIGN.md，用法见 README.md。

## 结构
- backend/   FastAPI + SQLAlchemy(SQLite) + APScheduler；uv 管理（`cd backend && uv sync && uv run pytest`）
- cli/       `sign-cli`：在本机提取 ticket 并提交（配置 ~/.config/fansy/sign.conf，依赖仅 cryptography）
- scripts/<平台>/{manifest.json,current.py,versions/vN.py}  签到脚本，文件为准；改 current.py 后 POST /api/scripts/sync 登记新版本
- frontend/   Vue 3 无构建单页面板（index.html + js/ 组件 + style.css；vendor/ 内置 Vue，不要引入 npm/打包步骤）；tools/service.sh 后台服务；tools/verify_local.sh 真实 ticket 验证
- 脚本约定：`run(ctx)` 必须，`on_credential(ctx,name,raw)` 可选；在隔离子进程里执行，凭证只经 stdin

## 已验证 / 未验证
- 已验证（假平台接口 + 按文章格式伪造的本地数据）：`cd backend && uv run pytest`（含 tests/test_live_e2e.py）、`cd cli && uv run pytest` 共 13 项通过。
- **未验证**：用真实 ticket 打真实平台接口；macOS 上 Qoder/Trae 的真实目录与加密格式
  （Qoder: ~/Library/Application Support/com.qodercn.app.stable/auth.v1.dat，口令在钥匙串 “Qoder CN App Safe Storage”，PBKDF2-SHA1/saltysalt/1003 + AES-128-CBC；
  Trae: …/Trae CN/User/globalStorage/storage.json；WorkBuddy: …/CodeBuddyExtension/Data/Public/auth/*.info）均来自第三方公开分析。

## 约束（务必遵守）
- 绝不打印/记录 token、口令、apikey；日志与输出只留尾 6 位；不要把凭证文件复制进仓库。
- 不要调用任何平台的 refresh token 接口（一次一换，会让客户端登出）。
- 真实签到会领取积分，触发前先向用户确认。
- 失败时先看 `tools/service.sh logs` 和运行日志，再改代码；改完跑两个目录的 pytest。
