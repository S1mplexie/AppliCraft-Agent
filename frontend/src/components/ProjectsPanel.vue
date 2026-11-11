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
const importChecked = ref<string[]>([])
const importing = ref(false)
const form = ref({ name: '', university: '', program: '', degree_type: '', region: '', intake: '', notes: '' })
const editingName = ref(false)
const nameDraft = ref('')

const detail = computed(() => projects.value.find(p => p.id === detailId.value) || null)
const profileDocs = computed(() => props.documents.filter(d => d.profile_id === props.profileId))
const projectDocs = computed(() => profileDocs.value.filter(d => d.project_id === detailId.value))
const ungroupedDocs = computed(() => profileDocs.value.filter(d => !d.project_id))
const groupedSchools = computed(() => {
  const kw = importSearch.value.trim().toLowerCase()
  const map = new Map<string, SystemProgram[]>()
  for (const p of props.systemPrograms) {
    if (kw && !(`${p.school_name_zh}${p.program_name_zh}${p.program_name_en}`.toLowerCase().includes(kw))) continue
    const list = map.get(p.school_name_zh) || []
    list.push(p)
    map.set(p.school_name_zh, list)
  }
  return [...map.entries()]
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
      <div class="page-head">
        <div>
          <template v-if="editingName">
            <input v-model="nameDraft" class="proj-name-input" @keyup.enter="renameProject" />
          </template>
          <h1 v-else>
            {{ detail.name }}
            <span class="proj-badge" :class="detail.source">{{ sourceLabel(detail) }}</span>
          </h1>
        </div>
        <div class="head-actions">
          <button class="btn" @click="detailId = ''">← 返回列表</button>
          <template v-if="editingName">
            <button class="btn primary" @click="renameProject">保存</button>
            <button class="btn" @click="editingName = false">取消</button>
          </template>
          <template v-else>
            <button class="btn" @click="emit('go', 'generate')">生成新文书</button>
            <button class="btn" @click="startRename">改名</button>
            <button class="btn" @click="removeProject">删除项目</button>
          </template>
        </div>
      </div>

      <div class="proj-info">
        <div class="proj-info-grid">
          <div class="ms-item"><span class="ms-k">学校</span><span class="ms-v">{{ detail.university || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">专业</span><span class="ms-v">{{ detail.program || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">学位</span><span class="ms-v">{{ detail.degree_type || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">地区</span><span class="ms-v">{{ detail.region || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">入学季</span><span class="ms-v">{{ detail.intake || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">文书数</span><span class="ms-v">{{ projectDocs.length }}</span></div>
        </div>
        <p v-if="detail.notes" class="hint">{{ detail.notes }}</p>
        <p v-if="detail.official_urls?.length" class="hint">
          官方页面：<a v-for="u in detail.official_urls" :key="u" :href="u" target="_blank" rel="noopener" class="proj-link">{{ u }}</a>
        </p>
      </div>

      <section class="proj-docs">
        <h2>本项目文书</h2>
        <p v-if="!projectDocs.length" class="hint">还没有归入该项目的文书。点击「生成新文书」，或从下方未分组文书中归组。</p>
        <ul v-else class="proj-doc-list">
          <li v-for="doc in projectDocs" :key="doc.id" class="proj-doc-row">
            <span class="tag" :class="doc.doc_type">{{ doc.doc_type_label }}</span>
            <button class="proj-doc-title" @click="emit('go', 'documents')">{{ doc.title }}</button>
            <span class="doc-status" :class="docStatusClass(doc)">{{ docStatusText(doc) }}</span>
            <span class="proj-doc-meta">{{ doc.word_count }} 词 · {{ doc.updated_at.slice(0, 10) }}</span>
            <button class="btn small" @click="unassign(doc.id)">移出</button>
          </li>
        </ul>
      </section>

      <section class="proj-docs">
        <h2>可归入本项目（未分组）的文书</h2>
        <p v-if="!ungroupedDocs.length" class="hint">当前档案没有未分组文书。</p>
        <ul v-else class="proj-doc-list">
          <li v-for="doc in ungroupedDocs" :key="doc.id" class="proj-doc-row">
            <span class="tag" :class="doc.doc_type">{{ doc.doc_type_label }}</span>
            <button class="proj-doc-title" @click="emit('go', 'documents')">{{ doc.title }}</button>
            <span class="doc-status" :class="docStatusClass(doc)">{{ docStatusText(doc) }}</span>
            <span class="proj-doc-meta">{{ doc.word_count }} 词 · {{ doc.updated_at.slice(0, 10) }}</span>
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

    <!-- 导入弹窗 -->
    <div v-if="modal === 'import'" class="modal-mask" @click.self="modal = null">
      <div class="modal proj-modal">
        <div class="modal-head">
          <h2>从知识库导入项目</h2>
          <button class="btn small" @click="modal = null">关闭</button>
        </div>
        <input v-model="importSearch" class="proj-search" placeholder="搜索学校或专业…" />
        <div class="proj-import-list">
          <p v-if="!groupedSchools.length" class="hint">没有匹配的项目。</p>
          <div v-for="[school, programs] in groupedSchools" :key="school" class="proj-import-school">
            <h3>{{ school }}</h3>
            <label v-for="p in programs" :key="p.program_id" class="proj-import-item">
              <input
                type="checkbox" :value="p.program_id"
                v-model="importChecked"
              />
              <span>{{ p.program_name_zh }}（{{ p.program_name_en }}）</span>
            </label>
          </div>
        </div>
        <div class="modal-foot">
          <span class="hint">已选 {{ importChecked.length }} 个项目</span>
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