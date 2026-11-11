// 文书列表：默认跟随全局「当前档案」，筛选标签与实际请求始终一致。
const api = require('../../utils/api.js');
const C = require('../../utils/constants.js');
const store = require('../../utils/profile-store.js');

function formatDocs(items) {
  return (items || []).map(function (m) {
    return {
      id: m.id,
      title: m.title || '未命名文书',
      typeLabel: m.doc_type_label || C.labelOf(C.DOC_TYPES, m.doc_type, m.doc_type),
      dateText: (m.updated_at || '').slice(0, 10),
      wordCount: m.word_count || 0,
      version: m.version || 1,
      verified: !!m.passed_verification,
      issueCount: m.issue_count || 0,
    };
  });
}

Page({
  data: {
    items: [],
    profiles: [],
    filterLabels: ['全部档案'],
    filterIndex: 0,
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

  onPullDownRefresh() { this.load(true); },

  /** 先确定筛选标签，再按同一个标签请求文书，杜绝「标签写 A、列表是全部」。 */
  async load(fromPullDown) {
    this.setData({ state: 'loading', error: '' });
    try {
      const list = (await api.api.listProfiles()).items || [];
      const activeId = store.resolveActiveId(list);
      const labels = ['全部档案'].concat(list.map(function (p) {
        return p.label || '未命名档案';
      }));

      let index;
      // 手动筛选只在「当前档案没变」时保留；在档案页换了档案就重新跟随。
      if (this._filterTouched && this._filterActiveId === activeId) {
        index = this.data.filterIndex;
      } else {
        this._filterTouched = false;
        let pos = -1;
        for (let i = 0; i < list.length; i += 1) {
          if (list[i].id === activeId) { pos = i; break; }
        }
        index = pos >= 0 ? pos + 1 : 0;
      }
      if (index > list.length) index = 0;

      const profile = index > 0 ? list[index - 1] : null;
      const result = await api.api.listDocuments(profile ? profile.id : null);
      const items = formatDocs(result.items);
      this.setData({
        items: items,
        profiles: list,
        filterLabels: labels,
        filterIndex: index,
        state: items.length ? 'ready' : 'empty',
      });
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '加载失败' });
    } finally {
      if (fromPullDown) wx.stopPullDownRefresh();
    }
  },

  async onFilterChange(e) {
    const index = Number(e.detail.value);
    this._filterTouched = true;
    this._filterActiveId = store.getActiveId();
    this.setData({ filterIndex: index, state: 'loading' });
    const profile = index > 0 ? this.data.profiles[index - 1] : null;
    try {
      const result = await api.api.listDocuments(profile ? profile.id : null);
      const items = formatDocs(result.items);
      this.setData({ items: items, state: items.length ? 'ready' : 'empty' });
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '筛选失败' });
    }
  },

  openDocument(e) {
    wx.navigateTo({ url: '/pages/document/document?id=' + e.currentTarget.dataset.id });
  },

  removeDocument(e) {
    const id = e.currentTarget.dataset.id;
    const title = e.currentTarget.dataset.title || '该文书';
    const self = this;
    wx.showModal({
      title: '删除文书',
      content: '确定删除「' + title + '」吗？该文书的所有历史版本也会一并删除。',
      confirmColor: '#d64545',
      success(res) {
        if (!res.confirm) return;
        api.api.deleteDocument(id).then(function () {
          wx.showToast({ title: '已删除', icon: 'success' });
          self.load();
        }).catch(function (err) {
          wx.showToast({ title: err.message || '删除失败', icon: 'none' });
        });
      },
    });
  },

  goGenerate() { wx.switchTab({ url: '/pages/generate/generate' }); },
});
