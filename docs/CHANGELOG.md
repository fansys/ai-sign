# 修改记录

## 2026-10-10 修复流水版本号
- 当日明细流水的 `vN` 显示的是 script_version 表自增 id，与脚本实际版本号不符；`/api/days`、`/api/runs` 的 run 行新增 `version`（脚本版本号），前端改用它。`version_id` 字段保留。

## 2026-10-10 CLI 下载改为免安装 zip
- `GET /api/cli/download` 返回 `sign-cli.zip`：`signcli/` + `sign-cli.sh` / `sign-cli.bat`（解压即用、无需安装，需 Python 3.9+）+ `sign.conf`（内置服务地址与 apikey，权限 600）。
- apikey 复用名为 `cli-download` 的未吊销 token（仅“提交凭证”权限），没有则自动创建；可在设置页重新生成/删除。
- CLI 配置查找顺序：`SIGN_CLI_CONFIG` > 程序目录 `sign.conf` > `~/.config/fansy/sign.conf`；移除原 `_default.py` 内置地址机制。

## 2026-10-10 CI 支持手动触发
- `docker.yml` 增加 `workflow_dispatch`（Actions 页 Run workflow），可选是否推送镜像；在 main 上手动运行同样打 `latest` 与 sha 标签。

## 2026-10-10 GitHub 仓库地址
- 仓库为 https://github.com/fansys/ai-sign（origin 用 SSH）；镜像名改为 ghcr.io/fansys/ai-sign（compose、README、Dockerfile source 标签同步；workflow 用 `github.repository`，无需改）。

## 2026-10-10 CLI 下载
- 设置页「在本机使用 CLI」新增下载按钮：`GET /api/cli/download?server=`（管理员）动态打包 `cli/`（前端传 `location.origin`，缺省按 Host/X-Forwarded-* 推断；仅允许 http/https）。
- Dockerfile 将 `cli/pyproject.toml`、`cli/signcli` 复制到 `/srv/cli`（`.dockerignore` 不再排除 cli，仍排除 tests/uv.lock）。

## 2026-10-10 账号单独签到
- 账号页每行新增“签到”按钮（调用 `POST /api/runs {account_id}`，后端无改动）；账号停用或无凭证时禁用。

## 2026-10-10 多语言与移动端适配
- 新增 `frontend/js/i18n.js`（zh / en，模板内用 `$t(key)`）；顶栏按钮切换语言，默认跟随浏览器，选择存 localStorage `sign_lang`。
- `style.css` 增加 ≤900px（单列）与 ≤640px（顶栏换行、页签横向滚动、表格横向滚动、紧凑日历）断点。
- 后端/脚本产生的运行消息仍为中文，不随语言切换。已用无头 Chrome 验证 390px 与桌面的中英文无报错；未在真机测试。

## 2026-10-10 前端重构为 Vue 3（无构建）
- 单文件 `index.html`（原生 DOM + 内联 JS）拆为 `frontend/`：`index.html`、`style.css`（样式原样迁移）、`js/{api,dialog,toast,store,utils}.js`、`js/components/*.js`（App/Dashboard/Scripts/Accounts/Settings/BarkSettings/TokenSettings/Modal/HelpTip）。
- Vue 3 以 ES module 随仓库分发（`vendor/vue.esm-browser.prod.js`，importmap 引用），组件用 template 字符串，无需 npm / 打包 / 编译；后端与 Dockerfile 不变。
- 页面外观与交互保持不变；已用无头 Chrome 验证四个页签与登录弹窗无报错。

## 2026-10-10 Bark 推送
- 设置页可配置 Bark 服务器与 Device Key（key 加密存 `setting` 表，页面只显示尾 4 位，留空保存即保持原值），可发送测试推送。详见 docs/sql/20261010_add_setting_table.sql
- 触发：账号当天首次签到成功推送（含积分）；“签到失败（含超时）”与“需重新授权”为两个独立开关（默认开）；需重新授权仅在脚本判定 ticket 无效（服务端 401/403 或本地凭证已过期）时触发；复选框改为自定义样式。手动“测试”运行不推送。
- 新增 `backend/app/notify.py`；接口 `GET/PUT /api/settings/bark`、`POST /api/settings/bark/test`。

