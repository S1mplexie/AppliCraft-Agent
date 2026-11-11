// 生成控制台：调用同步生成接口，期间展示完整工作流说明（不是实时节点推送）。
const api = require('../../utils/api.js');
const C = require('../../utils/constants.js');
const store = require('../../utils/profile-store.js');

const NO_PROGRAM = '不指定目标项目';
const NO_RECOMMENDER = '不指定推荐人';

Page({
  data: {
    profiles: [],
    profileLabels: [],
    profileIndex: -1,
    profileId: '',
    programLabels: [NO_PROGRAM],
    programIds: [null],
    programIndex: 0,
    recommenderLabels: [NO_RECOMMENDER],
    recommenderIds: [null],
    recommenderIndex: 0,
    docTypes: C.DOC_TYPES,
    docTypeIndex: 1,
    languageLabels: C.labelsOf(C.LANGUAGES),
    languageIndex: 0,
    toneLabels: C.labelsOf(C.TONES),
    toneIndex: 0,
    wordLimit: 900,
    extraInstructions: '',
    nodes: C.NODE_LABELS,
    quota: null,
    llmConfigured: true,
    state: 'loading',
    error: '',
    generating: false,
    elapsed: 0,
  },

  onShow() {
    if (!api.getToken()) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.loadAll();
  },

  onHide() {
    this.stopTimer();
  },

  onUnload() {
    this.stopTimer();
  },

  async loadAll() {
    this.setData({ state: 'loading', error: '' });
    try {
      const [list, me, config] = await Promise.all([
        api.api.listProfiles(), api.api.me(), api.api.getConfig(),
      ]);
      const profiles = list.items || [];
      const labels = profiles.map(function (p) { return p.label || '未命名档案'; });
      this.setData({
        profiles: profiles,
        profileLabels: labels,
        quota: me.quota,
        llmConfigured: !!config.llm_configured,
        state: profiles.length ? 'ready' : 'empty',
      });
      // 始终沿用全局「当前档案」；切 tab 回来或生成完成后都不会重置成第一份。
      if (profiles.length) {
        const activeId = store.resolveActiveId(profiles);
        let index = 0;
        for (let i = 0; i < profiles.length; i += 1) {
          if (profiles[i].id === activeId) { index = i; break; }
        }
        this.selectProfile(index);
      }
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '加载失败' });
    }
  },

  async selectProfile(index) {
    const profile = this.data.profiles[index];
    if (!profile) return;
    this.setData({ profileIndex: index, profileId: profile.id, programIndex: 0, recommenderIndex: 0 });
    try {
      const detail = await api.api.getProfile(profile.id);
      const programs = detail.target_programs || [];
      const recommenders = detail.recommenders || [];
      this.setData({
        programLabels: [NO_PROGRAM].concat(programs.map(function (p) {
          return [p.university, p.program].filter(Boolean).join(' · ') || '未命名项目';
        })),
        programIds: [null].concat(programs.map(function (p) { return p.id; })),
        recommenderLabels: [NO_RECOMMENDER].concat(recommenders.map(function (r) {
          return [r.name, r.affiliation].filter(Boolean).join(' · ') || '未命名推荐人';
        })),
        recommenderIds: [null].concat(recommenders.map(function (r) { return r.id; })),
      });
    } catch (err) {
      wx.showToast({ title: '目标项目读取失败', icon: 'none' });
    }
  },

  onProfileChange(e) {
    const index = Number(e.detail.value);
    const profile = this.data.profiles[index];
    if (!profile) return;
    // 在这里切换也同步回全局，档案页、文书页会一起跟随。
    store.setActiveId(profile.id);
    this.selectProfile(index);
  },
  onProgramChange(e) { this.setData({ programIndex: Number(e.detail.value) }); },
  onRecommenderChange(e) { this.setData({ recommenderIndex: Number(e.detail.value) }); },
  onLanguageChange(e) { this.setData({ languageIndex: Number(e.detail.value) }); },
  onToneChange(e) { this.setData({ toneIndex: Number(e.detail.value) }); },
  onWordLimitChange(e) { this.setData({ wordLimit: e.detail.value }); },
  onExtraInput(e) { this.setData({ extraInstructions: e.detail.value }); },
  pickDocType(e) { this.setData({ docTypeIndex: Number(e.currentTarget.dataset.index) }); },

  goProfiles() { wx.switchTab({ url: '/pages/index/index' }); },

  startTimer() {
    this.stopTimer();
    this.setData({ elapsed: 0 });
    const self = this;
    this._timer = setInterval(function () {
      self.setData({ elapsed: self.data.elapsed + 1 });
    }, 1000);
  },

  stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  },

  async generate() {
    if (!this.data.profileId) {
      this.setData({ error: '请先选择一份申请人档案' });
      return;
    }
    if (!this.data.llmConfigured) {
      this.setData({ error: '服务器尚未配置大模型 API Key，请联系管理员。' });
      return;
    }
    const payload = {
      profile_id: this.data.profileId,
      doc_type: C.DOC_TYPES[this.data.docTypeIndex].key,
      target_program_id: this.data.programIds[this.data.programIndex] || null,
      recommender_id: this.data.recommenderIds[this.data.recommenderIndex] || null,
      language: C.LANGUAGES[this.data.languageIndex].key,
      word_limit: this.data.wordLimit,
      tone: C.TONES[this.data.toneIndex].key,
      emphasis: [],
      extra_instructions: this.data.extraInstructions || '',
    };
    this.setData({ generating: true, error: '' });
    this.startTimer();
    try {
      const meta = await api.api.generate(payload);
      wx.showToast({ title: '生成完成', icon: 'success' });
      wx.navigateTo({ url: '/pages/document/document?id=' + meta.id });
      // 只刷新额度，不重载档案列表，避免刚选的档案被重置。
      const self = this;
      api.api.me().then(function (res) {
        self.setData({ quota: res.quota });
      }).catch(function () {
        // 额度刷新失败不打断流程，返回页面时 onShow 会再拉一次。
      });
    } catch (err) {
      this.setData({ error: err.message || '生成失败，请重试' });
    } finally {
      this.stopTimer();
      this.setData({ generating: false });
    }
  },
});
