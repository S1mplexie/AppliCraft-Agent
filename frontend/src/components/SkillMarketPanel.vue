<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api/client'
import { formatImportedAt } from '../utils/format'
import type { SkillDetail, SkillInfo, TabKey } from '../types'

const props = defineProps<{
  skills: SkillInfo[]
  selectedSkillIds: string[]
}>()
const emit = defineEmits<{
  refresh: []
  go: [tab: TabKey]
  'update:selectedSkillIds': [ids: string[]]
}>()

type SkillEdit = { id: string; name: string; description: string; filename: string }

const fileInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
const localMsg = ref('')
const localError = ref(false)
const detail = ref<SkillDetail | null>(null)
const detailLoading = ref(false)
const showExamples = ref(false)
// 导入成功后才弹出信息填写框；列表里的「编辑」复用同一弹窗。
const skillNaming = ref(false)
const skillNamingIsNew = ref(false)
const skillEdits = ref<SkillEdit[]>([])
const savingSkillNames = ref(false)

const builtin = computed(() => props.skills.filter((s) => s.origin === 'builtin'))
const imported = computed(() => props.skills.filter((s) => s.origin === 'user'))
const selected = ref<string[]>([...props.selectedSkillIds])
watch(() => props.selectedSkillIds, (v) => { selected.value = [...v] })

function flash(message: string, error = false) {
  localMsg.value = message
  localError.value = error
  window.setTimeout(() => { localMsg.value = '' }, 4200)
}

function toggleSkill(id: string) {
  const idx = selected.value.indexOf(id)
  if (idx === -1) selected.value.push(id)
  else selected.value.splice(idx, 1)
  emit('update:selectedSkillIds', [...selected.value])
}

function triggerUpload() {
  if (!importing.value) fileInput.value?.click()
}

function focusFirstSkillName() {
  void nextTick(() => {
    document.querySelector<HTMLInputElement>('.skill-naming-modal input')?.focus()
  })
}

