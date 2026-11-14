<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { DIMENSION_LABELS } from '../types'
import { shortImportedAt } from '../utils/format'
import type {
  AppConfig, ApplicantProfile, DocType, GeneratePayload, KnowledgeRef,
  Language, NodeEvent, QuotaInfo, ReferenceDoc, SkillInfo, TabKey, Issue, UserLLMConfig,
} from '../types'

const props = defineProps<{
  profile: ApplicantProfile
  profileId: string
  config: AppConfig | null
  myLlm: UserLLMConfig | null
  quota: QuotaInfo | null
  generating: boolean
  planning: boolean
  events: NodeEvent[]
  issues: Issue[]
  outline: any[]
  warnings: string[]
  numericWarnings: string[]
  score: number | null
  dimensions: Record<string, number> | null
  verdict: string | null
  knowledge: KnowledgeRef | null
  references: ReferenceDoc[]
  selectedReferenceIds: string[]
  skills: SkillInfo[]
  selectedSkillIds: string[]
  wordCount: number | null
  placeholderCount: number | null
  /** 本地部署版（免登录、单用户）为 true：计费口径显示为本地 API Key。 */
  standalone: boolean
}>()
const emit = defineEmits<{
  generate: [payload: GeneratePayload]
  go: [tab: TabKey]
  'update:selectedReferenceIds': [ids: string[]]
  'update:selectedSkillIds': [ids: string[]]
  refreshReferences: []
}>()

const selected = ref<string[]>([...props.selectedReferenceIds])
// 父→子同步带内容去重：App.vue 可能赋同内容的新数组，逐项比较避免无谓重置。
watch(() => props.selectedReferenceIds, (v) => {
  if (v.join('\u0000') !== selected.value.join('\u0000')) selected.value = [...v]
})
function toggleReference(id: string) {
  const idx = selected.value.indexOf(id)
  if (idx === -1) selected.value.push(id)
  else selected.value.splice(idx, 1)
  emit('update:selectedReferenceIds', [...selected.value])
}
// 注意：不能加 watch(selected, emit) 之类的回传——父→子 watch 与子→父 emit 会形成
// 无限递归更新（每次都是新数组引用），页面直接卡死；子→父只在用户操作处显式 emit。

const selectedSkills = ref<string[]>([...props.selectedSkillIds])
watch(() => props.selectedSkillIds, (v) => {
  if (v.join('\u0000') !== selectedSkills.value.join('\u0000')) selectedSkills.value = [...v]
})
function toggleSkill(id: string) {
  const idx = selectedSkills.value.indexOf(id)
  if (idx === -1) selectedSkills.value.push(id)
  else selectedSkills.value.splice(idx, 1)
  emit('update:selectedSkillIds', [...selectedSkills.value])
}

const docTypes: { key: DocType; label: string; hint: string }[] = [
  { key: 'ps', label: '个人陈述 PS / SOP', hint: '围绕目标项目展开' },
  { key: 'recommendation', label: '推荐信', hint: '以推荐人视角书写' },
  { key: 'cv', label: '学术 CV', hint: '结构化呈现事实清单' },
]
const docType = ref<DocType>('ps')
const language = ref<Language>('en')
// 中英对照：仅英文文书可用；默认开启，方便中文母语申请人逐段核对 AI 英文。
const bilingual = ref(true)
const wordLimit = ref(900)
// 中文文书无需对照；切到中文时强制关闭，切回英文恢复默认开启。
watch(language, (value) => {
  if (value === 'zh') bilingual.value = false
  else bilingual.value = true
})
const tone = ref('professional')
// 默认选中档案里的第一项（与后端 _pick 的 fallback 语义一致，避免请求里出现歧义的 null）。
const targetProgramId = ref(props.profile.target_programs[0]?.id || '')
const recommenderId = ref(props.profile.recommenders[0]?.id || '')
const extraInstructions = ref('')
const emphasis = ref<string[]>([])
const emphasisInput = ref('')

type InsightKey = 'trace' | 'verify' | 'outline'
const insightTab = ref<InsightKey>('trace')
const insightTabs = computed(() => [
  { key: 'trace' as const, label: '生成轨迹', count: props.events.length },
  { key: 'verify' as const, label: '事实校验', count: props.issues.length },
  { key: 'outline' as const, label: '段落大纲', count: props.outline.length },
])
// 有任何产出（轨迹/校验/大纲）时展开面板；空闲时收起，页面保持简洁。
const hasOutput = computed(() => props.events.length > 0 || props.outline.length > 0 || props.score != null)
const insightOpen = ref(false)
watch(() => props.generating, (running) => {
  if (running) { insightTab.value = 'trace'; insightOpen.value = true }
})
watch(hasOutput, (v) => { if (v) insightOpen.value = true })

