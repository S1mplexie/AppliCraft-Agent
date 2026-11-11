<script setup lang="ts">
/** 申请看板：总览所有目标项目的截止倒计时、材料清单进度与文书状态，
 *  每个目标项目一张卡。PS/CV/推荐信由文书自动派生，成绩单/语言成绩/申请费为手动勾选。 */
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { ApplicationProject, DocumentMeta, SystemProgram } from '../types'

const props = defineProps<{
  profileId: string
  documents: DocumentMeta[]
  systemPrograms: SystemProgram[]
}>()
const emit = defineEmits<{
  (e: 'go', tab: 'generate' | 'documents' | 'projects'): void
  (e: 'refresh-docs'): void
}>()

const projects = ref<ApplicationProject[]>([])
const loading = ref(false)

async function loadProjects() {
  if (!props.profileId) { projects.value = []; return }
  loading.value = true
  try { projects.value = (await api.listProjects(props.profileId)).items }
  catch { projects.value = [] }
  finally { loading.value = false }
}
watch(() => props.profileId, () => void loadProjects(), { immediate: true })

// ----------------------------------------------------------- 文书分布
const profileDocs = computed(() => props.documents.filter(d => d.profile_id === props.profileId))
const docsByProject = computed(() => {
  const m = new Map<string, DocumentMeta[]>()
  for (const d of profileDocs.value) {
    if (!d.project_id) continue
    const list = m.get(d.project_id) || []
    list.push(d)
    m.set(d.project_id, list)
  }
  return m
})
function docCounts(id: string) {
  const counts = { cv: 0, ps: 0, recommendation: 0 } as Record<string, number>
  for (const d of docsByProject.value.get(id) || []) counts[d.doc_type] = (counts[d.doc_type] || 0) + 1
  return counts
}
function projectStatus(id: string) {
  const docs = docsByProject.value.get(id) || []
  const verified = docs.filter(d => d.passed_verification).length
  const issues = docs.filter(d => !d.passed_verification && d.issue_count > 0).length
  const pending = docs.length - verified - issues
  return { total: docs.length, verified, issues, pending }
}

// ----------------------------------------------------------- 材料清单
type ManualKey = 'transcript' | 'language' | 'fee'
const MANUAL_KEYS: { key: ManualKey; label: string }[] = [
  { key: 'transcript', label: '成绩单' },
  { key: 'language', label: '语言成绩' },
  { key: 'fee', label: '申请费' },
]
const DOC_KEYS = [
  { key: 'ps', label: 'PS' },
  { key: 'cv', label: 'CV' },
  { key: 'recommendation', label: '推荐信' },
] as const

const MATERIALS_TOTAL = 6
function materialsDone(p: ApplicationProject) {
  const counts = docCounts(p.id)
  let done = 0
  if (counts.ps > 0) done++
  if (counts.cv > 0) done++
  if (counts.recommendation > 0) done++
  const mats = p.materials || {}
  for (const k of MANUAL_KEYS) if (mats[k.key]) done++
  return done
}

// ----------------------------------------------------------- 截止倒计时
type DeadlineState = 'none' | 'overdue' | 'urgent' | 'soon' | 'normal'
function deadlineInfo(deadline?: string): { state: DeadlineState; days: number | null; text: string } {
  if (!deadline) return { state: 'none', days: null, text: '截止日期待填写' }
  const target = new Date(`${deadline}T00:00:00`)
  if (isNaN(target.getTime())) return { state: 'none', days: null, text: '日期格式有误' }
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((target.getTime() - today.getTime()) / 86400000)
  if (days < 0) return { state: 'overdue', days, text: `已逾期 ${Math.abs(days)} 天` }
  if (days === 0) return { state: 'urgent', days: 0, text: '今天截止' }
  if (days <= 30) return { state: 'urgent', days, text: `还剩 ${days} 天` }
  if (days <= 90) return { state: 'soon', days, text: `还剩 ${days} 天` }
  return { state: 'normal', days, text: `还剩 ${days} 天` }
}

