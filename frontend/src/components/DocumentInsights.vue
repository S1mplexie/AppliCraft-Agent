<script setup lang="ts">
/**
 * 文书洞察：生成轨迹 / 事实校验 / 段落大纲。
 *
 * 两种数据来源，互不串台：
 * - archive（默认，传 document）：全部从「当前打开文书」自己的 trace 派生，
 *   打开别的文书或来回切 tab 都只显示这份文书的记录。
 * - live（传 live + SSE 字段）：生成页展示「本次生成」的实时进度，
 *   生成完成后自动跳到文书库，不留在生成页当历史残留。
 */
import { computed, ref, watch } from 'vue'
import { DIMENSION_LABELS, NODE_LABELS } from '../types'
import type { DocumentDetail, Issue, KnowledgeRef, NodeEvent } from '../types'

const props = defineProps<{
  document?: DocumentDetail | null
  live?: boolean
  events?: NodeEvent[]
  issues?: Issue[]
  outline?: any[]
  warnings?: string[]
  numericWarnings?: string[]
  score?: number | null
  dimensions?: Record<string, number> | null
  verdict?: string | null
  knowledge?: KnowledgeRef | null
  wordCount?: number | null
  placeholderCount?: number | null
  wordLimit?: number | null
  generating?: boolean
  modelName?: string
}>()
const emit = defineEmits<{ go: [tab: 'documents'] }>()

const trace = computed(() => props.document?.trace || null)
const critique = computed(() => trace.value?.critique || null)
// 归档事件补齐中文节点名：旧文档可能只落了 node / summary。
const archivedEvents = computed<NodeEvent[]>(() =>
  (trace.value?.events || []).map(e => ({
    ...e,
    label: e.label || NODE_LABELS[e.node] || e.node,
  } as NodeEvent)),
)

const view = computed(() => {
  if (props.live) {
    // 文书库的实时区不传表单里的 wordLimit，从最近的 verify 自检结果里取目标篇幅。
    const lastVerify = [...(props.events || [])].reverse().find(e => e.node === 'verify')
    return {
      events: props.events || [],
      issues: props.issues || [],
      outline: props.outline || [],
      warnings: props.warnings || [],
      numericWarnings: props.numericWarnings || [],
      score: props.score ?? null,
      dimensions: props.dimensions ?? null,
      verdict: props.verdict ?? null,
      knowledge: props.knowledge ?? null,
      wordCount: props.wordCount ?? null,
      placeholderCount: props.placeholderCount ?? null,
      wordLimit: props.wordLimit ?? lastVerify?.self_check?.limit ?? null,
    }
  }
  const c = critique.value
  const lastVerify = [...archivedEvents.value].reverse().find(e => e.node === 'verify')
  return {
    events: archivedEvents.value,
    issues: c?.issues || [],
    outline: trace.value?.outline || [],
    warnings: trace.value?.warnings || [],
    numericWarnings: c?.numeric_warnings || [],
    score: c?.score ?? null,
    dimensions: c?.dimensions ?? null,
    verdict: c?.verdict ?? (c?.issues?.length ? 'needs_review' : 'passed'),
    knowledge: trace.value?.knowledge ?? null,
    wordCount: c?.word_count ?? props.document?.meta.word_count ?? null,
    placeholderCount: c?.placeholder_count ?? lastVerify?.self_check?.placeholders ?? null,
    wordLimit: trace.value?.request?.word_limit ?? lastVerify?.self_check?.limit ?? null,
  }
})

type InsightKey = 'trace' | 'verify' | 'outline'
const insightTab = ref<InsightKey>('trace')
const insightTabs = computed(() => [
  { key: 'trace' as const, label: '生成轨迹', count: view.value.events.length },
  { key: 'verify' as const, label: '事实校验', count: view.value.issues.length },
  { key: 'outline' as const, label: '段落大纲', count: view.value.outline.length },
])
// 生成一开始强制回到轨迹页；切换文书时若当前 tab 无内容也回落到轨迹页。
watch(() => props.generating, (running) => { if (running) insightTab.value = 'trace' })
watch(() => props.document?.meta.id, () => { insightTab.value = 'trace' })

