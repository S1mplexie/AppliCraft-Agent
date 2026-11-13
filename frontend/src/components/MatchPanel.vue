<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { uid } from '../types'
import type { ApplicantProfile, MatchItem, MatchPreferences, MatchResult } from '../types'

const props = defineProps<{ profileId: string; profile: ApplicantProfile; standalone?: boolean; llmConfigured?: boolean }>()
const emit = defineEmits<{ toast: [message: string]; quotaChanged: [] }>()

// 本地部署版必须配置自己的大模型 API Key 才能做 AI 评估；未配置时禁用按钮并提示。
const llmReady = computed(() => props.llmConfigured !== false)

// 评估是显式扣费动作（系统 Key 用户扣 1 次免费额度），由用户点「开始评估」触发；
// 切换档案后结果自动清空，提示重新评估（结果随档案分域）。
const state = ref<'idle' | 'loading' | 'done' | 'error'>('idle')
const loadError = ref('')
const result = ref<MatchResult | null>(null)
const addedIds = ref<Set<string>>(new Set())

// 择校 / 项目偏好（可选）：优先地区与优先专业方向；localStorage 记忆，跨会话保持。
const prefs = ref<MatchPreferences>({ priority_regions: [], preferred_fields: [] })
const fieldInput = ref('')
const PREFS_KEY = 'applicraft.match_preferences'

try {
  const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || 'null') as MatchPreferences | null
  if (saved?.priority_regions?.length || saved?.preferred_fields?.length) prefs.value = saved
} catch { /* 损坏忽略 */ }
watch(prefs, () => localStorage.setItem(PREFS_KEY, JSON.stringify(prefs.value)), { deep: true })

function addField() {
  const v = fieldInput.value.trim()
  if (v && !prefs.value.preferred_fields.includes(v)) prefs.value.preferred_fields.push(v)
  fieldInput.value = ''
}
function removeField(v: string) {
  prefs.value.preferred_fields = prefs.value.preferred_fields.filter(x => x !== v)
}

// 偏好文案：既用于结果页展示「本次按什么偏好评估」，也在回到偏好页时提示上次设置。
const prefsText = computed(() => {
  const parts: string[] = []
  if (prefs.value.priority_regions.includes('HK')) parts.push('优先香港')
  if (prefs.value.priority_regions.includes('SG')) parts.push('优先新加坡')
  if (prefs.value.preferred_fields.length) parts.push(`优先方向：${prefs.value.preferred_fields.join('、')}`)
  return parts.join(' · ')
})
// 记录「发起本次评估时」的偏好快照，避免用户后来改了偏好导致结果页文案对不上。
const appliedPrefsText = ref('')
const hasLastResult = computed(() => !!result.value)

watch(() => props.profileId, () => {
  state.value = 'idle'
  result.value = null
  addedIds.value = new Set()
})

async function runMatch() {
  if (state.value === 'loading') return
  state.value = 'loading'
  loadError.value = ''
  const submittedPrefs = prefsText.value
  try {
    result.value = await api.matchProfile(props.profileId, prefs.value)
    state.value = 'done'
    appliedPrefsText.value = submittedPrefs
    addedIds.value = new Set()
    emit('quotaChanged')
    if (result.value.billing_source === 'system') {
      emit('toast', `评估完成，已消耗 1 次免费额度（今日剩 ${result.value.quota.system_key_remaining} 次）`)
    }
  } catch (error) {
    state.value = 'error'
    loadError.value = (error as Error).message
  }
}

// 重新评估不直接发起（避免不给改偏好的机会）：回到偏好表单，
// 上次结果保留在内存里，可随时无消耗查看。
function backToPrefs() {
  if (state.value === 'loading') return
  state.value = 'idle'
  loadError.value = ''
  scrollToTop()
}
function showLastResult() {
  if (!result.value) return
  state.value = 'done'
  scrollToTop()
}
function scrollToTop() {
  const page = document.querySelector('.match-page')
  const scroller = page?.closest('.page-view') as HTMLElement | null
  try { scroller?.scrollTo({ top: 0, behavior: 'smooth' }) } catch { /* 忽略 */ }
  try { window.scrollTo({ top: 0, behavior: 'smooth' }) } catch { /* 忽略 */ }
}

const tierLabels = computed(() => result.value?.tier_labels || {})

// 展示顺序：先呈现录取机会（冲刺 / 稳妥 / 保底），最后单列硬性缺口，更符合阅读习惯。
const tierDisplayOrder = ['reach', 'match', 'safety', 'gap']

const byTierMap = computed(() => {
  const map = new Map<string, MatchItem[]>()
  for (const item of result.value?.results || []) {
    const list = map.get(item.tier) || []
    list.push(item)
    map.set(item.tier, list)
  }
  return map
})

const groups = computed(() =>
  tierDisplayOrder
    .filter(t => byTierMap.value.has(t))
    .map(t => ({ tier: t, label: tierLabels.value[t] || t, items: byTierMap.value.get(t) as MatchItem[] }))
)