// ----------------------------------------------------------- 概览 + 排序
const sortedProjects = computed(() => {
  const arr = [...projects.value]
  arr.sort((a, b) => {
    const da = a.deadline ? new Date(`${a.deadline}T00:00:00`).getTime() : Infinity
    const db = b.deadline ? new Date(`${b.deadline}T00:00:00`).getTime() : Infinity
    if (da !== db) return da - db
    return b.updated_at.localeCompare(a.updated_at)
  })
  return arr
})
const overview = computed(() => {
  const total = projects.value.length
  let urgent = 0, overdue = 0, ready = 0, sumPct = 0
  for (const p of projects.value) {
    const di = deadlineInfo(p.deadline)
    if (di.state === 'overdue') overdue++
    else if (di.state === 'urgent') urgent++
    sumPct += Math.round(materialsDone(p) / MATERIALS_TOTAL * 100)
    if (materialsDone(p) === MATERIALS_TOTAL) ready++
  }
  return { total, urgent, overdue, ready, avgPct: total ? Math.round(sumPct / total) : 0 }
})

// ----------------------------------------------------------- 编辑（持久化）
const editingId = ref('')
const deadlineDraft = ref('')
function openDeadline(p: ApplicationProject) {
  editingId.value = p.id
  deadlineDraft.value = p.deadline || ''
}
async function saveDeadline(p: ApplicationProject) {
  try {
    await api.updateProject(props.profileId, p.id, { deadline: deadlineDraft.value || null })
    editingId.value = ''
    await loadProjects()
  } catch { /* 失败静默，下次刷新再看 */ }
}
async function toggleManual(p: ApplicationProject, key: ManualKey) {
  const mats = { ...(p.materials || {}) }
  mats[key] = !mats[key]
  try {
    await api.updateProject(props.profileId, p.id, { materials: mats })
    await loadProjects()
  } catch { /* 失败静默 */ }
}

function sourceLabel(p: ApplicationProject) { return p.source === 'imported' ? '知识库导入' : '自定义' }
function shortRegion(r: string) {
  if (r === 'HK' || r === '香港') return '香港'
  if (r === 'SG' || r === '新加坡') return '新加坡'
  return r || ''
}
function officialLinks(p: ApplicationProject) {
  return (p.official_urls || []).map(u => {
    try { return { href: u, label: new URL(u).hostname.replace(/^www\./, '') } }
    catch { return { href: u, label: u } }
  })
}
</script>

