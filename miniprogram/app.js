// AppliCraft 小程序入口：服务器地址与会话 token 都只存在本机缓存。
// 默认指向已部署的线上后端，打开模拟器即可直接使用；如需接本地或换域名，
// 在登录页「服务器地址」里修改一次即可（会持久化到本机缓存）。
const DEFAULT_BASE_URL = 'http://43.136.175.87:8000';
const KEY_BASE_URL = 'applicraft_base_url';
const KEY_TOKEN = 'applicraft_token';
// 与 utils/profile-store.js 保持一致的键名；账号变更时由入口统一清理。
const KEY_ACTIVE_PROFILE = 'applicraft_active_profile';

App({
  globalData: {
    appName: 'AppliCraft',
    baseUrl: DEFAULT_BASE_URL,
    token: '',
    user: null,
    quota: null,
  },

  onLaunch() {
    this.globalData.baseUrl = wx.getStorageSync(KEY_BASE_URL) || DEFAULT_BASE_URL;
    this.globalData.token = wx.getStorageSync(KEY_TOKEN) || '';
  },

  setBaseUrl(url) {
    const value = (url || '').trim().replace(/\/+$/, '');
    const normalized = /\/api$/.test(value) ? value.slice(0, -4) : value;
    this.globalData.baseUrl = normalized || DEFAULT_BASE_URL;
    wx.setStorageSync(KEY_BASE_URL, this.globalData.baseUrl);
    return this.globalData.baseUrl;
  },

  setSession(token, user, quota) {
    // 换账号登录或退出时清掉「当前档案」，避免沿用别人档案的 id。
    const sameUser = user && this.globalData.user && this.globalData.user.email === user.email;
    if (!sameUser) wx.removeStorageSync(KEY_ACTIVE_PROFILE);
    this.globalData.token = token || '';
    this.globalData.user = user || null;
    this.globalData.quota = quota || null;
    if (token) {
      wx.setStorageSync(KEY_TOKEN, token);
    } else {
      wx.removeStorageSync(KEY_TOKEN);
    }
  },

  clearSession() {
    this.setSession('', null, null);
  },
});
