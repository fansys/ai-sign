# AI 自动签到服务 · 设计方案

> 技术选型：Python 3.12 + FastAPI + SQLite（可平滑切 PostgreSQL）+ APScheduler；前端 Vue 3（无构建）；单机 Docker 部署。签到脚本使用 Python 编写。

## 1. 目标与范围

| 需求 | 方案要点 |
|---|---|
| 多平台、多账号 | 「平台 Platform」下挂多个「账号 Account」，每个账号独立凭证、独立执行记录 |
| API 提交 key/token/数据文件 | 凭证 API（JSON 值 / 文件上传），加密落库，脚本按名取用 |
| 脚本解析 ticket | 脚本除 `run()` 外可实现 `on_credential()` 钩子，提交时即解析校验 |
| 良好扩展性 | 平台 = 脚本 + manifest；通知、调度、凭证类型均为可插拔点 |
| 脚本版本控制 | 版本不可变，平台指向「启用版本」，支持回滚、diff、试运行 |
| 在线编辑 | 在线编辑器 → 保存为草稿 → 试运行 → 发布为新版本 → 启用 |

## 2. 总体架构

```
 ┌────────── Web UI (Vue 3) ──────────┐      外部系统 / 抓包工具 / 手机快捷指令
 │ 仪表盘 | 平台&脚本 | 账号&凭证 | 设置 │                │ (Bearer API Token)
 └───────────────┬─────────────────────┘                │
                 │ REST (JSON)                          │
        ┌────────▼──────────────────────────────────────▼───────┐
        │                    FastAPI 应用                        │
        │  Auth │ Platform │ Account │ Credential │ Script │ Run │
        └───┬──────────┬───────────────┬──────────────┬─────────┘
            │          │               │              │
     ┌──────▼───┐ ┌────▼─────┐   ┌─────▼──────┐  ┌────▼─────────┐
     │ SQLite/PG│ │ 加密层   │   │ Scheduler  │  │ Notifier插件 │
     │          │ │(Fernet)  │   │(APScheduler)│ │ webhook/Bark…│
     └──────────┘ └──────────┘   └─────┬──────┘  └──────────────┘
                                       │ 入队
                                ┌──────▼───────┐
                                │ Runner(并发池)│  每次执行 = 独立子进程
                                └──────┬───────┘
                                       │ stdin: ctx(JSON) / stdout: 事件+结果
                                ┌──────▼───────┐
                                │ 签到脚本沙箱  │  Python，受限环境
                                └──────────────┘
```

单进程部署即可：API、调度器、Runner 同进程（Runner 通过 `asyncio.create_subprocess_exec` 拉起脚本子进程）。后期若要横向扩展，把 Runner 拆成 worker 并用队列（Redis/DB 表轮询）即可，接口不变。

## 3. 核心领域模型

```
Platform 1──* ScriptVersion          Platform.active_version_id → 当前启用版本
Platform 1──* Account 1──* Credential
Account  1──* Run 1──* RunEvent      （Run = 一次签到尝试；Event = 动作流水）
Account  1──* AccountState           （脚本可持久化的 KV，如刷新后的 token、上次签到日）
```

### 表结构（要点字段）

**platform**
`id, key(唯一, 如 workbuddy), name, icon, enabled, manifest(JSON), active_version_id, schedule_override(JSON|null), created_at`

**script_version**（不可变）
`id, platform_id, version(自增 1,2,3…), source(TEXT), sha256, note(提交说明), author, created_at, parent_version_id`
草稿单独存 `script_draft(platform_id, source, updated_at)`，每平台一份，不占版本号。

**account**
`id, platform_id, name(如“主号”), enabled, schedule_override, created_at`

**credential**
`id, account_id, name(如 token / cookie / har), kind(text|json|file), value_enc(BLOB), filename, size, status(valid|expired|unknown), parsed_meta(JSON, 脱敏摘要), updated_at, expires_at`
同一 `(account_id, name)` 唯一，更新即覆盖；可选保留最近 N 次历史用于回滚。

**run**
`id, account_id, script_version_id, trigger(schedule|retry|manual|test), local_date(YYYY-MM-DD, Asia/Shanghai), status(success|already|failed|need_auth|timeout|running), attempt_no, points, message, started_at, finished_at, duration_ms`

**run_event**（动作流水）
`id, run_id, ts, level, tag, message, data(JSON)`

**api_token**
`id, name, token_hash, scopes(credentials:write 等), last_used_at, revoked_at`

**notifier**
`id, type(webhook|bark|telegram|email), config_enc, events(failed|need_auth|success), enabled`

## 4. 签到脚本规范（扩展性的核心）

每个平台的脚本是一个 Python 模块，约定两个入口：

