export type DocType = 'cv' | 'ps' | 'recommendation'
export type Language = 'en' | 'zh'
/** 一级导航分区；与 URL hash 同步，刷新后仍能回到原来的工作台。 */
export type TabKey = 'profile' | 'match' | 'projects' | 'board' | 'generate' | 'library' | 'skills' | 'documents' | 'settings'
/** 档案表单的二级分区。 */
export type ProfileSection =
  'basics' | 'education' | 'experience' | 'credentials' | 'programs' | 'recommenders' | 'goals'

export interface Basics {
  name_en: string; name_zh: string; email: string; phone: string
  location: string; linkedin: string; github: string; personal_site: string
}
export interface Education {
  id: string; school: string; degree: string; major: string; gpa: string
  gpa_scale: string; gpa_average: string; ranking: string; start_date: string; end_date: string
  relevant_courses: string[]; thesis: string; highlights: string
}
export interface Experience {
  id: string; type: string; org: string; role: string; location: string
  start_date: string; end_date: string; bullets: string[]; tags: string[]
  related_recommender: string
}
export interface Award { id: string; title: string; issuer: string; date: string; detail: string }
export interface SkillGroup { id: string; category: string; items: string[] }
export interface TestScore { id: string; kind: string; total: string; breakdown: string; date: string }
export interface TargetProgram {
  id: string; university: string; program: string; degree_type: string
  region: string; intake: string; deadline: string; language_requirement: string
  curriculum_notes: string; faculty_notes: string; why_fit: string; notes: string
  /** 从系统项目库导入时记录来源 program_id，用于去重与「已在目标项目」标记；手工填写的条目为空。 */
  source_program_id?: string
}
export interface Recommender {
  id: string; name: string; title: string; affiliation: string; email: string
  relation: string; known_since: string; observed_strengths: string[]
  tone: string; notes: string
}
export interface ApplicantProfile {
  id: string; label: string; created_at: string; updated_at: string
  basics: Basics; education: Education[]; experiences: Experience[]
  publications: string[]; awards: Award[]; skill_groups: SkillGroup[]
  test_scores: TestScore[]; target_programs: TargetProgram[]; recommenders: Recommender[]
  career_goal: string; additional_notes: string; writing_constraints: string
}
export interface ProfileSummary { id: string; label: string; updated_at: string; name: string }
/** 申请项目：挂在档案之下，从知识库导入（imported）或自定义新建（custom）；
 *  生成的文书通过 project_id 归入项目，未归组文书在项目管理里标「未分组」。 */
