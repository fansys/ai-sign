import { reactive } from 'vue'
import { t } from './i18n.js'

// 全局模态框状态，由 components/Modal.js 渲染
export const dlg = reactive({
  show: false, title: '', msg: '', hint: '', okText: '确定', kind: '',
  input: null, check: null, cancel: true, required: false, value: '', checked: false,
})
let resolver = null

/**
 * 通用模态框。opt: {input:{type,placeholder,value}, check:{label,checked}, hint, cancel:false, required}
 * 取消返回 null；确定返回 {value, checked}。
 */
export function modal(title, msg, okText = t('ok'), kind = '', opt = {}) {
  return new Promise(resolve => {
    Object.assign(dlg, {
      show: true, title, msg, okText, kind,
      hint: opt.hint || '', input: opt.input || null, check: opt.check || null,
      cancel: opt.cancel !== false, required: !!opt.required,
      value: opt.input?.value || '', checked: !!opt.check?.checked,
    })
    resolver = resolve
  })
}

export function closeModal(result) {
  dlg.show = false
  resolver?.(result)
  resolver = null
}

export const ask = async (title, msg, okText, kind) => !!(await modal(title, msg, okText, kind))
