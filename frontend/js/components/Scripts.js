import { computed, ref } from 'vue'
import { api, guard, post, put } from '../api.js'
import { modal } from '../dialog.js'
import { t } from '../i18n.js'
import { toast } from '../toast.js'
import { accLabel, eventLines, fmt, lineDiff } from '../utils.js'

export default {
  setup(_, { expose }) {
    const plats = ref([]), accs = ref([])
    const plat = ref(''), accId = ref('')
    const src = ref(''), isDraft = ref(false)
    const versions = ref([]), activeVid = ref(null)
    const out = ref('—')
    const diff = ref(null)   // {title, rows}

    const platAccs = computed(() => accs.value.filter(a => a.platform === plat.value))

    const loadScript = guard(async () => {
      const k = plat.value
      const [d, v] = await Promise.all([api(`/api/platforms/${k}/draft`), api(`/api/platforms/${k}/versions`)])
      src.value = d.source
      isDraft.value = d.is_draft
      versions.value = v.versions
      activeVid.value = v.active_version_id
      accId.value = platAccs.value[0]?.id ?? ''
    })
    const load = guard(async () => {
      plats.value = await api('/api/platforms')
      accs.value = await api('/api/accounts')
      if (!plats.value.some(p => p.key === plat.value)) plat.value = plats.value[0]?.key || ''
      await loadScript()
    })

    const saveDraft = guard(async () => {
      await put(`/api/platforms/${plat.value}/draft`, { source: src.value })
      toast(t('draftSaved'))
      loadScript()
    })
    const testRun = guard(async () => {
      if (!accId.value) return toast(t('platNoAcc'))
      out.value = t('running')
      const r = await post(`/api/platforms/${plat.value}/test`, { account_id: +accId.value, source: src.value })
      out.value = t('testOut', { status: r.status, points: r.points ?? '-', msg: r.message }) + eventLines(r.events)
    })
    const publish = guard(async () => {
      const r = await modal(t('publishTitle'), '', t('publish'), '', {
        required: true, input: { placeholder: t('notePh') }, check: { label: t('activateNow'), checked: true },
      })
      if (!r) return
      await post(`/api/platforms/${plat.value}/publish`, { source: src.value, note: r.value.trim(), activate: r.checked })
      toast(t('published'))
      loadScript()
    })
    const activate = guard(async id => {
      await post(`/api/platforms/${plat.value}/activate`, { version_id: id })
      toast(t('activated'))
      loadScript()
    })
    const loadVer = guard(async id => {
      const v = await api(`/api/platforms/${plat.value}/versions/${id}`)
      src.value = v.source
      toast(t('loadedVer', { v: v.version }))
    })
    const diffVer = guard(async id => {
      const v = await api(`/api/platforms/${plat.value}/versions/${id}`)
      diff.value = { title: t('diffTitle', { v: v.version }), rows: lineDiff(v.source, src.value) }
    })

    expose({ load })
    return { plats, plat, accId, platAccs, src, isDraft, versions, activeVid, out, diff, accLabel, fmt, loadScript, saveDraft, testRun, publish, activate, loadVer, diffVer }
  },
  template: `
<div class="panel w">
  <div class="flex" style="margin-bottom:12px">
    <b>{{ $t('platform') }}</b>
    <select v-model="plat" @change="loadScript"><option v-for="p in plats" :key="p.key" :value="p.key">{{ p.name }}</option></select>
    <span class="pill" :class="isDraft ? 'o' : 'g'">{{ isDraft ? $t('draft') : $t('activeVersion') }}</span><span class="sp"></span>
    <select v-model="accId">
      <option v-for="a in platAccs" :key="a.id" :value="a.id">{{ accLabel(a) }}</option>
      <option v-if="!platAccs.length" value="">{{ $t('noAcc') }}</option>
    </select>
    <button class="sm" @click="saveDraft">{{ $t('saveDraft') }}</button>
    <button class="sm" @click="testRun">{{ $t('testRun') }}</button>
    <button class="sm pri" @click="publish">{{ $t('publish') }}</button>
  </div>
  <textarea v-model="src" class="code" spellcheck="false"></textarea>
  <h3>{{ $t('testResult') }}</h3><pre class="out">{{ out }}</pre>
  <h3>{{ $t('versionHistory') }}</h3>
  <table>
    <tr><th>{{ $t('version') }}</th><th>{{ $t('note') }}</th><th>{{ $t('author') }}</th><th>{{ $t('time') }}</th><th></th></tr>
    <tr v-for="x in versions" :key="x.id">
      <td>v{{ x.version }} <span v-if="x.id === activeVid" class="pill g">{{ $t('inUse') }}</span></td>
      <td>{{ x.note }}</td><td>{{ x.author }}</td><td>{{ fmt(x.created_at) }}</td>
      <td><button class="sm" @click="loadVer(x.id)">{{ $t('load') }}</button> <button class="sm" @click="diffVer(x.id)">{{ $t('compare') }}</button> <button v-if="x.id !== activeVid" class="sm" @click="activate(x.id)">{{ $t('enable') }}</button></td>
    </tr>
  </table>
  <div v-if="diff" class="out diff" style="margin-top:12px">
    <b>{{ diff.title }}</b>
    <div v-for="(r, i) in diff.rows" :key="i" :class="r.cls">{{ r.text }}</div>
    <div v-if="!diff.rows.length">{{ $t('noDiff') }}</div>
  </div>
</div>`,
}