```python
# manifest 写在平台配置里，也可在脚本头部以 MANIFEST 常量声明
MANIFEST = {
    "name": "WorkBuddy",
    "credentials": [                       # 驱动前端“账号凭证”表单
        {"name": "token",  "kind": "text", "required": True,  "label": "登录 Token"},
        {"name": "device", "kind": "file", "required": False, "label": "设备数据文件"},
    ],
    "timeout_sec": 60,
    "schedule": {"daily": "10:05", "retry_hourly": ["11:00", "23:00"], "max_attempts": 14},
}

async def on_credential(ctx, name: str, raw: bytes) -> dict:
    """凭证提交时调用：解析 ticket、校验有效性。
    返回 {"value": <清洗后要保存的值>, "meta": {...脱敏摘要}, "expires_at": ...}
    抛 CredentialError 则拒绝保存并返回 4xx。"""

async def run(ctx) -> dict:
    """执行一次签到。返回 {"status": "success|already|failed|need_auth",
                          "points": 100, "message": "今日已签到"}"""
```

### ctx 能力（白名单 SDK，脚本只能通过它访问外部）

| 能力 | 说明 |
|---|---|
| `ctx.cred(name)` / `ctx.cred_file(name)` | 取凭证文本/文件字节 |
| `ctx.save_cred(name, value)` | 脚本刷新了 token 后回写 |
| `ctx.http` | 预配置的 httpx.AsyncClient（统一超时、UA、代理、请求日志自动脱敏入流水） |
| `ctx.state.get/set` | 账号级持久 KV |
| `ctx.log.info/warn/error(tag, msg, **data)` | 写入 run_event |
| `ctx.today` / `ctx.now` | 统一按 Asia/Shanghai |
| `ctx.is_test` | 试运行标志（脚本可据此跳过破坏性操作） |
| `ctx.browser`（可选扩展） | 需要 Playwright 的平台再开启 |

### 执行与隔离

- 每次执行启动独立子进程：`python -I -m runner.bootstrap`，ctx 与脚本源码通过 stdin 传入，**凭证只走 stdin，不进环境变量/命令行/磁盘**。
- 子进程用 `resource` 限制 CPU/内存/文件数，清空环境变量，工作目录为临时空目录，超时强杀。
- 事件通过 stdout 的 JSON Lines 回传（log、save_cred、result），主进程统一落库。
- 说明：Python 子进程不是强沙箱。个人/小团队、脚本由自己编写的场景够用；若将来开放第三方脚本，升级为“每次执行起一个一次性容器/nsjail + 网络白名单”，Runner 接口不用改。
- 平台库白名单：基础镜像预装 httpx、lxml、pycryptodome 等；脚本 `import` 其他包会报错（后续可加“依赖声明”）。

## 5. 版本控制与在线编辑

```
 编辑草稿 ──保存──▶ script_draft
     │
     ├─ 试运行(选账号) ──▶ run(trigger=test, 使用草稿源码, 不计入日历)
     │
     └─ 发布 ──▶ 新建 script_version (v+1, sha256 去重, 必填 note)
                       │
                       └─ 启用 ──▶ platform.active_version_id = v
```

- 版本不可变，只能新增；“回滚”= 把 active 指回旧版本（可选：基于旧版创建草稿）。
- 启用前强制：语法检查（`ast.parse`）+ 校验 `run` 存在 + 可选“用某账号试运行通过”。
- 每个 Run 记录所用 `script_version_id`，出问题能精确追溯到版本。
- 前端：文本编辑器 + 版本列表 + 任意两版 diff + 试运行日志面板。
- 新建平台时提供脚本模板（Cookie 型、Token+接口型、需 ticket 解析型）。

## 6. 凭证提交 API

鉴权：`Authorization: Bearer <api_token>`，token 在「设置」页创建，仅显示一次，库内存哈希，可按 scope 与平台限制。

```
PUT  /api/accounts/{account_id}/credentials/{name}        提交/更新
     Content-Type: application/json   {"value": "xxx"}          # 文本或 JSON
     Content-Type: multipart/form-data  file=@data.har          # 文件
     → 若脚本定义了 on_credential：同步执行，返回 meta/校验结果

PUT  /api/platforms/{key}/accounts/{account_name}/credentials/{name}
     # 便于外部工具按名称提交，不需要知道数字 ID；账号不存在时可 ?create=1 自动创建

GET  /api/accounts/{id}/credentials                         仅返回名称/状态/脱敏摘要/更新时间
DELETE /api/accounts/{id}/credentials/{name}
```

- 落库前使用 Fernet(AES-128-CBC+HMAC) 或 AES-GCM 加密，主密钥来自环境变量 `SIGN_MASTER_KEY`（不入库、不入镜像）。
- 接口永不回显明文；日志对 token、cookie 自动脱敏。
- 凭证被脚本判定失效（`need_auth`）→ 状态置 `expired` → 触发通知，提醒重新提交。
- 单文件大小上限（默认 5MB），文件存加密 BLOB（小文件）或加密后落 `data/` 目录。

## 7. 调度策略（每天 10:05 签到 · 11:00–23:00 整点补签）