watch(docType, (value) => {
  wordLimit.value = value === 'recommendation' ? 550 : value === 'cv' ? 600 : 900
})

// 系统 Key 没配但用户填了自己的 Key 时同样可以生成：以「当前生效来源」为准。
const llmReady = computed(() =>
  props.myLlm ? props.myLlm.effective_source !== 'none' : !!props.config?.llm_configured,
)
const effectiveModel = computed(() =>
  props.myLlm?.effective_model || props.config?.llm_model || '模型',
)
// 普通账号用系统共享 Key 每天只有固定免费次数，用完后必须自己配 Key。
const billingUnlimited = computed(() => !!(props.myLlm?.unlimited ?? props.quota?.unlimited))
const freeLimit = computed(() =>
  props.myLlm?.system_key_daily_limit ?? props.quota?.system_key_limit
  ?? props.config?.system_key_daily_limit ?? 3,
)
const freeRemaining = computed(() =>
  props.myLlm?.system_key_remaining ?? props.quota?.system_key_remaining ?? null,
)
const freeExhausted = computed(() =>
  !billingUnlimited.value && freeRemaining.value !== null && freeRemaining.value <= 0,
)
const billingLabel = computed(() => {
  if (props.standalone) return '本地 API Key · 不限次数'
  if (props.myLlm?.is_admin || props.quota?.source === 'admin') return '系统共享 Key · 管理员不限次数'
  if (props.myLlm?.effective_source === 'personal') return '你的 Key，不占系统额度'
  if (billingUnlimited.value) return '不限次数'
  return `系统共享 Key · 今日剩 ${freeRemaining.value ?? freeLimit.value} 次`
})
const canGenerate = computed(() =>
  !!props.profileId && llmReady.value && !props.generating && !props.planning && !freeExhausted.value,
)
const buttonLabel = computed(() => {
  const names: Record<DocType, string> = { ps: '个人陈述', recommendation: '推荐信', cv: '学术 CV' }
  return `生成${names[docType.value]}`
})
const runLabel = computed(() => {
  if (props.planning) return '规划大纲中…'
  if (props.generating) return '生成中…'
  return buttonLabel.value
})
const blockReason = computed(() => {
  if (!props.profileId) return '请先创建或选择一个申请人档案'
  if (!llmReady.value) return '还没有可用的 API Key，请到「设置 → 我的大模型 API」配置'
  if (freeExhausted.value) return `今日 ${freeLimit.value} 次系统免费额度已用完，配置自己的 Key 后可继续生成`
  if (props.generating) return '正在生成中…'
  return ''
})

const dimensionRows = computed(() =>
  Object.entries(props.dimensions || {}).map(([key, value]) => ({
    key,
    label: DIMENSION_LABELS[key] || key,
    value: Math.max(0, Math.min(5, Number(value) || 0)),
  })),
)
const scoreColor = computed(() => {
  const s = props.score
  if (s == null) return 'neutral'
  if (s >= 85) return 'good'
  if (s >= 70) return 'warn'
  return 'bad'
})
const scoreLabel = computed(() => {
  const s = props.score
  if (s == null) return '未评分'
  if (s >= 85) return '优秀'
  if (s >= 70) return '良好'
  return '需修改'
})
// 生成阶段进度：把 SSE 节点映射成固定步骤，避免轨迹只是一条不断追加的日志。
const STAGES = [
  { key: 'intake', label: '素材' },
  { key: 'outline', label: '大纲' },
  { key: 'draft', label: '初稿' },
  { key: 'verify', label: '校验' },
  { key: 'revise', label: '修订' },
  { key: 'finalize', label: '定稿' },
]
const NODE_TO_STAGE: Record<string, number> = {
  intake: 0, outline: 1, draft: 2, cv_render: 2, verify: 3, revise: 4, finalize: 5,
}
const stageIndex = computed(() => {
  let idx = -1
  for (const event of props.events) {
    const i = NODE_TO_STAGE[event.node]
    if (i != null) idx = Math.max(idx, i)
  }
  return idx
})
const stageDone = computed(() => stageIndex.value >= STAGES.length - 1)
const verdictMeta = computed(() => {
  switch (props.verdict) {
    case 'factual_risk': return { label: '事实风险', cls: 'bad' }
    case 'needs_review': return { label: '建议复核', cls: 'warn' }
    case 'passed': return { label: '已核验', cls: 'good' }
    default: return null
  }
})
const FATAL_TYPES = new Set(['fabrication', 'contradiction', 'unsupported', 'program_fit'])
const hardCount = computed(() => props.issues.filter(i => FATAL_TYPES.has(i.type)).length)
const knowledgeSources = computed(() => props.knowledge?.sources || [])