const dimensionRows = computed(() =>
  Object.entries(view.value.dimensions || {}).map(([key, value]) => ({
    key,
    label: DIMENSION_LABELS[key] || key,
    value: Math.max(0, Math.min(5, Number(value) || 0)),
  })),
)
const scoreColor = computed(() => {
  const s = view.value.score
  if (s == null) return 'neutral'
  if (s >= 85) return 'good'
  if (s >= 70) return 'warn'
  return 'bad'
})
const scoreLabel = computed(() => {
  const s = view.value.score
  if (s == null) return '未评分'
  if (s >= 85) return '优秀'
  if (s >= 70) return '良好'
  return '需修改'
})
// 生成阶段进度：把节点映射成固定步骤，避免轨迹只是一条不断追加的日志。
const STAGES = [
  { key: 'intake', label: '素材' },
  { key: 'outline', label: '大纲' },
  { key: 'draft', label: '初稿' },
  { key: 'verify', label: '自检' },
  { key: 'revise', label: '自修复' },
  { key: 'finalize', label: '定稿' },
]
const NODE_TO_STAGE: Record<string, number> = {
  intake: 0, outline: 1, draft: 2, cv_render: 2, verify: 3, revise: 4, finalize: 5,
}
const stageIndex = computed(() => {
  let idx = -1
  for (const event of view.value.events) {
    const i = NODE_TO_STAGE[event.node]
    if (i != null) idx = Math.max(idx, i)
  }
  return idx
})
const stageDone = computed(() => stageIndex.value >= STAGES.length - 1)
const verdictMeta = computed(() => {
  switch (view.value.verdict) {
    case 'factual_risk': return { label: '事实风险', cls: 'bad' }
    case 'needs_review': return { label: '建议复核', cls: 'warn' }
    case 'passed': return { label: '已核验', cls: 'good' }
    default: return null
  }
})

// ===== 自检修复轨迹：把「初稿评分 → 每轮自检 → 自修复 → 复检评分」显式画出来 =====
// 只统计「本次运行」：起草（draft / cv_render）或按建议重生成（regenerate）之后的事件。
// 文书归档的 trace 会累积多轮事件，不切段会把上一版分数误当成本轮初稿分。
const runStart = computed(() => {
  let idx = 0
  view.value.events.forEach((e, i) => {
    if (e.node === 'draft' || e.node === 'cv_render' || e.node === 'regenerate') idx = i + 1
  })
  return idx
})
const runEvents = computed(() => view.value.events.slice(runStart.value))
const verifyEvents = computed(() => runEvents.value.filter(e => e.node === 'verify'))
const repairRounds = computed(() => runEvents.value.filter(e => e.node === 'revise').length)
function issuesOf(e: NodeEvent): number {
  if (e.issue_total != null) return e.issue_total
  if (e.hard_issue_count != null || e.soft_issue_count != null) {
    return (e.hard_issue_count ?? 0) + (e.soft_issue_count ?? 0)
  }
  // 旧归档文档的 verify 事件只带 issues 数组，没有计数与自检明细。
  return e.issues?.length ?? 0
}
/** 分数曲线：初稿（或按建议修订前）→ 自检修复后的最后一次复检。 */
const repair = computed(() => {
  const vs = verifyEvents.value
  if (!vs.length) return null
  const first = vs[0]
  const last = vs[vs.length - 1]
  const initial = first.score_before ?? first.score ?? null
  const final = last.score ?? view.value.score ?? null
  return {
    initial,
    final,
    delta: initial != null && final != null ? final - initial : null,
    rounds: repairRounds.value,
    issuesBefore: issuesOf(first),
    issuesAfter: issuesOf(last),
    userDriven: view.value.events[runStart.value - 1]?.node === 'regenerate',
  }
})
function signed(n: number | null | undefined): string {
  if (n == null) return '—'
  return n > 0 ? '+' + n : String(n)
}
function deltaClass(n: number | null | undefined): string {
  if (n == null || n === 0) return 'flat'
  return n > 0 ? 'up' : 'down'
}
/** 程序确定性自检的四项硬指标，转成可直接渲染的 chip。 */
function checkChips(e: NodeEvent): { text: string; bad: boolean }[] {
  const sc = e.self_check
  if (!sc) return []
  return [
    { text: '篇幅 ' + (sc.length_ok ? '达标' : '偏差') + (sc.words != null ? ' ' + sc.words + '/' + (sc.limit ?? '—') + ' 词' : ''), bad: !sc.length_ok },
    { text: '占位符 ' + sc.placeholders + '/3', bad: !sc.placeholder_ok },
    { text: '结构 ' + (sc.structure_ok ? '正常' : '有残留'), bad: !sc.structure_ok },
    { text: sc.numbers ? '数字 ' + sc.numbers + ' 处待核' : '数字已核对', bad: sc.numbers > 0 },
  ]
}
const FATAL_TYPES = new Set(['fabrication', 'contradiction', 'unsupported', 'program_fit'])
const hardCount = computed(() => view.value.issues.filter(i => FATAL_TYPES.has(i.type)).length)
const knowledgeSources = computed(() => view.value.knowledge?.sources || [])

