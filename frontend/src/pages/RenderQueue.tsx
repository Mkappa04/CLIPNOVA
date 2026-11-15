import { useState } from 'react'
import { RenderCard } from './ClipEditor'
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
  const { data: renders, reload: reloadRenders } = useApi(() => api.renders({ status: 'completed,failed', limit: 60 }), [], 5000)
  return (
    <>
      <PageHeader title="Render Queue" subtitle="Tutti i job di elaborazione (import, analisi, rendering) e i video verticali prodotti" />
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

      <h2 className="mb-3 mt-8 font-display text-lg font-semibold text-white">Render completati</h2>
      {renders && renders.length === 0 && <p className="text-sm text-zinc-500">Nessun render. Apri una clip nel Clip Editor e premi Render.</p>}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {renders?.map((r) => <RenderCard key={r.id} r={r} onDeleted={reloadRenders} />)}
      </div>
    </>
  )
}
