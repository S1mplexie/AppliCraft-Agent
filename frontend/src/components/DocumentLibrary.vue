<script setup lang="ts">
import { computed, ref } from 'vue'
import DocumentViewer from './DocumentViewer.vue'
import type { DocumentDetail, DocumentMeta, Issue, RegenPayload, TabKey } from '../types'

const props = defineProps<{
  documents: DocumentMeta[]
  document: DocumentDetail | null
  issues: Issue[]
  outline: any[]
  warnings: string[]
  activeId: string
  scope: 'current' | 'all'
  regenerating: boolean
  regenStage: string
}>()
const emit = defineEmits<{
  open: [id: string]
  save: [markdown: string]
  remove: [id: string]
  regenerate: [payload: RegenPayload]
  go: [tab: TabKey]
  scope: [value: 'current' | 'all']
}>()

const filters = [
  { key: 'all', label: '全部' },
  { key: 'ps', label: 'PS / SOP' },
  { key: 'recommendation', label: '推荐信' },
  { key: 'cv', label: '学术 CV' },
] as const
const filter = ref<string>('all')
const keyword = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return props.documents.filter(doc => {
    if (filter.value !== 'all' && doc.doc_type !== filter.value) return false
    return !kw || (doc.title || '').toLowerCase().includes(kw)
  })
})

function fmtDate(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value.slice(0, 16) : d.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="page library-page">
    <div class="page-head">
      <div>
        <h1>文书库</h1>
        <p>按类型筛选、回溯版本、核对事实校验意见并导出 DOCX</p>
      </div>
      <div class="head-actions">
        <button class="btn primary" @click="emit('go', 'generate')">新建文书</button>
      </div>
    </div>

    <div class="library-layout">
      <aside class="library-side">
        <div class="scope-row">
          <button
            class="filter-chip" :class="{ active: scope === 'current' }"
            @click="emit('scope', 'current')"
          >当前档案</button>
          <button
            class="filter-chip" :class="{ active: scope === 'all' }"
            @click="emit('scope', 'all')"
          >全部档案</button>
        </div>
        <div class="library-filters">
          <button
            v-for="item in filters" :key="item.key" class="filter-chip"
            :class="{ active: filter === item.key }" @click="filter = item.key"
          >{{ item.label }}</button>
        </div>
        <input v-model="keyword" class="library-search" placeholder="搜索文书标题…" />
        <div class="library-count">
          <span>共 {{ filtered.length }} 份 · {{ scope === 'all' ? '全部档案' : '当前档案' }}</span>
        </div>

        <div class="library-list">
          <button
            v-for="doc in filtered" :key="doc.id" class="library-item"
            :class="{ active: activeId === doc.id }" @click="emit('open', doc.id)"
          >
            <div class="library-item-top">
              <span class="badge" :class="doc.passed_verification ? 'ok' : 'warn'">{{ doc.doc_type_label }}</span>
              <small>{{ fmtDate(doc.created_at) }}</small>
            </div>
            <strong>{{ doc.title }}</strong>
            <div class="library-item-meta">
              <span>v{{ doc.version }}</span><span>约 {{ doc.word_count }} 词</span>
              <span>{{ doc.language === 'zh' ? '中文' : 'English' }}</span>
              <span v-if="doc.issue_count" class="danger-text">{{ doc.issue_count }} 条待核</span>
            </div>
            <span class="library-delete link danger" @click.stop="emit('remove', doc.id)">删除</span>
          </button>
          <div v-if="!filtered.length" class="mini-empty">
            <strong>{{ documents.length ? '没有匹配的文书' : scope === 'current' ? '当前档案还没有文书' : '文书库还是空的' }}</strong>
            <span>{{ documents.length ? '换个类型或关键词试试' : scope === 'current' ? '文书按档案归属展示，其他档案的文书可切到「全部档案」查看' : '去生成工作台创建第一份材料' }}</span>
            <button v-if="scope === 'current' && !documents.length" class="btn small" @click="emit('scope', 'all')">
              查看全部档案的文书
            </button>
            <button class="btn small primary" @click="emit('go', 'generate')">去生成</button>
          </div>
        </div>
      </aside>

      <section class="panel library-viewer">
        <DocumentViewer
          :document="document" :issues="issues" :outline="outline" :warnings="warnings"
          :regenerating="regenerating" :regen-stage="regenStage"
          @save="emit('save', $event)" @remove="emit('remove', $event)"
          @regenerate="emit('regenerate', $event)"
        />
      </section>
    </div>
  </div>
</template>
