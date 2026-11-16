import { XCircle } from 'lucide-react'
import { api } from '../services/api'
import { JOB_LABELS, timeAgo } from '../services/format'
import { toast } from '../stores/toastStore'
import type { Job } from '../types'
import { ProgressBar, StatusBadge } from './ui'

export function JobList({ jobs, onChange, compact }: { jobs: Job[]; onChange?: () => void; compact?: boolean }) {
  const cancel = async (id: string) => {
    try {
      await api.cancelJob(id)
      toast.info('Annullamento richiesto')
      onChange?.()
    } catch (e) { toast.error(e) }
  }
  if (!jobs.length) return <p className="py-6 text-sm text-graphite-400">Nessuna elaborazione.</p>
  return (
    <ul className="divide-y divide-graphite-800">
      {jobs.map((j) => {
        const active = j.status === 'queued' || j.status === 'running'
        return (
          <li key={j.id} className="flex items-center gap-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-bone-100">{JOB_LABELS[j.type] ?? j.type}</span>
                <StatusBadge status={j.status} />
                <span className="timecode ml-auto text-2xs text-graphite-500">{timeAgo(j.created_at)}</span>
              </div>
              {(active || !compact) && (
                <p className={`mt-1 truncate text-xs ${j.error ? 'text-err' : 'text-graphite-400'}`}>{j.error ?? j.message}</p>
              )}
              {active && <ProgressBar value={j.progress} className="mt-2" />}
            </div>
            {active && (
              <button className="btn-ghost px-2 py-1 text-xs" onClick={() => cancel(j.id)} disabled={j.cancel_requested}>
                <XCircle size={14} /> {j.cancel_requested ? 'Annullo…' : 'Annulla'}
              </button>
            )}
          </li>
        )
      })}
    </ul>
  )
}
