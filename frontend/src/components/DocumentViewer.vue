<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { marked } from 'marked'
import DocumentInsights from './DocumentInsights.vue'
import type { DocumentDetail, Issue, RegenPayload } from '../types'
import { regenPanelRequest } from '../utils/regenPanel'

const props = defineProps<{
  document: DocumentDetail | null
  issues: Issue[]
  outline: any[]
  warnings: string[]
  regenerating: boolean
  regenStage: string
}>()
const emit = defineEmits<{
  save: [string]
  remove: [string]
  regenerate: [payload: RegenPayload]
}>()

const editing = ref(false)
const draft = ref('')
const selectedVersion = ref('')
// 当前正文对应的版本名（v1…v{current}），版本选择框里不再单列「当前」选项，
// 因为当前正文 v{current} 本就已在版本列表中。
const currentVersionName = computed(() => 'v' + (props.document?.meta.version ?? 1))
// 逐项审核建议：key 为待核项序号，值是该条的用户修改意见。
const suggestions = reactive<Record<number, string>>({})
const overallFeedback = ref('')
// 审核建议卡默认折叠：打开文书时只保留底部一条标题栏，把版面留给正文。
// 有待核项也不自动展开——工具栏的「审核建议 · N 项待核」与标题栏都可手动展开。
const regenOpen = ref(false)

function resetFeedback() {
  for (const key of Object.keys(suggestions)) delete suggestions[Number(key)]
  overallFeedback.value = ''
}

watch(
  () => `${props.document?.meta.id ?? ''}:${props.document?.meta.version ?? 0}`,
  () => {
    if (!props.document) return
    editing.value = false
    selectedVersion.value = currentVersionName.value
    resetFeedback()
    // 生成过程中新版本落库不打断进度展示；其余情况一律回到折叠态。
    regenOpen.value = props.regenerating
  },
)
// 校验意见变化（如重新生成后）时清空旧建议，避免序号错配。
watch(() => props.issues.map(issue => issue.quote + issue.type).join('|'), () => resetFeedback())
// 只有「开始按建议重新生成」才自动展开以显示进度；结束后保留用户当前的展开/折叠状态。
watch(() => props.regenerating, (busy) => {
  if (busy) regenOpen.value = true
})
// 来自洞察区「逐项给建议并重新生成」的显式展开请求，消费一次后清零。
// immediate 保证生成中查看器尚未挂载时发出的请求，在挂载后仍能生效。
watch(regenPanelRequest, (pending) => {
  if (pending <= 0) return
  regenOpen.value = true
  regenPanelRequest.value = 0
}, { immediate: true })

const displayMarkdown = computed(() => {
  const doc = props.document
  if (!doc) return ''
  return doc.versions.find(v => v.name === selectedVersion.value)?.markdown || doc.markdown
})

// 校验结论三态：事实风险 / 建议复核 / 已核验。旧文档没有 verdict 时回退到 passed_verification。
const critique = computed(() => props.document?.trace?.critique || null)
const verdictMeta = computed(() => {
  const level = critique.value?.verdict
  if (level === 'factual_risk') return { label: '事实风险', cls: 'bad' }
  if (level === 'needs_review') return { label: '建议复核', cls: 'warn' }
  if (level === 'passed') return { label: '已核验', cls: 'ok' }
  return props.document?.meta.passed_verification
    ? { label: '已核验', cls: 'ok' }
    : { label: '待核对', cls: 'warn' }
})
const scoreValue = computed(() => critique.value?.score ?? null)
// 上一轮用户逐项裁决过的条数：让用户知道自己的澄清已被带上。
const lastResolvedCount = computed(() => {
  const list = props.document?.trace?.issue_feedback || []
  return list.filter((x: any) => String(x?.suggestion || '').trim()).length
})
const traceOpen = ref(false)
// 正文下方的洞察区（生成轨迹 / 事实校验 / 段落大纲）：toolbar 分数入口快速滚动到这里。
const insightsRef = ref<HTMLElement | null>(null)
function scrollToInsights() {
  insightsRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function sanitize(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/\son\w+\s*=\s*["'][^"']*["']/gi, '')
    .replace(/javascript:/gi, '')
}

const rendered = computed(() => sanitize(String(marked.parse(displayMarkdown.value, { breaks: true }))))

// 中英对照视图：解析 markdown 中的 `> 译：` 翻译块，把每个英文块与其译块配对成左右双栏。
const bilingualView = ref(false)
watch(
  () => `${props.document?.meta.id ?? ''}:${props.document?.meta.version ?? 0}`,
  () => { bilingualView.value = !!props.document?.meta.bilingual },
  { immediate: true },
)

