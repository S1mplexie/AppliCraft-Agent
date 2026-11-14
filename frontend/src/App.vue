<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import ProfileForm from './components/ProfileForm.vue'
import GeneratePanel from './components/GeneratePanel.vue'
import DocumentLibrary from './components/DocumentLibrary.vue'
import LibraryPanel from './components/LibraryPanel.vue'
import SkillMarketPanel from './components/SkillMarketPanel.vue'
import ProjectsPanel from './components/ProjectsPanel.vue'
import SettingsView from './components/SettingsView.vue'
import MatchPanel from './components/MatchPanel.vue'
import AuthView from './components/AuthView.vue'
import ProfileSwitcher from './components/ProfileSwitcher.vue'
import SystemProgramPicker from './components/SystemProgramPicker.vue'
import { api, onUnauthorized } from './api/client'
import {
  demoProfile, emptyProfile, systemProgramToTarget,
  type AppConfig, type ApplicantProfile, type ApplicationProject, type AuthResponse, type AuthUser,
  type DocumentDetail, type DocumentMeta, type GeneratePayload, type Issue,
  type KnowledgeRef, type LocalLLMConfig, type NodeEvent, type ProfileSection, type ProfileSummary, type QuotaInfo,
  type RegenPayload, type ReferenceDoc, type ResumeParseResult, type SkillInfo,
  type SystemProgram, type TabKey, type UserLLMConfig,
} from './types'

/** 一级导航：按工作流分组的左侧栏。申请看板（board）已下沉为「项目管理」内部的视图切换，不再单独占一个顶级 tab。 */
const NAV_GROUPS: { label: string; tabs: { key: TabKey; label: string }[] }[] = [
  { label: '申请准备', tabs: [
    { key: 'profile', label: '申请人档案' },
    { key: 'match', label: '选校评估' },
    { key: 'projects', label: '项目管理' },
  ]},
  { label: '文书', tabs: [
    { key: 'generate', label: '生成文书' },
    { key: 'documents', label: '文书库' },
  ]},
  { label: '素材', tabs: [
    { key: 'library', label: '参考文档库' },
    { key: 'skills', label: 'Skill 市场' },
  ]},
  { label: '设置', tabs: [
    { key: 'settings', label: '设置' },
  ]},
]
const ALL_TABS = NAV_GROUPS.flatMap(g => g.tabs)
function tabFromHash(): TabKey {
  const key = window.location.hash.replace(/^#\/?/, '')
  return ALL_TABS.some(tab => tab.key === key) ? key as TabKey : 'profile'
}

const activeTab = ref<TabKey>('profile')
const profileSection = ref<ProfileSection>('basics')
const config = ref<AppConfig | null>(null)
const user = ref<AuthUser | null>(null)
const quota = ref<QuotaInfo | null>(null)
// 我的大模型 API（BYOK）：脱敏配置 + 当前生效来源，登录后加载。
const myLlm = ref<UserLLMConfig | null>(null)
const effectiveModel = computed(() => myLlm.value?.effective_model || config.value?.llm_model || '')
const llmReady = computed(() =>
  myLlm.value ? myLlm.value.effective_source !== 'none' : !!config.value?.llm_configured,
)
// 系统共享 Key 的免费额度：管理员与自带 Key 用户 unlimited，其余账号每天有限次。
const freeRemaining = computed(() =>
  myLlm.value?.system_key_remaining ?? quota.value?.system_key_remaining ?? null,
)
const billingUnlimited = computed(() => !!(myLlm.value?.unlimited ?? quota.value?.unlimited))
// 悬浮球反馈弹窗形态：管理员查看全部反馈，普通用户提交建议。
const isAdmin = computed(() => !!(myLlm.value?.is_admin || quota.value?.source === 'admin'))
// 选校评估需要可用的大模型：本地版=已配本地 Key；网页版=系统 Key 已配或自有 Key/管理员。
const llmConfigured = computed(() => {
  if (standalone.value) return myLlm.value?.effective_source === 'personal'
  return !!(
    config.value?.llm_configured ||
    myLlm.value?.effective_source === 'personal' ||
    isAdmin.value
  )
})

const freeExhausted = computed(() =>
  !billingUnlimited.value && freeRemaining.value !== null && freeRemaining.value <= 0,
)
const quotaLabel = computed(() => {
  if (standalone.value) return '本地部署 · 不限次数'
  if (myLlm.value?.is_admin || quota.value?.source === 'admin') return '管理员 · 不限次数'
  if (billingUnlimited.value) return '自有 Key · 不限次数'
  return `今日免费剩 ${freeRemaining.value ?? quota.value?.remaining ?? 0} 次`
})
const authReady = ref(false)
/** 本地部署版（standalone）：免登录、单用户、用自己的 Key；由 /api/config 的 standalone 字段驱动。 */
const standalone = computed(() => !!config.value?.standalone)
const profiles = ref<ProfileSummary[]>([])
const profile = ref<ApplicantProfile>(emptyProfile())
const currentProfileId = ref('')
const documents = ref<DocumentMeta[]>([])
const activeDoc = ref<DocumentDetail | null>(null)
// 参考文档库：用户上传的参考文档 + 系统自带港新项目信息。
const references = ref<ReferenceDoc[]>([])
const selectedReferenceIds = ref<string[]>([])
const systemPrograms = ref<SystemProgram[]>([])
// 系统项目库 → 当前档案目标项目：选择器状态与已导入 id（去重 / 已在目标项目标记）。
const pickerOpen = ref(false)
const pickerKey = ref(0)
const pickerPreselected = ref<string[]>([])
const existingTargetIds = computed(() => (profile.value.target_programs || [])
  .map(t => t.source_program_id || '')
  .filter(Boolean))
// 项目管理：当前档案的申请项目列表（切档案时刷新，未归组文书标「未分组」）。
const projects = ref<ApplicationProject[]>([])
// Skill 市场：内置 + 本人导入的技能，勾选后在生成时作为写法约束注入。
const skills = ref<SkillInfo[]>([])
const selectedSkillIds = ref<string[]>([])
const events = ref<NodeEvent[]>([])
const issues = ref<Issue[]>([])
const outline = ref<any[]>([])
const warnings = ref<string[]>([])
// 数字待核对：verify 节点每轮复检覆盖更新（不累积），与全局 warnings 的累加语义不同。
const numericWarnings = ref<string[]>([])
const score = ref<number | null>(null)
const dimensions = ref<Record<string, number> | null>(null)
// 校验结论三态：passed / needs_review / factual_risk（旧文档无该字段时由组件回退）。
const verdict = ref<string | null>(null)
const knowledge = ref<KnowledgeRef | null>(null)
const generating = ref(false)
// 大纲预检：handleGenerate 先规划大纲并展示给用户确认 / 微调，确认后再正式起草。
// planReview 非空即表示处于「等待用户确认大纲」阶段，此时 generating 为假。
const planReview = ref<{
  outline: any[]
  evidence: Record<string, string>
  warnings: string[]
  payload: GeneratePayload
  planError?: string
} | null>(null)
const planOutline = ref<any[]>([])      // 用户可编辑的副本
const planning = ref(false)              // 正在调用 /generate/plan
// 确定性后检指标：verify 节点随事件上报，供「事实校验」页展示自检行。
const wordCount = ref<number | null>(null)
const placeholderCount = ref<number | null>(null)
// 按审核建议重新生成：文档查看器里的反馈框触发，SSE 复用同一套轨迹展示。
const regenerating = ref(false)
const regenStage = ref('')
const saveState = ref('修改后自动保存')
const toastMsg = ref('')
const toastError = ref(false)
// 档案管理浮层：全站只有这一个切换/新建/改名/删除入口。
const switcherOpen = ref(false)
// 文书库默认只看当前档案；切成「全部」才能看到已删除档案遗留的文书。
const docScope = ref<'current' | 'all'>('current')
// 简历上传解析：隐藏 file input + 解析结果变更清单弹窗。
const resumeFileInput = ref<HTMLInputElement | null>(null)
const resumeUploading = ref(false)
const resumeModalOpen = ref(false)
const resumeChanges = ref<string[]>([])

let loading = false
let switching = false
let pendingSave = false
let saveTimer: number | undefined
let toastTimer: number | undefined

async function refreshQuota() {
  // 评估扣费后同步顶栏剩余次数；失败静默（下一次操作会再刷）。
  if (standalone.value) { await loadLocalLlm(); return }
  try {
    quota.value = (await api.me()).quota
  } catch { /* 静默 */ }
}

function toast(message: string, error = false) {
  toastMsg.value = message
  toastError.value = error
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toastMsg.value = ''), 4200)
}

