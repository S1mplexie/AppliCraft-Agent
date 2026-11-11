<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import type { FeedbackItem } from '../types'

const props = defineProps<{ isAdmin: boolean }>()

/** 悬浮球：固定于视口两侧，可拖拽、松手吸附最近边缘；点击（位移 < 6px）打开反馈弹窗。
 *  停靠边与纵向位置记入 localStorage，刷新后保持用户上次摆放。 */
const BALL = 48
const EDGE = 8
const DRAG_THRESHOLD = 6
const POS_KEY = 'applicraft.feedback_bubble'

const ballSide = ref<'left' | 'right'>('right')
const ballY = ref(Math.round(window.innerHeight * 0.55))
const dragging = ref(false)
const dragMoved = ref(false)
const dragX = ref(0)
const bubbleOpen = ref(false)

function clampY(y: number): number {
  const min = BALL / 2 + EDGE
  const max = window.innerHeight - BALL / 2 - EDGE
  return Math.max(min, Math.min(max, y))
}

function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(POS_KEY) || 'null') as
      | { side?: 'left' | 'right'; y?: number }
      | null
    if (saved && typeof saved.y === 'number' && (saved.side === 'left' || saved.side === 'right')) {
      ballSide.value = saved.side
      ballY.value = clampY(saved.y)
    }
  } catch { /* 损坏数据忽略，用默认位置 */ }
}

function persist() {
  localStorage.setItem(POS_KEY, JSON.stringify({ side: ballSide.value, y: Math.round(ballY.value) }))
}

let startX = 0
let startY = 0
let startBallX = 0
let startBallY = 0

function ballCenterX(): number {
  return ballSide.value === 'left' ? EDGE + BALL / 2 : window.innerWidth - EDGE - BALL / 2
}

function onPointerDown(e: PointerEvent) {
  dragging.value = true
  dragMoved.value = false
  startX = e.clientX
  startY = e.clientY
  startBallX = ballCenterX()
  startBallY = ballY.value
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  const dx = e.clientX - startX
  const dy = e.clientY - startY
  if (!dragMoved.value && Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD) dragMoved.value = true
  if (!dragMoved.value) return
  dragX.value = Math.max(BALL / 2, Math.min(window.innerWidth - BALL / 2, startBallX + dx))
  ballY.value = clampY(startBallY + dy)
}

function onPointerUp() {
  if (!dragging.value) return
  dragging.value = false
  if (dragMoved.value) {
    // 吸附到最近的左右边缘并记忆位置；位移不足视为点击，交给 click 分支。
    ballSide.value = dragX.value < window.innerWidth / 2 ? 'left' : 'right'
    dragX.value = 0
    persist()
  } else {
    openBubble()
  }
}

const ballStyle = computed(() => {
  const style: Record<string, string> = { top: `${Math.round(ballY.value - BALL / 2)}px` }
  if (dragging.value && dragMoved.value) {
    style.left = `${Math.round(dragX.value - BALL / 2)}px`
    style.right = 'auto'
  }
  return style
})

function onResize() {
  ballY.value = clampY(ballY.value)
}
onMounted(() => {
  restore()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

// ---- 反馈弹窗：普通用户提交表单；管理员查看全部反馈 ----
const feedbackContent = ref('')
const feedbackBusy = ref(false)
const feedbackMsg = ref('')
const feedbackItems = ref<FeedbackItem[]>([])
const feedbackLoading = ref(false)

function openBubble() {
  bubbleOpen.value = true
  feedbackMsg.value = ''
  if (props.isAdmin) void loadFeedback()
}

async function submitFeedback() {
  const content = feedbackContent.value.trim()
  if (!content || feedbackBusy.value) return
  feedbackBusy.value = true
  feedbackMsg.value = ''
  try {
    await api.submitFeedback(content)
    feedbackContent.value = ''
    feedbackMsg.value = '已提交，感谢你的反馈！'
  } catch (error) {
    feedbackMsg.value = (error as Error).message
  } finally {
    feedbackBusy.value = false
  }
}

async function loadFeedback() {
  if (feedbackLoading.value) return
  feedbackLoading.value = true
  try {
    feedbackItems.value = (await api.listFeedback()).items
  } catch {
    feedbackItems.value = []
  } finally {
    feedbackLoading.value = false
  }
}

function fmtDate(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN')
}
</script>

<template>
  <button
    class="feedback-bubble" :class="[ballSide, { dragging, moved: dragMoved }]" :style="ballStyle"
    title="意见反馈" aria-label="意见反馈"
    @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp" @pointercancel="onPointerUp"
  >
    <span class="fb-text">反馈</span>
  </button>

  <div v-if="bubbleOpen" class="modal-mask" @click.self="bubbleOpen = false">
    <div class="modal feedback-modal">
      <div class="card-head">
        <h2>意见反馈</h2>
        <span class="hint">{{ props.isAdmin ? `共 ${feedbackItems.length} 条 · 最新在前` : '功能建议、问题报告' }}</span>
        <button class="link" style="margin-left: auto;" @click="bubbleOpen = false">关闭</button>
      </div>
      <template v-if="!props.isAdmin">
        <textarea
          v-model="feedbackContent" rows="5" maxlength="2000"
          placeholder="告诉我们哪里好用、哪里不顺手，或你希望增加的功能（≤2000 字）"
        ></textarea>
        <div class="llm-actions">
          <button class="btn primary" :disabled="feedbackBusy || !feedbackContent.trim()" @click="submitFeedback">
            {{ feedbackBusy ? '提交中…' : '提交反馈' }}
          </button>
          <span v-if="feedbackMsg" class="llm-msg">{{ feedbackMsg }}</span>
        </div>
        <p class="hint" style="margin: 12px 0 0;">反馈直接送达管理员，不会展示给其他用户；请勿填写密码等敏感信息。</p>
      </template>
      <template v-else>
        <div v-if="feedbackItems.length" class="feedback-list">
          <div v-for="item in feedbackItems" :key="item.id" class="feedback-item">
            <div class="feedback-meta">
              <b>{{ item.user_name || item.user_email }}</b>
              <small>{{ item.user_email }}</small>
              <span class="hint">{{ fmtDate(item.created_at) }}</span>
            </div>
            <p class="feedback-content">{{ item.content }}</p>
          </div>
        </div>
        <p v-else class="hint" style="margin: 0;">还没有收到用户反馈。</p>
      </template>
    </div>
  </div>
</template>