function _stripZhBlocks(md: string): string {
  const out: string[] = []
  let skipping = false
  for (const line of md.split('\n')) {
    if (/^\s*>\s*译[:：]/.test(line)) { skipping = true; continue }
    if (skipping && /^\s*>/.test(line)) continue
    skipping = false
    out.push(line)
  }
  return out.join('\n')
}

// 中英对照：把正文切成「英文块 / 译块」，逐块配对。
// 译块以 `> 译：` 起始，可带多行 `> ` 续行。这里按行扫描而不是单纯按空行切分：
// 模型偶尔把译块紧贴英文行、或与下一段英文挤在同一块，按空行切会让该段右栏缺失、
// 中文被当成引用渲染进英文栏。无论前后有没有空行，译块都拆成独立块。
function _splitBilingualBlocks(md: string): string[] {
  const blocks: string[] = []
  let buf: string[] = []
  let inZh = false
  const flush = () => {
    const text = buf.join('\n').trim()
    if (text) blocks.push(text)
    buf = []
  }
  for (const line of md.replace(/\r\n/g, '\n').split('\n')) {
    const zhStart = /^\s*>\s*译[:：]/.test(line)
    const quote = /^\s*>/.test(line)
    if (zhStart) {
      flush()
      inZh = true
      buf.push(line)
    } else if (inZh && quote) {
      buf.push(line)
    } else {
      if (inZh) { flush(); inZh = false }
      if (!line.trim()) flush()
      else buf.push(line)
    }
  }
  flush()
  return blocks
}