## 2026-10-10 Docker 化与 CI、杂项优化
- Dockerfile：直接用 venv 启动（仍以 root 运行）、HEALTHCHECK；新增 `.dockerignore`；compose 改用 ghcr 镜像，数据挂载 `./data:/data`，`SIGN_MASTER_KEY`/`SIGN_ADMIN_TOKEN` 改为可选（缺省在 ./data 自动生成）。
- 新增无需鉴权的 `GET /healthz`；启动日志不再打印完整管理 token（仅尾 6 位）。
- 新增 `.github/workflows/docker.yml`：先跑 backend/cli pytest，再构建 amd64+arm64 镜像，非 PR 时推送 ghcr.io（main→latest，tag v*→同名，另有 sha）。
- 前端：登录与发布说明改用统一模态框（无原生 alert/prompt/confirm），登录可选“记住 token”（勾选存 localStorage，否则仅本标签页 sessionStorage），token 失效时自动弹出重新登录。
- 前端：时间格式 `yyyy-MM-dd HH:mm:ss`；下拉框、文件输入框样式优化（保留原生控件）。

## 2026-10-10 favicon 与顶栏 logo
- 新增 `frontend/favicon.svg`（日历 + 橙色对勾，黄底粗描边，与面板风格一致）；页面 `<link rel=icon>` 与顶栏 logo 共用该文件。

## 2026-10-10 代码精简
- 后端：删除未被前端/CLI/测试使用的接口与逻辑：`POST /api/platforms`（新平台改为新建 scripts/<key>/ 后 sync）、`GET /accounts/{id}/credentials`、`DELETE …/credentials/{name}`、账号 `pinned_version_id`（模型字段与相关逻辑）、`?token=` 查询串鉴权；清理未用 import。`api_token`/`account` 表无结构迁移，旧 `account.pinned_version_id` 列留在库中不再使用。
- CLI：删除 `sign-cli push --run` 与 `Client.run`（需要管理 token，apikey 无权限，实际不可用）；清理未用变量。
- 前端：删除未用的 `ymd` 与 `.btn` 样式。

## 2026-10-10 页面样式优化、危险操作按钮
- 按钮 hover/focus 反馈、表格行高亮、表头样式；危险操作（删除）红色按钮带 ✕，风险操作（重新生成）橙色按钮。
- 删除账号 / 删除 token / 重新生成 token 改用自定义确认弹窗（红/橙主题，Esc 或点遮罩取消，默认聚焦“取消”）。

## 2026-10-10 API Token 支持删除与重新生成
- `DELETE /api/tokens/{id}` 改为物理删除（原为吊销）；新增 `POST /api/tokens/{id}/regenerate`：同名同权限换新原文，旧值立即失效。前端按钮：重新生成 / 删除（均二次确认）。

## 2026-10-10 账号名自动命名，优先取官方 API
- 脚本在 meta 中给出 `identity`（稳定 id）和 `label`；服务端 `resolve_account` 按 identity 合并/改名，CLI 默认账号 `default` 会被替换。
- 命名：Qoder CN `name (脱敏手机)`、Qoder `name (email)`、Trae CN `ScreenName (脱敏手机)`、WorkBuddy `nickname`。
- Qoder 系：`GET /api/v1/userinfo`（Bearer）；Trae：`POST /cloudide/api/v3/trae/GetUserInfo`，头 `x-cloudide-token: <JWT>`；失败回退本地 ticket 字段。WorkBuddy 无可用 API，仍用本地字段。

## 2026-10-10 凭证/API Token 可复制、国际版 Qoder、显示优化
- 新增平台 `qoder-intl`（显示名 Qoder，接口 openapi.qoder.sh）；国内版改名 Qoder CN / Trae CN。
- 凭证复制：`GET /api/accounts/{id}/credentials/{name}/value`（仅管理员，no-store）。
- API Token 加密保存并支持复制：`GET /api/tokens/{id}/value`；列表只显示带星号形式。旧 token 不可复制。详见 docs/sql/20261010_api_token_add_token_enc.sql
- Trae 脚本从 JWT `exp` 取到期时间；WorkBuddy 单文件账号名统一为 `WorkBuddy`。
- 前端：tab 刷新保留（URL hash）、凭证标签统一样式、账号名去掉 default。
