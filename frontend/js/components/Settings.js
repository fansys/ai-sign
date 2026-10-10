import { ref } from 'vue'
import BarkSettings from './BarkSettings.js'
import TokenSettings from './TokenSettings.js'

export default {
  components: { BarkSettings, TokenSettings },
  setup(_, { expose }) {
    const bark = ref(null), tokens = ref(null)
    expose({ load: () => { bark.value?.load(); tokens.value?.load() } })
    return { bark, tokens }
  },
  template: `<div><BarkSettings ref="bark" /><TokenSettings ref="tokens" /></div>`,
}
