import { createApp } from 'vue'
import { locale, setLocale, t } from './i18n.js'
import App from './components/App.js'

setLocale(locale.value)

const app = createApp(App)
app.config.globalProperties.$t = t
app.mount('#app')
