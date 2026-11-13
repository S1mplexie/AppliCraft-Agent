<script setup lang="ts">
/** 从系统项目库（知识库收录的港新官方项目）批量导入到「申请人档案 → 目标项目」。
 *  档案页与参考文档库共用同一个选择器，勾选结果交给 App.vue 统一回填，避免两套映射逻辑。 */
import { computed, onMounted, ref } from 'vue'
import type { SystemProgram } from '../types'

const props = defineProps<{
  programs: SystemProgram[]
  existingIds: string[]
  preselected?: string[]
  profileLabel?: string
}>()
const emit = defineEmits<{ close: []; import: [ids: string[]] }>()

const keyword = ref('')
const region = ref<'all' | 'HK' | 'SG'>('all')
const checked = ref<string[]>([])

const filters = [
  { key: 'all', label: '全部' },
  { key: 'HK', label: '中国香港' },
  { key: 'SG', label: '新加坡' },
] as const

const existing = computed(() => new Set(props.existingIds))
const counts = computed(() => ({
  all: props.programs.length,
  HK: props.programs.filter(p => p.region === 'HK').length,
  SG: props.programs.filter(p => p.region === 'SG').length,
}))
const matched = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.programs.filter(p => {
    if (region.value !== 'all' && p.region !== region.value) return false
    if (!kw) return true
    return `${p.school_name_zh}${p.school_id}${p.program_name_zh}${p.program_name_en}${p.faculty}`
      .toLowerCase().includes(kw)
  })
})
const groups = computed(() => {
  const map = new Map<string, SystemProgram[]>()
  for (const p of matched.value) {
    const key = p.school_name_zh || p.school_id || '其他院校'
    const list = map.get(key) || []
    list.push(p)
    map.set(key, list)
  }
  return [...map.entries()]
})
const selectable = computed(() => matched.value.filter(p => !existing.value.has(p.program_id)))
const allSelected = computed(() => selectable.value.length > 0
  && selectable.value.every(p => checked.value.includes(p.program_id)))
const checkedPrograms = computed(() => checked.value
  .map(id => props.programs.find(p => p.program_id === id))
  .filter((p): p is SystemProgram => !!p))

// 每次打开都是干净状态；从参考文档库单个项目点进来时预选那一项。
onMounted(() => {
  checked.value = (props.preselected || []).filter(id =>
    props.programs.some(p => p.program_id === id) && !props.existingIds.includes(id))
})

