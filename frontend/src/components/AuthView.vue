<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../api/client'
import type { AuthResponse } from '../types'

const props = defineProps<{
  allowRegistration: boolean
  systemKeyLimit: number
  checking: boolean
}>()
const emit = defineEmits<{ authed: [payload: AuthResponse] }>()

// 首次访问永远是登录页；注册需要用户主动切换，不做自动跳转。
const mode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const displayName = ref('')
const busy = ref(false)
const error = ref('')

// 关闭开放注册时把界面收回登录（例如首个账号建完自动收敛）；开放时不改变默认登录态。
watch(() => props.allowRegistration, (open) => { if (!open) mode.value = 'login' }, { immediate: true })

function switchMode() {
  if (props.checking || busy.value) return
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}

async function submit() {
  if (busy.value || props.checking) return
  error.value = ''
  busy.value = true
  try {
    const result = mode.value === 'login'
      ? await api.login(email.value, password.value)
      : await api.register(email.value, password.value, displayName.value)
    emit('authed', result)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-shell">
    <div class="auth-layout">
      <section class="auth-intro">
        <div class="intro-brand">
          <span class="brand-mark">A</span>
          <span>AppliCraft</span>
        </div>
        <h1>把经历整理成事实，<br />把事实写成好文书。</h1>
        <p class="intro-desc">
          面向港硕与申请制硕士的 CV、个人陈述与推荐信生成工作台。
          内容只取自你的档案，可核对、可编辑、可导出。
        </p>
        <ul class="intro-points">
          <li><b>事实驱动</b><span>分区维护教育、经历、项目与推荐人，不编造经历</span></li>
          <li><b>过程透明</b><span>实时查看大纲、生成轨迹与事实校验意见</span></li>
          <li><b>多端同步</b><span>网页与微信小程序共用账号、档案与文书</span></li>
        </ul>
      </section>

      <div class="auth-card">
        <span class="card-eyebrow">{{ mode === 'login' ? 'WELCOME BACK' : 'GET STARTED' }}</span>
        <h2>{{ mode === 'login' ? '登录工作台' : '注册新账号' }}</h2>
        <p class="hint">账号密码登录；每位用户的档案、文书与生成记录相互隔离。</p>
        <p v-if="checking" class="auth-checking">正在检查登录状态，请稍候…</p>

        <form @submit.prevent="submit">
          <label class="field">
            <span>邮箱</span>
            <input v-model="email" type="email" autocomplete="email" required :disabled="checking" placeholder="you@example.com" />
          </label>
          <label v-if="mode === 'register'" class="field">
            <span>显示名称（可选）</span>
            <input v-model="displayName" autocomplete="name" :disabled="checking" placeholder="例如：张三" />
          </label>
          <label class="field">
            <span>密码</span>
            <input
              v-model="password" type="password" required minlength="8" :disabled="checking" placeholder="至少 8 位"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            />
          </label>
          <div v-if="error" class="auth-error">{{ error }}</div>
          <button class="btn primary auth-submit" type="submit" :disabled="busy || checking">
            {{ checking ? '正在恢复登录状态…' : busy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
          </button>
        </form>

        <div class="auth-switch">
          <template v-if="props.allowRegistration">
            {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
            <button class="link" type="button" :disabled="checking || busy" @click="switchMode">
              {{ mode === 'login' ? '立即注册' : '去登录' }}
            </button>
          </template>
          <span v-else class="hint">当前未开放注册，账号由管理员分配</span>
        </div>

        <p class="hint auth-note">
          新账号每天可免费使用系统模型 {{ props.systemKeyLimit }} 次；用完后可在「设置 → 我的大模型 API」填入自己的 Key 继续生成。<br />
          密钥由服务端加密保管，不会下发到浏览器；本服务不发送邮件，忘记密码请联系管理员重置。
        </p>
      </div>
    </div>
  </div>
</template>
