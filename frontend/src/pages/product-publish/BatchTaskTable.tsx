import { Fragment } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { PublishBatchTarget } from '@/api/productPublish'
import { formatPublishTime, targetPresentation } from './batchPublishPresentation'

interface Props {
  targets: PublishBatchTarget[]
  accountNames: Map<string, string>
  expanded: Set<number>
  selected: Set<number>
  canRetry: boolean
  busy: boolean
  onToggle: (id: number) => void
  onExpand: (id: number) => void
}

export function BatchTaskTable({ targets, accountNames, expanded, selected, canRetry, busy, onToggle, onExpand }: Props) {
  return <div className="mt-3 overflow-x-auto">
    <table aria-label="发布任务明细" className="w-full min-w-[960px] text-left text-xs">
      <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500">
        <tr>{['选择 / 记录', '账号', '商品', '状态', '发布进度', '待发布预计时间', '成功实际发布时间', '错误 / 排程原因'].map(label => <th key={label} scope="col" className="p-3 font-medium">{label}</th>)}</tr>
      </thead>
      <tbody>
        {targets.map(target => {
          const view = targetPresentation(target)
          const isExpanded = expanded.has(target.id)
          return <Fragment key={target.id}>
            <tr className="border-b border-slate-200 dark:border-slate-700 align-top">
              <td className="p-3"><div className="flex items-center gap-2">
                {target.status === 'failed' && canRetry && <input type="checkbox" aria-label={`选择重试 ${target.account_id} · ${target.title}`}
                  disabled={busy} checked={selected.has(target.id)} onChange={() => onToggle(target.id)} />}
                <button type="button" className="text-blue-600 flex items-center gap-1" aria-label={`${isExpanded ? '收起' : '展开'} ${target.account_id} · ${target.title} 的尝试记录`}
                  aria-expanded={isExpanded} aria-controls={`target-attempts-${target.id}`} onClick={() => onExpand(target.id)}>
                  {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}记录 ({target.attempt_count})
                </button>
              </div></td>
              <td className="p-3"><div>{accountNames.get(target.account_id) || target.account_id}</div><div className="text-slate-400">{target.account_id}</div></td>
              <td className="p-3 max-w-xs break-words">{target.title}<div className="text-slate-400">素材 #{target.material_id}</div></td>
              <td className="p-3 whitespace-nowrap"><span className={view.className}>{view.label}</span></td>
              <td className="p-3">{view.progress}</td>
              <td className="p-3 whitespace-nowrap">{view.expected}</td>
              <td className="p-3 whitespace-nowrap">{view.actual}</td>
              <td className="p-3 max-w-xs break-words text-amber-600">{target.error_message || target.schedule_error ? <>{target.error_message && <p>{target.error_message}</p>}{target.schedule_error && <p>{target.schedule_error}</p>}</> : '—'}</td>
            </tr>
            {isExpanded && <tr id={`target-attempts-${target.id}`} className="bg-slate-50 dark:bg-slate-800/50">
              <td colSpan={8} className="p-3 space-y-2 text-slate-500 break-all">
                <p>计划：{formatPublishTime(target.scheduled_at)} · 可执行：{formatPublishTime(target.available_at)} · 截止：{formatPublishTime(target.deadline_at)}</p>
                <p>请求发起：{formatPublishTime(target.request_started_at)} · 最小间隔：{target.minimum_gap_seconds} 秒</p>
                {target.attempts.length === 0 && <p>暂无尝试记录</p>}
                {target.attempts.map(attempt => <div key={attempt.id} className="border-t border-slate-200 dark:border-slate-700 pt-2">
                  <p>尝试 #{attempt.attempt_no} · {attempt.status} · {attempt.error_message || '无错误信息'}</p>
                  <p>日志 ID：{attempt.publish_log_id ?? '—'} · 平台商品 ID：{attempt.item_id || '—'}</p>
                  <p>请求发起：{formatPublishTime(attempt.request_started_at)} · 结束：{formatPublishTime(attempt.finished_at)}</p>
                  {attempt.schedule_error && <p className="text-amber-600">{attempt.schedule_error}</p>}
                </div>)}
              </td>
            </tr>}
          </Fragment>
        })}
      </tbody>
    </table>
    <p className="mt-2 text-xs text-slate-400">预计时间随调度更新；成功实际发布时间使用服务端完成记录，不以计划时间代替。结果未知请先核对。</p>
  </div>
}