<template>
  <div class="page board-page">
    <div class="bd-head">
      <div class="bd-head-main">
        <span class="bd-eyebrow">APPLICATION BOARD · 申请看板</span>
        <h1>申请看板</h1>
        <p>总览所有目标项目的截止日期、材料进度与文书状态，一眼看清还差什么。</p>
      </div>
      <div class="bd-head-actions">
        <button class="btn" @click="emit('go', 'projects')">管理项目</button>
        <button class="btn primary" @click="emit('go', 'generate')">生成文书</button>
      </div>
    </div>

    <p v-if="loading" class="bd-loading"><span class="bd-loading-dot"></span>正在加载项目…</p>

    <template v-else>
      <div v-if="!projects.length" class="bd-empty">
        <span class="bd-empty-mark" aria-hidden="true">◷</span>
        <h2>还没有目标项目</h2>
        <p>先在「项目管理」里导入或新建申请项目，这里就会按项目汇总截止日期与材料进度。</p>
        <button class="btn primary" @click="emit('go', 'projects')">去项目管理 →</button>
      </div>

      <template v-else>
        <!-- 总览 -->
        <div class="bd-overview">
          <div class="bd-stat"><span class="bd-stat-num">{{ overview.total }}</span><span class="bd-stat-lab">目标项目</span></div>
          <div class="bd-stat" :class="{ alert: overview.urgent }">
            <span class="bd-stat-num">{{ overview.urgent }}</span><span class="bd-stat-lab">30 天内截止</span>
          </div>
          <div class="bd-stat" :class="{ alert: overview.overdue }">
            <span class="bd-stat-num">{{ overview.overdue }}</span><span class="bd-stat-lab">已逾期</span>
          </div>
          <div class="bd-stat">
            <span class="bd-stat-num ok">{{ overview.ready }}<i>/ {{ overview.total }}</i></span>
            <span class="bd-stat-lab">材料齐备</span>
          </div>
          <div class="bd-stat">
            <span class="bd-stat-num">{{ overview.avgPct }}%</span>
            <span class="bd-stat-lab">平均材料完成度</span>
          </div>
        </div>

        <!-- 卡片网格 -->
        <div class="bd-grid">
          <article
            v-for="(p, idx) in sortedProjects" :key="p.id"
            class="bd-card" :class="[p.source, deadlineInfo(p.deadline).state]"
          >
            <header class="bd-card-top">
              <span class="bd-card-idx">{{ String(idx + 1).padStart(2, '0') }}</span>
              <span class="proj-badge" :class="p.source">{{ sourceLabel(p) }}</span>
              <span v-if="shortRegion(p.region)" class="bd-region" :class="shortRegion(p.region) === '香港' ? 'hk' : 'sg'">
                {{ shortRegion(p.region) }}
              </span>
              <span class="bd-card-go" aria-hidden="true">↗</span>
            </header>

            <div class="bd-card-title">
              <span class="bd-card-school">{{ p.university || '未填写学校' }}</span>
              <span class="bd-card-name">{{ p.name }}</span>
              <span class="bd-card-program">{{ p.program || p.program_name_en || '未填写专业' }}</span>
            </div>

            <!-- 截止倒计时 -->
            <div class="bd-deadline" :class="deadlineInfo(p.deadline).state">
              <template v-if="editingId !== p.id">
                <span class="bd-deadline-label">申请截止</span>
                <span class="bd-countdown">
                  <b>{{ deadlineInfo(p.deadline).text }}</b>
                  <small v-if="p.deadline">{{ p.deadline }}</small>
                </span>
                <button class="bd-deadline-edit" @click="openDeadline(p)">设日期</button>
              </template>
              <template v-else>
                <input type="date" v-model="deadlineDraft" class="bd-date" />
                <button class="btn small primary" @click="saveDeadline(p)">保存</button>
                <button class="btn small" @click="editingId = ''">取消</button>
              </template>
            </div>

            <!-- 材料清单 -->
            <div class="bd-materials">
              <div class="bd-mat-head"><span>材料清单</span><b>{{ materialsDone(p) }}/{{ MATERIALS_TOTAL }}</b></div>
              <div class="bd-mat-grid">
                <button
                  v-for="k in DOC_KEYS" :key="k.key" type="button"
                  class="bd-mat auto" :class="{ on: docCounts(p.id)[k.key] > 0 }"
                  @click="emit('go', 'documents')"
                >
                  <span class="bd-mat-box">{{ docCounts(p.id)[k.key] > 0 ? '✓' : '' }}</span>
                  <span class="bd-mat-text">
                    <span class="bd-mat-label">{{ k.label }}</span>
                    <span class="bd-mat-sub">{{ docCounts(p.id)[k.key] > 0 ? `${docCounts(p.id)[k.key]} 篇` : '未生成' }}</span>
                  </span>
                </button>
                <button
                  v-for="m in MANUAL_KEYS" :key="m.key" type="button"
                  class="bd-mat" :class="{ on: p.materials?.[m.key] }"
                  @click="toggleManual(p, m.key)"
                >
                  <span class="bd-mat-box">{{ p.materials?.[m.key] ? '✓' : '' }}</span>
                  <span class="bd-mat-text">
                    <span class="bd-mat-label">{{ m.label }}</span>
                    <span class="bd-mat-sub">{{ p.materials?.[m.key] ? '已备' : '待办' }}</span>
                  </span>
                </button>
              </div>
              <div class="bd-mat-track"><span class="bd-mat-fill" :style="{ width: `${Math.round(materialsDone(p) / MATERIALS_TOTAL * 100)}%` }"></span></div>
            </div>

            <!-- 当前文书状态 -->
            <div class="bd-status">
              <span class="bd-status-item"><b>{{ projectStatus(p.id).total }}</b> 篇文书</span>
              <span v-if="projectStatus(p.id).verified" class="bd-status-item ok">✓ 已校验 {{ projectStatus(p.id).verified }}</span>
              <span v-if="projectStatus(p.id).issues" class="bd-status-item bad">待核 {{ projectStatus(p.id).issues }}</span>
              <span v-if="!projectStatus(p.id).total" class="bd-status-item idle">暂无文书</span>
            </div>

            <!-- 官方链接 -->
            <div v-if="officialLinks(p).length" class="bd-links">
              <a v-for="l in officialLinks(p)" :key="l.href" :href="l.href" :title="l.href" target="_blank" rel="noopener" class="bd-link">
                {{ l.label }} <span aria-hidden="true">↗</span>
              </a>
            </div>

            <footer class="bd-card-foot">
              <button class="link" @click="emit('go', 'projects')">查看项目 →</button>
              <button class="btn small" @click="emit('go', 'generate')">生成文书</button>
            </footer>
          </article>
        </div>
      </template>
    </template>
  </div>
</template>
