import { computed, ref, watch } from 'vue'
import { api, copyFrom, del, guard, patch, post, put } from '../api.js'
import { ask } from '../dialog.js'
import { t } from '../i18n.js'
import { toast } from '../toast.js'
import { accLabel, fmt } from '../utils.js'

export default {
  setup(_, { expose }) {
    const plats = ref([]), accs = ref([])
    const nPlat = ref(''), nName = ref('')                 // 新增账号
    const cAcc = ref(''), cName = ref(''), cText = ref('') // 提交凭证
    const cFile = ref(null)

    // 选中账号所属平台声明的凭证项；未声明时默认 auth
    const credNames = computed(() => {
      const a = accs.value.find(x => x.id == cAcc.value)
      const p = plats.value.find(x => x.key === a?.platform)
      return (p && p.manifest.credentials) || [{ name: 'auth' }]
    })
    watch(credNames, list => { cName.value = list[0].name }, { immediate: true })

    const load = guard(async () => {
      plats.value = await api('/api/platforms')
      accs.value = await api('/api/accounts')
      if (!plats.value.some(p => p.key === nPlat.value)) nPlat.value = plats.value[0]?.key || ''
      if (!accs.value.some(a => a.id == cAcc.value)) cAcc.value = accs.value[0]?.id ?? ''
    })
    const addAcc = guard(async () => {
      await post('/api/accounts', { platform: nPlat.value, name: nName.value })
      nName.value = ''
      load()
    })
    const toggleAcc = guard((id, enabled) => patch('/api/accounts/' + id, { enabled }))
    const delAcc = guard(async id => {
      const a = accs.value.find(x => x.id === id)
      if (!await ask(t('delAccTitle'), t('delAccMsg', { name: a ? accLabel(a) : t('thisAcc') }), t('confirmDelete'), 'danger')) return
      await del('/api/accounts/' + id)
      load()
    })
    const runAcc = guard(async id => {
      await post('/api/runs', { account_id: id })
      toast(t('runTriggered'))
      setTimeout(load, 3000)
    })
    const copyCred = guard((id, name) => copyFrom(`/api/accounts/${id}/credentials/${encodeURIComponent(name)}/value`, t('copied', { n: name })))
    const putCred = guard(async () => {
      const url = `/api/accounts/${cAcc.value}/credentials/${cName.value}`
      const f = cFile.value.files[0]
      let r
      if (f) {
        const fd = new FormData()
        fd.append('file', f)
        r = await api(url, { method: 'PUT', body: fd })
      } else {
        const v = cText.value.trim()
        if (!v) return toast(t('pickOrPaste'))
        r = await put(url, { value: v })
      }
      toast(t('savedStatus', { s: r.status }))
      cText.value = ''
      cFile.value.value = ''
      load()
    })
    const credTitle = c => t('credTip', { u: fmt(c.updated_at) }) + (c.expires_at ? t('credTipExp', { e: fmt(c.expires_at) }) : '')

    expose({ load })
    return { plats, accs, nPlat, nName, cAcc, cName, cText, cFile, credNames, accLabel, credTitle, addAcc, toggleAcc, delAcc, runAcc, copyCred, putCred }
  },
  template: `
<div class="panel w">
  <div class="flex" style="margin-bottom:12px">
    <b>{{ $t('addAccount') }}</b>
    <select v-model="nPlat"><option v-for="p in plats" :key="p.key" :value="p.key">{{ p.name }}</option></select>
    <input v-model="nName" :placeholder="$t('accNamePh')"><button class="sm" @click="addAcc">{{ $t('add') }}</button>
  </div>
  <table>
    <tr><th>{{ $t('colAccount') }}</th><th>{{ $t('colEnabled') }}</th><th>{{ $t('colCred') }}</th><th></th></tr>
    <tr v-for="a in accs" :key="a.id">
      <td><b>{{ a.platform_name }}</b><template v-if="accLabel(a) !== a.platform_name"> / {{ a.name }}</template></td>
      <td><input type="checkbox" :checked="a.enabled" @change="toggleAcc(a.id, $event.target.checked)"></td>
      <td>
        <template v-for="c in a.credentials" :key="c.name"><span class="pill" :class="c.status === 'expired' ? 'r' : 'g'" style="cursor:pointer" :title="credTitle(c)" @click="copyCred(a.id, c.name)">{{ c.name }}{{ c.status === 'expired' ? $t('expiredSuffix') : '' }}</span> </template>
        <span v-if="!a.credentials.length" style="color:var(--mut)">{{ $t('notSubmitted') }}</span>
      </td>
      <td><div class="ops"><button class="sm" :disabled="!a.enabled || !a.credentials.length" @click="runAcc(a.id)">{{ $t('runAcc') }}</button><button class="sm danger" @click="delAcc(a.id)">{{ $t('delete') }}</button></div></td>
    </tr>
  </table>
  <h3>{{ $t('submitCred') }}</h3>
  <div class="flex">
    <select v-model="cAcc"><option v-for="a in accs" :key="a.id" :value="a.id">{{ accLabel(a) }}</option></select>
    <select v-model="cName"><option v-for="c in credNames" :key="c.name" :value="c.name">{{ c.label || c.name }} ({{ c.name }})</option></select>
    <input type="file" ref="cFile"><button class="sm pri" @click="putCred">{{ $t('upload') }}</button>
  </div>
  <textarea v-model="cText" rows="5" style="width:100%;margin-top:10px" :placeholder="$t('pastePh')"></textarea>
  <p style="color:var(--mut)">{{ $t('cliTip1') }}<code>sign-cli push</code>{{ $t('cliTip2') }}</p>
</div>`,
}
