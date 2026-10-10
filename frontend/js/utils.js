import { t } from './i18n.js'

export const pad = n => String(n).padStart(2, '0')
export const fmt = t => (t ? String(t).replace('T', ' ').slice(0, 19) : '-')   // yyyy-MM-dd HH:mm:ss

// 状态 → [文案 key, 样式]
const ST = {
  success: ['st.done', 'g'], already: ['st.done', 'g'], failed: ['st.failed', 'r'],
  need_auth: ['st.need_auth', 'r'], timeout: ['st.timeout', 'r'], running: ['st.running', 'o'],
}
export const stLabel = s => (ST[s] ? t(ST[s][0]) : s)
export const stCls = s => (ST[s] || [0, 'o'])[1]
export const trLabel = s => (['schedule', 'retry', 'manual', 'test'].includes(s) ? t('tr.' + s) : s)

// 账号 / 运行记录显示名：default 或与平台同名时只显示平台名
export const accLabel = a => (a.name === 'default' || a.name === a.platform_name ? a.platform_name : a.platform_name + ' / ' + a.name)
export const runLabel = r => r.platform + (r.account === 'default' || r.account === r.platform ? '' : ' · ' + r.account)

export const eventLines = events => events.map(e => `${e.ts} [${e.level}] ${e.tag} ${e.message}`).join('\n')

/** 按行 LCS 对比 a→b，返回 [{cls:'a'|'d', text}]（相同行省略） */
export function lineDiff(a, b) {
  const A = a.split('\n'), B = b.split('\n')
  const L = Array.from({ length: A.length + 1 }, () => new Array(B.length + 1).fill(0))
  for (let i = A.length - 1; i >= 0; i--)
    for (let j = B.length - 1; j >= 0; j--)
      L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1])
  const out = []
  let i = 0, j = 0
  while (i < A.length || j < B.length) {
    if (i < A.length && j < B.length && A[i] === B[j]) { i++; j++ }
    else if (j < B.length && (i === A.length || L[i][j + 1] >= L[i + 1][j])) out.push({ cls: 'a', text: '+ ' + B[j++] })
    else out.push({ cls: 'd', text: '- ' + A[i++] })
  }
  return out
}