function cleanName(name: string) {
  return (name || '').replace(/[（(]非官方译名[）)]/g, '').trim()
}
function shortFaculty(s: string) {
  return s && s.length > 28 ? `${s.slice(0, 28)}…` : (s || '')
}
function shortIntake(s: string) {
  if (!s) return '入学季待核实'
  const first = s.split(/[（(；;，,]/)[0].trim()
  return first.length > 18 ? `${first.slice(0, 18)}…` : first
}
function regionLabel(r: string) {
  return r === 'HK' ? '中国香港' : r === 'SG' ? '新加坡' : (r || '其他')
}
function isChecked(id: string) { return checked.value.includes(id) }
function isImported(id: string) { return existing.value.has(id) }
function toggle(p: SystemProgram) {
  if (isImported(p.program_id)) return
  checked.value = isChecked(p.program_id)
    ? checked.value.filter(id => id !== p.program_id)
    : [...checked.value, p.program_id]
}
function toggleAll() {
  const ids = selectable.value.map(p => p.program_id)
  checked.value = allSelected.value
    ? checked.value.filter(id => !ids.includes(id))
    : [...new Set([...checked.value, ...ids])]
}
function remove(id: string) {
  checked.value = checked.value.filter(x => x !== id)
}
function submit() {
  if (checked.value.length) emit('import', [...checked.value])
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal imp-modal" role="dialog" aria-modal="true" aria-label="从系统项目库导入目标项目">
      <div class="imp-head">
        <div>
          <span class="imp-eyebrow">系统项目库 · 官方资料</span>
          <h2>导入目标项目</h2>
          <p>勾选后写入档案「{{ profileLabel || '当前档案' }}」的目标项目，学校、项目名、学院、地区与入学季自动带入，仍可继续编辑。</p>
        </div>
        <button class="imp-close" aria-label="关闭" @click="emit('close')">×</button>
      </div>

      <div class="imp-toolbar">
        <div class="imp-search">
          <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="M12.6 12.6 17 17" /></svg>
          <input v-model="keyword" placeholder="搜索学校 / 专业中英文名…" aria-label="搜索系统项目" />
          <button v-if="keyword" class="imp-search-clear" aria-label="清空搜索" @click="keyword = ''">×</button>
        </div>
        <div class="imp-filters">
          <button
            v-for="f in filters" :key="f.key"
            class="imp-filter" :class="{ on: region === f.key }"
            @click="region = f.key"
          >{{ f.label }} <em>{{ counts[f.key] }}</em></button>
        </div>
      </div>

      <div class="imp-status">
        <span>共 {{ matched.length }} 个项目 · {{ groups.length }} 所学校<span v-if="existing.size"> · 已导入 {{ existing.size }} 个</span></span>
        <span class="imp-status-actions">
          <button class="link" :disabled="!selectable.length" @click="toggleAll">
            {{ allSelected ? '取消全选' : '全选当前结果' }}
          </button>
          <button class="link" :disabled="!checked.length" @click="checked = []">清空</button>
        </span>
      </div>

      <div class="imp-body">
        <div v-if="!groups.length" class="imp-empty">
          <span class="imp-empty-mark">⌕</span>
          <strong>没有匹配的项目</strong>
          <span class="hint">换个关键词，或切换地区筛选试试。</span>
        </div>
        <div v-for="[school, items] in groups" :key="school" class="imp-school">
          <div class="imp-school-head">
            <h3>{{ school }}</h3>
            <span class="imp-school-count">{{ items.length }} 个项目</span>
            <span class="imp-school-line"></span>
          </div>
          <div class="imp-grid">
            <label
              v-for="p in items" :key="p.program_id" class="imp-card"
              :class="{ on: isChecked(p.program_id), done: isImported(p.program_id) }"
            >
              <input
                class="imp-native" type="checkbox" :checked="isChecked(p.program_id)"
                :disabled="isImported(p.program_id)" @change="toggle(p)"
              />
              <span class="imp-check" aria-hidden="true"></span>
              <span class="imp-card-zh">{{ cleanName(p.program_name_zh) || p.program_name_en }}</span>
              <span class="imp-card-en">{{ p.program_name_en }}</span>
              <span class="imp-card-meta">
                <span v-if="p.faculty">{{ shortFaculty(p.faculty) }}</span>
                <span>{{ shortIntake(p.intake) }}</span>
              </span>
              <span class="imp-card-foot">
                <span class="imp-region" :class="p.region === 'HK' ? 'hk' : 'sg'">{{ regionLabel(p.region) }}</span>
                <span class="imp-fields">{{ p.fields?.length ? `${p.fields.length} 个资料板块` : '官方资料' }}</span>
                <span v-if="isImported(p.program_id)" class="imp-done-tag">已在目标项目</span>
              </span>
            </label>
          </div>
        </div>
      </div>

      <div class="imp-foot">
        <div class="imp-foot-left">
          <span class="imp-foot-label">已选 {{ checked.length }} 个项目</span>
          <div class="imp-chips">
            <span v-for="p in checkedPrograms.slice(0, 4)" :key="p.program_id" class="imp-chip">
              <span class="imp-chip-text">{{ cleanName(p.program_name_zh) || p.program_name_en }}</span>
              <button type="button" aria-label="移除" @click="remove(p.program_id)">×</button>
            </span>
            <span v-if="checkedPrograms.length > 4" class="imp-chip more">+{{ checkedPrograms.length - 4 }}</span>
          </div>
        </div>
        <div class="imp-foot-actions">
          <button class="btn small" @click="emit('close')">取消</button>
          <button class="btn small primary" :disabled="!checked.length" @click="submit">导入选中项目</button>
        </div>
      </div>
    </div>
  </div>
</template>
