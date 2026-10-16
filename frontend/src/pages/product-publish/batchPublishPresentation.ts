import type { PublishBatchTarget } from '@/api/productPublish'

export const publishWindowLabel = (hours: number | null) => hours === 0 ? '立即发布' : hours == null ? '未记录' : `${hours} 小时`

export function formatPublishTime(value?: string | null): string {
  if (!value) return '未记录'
  // Preserve the API timezone semantics: no zone is added to naive timestamps.
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function targetPresentation(target: PublishBatchTarget) {
  const states = {
    pending: { label: '待发布', progress: '等待执行', className: 'badge-secondary' },
    publishing: { label: '发布中', progress: '执行中，等待平台结果', className: 'badge-info' },
    success: { label: '已发布', progress: '发布成功', className: 'badge-success' },
    failed: { label: '发布失败', progress: '已结束，未成功', className: 'badge-danger' },
    unknown: { label: '结果未知', progress: '请先核对平台结果', className: 'badge-warning' },
    skipped: { label: '已跳过', progress: '未发布', className: 'badge-secondary' },
  }
  const scheduled = target.scheduled_at
  const available = target.available_at
  const expectedAt = available && (!scheduled || new Date(available).getTime() >= new Date(scheduled).getTime()) ? available : scheduled
  const successfulAttempt = [...target.attempts].sort((a, b) => b.attempt_no - a.attempt_no).find(attempt => attempt.status === 'success' && attempt.finished_at)
  return {
    ...states[target.status],
    expected: target.status === 'pending' ? expectedAt ? formatPublishTime(expectedAt) : target.window_hours === 0 ? '立即执行（等待调度）' : '等待排程' : '—',
    actual: target.status === 'success' ? formatPublishTime(target.finished_at || successfulAttempt?.finished_at) : '—',
  }
}