// 顶部概览：四档计数（含 0 档），一眼看清机会分布。
const summary = computed(() =>
  tierDisplayOrder.map(t => ({
    tier: t,
    label: tierLabels.value[t] || t,
    count: byTierMap.value.get(t)?.length || 0,
  }))
)

// 档案关键字段完整度：信息不足时模型难以拉开档次，先给明确提示而不是产出「全部同一档」。
const missingBasics = computed(() => {
  const p = props.profile
  const missing: string[] = []
  if (!(p.education || []).some(e => e.school || e.gpa || e.gpa_average || e.major)) missing.push('教育背景 / GPA')
  if (!(p.test_scores || []).some(s => s.total)) missing.push('语言成绩')
  if (!(p.experiences || []).length) missing.push('实习 / 科研经历')
  return missing
})

// 结果退化检测：九成以上项目挤在同一档时诚实提示，避免用户以为「分级功能坏了」。
const lowDiscrimination = computed(() => {
  const counts = summary.value.map(s => s.count)
  const total = counts.reduce((a, b) => a + b, 0)
  return total > 0 && Math.max(...counts) >= total * 0.9
})
const dominantTier = computed(() => {
  const top = [...summary.value].sort((a, b) => b.count - a.count)[0]
  const total = summary.value.reduce((a, b) => a + b.count, 0)
  return top ? `${top.count} / ${total} 个「${top.label}」` : ''
})

function alreadyIn(item: MatchItem): boolean {
  return item.in_target || addedIds.value.has(item.program_id)
}

async function addToTargets(item: MatchItem) {
  if (alreadyIn(item)) return
  // push 进共享的响应式档案对象会触发自动保存；此处再手动落盘一次确保即时生效。
  props.profile.target_programs.push({
    id: uid(),
    university: item.school_name_zh,
    program: item.name_en,
    degree_type: 'Taught Master',
    region: item.region === 'HK' ? '中国香港' : item.region === 'SG' ? '新加坡' : '',
    intake: '', deadline: item.deadline, language_requirement: '',
    curriculum_notes: '', faculty_notes: '', why_fit: '',
    notes: '来自选校评估，请核对官网最新要求后补充课程与师资信息',
  })
  try {
    await api.updateProfile(props.profileId, props.profile)
    addedIds.value.add(item.program_id)
    emit('toast', `已将「${item.name_zh || item.name_en}」加入目标项目档案`)
  } catch (error) {
    emit('toast', `加入失败：${(error as Error).message}`)
  }
}
</script>

