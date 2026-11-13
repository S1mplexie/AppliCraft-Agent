<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  uid,
  type ApplicantProfile, type Award, type Education, type Experience,
  type ProfileSection, type Recommender, type SkillGroup, type TargetProgram, type TestScore,
} from '../types'

const props = defineProps<{
  profile: ApplicantProfile
  section?: ProfileSection
  saveState?: string
  /** 系统项目库已收录的官方项目数量，为 0 时禁用导入入口。 */
  systemProgramCount?: number
}>()
const emit = defineEmits<{
  sectionChange: [section: ProfileSection]
  save: []
  importTargets: []
}>()

// 切换当前档案时，父组件通过 :key 重新挂载本组件；p 始终指向同一个响应式档案对象。
const p = props.profile
const activeSection = ref<ProfileSection>(props.section || 'basics')
watch(() => props.section, (value) => { if (value) activeSection.value = value })
function switchSection(key: ProfileSection) {
  activeSection.value = key
  emit('sectionChange', key)
}

const sections = computed(() => [
  { key: 'basics' as const, label: '基本信息', count: '', done: !!(p.basics.name_en && p.basics.email), todo: !(p.basics.name_en && p.basics.email) },
  { key: 'education' as const, label: '教育背景', count: String(p.education.length), done: p.education.length > 0, todo: p.education.length === 0 },
  { key: 'experience' as const, label: '经历与论文', count: String(p.experiences.length + p.publications.length), done: p.experiences.length > 0, todo: p.experiences.length === 0 },
  { key: 'credentials' as const, label: '技能 / 奖项 / 成绩', count: String(p.skill_groups.length + p.awards.length + p.test_scores.length), done: p.skill_groups.length > 0 || p.test_scores.length > 0, todo: !(p.skill_groups.length > 0 || p.test_scores.length > 0) },
  { key: 'programs' as const, label: '目标项目', count: String(p.target_programs.length), done: p.target_programs.length > 0, todo: p.target_programs.length === 0 },
  { key: 'recommenders' as const, label: '推荐人', count: String(p.recommenders.length), done: p.recommenders.length > 0, todo: p.recommenders.length === 0 },
  { key: 'goals' as const, label: '职业目标与约束', count: '', done: !!p.career_goal.trim(), todo: !p.career_goal.trim() },
])

/** 档案完整度：这六项是生成一份可用文书所需的最小事实集（基本信息含推荐人不计入必填）。 */
const requiredKeys = ['basics', 'education', 'experience', 'credentials', 'programs', 'goals'] as const
const requiredSections = computed(() => sections.value.filter(s => (requiredKeys as readonly string[]).includes(s.key)))
const completedCount = computed(() => requiredSections.value.filter(s => s.done).length)
const completeness = computed(() => Math.round(completedCount.value / requiredSections.value.length * 100))

const splitComma = (e: Event): string[] =>
  (e.target as HTMLInputElement).value.split(/[,，]/).map(s => s.trim()).filter(Boolean)
const splitLines = (e: Event): string[] =>
  (e.target as HTMLTextAreaElement).value.split('\n').map(s => s.trim()).filter(Boolean)
const joined = (list: string[] = [], separator = ', ') => list.join(separator)

const newEducation = (): Education => ({
  id: uid(), school: '', degree: 'Bachelor', major: '', gpa: '', gpa_scale: '4.0',
  ranking: '', start_date: '', end_date: '', relevant_courses: [], thesis: '', highlights: '',
})
const newExperience = (): Experience => ({
  id: uid(), type: 'project', org: '', role: '', location: '', start_date: '', end_date: '',
  bullets: [], tags: [], related_recommender: '',
})
const newAward = (): Award => ({ id: uid(), title: '', issuer: '', date: '', detail: '' })
const newSkill = (): SkillGroup => ({ id: uid(), category: '', items: [] })
const newScore = (): TestScore => ({ id: uid(), kind: '', total: '', breakdown: '', date: '' })
const newProgram = (): TargetProgram => ({
  id: uid(), university: '', program: '', degree_type: 'Taught Master', region: '', source_program_id: '',
  intake: '', deadline: '', language_requirement: '', curriculum_notes: '', faculty_notes: '',
  why_fit: '', notes: '',
})
const newRecommender = (): Recommender => ({
  id: uid(), name: '', title: '', affiliation: '', email: '', relation: '', known_since: '',
  observed_strengths: [], tone: 'academic', notes: '',
})
</script>

