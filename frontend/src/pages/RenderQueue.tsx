import { useState } from 'react'
import { JobList } from '../components/JobList'
import { ErrorBox, PageHeader, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'

const FILTERS = [
  ['queued,running', 'Attivi'],
  ['completed', 'Completati'],
  ['failed', 'Falliti'],
  ['cancelled', 'Annullati'],
  ['', 'Tutti'],
] as const

export function RenderQueue() {
  const [filter, setFilter] = useState<string>('')
  const { data, error, reload } = useApi(() => api.jobs({ status: filter, limit: 200 }), [filter], 2000)
  return (
    <>
      <PageHeader title="Render Queue" subtitle="Tutti i job di elaborazione: import, analisi e (da Milestone 3) rendering" />
      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map(([k, l]) => (
          <button key={l} onClick={() => setFilter(k)}
            className={cx('rounded-full px-3 py-1 text-sm ring-1 transition', filter === k ? 'bg-nova-600 text-white ring-nova-500' : 'text-zinc-400 ring-ink-600 hover:text-white')}>
            {l}
          </button>
        ))}
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      <div className="card px-4"><JobList jobs={data ?? []} onChange={reload} /></div>
    </>
  )
}
