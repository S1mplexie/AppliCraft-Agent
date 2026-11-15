import { ref } from 'vue'

/**
 * 审核建议面板的跨 tab 展开请求。
 *
 * 面板默认折叠（打开文书时把版面留给正文），但「逐项给建议并重新生成」这类
 * 入口已经明确表达了展开意图。用计数器而不是布尔值：目标查看器在生成过程中
 * 尚未挂载时请求也不会丢失，挂载后由 immediate watch 消费一次并清零。
 */
export const regenPanelRequest = ref(0)

export function requestRegenPanel() {
  regenPanelRequest.value += 1
}