const emptyText = computed(() => ({
  trace: props.live ? '正在准备生成…' : '这份文书没有保存生成轨迹（较早生成的文书可能未记录节点明细）',
  verify: props.live ? '生成后模型会核对文书中的事实与数字，并给出质量评分，可疑之处会列在这里' : '这份文书没有记录校验意见',
  outline: props.live ? '生成时模型会先规划段落结构，再逐段写作' : '这份文书没有记录段落大纲',
}))
</script>

<template>
  <section class="card insight-panel">
    <div class="insight-scope-bar">
      <span class="insight-scope" :class="live ? 'live' : 'archive'">
        {{ live ? '本次生成 · 实时进度' : '该文书的生成记录' }}
      </span>
      <small>{{ live ? '完成后会自动归档到文书库中对应的文书下' : '只展示当前打开文书的轨迹与校验结果，切换文书不会串台' }}</small>
    </div>
    <div class="insight-tabs">
      <button
        v-for="tab in insightTabs" :key="tab.key" class="insight-tab"
        :class="{ active: insightTab === tab.key }" @click="insightTab = tab.key"
      >
        {{ tab.label }}<em v-if="tab.count">{{ tab.count }}</em>
      </button>
    </div>

    <div v-if="view.events.length" class="stage-track">
      <div
        v-for="(stage, i) in STAGES" :key="stage.key" class="stage"
        :class="{ done: i <= stageIndex, running: generating && i === stageIndex && !stageDone }"
      >
        <span class="stage-dot"></span><span class="stage-label">{{ stage.label }}</span>
      </div>
    </div>

    <div class="insight-body">
      <div v-show="insightTab === 'trace'">
        <!-- 自检修复：初稿分 → 复检分，让分数提升与修复轮次一眼可见 -->
        <div v-if="repair" class="repair-card">
          <div class="repair-head">
            <span class="repair-title">自检修复</span>
            <span class="repair-badge" :class="repair.rounds ? 'active' : 'clean'">
              {{ repair.rounds ? '自动修复 ' + repair.rounds + ' 轮' : '初审通过 · 未触发修复' }}
            </span>
          </div>
          <div class="repair-flow">
            <div class="rf-side">
              <small>{{ repair.userDriven ? '修订前评分' : '初稿评分' }}</small>
              <div><b>{{ repair.initial ?? '—' }}</b><span>/100</span></div>
            </div>
            <div class="rf-arrow">
              <span class="rf-line"></span>
              <em :class="deltaClass(repair.delta)">{{ signed(repair.delta) }} 分</em>
            </div>
            <div class="rf-side">
              <small>自检修复后复检</small>
              <div><b :class="deltaClass(repair.delta)">{{ repair.final ?? '—' }}</b><span>/100</span></div>
            </div>
          </div>
          <p class="repair-meta">
            <template v-if="repair.rounds">
              模型复核 + 程序直检共发现 {{ repair.issuesBefore }} 条问题，经 {{ repair.rounds }} 轮自修复，复检剩 {{ repair.issuesAfter }} 条
            </template>
            <template v-else>初稿即通过事实一致性与程序自检，无需自动改写</template>
          </p>
        </div>

        <div v-if="view.events.length" class="timeline">
          <div
            v-for="(event, i) in view.events" :key="i" class="timeline-item"
            :class="{ 'tl-verify': event.node === 'verify', 'tl-revise': event.node === 'revise' }"
          >
            <span class="timeline-dot"></span>
            <div class="tl-head">
              <strong>{{ event.label }}</strong>
              <span v-if="event.node === 'verify'" class="tl-tag" :class="event.round ? 'recheck' : 'initial'">
                {{ event.round ? '第 ' + event.round + ' 轮复检' : '初稿初审' }}
              </span>
              <span v-else-if="event.node === 'revise'" class="tl-tag fix">
                自检修复{{ event.focus ? ' · ' + event.focus : '' }}
              </span>
            </div>
            <small>{{ event.summary }}</small>
            <div v-if="event.node === 'verify'" class="tl-detail">
              <span class="tl-score">质量分 <b>{{ event.score ?? '—' }}</b>/100</span>
              <span v-if="event.score_delta != null" class="tl-delta" :class="deltaClass(event.score_delta)">{{ signed(event.score_delta) }}</span>
              <span class="tl-issues">发现 {{ issuesOf(event) }} 条意见</span>
              <div v-if="checkChips(event).length" class="tl-check">
                <span class="tlc-label">程序自检</span>
                <span v-for="(chip, j) in checkChips(event)" :key="j" :class="{ bad: chip.bad }">{{ chip.text }}</span>
              </div>
            </div>
            <div v-else-if="event.node === 'revise' && event.fixes?.length" class="tl-fixes">
              <div v-for="(fix, j) in event.fixes" :key="j">· {{ fix }}</div>
            </div>
          </div>
        </div>
        <div v-else class="mini-empty">
          <strong>还没有生成轨迹</strong>
          <span>{{ emptyText.trace }}</span>
        </div>
        <div v-if="generating" class="running">正在调用 {{ modelName || '模型' }} …</div>
      </div>

      <div v-show="insightTab === 'verify'">
        <!-- 质量评分概览 -->
        <div v-if="view.score != null || dimensionRows.length" class="quality-card" :class="scoreColor">
          <div class="quality-score">
            <span class="score-num">{{ view.score ?? '—' }}</span>
            <span class="score-max">/100</span>
            <span class="score-tag">{{ scoreLabel }}</span>
            <span v-if="verdictMeta" class="score-verdict" :class="verdictMeta.cls">{{ verdictMeta.label }}</span>
          </div>
          <div class="quality-dims">
            <div v-for="dim in dimensionRows" :key="dim.key" class="dim-row">
              <span class="dim-label">{{ dim.label }}</span>
              <span class="dim-bar"><span class="dim-fill" :style="{ width: (dim.value / 5 * 100) + '%' }"></span></span>
              <span class="dim-val">{{ dim.value }}/5</span>
            </div>
          </div>
        </div>
        <p v-if="view.score != null || dimensionRows.length" class="quality-note">
          总分由六维评分等权换算（六维平均 × 20），与下方各维度一致；存在事实安全硬错误时封顶 70 分。
        </p>

        <!-- 事实校验页也能看到同一条自检修复分数曲线 -->
        <div v-if="repair && repair.rounds" class="quality-progress">
          <span class="qp-label">自检修复</span>
          <span>{{ repair.userDriven ? '修订前' : '初稿' }} <b>{{ repair.initial ?? '—' }}</b></span>
          <span class="qp-arrow">→</span>
          <span>修复 {{ repair.rounds }} 轮后 <b>{{ repair.final ?? '—' }}</b></span>
          <em :class="deltaClass(repair.delta)">{{ signed(repair.delta) }} 分</em>
        </div>

        <div v-if="view.wordCount != null" class="selfcheck">
          <span class="sc-label">确定性自检</span>
          <span class="sc-item">约 <b>{{ view.wordCount }}</b> 词<span v-if="view.wordLimit != null">（目标 {{ view.wordLimit }}）</span></span>
          <span class="sc-item" :class="{ warn: (view.placeholderCount ?? 0) > 3 }">
            <b>{{ view.placeholderCount ?? 0 }}</b> 个待确认占位符
          </span>
          <small class="hint">篇幅与占位符由程序直接核对，不依赖模型判断。</small>
        </div>

        <div v-if="knowledgeSources.length" class="kb-sources">
          <header>已引用项目官方资料 · {{ knowledgeSources.length }} 份</header>
          <ul>
            <li v-for="(src, i) in knowledgeSources" :key="i">
              <template v-if="src.url"><a :href="src.url" target="_blank" rel="noopener">{{ src.school }} · {{ src.program }}</a></template>
              <template v-else>{{ src.school }} · {{ src.program }}</template>
              <small> · {{ src.field }}</small>
            </li>
          </ul>
        </div>
        <div v-else-if="view.knowledge && view.knowledge.note" class="kb-note">{{ view.knowledge.note }}</div>

        <div v-if="view.issues.length" class="issues">
          <header>待修订意见 · {{ view.issues.length }} 条<span v-if="hardCount"> · 其中 {{ hardCount }} 条事实风险需优先处理</span></header>
          <div v-for="(issue, i) in view.issues" :key="i" class="issue">
            <span class="tag" :class="issue.type">{{ issue.type }}</span>
            <p>{{ issue.reason }}</p>
            <small>「{{ issue.quote }}」→ {{ issue.fix }}</small>
          </div>
          <button v-if="live" class="btn small full" @click="emit('go', 'documents')">逐项给建议并重新生成</button>
        </div>
        <div v-if="view.warnings.length" class="warnings">
          <div v-for="(warning, i) in view.warnings" :key="i">⚠ {{ warning }}</div>
        </div>
        <div v-if="view.numericWarnings.length" class="warnings">
          <div v-for="(warning, i) in view.numericWarnings" :key="'n' + i">№ {{ warning }}</div>
          <small class="hint">以上数字在最新一轮复检中仍未在事实清单里找到对应。</small>
        </div>
        <div v-if="!view.score && !dimensionRows.length && !view.issues.length && !view.warnings.length && !view.numericWarnings.length && !knowledgeSources.length && !(view.knowledge && view.knowledge.note)" class="mini-empty">
          <strong>暂无校验意见</strong>
          <span>{{ emptyText.verify }}</span>
        </div>
      </div>

      <div v-show="insightTab === 'outline'">
        <div v-if="view.outline.length" class="outline-list">
          <div v-for="(section, i) in view.outline" :key="i" class="outline-item">
            <span class="outline-index">{{ String(i + 1).padStart(2, '0') }}</span>
            <div><strong>{{ section.title }}</strong><p>{{ section.goal }}</p>
              <small v-if="section.evidence_ids && section.evidence_ids.length">证据：{{ section.evidence_ids.join(', ') }}</small>
            </div>
          </div>
        </div>
        <div v-else class="mini-empty"><strong>还没有大纲</strong><span>{{ emptyText.outline }}</span></div>
      </div>
    </div>
  </section>
</template>
