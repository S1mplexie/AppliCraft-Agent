<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { ReferenceDoc, SystemProgram, TabKey } from '../types'
import { api } from '../api/client'
import { formatImportedAt } from '../utils/format'

const props = defineProps<{
  references: ReferenceDoc[]
  systemPrograms: SystemProgram[]
}>()
const emit = defineEmits<{
  uploaded: []
  deleted: []
  go: [tab: TabKey]
}>()

type NameDialog = { id: string; filename: string; isNew: boolean }

const fileInput = ref<HTMLInputElement | null>(null)
const nameInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const localMsg = ref('')
const localError = ref(false)
// 导入成功后才弹出命名框；列表里的「重命名」复用同一弹窗。
const nameDialog = ref<NameDialog | null>(null)
const nameEdit = ref('')
const savingName = ref(false)

function flash(message: string, error = false) {
  localMsg.value = message
  localError.value = error
  window.setTimeout(() => { localMsg.value = '' }, 4200)
}

function triggerUpload() {
  if (!uploading.value) fileInput.value?.click()
}

function focusNameInput() {
  void nextTick(() => nameInput.value?.focus())
}

async function handleFile(file: File) {
  if (uploading.value) return
  uploading.value = true
  try {
    const saved = await api.uploadReference(file)
    // 先让列表立刻出现新文档，再弹窗补名称；跳过也不影响使用。
    emit('uploaded')
    nameEdit.value = ''
    nameDialog.value = { id: saved.id, filename: saved.filename, isNew: true }
    focusNameInput()
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    uploading.value = false
  }
}

function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void handleFile(file)
}

function onDrop(event: DragEvent) {
  const file = event.dataTransfer?.files?.[0]
  if (file) void handleFile(file)
}

function openRename(doc: ReferenceDoc) {
  nameEdit.value = doc.name === doc.filename ? '' : doc.name
  nameDialog.value = { id: doc.id, filename: doc.filename, isNew: false }
  focusNameInput()
}

function closeNameDialog() {
  if (savingName.value || !nameDialog.value) return
  if (nameDialog.value.isNew) flash('已保留原始文件名，之后可点「重命名」修改')
  nameDialog.value = null
}

async function saveName() {
  const dialog = nameDialog.value
  if (!dialog || savingName.value) return
  savingName.value = true
  try {
    await api.renameReference(dialog.id, nameEdit.value)
    flash('文档名称已保存')
    nameDialog.value = null
    emit('uploaded')
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    savingName.value = false
  }
}

async function removeReference(id: string, name: string) {
  if (!confirm(`删除参考文档「${name || id}」？删除后已生成文书中的引用记录仍会保留。`)) return
  try {
    await api.deleteReference(id)
    flash('已删除参考文档')
    emit('deleted')
  } catch (error) {
    flash((error as Error).message, true)
  }
}

