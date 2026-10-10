import { ref } from 'vue'
import { api, copyFrom, del, download, guard, post } from '../api.js'
import { ask } from '../dialog.js'
import { t } from '../i18n.js'
import { toast } from '../toast.js'
import { fmt } from '../utils.js'

export default {
  setup(_, { expose }) {
    const tokens = ref([])
    const name = ref('')

    const load = guard(async () => { tokens.value = await api('/api/tokens') })
    const create = guard(async () => {
      await post('/api/tokens', { name: name.value || 'cli' })
      toast(t('created'))
      load()
    })
    const copy = guard(id => copyFrom(`/api/tokens/${id}/value`, t('tokenCopied')))
    const remove = guard(async id => {
      if (!await ask(t('delTokTitle'), t('delTokMsg'), t('confirmDelete'), 'danger')) return
      await del('/api/tokens/' + id)
      load()
    })
    const regen = guard(async id => {
      if (!await ask(t('regenTitle'), t('regenMsg'), t('regen'), 'warn')) return
      await post(`/api/tokens/${id}/regenerate`)
      toast(t('regenerated'))
      load()
    })
    const dlCli = guard(() => download('/api/cli/download?server=' + encodeURIComponent(location.origin), 'sign-cli.zip'))

    expose({ load })
    return { tokens, name, origin: location.origin, fmt, create, copy, remove, regen, dlCli }
  },
  template: `
<div class="panel w">
  <div class="flex"><b>{{ $t('tokenTitle') }}</b><input v-model="name" :placeholder="$t('tokenNamePh')"><button class="sm" @click="create">{{ $t('create') }}</button></div>
  <p style="color:var(--acc);font-weight:700"></p>
  <table>
    <tr><th>{{ $t('colName') }}</th><th>{{ $t('colToken') }}</th><th>{{ $t('colScopes') }}</th><th>{{ $t('colLastUsed') }}</th><th></th></tr>
    <tr v-for="x in tokens" :key="x.id">
      <td>{{ x.name }}</td>
      <td><code>{{ x.masked }}</code> <button v-if="x.copyable" class="sm" @click="copy(x.id)">{{ $t('copy') }}</button></td>
      <td>{{ x.scopes.join(',') }}</td><td>{{ fmt(x.last_used_at) }}</td>
      <td><div class="ops"><button class="sm warn" @click="regen(x.id)">{{ $t('regen') }}</button><span class="gap"></span><button class="sm danger" @click="remove(x.id)">{{ $t('delete') }}</button></div></td>
    </tr>
  </table>
  <h3>{{ $t('cliTitle') }} <button class="sm" @click="dlCli">{{ $t('cliDownload') }}</button></h3>
  <pre class="out">{{ $t('cliHint', { url: origin }) }}</pre>
</div>`,
}
