import { reactive } from 'vue'

// 跨组件共享：面板加载的服务状态（顶栏副标题用）
export const store = reactive({ status: null })
