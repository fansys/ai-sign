import { ref } from 'vue'

// 轻量多语言：t('key', {参数}) 读取 locale，切换语言时模板自动刷新。后端返回的运行消息保持原文。
const messages = {
  zh: {
    title: 'AI 自动签到控制面板', loading: '加载中…', refresh: '刷新', runNow: '立即签到', runAcc: '签到', runTriggered: '已触发，稍后自动刷新',
    sub: '每天 {at} 签到 · {from}:00–{to}:00 整点补签 · 今天是 {today} · 更新于 {now}',
    'tab.dash': '面板', 'tab.script': '平台与脚本', 'tab.acc': '账号与凭证', 'tab.set': '设置', langSwitch: 'English',
    ok: '确定', cancel: '取消', copyFail: '复制失败 HTTP {s}', delete: '删除', confirmDelete: '确认删除',
    login: '登录', enterToken: '请输入管理 token', loginHint: '在 data/admin.token 文件，或环境变量 SIGN_ADMIN_TOKEN 中查看',
    tokenPh: '管理 token', remember: '记住 token', badToken: 'token 无效或已失效，请重新输入',
    // 面板
    calTitle: '·· 签到日历', calHint: '点击某天查看当天明细', monthTitle: '{y} 年 {m} 月', prevMonth: '上个月', today: '今天', nextMonth: '下个月',
    weekdays: '一,二,三,四,五,六,日', legendOk: '全部成功', legendPartial: '部分待签到', legendFail: '有失败', legendNone: '无记录',
    recorded: '本月有记录 {n} 天', detail: '·· 明细', detailOf: '·· {d} 明细', byTimeDesc: '按时间倒序', dayResults: '当日结果（每个账号一条）',
    actionFlow: '动作流水 · 时间倒序', successN: '成功 {n}', actionsN: '动作 {n} 条', noRecord: '当天没有记录', pointsN: '积分 {n}',
    attemptsN: '尝试 {n} 次', noLogs: '（无日志）',
    'st.done': '今日已签到', 'st.failed': '失败', 'st.need_auth': '需重新授权', 'st.timeout': '超时', 'st.running': '执行中',
    'tr.schedule': '定时', 'tr.retry': '补签', 'tr.manual': '手动', 'tr.test': '测试',
    // 脚本
    platform: '平台', draft: '草稿（未发布）', activeVersion: '已启用版本', noAcc: '无账号', saveDraft: '保存草稿', testRun: '试运行', publish: '发布',
    testResult: '试运行结果（不计入日历，ctx.is_test=True）', versionHistory: '版本历史', version: '版本', note: '说明', author: '作者', time: '时间',
    inUse: '启用中', load: '载入', compare: '与编辑区对比', enable: '启用', draftSaved: '草稿已保存', platNoAcc: '该平台还没有账号', running: '运行中…',
    testOut: '状态: {status}  积分: {points}\n消息: {msg}\n\n', publishTitle: '发布新版本', notePh: '发布说明（必填）', activateNow: '发布后立即启用该版本',
    published: '已发布', activated: '已启用/回滚', loadedVer: '已载入 v{v}（保存草稿后可基于它发布新版本）', diffTitle: 'v{v} → 编辑区', noDiff: '无差异',
    // 账号
    addAccount: '新增账号', accNamePh: '账号名，如 主号', add: '添加', colAccount: '平台/账号', colEnabled: '启用', colCred: '凭证', notSubmitted: '未提交',
    expiredSuffix: ' · 已过期', credTip: '点击复制 · 更新 {u}', credTipExp: ' · 到期 {e}', delAccTitle: '删除账号',
    delAccMsg: '将永久删除「{name}」及其全部凭证和签到记录，无法恢复。', thisAcc: '该账号', copied: '{n} 已复制到剪贴板', submitCred: '提交凭证', upload: '上传',
    pastePh: '或直接粘贴凭证内容（JSON / 文本）', cliTip1: '更省事的方式：在装有客户端的电脑上运行 ', cliTip2: '，自动提取并提交。',
    pickOrPaste: '请选择文件或粘贴内容', savedStatus: '已保存，状态：{s}',
    // 设置
    barkTitle: 'Bark 推送', barkHint: '勾选的事件会推送', server: '服务器', deviceKey: 'Device Key', evSuccess: '当天首次签到成功', evFail: '签到失败',
    evAuth: '需重新授权（ticket 无效）', save: '保存', sendTest: '发送测试', saved: '已保存', testSent: '测试推送已发送', keyPh: 'Bark App 里的 key',
    keySavedPh: '已保存（{m}），留空保持不变', tokenTitle: 'API Token', tokenNamePh: '名称，如 my-pc', create: '创建', created: '已创建，可在列表中复制',
    colName: '名称', colToken: 'Token', colScopes: '权限', colLastUsed: '最近使用', copy: '复制', tokenCopied: 'API Token 已复制到剪贴板',
    regen: '重新生成', delTokTitle: '删除 API Token', delTokMsg: '删除后，使用该 token 的 CLI 将无法再提交凭证，且无法恢复。',
    regenTitle: '重新生成 API Token', regenMsg: '旧 token 将立即失效，需要把新值更新到使用它的 CLI 配置（~/.config/fansy/sign.conf）。', regenerated: '已重新生成，可在列表中复制',
    cliTitle: '在本机使用 CLI', cliDownload: '下载 CLI（已内置本服务地址）', downloadFail: '下载失败 HTTP {s}',
    cliHint: '# 解压下载的 sign-cli.zip 后（服务地址 {url} 已内置）\npip install ./sign-cli   # 或 uv tool install ./sign-cli\nsign-cli init            # 只需填入上面创建的 token\n\n# 也可手动配置 ~/.config/fansy/sign.conf\n[server]\nurl = {url}\napikey = <上面创建的 token>\n\nsign-cli        # 交互确认后提交\nsign-cli push -y  # 全部提交',
  },
  en: {
    title: 'AI Auto Check-in Console', loading: 'Loading…', refresh: 'Refresh', runNow: 'Check in now', runAcc: 'Check in', runTriggered: 'Triggered, refreshing shortly',
    sub: 'Daily at {at} · hourly retry {from}:00–{to}:00 · Today {today} · Updated {now}',
    'tab.dash': 'Dashboard', 'tab.script': 'Platforms & Scripts', 'tab.acc': 'Accounts & Credentials', 'tab.set': 'Settings', langSwitch: '中文',
    ok: 'OK', cancel: 'Cancel', copyFail: 'Copy failed: HTTP {s}', delete: 'Delete', confirmDelete: 'Delete',
    login: 'Sign in', enterToken: 'Enter the admin token', loginHint: 'Find it in data/admin.token, or the SIGN_ADMIN_TOKEN environment variable',
    tokenPh: 'Admin token', remember: 'Remember token', badToken: 'Invalid or expired token, please enter it again',
    calTitle: '·· Calendar', calHint: 'Click a day for details', monthTitle: '{mon} {y}', prevMonth: 'Prev', today: 'Today', nextMonth: 'Next',
    weekdays: 'Mon,Tue,Wed,Thu,Fri,Sat,Sun', legendOk: 'All done', legendPartial: 'Pending', legendFail: 'Failed', legendNone: 'No record',
    recorded: '{n} day(s) recorded this month', detail: '·· Details', detailOf: '·· Details · {d}', byTimeDesc: 'Newest first', dayResults: 'Results of the day (one per account)',
    actionFlow: 'Activity · newest first', successN: 'Success {n}', actionsN: '{n} action(s)', noRecord: 'No records for this day', pointsN: 'Points {n}',
    attemptsN: '{n} attempt(s)', noLogs: '(no logs)',
    'st.done': 'Checked in', 'st.failed': 'Failed', 'st.need_auth': 'Re-auth needed', 'st.timeout': 'Timeout', 'st.running': 'Running',
    'tr.schedule': 'Scheduled', 'tr.retry': 'Retry', 'tr.manual': 'Manual', 'tr.test': 'Test',
    platform: 'Platform', draft: 'Draft (unpublished)', activeVersion: 'Active version', noAcc: 'No account', saveDraft: 'Save draft', testRun: 'Test run', publish: 'Publish',
    testResult: 'Test result (not counted in calendar, ctx.is_test=True)', versionHistory: 'Version history', version: 'Version', note: 'Note', author: 'Author', time: 'Time',
    inUse: 'Active', load: 'Load', compare: 'Diff with editor', enable: 'Activate', draftSaved: 'Draft saved', platNoAcc: 'This platform has no account yet', running: 'Running…',
    testOut: 'Status: {status}  Points: {points}\nMessage: {msg}\n\n', publishTitle: 'Publish new version', notePh: 'Release note (required)', activateNow: 'Activate right after publishing',
    published: 'Published', activated: 'Activated / rolled back', loadedVer: 'Loaded v{v} (save as draft to publish a new version based on it)', diffTitle: 'v{v} → editor', noDiff: 'No difference',
    addAccount: 'Add account', accNamePh: 'Account name, e.g. main', add: 'Add', colAccount: 'Platform / Account', colEnabled: 'Enabled', colCred: 'Credentials', notSubmitted: 'Not submitted',
    expiredSuffix: ' · expired', credTip: 'Click to copy · updated {u}', credTipExp: ' · expires {e}', delAccTitle: 'Delete account',
    delAccMsg: '“{name}” and all its credentials and check-in records will be permanently deleted.', thisAcc: 'this account', copied: '{n} copied to clipboard', submitCred: 'Submit credentials', upload: 'Upload',
    pastePh: 'Or paste the credential content (JSON / text)', cliTip1: 'Easier: run ', cliTip2: ' on the computer with the client installed to extract and submit automatically.',
    pickOrPaste: 'Choose a file or paste content', savedStatus: 'Saved, status: {s}',
    barkTitle: 'Bark notifications', barkHint: 'Checked events will be pushed', server: 'Server', deviceKey: 'Device Key', evSuccess: 'First successful check-in of the day', evFail: 'Check-in failed',
    evAuth: 'Re-auth needed (invalid ticket)', save: 'Save', sendTest: 'Send test', saved: 'Saved', testSent: 'Test notification sent', keyPh: 'Key from the Bark app',
    keySavedPh: 'Saved ({m}); leave empty to keep', tokenTitle: 'API Token', tokenNamePh: 'Name, e.g. my-pc', create: 'Create', created: 'Created; copy it from the list',
    colName: 'Name', colToken: 'Token', colScopes: 'Scopes', colLastUsed: 'Last used', copy: 'Copy', tokenCopied: 'API Token copied to clipboard',
    regen: 'Regenerate', delTokTitle: 'Delete API Token', delTokMsg: 'CLIs using this token will no longer be able to submit credentials. This cannot be undone.',
    regenTitle: 'Regenerate API Token', regenMsg: 'The old token becomes invalid immediately; update the CLI config (~/.config/fansy/sign.conf) with the new value.', regenerated: 'Regenerated; copy it from the list',
    cliTitle: 'Use the CLI on this machine', cliDownload: 'Download CLI (server URL built in)', downloadFail: 'Download failed: HTTP {s}',
    cliHint: '# After unzipping sign-cli.zip (server URL {url} is built in)\npip install ./sign-cli   # or: uv tool install ./sign-cli\nsign-cli init            # just enter the token created above\n\n# Or configure ~/.config/fansy/sign.conf manually\n[server]\nurl = {url}\napikey = <the token created above>\n\nsign-cli        # confirm interactively, then submit\nsign-cli push -y  # submit all',
  },
}

const saved = localStorage.getItem('sign_lang')
const detect = () => ((navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en')
export const locale = ref(messages[saved] ? saved : detect())

/** 翻译；{name} 占位符用 params 替换。缺失的 key 回退中文，再回退 key 本身。 */
export function t(key, params = {}) {
  const s = messages[locale.value][key] ?? messages.zh[key] ?? key
  return s.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '')
}

export function setLocale(l) {
  locale.value = l
  localStorage.setItem('sign_lang', l)
  document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
  document.title = t('title')
}
export const toggleLocale = () => setLocale(locale.value === 'zh' ? 'en' : 'zh')
