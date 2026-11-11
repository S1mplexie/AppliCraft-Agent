<script setup lang="ts">
/** 项目管理：以申请项目为中心组织文书。支持从知识库导入官方项目或自定义新建，
 *  项目详情里把已生成的文书归组 / 移出，未归组文书标「未分组」。 */
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { ApplicationProject, DocumentMeta, SystemProgram } from '../types'

const props = defineProps<{
  profileId: string
  documents: DocumentMeta[]
  systemPrograms: SystemProgram[]
}>()
const emit = defineEmits<{ (e: 'go', tab: 'generate' | 'documents'): void; (e: 'refresh-docs'): void }>()

const projects = ref<ApplicationProject[]>([])
const loading = ref(false)
const detailId = ref('')
const modal = ref<'import' | 'create' | null>(null)
const importSearch = ref('')
const importRegion = ref<'all' | 'HK' | 'SG'>('all')
const importChecked = ref<string[]>([])
const importing = ref(false)
const regionFilters = [
  { key: 'all', label: '全部' },
  { key: 'HK', label: '香港' },
  { key: 'SG', label: '新加坡' },
] as const
const form = ref({ name: '', university: '', program: '', degree_type: '', region: '', intake: '', notes: '' })
const editingName = ref(false)
const nameDraft = ref('')

const detail = computed(() => projects.value.find(p => p.id === detailId.value) || null)
const profileDocs = computed(() => props.documents.filter(d => d.profile_id === props.profileId))
const projectDocs = computed(() => profileDocs.value.filter(d => d.project_id === detailId.value))
const ungroupedDocs = computed(() => profileDocs.value.filter(d => !d.project_id))
const importedIds = computed(() => new Set(
  projects.value.filter(p => p.source === 'imported' && p.system_program_id).map(p => p.system_program_id),
))
const regionCounts = computed(() => ({
  all: props.systemPrograms.length,
  HK: props.systemPrograms.filter(p => p.region === 'HK').length,
  SG: props.systemPrograms.filter(p => p.region === 'SG').length,
}))
const matchedPrograms = computed(() => {
  const kw = importSearch.value.trim().toLowerCase()
  return props.systemPrograms.filter(p => {
    if (importRegion.value !== 'all' && p.region !== importRegion.value) return false
    if (!kw) return true
    return `${p.school_name_zh}${p.school_id}${p.program_name_zh}${p.program_name_en}${p.faculty}`
      .toLowerCase().includes(kw)
  })
})
const groupedSchools = computed(() => {
  const map = new Map<string, SystemProgram[]>()
  for (const p of matchedPrograms.value) {
    const list = map.get(p.school_name_zh) || []
    list.push(p)
    map.set(p.school_name_zh, list)
  }
  return [...map.entries()]
})
const selectableVisible = computed(() => matchedPrograms.value.filter(p => !importedIds.value.has(p.program_id)))
const checkedPrograms = computed(() => importChecked.value
  .map(id => props.systemPrograms.find(p => p.program_id === id))
  .filter((p): p is SystemProgram => !!p))
const allVisibleSelected = computed(() => selectableVisible.value.length > 0
  && selectableVisible.value.every(p => importChecked.value.includes(p.program_id)))

