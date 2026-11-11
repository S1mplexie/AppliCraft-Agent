<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import { LLM_PROVIDERS, type UserLLMConfig } from '../types'

const props = defineProps<{ llm: UserLLMConfig | null }>()
const emit = defineEmits<{ changed: [] }>()

const baseUrl = ref('')
const model = ref('')
const apiKey = ref('')
const busy = ref<'save' | 'test' | 'delete' | null>(null)
const msg = ref('')
const msgError = ref(false)

watch(
  () => props.llm,
  (value) => {
    baseUrl.value = value?.base_url || ''
    model.value = value?.model || ''
    apiKey.value = ''
  },
  { immediate: true },
)

const enabled = computed(() => props.llm?.allow_personal_llm_keys !== false)
const source = computed(() => props.llm?.effective_source || 'none')
const freeLimit = computed(() => props.llm?.system_key_daily_limit ?? 3)
const sourceLabel = computed(() => {
  if (props.llm?.is_admin) {
    return source.value === 'personal'
      ? '管理员账号 · 正在使用自己的 Key'
      : '管理员账号 · 系统 Key 不限次数'
  }
  return ({
    personal: '正在使用你自己的 API Key',
    system: '正在使用系统共享 API Key',
    none: '暂无可用 API Key',
  })[source.value]
})
const sourceClass = computed(() => ({
  personal: 'badge ok',
  system: 'badge warn',
  none: 'badge warn',
})[source.value])

function flash(text: string, error = false) {
  msg.value = text
  msgError.value = error
  window.setTimeout(() => { msg.value = '' }, 5000)
}

function applyProvider(id: string) {
  const preset = LLM_PROVIDERS.find(item => item.id === id)
  if (!preset) return
  baseUrl.value = preset.base_url
  model.value = preset.model
  flash(`已填入 ${preset.label} 的地址与模型名，请粘贴你自己的 API Key`)
}

function payload() {
  return { base_url: baseUrl.value.trim(), model: model.value.trim(), api_key: apiKey.value.trim() }
}

async function save() {
  busy.value = 'save'
  try {
    await api.saveMyLlm(payload())
    apiKey.value = ''
    flash('已保存。之后的生成会使用你自己的 Key，不再占用系统额度。')
    emit('changed')
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    busy.value = null
  }
}

async function testConnection() {
  busy.value = 'test'
  try {
    const result = await api.testMyLlm(payload())
    flash(result.message, !result.ok)
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    busy.value = null
  }
}

async function remove() {
  if (!confirm('清除你自己配置的 API Key？之后将回退到系统共享 Key（若管理员已关闭兜底，则需要重新配置）。')) return
  busy.value = 'delete'
  try {
    await api.deleteMyLlm()
    apiKey.value = ''
    flash('已清除个人 API Key')
    emit('changed')
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    busy.value = null
  }
}

function fmtDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <section class="card span-2 llm-card">
    <div class="card-head">
      <h2>我的大模型 API</h2>
      <span :class="sourceClass">{{ sourceLabel }}</span>
    </div>

    <p class="llm-lead">
      填入你自己的 API Key 后，生成文书会走你的账号、由你承担费用，<b>不限次数且不占系统额度</b>；
      未填写才回退到系统共享 Key。<b>管理员账号不限次数</b>；其他账号每天只有
      <b>{{ freeLimit }} 次</b>免费额度，用完后必须配置自己的 Key。
      Key 在服务端加密保存，任何页面都不会显示完整内容。
    </p>

    <div class="llm-status">
      <div v-if="llm?.is_admin"><span>今日免费额度</span><b>管理员 · 不限次数</b></div>
      <div v-else-if="llm?.unlimited"><span>今日免费额度</span><b>自有 Key · 不限次数</b></div>
      <div v-else-if="llm"><span>今日免费额度</span>
        <b :class="llm.system_key_remaining === 0 ? 'danger-text' : ''">
          剩 {{ llm.system_key_remaining }} / {{ freeLimit }} 次
        </b>
      </div>
      <div><span>当前生效模型</span><b>{{ llm?.effective_model || '—' }}</b></div>
      <div><span>当前接口地址</span><b class="wrap">{{ llm?.effective_base_url || '—' }}</b></div>
      <div v-if="llm?.has_key"><span>我的 Key</span><b>{{ llm.api_key_hint }}（已加密保存）</b></div>
      <div v-if="llm?.require_personal_llm_key"><span>管理员设置</span><b>已强制每人自带 Key</b></div>
      <div v-if="llm?.has_key && llm.updated_at"><span>最近更新</span><b>{{ fmtDate(llm.updated_at) }}</b></div>
    </div>

    <div v-if="!enabled" class="llm-disabled">
      管理员已关闭「用户自带 API Key」功能，当前统一使用系统共享 Key。
    </div>

    <template v-else>
      <div class="llm-presets">
        <span class="hint">快捷填入：</span>
        <button
          v-for="item in LLM_PROVIDERS" :key="item.id" class="btn small"
          :title="item.hint" @click="applyProvider(item.id)"
        >{{ item.label }}</button>
      </div>

      <div class="llm-form">
        <label class="field">
          <span>接口地址（OpenAI 兼容 /chat/completions）</span>
          <input v-model="baseUrl" type="text" placeholder="https://api.deepseek.com/v1" spellcheck="false" />
        </label>
        <label class="field">
          <span>模型名称</span>
          <input v-model="model" type="text" placeholder="deepseek-chat" spellcheck="false" />
        </label>
        <label class="field span-2">
          <span>API Key {{ llm?.has_key ? '（留空表示继续使用已保存的 Key）' : '' }}</span>
          <input
            v-model="apiKey" type="password" autocomplete="new-password"
            :placeholder="llm?.has_key ? `已保存 ${llm.api_key_hint}，如需更换请重新粘贴` : '只填你自己的 Key，不会下发到任何第三方'"
            spellcheck="false"
          />
        </label>
      </div>

      <div class="llm-actions">
        <button class="btn primary" :disabled="busy !== null" @click="save">
          {{ busy === 'save' ? '保存中…' : '保存配置' }}
        </button>
        <button class="btn" :disabled="busy !== null" @click="testConnection">
          {{ busy === 'test' ? '测试中…' : '测试连接' }}
        </button>
        <button class="btn ghost" :disabled="busy !== null || !llm?.has_key" @click="remove">
          {{ busy === 'delete' ? '清除中…' : '清除我的 Key' }}
        </button>
        <span v-if="msg" class="llm-msg" :class="{ error: msgError }">{{ msg }}</span>
      </div>

      <p class="hint llm-note">
        安全提示：只填写你信任的服务商地址；Key 以 Fernet 密文存库、服务端仅在生成时解密使用，
        日志与错误信息都会脱敏。切换模型后，文书生成质量与费用以该服务商为准。
      </p>
    </template>
  </section>
</template>
