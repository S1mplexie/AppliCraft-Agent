<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { uid } from '../types'
import type { ApplicantProfile, MatchItem, MatchResult } from '../types'

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

watch(() => props.profileId, () => {
  state.value = 'idle'
  result.value = null
  addedIds.value = new Set()
})

async function runMatch() {
  if (state.value === 'loading') return
  state.value = 'loading'
  loadError.value = ''
  try {
    result.value = await api.matchProfile(props.profileId)
    state.value = 'done'
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

const tierOrder = computed(() => result.value?.tier_order || ['gap', 'reach', 'match', 'safety'])
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
    region: item.region === 'HK' ? 'Hong Kong, China' : 'Singapore',
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
        <p>大模型结合档案与 30 个港新项目官方要求，给出适配等级（保底 / 稳妥 / 冲刺 / 硬性缺口）</p>
      </div>
      <div v-if="state !== 'idle'" class="head-actions">
        <button class="btn primary" :disabled="state === 'loading' || !llmReady" @click="runMatch">
          {{ state === 'loading' ? '评估中…' : '重新评估' }}
        </button>
      </div>
    </div>

    <div v-if="state === 'idle'" class="card">
      <p style="margin: 0 0 10px;">由大模型综合档案中的 GPA / 均分、语言成绩（含单项）、专业与课程匹配度、科研 / 实习等背景，对 30 个港新项目评估适配等级：</p>
      <ul class="match-idle-list">
        <li>适配等级分级（保底 / 稳妥 / 冲刺 / 硬性缺口），每条附判断依据</li>
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
      <button class="btn primary" :disabled="state === 'loading' || !llmReady" @click="runMatch">开始评估</button>
    </div>

    <div v-else-if="state === 'loading'" class="card">
      <p style="margin: 0;" class="running">评估计算中…</p>
    </div>

    <div v-else-if="state === 'error'" class="card">
      <div class="auth-error">{{ loadError }}</div>
      <button class="btn" @click="runMatch">重试</button>
    </div>

    <template v-else-if="result">
      <div class="match-summary">
        <div v-for="s in summary" :key="s.tier" class="match-stat" :class="s.tier">
          <span class="match-stat-num">{{ s.count }}</span>
          <span class="match-stat-label">{{ s.label }}</span>
        </div>
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