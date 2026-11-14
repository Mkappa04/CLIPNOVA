import { Construction } from 'lucide-react'
import { PageHeader } from '../components/ui'

export function ComingSoon({ title, milestone, features }: { title: string; milestone: number; features: string[] }) {
  return (
    <>
      <PageHeader title={title} subtitle={`Disponibile dalla Milestone ${milestone}`} />
      <div className="card p-6">
        <div className="mb-4 flex items-center gap-3">
          <div className="rounded-xl bg-pulse-500/10 p-3 text-pulse-400 ring-1 ring-pulse-500/30"><Construction size={22} /></div>
          <p className="text-sm text-zinc-300">Questa sezione non è ancora implementata. Funzionalità previste:</p>
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {features.map((f) => (
            <li key={f} className="rounded-lg bg-ink-850 px-3 py-2 text-sm text-zinc-300 ring-1 ring-ink-700">{f}</li>
          ))}
        </ul>
      </div>
    </>
  )
}