function goTab(tab: TabKey) { activeTab.value = tab }
function syncHash() {
  // 未登录时保持干净的入口地址，避免初次访问被写成 #/profile 之类的内部路由。
  if (!user.value) return
  const target = `#/${activeTab.value}`
  if (window.location.hash !== target) window.location.hash = target
}
function onHashChange() { activeTab.value = tabFromHash() }
watch(activeTab, syncHash)

/** 每个账号各自记住上次使用的档案；退出后重新登录不会跳回第一份。 */
function rememberKey() {
  return `applicraft.profile_id.${user.value?.email || 'guest'}`
}

function resetWorkspace() {
  profiles.value = []
  profile.value = emptyProfile()
  currentProfileId.value = ''
  documents.value = []
  projects.value = []
  activeDoc.value = null
  events.value = []; issues.value = []; outline.value = []; warnings.value = []
  numericWarnings.value = []
  score.value = null; dimensions.value = null; knowledge.value = null
  regenerating.value = false
  regenStage.value = ''
  window.clearTimeout(saveTimer)
  pendingSave = false
  switcherOpen.value = false
  docScope.value = 'current'
}

onUnauthorized(() => {
  user.value = null
  quota.value = null
  myLlm.value = null
  references.value = []
  selectedReferenceIds.value = []
  skills.value = []
  selectedSkillIds.value = []
  resetWorkspace()
  toast('登录已失效，请重新登录', true)
})

async function loadProfiles() {
  profiles.value = (await api.listProfiles()).items
}

async function loadDocuments() {
  // 「全部」范围不传 profile_id，可看到已删除档案遗留的文书。
  const scopeId = docScope.value === 'current' ? currentProfileId.value : ''
  if (docScope.value === 'current' && !scopeId) { documents.value = []; return }
  documents.value = (await api.listDocuments(scopeId || undefined)).items
}

