// 档案列表：所有数据来自自建后端；「当前档案」由 profile-store 全局维护。
const api = require('../../utils/api.js');
const store = require('../../utils/profile-store.js');

Page({
  data: {
    items: [],
    activeId: '',
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

  onPullDownRefresh() {
    this.load(true);
  },

  async load(fromPullDown) {
    this.setData({ state: 'loading', error: '' });
    try {
      const result = await api.api.listProfiles();
      const raw = result.items || [];
      // 记忆的档案若已被删除，自动回退到第一份并写回缓存。
      const activeId = store.resolveActiveId(raw);
      const items = raw.map(function (item) {
        return {
          id: item.id,
          label: item.label || '未命名档案',
          name: item.name || '',
          dateText: (item.updated_at || '').slice(0, 10),
          isActive: item.id === activeId,
        };
      });
      this.setData({ items: items, activeId: activeId, state: items.length ? 'ready' : 'empty' });
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '加载失败' });
    } finally {
      if (fromPullDown) wx.stopPullDownRefresh();
    }
  },

  createProfile() {
    wx.navigateTo({ url: '/pages/profile-edit/profile-edit?mode=create' });
  },

  editProfile(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/profile-edit/profile-edit?mode=edit&id=' + id });
  },

  /** 设为当前档案：生成工作台会默认使用这一份，切 tab 不再丢失选择。 */
  setActive(e) {
    const id = e.currentTarget.dataset.id;
    if (!id || id === this.data.activeId) return;
    store.setActiveId(id);
    const items = this.data.items.map(function (item) {
      item.isActive = item.id === id;
      return item;
    });
    this.setData({ activeId: id, items: items });
    wx.showToast({ title: '已设为当前档案', icon: 'none' });
  },

  /** 一步到位：设定当前档案后直接去生成，不必再到生成页重新 picker。 */
  generateWith(e) {
    this.setActive(e);
    wx.switchTab({ url: '/pages/generate/generate' });
  },

  removeProfile(e) {
    const id = e.currentTarget.dataset.id;
    const label = e.currentTarget.dataset.label || '该档案';
    const self = this;
    wx.showModal({
      title: '删除档案',
      content: '确定删除「' + label + '」吗？已生成的文书不会被删除，但无法再基于该档案生成新文书。',
      confirmColor: '#d64545',
      success(res) {
        if (!res.confirm) return;
        api.api.deleteProfile(id).then(function () {
          wx.showToast({ title: '已删除', icon: 'success' });
          // 删的是当前档案时，load 会自动切换到剩余的第一份。
          self.load();
        }).catch(function (err) {
          wx.showToast({ title: err.message || '删除失败', icon: 'none' });
        });
      },
    });
  },

  goGenerate() {
    wx.switchTab({ url: '/pages/generate/generate' });
  },
});