async function handleFile(file: File) {
  if (importing.value) return
  importing.value = true
  try {
    const result = await api.importSkill(file)
    // 先让列表立刻出现新技能，再弹窗补名称与简介；跳过也不影响使用。
    emit('refresh')
    flash(`已导入 ${result.imported} 个技能`)
    if (!result.items.length) return
    skillEdits.value = result.items.map((s) => ({
      id: s.id,
      name: s.name || '',
      description: s.description || '',
      filename: s.filename || '',
    }))
    skillNamingIsNew.value = true
    skillNaming.value = true
    focusFirstSkillName()
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    importing.value = false
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

function openSkillNaming(skill: SkillInfo) {
  skillEdits.value = [{
    id: skill.id,
    name: skill.name || '',
    description: skill.description || '',
    filename: skill.filename || '',
  }]
  skillNamingIsNew.value = false
  skillNaming.value = true
  focusFirstSkillName()
}

function closeSkillNaming() {
  if (savingSkillNames.value) return
  if (skillNamingIsNew.value) flash('已保留导入时的默认信息，之后可点「编辑」修改')
  skillNaming.value = false
}

async function saveSkillNames() {
  if (savingSkillNames.value || !skillEdits.value.length) return
  savingSkillNames.value = true
  try {
    await Promise.all(skillEdits.value.map((item) =>
      api.updateSkill(item.id, item.name, item.description)))
    flash('技能信息已保存')
    skillNaming.value = false
    emit('refresh')
  } catch (error) {
    flash((error as Error).message, true)
    // 批量保存可能部分成功，刷新列表让用户看到实际结果。
    emit('refresh')
  } finally {
    savingSkillNames.value = false
  }
}

async function openDetail(id: string) {
  detailLoading.value = true
  detail.value = null
  showExamples.value = false
  try {
    detail.value = await api.skillDetail(id)
  } catch (error) {
    flash((error as Error).message, true)
  } finally {
    detailLoading.value = false
  }
}

async function removeSkill(skill: SkillInfo) {
  if (!confirm(`删除导入的技能「${skill.name}」？已生成文书中的使用记录仍会保留。`)) return
  try {
    await api.deleteSkill(skill.id)
    const next = selected.value.filter((id) => id !== skill.id)
    selected.value = next
    emit('update:selectedSkillIds', [...next])
    flash('已删除技能')
    emit('refresh')
  } catch (error) {
    flash((error as Error).message, true)
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>Skill 市场</h1>
        <p>选用系统内置的申请文书写作技能，或导入你自己的 SKILL.md / 技能包；勾选后在生成文书时作为写法约束生效</p>
      </div>
      <span class="hint">已选 {{ selected.length }} 个技能 · <button class="link" @click="emit('go', 'generate')">去生成文书</button></span>
    </div>

    <div v-if="localMsg" class="lib-toast" :class="{ error: localError }">{{ localMsg }}</div>

    <!-- 导入 -->
    <section class="card">
      <div class="card-head"><h2>导入技能</h2><span class="hint">单个 .md / .txt，或含多个 SKILL.md 的 .zip，≤ 1 MB</span></div>
      <div class="upload-zone" @click="triggerUpload" @dragover.prevent @drop.prevent="onDrop">
        <input
          ref="fileInput" type="file" accept=".md,.markdown,.txt,.zip"
          style="display: none" @change="onFile"
        />
        <div class="upload-inner">
          <span class="upload-icon">⬆</span>
          <strong>{{ importing ? '解析中…' : '点击或拖拽文件到此处导入' }}</strong>
          <small class="hint">支持带 frontmatter 的 SKILL.md；zip 包内每个 SKILL.md 会成为一个独立技能</small>
        </div>
      </div>
      <p class="hint naming-lead">
        导入成功后会弹出信息框，逐一填写技能名称和简介；也可以跳过，之后在列表里点「编辑」补填。
      </p>
      <p class="hint skill-lead">
        技能只提供「怎么写」的方法论，不会被当作申请人的事实；生成时事实清单与字数要求始终优先。
      </p>
    </section>

    <!-- 系统内置 -->
    <section class="card">
      <div class="card-head">
        <h2>系统内置技能 · {{ builtin.length }} 个</h2>
        <span class="hint">来自研究生申请文书写作技能包，全站只读</span>
      </div>
      <div v-if="!builtin.length" class="mini-empty"><strong>暂无内置技能</strong></div>
      <div v-else class="skill-grid">
        <article v-for="skill in builtin" :key="skill.id" class="skill-card" :class="{ on: selected.includes(skill.id) }">
          <div class="skill-card-head">
            <span class="tag skill-origin">内置</span>
            <strong>{{ skill.name }}</strong>
          </div>
          <p class="skill-desc">{{ skill.description }}</p>
          <div class="skill-tags">
            <span v-for="tag in skill.tags || []" :key="tag" class="tag field-tag">{{ tag }}</span>
          </div>
          <small class="hint">{{ skill.name_en }} · 方法论 {{ skill.char_count }} 字</small>
          <div class="skill-actions">
            <label class="skill-check">
              <input type="checkbox" :checked="selected.includes(skill.id)" @change="toggleSkill(skill.id)" />
              用于生成
            </label>
            <button class="link" @click="openDetail(skill.id)">查看方法论</button>
          </div>
        </article>
      </div>
    </section>

    <!-- 我导入的 -->
    <section class="card">
      <div class="card-head">
        <h2>我导入的技能 · {{ imported.length }} 个</h2>
        <button class="btn small" :disabled="importing" @click="triggerUpload">{{ importing ? '解析中…' : '继续导入' }}</button>
      </div>
      <div v-if="!imported.length" class="mini-empty">
        <strong>还没有导入技能</strong>
        <span>可以上传单个 SKILL.md，或把整个技能目录打包成 zip 一次导入多个</span>
      </div>
      <ul v-else class="ref-doc-list">
        <li v-for="skill in imported" :key="skill.id" class="ref-doc-item" :class="{ 'skill-selected': selected.includes(skill.id) }">
          <div class="ref-doc-main">
            <strong>{{ skill.name }}</strong>
            <small>{{ skill.description || skill.filename }}</small>
            <small class="import-time">导入时间：{{ formatImportedAt(skill.imported_at) }}</small>
            <small class="hint">{{ skill.filename }} · {{ skill.char_count }} 字<span v-if="skill.has_examples"> · 含示例</span></small>
          </div>
          <div class="ref-doc-actions">
            <label class="skill-check">
              <input type="checkbox" :checked="selected.includes(skill.id)" @change="toggleSkill(skill.id)" />
              用于生成
            </label>
            <button class="link" @click="openDetail(skill.id)">查看</button>
            <button class="link" @click="openSkillNaming(skill)">编辑</button>
            <button class="link danger" @click="removeSkill(skill)">删除</button>
          </div>
        </li>
      </ul>
    </section>

    <!-- 技能详情 -->
    <div v-if="detail || detailLoading" class="modal-mask" @click.self="detail = null">
      <div class="modal skill-modal">
        <div class="card-head">
          <h2>{{ detail?.name || '正在读取技能…' }}</h2>
          <button class="link" @click="detail = null">关闭</button>
        </div>
        <p class="hint">{{ detail?.description }}</p>
        <div v-if="detailLoading" class="hint">读取中…</div>
        <pre v-else class="skill-detail-body">{{ detail?.content }}</pre>
        <div v-if="detail?.examples">
          <button class="link" @click="showExamples = !showExamples">
            {{ showExamples ? '收起示例' : '展开配套示例' }}
          </button>
          <pre v-if="showExamples" class="skill-detail-body examples">{{ detail.examples }}</pre>
        </div>
      </div>
    </div>

    <!-- 导入后填写 / 事后编辑名称与简介 -->
    <div v-if="skillNaming" class="modal-mask" @click.self="closeSkillNaming">
      <div class="modal naming-modal skill-naming-modal">
        <div class="card-head">
          <h2>{{ skillNamingIsNew ? '技能已导入' : '编辑技能信息' }}</h2>
          <button class="link" @click="closeSkillNaming">关闭</button>
        </div>
        <p class="hint naming-hint">
          {{ skillNamingIsNew
            ? '填写名称与简介，便于之后在生成页区分；zip 包里的多个技能可一次填完。'
            : '修改后方法论正文与导入时间都不会变化。' }}
        </p>
        <div class="naming-list">
          <div v-for="(item, idx) in skillEdits" :key="item.id" class="naming-item">
            <div class="naming-file">
              {{ skillEdits.length > 1 ? `技能 ${idx + 1} · ` : '' }}{{ item.filename || '导入技能' }}
            </div>
            <label class="field">
              <span>技能名称</span>
              <input v-model="item.name" maxlength="80" placeholder="例如：我的 PS 写法规范" />
            </label>
            <label class="field">
              <span>简介（可选）</span>
              <textarea v-model="item.description" maxlength="300" rows="2" placeholder="一句话说明这个技能约束什么"></textarea>
            </label>
          </div>
        </div>
        <div class="modal-actions naming-actions">
          <button class="btn" :disabled="savingSkillNames" @click="closeSkillNaming">
            {{ skillNamingIsNew ? '稍后再说' : '取消' }}
          </button>
          <button class="btn primary" :disabled="savingSkillNames" @click="saveSkillNames">
            {{ savingSkillNames ? '保存中…' : '保存信息' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