async function loadReferences() {
  try { references.value = (await api.listReferences()).items } catch { references.value = [] }
}
async function loadSystemPrograms() {
  try { systemPrograms.value = (await api.listSystemPrograms()).items } catch { systemPrograms.value = [] }
}
async function loadSkills() {
  try { skills.value = (await api.listSkills()).items } catch { skills.value = [] }
}
async function loadProjects() {
  // 项目挂在档案之下：没有当前档案时清空即可，不发请求。
  try { projects.value = currentProfileId.value ? (await api.listProjects(currentProfileId.value)).items : [] }
  catch { projects.value = [] }
}
async function loadMyLlm() {
  try { myLlm.value = await api.getMyLlm() } catch { myLlm.value = null }
}

/** 把后端 /settings/llm 的脱敏配置映射成 UserLLMConfig 形状，复用既有面板与顶栏逻辑。 */
function localToUserLlm(local: LocalLLMConfig): UserLLMConfig {
  return {
    has_key: local.configured,
    api_key_hint: local.api_key_hint,
    base_url: local.base_url,
    model: local.model,
    updated_at: '',
    effective_source: local.configured ? 'personal' : 'none',
    effective_model: local.model,
    effective_base_url: local.base_url,
    allow_personal_llm_keys: true,
    require_personal_llm_key: false,
    system_llm_configured: local.configured,
    unlimited: true,
    system_key_daily_limit: 0,
    system_key_remaining: null,
  }
}
async function loadLocalLlm() {
  // 本地版走 /settings/llm（落盘 data/local_llm.json），不依赖登录态。
  try {
    myLlm.value = localToUserLlm(await api.getLocalLlm())
  } catch {
    myLlm.value = localToUserLlm({ base_url: '', api_key_hint: '', model: '', configured: false })
  }
}

/** 设置页「我的大模型 API」改动后刷新顶栏生效模型：本地版与网页版走不同接口。 */
async function refreshLlmConfig() {
  if (standalone.value) await loadLocalLlm()
  else await loadMyLlm()
}

/** 本地版没有「登录」概念：直接加载全站列表与本地 LLM 配置，再进入档案。 */
async function enterWorkspaceLocal() {
  await Promise.all([loadReferences(), loadSystemPrograms(), loadSkills(), loadLocalLlm()])
  await loadProfiles()
  const remembered = localStorage.getItem(rememberKey()) || ''
  const target = profiles.value.some(p => p.id === remembered)
    ? remembered
    : profiles.value[0]?.id || ''
  if (target) await selectProfile(target)
  else await createProfile({ switchToProfile: false })
}

/** 生成完成后同时刷新配额与个人配置：免费次数是服务端按当日日志算出来的。 */
async function refreshBilling() {
  if (standalone.value) { await loadLocalLlm(); return }
  try { quota.value = (await api.me()).quota } catch { /* 刷新失败不打断流程 */ }
  await loadMyLlm()
}

function setDocScope(scope: 'current' | 'all') {
  if (docScope.value === scope) return
  docScope.value = scope
  activeDoc.value = null
  void loadDocuments()
  toast(scope === 'all' ? '已显示全部档案的文书' : '已只显示当前档案的文书')
}

async function saveProfile(silent = false) {
  if (!currentProfileId.value) return
  window.clearTimeout(saveTimer)
  try {
    saveState.value = '正在保存…'
    await api.updateProfile(currentProfileId.value, profile.value)
    pendingSave = false
    saveState.value = `已保存 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`
    if (!silent) toast('档案已保存')
    await loadProfiles()
  } catch (error) {
    saveState.value = '保存失败，请重试'
    toast((error as Error).message, true)
  }
}

// 自动保存唯一事实来源；档案正在载入时不触发保存。
// 注意：本地部署版（standalone）user 恒为 null，不能拿它当自动保存开关，否则本地版永远不保存。
watch(profile, () => {
  if (loading || !currentProfileId.value) return
  pendingSave = true
  saveState.value = '有未保存的修改…'
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => void saveProfile(true), 900)
}, { deep: true })

// 参考文档被删除后，清理仍勾选中的失效 id，避免生成时引用不存在的文档。
watch(references, () => {
  const ids = new Set(references.value.map((r) => r.id))
  selectedReferenceIds.value = selectedReferenceIds.value.filter((id) => ids.has(id))
}, { deep: true })

// 导入的技能被删除后同样清理勾选，避免把不存在的技能 id 发给后端。
watch(skills, () => {
  const ids = new Set(skills.value.map((s) => s.id))
  selectedSkillIds.value = selectedSkillIds.value.filter((id) => ids.has(id))
}, { deep: true })

/** 切换档案前把上一份档案尚未落盘的编辑强制保存，避免静默丢失。 */
async function flushPendingSave() {
  window.clearTimeout(saveTimer)
  if (pendingSave && currentProfileId.value) await saveProfile(true)
}

/** 旧版给「目标项目 · 地区」预置过英文占位值；载入档案时统一改为中文标签并落盘一次。
 *  只处理完全相等的哨兵值，用户自己写的内容不会被改写。 */
function normalizeLegacyRegions(data: ApplicantProfile): boolean {
  const legacy: Record<string, string> = { 'Hong Kong, China': '中国香港', Singapore: '新加坡' }
  let changed = false
  for (const t of data.target_programs || []) {
    if (legacy[t.region]) { t.region = legacy[t.region]; changed = true }
  }
  return changed
}

