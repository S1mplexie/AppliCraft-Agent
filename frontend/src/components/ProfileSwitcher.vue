<script setup lang="ts">
/** 顶栏唯一的档案管理入口：切换、新建、改名、删除都在这里完成。 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ProfileSummary } from '../types'

const props = defineProps<{
  profiles: ProfileSummary[]
  currentId: string
  busy: boolean
  open: boolean
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  select: [id: string]
  create: [payload: { label: string; withDemo: boolean }]
  rename: [payload: { id: string; label: string }]
  remove: [id: string]
}>()

const root = ref<HTMLElement | null>(null)
const newLabel = ref('')
const renameId = ref('')
const renameValue = ref('')
const removeId = ref('')

const current = computed(() => props.profiles.find(item => item.id === props.currentId))

function setOpen(value: boolean) { emit('update:open', value) }
function toggle() { setOpen(!props.open) }
function close() {
  renameId.value = ''
  removeId.value = ''
  setOpen(false)
}
watch(() => props.open, (value) => { if (!value) { renameId.value = ''; removeId.value = '' } })

// 点击浮层以外区域收起，避免面板一直挂着遮挡内容。
function onOutside(event: PointerEvent) {
  if (props.open && root.value && !root.value.contains(event.target as Node)) close()
}
onMounted(() => document.addEventListener('pointerdown', onOutside))
onUnmounted(() => document.removeEventListener('pointerdown', onOutside))

function choose(id: string) {
  if (props.busy || id === props.currentId) { close(); return }
  emit('select', id)
  close()
}

function startRename(item: ProfileSummary) {
  removeId.value = ''
  renameId.value = item.id
  renameValue.value = item.label || ''
}
function submitRename() {
  const label = renameValue.value.trim()
  if (!renameId.value || !label) { renameId.value = ''; return }
  emit('rename', { id: renameId.value, label })
  renameId.value = ''
}
function askRemove(id: string) {
  renameId.value = ''
  removeId.value = id
}
function confirmRemove() {
  if (!removeId.value) return
  emit('remove', removeId.value)
  removeId.value = ''
}
function create(withDemo: boolean) {
  if (props.busy) return
  emit('create', { label: newLabel.value.trim(), withDemo })
  newLabel.value = ''
  close()
}

function fmtDate(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value.slice(0, 10) : d.toLocaleDateString('zh-CN', {
    month: '2-digit', day: '2-digit',
  })
}
</script>

<template>
  <div ref="root" class="switcher">
    <button
      class="switcher-trigger" :class="{ open, 'is-busy': busy }"
      :title="busy ? '生成进行中，暂不能切换档案' : '切换或管理档案'"
      @click="toggle"
    >
      <span class="switcher-icon">▤</span>
      <span class="switcher-text">
        <small>当前档案</small>
        <strong>{{ current?.label || (profiles.length ? '选择档案' : '暂无档案') }}</strong>
      </span>
      <span class="switcher-caret">⌄</span>
    </button>

    <div v-if="open" class="switcher-panel">
      <div class="switcher-head">
        <strong>切换档案</strong>
        <span class="hint">共 {{ profiles.length }} 份 · 数据相互隔离</span>
      </div>

      <div class="switcher-list">
        <div
          v-for="item in profiles" :key="item.id"
          class="switcher-row" :class="{ active: item.id === currentId }"
        >
          <button class="switcher-main" :disabled="busy" @click="choose(item.id)">
            <span class="switcher-row-top">
              <b>{{ item.label || '未命名档案' }}</b>
              <span v-if="item.id === currentId" class="badge ok">使用中</span>
            </span>
            <small>{{ item.name || '未填写姓名' }} · 更新于 {{ fmtDate(item.updated_at) }}</small>
          </button>
          <div class="switcher-row-actions">
            <button class="mini-link" :disabled="busy" @click="startRename(item)">改名</button>
            <button class="mini-link danger" :disabled="busy" @click="askRemove(item.id)">删除</button>
          </div>

          <div v-if="renameId === item.id" class="switcher-inline" @click.stop>
            <input
              v-model="renameValue" class="inline-input" maxlength="40"
              placeholder="输入新的档案名称" @keyup.enter="submitRename" @keyup.esc="renameId = ''"
            />
            <button class="btn small primary" @click="submitRename">保存</button>
            <button class="btn small" @click="renameId = ''">取消</button>
          </div>
          <div v-if="removeId === item.id" class="switcher-inline danger-inline" @click.stop>
            <span>确认删除「{{ item.label }}」？已生成文书会保留，但不再关联档案。</span>
            <div class="inline-actions">
              <button class="btn small danger-solid" @click="confirmRemove">确认删除</button>
              <button class="btn small" @click="removeId = ''">取消</button>
            </div>
          </div>
        </div>
        <div v-if="!profiles.length" class="switcher-empty">还没有档案，在下方新建一份。</div>
      </div>

      <div class="switcher-create">
        <label class="switcher-create-label">新建档案</label>
        <input
          v-model="newLabel" class="switcher-input" maxlength="40"
          placeholder="档案名称（可留空，自动生成）" :disabled="busy" @keyup.enter="create(false)"
        />
        <div class="switcher-create-actions">
          <button class="btn small primary" :disabled="busy" @click="create(false)">＋ 空白档案</button>
          <button class="btn small" :disabled="busy" @click="create(true)">载入示例</button>
        </div>
      </div>
      <p class="switcher-foot">切换后，档案表单、文书库与生成参数会一起切换到该档案。</p>
    </div>
  </div>
</template>
