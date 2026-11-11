// 统一请求层：所有业务接口都走自建 FastAPI，凭证用 Bearer token 显式携带。
const KEY_TOKEN = 'applicraft_token';

function getAppInstance() {
  return getApp();
}

function baseUrl() {
  const app = getAppInstance();
  return (app && app.globalData.baseUrl) || 'http://43.136.175.87:8000';
}

function getToken() {
  return wx.getStorageSync(KEY_TOKEN) || '';
}

function buildUrl(path) {
  return baseUrl().replace(/\/+$/, '') + '/api' + path;
}

/**
 * 发起 API 请求。
 * @param {string} path 以 / 开头的接口路径（不含 /api 前缀）
 * @param {object} options { method, data, auth, timeout }
 * @returns {Promise<any>} 成功时返回响应体
 */
function request(path, options) {
  const opts = options || {};
  const method = opts.method || 'GET';
  const needAuth = opts.auth !== false;
  const header = { 'Content-Type': 'application/json' };
  if (needAuth && getToken()) {
    header.Authorization = 'Bearer ' + getToken();
  }
  return new Promise((resolve, reject) => {
    wx.request({
      url: buildUrl(path),
      method: method,
      data: opts.data || {},
      header: header,
      timeout: opts.timeout || 30000,
      success(res) {
        const body = res.data || {};
        if (res.statusCode === 401 && needAuth) {
          const app = getAppInstance();
          if (app) app.clearSession();
          if (!opts.silent401) wx.reLaunch({ url: '/pages/login/login' });
          reject({ message: '登录已失效，请重新登录', statusCode: 401 });
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body);
          return;
        }
        const detail = body.detail || body.message || '';
        reject({
          message: typeof detail === 'string' && detail ? detail : '请求失败（HTTP ' + res.statusCode + '）',
          statusCode: res.statusCode,
          data: body,
        });
      },
      fail(err) {
        reject({
          message: '无法连接服务器，请检查地址与网络：' + (err && err.errMsg ? err.errMsg : '未知错误'),
          statusCode: 0,
        });
      },
    });
  });
}

function setSession(token, user, quota) {
  const app = getAppInstance();
  if (app) app.setSession(token, user, quota);
}

function clearSession() {
  const app = getAppInstance();
  if (app) app.clearSession();
}

const api = {
  getConfig: () => request('/config', { auth: false, timeout: 15000 }),
  health: () => request('/health', { auth: false, timeout: 15000 }),

  tokenLogin: (email, password) => request('/auth/token-login', {
    method: 'POST', auth: false, data: { email: email, password: password }, timeout: 20000,
  }),
  tokenRegister: (email, password, displayName) => request('/auth/token-register', {
    method: 'POST', auth: false,
    data: { email: email, password: password, display_name: displayName || '' }, timeout: 20000,
  }),
  tokenLogout: () => request('/auth/token-logout', { method: 'POST', timeout: 15000 }),
  me: () => request('/auth/me'),
  // 我的大模型 API：只读状态（脱敏），用于「我的」页显示当前由谁承担模型费用。
  getMyLlm: () => request('/me/llm'),

  // 微信一键登录：code 由 wx.login 获取，一次性有效；AppSecret 只在服务端。
  wechatLogin: (code) => request('/auth/wechat-login', {
    method: 'POST', auth: false, data: { code: code }, timeout: 20000,
  }),
  // 首次使用微信登录时，把 openid 绑定到已有账号（同时完成登录）。
  wechatBind: (code, email, password) => request('/auth/wechat-bind', {
    method: 'POST', auth: false,
    data: { code: code, email: email, password: password }, timeout: 20000,
  }),

  listProfiles: () => request('/profiles'),
  getProfile: (id) => request('/profiles/' + id),
  createProfile: (payload) => request('/profiles', { method: 'POST', data: payload, timeout: 30000 }),
  updateProfile: (id, payload) => request('/profiles/' + id, { method: 'PUT', data: payload, timeout: 30000 }),
  deleteProfile: (id) => request('/profiles/' + id, { method: 'DELETE' }),

  listDocuments: (profileId) => request('/documents' + (profileId ? '?profile_id=' + encodeURIComponent(profileId) : '')),
  getDocument: (id) => request('/documents/' + id),
  updateDocument: (id, markdown) => request('/documents/' + id, {
    method: 'PUT', data: { markdown: markdown }, timeout: 30000,
  }),
  deleteDocument: (id) => request('/documents/' + id, { method: 'DELETE' }),

  // 生成一次通常需要 1-3 分钟，超时放到 5 分钟；小程序不支持浏览器 SSE，走同步接口。
  generate: (payload) => request('/generate', { method: 'POST', data: payload, timeout: 300000 }),

  downloadDocx: (id) => new Promise((resolve, reject) => {
    const header = {};
    if (getToken()) header.Authorization = 'Bearer ' + getToken();
    wx.downloadFile({
      url: buildUrl('/documents/' + id + '/download?format=docx'),
      header: header,
      timeout: 120000,
      success(res) {
        if (res.statusCode === 200 && res.tempFilePath) resolve(res.tempFilePath);
        else reject({ message: '导出失败（HTTP ' + res.statusCode + '）' });
      },
      fail(err) {
        reject({ message: '导出失败：' + (err && err.errMsg ? err.errMsg : '网络错误') });
      },
    });
  }),
};

module.exports = {
  api: api,
  request: request,
  baseUrl: baseUrl,
  getToken: getToken,
  buildUrl: buildUrl,
  setSession: setSession,
  clearSession: clearSession,
};