function formatSize(bytes: number): string {
  if (!bytes) return '0 KB'
  const kb = bytes / 1024
  return kb < 1024 ? `${kb.toFixed(0)} KB` : `${(kb / 1024).toFixed(1)} MB`
}
// 系统项目按学校分组，便于浏览。
const groupedPrograms = computed(() => {
  const groups: Record<string, SystemProgram[]> = {}
  for (const p of props.systemPrograms) {
    const key = p.school_name_zh || p.school_id
    ;(groups[key] ||= []).push(p)
  }
  return Object.entries(groups).map(([school, items]) => ({ school, items }))
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>参考文档库</h1>
        <p>上传你自己的项目参考材料，并在生成文书时勾选使用；下方同时展示系统已覆盖的港新项目官方信息</p>
      </div>
    </div>

    <div v-if="localMsg" class="lib-toast" :class="{ error: localError }">{{ localMsg }}</div>

    <!-- 上传 -->
    <section class="card">
      <div class="card-head"><h2>上传参考文档</h2><span class="hint">PDF / DOCX / TXT / MD，≤ 10 MB</span></div>
      <div class="upload-zone" @click="triggerUpload" @dragover.prevent @drop.prevent="onDrop">
        <input
          ref="fileInput" type="file" accept=".pdf,.docx,.txt,.md"
          style="display: none" @change="onFile"
        />
        <div class="upload-inner">
          <span class="upload-icon">⬆</span>
          <strong>{{ uploading ? '解析中…' : '点击或拖拽文件到此处上传' }}</strong>
          <small class="hint">仅抽取纯文本用于生成时的补充背景，原文仅保存在你的账户下供下载核对</small>
        </div>
      </div>
      <p class="hint naming-lead">导入成功后会弹出命名框，方便区分不同材料；也可以跳过，之后在列表里点「重命名」补填。</p>
    </section>

    <!-- 我的参考文档 -->
    <section class="card">
      <div class="card-head">
        <h2>我的参考文档 · {{ references.length }} 份</h2>
        <button class="btn small" :disabled="uploading" @click="triggerUpload">{{ uploading ? '解析中…' : '继续上传' }}</button>
      </div>
      <div v-if="!references.length" class="mini-empty">
        <strong>还没有上传任何参考文档</strong>
        <span>上传后可在「生成文书」页勾选使用；系统不会主动注入，完全由你决定</span>
      </div>
      <ul v-else class="ref-doc-list">
        <li v-for="doc in references" :key="doc.id" class="ref-doc-item">
          <div class="ref-doc-main">
            <strong>{{ doc.name || doc.filename }}</strong>
            <small class="import-time">导入时间：{{ formatImportedAt(doc.uploaded_at) }}</small>
            <small>{{ doc.filename }} · {{ doc.ext.replace('.', '').toUpperCase() || 'FILE' }} · {{ formatSize(doc.size) }} · {{ doc.char_count }} 字</small>
          </div>
          <div class="ref-doc-actions">
            <a class="link" :href="api.downloadReferenceUrl(doc.id)" target="_blank" rel="noopener">下载原文</a>
            <button class="link" @click="openRename(doc)">重命名</button>
            <button class="link danger" @click="removeReference(doc.id, doc.name || doc.filename)">删除</button>
          </div>
        </li>
      </ul>
    </section>

    <!-- 系统自带港新项目信息 -->
    <section class="card">
      <div class="card-head">
        <h2>系统自带港新项目信息 · {{ systemPrograms.length }} 个</h2>
        <span class="hint">来自知识库，只读；生成对应项目文书时自动检索官方资料</span>
      </div>
      <div v-if="!systemPrograms.length" class="mini-empty">
        <strong>暂无系统项目信息</strong>
        <span>知识库为空或尚未构建</span>
      </div>
      <div v-for="group in groupedPrograms" :key="group.school" class="program-group">
        <h3 class="program-school">{{ group.school }}</h3>
        <ul class="program-list">
          <li v-for="p in group.items" :key="p.program_id" class="program-item">
            <div class="program-head">
              <strong>{{ p.program_name_en }}</strong>
              <small v-if="p.program_name_zh" class="hint">{{ p.program_name_zh }}</small>
              <span v-if="p.intake" class="tag program-intake">{{ p.intake }}</span>
            </div>
            <small class="program-meta" v-if="p.faculty || p.region">{{ [p.faculty, p.region].filter(Boolean).join(' · ') }}</small>
            <div class="program-fields" v-if="p.fields.length">
              <span v-for="f in p.fields" :key="f" class="tag field-tag">{{ f }}</span>
            </div>
            <a v-if="p.official_urls.length" class="link" :href="p.official_urls[0]" target="_blank" rel="noopener">官方链接 ↗</a>
          </li>
        </ul>
      </div>
    </section>

    <!-- 导入后命名 / 事后重命名 -->
    <div v-if="nameDialog" class="modal-mask" @click.self="closeNameDialog">
      <div class="modal naming-modal">
        <div class="card-head">
          <h2>{{ nameDialog.isNew ? '文档已导入' : '修改文档名称' }}</h2>
          <button class="link" @click="closeNameDialog">关闭</button>
        </div>
        <p class="hint naming-hint">
          {{ nameDialog.isNew
            ? '给这份材料起个便于识别的名字，生成文书勾选时更容易区分。'
            : '修改后已抽取的正文与导入时间都不会变化。' }}
        </p>
        <div class="naming-file">原始文件：{{ nameDialog.filename }}</div>
        <label class="field">
          <span>文档名称</span>
          <input
            ref="nameInput" v-model="nameEdit" maxlength="120"
            :placeholder="'留空则使用：' + nameDialog.filename"
            @keyup.enter="saveName"
          />
        </label>
        <div class="modal-actions naming-actions">
          <button class="btn" :disabled="savingName" @click="closeNameDialog">
            {{ nameDialog.isNew ? '稍后再说' : '取消' }}
          </button>
          <button class="btn primary" :disabled="savingName" @click="saveName">
            {{ savingName ? '保存中…' : '保存名称' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