<template>
  <div class="page match-page">
    <div class="page-head">
      <div>
        <h1>选校评估</h1>
        <p>大模型结合档案与系统收录的港新项目官方要求，给出适配等级（冲刺 / 稳妥 / 保底 / 硬性缺口）</p>
      </div>
      <div v-if="state === 'done' || state === 'error'" class="head-actions">
        <button class="btn primary" :disabled="state === 'loading'" @click="backToPrefs">
          调整偏好并重新评估
        </button>
      </div>
    </div>

    <div v-if="state === 'idle'" class="card">
      <div v-if="hasLastResult" class="banner match-prev-note">
        上次的评估结果已保留：先调整下面的偏好再评估，或直接
        <button class="btn small" @click="showLastResult">查看上次结果</button>
      </div>
      <div v-if="missingBasics.length" class="match-warn">
        当前档案还缺少：{{ missingBasics.join('、') }}。信息不足时模型难以拉开冲刺 / 稳妥 / 保底，建议先到左侧「申请人档案」补全后再评估。
      </div>
      <p style="margin: 0 0 10px;">由大模型综合档案中的 GPA / 均分、语言成绩（含单项）、专业与课程匹配度、科研 / 实习等背景，对系统收录的港新项目评估适配等级：</p>
      <ul class="match-idle-list">
        <li>四档适配等级（冲刺 / 稳妥 / 保底 / 硬性缺口），每条附判断依据</li>
        <li>硬性缺口清单（语言未达标等明显不满足官方门槛的项目会被单独标出）</li>
        <li>一键把项目加入目标项目列表</li>
      </ul>
      <p v-if="props.standalone && !llmReady" class="banner" style="margin: 10px 0 14px;">
        请先在「设置 → 我的大模型 API」填入你自己的 API Key，才能使用 AI 选校评估。
      </p>
      <p v-else class="hint" style="margin: 10px 0 14px;">
        <template v-if="props.standalone">
          本地部署版用你自己的 Key 调用大模型，不消耗任何免费额度，可随时重新评估。
          结果由 AI 结合官方要求给出，仅供参考：语言硬性门槛以官方要求为准，提交申请前请以官网最新信息为准。
        </template>
        <template v-else>
          每次评估消耗 1 次免费额度（与文书生成共用每日配额；管理员与自有 Key 用户不占用）。
          结果由 AI 结合官方要求给出，仅供参考：语言硬性门槛以官方要求为准，提交申请前请以官网最新信息为准。
        </template>
      </p>
      <div class="pref-block">
        <div class="field">
          <span>择校偏好：优先地区（可选）</span>
          <div class="pref-checks">
            <label class="pref-check"><input type="checkbox" value="HK" v-model="prefs.priority_regions" /> 优先香港</label>
            <label class="pref-check"><input type="checkbox" value="SG" v-model="prefs.priority_regions" /> 优先新加坡</label>
          </div>
        </div>
        <div class="field">
          <span>项目偏好：优先专业方向（可选，回车添加）</span>
          <input v-model="fieldInput" placeholder="例如：计算机、人工智能、金融科技" @keydown.enter.prevent="addField" />
          <div v-if="prefs.preferred_fields.length" class="tag-row">
            <span v-for="f in prefs.preferred_fields" :key="f" class="tag removable" @click="removeField(f)">{{ f }} ×</span>
          </div>
        </div>
        <p class="hint">偏好会让大模型在评估理由中呼应你的倾向；留空则对所有项目一视同仁。调整偏好本身不消耗额度。</p>
      </div>
      <div class="match-start-actions">
        <button class="btn primary" :disabled="state === 'loading' || !llmReady" @click="runMatch">
          {{ hasLastResult ? '按当前偏好重新评估' : '开始评估' }}
        </button>
        <button v-if="hasLastResult" class="btn" @click="showLastResult">返回上次结果</button>
      </div>
    </div>

    <div v-else-if="state === 'loading'" class="card">
      <p style="margin: 0;" class="running">评估计算中…</p>
    </div>

    <div v-else-if="state === 'error'" class="card">
      <div class="auth-error">{{ loadError }}</div>
      <div class="match-start-actions" style="margin-top: 12px;">
        <button class="btn primary" :disabled="!llmReady" @click="runMatch">重试</button>
        <button class="btn" @click="backToPrefs">返回修改偏好</button>
        <button v-if="hasLastResult" class="btn" @click="showLastResult">查看上次结果</button>
      </div>
    </div>

    <template v-else-if="result">
      <div class="match-summary">
        <div v-for="s in summary" :key="s.tier" class="match-stat" :class="s.tier">
          <span class="match-stat-num">{{ s.count }}</span>
          <span class="match-stat-label">{{ s.label }}</span>
        </div>
      </div>
      <p v-if="result.preferences_applied" class="hint match-pref-note">
        本次已按偏好评估：{{ appliedPrefsText || '已应用择校偏好' }}
      </p>

      <div v-if="lowDiscrimination" class="match-warn">
        本次评估区分度不足：{{ dominantTier }}，多数项目落在同一档。这通常是档案缺少 GPA、语言成绩或经历等关键信息所致，建议补全档案后重新评估。
      </div>

      <div class="card match-snapshot-card">
        <div class="card-head"><h2>档案硬指标</h2><span class="hint">评估输入</span></div>
        <div class="match-snapshot">
          <div class="ms-item"><span class="ms-k">GPA</span><span class="ms-v">{{ result.profile_snapshot.gpa || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">均分</span><span class="ms-v">{{ result.profile_snapshot.gpa_average || '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">IELTS</span><span class="ms-v">{{ result.profile_snapshot.ielts_total ?? '—' }}</span></div>
          <div class="ms-item"><span class="ms-k">TOEFL</span><span class="ms-v">{{ result.profile_snapshot.toefl_total ?? '—' }}</span></div>
        </div>
        <p v-if="result.profile_snapshot.notes.length" class="hint" style="margin: 10px 0 0;">{{ result.profile_snapshot.notes[0] }}</p>
        <p class="hint watermark" style="margin: 6px 0 0;">{{ result.profile_snapshot.watermark_note }}</p>
      </div>

      <section v-for="group in groups" :key="group.tier" class="tier-section" :class="group.tier">
        <header class="tier-section-head">
          <span class="tier-badge lg" :class="group.tier">{{ group.label }}</span>
          <span class="tier-section-count">{{ group.items.length }} 个项目</span>
        </header>
        <div class="tier-section-body">
          <article v-for="item in group.items" :key="item.program_id" class="match-card">
            <div class="match-card-head">
              <div class="match-card-title">
                <strong>{{ item.school_name_zh }} · {{ item.name_en }}</strong>
                <span class="match-card-sub">{{ item.name_zh }}</span>
              </div>
              <span class="tier-badge" :class="item.tier">{{ item.tier_label }}</span>
            </div>
            <div class="match-detail">
              <div v-if="item.reasons.length" class="match-block reasons">
                <div class="match-block-title">判断依据</div>
                <ul><li v-for="(r, i) in item.reasons" :key="'r' + i">{{ r }}</li></ul>
              </div>
              <div v-if="item.gaps.length" class="match-block gaps">
                <div class="match-block-title">短板 / 缺口</div>
                <ul><li v-for="(g, i) in item.gaps" :key="'g' + i">{{ g }}</li></ul>
              </div>
              <small v-if="item.language_note" class="hint match-note">口径：{{ item.language_note }}</small>
            </div>
            <div class="match-card-foot">
              <span class="hint">{{ item.intake }}{{ item.deadline ? ' · 截止 ' + item.deadline : '' }}</span>
              <button class="btn small primary" :disabled="alreadyIn(item)" @click="addToTargets(item)">
                {{ alreadyIn(item) ? '已在档案' : '加入档案' }}
              </button>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>