<template>
  <div class="profile-workspace">
    <div class="profile-toolbar">
      <label class="field profile-name"><span>档案名称</span><input v-model="p.label" placeholder="例如：陈亦然 2027 Fall" /></label>
      <div class="profile-toolbar-right">
        <span class="save-state">{{ saveState || '修改后自动保存' }}</span>
        <button class="btn small" type="button" :disabled="!p.id" @click="emit('save')">保存</button>
      </div>
    </div>

    <div class="profile-layout">
      <aside class="profile-nav" aria-label="档案分区">
        <button
          v-for="item in sections" :key="item.key" class="profile-nav-item"
          :class="{ active: activeSection === item.key }" @click="switchSection(item.key)"
        >
          <span v-if="item.todo" class="todo-dot" title="还有待补全的内容"></span>
          {{ item.label }}
          <span v-if="item.count" class="side-num">{{ item.count }}</span>
        </button>
        <div class="profile-nav-foot">
          <div class="completeness">
            <span>完整度 {{ completedCount }}/{{ requiredSections.length }}</span>
            <strong :class="completeness === 100 ? 'ok-text' : ''">{{ completeness }}%</strong>
          </div>
          <div class="progress-track" style="margin-top: 7px;">
            <div class="progress-fill" :class="{ done: completeness === 100 }" :style="{ width: completeness + '%' }"></div>
          </div>
        </div>
      </aside>

      <div class="profile-sections">
        <!-- 基本信息 -->
        <section v-show="activeSection === 'basics'" class="form-section">
          <div class="section-title"><h3>基本信息</h3><span>姓名与联系方式会直接写入 CV 抬头</span></div>
          <div class="grid2">
            <label class="field"><span>英文姓名</span><input v-model="p.basics.name_en" placeholder="Yiran Chen" /></label>
            <label class="field"><span>中文姓名</span><input v-model="p.basics.name_zh" placeholder="陈亦然" /></label>
            <label class="field"><span>邮箱</span><input v-model="p.basics.email" /></label>
            <label class="field"><span>电话</span><input v-model="p.basics.phone" /></label>
            <label class="field"><span>所在地</span><input v-model="p.basics.location" /></label>
            <label class="field"><span>LinkedIn</span><input v-model="p.basics.linkedin" /></label>
            <label class="field"><span>GitHub</span><input v-model="p.basics.github" /></label>
            <label class="field"><span>个人主页</span><input v-model="p.basics.personal_site" /></label>
          </div>
        </section>

        <!-- 教育背景 -->
        <section v-show="activeSection === 'education'" class="form-section">
          <div class="section-title"><h3>教育背景</h3><span>按时间倒序填写，GPA 与排名需与成绩单一致</span></div>
          <div v-for="(item, i) in p.education" :key="item.id" class="entry">
            <div class="entry-head"><strong>ED{{ i + 1 }}</strong><button class="link danger" @click="p.education.splice(i, 1)">删除</button></div>
            <div class="grid2">
              <label class="field"><span>学校</span><input v-model="item.school" /></label>
              <label class="field"><span>学位</span><input v-model="item.degree" /></label>
              <label class="field"><span>专业</span><input v-model="item.major" /></label>
              <label class="field"><span>GPA / 满分</span><input v-model="item.gpa" placeholder="3.7 / 4.0" /></label>
              <label class="field"><span>均分（百分制）</span><input v-model="item.gpa_average" placeholder="85 / 100" /></label>
              <label class="field"><span>排名</span><input v-model="item.ranking" placeholder="Top 15%" /></label>
              <label class="field"><span>起止时间</span><input v-model="item.start_date" placeholder="2022-09 ~ 2026-06" /></label>
            </div>
            <label class="field"><span>相关课程（逗号分隔）</span><input :value="joined(item.relevant_courses)" @input="item.relevant_courses = splitComma($event)" /></label>
            <label class="field"><span>毕业论文</span><input v-model="item.thesis" /></label>
            <label class="field"><span>补充亮点</span><textarea v-model="item.highlights" /></label>
          </div>
          <button class="btn ghost full" @click="p.education.push(newEducation())">+ 添加教育经历</button>
          <p v-if="!p.education.length" class="hint">还没有教育经历，至少填一段本科信息。</p>
        </section>

        <!-- 经历与论文 -->
        <section v-show="activeSection === 'experience'" class="form-section">
          <div class="section-title"><h3>研究 / 实习 / 项目经历</h3><span>每条事实要点写清「做了什么 + 结果 + 数据」，这是文书的证据来源</span></div>
          <div v-for="(item, i) in p.experiences" :key="item.id" class="entry">
            <div class="entry-head"><strong>E{{ i + 1 }}</strong><button class="link danger" @click="p.experiences.splice(i, 1)">删除</button></div>
            <div class="grid2">
              <label class="field"><span>类型</span>
                <select v-model="item.type">
                  <option value="research">科研</option><option value="internship">实习</option>
                  <option value="work">全职</option><option value="project">项目</option>
                  <option value="volunteer">志愿</option><option value="competition">竞赛</option>
                </select>
              </label>
              <label class="field"><span>单位 / 实验室</span><input v-model="item.org" /></label>
              <label class="field"><span>角色</span><input v-model="item.role" /></label>
              <label class="field"><span>地点</span><input v-model="item.location" /></label>
              <label class="field"><span>开始</span><input v-model="item.start_date" placeholder="2024-09" /></label>
              <label class="field"><span>结束</span><input v-model="item.end_date" placeholder="2025-12" /></label>
            </div>
            <label class="field"><span>事实要点（每行一条，含做了什么 / 结果 / 数据）</span>
              <textarea :value="joined(item.bullets, '\n')" rows="4" @input="item.bullets = splitLines($event)" />
            </label>
            <div class="grid2">
              <label class="field"><span>标签（逗号分隔）</span><input :value="joined(item.tags)" @input="item.tags = splitComma($event)" /></label>
              <label class="field"><span>关联推荐人 ID（可选）</span><input v-model="item.related_recommender" /></label>
            </div>
          </div>
          <button class="btn ghost full" @click="p.experiences.push(newExperience())">+ 添加经历</button>

          <div class="section-title sub"><h3>论文 / 出版物</h3><span>每行一条完整引用</span></div>
          <label class="field"><span>每行一条完整引用</span>
            <textarea :value="joined(p.publications, '\n')" rows="3" @input="p.publications = splitLines($event)" />
          </label>
        </section>

        <!-- 技能 / 奖项 / 成绩 -->
        <section v-show="activeSection === 'credentials'" class="form-section">
          <div class="section-title"><h3>技能 / 奖项 / 标化成绩</h3><span>CV 的技能栏与 PS 中的量化证据取自这里</span></div>
          <div v-for="(item, i) in p.skill_groups" :key="item.id" class="entry">
            <div class="entry-head"><strong>技能组 {{ i + 1 }}</strong><button class="link danger" @click="p.skill_groups.splice(i, 1)">删除</button></div>
            <label class="field"><span>类别</span><input v-model="item.category" placeholder="Programming" /></label>
            <label class="field"><span>内容（逗号分隔）</span><input :value="joined(item.items)" @input="item.items = splitComma($event)" /></label>
          </div>
          <button class="btn ghost full" @click="p.skill_groups.push(newSkill())">+ 添加技能组</button>

          <div class="section-title sub"><h3>奖项与荣誉</h3></div>
          <div v-for="(item, i) in p.awards" :key="item.id" class="entry">
            <div class="entry-head"><strong>A{{ i + 1 }}</strong><button class="link danger" @click="p.awards.splice(i, 1)">删除</button></div>
            <div class="grid2">
              <label class="field"><span>奖项</span><input v-model="item.title" /></label>
              <label class="field"><span>颁发机构</span><input v-model="item.issuer" /></label>
              <label class="field"><span>时间</span><input v-model="item.date" /></label>
              <label class="field"><span>补充说明</span><input v-model="item.detail" /></label>
            </div>
          </div>
          <button class="btn ghost full" @click="p.awards.push(newAward())">+ 添加奖项</button>

          <div class="section-title sub"><h3>标化考试</h3><span>成绩与日期务必与官方成绩单一致</span></div>
          <div v-for="(item, i) in p.test_scores" :key="item.id" class="entry">
            <div class="entry-head"><strong>成绩 {{ i + 1 }}</strong><button class="link danger" @click="p.test_scores.splice(i, 1)">删除</button></div>
            <div class="grid2">
              <label class="field"><span>考试</span><input v-model="item.kind" placeholder="IELTS / TOEFL / GRE" /></label>
              <label class="field"><span>总分</span><input v-model="item.total" /></label>
              <label class="field"><span>分项</span><input v-model="item.breakdown" /></label>
              <label class="field"><span>考试日期</span><input v-model="item.date" /></label>
            </div>
          </div>
          <button class="btn ghost full" @click="p.test_scores.push(newScore())">+ 添加成绩</button>
        </section>

        <!-- 目标项目 -->
        <section v-show="activeSection === 'programs'" class="form-section">
          <div class="section-title section-title-row">
            <div>
              <h3>目标项目</h3>
              <span>这里的信息用于定制 PS 的 why-this-programme 段落；截止日期与语言要求请以官网为准</span>
            </div>
            <button
              class="btn small primary" type="button" :disabled="!props.systemProgramCount"
              :title="props.systemProgramCount ? '从系统收录的港新官方项目批量导入' : '系统项目库未加载'"
              @click="emit('importTargets')"
            >从系统项目库导入</button>
          </div>
          <p class="hint import-lead">
            系统项目库已收录 {{ props.systemProgramCount || 0 }} 个港新官方项目，可批量带入学校、项目名、学院与入学季；
            导入后再补充课程要点与「你与项目的契合点」，也可以完全手动填写。
          </p>
          <datalist id="target-region-options">
            <option value="中国香港"></option><option value="新加坡"></option><option value="其他"></option>
          </datalist>
          <div v-for="(item, i) in p.target_programs" :key="item.id" class="entry">
            <div class="entry-head">
              <strong>项目 {{ i + 1 }}</strong>
              <span v-if="item.source_program_id" class="badge ok">系统项目库</span>
              <button class="link danger" @click="p.target_programs.splice(i, 1)">删除</button>
            </div>
            <div class="grid2">
              <label class="field"><span>学校</span><input v-model="item.university" /></label>
              <label class="field"><span>项目名称</span><input v-model="item.program" /></label>
              <label class="field"><span>地区</span><input v-model="item.region" list="target-region-options" /></label>
              <label class="field"><span>入学季</span><input v-model="item.intake" placeholder="2027 Fall" /></label>
              <label class="field"><span>截止日期</span><input v-model="item.deadline" placeholder="以官网核实为准" /></label>
              <label class="field"><span>语言要求</span><input v-model="item.language_requirement" /></label>
            </div>
            <label class="field"><span>课程 / 项目结构要点</span><textarea v-model="item.curriculum_notes" /></label>
            <label class="field"><span>师资 / 研究方向要点</span><textarea v-model="item.faculty_notes" /></label>
            <label class="field"><span>你与项目的契合点（自己的话）</span><textarea v-model="item.why_fit" /></label>
          </div>
          <button class="btn ghost full" @click="p.target_programs.push(newProgram())">+ 添加项目</button>
          <p v-if="!p.target_programs.length" class="hint">至少填一个目标项目，生成时可以选择不指定。</p>
        </section>

        <!-- 推荐人 -->
        <section v-show="activeSection === 'recommenders'" class="form-section">
          <div class="section-title"><h3>推荐人</h3><span>推荐信会以所选推荐人的视角与语气书写</span></div>
          <div v-for="(item, i) in p.recommenders" :key="item.id" class="entry">
            <div class="entry-head"><strong>推荐人 {{ i + 1 }}</strong><button class="link danger" @click="p.recommenders.splice(i, 1)">删除</button></div>
            <div class="grid2">
              <label class="field"><span>姓名</span><input v-model="item.name" /></label>
              <label class="field"><span>职称</span><input v-model="item.title" /></label>
              <label class="field"><span>单位</span><input v-model="item.affiliation" /></label>
              <label class="field"><span>邮箱</span><input v-model="item.email" /></label>
              <label class="field"><span>认识时间 / 场合</span><input v-model="item.known_since" /></label>
              <label class="field"><span>文书语气</span>
                <select v-model="item.tone"><option value="academic">学术</option><option value="professional">职业</option></select>
              </label>
            </div>
            <label class="field"><span>与申请人的关系</span><textarea v-model="item.relation" /></label>
            <label class="field"><span>可佐证的优点（逗号分隔）</span><input :value="joined(item.observed_strengths)" @input="item.observed_strengths = splitComma($event)" /></label>
          </div>
          <button class="btn ghost full" @click="p.recommenders.push(newRecommender())">+ 添加推荐人</button>
        </section>

        <!-- 职业目标与全局约束 -->
        <section v-show="activeSection === 'goals'" class="form-section">
          <div class="section-title"><h3>职业目标与全局约束</h3><span>这部分决定 PS 的主线，也会影响每次生成时的裁剪偏好</span></div>
          <label class="field"><span>短期 / 长期职业目标</span><textarea v-model="p.career_goal" rows="4" /></label>
          <label class="field"><span>补充说明（希望写进文书的背景信息）</span><textarea v-model="p.additional_notes" rows="3" /></label>
          <label class="field"><span>全局写作约束（如：不要提及某段经历、必须强调量化能力）</span><textarea v-model="p.writing_constraints" rows="3" /></label>
          <p class="hint">全局约束会作用于所有文书；单次生成的临时要求请写到生成页的「额外指令」。</p>
        </section>
      </div>
    </div>
  </div>
</template>