async function selectProfile(id: string) {
  if (!id || id === currentProfileId.value || switching) { switcherOpen.value = false; return }
  if (generating.value) { toast('生成进行中，暂不能切换档案', true); return }
  switching = true
  await flushPendingSave()
  loading = true
  try {
    const data = await api.getProfile(id)
    profile.value = data
    currentProfileId.value = id
    localStorage.setItem(rememberKey(), id)
    if (normalizeLegacyRegions(profile.value)) {
      void saveProfile(true)
      toast('已把旧版预填的地区改为中文标签，可在「目标项目」核对')
    }
    activeDoc.value = null
    events.value = []; issues.value = []; outline.value = []; warnings.value = []
    saveState.value = '已载入档案'
    await loadDocuments()
    await loadProjects()
    await nextTick()
  } catch (error) {
    toast((error as Error).message, true)
  } finally {
    await nextTick()
    loading = false
    switching = false
  }
}

interface CreateOptions { label?: string; withDemo?: boolean; switchToProfile?: boolean; importedProgramIds?: string[] }

async function createProfile(options: CreateOptions = {}) {
  if (generating.value) { toast('生成进行中，暂不能新建档案', true); return }
  try {
    const withDemo = !!options.withDemo
    const base = withDemo ? demoProfile() : emptyProfile()
    // 创建时就能命名，避免多份「未命名档案」分不清。
    base.label = options.label?.trim() || `我的申请档案 ${profiles.value.length + 1}`
    // 创建时支持从系统自带项目导入目标院校：勾选的官方项目直接写入档案「目标项目」。
    const imported = (options.importedProgramIds || [])
      .map(id => systemPrograms.value.find(p => p.program_id === id))
      .filter((p): p is SystemProgram => !!p)
    if (imported.length) base.target_programs = imported.map(systemProgramToTarget)
    const saved = await api.createProfile(base)
    await loadProfiles()
    await selectProfile(saved.id)
    switcherOpen.value = false
    toast(withDemo
      ? '已载入示例档案，请替换为真实信息后再生成'
      : `已创建「${base.label}」${imported.length ? `，并导入 ${imported.length} 个目标项目` : ''}`)
    if (options.switchToProfile !== false) activeTab.value = 'profile'
  } catch (error) {
    toast((error as Error).message, true)
  }
}

/** 打开系统项目库选择器；档案页传空数组，参考文档库单个项目点进来时预选该项。 */
function openTargetPicker(ids: string[] = []) {
  if (!systemPrograms.value.length) { toast('系统项目库尚未加载，请刷新后重试', true); return }
  pickerPreselected.value = ids
  pickerKey.value += 1          // 每次打开重新挂载，保证搜索/筛选/勾选都是干净状态
  pickerOpen.value = true
}

/** 把勾选的官方项目写入当前档案的目标项目；已导入的自动跳过，并立即落盘。 */
async function importTargetPrograms(ids: string[]) {
  const existing = new Set(existingTargetIds.value)
  const fresh = ids
    .map(id => systemPrograms.value.find(p => p.program_id === id))
    .filter((p): p is SystemProgram => !!p && !existing.has(p.program_id))
  pickerOpen.value = false
  if (!fresh.length) { toast('所选项目都已在目标项目中', true); return }
  if (!profile.value.target_programs) profile.value.target_programs = []
  profile.value.target_programs.push(...fresh.map(systemProgramToTarget))
  activeTab.value = 'profile'
  profileSection.value = 'programs'
  toast(`已导入 ${fresh.length} 个目标项目，请补充课程要点与契合点`)
  // 自动保存有 900ms 防抖，这里立即落盘，避免刚导入就切档案 / 关页面时丢失。
  await saveProfile(true)
}

async function renameProfile(id: string, label: string) {
  const next = label.trim()
  if (!id || !next) return
  try {
    if (id === currentProfileId.value) {
      await flushPendingSave()
      loading = true               // 防止 label 赋值再排一次自动保存
      profile.value.label = next
      await nextTick()
      loading = false
      await saveProfile(false)
    } else {
      const data = await api.getProfile(id)
      data.label = next
      await api.updateProfile(id, data)
      await loadProfiles()
      toast('档案已改名')
    }
  } catch (error) {
    toast((error as Error).message, true)
  } finally {
    loading = false
  }
}

async function removeProfile(id: string) {
  if (!id || switching) return
  if (generating.value) { toast('生成进行中，暂不能删除档案', true); return }
  const target = profiles.value.find(item => item.id === id)
  try {
    if (id === currentProfileId.value) {
      window.clearTimeout(saveTimer)
      pendingSave = false
    }
    await api.deleteProfile(id)
    await loadProfiles()
    if (id === currentProfileId.value) {
      const next = profiles.value[0]
      if (next) {
        await selectProfile(next.id)
        toast(`已删除「${target?.label || '档案'}」，已切换到「${next.label}」`)
      } else {
        // 始终保持一份可用档案，避免出现「表单能填但永远不保存」的空状态。
        await createProfile({ switchToProfile: false })
        toast('已删除最后一份档案，并自动新建一份空白档案')
      }
    } else {
      toast(`已删除「${target?.label || '档案'}」`)
    }
  } catch (error) {
    toast((error as Error).message, true)
  }
}

async function triggerResumeUpload() {
  if (!currentProfileId.value) { toast('请先创建或选择档案', true); return }
  resumeFileInput.value?.click()
}

