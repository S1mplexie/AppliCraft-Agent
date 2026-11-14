<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import DocumentViewer from './DocumentViewer.vue'
import DocumentInsights from './DocumentInsights.vue'
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
  /** 本次生成进行中：右栏切换成实时轨迹，替代文书查看器。 */
  generating: boolean
  liveData: Record<string, any> | null
  /** 最近一次生成的结果：成功条 / 失败卡片 / 「新」标记共用的数据源。 */
  genOutcome: {
    ok: boolean; docId?: string; title?: string; score?: number | null; message?: string
  } | null
}>()
const emit = defineEmits<{
  open: [id: string]
  save: [markdown: string]
  remove: [id: string]
  regenerate: [payload: RegenPayload]
  go: [tab: TabKey]
  scope: [value: 'current' | 'all']
  dismissResult: []
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

// 新文书生成完成后，把它滚进列表可视区（文书多时顶部提示条之外的第二重定位）。
watch(() => props.genOutcome?.docId, async (id) => {
  if (!id || !props.genOutcome?.ok) return
  await nextTick()
  document.querySelector<HTMLElement>('.library-item.just-created')
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
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
        <button class="btn primary" @click="emit('go', 'generate')">
          {{ generating ? '返回生成工作台 →' : '新建文书 →' }}
        </button>
      </div>
    </div>

    <!-- 生成完成的往返闭环：明确告诉用户新文书在哪、分数多少、怎么回去写下一份。 -->
    <div v-if="genOutcome?.ok" class="gen-result-bar">
      <span class="gen-result-icon">✓</span>
      <div class="gen-result-text">
        <strong>《{{ genOutcome.title || '新文书' }}》已生成并打开</strong>
        <small>
          质量分{{ genOutcome.score != null ? ' ' + genOutcome.score + '/100' : '已归档' }}
          · 生成轨迹与事实校验已保存在这份文书下
        </small>
      </div>
      <button class="btn small" @click="emit('go', 'generate')">返回生成工作台</button>
      <button class="icon-btn" title="关闭提示" @click="emit('dismissResult')">×</button>
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
            :class="{ active: activeId === doc.id, 'just-created': genOutcome?.ok && genOutcome.docId === doc.id }"
            @click="emit('open', doc.id)"
          >
            <div class="library-item-top">
              <span class="badge" :class="doc.passed_verification ? 'ok' : 'warn'">{{ doc.doc_type_label }}</span>
              <small>{{ fmtDate(doc.created_at) }}</small>
            </div>
            <div class="library-item-title">
              <strong>{{ doc.title }}</strong>
              <span v-if="genOutcome?.ok && genOutcome.docId === doc.id" class="new-tag">新</span>
            </div>
            <div class="library-item-meta">
              <span>v{{ doc.version }}</span><span>约 {{ doc.word_count }} 词</span>
              <span>{{ doc.language === 'zh' ? '中文' : 'English' }}</span>
              <span v-if="doc.bilingual" class="bilingual-tag">中英对照</span>
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
            <button class="btn small primary" @click="emit('go', 'generate')">去生成 →</button>
          </div>
        </div>
      </aside>

      <section class="panel library-viewer">
        <!-- 生成中：直接在这里显示本次生成的实时轨迹，而不是留在「生成文书」tab -->
        <template v-if="generating">
          <div class="gen-live-head">
            <span class="gen-live-dot"></span>
            <div>
              <strong>正在生成新文书…</strong>
              <small>下方是本次生成的实时轨迹与自检修复过程；生成在后台继续，可先回工作台，点左侧「文书库」随时回来</small>
            </div>
            <button class="btn small" @click="emit('go', 'generate')">回生成工作台</button>
          </div>
          <DocumentInsights v-bind="liveData || {}" live :generating="true" />
        </template>
        <!-- 生成失败：不要把用户悄悄丢回上一份文书，给明确原因与重试入口。 -->
        <div v-else-if="genOutcome && !genOutcome.ok" class="gen-fail-card">
          <span class="gen-fail-mark">!</span>
          <h2>本次生成未完成</h2>
          <p class="gen-fail-msg">{{ genOutcome.message || '生成过程中出现异常，请稍后重试。' }}</p>
          <p class="gen-fail-hint">这次没有产出新文书；原来的文书和额度状态未受影响。可以回到生成工作台调整参数后重试。</p>
          <div class="gen-fail-actions">
            <button class="btn primary" @click="emit('go', 'generate')">返回生成工作台重试 →</button>
            <button class="btn" @click="emit('dismissResult')">留在文书库</button>
          </div>
        </div>
        <DocumentViewer
          v-else
          :document="document" :issues="issues" :outline="outline" :warnings="warnings"
          :regenerating="regenerating" :regen-stage="regenStage"
          @save="emit('save', $event)" @remove="emit('remove', $event)"
          @regenerate="emit('regenerate', $event)"
        />
      </section>
    </div>
  </div>
</template>
