// 「当前档案」是小程序内唯一的档案状态：档案页设定，生成页与文书页共用。
// 只存 id，不缓存档案内容；各页面 onShow 时用列表校验有效性，避免指向已删除的档案。
const KEY_ACTIVE = 'applicraft_active_profile';

function getActiveId() {
  return wx.getStorageSync(KEY_ACTIVE) || '';
}

function setActiveId(id) {
  if (id) wx.setStorageSync(KEY_ACTIVE, id);
  else wx.removeStorageSync(KEY_ACTIVE);
}

function clearActiveId() {
  wx.removeStorageSync(KEY_ACTIVE);
}

/**
 * 在档案列表里解析出有效的当前档案：
 * 记忆的 id 仍存在就继续用；已被删除或首次使用则回退到第一份，并写回缓存。
 * @param {Array<{id: string}>} items 后端返回的档案列表
 * @returns {string} 当前档案 id，空列表返回空串
 */
function resolveActiveId(items) {
  const list = items || [];
  const saved = getActiveId();
  const valid = list.some(function (item) { return item.id === saved; });
  const id = valid ? saved : (list[0] ? list[0].id : '');
  if (id !== saved) setActiveId(id);
  return id;
}

module.exports = {
  KEY_ACTIVE: KEY_ACTIVE,
  getActiveId: getActiveId,
  setActiveId: setActiveId,
  clearActiveId: clearActiveId,
  resolveActiveId: resolveActiveId,
};