async function onResumeFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 重置，允许重复选择同一文件
  if (!file || !currentProfileId.value) return
  resumeUploading.value = true
  try {
    const result: ResumeParseResult = await api.parseResume(currentProfileId.value, file)
    // 原地合并，保证 ProfileForm（持有同一响应式对象）立即反映变化。
    Object.assign(profile.value, result.profile)
    resumeChanges.value = result.changes
    resumeModalOpen.value = true
    saveState.value = '简历解析已覆盖并保存'
    await loadProfiles()
    toast(
      result.changes.length
        ? `简历已解析，覆盖 ${result.changes.length} 处信息`
        : '简历已解析，未发现可覆盖的新信息',
    )
  } catch (error) {
    toast((error as Error).message, true)
  } finally {
    resumeUploading.value = false
  }
}

async function handleGenerate(payload: GeneratePayload) {
  if (!currentProfileId.value) { toast('请先创建或选择档案', true); return }
  // 阶段一：先规划大纲（不消耗额度），展示给用户确认 / 微调后再起草。
  planning.value = true
  planReview.value = null
  try {
    await saveProfile(true)
    const plan = await api.generatePlan({ ...payload, profile_id: currentProfileId.value })
    planOutline.value = JSON.parse(JSON.stringify(plan.outline || []))
    planReview.value = {
      outline: plan.outline || [],
      evidence: plan.evidence || {},
      warnings: plan.warnings || [],
      payload: { ...payload, profile_id: currentProfileId.value },
    }
  } catch (error) {
    toast((error as Error).message, true)
  } finally {
    planning.value = false
  }
}

/** 阶段二：用户确认大纲后，带 outline 正式生成。edited 为空表示沿用模型规划的大纲。 */
async function startGenerationWithOutline(edited: any[] | null) {
  const pr = planReview.value
  if (!pr) return
  const payload = { ...pr.payload, outline: edited ?? pr.outline }
  planReview.value = null
  events.value = []; issues.value = []; outline.value = []; warnings.value = []
  numericWarnings.value = []; wordCount.value = null; placeholderCount.value = null
  score.value = null; dimensions.value = null; knowledge.value = null
  verdict.value = null
  generating.value = true
  try {
    const meta = await api.generateStream(payload, (envelope) => {
      if (envelope.event !== 'node') return
      const data = envelope.data as NodeEvent
      events.value.push(data)
      if (data.outline) outline.value = data.outline
      if (data.issues) issues.value = data.issues
      if (data.warnings?.length) warnings.value.push(...data.warnings)
      if (data.numeric_warnings) numericWarnings.value = data.numeric_warnings
      if (data.score != null) score.value = data.score
      if (data.dimensions) dimensions.value = data.dimensions
      if (data.knowledge) knowledge.value = data.knowledge
      if (data.verdict) verdict.value = data.verdict
      if (data.word_count != null) wordCount.value = data.word_count
      if (data.placeholder_count != null) placeholderCount.value = data.placeholder_count
    })
    await loadDocuments()
    await openDocument(meta.id)
    await refreshBilling()
    activeTab.value = 'documents'
    toast('生成完成，已在文书库中打开')
  } catch (error) {
    toast((error as Error).message, true)
  } finally {
    generating.value = false
  }
}

/** 用户在大纲预检里点击「确认并开始撰写」。 */
function confirmPlan() { startGenerationWithOutline(planOutline.value) }
/** 重新规划大纲（模型再生成一份结构）。 */
async function replan() {
  const pr = planReview.value
  if (!pr) return
  planning.value = true
  try {
    const plan = await api.generatePlan(pr.payload)
    planOutline.value = JSON.parse(JSON.stringify(plan.outline || []))
    planReview.value = {
      outline: plan.outline || [], evidence: plan.evidence || {},
      warnings: plan.warnings || [], payload: pr.payload,
    }
  } catch (error) { toast((error as Error).message, true) }
  finally { planning.value = false }
}
/** 跳过预检，直接让模型自行规划并起草（等同旧流程）。 */
function skipPlan() { startGenerationWithOutline(null) }

async function handleRegenerate(payload: RegenPayload) {
  const doc = activeDoc.value
  if (!doc || regenerating.value || generating.value) return
  if (!payload.feedback && !payload.issueFeedback.length) return
  regenerating.value = true
  regenStage.value = ''
  try {
    const meta = await api.regenerateStream(doc.meta.id, payload, (envelope) => {
      if (envelope.event !== 'node') return
      const data = envelope.data as NodeEvent
      // 轨迹里追加这一轮重生成事件，实时看到「应用建议→修订→复审→定稿」。
      events.value.push(data)
      regenStage.value = data.summary || ''
      if (data.issues) issues.value = data.issues
      if (data.warnings?.length) warnings.value.push(...data.warnings)
      if (data.numeric_warnings) numericWarnings.value = data.numeric_warnings
      if (data.score != null) score.value = data.score
      if (data.dimensions) dimensions.value = data.dimensions
      if (data.verdict) verdict.value = data.verdict
    })
    await loadDocuments()
    await openDocument(meta.id)
    await refreshBilling()
    toast(`已按建议重新生成，保存为 v${meta.version} 新版本`)
  } catch (error) {
    toast((error as Error).message, true)
  } finally {
    regenerating.value = false
    regenStage.value = ''
  }
}

