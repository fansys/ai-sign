import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { closeModal, dlg } from '../dialog.js'
import HelpTip from './HelpTip.js'

export default {
  components: { HelpTip },
  setup() {
    const inp = ref(null), yes = ref(null), no = ref(null)
    const okClass = computed(() => (dlg.kind === 'danger' ? 'solid-danger' : dlg.kind === 'warn' ? 'solid-warn' : 'pri'))

    const submit = () => {
      if (dlg.input && dlg.required && !dlg.value.trim()) return inp.value?.focus()
      closeModal({ value: dlg.value, checked: dlg.checked })
    }
    const cancel = () => closeModal(null)
    const onKey = e => {
      if (e.key === 'Escape' && dlg.cancel) cancel()
      else if (e.key === 'Enter' && dlg.input && e.target !== no.value) submit()
    }
    watch(() => dlg.show, async show => {
      if (!show) return document.removeEventListener('keydown', onKey)
      document.addEventListener('keydown', onKey)
      await nextTick()
      ;(dlg.input ? inp.value : dlg.cancel ? no.value : yes.value)?.focus()
    })
    onUnmounted(() => document.removeEventListener('keydown', onKey))
    return { dlg, inp, yes, no, okClass, submit, cancel, onMask: () => dlg.cancel && cancel() }
  },
  template: `
<div id="dlg" :class="{ show: dlg.show }" @click.self="onMask">
  <div class="box" :class="{ danger: dlg.kind === 'danger' }">
    <h4>{{ dlg.title }}</h4>
    <p v-show="dlg.msg">{{ dlg.msg }}<HelpTip v-if="dlg.hint" :text="dlg.hint" /></p>
    <input v-if="dlg.input" ref="inp" v-model="dlg.value" :type="dlg.input.type || 'text'" :placeholder="dlg.input.placeholder || ''" style="width:100%;margin:0 0 12px">
    <label v-if="dlg.check" style="display:flex;margin:0 0 16px"><input type="checkbox" v-model="dlg.checked"><span>{{ dlg.check.label }}</span></label>
    <div class="btns">
      <button v-if="dlg.cancel" ref="no" @click="cancel">{{ $t('cancel') }}</button>
      <button ref="yes" :class="okClass" @click="submit">{{ dlg.okText }}</button>
    </div>
  </div>
</div>`,
}