function _cleanZh(block: string): string {
  return block
    .replace(/^\s*>\s*译[:：]\s?/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .trim()
}

// 规则：仅有「英文块紧跟其译块」时才渲染成左右一对；标题 / 列表等未翻译结构、
// 或模型漏译的段落，一律整宽渲染（不进双栏，避免空白右栏）；译块只配对紧邻的
// 上一个英文块，从根本上杜绝左右错位。
function _buildBilingual(md: string): string {
  const blocks = _splitBilingualBlocks(md)
  const out: string[] = []
  let pendingEn = ''
  const renderFull = (enText: string) =>
    `<div class="bi-full">${sanitize(String(marked.parse(enText, { breaks: true })))}</div>`
  const renderPair = (enText: string, zhText: string) => {
    // 小标题型对照行单独标记，CSS 里让左右两栏的标题视觉对齐。
    const cls = /^\s*#{1,6}\s/.test(enText) ? 'bi-pair bi-pair-heading' : 'bi-pair'
    return `<div class="${cls}"><div class="bi-en">${sanitize(String(marked.parse(enText, { breaks: true })))}</div>` +
      `<div class="bi-zh">${sanitize(String(marked.parse(zhText, { breaks: true })))}</div></div>`
  }
  const isZh = (b: string) => /^\s*>\s*译[:：]/.test(b)
  for (const block of blocks) {
    if (isZh(block)) {
      const zh = _cleanZh(block)
      if (pendingEn) {
        out.push(renderPair(pendingEn, zh))
        pendingEn = ''
      } else {
        // 落单译块（前面无可配对英文）：整宽显示中文，避免凭空成对照。
        out.push(`<div class="bi-full bi-full-zh">${sanitize(String(marked.parse(zh, { breaks: true })))}</div>`)
      }
    } else {
      if (pendingEn) out.push(renderFull(pendingEn))
      pendingEn = block
    }
  }
  if (pendingEn) out.push(renderFull(pendingEn))
  return out.join('\n')
}

// 纯英文视图：剥离译块后渲染（用于非对照模式与单语文档）。
const monoHtml = computed(() =>
  sanitize(String(marked.parse(_stripZhBlocks(displayMarkdown.value), { breaks: true }))),
)

// 最终正文 HTML：双语文档且开启对照时走双栏，否则走纯英文。
const viewHtml = computed(() => {
  if (props.document?.meta.bilingual && bilingualView.value) return _buildBilingual(displayMarkdown.value)
  return monoHtml.value
})

const advisedCount = computed(() =>
  props.issues.filter((_, i) => (suggestions[i] || '').trim()).length,
)
const canRegenerate = computed(() =>
  !props.regenerating && (advisedCount.value > 0 || !!overallFeedback.value.trim()),
)

/* ---------- 审核建议面板高度：拖动顶部手柄调整，按浏览器记住 ---------- */
const REGEN_HEIGHT_KEY = 'applicraft.regen-panel-height.v1'
const REGEN_MIN_HEIGHT = 160
const REGEN_DEFAULT_HEIGHT = 320

function clampRegenHeight(px: number): number {
  // 上限与 CSS 的 max-height 对齐：桌面 72vh，窄屏 60vh，避免状态值和实际高度不一致。
  const ratio = window.innerWidth <= 760 ? 0.6 : 0.72
  const upper = Math.max(REGEN_MIN_HEIGHT + 40, Math.round(window.innerHeight * ratio))
  return Math.min(upper, Math.max(REGEN_MIN_HEIGHT, Math.round(px)))
}
function readRegenHeight(): number {
  try {
    const saved = Number(window.localStorage.getItem(REGEN_HEIGHT_KEY))
    if (Number.isFinite(saved) && saved > 0) return clampRegenHeight(saved)
  } catch { /* 隐私模式下 localStorage 不可用，回退到默认高度 */ }
  return clampRegenHeight(REGEN_DEFAULT_HEIGHT)
}
const regenHeight = ref(readRegenHeight())
const regenResizing = ref(false)
let stopResize: (() => void) | null = null

function persistRegenHeight() {
  try { window.localStorage.setItem(REGEN_HEIGHT_KEY, String(regenHeight.value)) } catch { /* ignore */ }
}
function setRegenHeight(px: number) {
  regenHeight.value = clampRegenHeight(px)
}
/** 手柄贴在面板上沿：向上拖加高、向下拖压低。Pointer Events 同时覆盖鼠标与触屏。 */
function onRegenResizeStart(event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  // 鼠标端不 preventDefault：那会连带阻止 click/dblclick，双击恢复默认就收不到事件。
  // 拖拽中的文本选择由 body.regen-resizing 处理，触屏滚动由 touch-action:none 处理。
  if (event.pointerType !== 'mouse') event.preventDefault()
  const startY = event.clientY
  const startHeight = regenHeight.value
  regenResizing.value = true
  document.body.classList.add('regen-resizing')
  const onMove = (e: PointerEvent) => setRegenHeight(startHeight + (startY - e.clientY))
  const onEnd = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onEnd)
    window.removeEventListener('pointercancel', onEnd)
    document.body.classList.remove('regen-resizing')
    regenResizing.value = false
    stopResize = null
    persistRegenHeight()
  }
  stopResize = onEnd
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onEnd)
  window.addEventListener('pointercancel', onEnd)
}
/** 键盘可达：↑/↓ 每次 20px（Shift 加速到 60px），Home 或双击手柄恢复默认。 */
function onRegenResizeKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown' && event.key !== 'Home') return
  event.preventDefault()
  const step = event.shiftKey ? 60 : 20
  setRegenHeight(
    event.key === 'Home'
      ? REGEN_DEFAULT_HEIGHT
      : regenHeight.value + (event.key === 'ArrowUp' ? step : -step),
  )
  persistRegenHeight()
}
function resetRegenHeight() {
  setRegenHeight(REGEN_DEFAULT_HEIGHT)
  persistRegenHeight()
}
function onWindowResize() { setRegenHeight(regenHeight.value) }
onMounted(() => window.addEventListener('resize', onWindowResize))
onUnmounted(() => {
  window.removeEventListener('resize', onWindowResize)
  stopResize?.()
})

function startEdit() {
  if (selectedVersion.value !== currentVersionName.value) selectedVersion.value = currentVersionName.value
  draft.value = displayMarkdown.value
  editing.value = true
  regenOpen.value = false
}
/** 工具栏入口：展开/收起审核建议面板（固定在底部，与正文独立滚动，无需滚动定位）。 */
function toggleRegen() {
  regenOpen.value = !regenOpen.value
}
function save() {
  emit('save', draft.value)
  editing.value = false
}
function copy() {
  navigator.clipboard?.writeText(displayMarkdown.value)
}
function download(format: 'md' | 'docx') {
  if (!props.document) return
  // 版本选择框只列 v1、v2…，selectedVersion 恒为真实版本名（含当前正文对应版本）。
  window.location.href = `/api/documents/${props.document.meta.id}/download?format=${format}&version=${selectedVersion.value}`
}
function submitRegenerate() {
  if (!canRegenerate.value) return
  const issueFeedback = props.issues
    .map((_, index) => ({ index, suggestion: (suggestions[index] || '').trim() }))
    .filter(item => item.suggestion)
  emit('regenerate', { feedback: overallFeedback.value.trim(), issueFeedback })
}
</script>

