import { computed, ref } from 'vue'
import { api, guard } from '../api.js'
import { locale, t } from '../i18n.js'
import { store } from '../store.js'
import { eventLines, pad, runLabel, stCls, stLabel, trLabel } from '../utils.js'

export default {
  setup(_, { expose }) {
    const cur = ref(new Date())   // 日历当前月份
    const sel = ref(null)         // 选中的日期 yyyy-MM-dd
    const cal = ref({ days: [], recorded_days: 0 })
    const day = ref(null)

    const monthKey = computed(() => `${cur.value.getFullYear()}-${pad(cur.value.getMonth() + 1)}`)
    const title = computed(() => {
      const [y, m] = [cur.value.getFullYear(), cur.value.getMonth()]
      return t('monthTitle', { y, m: m + 1, mon: new Date(y, m, 1).toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en', { month: 'long' }) })
    })
    const offset = computed(() => (new Date(cur.value.getFullYear(), cur.value.getMonth(), 1).getDay() + 6) % 7)
    const nextDisabled = computed(() => !!store.status && monthKey.value >= store.status.today.slice(0, 7))
    const cells = computed(() => {
      const [y, m] = [cur.value.getFullYear(), cur.value.getMonth()]
      const rec = Object.fromEntries(cal.value.days.map(d => [d.date, d]))
      const today = store.status?.today || ''
      return Array.from({ length: new Date(y, m + 1, 0).getDate() }, (_, i) => {
        const k = `${y}-${pad(m + 1)}-${pad(i + 1)}`
        return { k, d: i + 1, r: rec[k], future: k > today, today: k === today }
      })
    })

    const loadDay = guard(async () => { day.value = await api('/api/days/' + sel.value) })
    const load = guard(async () => {
      store.status = await api('/api/status')
      sel.value = sel.value || store.status.today
      cal.value = await api('/api/calendar?month=' + monthKey.value)
      await loadDay()
    })
    const pick = k => { sel.value = k; load() }
    const moveMonth = n => { cur.value = new Date(cur.value.getFullYear(), cur.value.getMonth() + n, 1); load() }
    const goToday = () => { cur.value = new Date(); sel.value = null; load() }
    const toggleLogs = guard(async a => {
      a._open = !a._open
      if (a._logs !== undefined) return
      a._logs = ''
      a._logs = eventLines((await api('/api/runs/' + a.id)).events) || t('noLogs')
    })

    expose({ load })
    return { cal, day, sel, title, offset, cells, nextDisabled, pick, moveMonth, goToday, toggleLogs, runLabel, stCls, stLabel, trLabel }
  },
  template: `
<div class="grid">
  <div class="panel y">
    <div class="ph"><span>{{ $t('calTitle') }}</span><span>{{ $t('calHint') }}</span></div>
    <div class="mh"><h2>{{ title }}</h2>
      <div class="flex"><button class="sm" @click="moveMonth(-1)">{{ $t('prevMonth') }}</button><button class="sm" @click="goToday">{{ $t('today') }}</button><button class="sm" :disabled="nextDisabled" @click="moveMonth(1)">{{ $t('nextMonth') }}</button></div></div>
    <div class="cal">
      <div class="dow" v-for="w in $t('weekdays').split(',')" :key="w">{{ w }}</div>
      <div v-for="i in offset" :key="'o' + i"></div>
      <div v-for="c in cells" :key="c.k" class="day" :class="[c.r ? c.r.status : '', { future: c.future, sel: c.k === sel, today: c.today }]" @click="!c.future && pick(c.k)">
        <span class="n">{{ c.d }}</span>
        <span v-if="c.r" class="dots"><i v-for="n in Math.min(c.r.count, 3)" :key="n"></i></span>
      </div>
    </div>
    <div class="legend"><span><i style="background:var(--grn2)"></i>{{ $t('legendOk') }}</span><span><i style="background:var(--org)"></i>{{ $t('legendPartial') }}</span><span><i style="background:var(--red)"></i>{{ $t('legendFail') }}</span><span><i style="background:#fff"></i>{{ $t('legendNone') }}</span><span class="sp"></span><span>{{ $t('recorded', { n: cal.recorded_days }) }}</span></div>
  </div>
  <div class="panel w">
    <div class="ph"><span>{{ day ? $t('detailOf', { d: sel }) : $t('detail') }}</span><span>{{ $t('byTimeDesc') }}</span></div>
    <div v-if="day"><span class="big">{{ sel }}</span><span class="pill">{{ $t('successN', { n: day.success }) }}</span> <span class="pill">{{ $t('actionsN', { n: day.actions_count }) }}</span></div>
    <h3>{{ $t('dayResults') }}</h3>
    <div>
      <div v-for="r in day ? day.results : []" :key="r.platform + r.account" class="row">
        <b>{{ runLabel(r) }}</b><span class="pill" :class="stCls(r.status)">{{ stLabel(r.status) }}</span>
        <span v-if="r.points != null" class="pts">{{ $t('pointsN', { n: r.points }) }}</span><span class="pill">{{ $t('attemptsN', { n: r.attempts }) }}</span><span class="pill">{{ r.time }}</span>
      </div>
      <div v-if="day && !day.results.length" style="color:var(--mut)">{{ $t('noRecord') }}</div>
    </div>
    <h3>{{ $t('actionFlow') }}</h3>
    <div class="scroll">
      <div v-for="a in day ? day.actions : []" :key="a.id" class="act" :class="{ open: a._open }" @click="toggleLogs(a)">
        <div class="t"><span><span class="dot" :class="a.status"></span>{{ runLabel(a) }}</span><small>{{ a.finished_at || a.started_at }}</small></div>
        <div class="m">{{ a.message || stLabel(a.status) }}</div>
        <span class="pill y">{{ trLabel(a.trigger) }}</span> <span class="pill" :class="stCls(a.status)">{{ stLabel(a.status) }}</span>
        <template v-if="a.repeat > 1"> <span class="pill">×{{ a.repeat }}</span></template>
        <template v-if="a.version"> <span class="pill">v{{ a.version }}</span></template>
        <div class="logs">{{ a._logs }}</div>
      </div>
    </div>
  </div>
</div>`,
}
