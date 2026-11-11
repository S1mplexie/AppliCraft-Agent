/** 服务端时间戳统一是 UTC ISO；在浏览器按本地时区显示，并附相对时间便于区分先后。 */
function parse(iso?: string): Date | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 完整导入时间：2026-11-10 11:23:45（3 小时前） */
export function formatImportedAt(iso?: string): string {
  const date = parse(iso)
  if (!date) return '导入时间未记录'
  const absolute = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000)
  let relative = ''
  if (minutes < 1) relative = '刚刚'
  else if (minutes < 60) relative = `${minutes} 分钟前`
  else if (minutes < 1440) relative = `${Math.floor(minutes / 60)} 小时前`
  else if (minutes < 43200) relative = `${Math.floor(minutes / 1440)} 天前`
  return relative ? `${absolute}（${relative}）` : absolute
}

/** 紧凑导入时间：11-10 11:23，用于生成页的勾选项。 */
export function shortImportedAt(iso?: string): string {
  const date = parse(iso)
  if (!date) return '时间未知'
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
