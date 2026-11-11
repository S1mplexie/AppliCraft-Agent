<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { uid } from '../types'
import type { ApplicantProfile, MatchItem, MatchResult } from '../types'

const props = defineProps<{ profileId: string; profile: ApplicantProfile }>()
const emit = defineEmits<{ toast: [message: string]; quotaChanged: [] }>()

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

const groups = computed(() => {
  const byTier = new Map<string, MatchItem[]>()
  for (const item of result.value?.results || []) {
    const list = byTier.get(item.tier) || []
    list.push(item)
    byTier.set(item.tier, list)
  }
  return tierOrder.value
    .filter(t => byTier.has(t))
    .map(t => ({ tier: t, label: tierLabels.value[t] || t, items: byTier.get(t) as MatchItem[] }))
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
        <p>当前档案「{{ props.profile.label || '未命名档案' }}」的硬指标与 30 个港新项目要求的规则比对</p>
      </div>
      <div v-if="state !== 'idle'" class="head-actions">
        <button class="btn primary" :disabled="state === 'loading'" @click="runMatch">
          {{ state === 'loading' ? '评估中…' : '重新评估' }}
        </button>
      </div>
    </div>

    <div v-if="state === 'idle'" class="card">
      <p style="margin: 0 0 10px;">基于档案中的 GPA、均分、语言分（含单项）与专业课程，对 30 个港新项目做规则比对：</p>
      <ul class="match-idle-list">
        <li>匹配度分级（保底 / 稳妥 / 冲刺），每条附判断依据</li>
        <li>硬性缺口清单（精确到语言单项分，例如「写作 5.0 不满足单项要求 5.5」）</li>
        <li>一键把项目加入目标项目列表</li>
      </ul>
      <p class="hint" style="margin: 10px 0 14px;">
        每次评估消耗 1 次免费额度（与文书生成共用每日配额；管理员与自有 Key 用户不占用）。
        评估为规则比对、结果仅供参考：语言分数随入学季更新，提交申请前以官网为准。
      </p>
      <button class="btn primary" :disabled="state === 'loading'" @click="runMatch">开始评估</button>
    </div>

    <div v-else-if="state === 'loading'" class="card">
      <p style="margin: 0;" class="running">评估计算中…</p>
    </div>

    <div v-else-if="state === 'error'" class="card">
      <div class="auth-error">{{ loadError }}</div>
      <button class="btn" @click="runMatch">重试</button>
    </div>

    <template v-else-if="result">
      <div class="card">
        <div class="card-head"><h2>档案硬指标</h2><span class="hint">评估输入</span></div>
        <div class="match-snapshot">
          <span>GPA <b>{{ result.profile_snapshot.gpa || '—' }}</b></span>
          <span>均分 <b>{{ result.profile_snapshot.gpa_average || '—' }}</b></span>
          <span>IELTS <b>{{ result.profile_snapshot.ielts_total ?? '—' }}</b></span>
          <span>TOEFL <b>{{ result.profile_snapshot.toefl_total ?? '—' }}</b></span>
        </div>
        <p v-if="result.profile_snapshot.notes.length" class="hint" style="margin: 0;">{{ result.profile_snapshot.notes[0] }}</p>
        <p class="hint" style="margin: 8px 0 0;">{{ result.profile_snapshot.watermark_note }}</p>
      </div>

      <div v-for="group in groups" :key="group.tier" style="margin-top: 16px;">
        <div class="match-tier-head">
          <span class="tier-badge" :class="group.tier">{{ group.label }}</span>
          <span class="hint">{{ group.items.length }} 个项目</span>
        </div>
        <div v-for="item in group.items" :key="item.program_id" class="match-card">
          <div class="match-card-top">
            <strong>{{ item.school_name_zh }} · {{ item.name_en }}</strong>
            <span class="tier-badge" :class="item.tier">{{ item.tier_label }}</span>
            <span class="hint">{{ item.name_zh }}</span>
          </div>
          <ul class="match-list">
            <li v-for="(reason, i) in item.reasons" :key="'r' + i">{{ reason }}</li>
          </ul>
          <ul v-if="item.gaps.length" class="match-list match-gaps">
            <li v-for="(gap, i) in item.gaps" :key="'g' + i">{{ gap }}</li>
          </ul>
          <small v-if="item.language_note" class="hint">口径：{{ item.language_note }}</small>
          <div class="match-foot">
            <span class="hint">{{ item.intake }}{{ item.deadline ? ` · 截止 ${item.deadline}` : '' }}</span>
            <button class="btn small primary" :disabled="alreadyIn(item)" @click="addToTargets(item)">
              {{ alreadyIn(item) ? '已在档案' : '加入档案' }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>