<template>
  <template v-if="document">
    <div class="viewer-toolbar">
      <button v-if="!editing" class="btn small" @click="startEdit">编辑</button>
      <template v-else>
        <button class="btn small primary" @click="save">保存为新版本</button>
        <button class="btn small" @click="editing = false">取消</button>
      </template>
      <button class="btn small" @click="copy">复制</button>
      <button class="btn small" @click="download('md')">.md</button>
      <button class="btn small" @click="download('docx')">.docx</button>
      <button
        v-if="!editing" class="btn small" :class="{ 'regen-entry': issues.length, active: regenOpen }"
        :aria-expanded="regenOpen" :title="regenOpen ? '收起审核建议面板' : '逐项填写修改意见，按建议重新生成'"
        @click="toggleRegen"
      >
        审核建议{{ issues.length ? ` · ${issues.length} 项待核` : '' }}
      </button>
      <button
        v-if="!editing" class="btn small" title="查看这份文书的生成轨迹、事实校验与段落大纲"
        @click="scrollToInsights"
      >生成轨迹</button>
      <button
        v-if="document.meta.bilingual" class="btn small" :class="{ active: bilingualView }"
        @click="bilingualView = !bilingualView"
        :title="bilingualView ? '当前为左右双栏对照，点击只看英文' : '点击开启中英对照'"
      >
        {{ bilingualView ? '只看英文' : '中英对照' }}
      </button>
      <select v-model="selectedVersion">
        <option v-for="version in document.versions" :key="version.name" :value="version.name">{{ version.name }}</option>
      </select>
      <span class="spacer"></span>
      <button
        v-if="scoreValue != null" class="badge score-badge" type="button"
        title="查看这份文书的生成轨迹与质量评分" @click="scrollToInsights"
      >{{ scoreValue }} 分</button>
      <span class="badge" :class="verdictMeta.cls">{{ verdictMeta.label }}</span>
      <button class="link danger" @click="emit('remove', document.meta.id)">删除</button>
    </div>

    <div class="doc-scroll">
      <textarea v-if="editing" v-model="draft" class="editor" spellcheck="false"></textarea>
      <article v-else class="prose" :class="{ 'bi-grid': document.meta.bilingual && bilingualView }" v-html="viewHtml"></article>

      <!-- 该文书自己的生成轨迹 / 事实校验 / 段落大纲：数据全部从 document.trace 派生，
           与生成页的实时状态解耦，打开另一份文书也不会串台。 -->
      <div v-if="!editing" ref="insightsRef" class="doc-insights">
        <DocumentInsights :document="document" />
      </div>

      <details
        v-if="!editing" class="trace" :open="traceOpen"
        @toggle="(e: Event) => traceOpen = (e.target as HTMLDetailsElement).open"
      >
        <summary>引用资料与元信息</summary>
        <div class="trace-body">
          <div v-if="document.trace.knowledge && document.trace.knowledge.sources && document.trace.knowledge.sources.length">
            <h4>引用项目官方资料 · {{ document.trace.knowledge.sources.length }} 份</h4>
            <ul class="kb-mini">
              <li v-for="(src, i) in document.trace.knowledge.sources" :key="i">
                <template v-if="src.url"><a :href="src.url" target="_blank" rel="noopener">{{ src.school }} · {{ src.program }}</a></template>
                <template v-else>{{ src.school }} · {{ src.program }}</template>
                <small> · {{ src.field }}</small>
              </li>
            </ul>
          </div>
          <div v-if="document.trace.references && document.trace.references.length">
            <h4>使用的参考文档 · {{ document.trace.references.filter((r: any) => r.included !== false).length }} 份</h4>
            <ul class="kb-mini">
              <li v-for="(ref, i) in document.trace.references" :key="i">
                {{ ref.name || ref.filename || ref.id }}
                <small v-if="ref.included === false"> · 未注入（超字数预算）</small>
                <small v-else-if="ref.missing"> · 已删除</small>
              </li>
            </ul>
          </div>
          <div v-if="document.trace.skills && document.trace.skills.length">
            <h4>启用的写作技能 · {{ document.trace.skills.filter((s: any) => s.included !== false).length }} 个</h4>
            <ul class="kb-mini">
              <li v-for="(skill, i) in document.trace.skills" :key="i">
                {{ skill.name || skill.id }}
                <small v-if="skill.missing"> · 已删除</small>
                <small v-else-if="skill.included === false"> · 未注入（超字数预算）</small>
                <small v-else-if="skill.truncated"> · 内容按预算截断</small>
                <small v-else> · {{ skill.origin === 'user' ? '我导入的' : '系统内置' }}</small>
              </li>
            </ul>
          </div>
          <div v-if="warnings.length">
            <h4>需要人工确认</h4>
            <ul><li v-for="(warning, i) in warnings" :key="i">{{ warning }}</li></ul>
          </div>
          <div v-if="(document.trace.critique?.numeric_warnings || []).length">
            <h4>数字待核对（最后一轮复检）</h4>
            <ul><li v-for="(warning, i) in document.trace.critique!.numeric_warnings" :key="'n' + i">{{ warning }}</li></ul>
          </div>
          <div>
            <h4>元信息</h4>
            模型 {{ document.trace.model || document.meta.model }} · 语言 {{ document.meta.language }} ·
            约 {{ document.meta.word_count }} 词 · 修订 {{ document.trace.revision_count || 0 }} 次 ·
            共 {{ document.versions.length }} 个版本
          </div>
        </div>
      </details>
    </div>

    <!-- 逐项审核建议：独立于正文滚动区的底部面板，默认折叠；展开后上沿可拖动调高，内部独立滚动 -->
    <details
      v-if="!editing" class="regen-card" :class="{ busy: regenerating, resizing: regenResizing }"
      :open="regenOpen" @toggle="(e: Event) => regenOpen = (e.target as HTMLDetailsElement).open"
    >
      <summary>
        <strong>审核建议与重新生成</strong>
        <span class="hint" v-if="!regenerating">
          {{ issues.length ? `${issues.length} 项待核 · 已填 ${advisedCount} 项` : '无待核项 · 可填写整体修改要求后重新生成' }}<template v-if="lastResolvedCount"> · 上轮已裁决 {{ lastResolvedCount }} 项</template>
        </span>
        <span class="hint" v-else>{{ regenStage || '正在调用模型…' }}</span>
        <span class="regen-size-tools">
          <span class="hint">拖动上沿可调高度</span>
          <button class="regen-size-reset" type="button" title="恢复默认高度" @click.stop.prevent="resetRegenHeight">恢复默认</button>
        </span>
      </summary>
      <div
        class="regen-resizer" role="separator" aria-orientation="horizontal" tabindex="0"
        aria-label="拖动调整审核建议面板高度，双击恢复默认" :aria-valuenow="regenHeight"
        :aria-valuemin="REGEN_MIN_HEIGHT" title="上下拖动调整高度 · 双击恢复默认"
        @pointerdown="onRegenResizeStart" @keydown="onRegenResizeKey" @dblclick="resetRegenHeight"
      ><span></span></div>
      <div class="regen-card-inner" :style="{ height: regenHeight + 'px' }">
        <div v-if="issues.length" class="issue-advisories">
          <div v-for="(issue, i) in issues" :key="i" class="issue-advisory">
            <div class="issue-advisory-head">
              <span class="issue-no">{{ i + 1 }}</span>
              <span class="tag" :class="issue.type">{{ issue.type }}</span>
              <p>{{ issue.reason }}</p>
            </div>
            <small v-if="issue.quote || issue.fix">「{{ issue.quote }}」→ {{ issue.fix }}</small>
            <input
              v-model="suggestions[i]" :disabled="regenerating"
              :placeholder="`第 ${i + 1} 项的审核意见，例如：保留原意，只把「显著提升」换成具体指标`"
            />
          </div>
        </div>

        <label class="field overall-field">
          <span>{{ issues.length ? '整体补充说明（可选）' : '整体修改要求' }}</span>
          <textarea
            v-model="overallFeedback" rows="2" :disabled="regenerating"
            placeholder="跨条目的要求，例如：全文语气更克制；结尾的职业规划与 MSc 课程挂钩"
          ></textarea>
        </label>

        <div class="regen-actions">
          <button class="btn small primary" :disabled="!canRegenerate" @click="submitRegenerate">
            {{ regenerating ? '重新生成中…' : '按审核建议重新生成' }}
          </button>
          <span class="hint">
            保存为 v{{ document.meta.version + 1 }} 新版本 · 只用已锁定事实
          </span>
        </div>
      </div>
    </details>
  </template>

  <div v-else class="empty-state">
    <span class="empty-icon">▤</span>
    <strong>尚未选择文书</strong>
    <span>从左侧列表打开一份材料，或去生成页创建第一份</span>
  </div>
</template>
