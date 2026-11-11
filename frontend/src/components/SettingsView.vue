<script setup lang="ts">
import { computed } from 'vue'
import LlmSettingsCard from './LlmSettingsCard.vue'
import type { AppConfig, AuthUser, ProfileSummary, QuotaInfo, UserLLMConfig } from '../types'

const props = defineProps<{
  user: AuthUser
  quota: QuotaInfo | null
  config: AppConfig | null
  myLlm: UserLLMConfig | null
  profiles: ProfileSummary[]
  currentProfileId: string
  saveState: string
}>()
const emit = defineEmits<{
  manage: []
  save: []
  logout: []
  refreshLlm: []
}>()

const currentLabel = computed(() =>
  props.profiles.find(item => item.id === props.currentProfileId)?.label || '',
)
const isAdmin = computed(() => !!(props.myLlm?.is_admin || props.quota?.source === 'admin'))
const unlimited = computed(() => !!(props.myLlm?.unlimited || props.quota?.unlimited))
const billingText = computed(() => {
  if (isAdmin.value) return '系统共享 Key（管理员不限次数）'
  if (props.myLlm?.effective_source === 'personal') return '自有 Key（不占系统额度）'
  return '系统共享 Key'
})
const quotaText = computed(() => {
  if (isAdmin.value) return '不限次数 · 管理员账号'
  if (unlimited.value) return '不限次数 · 自有 Key'
  const limit = props.myLlm?.system_key_daily_limit
    ?? props.quota?.system_key_limit ?? props.config?.system_key_daily_limit ?? 3
  const remaining = props.myLlm?.system_key_remaining ?? props.quota?.system_key_remaining
  if (remaining == null) return `${props.user.daily_quota} 次/天`
  return `今日免费 ${Math.max(0, limit - remaining)} / ${limit} 次（剩 ${remaining}）`
})

function fmtDate(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN')
}

</script>

<template>
  <div class="page settings-page">
    <div class="page-head">
      <div><h1>设置</h1><p>账号、服务状态与使用提示</p></div>
      <div class="head-actions">
        <button class="btn" @click="emit('logout')">退出登录</button>
      </div>
    </div>

    <div class="settings-grid">
      <section class="card">
        <div class="card-head"><h2>账号与服务</h2><span class="badge ok">已登录</span></div>
        <div class="kv-list">
          <div><span>邮箱</span><b>{{ user.email }}</b></div>
          <div><span>显示名称</span><b>{{ user.display_name || '未设置' }}</b></div>
          <div><span>注册时间</span><b>{{ fmtDate(user.created_at) }}</b></div>
          <div><span>今日配额</span><b>{{ quotaText }}</b></div>
          <div><span>计费方式</span><b :class="myLlm?.effective_source === 'personal' ? 'ok-text' : ''">{{ billingText }}</b></div>
          <div><span>当前模型</span><b>{{ myLlm?.effective_model || config?.llm_model || '—' }}</b></div>
          <div><span>系统 Key</span><b :class="config?.llm_configured ? 'ok-text' : 'danger-text'">{{ config?.llm_configured ? '已就绪' : '未配置' }}</b></div>
          <div><span>服务版本</span><b>{{ config?.version || '—' }}</b></div>
          <div><span>自助注册</span><b>{{ config?.allow_registration ? '开放' : '关闭' }}</b></div>
          <div><span>微信登录</span><b>{{ config?.wechat_login_enabled ? '已启用' : '未启用' }}</b></div>
        </div>
        <p class="hint card-note">系统 Key 由服务端 .env 保管，不会下发到浏览器；你也可以在下方配置自己的 Key。</p>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>档案管理</h2>
          <span class="hint">{{ saveState }}</span>
        </div>
        <div class="kv-list">
          <div><span>当前档案</span><b>{{ currentLabel || '暂无' }}</b></div>
          <div><span>档案总数</span><b>{{ profiles.length }} 份</b></div>
          <div><span>数据范围</span><b class="wrap">各档案相互隔离，文书库与生成参数随档案同步切换</b></div>
        </div>
        <div class="quick-actions" style="display: flex; gap: 8px; margin-top: 14px;">
          <button class="btn small primary" @click="emit('manage')">管理档案</button>
          <button class="btn small" :disabled="!currentProfileId" @click="emit('save')">立即保存当前档案</button>
        </div>
        <p class="hint card-note">切换、新建、改名与删除统一在顶栏「当前档案」入口完成；删除后会自动切换到剩余档案。</p>
      </section>

      <LlmSettingsCard :llm="myLlm" @changed="emit('refreshLlm')" />

      <section class="card span-2">

        <div class="card-head"><h2>使用与安全提示</h2></div>
        <ul class="tips">
          <li>配置自己的 API Key 后，生成费用由你的服务商账号承担，且不受系统每日次数限制；未配置时使用系统共享 Key。</li>
          <li>文书中的事实、数字、校名与项目名必须人工核对；模型只使用档案里出现过的信息。</li>
          <li>档案修改后自动保存（停止输入约 1 秒），也可在上方点「立即保存当前档案」。</li>
          <li>删除档案会保留已生成的文书，但文书将不再关联到任何档案，建议先导出 DOCX。</li>
          <li>当前通过 HTTP 访问时请勿在公共网络输入敏感信息；正式使用请配置 HTTPS 域名。</li>
        </ul>
      </section>
    </div>
  </div>
</template>
