import { reactive } from 'vue'

/** 全局确认弹窗配置。message 必填，其余可选。 */
export interface ConfirmOptions {
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  /** 确认按钮是否用危险色（删除/注销等破坏性操作默认 true）。 */
  danger?: boolean
}

interface ConfirmState {
  open: boolean
  title: string
  message: string
  confirmText: string
  cancelText: string
  danger: boolean
  resolve: ((value: boolean) => void) | null
}

const state = reactive<ConfirmState>({
  open: false,
  title: '',
  message: '',
  confirmText: '确认删除',
  cancelText: '取消',
  danger: true,
  resolve: null,
})

export const confirmState = state

/**
 * 打开自定义确认弹窗，替代浏览器原生 confirm()。
 * 若上一次弹窗仍未结算（极端情况），先按「取消」结算，避免 Promise 悬挂。
 */
export function confirm(options: ConfirmOptions | string): Promise<boolean> {
  if (state.resolve) {
    const pending = state.resolve
    state.resolve = null
    pending(false)
  }
  const opt = typeof options === 'string' ? { message: options } : options
  state.title = opt.title ?? '请确认'
  state.message = opt.message
  state.confirmText = opt.confirmText ?? '确认删除'
  state.cancelText = opt.cancelText ?? '取消'
  state.danger = opt.danger ?? true
  state.open = true
  return new Promise<boolean>((resolve) => { state.resolve = resolve })
}

/** 轻量提示弹窗（只有一个「知道了」按钮），替代浏览器原生 alert()。 */
export function showAlert(message: string, title = '提示'): Promise<void> {
  return confirm({ title, message, confirmText: '知道了', cancelText: '', danger: false }).then(() => undefined)
}

/** 由弹窗组件调用：结算并关闭。 */
export function resolveConfirm(value: boolean) {
  state.open = false
  const done = state.resolve
  state.resolve = null
  if (done) done(value)
}
