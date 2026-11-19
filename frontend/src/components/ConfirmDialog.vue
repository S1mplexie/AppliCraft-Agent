<script setup lang="ts">
/**
 * 全局自定义确认弹窗：替代浏览器原生 confirm()/alert()。
 * 样式复用 main.css 里既有的 .confirm-* 系列；通过 utils/confirm.ts 的 Promise API 调用。
 */
import { nextTick, ref, watch } from 'vue'
import { confirmState, resolveConfirm } from '../utils/confirm'

const primaryBtn = ref<HTMLButtonElement | null>(null)

// 危险操作默认聚焦「取消」，避免误按回车把数据删掉；纯提示（无取消）才聚焦主按钮。
watch(() => confirmState.open, async (open) => {
  if (!open) return
  await nextTick()
  if (confirmState.cancelText) return
  primaryBtn.value?.focus()
})

function onKeydown(e: KeyboardEvent) {
  if (!confirmState.open) return
  if (e.key === 'Escape') {
    e.preventDefault()
    resolveConfirm(false)
  }
}
window.addEventListener('keydown', onKeydown)
</script>

<template>
  <div
    v-if="confirmState.open"
    class="confirm-overlay global-confirm-overlay"
    @click.self="resolveConfirm(false)"
  >
    <div
      class="confirm-modal"
      :class="{ 'confirm-modal--info': !confirmState.danger }"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="global-confirm-title"
      aria-describedby="global-confirm-desc"
    >
      <div class="confirm-icon" aria-hidden="true">{{ confirmState.danger ? '!' : 'i' }}</div>
      <h2 id="global-confirm-title">{{ confirmState.title }}</h2>
      <p id="global-confirm-desc">{{ confirmState.message }}</p>
      <div class="confirm-actions">
        <button v-if="confirmState.cancelText" class="btn" @click="resolveConfirm(false)">
          {{ confirmState.cancelText }}
        </button>
        <button
          ref="primaryBtn"
          class="btn"
          :class="confirmState.danger ? 'danger-solid' : 'primary'"
          @click="resolveConfirm(true)"
        >
          {{ confirmState.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>
