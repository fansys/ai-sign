import { reactive, ref } from 'vue'
import { api, guard, post, put } from '../api.js'
import { t } from '../i18n.js'
import { toast } from '../toast.js'

export default {
  setup(_, { expose }) {
    const f = reactive({ server: '', key: '', on_success: true, on_failure: true, on_auth: true })
    const masked = ref('')   // 已保存 key 的脱敏形式，空表示未配置

    const load = guard(async () => {
      const b = await api('/api/settings/bark')
      Object.assign(f, { server: b.server, key: '', on_success: b.on_success, on_failure: b.on_failure, on_auth: b.on_auth })
      masked.value = b.configured ? b.key_masked : ''
    })
    const save = guard(async () => {
      await put('/api/settings/bark', { ...f })
      toast(t('saved'))
      load()
    })
    const test = guard(async () => {
      await post('/api/settings/bark/test')
      toast(t('testSent'))
    })
    expose({ load })
    return { f, masked, save, test }
  },
  template: `
<div class="panel w" style="margin-bottom:16px">
  <b>{{ $t('barkTitle') }}</b><span style="color:#6b5f4a;margin-left:10px;font-weight:400">{{ $t('barkHint') }}</span>
  <div class="flex" style="margin:12px 0">
    <span>{{ $t('server') }}</span><input v-model="f.server" placeholder="https://api.day.app" style="width:260px">
    <span>{{ $t('deviceKey') }}</span><input v-model="f.key" type="password" :placeholder="masked ? $t('keySavedPh', { m: masked }) : $t('keyPh')" style="width:220px" autocomplete="off">
  </div>
  <div class="flex">
    <label><input type="checkbox" v-model="f.on_success">{{ $t('evSuccess') }}</label>
    <label><input type="checkbox" v-model="f.on_failure">{{ $t('evFail') }}</label>
    <label><input type="checkbox" v-model="f.on_auth">{{ $t('evAuth') }}</label>
    <button class="sm" @click="save">{{ $t('save') }}</button><button class="sm" @click="test">{{ $t('sendTest') }}</button>
  </div>
</div>`,
}