function cleanProgramName(name: string) {
  return name.replace(/[（(]非官方译名[）)]/g, '').trim()
}
function shortFaculty(s: string) {
  if (!s) return ''
  return s.length > 28 ? `${s.slice(0, 28)}…` : s
}
function shortIntake(s: string) {
  if (!s) return '入学季待核实'
  const first = s.split(/[（(；;，,]/)[0].trim()
  return first.length > 18 ? `${first.slice(0, 18)}…` : first
}
function regionLabel(r: string) {
  return r === 'HK' ? '香港' : r === 'SG' ? '新加坡' : r || '其他'
}
function isChecked(pid: string) { return importChecked.value.includes(pid) }
function isImported(pid: string) { return importedIds.value.has(pid) }
function toggleProgram(p: SystemProgram) {
  if (isImported(p.program_id)) return
  importChecked.value = isChecked(p.program_id)
    ? importChecked.value.filter(id => id !== p.program_id)
    : [...importChecked.value, p.program_id]
}
function removeChecked(pid: string) {
  importChecked.value = importChecked.value.filter(id => id !== pid)
}
function toggleAllVisible() {
  const ids = selectableVisible.value.map(p => p.program_id)
  importChecked.value = allVisibleSelected.value
    ? importChecked.value.filter(id => !ids.includes(id))
    : [...new Set([...importChecked.value, ...ids])]
}
// 每次打开导入弹窗都从干净状态开始（搜索词 / 地区筛选 / 勾选）。
watch(modal, m => {
  if (m !== 'import') return
  importSearch.value = ''
  importRegion.value = 'all'
  importChecked.value = []
})

const docTypeShort: Record<string, string> = { cv: 'CV', ps: 'PS', recommendation: '推荐信' }
const projectsWithDocs = computed(() => {
  const counts = new Map<string, Record<string, number>>()
  for (const d of profileDocs.value) {
    if (!d.project_id) continue
    const m = counts.get(d.project_id) || { cv: 0, ps: 0, recommendation: 0 }
    m[d.doc_type] = (m[d.doc_type] || 0) + 1
    counts.set(d.project_id, m)
  }
  return counts
})
function typeBreakdown(id: string) {
  const m = projectsWithDocs.value.get(id) || ({} as Record<string, number>)
  return (['cv', 'ps', 'recommendation'] as const)
    .filter(t => m[t])
    .map(t => ({ type: t, label: docTypeShort[t], count: m[t] }))
}
function docStatusText(doc: DocumentMeta) {
  if (doc.passed_verification) return '已校验'
  if (doc.issue_count > 0) return `${doc.issue_count} 处待核`
  return '未校验'
}
function docStatusClass(doc: DocumentMeta) {
  if (doc.passed_verification) return 'ok'
  if (doc.issue_count > 0) return 'bad'
  return 'idle'
}
const detailSubtitle = computed(() => {
  const d = detail.value
  if (!d) return ''
  return [d.university, d.program, d.intake].filter(Boolean).join(' · ') || '尚未填写学校、专业与入学季'
})
const verifiedCount = computed(() => projectDocs.value.filter(d => d.passed_verification).length)
const issueDocCount = computed(() => projectDocs.value.filter(d => !d.passed_verification && d.issue_count > 0).length)
const verifyProgress = computed(() => projectDocs.value.length
  ? Math.round(verifiedCount.value / projectDocs.value.length * 100) : 0)
const officialLinks = computed(() => (detail.value?.official_urls || []).map(u => {
  try { return { href: u, label: new URL(u).hostname.replace(/^www\./, '') } }
  catch { return { href: u, label: u } }
}))

async function loadProjects() {
  if (!props.profileId) { projects.value = []; return }
  loading.value = true
  try { projects.value = (await api.listProjects(props.profileId)).items }
  catch { projects.value = [] }
  finally { loading.value = false }
}
watch(() => props.profileId, () => { detailId.value = ''; modal.value = null; void loadProjects() }, { immediate: true })

async function importCheckedPrograms() {
  if (!importChecked.value.length) return
  importing.value = true
  try {
    for (const pid of importChecked.value) {
      if (importedIds.value.has(pid)) continue
      const program = props.systemPrograms.find(p => p.program_id === pid)
      if (!program) continue
      await api.createProject(props.profileId, {
        name: `${program.school_name_zh} · ${program.program_name_zh}`,
        system_program_id: pid,
      })
    }
    await loadProjects()
    modal.value = null
    importChecked.value = []
  } finally { importing.value = false }
}

async function createCustom() {
  if (!form.value.name.trim()) return
  await api.createProject(props.profileId, { ...form.value })
  form.value = { name: '', university: '', program: '', degree_type: '', region: '', intake: '', notes: '' }
  modal.value = null
  await loadProjects()
}

async function renameProject() {
  if (!detail.value || !nameDraft.value.trim()) return
  await api.updateProject(props.profileId, detail.value.id, { name: nameDraft.value })
  editingName.value = false
  await loadProjects()
}

function startRename() {
  editingName.value = true
  nameDraft.value = detail.value?.name || ''
}

async function removeProject() {
  if (!detail.value || !window.confirm(`删除项目「${detail.value.name}」？名下文书会回到未分组，不会被删除。`)) return
  await api.deleteProject(props.profileId, detail.value.id)
  detailId.value = ''
  await loadProjects()
}

async function assign(docId: string) {
  if (!detailId.value) return
  await api.assignDocument(props.profileId, detailId.value, docId)
  emit('refresh-docs')
  await loadProjects()
}

async function unassign(docId: string) {
  if (!detailId.value) return
  await api.unassignDocument(props.profileId, detailId.value, docId)
  emit('refresh-docs')
  await loadProjects()
}

function sourceLabel(p: ApplicationProject) { return p.source === 'imported' ? '知识库导入' : '自定义' }
</script>

<template>
  <div class="page projects-page">
    <!-- 项目详情 -->
    <template v-if="detail">
      <div class="pd-crumb">
        <button class="link" @click="detailId = ''">← 返回项目列表</button>
        <span class="pd-crumb-sep">/</span>
        <span class="pd-crumb-cur">{{ detail.name }}</span>
      </div>

      <div class="pd-head">
        <div class="pd-head-main">
          <span class="pd-eyebrow">申请项目 · {{ sourceLabel(detail) }}</span>
          <template v-if="editingName">
            <div class="pd-rename">
              <input v-model="nameDraft" class="proj-name-input" @keyup.enter="renameProject" />
              <button class="btn small primary" @click="renameProject">保存</button>
              <button class="btn small" @click="editingName = false">取消</button>
            </div>
          </template>
          <h1 v-else>{{ detail.name }}</h1>
          <p class="pd-sub">{{ detailSubtitle }}</p>
        </div>
        <div v-if="!editingName" class="head-actions">
          <button class="btn primary" @click="emit('go', 'generate')">生成新文书</button>
          <button class="btn" @click="startRename">改名</button>
          <button class="btn btn-ghost danger-ghost" @click="removeProject">删除项目</button>
        </div>
      </div>

      <!-- 准备概览：已归入 / 已校验 / 待核 + 核验通过率 -->
      <div class="pd-stats">
        <div class="pd-stat"><span class="pd-stat-num">{{ projectDocs.length }}</span><span class="pd-stat-lab">已归入文书</span></div>
        <div class="pd-stat"><span class="pd-stat-num ok">{{ verifiedCount }}</span><span class="pd-stat-lab">事实校验通过</span></div>
        <div class="pd-stat" :class="{ warn: issueDocCount > 0 }">
          <span class="pd-stat-num">{{ issueDocCount }}</span><span class="pd-stat-lab">存在待核问题</span>
        </div>
        <div class="pd-progress">
          <div class="pd-progress-top"><span>核验通过率</span><b>{{ verifyProgress }}%</b></div>
          <div class="progress-track"><div class="progress-fill" :class="{ done: verifyProgress === 100 }" :style="{ width: `${verifyProgress}%` }"></div></div>
          <span class="hint">按已归入文书的校验结果计算</span>
        </div>
      </div>

      <!-- 项目档案卡 -->
      <div class="pd-info">
        <div class="pd-info-head">
          <span class="pd-eyebrow">项目档案</span>
          <span class="proj-badge" :class="detail.source">{{ sourceLabel(detail) }}</span>
        </div>
        <div class="pd-facts">
          <div class="pd-fact"><span>学校</span><b>{{ detail.university || '未填写' }}</b></div>
          <div class="pd-fact"><span>专业</span><b>{{ detail.program || '未填写' }}</b></div>
          <div class="pd-fact"><span>学位</span><b>{{ detail.degree_type || '未填写' }}</b></div>
          <div class="pd-fact"><span>地区</span><b>{{ detail.region || '未填写' }}</b></div>
          <div class="pd-fact"><span>入学季</span><b>{{ detail.intake || '未填写' }}</b></div>
          <div class="pd-fact"><span>文书数</span><b>{{ projectDocs.length }} 篇</b></div>
        </div>
        <div v-if="detail.notes" class="pd-note">
          <span class="pd-note-label">备注</span>
          <p>{{ detail.notes }}</p>
        </div>
        <div v-if="officialLinks.length" class="pd-links">
          <span class="pd-note-label">官方页面</span>
          <a v-for="l in officialLinks" :key="l.href" :href="l.href" :title="l.href" target="_blank" rel="noopener" class="pd-link">
            {{ l.label }} <span aria-hidden="true">↗</span>
          </a>
        </div>
      </div>

      <!-- 已归入文书 -->
      <section class="pd-section">
        <div class="pd-section-head">
          <span class="pd-section-bar"></span>
          <div class="pd-section-text">
            <h2>本项目文书 <span class="pd-count">{{ projectDocs.length }}</span></h2>
            <p>已归入该申请项目的 CV、PS 与推荐信。</p>
          </div>
          <button class="btn small" @click="emit('go', 'generate')">生成新文书</button>
        </div>
        <div v-if="!projectDocs.length" class="pd-empty">
          <strong>还没有归入该项目的文书</strong>
          <span class="hint">生成新文书，或从下方未分组文书中归组。</span>
        </div>
        <ul v-else class="pd-doc-list">
          <li v-for="doc in projectDocs" :key="doc.id" class="pd-doc-row">
            <span class="tag" :class="doc.doc_type">{{ doc.doc_type_label }}</span>
            <div class="pd-doc-main">
              <button class="pd-doc-title" @click="emit('go', 'documents')">{{ doc.title }}</button>
              <span class="pd-doc-meta">{{ doc.word_count }} 词 · 更新于 {{ doc.updated_at.slice(0, 10) }}</span>
            </div>
            <span class="doc-status" :class="docStatusClass(doc)">{{ docStatusText(doc) }}</span>
            <button class="btn small" @click="unassign(doc.id)">移出</button>
          </li>
        </ul>
      </section>

      <!-- 可归入的未分组文书 -->
      <section class="pd-section candidate">
        <div class="pd-section-head">
          <span class="pd-section-bar"></span>
          <div class="pd-section-text">
            <h2>可归入本项目 <span class="pd-count">{{ ungroupedDocs.length }}</span></h2>
            <p>尚未归入任何项目的文书，选合适的归入当前申请。</p>
          </div>
        </div>
        <div v-if="!ungroupedDocs.length" class="pd-empty slim">
          <span class="hint">当前档案没有未分组文书，所有文书都已归入项目。</span>
        </div>
        <ul v-else class="pd-doc-list">
          <li v-for="doc in ungroupedDocs" :key="doc.id" class="pd-doc-row">
            <span class="tag" :class="doc.doc_type">{{ doc.doc_type_label }}</span>
            <div class="pd-doc-main">
              <button class="pd-doc-title" @click="emit('go', 'documents')">{{ doc.title }}</button>
              <span class="pd-doc-meta">{{ doc.word_count }} 词 · 更新于 {{ doc.updated_at.slice(0, 10) }}</span>
            </div>
            <span class="doc-status" :class="docStatusClass(doc)">{{ docStatusText(doc) }}</span>
            <button class="btn small primary" @click="assign(doc.id)">归入本项目</button>
          </li>
        </ul>
      </section>
    </template>

    <!-- 项目列表 -->
    <template v-else>
      <div class="page-head">
        <div>
          <h1>项目管理</h1>
          <p>把文书按申请项目归类，跟踪每个项目的准备进度。</p>
        </div>
        <div class="head-actions">
          <button class="btn primary" @click="modal = 'import'">从知识库导入</button>
          <button class="btn" @click="modal = 'create'">新建项目</button>
        </div>
      </div>

      <p v-if="loading" class="hint">正在加载项目…</p>

      <template v-else>
        <!-- 概览 -->
        <div v-if="projects.length" class="proj-overview">
          <div class="ov-stat"><span class="ov-num">{{ projects.length }}</span><span class="ov-lab">申请项目</span></div>
          <div class="ov-stat"><span class="ov-num">{{ profileDocs.length }}</span><span class="ov-lab">文书总数</span></div>
          <div class="ov-stat" :class="{ alert: ungroupedDocs.length }">
            <span class="ov-num">{{ ungroupedDocs.length }}</span><span class="ov-lab">未分组</span>
          </div>
          <p class="ov-tip">未分组的文书不属于任何项目；打开任一项目即可归入对应申请。</p>
        </div>

        <!-- 未分组引导 -->
        <div v-if="ungroupedDocs.length" class="proj-ungrouped-card">
          <div>
            <strong>有 {{ ungroupedDocs.length }} 篇文书尚未归入任何项目</strong>
            <span class="hint">打开任一项目，即可把它们归入对应申请。</span>
          </div>
          <button v-if="projects.length" class="btn small" @click="detailId = projects[0].id">去归入</button>
        </div>

        <!-- 空状态 -->
        <div v-if="!projects.length" class="empty-lead">
          还没有申请项目。从知识库导入目标院校项目，或自定义新建：
          <div class="proj-actions">
            <button class="btn primary" @click="modal = 'import'">从知识库导入</button>
            <button class="btn" @click="modal = 'create'">新建项目</button>
          </div>
        </div>

        <!-- 卡片网格 -->
        <div v-else class="proj-grid">
          <button v-for="p in projects" :key="p.id" class="proj-card" @click="detailId = p.id">
            <div class="proj-card-top">
              <span class="proj-badge" :class="p.source">{{ sourceLabel(p) }}</span>
              <strong>{{ p.name }}</strong>
            </div>
            <span class="proj-card-sub">{{ p.university || '未填学校' }}{{ p.program ? ` · ${p.program}` : '' }}</span>
            <div class="proj-card-types">
              <span v-for="t in typeBreakdown(p.id)" :key="t.type" class="tag" :class="t.type">{{ t.label }} {{ t.count }}</span>
              <span v-if="!p.document_count" class="proj-card-empty">暂无文书</span>
            </div>
            <div class="proj-card-foot">
              <span class="proj-card-intake">{{ p.intake || '未设入学季' }}</span>
              <span class="proj-card-meta">{{ p.document_count }} 篇 · {{ p.updated_at.slice(0, 10) }}</span>
            </div>
          </button>
        </div>
      </template>
    </template>

    <!-- 导入弹窗：按学校分组的项目卡片，支持搜索 / 地区筛选 / 批量勾选 -->
    <div v-if="modal === 'import'" class="modal-mask" @click.self="modal = null">
      <div class="modal imp-modal" role="dialog" aria-modal="true" aria-label="从知识库导入项目">
        <div class="imp-head">
          <div>
            <span class="imp-eyebrow">知识库 · 官方项目</span>
            <h2>从知识库导入项目</h2>
            <p>按学校与地区浏览已收录的官方项目资料，勾选后批量加入申请清单。</p>
          </div>
          <button class="imp-close" aria-label="关闭" @click="modal = null">×</button>
        </div>

        <div class="imp-toolbar">
          <div class="imp-search">
            <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" /><path d="M12.6 12.6 17 17" /></svg>
            <input v-model="importSearch" placeholder="搜索学校 / 专业中英文名…" aria-label="搜索项目" />
            <button v-if="importSearch" class="imp-search-clear" aria-label="清空搜索" @click="importSearch = ''">×</button>
          </div>
          <div class="imp-filters">
            <button
              v-for="f in regionFilters" :key="f.key"
              class="imp-filter" :class="{ on: importRegion === f.key }"
              @click="importRegion = f.key"
            >{{ f.label }} <em>{{ regionCounts[f.key] }}</em></button>
          </div>
        </div>

        <div class="imp-status">
          <span>
            共 {{ matchedPrograms.length }} 个项目 · {{ groupedSchools.length }} 所学校<span v-if="importedIds.size"> · 已导入 {{ importedIds.size }} 个</span>
          </span>
          <span class="imp-status-actions">
            <button class="link" :disabled="!selectableVisible.length" @click="toggleAllVisible">
              {{ allVisibleSelected ? '取消全选' : '全选当前结果' }}
            </button>
            <button class="link" :disabled="!importChecked.length" @click="importChecked = []">清空</button>
          </span>
        </div>

        <div class="imp-body">
          <div v-if="!groupedSchools.length" class="imp-empty">
            <span class="imp-empty-mark">⌕</span>
            <strong>没有匹配的项目</strong>
            <span class="hint">换个关键词，或切换地区筛选试试。</span>
          </div>
          <div v-for="[school, programs] in groupedSchools" :key="school" class="imp-school">
            <div class="imp-school-head">
              <h3>{{ school }}</h3>
              <span class="imp-school-count">{{ programs.length }} 个项目</span>
              <span class="imp-school-line"></span>
            </div>
            <div class="imp-grid">
              <label
                v-for="p in programs" :key="p.program_id" class="imp-card"
                :class="{ on: isChecked(p.program_id), done: isImported(p.program_id) }"
              >
                <input
                  class="imp-native" type="checkbox" :checked="isChecked(p.program_id)"
                  :disabled="isImported(p.program_id)" @change="toggleProgram(p)"
                />
                <span class="imp-check" aria-hidden="true"></span>
                <span class="imp-card-zh">{{ cleanProgramName(p.program_name_zh) || p.program_name_en }}</span>
                <span class="imp-card-en">{{ p.program_name_en }}</span>
                <span class="imp-card-meta">
                  <span v-if="p.faculty">{{ shortFaculty(p.faculty) }}</span>
                  <span>{{ shortIntake(p.intake) }}</span>
                </span>
                <span class="imp-card-foot">
                  <span class="imp-region" :class="p.region === 'HK' ? 'hk' : 'sg'">{{ regionLabel(p.region) }}</span>
                  <span class="imp-fields">{{ p.fields?.length ? `${p.fields.length} 个资料板块` : '官方资料' }}</span>
                  <span v-if="isImported(p.program_id)" class="imp-done-tag">已导入</span>
                </span>
              </label>
            </div>
          </div>
        </div>

        <div class="imp-foot">
          <div class="imp-foot-left">
            <template v-if="checkedPrograms.length">
              <span class="imp-foot-label">已选 {{ checkedPrograms.length }} 个项目</span>
              <div class="imp-chips">
                <span v-for="p in checkedPrograms.slice(0, 3)" :key="p.program_id" class="imp-chip">
                  <span class="imp-chip-text">{{ cleanProgramName(p.program_name_zh) }}</span>
                  <button aria-label="移除该项目" @click="removeChecked(p.program_id)">×</button>
                </span>
                <span v-if="checkedPrograms.length > 3" class="imp-chip more">+{{ checkedPrograms.length - 3 }}</span>
              </div>
            </template>
            <span v-else class="hint">勾选项目后可批量导入申请清单</span>
          </div>
          <button class="btn primary" :disabled="!importChecked.length || importing" @click="importCheckedPrograms">
            {{ importing ? '导入中…' : '导入选中项目' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新建弹窗 -->
    <div v-if="modal === 'create'" class="modal-mask" @click.self="modal = null">
      <div class="modal proj-modal">
        <div class="modal-head">
          <h2>新建申请项目</h2>
          <button class="btn small" @click="modal = null">关闭</button>
        </div>
        <div class="proj-form">
          <label>项目名称 *<input v-model="form.name" placeholder="例：港大 CS 主申" /></label>
          <label>学校<input v-model="form.university" placeholder="香港大学" /></label>
          <label>专业<input v-model="form.program" placeholder="计算机科学" /></label>
          <label>学位<input v-model="form.degree_type" placeholder="MSc" /></label>
          <label>地区<input v-model="form.region" placeholder="HK / SG" /></label>
          <label>入学季<input v-model="form.intake" placeholder="2027 FALL" /></label>
          <label>备注<textarea v-model="form.notes" rows="2" /></label>
        </div>
        <div class="modal-foot">
          <span />
          <button class="btn primary" :disabled="!form.name.trim()" @click="createCustom">创建项目</button>
        </div>
      </div>
    </div>
  </div>
</template>