async function openDocument(id: string) {
  try {
    activeDoc.value = await api.getDocument(id)
    const trace = activeDoc.value.trace || {}
    issues.value = trace.critique?.issues || []
    outline.value = trace.outline || []
    warnings.value = trace.warnings || []
    numericWarnings.value = trace.critique?.numeric_warnings || []
    score.value = trace.critique?.score ?? null
    dimensions.value = trace.critique?.dimensions ?? null
    verdict.value = trace.critique?.verdict
      ?? (issues.value.length ? 'needs_review' : 'passed')
    wordCount.value = trace.critique?.word_count ?? null
    placeholderCount.value = trace.critique?.placeholder_count ?? null
    knowledge.value = trace.knowledge ?? null
    events.value = (trace.events || []).map((e: any) => ({
      node: e.node, label: e.label || e.node, summary: e.summary,
      warnings: [], outline: null, issues: null, passed: null,
    }))
    activeTab.value = 'documents'
  } catch (error) {
    toast((error as Error).message, true)
  }
}

async function saveDocument(markdown: string) {
  if (!activeDoc.value) return
  try {
    await api.updateDocument(activeDoc.value.meta.id, markdown)
    await openDocument(activeDoc.value.meta.id)
    await loadDocuments()
    toast('已保存为新版本')
  } catch (error) {
    toast((error as Error).message, true)
  }
}

async function removeDocument(id: string) {
  if (!confirm('删除这份文档及其所有版本？')) return
  try {
    await api.deleteDocument(id)
    if (activeDoc.value?.meta.id === id) activeDoc.value = null
    await loadDocuments()
    toast('文档已删除')
  } catch (error) {
    toast((error as Error).message, true)
  }
}

async function enterWorkspace() {
  // 与档案无关的全站列表：登录与刷新两条路径都要加载，避免登录后列表为空。
  await Promise.all([
    loadReferences(), loadSystemPrograms(), loadSkills(), loadMyLlm(),
  ])
  await loadProfiles()
  const remembered = localStorage.getItem(rememberKey()) || ''
  const target = profiles.value.some(p => p.id === remembered)
    ? remembered
    : profiles.value[0]?.id || ''
  if (target) await selectProfile(target)
  else await createProfile({ switchToProfile: false })
}

async function onAuthed(payload: AuthResponse) {
  user.value = payload.user
  quota.value = payload.quota
  syncHash()
  resetWorkspace()
  try { await enterWorkspace() } catch (error) {
    toast(`载入档案失败：${(error as Error).message}`, true)
  }
}

async function logout() {
  try { await api.logout() } catch { /* 即使服务端失败也清理本地状态 */ }
  user.value = null
  quota.value = null
  myLlm.value = null
  references.value = []
  selectedReferenceIds.value = []
  skills.value = []
  selectedSkillIds.value = []
  resetWorkspace()
  toast('已退出登录')
}

onMounted(async () => {
  activeTab.value = tabFromHash()
  syncHash()
  window.addEventListener('hashchange', onHashChange)
  try {
    config.value = await api.config()
  } catch (error) {
    toast(`无法连接后端：${(error as Error).message}`, true)
  }
  if (standalone.value) {
    // 本地版免登录：以虚拟单用户直接进工作区，不调 /auth/me，也不渲染登录页。
    try {
      await enterWorkspaceLocal()
    } catch (error) {
      toast(`载入工作区失败：${(error as Error).message}`, true)
    }
  } else {
    try {
      const me = await api.me()
      user.value = me.user
      quota.value = me.quota
      await enterWorkspace()
    } catch {
      user.value = null
    }
  }
  authReady.value = true
})
onUnmounted(() => window.removeEventListener('hashchange', onHashChange))
</script>

