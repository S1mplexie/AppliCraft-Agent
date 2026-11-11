// 文书详情：轻量 Markdown 展示、事实校验意见、编辑存版本与 Word 导出。
const api = require('../../utils/api.js');

const ISSUE_LABELS = {
  fabrication: '编造事实',
  contradiction: '前后矛盾',
  unsupported: '缺少依据',
  style: '文风问题',
  missing: '信息缺失',
};

function parseMarkdown(text) {
  return (text || '').split('\n').map(function (raw, idx) {
    const line = raw.trim();
    let type = 'p';
    let value = line;
    if (/^###\s/.test(line)) { type = 'h3'; value = line.slice(4); }
    else if (/^##\s/.test(line)) { type = 'h2'; value = line.slice(3); }
    else if (/^#\s/.test(line)) { type = 'h1'; value = line.slice(2); }
    else if (/^[-*]\s/.test(line)) { type = 'li'; value = line.slice(2); }
    else if (/^>\s/.test(line)) { type = 'quote'; value = line.slice(2); }
    else if (!line) { type = 'blank'; value = ''; }
    return { idx: idx, type: type, text: value.replace(/\*\*/g, '').replace(/`/g, '') };
  });
}

Page({
  data: {
    id: '',
    state: 'loading',
    error: '',
    meta: null,
    markdown: '',
    lines: [],
    issues: [],
    outline: [],
    versionCount: 0,
    issueCount: 0,
    editing: false,
    editText: '',
    editLength: 0,
    saving: false,
    dateText: '',
  },

  onLoad(options) {
    this.setData({ id: options.id || '' });
    this.load();
  },

  async load() {
    this._editValue = null;
    this.setData({ state: 'loading', error: '' });
    try {
      const doc = await api.api.getDocument(this.data.id);
      const trace = doc.trace || {};
      const critique = trace.critique || {};
      const issues = (critique.issues || trace.issues || []).map(function (item, idx) {
        return {
          idx: idx,
          label: ISSUE_LABELS[item.type] || item.type || '待核对',
          quote: item.quote || '',
          reason: item.reason || '',
          fix: item.fix || '',
        };
      });
      const outline = (trace.outline || []).map(function (section, idx) {
        return { idx: idx, title: section.title || '', goal: section.goal || '' };
      });
      const meta = doc.meta || {};
      this.setData({
        meta: meta,
        markdown: doc.markdown || '',
        lines: parseMarkdown(doc.markdown || ''),
        issues: issues,
        issueCount: issues.length,
        outline: outline,
        versionCount: (doc.versions || []).length,
        dateText: (meta.updated_at || '').slice(0, 10),
        editing: false,
        editText: doc.markdown || '',
        // 展示实际载入的字符数，便于一眼确认长文书没有被输入框截断。
        editLength: (doc.markdown || '').length,
        state: 'ready',
      });
      wx.setNavigationBarTitle({ title: meta.title || '文书详情' });
    } catch (err) {
      this.setData({ state: 'error', error: err.message || '文书加载失败' });
    }
  },

  copyAll() {
    wx.setClipboardData({
      data: this.data.markdown,
      success() { wx.showToast({ title: '全文已复制', icon: 'success' }); },
    });
  },

  startEdit() {
    // value 只在进入编辑态时灌入一次全文；之后的输入值放在实例变量里，
    // 避免每次按键都 setData 整篇长文书导致光标跳动和输入卡顿。
    this._editValue = this.data.markdown || '';
    this.setData({
      editing: true,
      editText: this._editValue,
      editLength: this._editValue.length,
    });
  },
  cancelEdit() {
    this._editValue = null;
    this.setData({
      editing: false,
      editText: this.data.markdown,
      editLength: (this.data.markdown || '').length,
    });
  },
  onEditInput(e) {
    this._editValue = e.detail.value || '';
    this.setData({ editLength: this._editValue.length });
  },

  async saveEdit() {
    const text = this._editValue == null ? (this.data.editText || '') : this._editValue;
    if (!text.trim()) {
      wx.showToast({ title: '正文不能为空', icon: 'none' });
      return;
    }
    this.setData({ saving: true });
    try {
      await api.api.updateDocument(this.data.id, text);
      wx.showToast({ title: '已保存新版本', icon: 'success' });
      this.setData({ editing: false });
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message || '保存失败', icon: 'none' });
    } finally {
      this.setData({ saving: false });
    }
  },

  async exportDocx() {
    wx.showLoading({ title: '正在导出 Word…', mask: true });
    try {
      const filePath = await api.api.downloadDocx(this.data.id);
      wx.hideLoading();
      wx.openDocument({
        filePath: filePath,
        fileType: 'docx',
        showMenu: true,
        fail() { wx.showToast({ title: '无法打开文档', icon: 'none' }); },
      });
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: err.message || '导出失败', icon: 'none' });
    }
  },

  remove() {
    const self = this;
    wx.showModal({
      title: '删除文书',
      content: '删除后所有历史版本一并移除，且无法恢复。',
      confirmColor: '#d64545',
      success(res) {
        if (!res.confirm) return;
        api.api.deleteDocument(self.data.id).then(function () {
          wx.navigateBack();
        }).catch(function (err) {
          wx.showToast({ title: err.message || '删除失败', icon: 'none' });
        });
      },
    });
  },
});
