// 档案编辑：只改页面上展示的字段，其余字段原样回传，避免覆盖网页版填写的内容。
const api = require('../../utils/api.js');
const C = require('../../utils/constants.js');
const store = require('../../utils/profile-store.js');

function newId() {
  return 'm' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function splitLines(text) {
  return (text || '').split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
}

function splitItems(text) {
  return (text || '').split(/[,，\n]/).map(function (s) { return s.trim(); }).filter(Boolean);
}

function joinItems(arr) {
  return (arr || []).join('、');
}

function emptyProfile() {
  return {
    label: '我的申请档案',
    basics: {
      name_en: '', name_zh: '', email: '', phone: '', location: '',
      linkedin: '', github: '', personal_site: '',
    },
    education: [],
    experiences: [],
    publications: [],
    awards: [],
    skill_groups: [],
    test_scores: [],
    target_programs: [],
    recommenders: [],
    career_goal: '',
    additional_notes: '',
    writing_constraints: '',
  };
}

function newEducation() {
  return {
    id: newId(), school: '', degree: 'Bachelor', major: '', gpa: '', gpa_scale: '4.0',
    ranking: '', start_date: '', end_date: '', relevant_courses: [], thesis: '',
    highlights: '', courses_text: '',
  };
}

function newExperience() {
  return {
    id: newId(), type: 'project', org: '', role: '', location: '', start_date: '',
    end_date: '', bullets: [], tags: [], related_recommender: '',
    bullets_text: '', tags_text: '', type_index: 3, type_label: '项目',
  };
}

function newProgram() {
  return {
    id: newId(), university: '', program: '', degree_type: 'Taught Master',
    region: 'Hong Kong, China', intake: '', deadline: '', language_requirement: '',
    curriculum_notes: '', faculty_notes: '', why_fit: '', notes: '',
  };
}

function newRecommender() {
  return {
    id: newId(), name: '', title: '', affiliation: '', email: '', relation: '',
    known_since: '', observed_strengths: [], tone: 'academic', notes: '',
    strengths_text: '',
  };
}

// 把数组字段转成便于在 textarea 中编辑的文本，同时保留原始数组。
function decorate(data) {
  const form = JSON.parse(JSON.stringify(data));
  form.education = (form.education || []).map(function (item) {
    item.courses_text = joinItems(item.relevant_courses);
    return item;
  });
  form.experiences = (form.experiences || []).map(function (item) {
    item.bullets_text = (item.bullets || []).join('\n');
    item.tags_text = joinItems(item.tags);
    let idx = 3;
    for (let i = 0; i < C.EXPERIENCE_TYPES.length; i += 1) {
      if (C.EXPERIENCE_TYPES[i].key === item.type) idx = i;
    }
    item.type_index = idx;
    item.type_label = C.EXPERIENCE_TYPES[idx].label;
    return item;
  });
  form.target_programs = form.target_programs || [];
  form.recommenders = (form.recommenders || []).map(function (item) {
    item.strengths_text = joinItems(item.observed_strengths);
    return item;
  });
  return form;
}

// 去掉辅助字段，并把文本还原成后端要求的数组。
function clean(form) {
  const payload = JSON.parse(JSON.stringify(form));
  payload.education = (payload.education || []).map(function (item) {
    item.relevant_courses = splitItems(item.courses_text);
    delete item.courses_text;
    return item;
  });
  payload.experiences = (payload.experiences || []).map(function (item) {
    item.bullets = splitLines(item.bullets_text);
    item.tags = splitItems(item.tags_text);
    delete item.bullets_text;
    delete item.tags_text;
    delete item.type_index;
    delete item.type_label;
    return item;
  });
  payload.recommenders = (payload.recommenders || []).map(function (item) {
    item.observed_strengths = splitItems(item.strengths_text);
    delete item.strengths_text;
    return item;
  });
  return payload;
}

Page({
  data: {
    mode: 'create',
    profileId: '',
    form: emptyProfile(),
    expTypeLabels: C.labelsOf(C.EXPERIENCE_TYPES),
    state: 'ready',
    error: '',
    saving: false,
  },

  onLoad(options) {
    const mode = options.mode === 'edit' ? 'edit' : 'create';
    this.setData({ mode: mode, profileId: options.id || '', state: mode === 'edit' ? 'loading' : 'ready' });
    wx.setNavigationBarTitle({ title: mode === 'edit' ? '编辑档案' : '新建档案' });
    if (mode === 'edit') this.load(options.id);
    else this.suggestLabel();
  },

  /** 新档案默认按顺序命名，避免多份同名档案难以分辨。 */
  async suggestLabel() {
    try {
      const list = await api.api.listProfiles();
      this.setData({ 'form.label': '我的申请档案 ' + ((list.items || []).length + 1) });
    } catch (err) {
      // 网络失败时保留 emptyProfile 的默认名称，不打断新建流程。
    }
  },

  async load(id) {
    try {
      const profile = await api.api.getProfile(id);
      this.setData({ form: decorate(profile), state: 'ready', error: '' });
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '档案加载失败' });
    }
  },

  onTopInput(e) {
    const patch = {};
    patch['form.' + e.currentTarget.dataset.field] = e.detail.value;
    this.setData(patch);
  },

  onBasicsInput(e) {
    const patch = {};
    patch['form.basics.' + e.currentTarget.dataset.field] = e.detail.value;
    this.setData(patch);
  },

  onArrayInput(e) {
    const d = e.currentTarget.dataset;
    const patch = {};
    patch['form.' + d.group + '[' + d.index + '].' + d.field] = e.detail.value;
    this.setData(patch);
  },

  onTypeChange(e) {
    const index = e.currentTarget.dataset.index;
    const typeIndex = Number(e.detail.value);
    const patch = {};
    patch['form.experiences[' + index + '].type_index'] = typeIndex;
    patch['form.experiences[' + index + '].type'] = C.EXPERIENCE_TYPES[typeIndex].key;
    patch['form.experiences[' + index + '].type_label'] = C.EXPERIENCE_TYPES[typeIndex].label;
    this.setData(patch);
  },

  addItem(e) {
    const group = e.currentTarget.dataset.group;
    const makers = {
      education: newEducation,
      experiences: newExperience,
      target_programs: newProgram,
      recommenders: newRecommender,
    };
    if (!makers[group]) return;
    const list = (this.data.form[group] || []).concat([makers[group]()]);
    const patch = {};
    patch['form.' + group] = list;
    this.setData(patch);
  },

  removeItem(e) {
    const group = e.currentTarget.dataset.group;
    const index = Number(e.currentTarget.dataset.index);
    const list = (this.data.form[group] || []).slice();
    list.splice(index, 1);
    const patch = {};
    patch['form.' + group] = list;
    this.setData(patch);
  },

  async save() {
    const form = this.data.form;
    if (!(form.label || '').trim()) {
      this.setData({ error: '请填写档案名称' });
      return;
    }
    const payload = clean(form);
    this.setData({ saving: true, error: '' });
    try {
      if (this.data.mode === 'edit') {
        await api.api.updateProfile(this.data.profileId, payload);
        store.setActiveId(this.data.profileId);
      } else {
        const saved = await api.api.createProfile(payload);
        // 新建后直接成为当前档案，回到列表即可生成，无需再手动选一次。
        store.setActiveId(saved.id);
      }
      wx.showToast({ title: '已保存', icon: 'success' });
      setTimeout(function () { wx.navigateBack(); }, 600);
    } catch (err) {
      this.setData({ error: err.message || '保存失败，请重试' });
    } finally {
      this.setData({ saving: false });
    }
  },
});
