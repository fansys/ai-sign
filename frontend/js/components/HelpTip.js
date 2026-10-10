import { onMounted, onUnmounted, ref } from 'vue'

// 问号图标：点击切换气泡提示，点其他位置收起
export default {
  props: { text: String },
  setup() {
    const on = ref(false)
    const off = () => { on.value = false }
    onMounted(() => document.addEventListener('click', off))
    onUnmounted(() => document.removeEventListener('click', off))
    return { on }
  },
  template: `<span class="qm" :class="{ on }" tabindex="0" @click.stop="on = !on">?<span class="tip">{{ text }}</span></span>`,
}