- 时区固定 Asia/Shanghai；APScheduler 的 cron 触发器。
- **每日主任务**：10:05 为所有启用账号各创建一次 Run。
- **整点补签**：11:00–23:00 每小时扫描“今日尚无 success/already 的启用账号”，重新执行，直到成功或达到 `max_attempts`。
- 幂等：以 `(account_id, local_date)` 为维度，已成功则跳过；同账号同时只允许一个 running（DB 唯一约束/内存锁）。
- `need_auth` 不再重试，直接通知并等待新凭证（提交新凭证后可自动触发一次补签）。
- 平台/账号可覆盖默认时间表；支持“立即签到”（全部/单平台/单账号）。
- 服务重启后对 `running` 的残留 Run 标记为 `failed(interrupted)`，并补跑错过的任务（misfire_grace）。

## 8. 前端页面（米黄底、粗黑描边、硬阴影）

1. **仪表盘（日历 + 当日明细）**
   - 顶栏：标题、调度说明、今天日期、更新时间；按钮「刷新」「立即签到」。
   - 左：月历，月份切换（上个月/今天/下个月），每天以颜色表示：全部成功(绿)、部分待签到(橙)、有失败(红)、无记录(空)；点点标记当日涉及的平台数；今天高亮。
   - 右：当日明细——「当日结果（每个平台一条）」展示状态、积分、尝试次数、时间；「动作流水（时间倒序）」展示每次 Run 的来源（手动/定时/补签）、结果、重复次数 ×N，可展开看 run_event 日志。
2. **平台与脚本**：平台列表 → 脚本编辑器、版本时间线、diff、试运行、启用/回滚。
3. **账号与凭证**：按平台分组，账号启用开关、凭证状态（有效/过期）、上传/粘贴凭证、复制 API 提交命令（curl 示例）。
4. **设置**：API Token、通知渠道、全局调度、时区。

仪表盘接口：

```
GET  /api/calendar?month=2026-09            → [{date, status, platform_count}]
GET  /api/days/2026-09-28                   → {summary:{success,actions}, results:[每平台一条], actions:[流水]}
POST /api/runs  {platform?, account?}       → 立即签到（返回 run_id，可 SSE 订阅进度）
GET  /api/runs/{id}/events (SSE)
```

日历状态计算：当日所有“应签到账号”中——全部 success/already → 绿；存在 failed/need_auth → 红；有账号尚未成功但无失败 → 橙；无记录 → 空。每账号取当日最后一条有效 Run。

## 9. 扩展点汇总

| 扩展点 | 方式 |
|---|---|
| 新平台 | 页面新建平台 + 写脚本（或套模板），无需改后端代码 |
| 新凭证类型 | `kind` 枚举 + 前端表单控件注册 |
| 新通知渠道 | 实现 `Notifier` 接口（`send(event)`），注册到 registry |
| 新触发器 | Scheduler 之外增加 webhook 触发（`POST /api/runs`）即可 |
| 脚本能力 | 在 SDK `ctx` 上新增方法（如 browser、验证码识别），脚本按需使用 |
| 存储切换 | SQLAlchemy + Alembic，SQLite → PostgreSQL 仅改连接串 |
| 多 Worker | Runner 抽象为队列消费者，调度器只负责入队 |

## 10. 项目结构

```
sign/
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI 入口，挂载静态前端
│  │  ├─ api/               # platforms, accounts, credentials, scripts, runs, calendar, auth
│  │  ├─ core/              # config, security(加解密/token), db, logging(脱敏)
│  │  ├─ models/            # SQLAlchemy 模型
│  │  ├─ services/          # script_service(版本/发布), credential_service, run_service, calendar_service
│  │  ├─ scheduler/         # jobs.py（主任务/补签）
│  │  ├─ runner/            # executor.py(拉子进程), bootstrap.py(子进程内SDK与ctx)
│  │  ├─ notifiers/         # base.py, webhook.py, bark.py ...
│  │  └─ templates/         # 脚本模板
│  ├─ alembic/ , tests/
├─ frontend/                # Vue 3（ES module，无构建，vendor/ 内置）+ 原生 textarea 编辑器，由 FastAPI 静态托管
├─ data/                    # sqlite、加密文件（挂载卷）
├─ Dockerfile, docker-compose.yml
└─ DESIGN.md
```

## 11. 安全要点

- 管理端登录（单用户密码 + Session/JWT），API Token 与登录分离。
- 凭证加密落库、不回显；日志、事件、异常栈统一脱敏。
- 脚本执行隔离（子进程 + 资源限制 + 超时 + 清空环境），出站网络可选域名白名单。
- 脚本源码属于高权限输入：仅管理员可编辑；每次发布留审计记录（author/note/hash）。
- 备份：`data/` 目录 + `SIGN_MASTER_KEY` 必须一起备份，丢失密钥则凭证无法解密。
