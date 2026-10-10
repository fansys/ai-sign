import { reactive } from 'vue'

export const toastState = reactive({ msg: '', show: false })
let timer

export function toast(msg) {
  toastState.msg = msg
  toastState.show = true
  clearTimeout(timer)
  timer = setTimeout(() => { toastState.show = false }, 3500)
}
