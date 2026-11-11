// 我的：账号、配额、服务器地址与退出登录。
const api = require('../../utils/api.js');
const app = getApp();

Page({
  data: {
    user: null,
    quota: null,
    baseUrl: '',
    editBaseUrl: '',
    model: '',
    llmConfigured: true,
    billingLabel: '系统共享 Key',
    billingPersonal: false,
    quotaLabel: '—',
    freeExhausted: false,
    state: 'loading',
    error: '',
  },

  onShow() {
    if (!api.getToken()) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.load();
  },

  async load() {
    this.setData({ state: 'loading', error: '' });
    try {
      // 单独兜底个人配置：即使后端是旧版本没有 /me/llm，也不影响「我的」页其它信息。
      const [me, config, myLlm] = await Promise.all([
        api.api.me(),
        api.api.getConfig(),
        api.api.getMyLlm().catch(function () { return null; }),
      ]);
      const baseUrl = app.globalData.baseUrl;
      const personal = !!(myLlm && myLlm.effective_source === 'personal');
      const isAdmin = !!(myLlm && myLlm.is_admin) || !!(me.quota && me.quota.source === 'admin');
      const unlimited = isAdmin || personal || !!(myLlm && myLlm.unlimited)
        || !!(me.quota && me.quota.unlimited);
      const freeLeft = myLlm && typeof myLlm.system_key_remaining === 'number'
        ? myLlm.system_key_remaining
        : (me.quota && typeof me.quota.system_key_remaining === 'number'
          ? me.quota.system_key_remaining : null);
      const freeExhausted = !unlimited && freeLeft !== null && freeLeft <= 0;
      let billingLabel = '系统共享 Key';
      if (personal) billingLabel = '自有 Key（不占系统额度）';
      else if (isAdmin) billingLabel = '系统共享 Key（管理员不限次数）';
      else billingLabel = '系统共享 Key · 今日剩 ' + (freeLeft === null ? '—' : freeLeft) + ' 次';
      this.setData({
        user: me.user,
        quota: me.quota,
        baseUrl: baseUrl,
        editBaseUrl: baseUrl,
        model: (myLlm && myLlm.effective_model) || config.llm_model,
        llmConfigured: myLlm ? myLlm.effective_source !== 'none' : !!config.llm_configured,
        billingPersonal: personal,
        billingLabel: billingLabel,
        quotaLabel: unlimited ? '不限次数' : (freeLeft === null ? '—' : '剩 ' + freeLeft + ' 次'),
        freeExhausted: freeExhausted,
        state: 'ready',
      });
      app.globalData.user = me.user;
      app.globalData.quota = me.quota;
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '加载失败' });
    }
  },

  onBaseUrlInput(e) { this.setData({ editBaseUrl: e.detail.value }); },

  saveBaseUrl() {
    const value = (this.data.editBaseUrl || '').trim();
    if (!/^https?:\/\//.test(value) && value !== '') {
      wx.showToast({ title: '地址需以 http:// 或 https:// 开头', icon: 'none' });
      return;
    }
    const next = app.setBaseUrl(value);
    api.clearSession();
    wx.showToast({ title: '地址已更新，请重新登录', icon: 'none' });
    setTimeout(function () { wx.reLaunch({ url: '/pages/login/login' }); }, 700);
    this.setData({ baseUrl: next });
  },

  async logout() {
    try {
      await api.api.tokenLogout();
    } catch (err) {
      // 本地会话仍然清除，避免网络异常导致无法退出。
    }
    api.clearSession();
    wx.reLaunch({ url: '/pages/login/login' });
  },
});