export interface ApplicationProject {
  id: string; profile_id: string; name: string
  source: 'imported' | 'custom'
  system_program_id: string
  university: string; program: string; program_name_en: string; faculty: string
  degree_type: string;   region: string; intake: string; notes: string
  official_urls: string[]
  /** 申请截止日期（YYYY-MM-DD），留空表示未设置；申请看板据此做倒计时。 */
  deadline?: string
  /** 手动勾选的材料清单（成绩单 / 语言成绩 / 申请费）；PS/CV/推荐信由文书自动派生。 */
  materials?: Record<string, boolean>
  created_at: string; updated_at: string; document_count: number
}
export interface DocumentMeta {
  id: string; profile_id: string; doc_type: DocType; doc_type_label: string
  title: string; created_at: string; updated_at: string; version: number
  model: string; language: string; word_count: number
  bilingual?: boolean
  passed_verification: boolean; issue_count: number
  project_id?: string
}
export interface Issue {
  quote: string; type: string; reason: string; fix: string
}
/** 重新生成的审核建议：逐项建议（按待核项序号）+ 整体补充说明。 */
export interface RegenPayload {
  feedback: string
  issueFeedback: { index: number; suggestion: string }[]
}
/** 文书质量六维评分（1-5）与综合分（0-100）。 */
export interface Critique {
  passed?: boolean
  /** 三态结论：passed 已核验 / needs_review 建议复核 / factual_risk 事实风险。 */
  verdict?: string
  score?: number
  dimensions?: Record<string, number>
  issues?: Issue[]
  hard_issue_count?: number
  soft_issue_count?: number
  summary?: string
  numeric_warnings?: string[]
}
export interface KnowledgeSource { school: string; program: string; field: string; url: string }
export interface KnowledgeRef {
  sources: KnowledgeSource[]
  matched_program?: string
  context_chars?: number
  enabled?: boolean
  note?: string
}
/** 评审维度中文名，用于前端展示。 */
export const DIMENSION_LABELS: Record<string, string> = {
  factual_safety: '事实安全',
  program_fit: '项目契合',
  specificity: '论证具体',
  structure: '结构完整',
  tone_register: '语气语域',
  language_quality: '语言质量',
}
export interface DocumentDetail {
  meta: DocumentMeta
  markdown: string
  trace: {
    request?: GeneratePayload
    model?: string
    outline?: { title: string; goal: string; evidence_ids: string[] }[]
    critique?: Critique
    knowledge?: KnowledgeRef
    references?: { id: string; name: string; filename: string; included?: boolean; missing?: boolean }[]
    skills?: { id: string; name: string; included?: boolean; missing?: boolean; truncated?: boolean; origin?: string }[]
    events?: { node: string; summary: string; at: string; score?: number; dimensions?: Record<string, number> }[]
    warnings?: string[]
    revision_count?: number
    /** 按建议重生成：上一版质量分与分差，用于在评分明细里展示「较上轮 +N」。 */
    previous_score?: number | null
    score_delta?: number | null
    feedback?: string
    issue_feedback?: { index: number; suggestion: string }[]
  }
  versions: { name: string; markdown: string }[]
}
export interface AppConfig {
  version: string; llm_configured: boolean; llm_model: string; llm_base_url: string
  api_key_hint: string; doc_types: Record<string, string>; max_revisions: number; message: string
  allow_registration: boolean; daily_quota: number
  wechat_login_enabled?: boolean
  allow_personal_llm_keys?: boolean
  require_personal_llm_key?: boolean
  /** 非管理员每天可免费使用系统默认 Key 的次数；管理员 / 自带 Key 不受限。 */
  system_key_daily_limit?: number
  /** 本地部署版（免登录、单用户、用自己的 Key）为 true；网页版多租户为 false/缺失。 */
  standalone?: boolean
}
/** 用户自带大模型 Key（BYOK）：接口只返回脱敏信息，永不返回完整 Key。 */
export interface UserLLMConfig {
  has_key: boolean
  api_key_hint: string
  base_url: string
  model: string
  updated_at: string
  effective_source: 'personal' | 'system' | 'none'
  effective_model: string
  effective_base_url: string
  allow_personal_llm_keys: boolean
  require_personal_llm_key: boolean
  system_llm_configured: boolean
  /** 当前账号的计费口径（由 /api/me/llm 回显）。 */
  is_admin?: boolean
  unlimited?: boolean
  system_key_daily_limit?: number
  system_key_remaining?: number
}
export interface UserLLMPayload { base_url: string; model: string; api_key: string }
/** 本地部署版（standalone）的「我的大模型 API」配置：GET 返回脱敏信息，永不回传完整 Key。 */
export interface LocalLLMConfig {
  base_url: string
  api_key_hint: string
  model: string
  configured: boolean
}
/** 本地部署版保存 / 测试大模型配置时的请求体；api_key 留空表示沿用已保存的 Key。 */
export interface LocalLLMPayload { base_url: string; model: string; api_key: string }
export interface LLMTestResult { ok: boolean; message: string; model: string }
/** 常见 OpenAI 兼容端点预设：只帮用户填地址与模型名，Key 始终由本人输入。 */
export interface LLMProvider {
  id: string; label: string; base_url: string; model: string; hint: string
}
export const LLM_PROVIDERS: LLMProvider[] = [
  { id: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', hint: '官方直连 /v1，模型 deepseek-chat' },
  { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini', hint: '需可访问官方端点' },
  { id: 'moonshot', label: 'Moonshot', base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k', hint: '国内直连' },
  { id: 'dashscope', label: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', hint: '阿里云兼容模式' },
  { id: 'zhipu', label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', hint: '智谱开放平台 v4' },
]
export interface AuthUser {
  id: string; email: string; display_name: string; daily_quota: number; created_at: string
  is_admin?: boolean
}
/** 选校评估：模型对档案硬指标与项目要求的适配评估结果。 */
export interface MatchItem {
  program_id: string; school_name_zh: string; name_en: string; name_zh: string
  region: string; intake: string; deadline: string
  tier: 'gap' | 'reach' | 'match' | 'safety'; tier_label: string
  reasons: string[]; gaps: string[]
  language_note?: string; in_target: boolean
}
export interface MatchResult {
  results: MatchItem[]
  profile_snapshot: {
    gpa: string; gpa_average: string
    ielts_total: number | null; toefl_total: number | null
    notes: string[]; watermark_note: string
  }
  tier_order: string[]; tier_labels: Record<string, string>
  /** 评估计费来源（admin/personal/system）：仅 system 来源占用免费额度。 */
  billing_source: 'admin' | 'personal' | 'system'
  quota: QuotaInfo
}
/** used/limit/remaining 为旧的总量护栏；system_key_* 才是本次真正生效的计费口径。 */
export interface QuotaInfo {
  used: number; limit: number; remaining: number
  unlimited?: boolean
  source?: 'admin' | 'personal' | 'system'
  system_key_used?: number
  system_key_limit?: number
  system_key_remaining?: number
}
export interface AuthResponse { user: AuthUser; quota: QuotaInfo }
export interface GeneratePayload {
  profile_id: string; doc_type: DocType
  target_program_id: string | null; recommender_id: string | null
  language: Language; word_limit: number; tone: string
  emphasis: string[]; extra_instructions: string
  reference_doc_ids: string[]
  skill_ids: string[]
  /** 大纲预检确认过的段落结构；提供时后端跳过大纲规划直接起草。 */
  outline?: any[] | null
}
/** 大纲预检结果：模型规划的结构与素材图例，供用户确认 / 微调后再起草。 */
export interface GeneratePlanResult {
  outline: any[]
  evidence: Record<string, string>
  warnings: string[]
}
/** 用户上传的参考文档元信息（不含正文）。 */
export interface ReferenceDoc {
  id: string; name: string; filename: string; ext: string
  size: number; char_count: number; uploaded_at: string
}
/** Skill 市场：系统内置或用户导入的写作技能（列表视图，不含正文）。 */
export interface SkillInfo {
  id: string; origin: 'builtin' | 'user'
  name: string; name_en?: string; description: string
  category?: string; doc_types?: DocType[]; tags?: string[]
  char_count?: number; imported_at?: string; filename?: string
  has_examples?: boolean
}
/** 技能详情：完整方法论正文与可选示例。 */
export interface SkillDetail extends SkillInfo {
  content: string; examples?: string; instructions?: string
}
/** 系统自带的港新项目官方信息（来自知识库，只读）。 */
export interface SystemProgram {
  program_id: string; school_id: string; school_name_zh: string
  program_name_en: string; program_name_zh: string; faculty: string
  region: string; intake: string; official_urls: string[]; fields: string[]
}
/** 系统项目库条目 → 档案目标项目：只搬官方事实骨架，申请人自述与未核实字段一律留空。 */
export function systemProgramToTarget(p: SystemProgram): TargetProgram {
  // 知识库中文项目名可能带「（非官方译名）」标注，那是资料校验注记，不能写进文书事实。
  const zhName = (p.program_name_zh || '').replace(/[（(]非官方译名[）)]/g, '').trim()
  const notes = [
    p.program_name_en ? `官方英文名：${p.program_name_en}` : '',
    (p.official_urls || []).length ? `官方页面：${(p.official_urls || []).join('  ')}` : '',
  ].filter(Boolean).join('\n')
  return {
    id: uid(),
    source_program_id: p.program_id,
    university: p.school_name_zh || p.school_id,
    program: zhName || p.program_name_en,
    degree_type: '',
    region: p.region === 'HK' ? '中国香港' : p.region === 'SG' ? '新加坡' : '',
    intake: p.intake,
    deadline: '',
    language_requirement: '',
    curriculum_notes: '',
    faculty_notes: p.faculty,
    why_fit: '',
    notes,
  }
}

export interface NodeEvent {
  node: string; label: string; summary: string
  warnings: string[]; outline: any; issues: Issue[] | null; passed: boolean | null
  score?: number | null; dimensions?: Record<string, number> | null; knowledge?: KnowledgeRef | null
  /** verify 结论三态：passed（已核验）/ needs_review（建议复核）/ factual_risk（事实风险）。 */
  verdict?: string | null
  hard_issue_count?: number | null; soft_issue_count?: number | null
  /** verify 节点每轮复检覆盖更新：文中出现但事实清单没有的数字。 */
  numeric_warnings?: string[] | null
  /** 确定性后检指标：约 X 词（目标 Y）、[TO CONFIRM] 占位符个数。 */
  word_count?: number | null; word_limit?: number | null
  placeholder_count?: number | null; placeholder_overflow?: boolean | null
}
export interface ResumeParseResult {
  profile: ApplicantProfile
  changes: string[]
}
export interface StreamEnvelope { event: 'start' | 'node' | 'done' | 'error'; data: any }

export const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4)

export function emptyProfile(label = '我的申请档案'): ApplicantProfile {
  return {
    id: '', label, created_at: '', updated_at: '',
    basics: { name_en: '', name_zh: '', email: '', phone: '', location: '', linkedin: '', github: '', personal_site: '' },
    education: [], experiences: [], publications: [], awards: [], skill_groups: [],
    test_scores: [], target_programs: [], recommenders: [],
    career_goal: '', additional_notes: '', writing_constraints: '',
  }
}

/** 示例档案：仅用于填充表单，帮助快速体验界面；请替换为真实信息后再生成。 */
export function demoProfile(): ApplicantProfile {
  const p = emptyProfile('示例 · 陈亦然 2027 Fall')
  p.basics = {
    name_en: 'Yiran Chen', name_zh: '陈亦然', email: 'yiran.chen@example.com',
    phone: '+86 138 0000 0000', location: 'Shanghai, China',
    linkedin: 'linkedin.com/in/yiran-chen', github: 'github.com/yiranchen', personal_site: '',
  }
  p.education = [{
    id: uid(), school: 'Example University', degree: 'Bachelor', major: 'Computer Science',
    gpa: '3.7', gpa_scale: '4.0', gpa_average: '88 / 100', ranking: 'Top 15%', start_date: '2022-09', end_date: '2026-06',
    relevant_courses: ['Machine Learning', 'Probability and Statistics', 'Database Systems', 'Algorithm Design'],
    thesis: '', highlights: '',
  }]
  p.experiences = [
    {
      id: uid(), type: 'research', org: 'Example University, Data Intelligence Lab', role: 'Research Assistant',
      location: 'Shanghai', start_date: '2024-09', end_date: '2025-12',
      bullets: [
        'Built a Chinese street-view OCR evaluation pipeline over 50,000 labelled images',
        'Reduced character error rate from 12.4% to 8.1% by redesigning the augmentation strategy',
        'Wrote the experiment protocol used by three subsequent lab projects',
      ],
      tags: ['NLP', 'research'], related_recommender: '',
    },
    {
      id: uid(), type: 'internship', org: 'Example Technology Co.', role: 'Data Science Intern',
      location: 'Shanghai', start_date: '2025-07', end_date: '2025-09',
      bullets: [
        'Developed a demand-forecasting model for 200+ retail SKUs and handed it to the operations team',
        'Presented weekly findings to a cross-functional team of six',
      ],
      tags: ['industry', 'communication'], related_recommender: '',
    },
  ]
  p.skill_groups = [
    { id: uid(), category: 'Programming', items: ['Python', 'PyTorch', 'SQL', 'Git'] },
    { id: uid(), category: 'Languages', items: ['Chinese (native)', 'English (IELTS 7.0)'] },
  ]
  p.test_scores = [{ id: uid(), kind: 'IELTS', total: '7.0', breakdown: 'L 7.5 / R 7.5 / W 6.5 / S 6.5', date: '2025-05' }]
  p.awards = [{ id: uid(), title: 'Outstanding Undergraduate Research Award', issuer: 'Example University', date: '2025-06', detail: '' }]
  p.target_programs = [
    {
      id: uid(), university: 'The University of Hong Kong', program: 'MSc in Computer Science',
      degree_type: 'Taught Master', region: '中国香港', intake: '2027 Fall', deadline: '',
      language_requirement: '', curriculum_notes: '', faculty_notes: '',
      why_fit: '', notes: '截止日期与语言要求请到官网核实后填写',
    },
    {
      id: uid(), university: 'National University of Singapore', program: 'MSc in Data Science and Machine Learning',
      degree_type: 'Taught Master', region: '新加坡', intake: '2027 Fall', deadline: '',
      language_requirement: '', curriculum_notes: '', faculty_notes: '',
      why_fit: '', notes: '截止日期与语言要求请到官网核实后填写',
    },
  ]
  p.recommenders = [
    {
      id: uid(), name: 'Prof. Lin', title: 'Associate Professor', affiliation: 'Example University',
      email: '', relation: 'Supervised the applicant\'s undergraduate research in the Data Intelligence Lab',
      known_since: '2024-09', observed_strengths: ['Experimental rigour', 'Independent troubleshooting'],
      tone: 'academic', notes: '',
    },
  ]
  p.career_goal = 'To work on reliable machine-learning systems for real-world document understanding, initially as an applied scientist.'
  p.writing_constraints = ''
  return p
}
