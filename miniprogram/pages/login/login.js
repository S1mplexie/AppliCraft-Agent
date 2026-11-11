// 账号密码登录：小程序不使用 Cookie，登录成功后保存 Bearer token。
const api = require('../../utils/api.js');
const app = getApp();

Page({
  data: {
    baseUrl: 'http://43.136.175.87:8000',
    email: '',
    password: '',
    displayName: '',
    mode: 'login',
    showAdvanced: false,
    allowRegistration: false,
    wechatEnabled: false,
    bindMode: false,
    loading: false,
    checking: true,
    error: '',
    hint: '',
  },

  onLoad() {
    this.setData({ baseUrl: app.globalData.baseUrl || 'http://43.136.175.87:8000' });
    this.loadConfig();
    if (app.globalData.token) {
      this.restoreSession();
    } else {
      this.setData({ checking: false });
    }
  },

  async loadConfig() {
    try {
      const config = await api.api.getConfig();
      this.setData({
        allowRegistration: !!config.allow_registration,
        wechatEnabled: !!config.wechat_login_enabled,
      });
    } catch (err) {
      this.setData({ hint: '暂时读不到服务器配置，请检查下方服务器地址。' });
    }
  },

  async restoreSession() {
    try {
      // 恢复会话失败时留在登录页即可，不触发请求层默认的跳转。
      const me = await api.request('/auth/me', { silent401: true });
      app.globalData.user = me.user;
      app.globalData.quota = me.quota;
      wx.switchTab({ url: '/pages/index/index' });
    } catch (err) {
      api.clearSession();
      this.setData({ checking: false });
    }
  },

  onBaseUrlInput(e) { this.setData({ baseUrl: e.detail.value, error: '' }); },
  onEmailInput(e) { this.setData({ email: e.detail.value, error: '' }); },
  onPasswordInput(e) { this.setData({ password: e.detail.value, error: '' }); },
  onNameInput(e) { this.setData({ displayName: e.detail.value, error: '' }); },

  // 把 wx.login 包成 Promise。code 只能用一次，绑定时要重新取一个新的。
  getWxCode() {
    return new Promise((resolve, reject) => {
      wx.login({
        success(res) {
          if (res.code) resolve(res.code);
          else reject({ message: '微信登录凭证获取失败，请检查小程序 AppID 配置' });
        },
        fail(err) {
          reject({ message: '无法调用微信登录：' + (err && err.errMsg ? err.errMsg : '未知错误') });
        },
      });
    });
  },

  // 微信登录与账号登录共用服务器地址设置和可达性检查。
  async ensureServer() {
    app.setBaseUrl(this.data.baseUrl);
    try {
      await api.api.health();
    } catch (err) {
      throw { message: '服务器不可达：' + err.message + '。开发期请在微信开发者工具勾选「不校验合法域名」，真机需 HTTPS 域名。' };
    }
  },

  finishLogin(result) {
    api.setSession(result.token, result.user, result.quota);
    wx.showToast({ title: '登录成功', icon: 'success' });
    wx.switchTab({ url: '/pages/index/index' });
  },

  async wechatLogin() {
    if (this.data.loading || this.data.checking) return;
    this.setData({ loading: true, error: '' });
    try {
      await this.ensureServer();
      const code = await this.getWxCode();
      const result = await api.api.wechatLogin(code);
      if (result.need_bind) {
        // 后端默认不自动建号：引导用已有账号密码完成一次绑定，之后即可免密登录。
        this.setData({
          bindMode: true,
          hint: result.message || '该微信尚未绑定账号，请用账号密码完成一次绑定。',
        });
        return;
      }
      this.finishLogin(result);
    } catch (err) {
      this.setData({ error: err.message || '微信登录失败，请重试' });
    } finally {
      this.setData({ loading: false });
    }
  },

  async bindWechat() {
    const email = (this.data.email || '').trim();
    const password = this.data.password || '';
    if (!email || !password) {
      this.setData({ error: '请填写已有账号的邮箱和密码' });
      return;
    }
    this.setData({ loading: true, error: '' });
    try {
      await this.ensureServer();
      const code = await this.getWxCode();
      const result = await api.api.wechatBind(code, email, password);
      this.finishLogin(result);
    } catch (err) {
      this.setData({ error: err.message || '绑定失败，请重试' });
    } finally {
      this.setData({ loading: false });
    }
  },

  exitBindMode() {
    this.setData({ bindMode: false, hint: '', error: '' });
  },

  toggleAdvanced() { this.setData({ showAdvanced: !this.data.showAdvanced }); },

  switchMode() {
    this.setData({
      mode: this.data.mode === 'login' ? 'register' : 'login',
      error: '',
    });
  },

  async submit() {
    // 绑定模式下同一个按钮提交「微信绑定 + 登录」，需要重新取一次 wx.login code。
    if (this.data.bindMode) {
      await this.bindWechat();
      return;
    }
    const email = (this.data.email || '').trim();
    const password = this.data.password || '';
    if (!email || !password) {
      this.setData({ error: '请填写邮箱和密码' });
      return;
    }
    if (password.length < 8) {
      this.setData({ error: '密码至少 8 位' });
      return;
    }
    this.setData({ loading: true, error: '' });
    try {
      await this.ensureServer();
      const result = this.data.mode === 'register'
        ? await api.api.tokenRegister(email, password, this.data.displayName)
        : await api.api.tokenLogin(email, password);
      this.finishLogin(result);
    } catch (err) {
      this.setData({ error: err.message || '登录失败，请重试' });
    } finally {
      this.setData({ loading: false });
    }
  },
});