<template>
  <!-- 首次访问（含会话检查中）直接渲染登录页，不再白屏等待 /api/auth/me 返回。
       本地部署版（standalone）免登录，跳过 AuthView，配置就绪后直接渲染工作区。 -->
  <AuthView
    v-if="!standalone && (!authReady || !user)"
    :allow-registration="config?.allow_registration ?? true"
    :system-key-limit="config?.system_key_daily_limit ?? 3"
    :checking="!authReady"
    @authed="onAuthed"
  />

  <div v-else-if="config" class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">A</span>
        <span class="brand-text"><strong>AppliCraft</strong><small>申请材料工作台</small></span>
      </div>
      <nav class="side-nav" aria-label="主导航">
        <div v-for="group in NAV_GROUPS" :key="group.label" class="side-group">
          <span class="side-group-label">{{ group.label }}</span>
          <button
            v-for="tab in group.tabs" :key="tab.key" class="side-item"
            :class="{ active: activeTab === tab.key }" @click="goTab(tab.key)"
          >
            <span class="side-label">{{ tab.label }}</span>
            <span v-if="tab.key === 'documents' && documents.length" class="side-num">{{ documents.length }}</span>
            <span v-if="tab.key === 'library' && references.length" class="side-num">{{ references.length }}</span>
            <span v-if="tab.key === 'skills' && selectedSkillIds.length" class="side-num">{{ selectedSkillIds.length }}</span>
            <span v-if="tab.key === 'generate' && generating" class="side-badge running-badge">生成中</span>
          </button>
        </div>
      </nav>
      <div class="sidebar-foot">
        <p>文书事实全部来自申请人档案。<br />生成后请人工核对再提交。</p>
      </div>
    </aside>

    <div class="main-col">
      <header class="topbar">
        <div class="topbar-center">
          <ProfileSwitcher
            v-model:open="switcherOpen" :profiles="profiles" :current-id="currentProfileId"
            :busy="generating" :system-programs="systemPrograms"
            @select="selectProfile" @create="createProfile"
            @rename="(payload) => renameProfile(payload.id, payload.label)"
            @remove="removeProfile"
          />
        </div>
        <div class="status">
          <span class="dot" :class="llmReady ? 'ok' : 'off'"></span>
          <span v-if="llmReady" class="model-name">{{ effectiveModel }}</span>
          <span v-else class="warn-text">未配置 API Key</span>
          <template v-if="standalone">
            <span class="badge ok byok-chip">本地部署版</span>
            <span class="hint">{{ quotaLabel }}</span>
          </template>
          <template v-else>
            <span v-if="myLlm?.is_admin || quota?.source === 'admin'" class="badge ok byok-chip">管理员</span>
            <span v-else-if="myLlm?.effective_source === 'personal'" class="badge ok byok-chip">自有 Key</span>
            <span v-if="quota" class="hint">{{ quotaLabel }}</span>
            <span class="hint user-name">{{ user.display_name || user.email }}</span>
            <button class="btn small" @click="logout">退出</button>
          </template>
        </div>
      </header>

      <div v-if="myLlm && myLlm.effective_source === 'none'" class="banner">
        当前账号还没有可用的 API Key，请到「设置 → 我的大模型 API」填入自己的 Key 后即可生成文书。
        <button class="btn small" @click="goTab('settings')">去配置</button>
      </div>
      <div v-else-if="freeExhausted" class="banner quota-banner">
        今日 {{ myLlm?.system_key_daily_limit ?? quota?.system_key_limit ?? 3 }} 次系统免费额度已用完。
        在「设置 → 我的大模型 API」填入自己的 Key 后即可继续不限次数生成，也可以明天再试。
        <button class="btn small" @click="goTab('settings')">去配置</button>
      </div>
      <div v-else-if="config && !standalone && !config.llm_configured && myLlm?.effective_source !== 'personal'" class="banner">
        {{ config.message }}
      </div>

      <main class="page-wrap">
        <!-- 申请人档案 -->
        <div v-show="activeTab === 'profile'" class="page-view">
          <div class="page profile-page">
            <div class="page-head">
              <div>
                <h1>申请人档案</h1>
                <p>所有文书的唯一事实来源，修改后自动保存</p>
              </div>
              <div class="head-actions">
                <button class="btn" :disabled="resumeUploading" @click="triggerResumeUpload">
                  {{ resumeUploading ? '解析中…' : '上传简历自动填充' }}
                </button>
                <button class="btn primary" @click="goTab('generate')">去生成文书</button>
                <button class="btn" @click="goTab('match')">选校评估</button>
              </div>
            </div>
            <ProfileForm
              :key="currentProfileId" :profile="profile" :section="profileSection"
              :save-state="saveState" :system-program-count="systemPrograms.length"
              @section-change="profileSection = $event" @save="saveProfile(false)"
              @import-targets="openTargetPicker()"
            />
          </div>
        </div>

        <!-- 选校评估 -->
        <div v-show="activeTab === 'match'" class="page-view">
          <MatchPanel
            :profile-id="currentProfileId" :profile="profile" :standalone="standalone"
            :llm-configured="llmConfigured"
            @quota-changed="refreshQuota" @toast="(m) => toast(m, false)"
          />
        </div>

        <!-- 项目管理（含「看板」视图切换） -->
        <div v-show="activeTab === 'projects'" class="page-view">
          <ProjectsPanel
            :profile-id="currentProfileId" :documents="documents" :system-programs="systemPrograms"
            @go="goTab" @refresh-docs="loadDocuments"
          />
        </div>

        <!-- 生成工作台 -->
        <div v-show="activeTab === 'generate'" class="page-view">
          <div class="page generate-page">
            <div class="page-head">
              <div>
                <h1>生成文书</h1>
                <p>当前档案「{{ profile.label || '未命名档案' }}」</p>
              </div>
              <div class="head-actions">
                <button class="btn" @click="goTab('profile')">检查档案</button>
                <button class="btn" @click="goTab('documents')">查看文书库</button>
              </div>
            </div>
            <!-- 切换档案时重挂载，清掉上一份档案的目标项目 / 推荐人选择。 -->
            <GeneratePanel
              :key="currentProfileId"
              :profile="profile" :profile-id="currentProfileId" :config="config" :my-llm="myLlm" :quota="quota"
              :standalone="standalone"
              :generating="generating" :planning="planning" :events="events" :issues="issues"
              :outline="outline" :warnings="warnings" :numeric-warnings="numericWarnings"
              :score="score" :dimensions="dimensions" :knowledge="knowledge" :verdict="verdict"
              :word-count="wordCount" :placeholder-count="placeholderCount"
              :references="references" :selected-reference-ids="selectedReferenceIds"
              :skills="skills" :selected-skill-ids="selectedSkillIds"
              @update:selected-reference-ids="selectedReferenceIds = $event"
              @update:selected-skill-ids="selectedSkillIds = $event"
              @generate="handleGenerate" @go="goTab"
              @refresh-references="loadReferences"
            />
          </div>
        </div>

        <!-- 大纲预检弹窗：确认 / 微调结构后再起草 -->
        <div v-if="planReview" class="plan-overlay" @click.self="skipPlan">
          <div class="plan-modal">
            <div class="plan-head">
              <h2>大纲预检</h2>
              <p>确认每段的结构与素材，或微调后再起草。改完后点「确认并开始撰写」。</p>
            </div>

            <div v-if="planReview.warnings.length" class="plan-warnings">
              <div v-for="(w, i) in planReview.warnings" :key="i">⚠ {{ w }}</div>
            </div>

            <div class="plan-list">
              <div v-for="(sec, i) in planOutline" :key="i" class="plan-section">
                <div class="plan-sec-head">
                  <span class="plan-idx">{{ String(i + 1).padStart(2, '0') }}</span>
                  <input v-model="sec.title" class="plan-title" placeholder="段落小标题" />
                  <div class="plan-sec-actions">
                    <button class="icon-btn" :disabled="i === 0" title="上移" @click="planOutline.splice(i - 1, 0, planOutline.splice(i, 1)[0])">↑</button>
                    <button class="icon-btn" :disabled="i === planOutline.length - 1" title="下移" @click="planOutline.splice(i + 1, 0, planOutline.splice(i, 1)[0])">↓</button>
                    <button class="icon-btn danger" title="删除该段" @click="planOutline.splice(i, 1)">×</button>
                  </div>
                </div>
                <textarea v-model="sec.specifics" class="plan-specifics" rows="2"
                  placeholder="本段要落地的具名事实（课程名 / 方法 / 数字 / 机构 / 工具）与具体反思" />
                <div v-if="sec.evidence_ids && sec.evidence_ids.length" class="plan-evidence">
                  <span class="pe-label">素材：</span>
                  <span v-for="eid in sec.evidence_ids" :key="eid" class="pe-chip">
                    {{ eid }}<small v-if="planReview.evidence[eid]"> · {{ planReview.evidence[eid] }}</small>
                  </span>
                </div>
              </div>
            </div>

            <div class="plan-foot">
              <button class="btn" :disabled="planning" @click="replan">
                {{ planning ? '规划中…' : '重新规划大纲' }}
              </button>
              <button class="btn" @click="skipPlan">跳过预检直接生成</button>
              <button class="btn primary" :disabled="!planOutline.length || planning" @click="confirmPlan">
                确认并开始撰写
              </button>
            </div>
          </div>
        </div>

        <!-- 参考文档库 -->
        <div v-show="activeTab === 'library'" class="page-view">
          <LibraryPanel
            :references="references" :system-programs="systemPrograms"
            :target-program-ids="existingTargetIds"
            @uploaded="loadReferences" @deleted="loadReferences"
            @go="goTab" @import-targets="openTargetPicker"
          />
        </div>

        <!-- Skill 市场 -->
        <div v-show="activeTab === 'skills'" class="page-view">
          <SkillMarketPanel
            :skills="skills" :selected-skill-ids="selectedSkillIds"
            @update:selected-skill-ids="selectedSkillIds = $event"
            @refresh="loadSkills" @go="goTab"
          />
        </div>

        <!-- 文书库 -->
        <div v-show="activeTab === 'documents'" class="page-view library-view">
          <DocumentLibrary
            :documents="documents" :document="activeDoc" :active-id="activeDoc?.meta.id || ''"
            :issues="issues" :outline="outline" :warnings="warnings" :scope="docScope"
            :regenerating="regenerating" :regen-stage="regenStage"
            @open="openDocument" @save="saveDocument" @remove="removeDocument"
            @regenerate="handleRegenerate"
            @go="goTab" @scope="setDocScope"
          />
        </div>

        <!-- 设置 -->
        <div v-show="activeTab === 'settings'" class="page-view">
          <SettingsView
            :user="user" :quota="quota" :config="config" :my-llm="myLlm" :profiles="profiles"
            :current-profile-id="currentProfileId" :save-state="saveState" :standalone="standalone"
            @manage="switcherOpen = true" @save="saveProfile(false)" @logout="logout"
            @refresh-llm="refreshLlmConfig"
          />
        </div>
      </main>
    </div>


    <!-- 系统项目库 → 当前档案目标项目：档案页与参考文档库共用的选择器 -->
    <SystemProgramPicker
      v-if="pickerOpen" :key="pickerKey"
      :programs="systemPrograms" :existing-ids="existingTargetIds"
      :preselected="pickerPreselected" :profile-label="profile.label"
      @close="pickerOpen = false" @import="importTargetPrograms"
    />

    <div v-if="toastMsg" class="toast" :class="{ error: toastError }">{{ toastMsg }}</div>

    <!-- 简历上传：隐藏 file input，由「上传简历自动填充」按钮触发 -->
    <input
      ref="resumeFileInput" type="file" accept=".pdf,.docx,.txt,.md"
      style="display: none" @change="onResumeFile"
    />

    <!-- 简历解析结果：覆盖的信息清单 -->
    <div v-if="resumeModalOpen" class="modal-mask" @click.self="resumeModalOpen = false">
      <div class="modal resume-modal">
        <h3>简历解析完成</h3>
        <p class="resume-sub">已用简历内容覆盖以下档案信息，并已自动保存到服务端：</p>
        <ul v-if="resumeChanges.length" class="resume-changes">
          <li v-for="(c, i) in resumeChanges" :key="i">{{ c }}</li>
        </ul>
        <p v-else class="hint">未发现可覆盖的新信息，请确认简历内容或文件格式。</p>
        <div class="modal-actions">
          <button class="btn primary" @click="resumeModalOpen = false">知道了，去核对</button>
        </div>
      </div>
    </div>
  </div>
</template>
