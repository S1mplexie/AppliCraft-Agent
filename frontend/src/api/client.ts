import type {
  ApplicantProfile, AppConfig, AuthResponse, DocumentDetail, DocumentMeta,
  FeedbackItem, GeneratePayload, LLMTestResult, MatchResult, ProfileSummary, RegenPayload, ReferenceDoc,
  ResumeParseResult, SkillDetail, SkillInfo, StreamEnvelope, SystemProgram,
  UserLLMConfig, UserLLMPayload,
} from '../types'

let unauthorizedHandler: (() => void) | null = null

/** 会话失效时由 App 注册回调，统一切回登录页。 */
export function onUnauthorized(fn: () => void) {
  unauthorizedHandler = fn
}

/** 把后端错误 detail 转成可读文案：pydantic 422 是对象数组，直接展示会是一坨 JSON。 */
function describeError(detail: any, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: any) => {
        const raw = item?.msg ?? item?.message ?? ''
        // 去掉 pydantic 的 "Value error, " 前缀，保留业务提示本身。
        return String(raw).replace(/^Value error,\s*/i, '').trim()
      })
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  if (detail && typeof detail === 'object') {
    const msg = (detail as any).msg ?? (detail as any).message
    if (typeof msg === 'string' && msg.trim()) return msg
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') {
      unauthorizedHandler?.()
    }
    let detail: any = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? body.message ?? detail
    } catch { /* keep statusText */ }
    throw new Error(describeError(detail, response.statusText))
  }
  return response.json() as Promise<T>
}

/** 基于 POST 的 SSE（EventSource 无法携带 JSON 请求体）：生成与按建议重生成共用。 */
async function sseStream(path: string, body: unknown, onEvent: (e: StreamEnvelope) => void): Promise<DocumentMeta> {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.()
    let detail: any = response.statusText
    try {
      const respBody = await response.json()
      detail = respBody.detail ?? detail
    } catch { /* keep statusText */ }
    throw new Error(describeError(detail, response.statusText))
  }
  if (!response.body) throw new Error('浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let document: DocumentMeta | null = null

  const handleBlock = (block: string) => {
    let event = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!data) return
    let parsed: any
    try { parsed = JSON.parse(data) } catch { return }
    const envelope: StreamEnvelope = { event: event as StreamEnvelope['event'], data: parsed }
    onEvent(envelope)
    if (envelope.event === 'error') throw new Error(parsed.message || '生成失败')
    if (envelope.event === 'done') document = parsed.document
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) handleBlock(block)
  }
  if (buffer.trim()) handleBlock(buffer)
  if (!document) throw new Error('生成流结束但未返回文档')
  return document
}

