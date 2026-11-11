<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { LLM_PROVIDERS, type LocalLLMConfig } from '../types'

const emit = defineEmits<{ changed: [] }>()

const baseUrl = ref('')
const model = ref('')
const apiKey = ref('')
const busy = ref<'save' | 'test' | null>(null)
const msg = ref('')
const msgError = ref(false)
const current = ref<LocalLLMConfig | null>(null)

onMounted(loadCurrent)

async function loadCurrent() {
  try {
    current.value = await api.getLocalLlm()
    baseUrl.value = current.value.base_url || ''
    model.value = current.value.model || ''
    apiKey.value = ''
  } catch {
    current.value = null
  }
}

const configured = computed(() => !!current.value?.configured)

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
    current.value = await api.saveLocalLlm(payload())
    apiKey.value = ''
    flash('已保存。之后的生成会使用这个 Key（仅保存在本机 data/local_llm.json）。')
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
    const result = await api.testLocalLlm(payload())
    flash(result.message, !result.ok)
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <section class="card span-2 llm-card">
    <div class="card-head">
      <h2>我的大模型 API</h2>
      <span :class="configured ? 'badge ok' : 'badge warn'">
        {{ configured ? '已配置 · 使用你的 Key' : '尚未配置 Key' }}
      </span>
    </div>

    <p class="llm-lead">
      本地部署版使用<strong>你自己的 API Key</strong>，生成费用由你的服务商账号承担，<b>不限次数</b>；
      Key 以明文保存在本机 <code>data/local_llm.json</code>，仅在生成时读取，不会上传到任何服务器。
      也可以先在 <code>.env</code> 设置 <code>APPLICRAFT_LLM_API_KEY</code> 后启动，本页再微调地址或模型名。
    </p>

    <div class="llm-status">
      <div><span>当前生效模型</span><b>{{ current?.model || '—' }}</b></div>
      <div><span>当前接口地址</span><b class="wrap">{{ current?.base_url || '—' }}</b></div>
      <div v-if="configured"><span>我的 Key</span><b>{{ current?.api_key_hint }}（仅本机保存）</b></div>
    </div>

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
        <span>API Key {{ configured ? '（留空表示继续使用已保存的 Key）' : '' }}</span>
        <input
          v-model="apiKey" type="password" autocomplete="new-password"
          :placeholder="configured ? '已保存 Key，如需更换请重新粘贴' : '只填你自己的 Key，仅保存在本机'"
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
      <span v-if="msg" class="llm-msg" :class="{ error: msgError }">{{ msg }}</span>
    </div>

    <p class="hint llm-note">
      安全提示：只填写你信任的服务商地址；Key 保存在本机文件，请妥善保管这台电脑。
      切换模型后，文书生成质量与费用以该服务商为准。
    </p>
  </section>
</template>
