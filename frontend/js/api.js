import { modal } from './dialog.js'
import { t } from './i18n.js'
import { toast } from './toast.js'

let token = localStorage.getItem('sign_token') || sessionStorage.getItem('sign_token') || ''
const clearToken = () => {
  token = ''
  localStorage.removeItem('sign_token')
  sessionStorage.removeItem('sign_token')
}

let pendingLogin = null   // 并发请求共用同一个登录弹窗
const login = err => pendingLogin || (pendingLogin = doLogin(err).finally(() => { pendingLogin = null }))

async function doLogin(err = '') {
  const r = await modal(t('login'), err || t('enterToken'), t('login'), '', {
    hint: t('loginHint'),
    cancel: false, required: true,
    input: { type: 'password', placeholder: t('tokenPh') },
    check: { label: t('remember'), checked: false },
  })
  clearToken()
  token = r.value.trim()
  ;(r.checked ? localStorage : sessionStorage).setItem('sign_token', token)
}

async function authFetch(path, opt = {}) {
  if (!token) await login()
  for (;;) {
    const isJson = opt.body && !(opt.body instanceof FormData)
    const r = await fetch(path, {
      ...opt,
      headers: { Authorization: 'Bearer ' + token, ...(isJson ? { 'Content-Type': 'application/json' } : {}), ...opt.headers },
    })
    if (r.status !== 401) return r
    clearToken()
    await login(t('badToken'))
  }
}

export async function api(path, opt = {}) {
  const r = await authFetch(path, opt)
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || j))
  return j
}

export const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body || {}) })
export const put = (path, body) => api(path, { method: 'PUT', body: JSON.stringify(body) })
export const patch = (path, body) => api(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = path => api(path, { method: 'DELETE' })

/** 取文本接口（凭证 / token 原文）并写入剪贴板 */
export async function copyFrom(path, okMsg) {
  const r = await authFetch(path)
  if (!r.ok) throw new Error(t('copyFail', { s: r.status }))
  await navigator.clipboard.writeText(await r.text())
  toast(okMsg)
}

/** 带鉴权下载文件（浏览器无法给 <a> 加 Authorization 头，改用 blob） */
export async function download(path, filename) {
  const r = await authFetch(path)
  if (!r.ok) throw new Error(t('downloadFail', { s: r.status }))
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await r.blob())
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

/** 包装异步处理函数：异常统一用 toast 提示 */
export const guard = fn => async (...a) => {
  try { return await fn(...a) } catch (e) { toast(e.message) }
}