function addEmphasis() {
  const value = emphasisInput.value.trim()
  if (value && !emphasis.value.includes(value)) emphasis.value.push(value)
  emphasisInput.value = ''
}

function submit() {
  if (!canGenerate.value) return
  emit('generate', {
    profile_id: props.profileId,
    doc_type: docType.value,
    target_program_id: docType.value === 'recommendation' ? null : (targetProgramId.value || null),
    recommender_id: docType.value === 'recommendation' ? (recommenderId.value || null) : null,
    language: language.value,
    bilingual: language.value === 'en' ? bilingual.value : false,
    word_limit: Number(wordLimit.value) || 900,
    tone: tone.value,
    emphasis: [...emphasis.value],
    extra_instructions: extraInstructions.value.trim(),
    reference_doc_ids: [...selected.value],
    skill_ids: [...selectedSkills.value],
  })
}
</script>

<template>
  <div class="generate-layout">
    <!-- 生成参数：单栏流程式 -->
    <section class="card generate-form">
      <div class="card-head">
        <h2>文书类型</h2>
        <span class="hint">决定生成链路与事实选取</span>
      </div>
      <div class="doc-type-row">
        <button
          v-for="tab in docTypes" :key="tab.key" class="doc-type-card"
          :class="{ active: docType === tab.key }" @click="docType = tab.key"
        >
          <strong>{{ tab.label }}</strong>
          <span>{{ tab.hint }}</span>
        </button>
      </div>

      <div class="card-head section-divider">
        <h2>定制参数</h2>
        <button class="link" @click="emit('go', 'profile')">去改档案</button>
      </div>
      <div class="block">
        <div class="grid2">
          <label class="field" v-if="docType !== 'recommendation'">
            <span>目标项目（用于定制）</span>
            <select v-model="targetProgramId">
              <option value="">不指定 / 使用第一个项目</option>
              <option v-for="item in profile.target_programs" :key="item.id" :value="item.id">
                {{ item.university }} · {{ item.program }}
              </option>
            </select>
          </label>
          <label class="field" v-else>
            <span>推荐人（决定信件视角）</span>
            <select v-model="recommenderId">
              <option value="">不指定 / 使用第一位推荐人</option>
              <option v-for="item in profile.recommenders" :key="item.id" :value="item.id">
                {{ item.name }} · {{ item.title }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>语言</span>
            <select v-model="language"><option value="en">English</option><option value="zh">简体中文</option></select>
          </label>
          <label v-if="language === 'en'" class="bi-toggle-row" :class="{ 'is-on': bilingual }">
            <span class="bi-toggle-text">
              <span class="bi-toggle-title">中英对照</span>
              <span class="bi-toggle-desc">每段英文附中文翻译，便于逐段核对</span>
            </span>
            <input type="checkbox" v-model="bilingual" class="bi-toggle-input" />
            <span class="bi-toggle-switch" aria-hidden="true"></span>
          </label>
          <label class="field">
            <span>{{ docType === 'cv' ? '篇幅参考（词）' : '目标字数（词）' }}</span>
            <input v-model.number="wordLimit" type="number" min="150" max="3000" step="50" />
          </label>
          <label class="field">
            <span>语气</span>
            <select v-model="tone">
              <option value="professional">专业克制</option><option value="confident">自信直接</option>
              <option value="warm">温和有温度</option><option value="concise">精简凝练</option>
            </select>
          </label>
        </div>

        <div class="field">
          <span>强调点（回车添加）</span>
          <input v-model="emphasisInput" placeholder="例如：量化研究能力" @keydown.enter.prevent="addEmphasis" />
          <div v-if="emphasis.length" class="tag-row">
            <span v-for="tag in emphasis" :key="tag" class="tag removable" @click="emphasis.splice(emphasis.indexOf(tag), 1)">
              {{ tag }} ×
            </span>
          </div>
        </div>

        <label class="field">
          <span>额外指令（仅对本次生成生效）</span>
          <textarea v-model="extraInstructions" rows="3" placeholder="例如：不要提及实习经历；结尾需点明跨方向申请的原因" />
        </label>
      </div>

      <!-- 参考文档库：勾选本次生成要使用的上传材料 -->
      <div class="card-head section-divider">
        <h2>参考文档</h2>
        <button class="link" @click="emit('go', 'library')">去上传 / 查看</button>
      </div>
      <div class="block ref-block">
        <p v-if="!props.references.length" class="hint">
          尚未上传任何参考文档。前往「参考文档库」上传你的项目说明、研究陈述等材料，生成时可勾选使用。
        </p>
        <div v-else class="ref-list">
          <label v-for="doc in props.references" :key="doc.id" class="ref-item" :class="{ on: selected.includes(doc.id) }">
            <input type="checkbox" :checked="selected.includes(doc.id)" @change="toggleReference(doc.id)" />
            <span class="ref-name">{{ doc.name || doc.filename }}</span>
            <small class="ref-meta">
              {{ doc.ext.replace('.', '').toUpperCase() || 'FILE' }} · {{ doc.char_count }} 字 · 导入 {{ shortImportedAt(doc.uploaded_at) }}
            </small>
          </label>
          <p class="hint">已勾选 {{ selected.length }} 份；生成时其文本会作为补充背景注入，不与事实清单冲突。</p>
        </div>
      </div>

      <!-- Skill 市场：勾选本次生成启用的写作技能 -->
      <div class="card-head section-divider">
        <h2>写作技能</h2>
        <button class="link" @click="emit('go', 'skills')">去 Skill 市场</button>
      </div>
      <div class="block ref-block">
        <p v-if="!props.skills.length" class="hint">技能列表载入中，或前往「Skill 市场」查看内置写作技能。</p>
        <div v-else class="ref-list">
          <label v-for="skill in props.skills" :key="skill.id" class="ref-item" :class="{ on: selectedSkills.includes(skill.id) }">
            <input type="checkbox" :checked="selectedSkills.includes(skill.id)" @change="toggleSkill(skill.id)" />
            <span class="ref-name">{{ skill.name }}</span>
            <small class="ref-meta">
              {{ skill.origin === 'builtin' ? '系统内置' : '导入 ' + shortImportedAt(skill.imported_at) }} · {{ skill.category || '写作技能' }}
            </small>
          </label>
          <p class="hint">已启用 {{ selectedSkills.length }} 个技能；技能只约束写法，不会被当作申请人事实，事实清单与字数要求始终优先。</p>
        </div>
      </div>

      <div v-if="freeExhausted" class="quota-exhausted">
        <div>
          <b>今日 {{ freeLimit }} 次系统免费额度已用完</b>
          <p class="hint">
            填入自己的 API Key 后即可继续不限次数生成，费用由你的服务商账号承担；也可以明天再试。
          </p>
        </div>
        <button class="btn primary small" @click="$emit('go', 'settings')">去配置我的 Key</button>
      </div>

      <div class="generate-row">
        <button class="btn primary" :disabled="!canGenerate" @click="submit">
          {{ runLabel }}
        </button>
        <div v-if="blockReason" class="reason">{{ blockReason }}</div>
        <p class="hint">
          生成会先规划大纲供你确认，再起草正文；全程调用 {{ effectiveModel }}（{{ billingLabel }}），完成后自动打开文书库。
        </p>
      </div>
    </section>

    <!-- 轨迹 / 校验 / 大纲：空闲时收起，生成或查看结果时展开 -->
    <section v-if="insightOpen" class="card insight-panel">
      <div class="insight-tabs">
        <button
          v-for="tab in insightTabs" :key="tab.key" class="insight-tab"
          :class="{ active: insightTab === tab.key }" @click="insightTab = tab.key"
        >
          {{ tab.label }}<em v-if="tab.count">{{ tab.count }}</em>
        </button>
      </div>

      <div v-if="events.length" class="stage-track">
        <div
          v-for="(stage, i) in STAGES" :key="stage.key" class="stage"
          :class="{ done: i <= stageIndex, running: generating && i === stageIndex && !stageDone }"
        >
          <span class="stage-dot"></span><span class="stage-label">{{ stage.label }}</span>
        </div>
      </div>

      <div class="insight-body">
        <div v-show="insightTab === 'trace'">
          <div v-if="events.length" class="timeline">
            <div v-for="(event, i) in events" :key="i" class="timeline-item">
              <span class="timeline-dot"></span>
              <strong>{{ event.label }}</strong>
              <small>{{ event.summary }}</small>
            </div>
          </div>
          <div v-else class="mini-empty">
            <strong>还没有生成轨迹</strong>
            <span>点击「{{ buttonLabel }}」，这里会实时显示生成过程的每个节点</span>
          </div>
          <div v-if="generating" class="running">正在调用 {{ effectiveModel }} …</div>
        </div>

        <div v-show="insightTab === 'verify'">
          <!-- 质量评分概览 -->
          <div v-if="score != null || dimensionRows.length" class="quality-card" :class="scoreColor">
            <div class="quality-score">
              <span class="score-num">{{ score ?? '—' }}</span>
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
          <p v-if="score != null || dimensionRows.length" class="quality-note">
            总分由六维评分等权换算（六维平均 × 20），与下方各维度一致；存在事实安全硬错误时封顶 70 分。
          </p>

          <div v-if="wordCount != null" class="selfcheck">
            <span class="sc-label">确定性自检</span>
            <span class="sc-item">约 <b>{{ wordCount }}</b> 词（目标 {{ wordLimit }}）</span>
            <span class="sc-item" :class="{ warn: (placeholderCount ?? 0) > 3 }">
              <b>{{ placeholderCount ?? 0 }}</b> 个待确认占位符
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
          <div v-else-if="knowledge && knowledge.note" class="kb-note">{{ knowledge.note }}</div>

          <div v-if="selected.length" class="kb-sources">
            <header>本次将使用的参考文档 · {{ selected.length }} 份</header>
            <ul>
              <li v-for="doc in props.references.filter((r) => selected.includes(r.id))" :key="doc.id">
                {{ doc.name || doc.filename }}
                <small> · {{ doc.char_count }} 字 · 导入 {{ shortImportedAt(doc.uploaded_at) }}</small>
              </li>
            </ul>
          </div>

          <div v-if="selectedSkills.length" class="kb-sources">
            <header>本次启用的写作技能 · {{ selectedSkills.length }} 个</header>
            <ul>
              <li v-for="skill in props.skills.filter((s) => selectedSkills.includes(s.id))" :key="skill.id">
                {{ skill.name }}
                <small> · {{ skill.origin === 'builtin' ? '系统内置' : '我导入的' }}</small>
              </li>
            </ul>
          </div>

          <div v-if="issues.length" class="issues">
            <header>待修订意见 · {{ issues.length }} 条<span v-if="hardCount"> · 其中 {{ hardCount }} 条事实风险需优先处理</span></header>
            <div v-for="(issue, i) in issues" :key="i" class="issue">
              <span class="tag" :class="issue.type">{{ issue.type }}</span>
              <p>{{ issue.reason }}</p>
              <small>「{{ issue.quote }}」→ {{ issue.fix }}</small>
            </div>
            <button class="btn small full" @click="emit('go', 'documents')">逐项给建议并重新生成</button>
          </div>
          <div v-if="warnings.length" class="warnings">
            <div v-for="(warning, i) in warnings" :key="i">⚠ {{ warning }}</div>
          </div>
          <div v-if="numericWarnings.length" class="warnings">
            <div v-for="(warning, i) in numericWarnings" :key="'n' + i">№ {{ warning }}</div>
            <small class="hint">以上数字在最新一轮复检中仍未在事实清单里找到对应。</small>
          </div>
          <div v-if="!score && !dimensionRows.length && !issues.length && !warnings.length && !numericWarnings.length && !knowledgeSources.length && !(knowledge && knowledge.note)" class="mini-empty">
            <strong>暂无校验意见</strong>
            <span>生成后模型会核对文书中的事实与数字，并给出质量评分，可疑之处会列在这里</span>
          </div>
        </div>

        <div v-show="insightTab === 'outline'">
          <div v-if="outline.length" class="outline-list">
            <div v-for="(section, i) in outline" :key="i" class="outline-item">
              <span class="outline-index">{{ String(i + 1).padStart(2, '0') }}</span>
              <div><strong>{{ section.title }}</strong><p>{{ section.goal }}</p>
                <small v-if="section.evidence_ids && section.evidence_ids.length">证据：{{ section.evidence_ids.join(', ') }}</small>
              </div>
            </div>
          </div>
          <div v-else class="mini-empty"><strong>还没有大纲</strong><span>生成时模型会先规划段落结构，再逐段写作</span></div>
        </div>
      </div>
    </section>
  </div>
</template>
