import { computed, nextTick, onMounted, ref } from 'vue'
import { post, guard } from '../api.js'
import { t, toggleLocale } from '../i18n.js'
import { store } from '../store.js'
import { toast, toastState } from '../toast.js'
import Accounts from './Accounts.js'
import Dashboard from './Dashboard.js'
import Modal from './Modal.js'
import Scripts from './Scripts.js'
import Settings from './Settings.js'

const TABS = ['dash', 'script', 'acc', 'set']

export default {
  components: { Accounts, Dashboard, Modal, Scripts, Settings },
  setup() {
    const tab = ref('dash')
    const views = { dash: ref(null), script: ref(null), acc: ref(null), set: ref(null) }

    const sub = computed(() => {
      const s = store.status
      if (!s) return t('loading')
      const [from, to] = s.retry_hours.split('-')
      return t('sub', { at: s.daily_at, from, to, today: s.today, now: s.now })
    })
    const reload = () => views[tab.value].value?.load()
    const go = async k => {
      tab.value = k
      history.replaceState(null, '', '#' + k)
      await nextTick()
      reload()
    }
    const runNow = guard(async () => {
      await post('/api/runs', {})
      toast(t('runTriggered'))
      setTimeout(() => views.dash.value?.load(), 3000)
      setTimeout(() => views.dash.value?.load(), 8000)
    })
    onMounted(() => go(TABS.some(k => '#' + k === location.hash) ? location.hash.slice(1) : 'dash'))

    return { TABS, tab, sub, go, toggleLocale, reload, runNow, toastState, ...Object.fromEntries(Object.entries(views).map(([k, r]) => ['v_' + k, r])) }
  },
  template: `
<header>
  <img class="logo" src="/static/favicon.svg" alt="">
  <div><h1>{{ $t('title') }}</h1><div class="sub">{{ sub }}</div></div>
  <div class="sp"></div>
  <button @click="toggleLocale">{{ $t('langSwitch') }}</button>
  <button @click="reload">{{ $t('refresh') }}</button>
  <button class="pri" @click="runNow">{{ $t('runNow') }}</button>
</header>
<nav><button v-for="k in TABS" :key="k" :class="{ on: tab === k }" @click="go(k)">{{ $t('tab.' + k) }}</button></nav>
<main>
  <Dashboard ref="v_dash" v-show="tab === 'dash'" />
  <Scripts ref="v_script" v-show="tab === 'script'" />
  <Accounts ref="v_acc" v-show="tab === 'acc'" />
  <Settings ref="v_set" v-show="tab === 'set'" />
</main>
<div id="toast" :style="{ display: toastState.show ? 'block' : 'none' }">{{ toastState.msg }}</div>
<Modal />`,
}