/** 上传 FormData（不能沿用 request 的 JSON Content-Type）。 */
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: 'POST', credentials: 'include', body: form,
  })
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.()
    let detail: any = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch { /* keep statusText */ }
    throw new Error(describeError(detail, response.statusText))
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; version: string; llm_configured: boolean; db_ok: boolean }>('/health'),
  config: () => request<AppConfig>('/config'),

  // ------------------------------------------------ 我的大模型 API（用户自带 Key）
  /** 返回脱敏配置与当前真正生效的来源（自有 / 系统 / 无）。 */
  getMyLlm: () => request<UserLLMConfig>('/me/llm'),
  /** api_key 留空表示沿用已保存的 Key，只改地址或模型名。 */
  saveMyLlm: (payload: UserLLMPayload) =>
    request<UserLLMConfig>('/me/llm', { method: 'PUT', body: JSON.stringify(payload) }),
  deleteMyLlm: () =>
    request<{ deleted: boolean } & UserLLMConfig>('/me/llm', { method: 'DELETE' }),
  testMyLlm: (payload: UserLLMPayload) =>
    request<LLMTestResult>('/me/llm/test', { method: 'POST', body: JSON.stringify(payload) }),

  register: (email: string, password: string, displayName: string) =>
    request<AuthResponse>('/auth/register', {
      method: 'POST', body: JSON.stringify({ email, password, display_name: displayName }),
    }),
  login: (email: string, password: string) =>
    request<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request<{ logged_out: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => request<AuthResponse>('/auth/me'),

  submitFeedback: (content: string) =>
    request<{ id: number; created_at: string }>('/feedback', {
      method: 'POST', body: JSON.stringify({ content }),
    }),
  listFeedback: () => request<{ items: FeedbackItem[] }>('/feedback'),
  matchProfile: (profileId: string) =>
    // 评估是显式扣费动作（系统 Key 用户扣 1 次免费额度），必须 POST 由用户触发。
    request<MatchResult>(`/match/${profileId}`, { method: 'POST' }),

  listProfiles: () => request<{ items: ProfileSummary[] }>('/profiles'),
  getProfile: (id: string) => request<ApplicantProfile>(`/profiles/${id}`),
  createProfile: (profile: ApplicantProfile) =>
    request<ApplicantProfile>('/profiles', { method: 'POST', body: JSON.stringify(profile) }),
  updateProfile: (id: string, profile: ApplicantProfile) =>
    request<ApplicantProfile>(`/profiles/${id}`, { method: 'PUT', body: JSON.stringify(profile) }),
  deleteProfile: (id: string) =>
    request<{ deleted: boolean }>(`/profiles/${id}`, { method: 'DELETE' }),

  /** 上传简历（PDF/DOCX/TXT/MD），由后端解析后以覆盖语义合并进档案。 */
  parseResume: (profileId: string, file: File): Promise<ResumeParseResult> =>
    new Promise<ResumeParseResult>((resolve, reject) => {
      const form = new FormData()
      form.append('file', file)
      fetch(`/api/profiles/${profileId}/parse-resume`, {
        method: 'POST',
        credentials: 'include',
        body: form,
        // 不要手动设置 Content-Type：浏览器会为 FormData 自动加上 multipart 边界。
      })
        .then(async (response) => {
          if (!response.ok) {
            if (response.status === 401) unauthorizedHandler?.()
            let detail: any = response.statusText
            try {
              const body = await response.json()
              detail = body.detail ?? detail
            } catch { /* keep statusText */ }
            throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
          }
          resolve((await response.json()) as ResumeParseResult)
        })
        .catch((err) => reject(err instanceof Error ? err : new Error(String(err))))
    }),

  listDocuments: (profileId?: string) =>
    request<{ items: DocumentMeta[] }>(`/documents${profileId ? `?profile_id=${profileId}` : ''}`),
  getDocument: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  updateDocument: (id: string, markdown: string) =>
    request<DocumentMeta>(`/documents/${id}`, { method: 'PUT', body: JSON.stringify({ markdown }) }),
  deleteDocument: (id: string) =>
    request<{ deleted: boolean }>(`/documents/${id}`, { method: 'DELETE' }),

  downloadUrl: (id: string, format: 'md' | 'docx', version?: string) =>
    `/api/documents/${id}/download?format=${format}${version ? `&version=${version}` : ''}`,

  /** 基于 POST 的 SSE（EventSource 无法携带 JSON 请求体）。 */
  generateStream: (payload: GeneratePayload, onEvent: (e: StreamEnvelope) => void) =>
    sseStream('/api/generate/stream', payload, onEvent),

  /** 按逐项审核建议重新生成文档：修订 → 复审 → 定稿，返回新版本 meta。 */
  regenerateStream: (documentId: string, payload: RegenPayload, onEvent: (e: StreamEnvelope) => void) =>
    sseStream(
      `/api/documents/${documentId}/regenerate`,
      // 后端字段为 snake_case，这里统一映射，避免只填逐项建议时字段被丢弃导致 422。
      { feedback: payload.feedback, issue_feedback: payload.issueFeedback },
      onEvent,
    ),

  // ---------------------------------------------------------- 参考文档库
  listReferences: () => request<{ items: ReferenceDoc[] }>('/library/references'),
  /** 上传参考文档（PDF/DOCX/TXT/MD）；名称在导入成功后的弹窗里再补。 */
  uploadReference: (file: File): Promise<ReferenceDoc> => {
    const form = new FormData()
    form.append('file', file)
    return postForm('/library/references', form)
  },
  /** 导入后补充/修改文档标题（不改文件与导入时间）。 */
  renameReference: (id: string, name: string) =>
    request<ReferenceDoc>(`/library/references/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify({ name }),
    }),
  deleteReference: (id: string) =>
    request<{ deleted: boolean }>(`/library/references/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  downloadReferenceUrl: (id: string) => `/api/library/references/${id}/download`,
  listSystemPrograms: () => request<{ items: SystemProgram[] }>('/library/system-programs'),

  // ---------------------------------------------------------- Skill 市场
  listSkills: () => request<{ items: SkillInfo[] }>('/skills'),
  /** 导入单个 .md/.txt 技能或含多个 SKILL.md 的 .zip 技能包。 */
  importSkill: (file: File): Promise<{ items: SkillInfo[]; imported: number }> => {
    const form = new FormData()
    form.append('file', file)
    return postForm('/skills', form)
  },
  /** 导入后补充/修改技能名称与简介（不改方法论正文与导入时间）。 */
  updateSkill: (id: string, name: string, description: string) =>
    request<SkillInfo>(`/skills/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify({ name, description }),
    }),
  skillDetail: (id: string) =>
    request<SkillDetail>(`/skills/detail?skill_id=${encodeURIComponent(id)}`),
  deleteSkill: (id: string) =>
    request<{ deleted: boolean }>(`/skills/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}
