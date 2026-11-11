// 与后端 schemas.py / profile.py 保持一致的可选项与展示文案。
const DOC_TYPES = [
  { key: 'cv', label: '学术 CV' },
  { key: 'ps', label: '个人陈述 PS' },
  { key: 'recommendation', label: '推荐信' },
];

const LANGUAGES = [
  { key: 'en', label: '英文（申请默认）' },
  { key: 'zh', label: '简体中文' },
];

const TONES = [
  { key: 'professional', label: '专业稳重' },
  { key: 'confident', label: '自信有力' },
  { key: 'warm', label: '真诚温和' },
  { key: 'concise', label: '简洁凝练' },
];

const EXPERIENCE_TYPES = [
  { key: 'research', label: '科研' },
  { key: 'internship', label: '实习' },
  { key: 'work', label: '全职工作' },
  { key: 'project', label: '项目' },
  { key: 'volunteer', label: '志愿' },
  { key: 'competition', label: '竞赛' },
];

const NODE_LABELS = [
  '整理申请人事实清单',
  '规划结构与素材选取',
  '起草正文 / 渲染简历',
  '事实一致性与文书质量校验',
  '按校验意见修订',
  '定稿与归档',
];

function labelOf(list, key, fallback) {
  for (let i = 0; i < list.length; i += 1) {
    if (list[i].key === key) return list[i].label;
  }
  return fallback || key || '未指定';
}

function labelsOf(list) {
  return list.map(function (item) { return item.label; });
}

module.exports = {
  DOC_TYPES: DOC_TYPES,
  LANGUAGES: LANGUAGES,
  TONES: TONES,
  EXPERIENCE_TYPES: EXPERIENCE_TYPES,
  NODE_LABELS: NODE_LABELS,
  labelOf: labelOf,
  labelsOf: labelsOf,
};
