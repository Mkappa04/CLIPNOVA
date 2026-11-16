import { ArrowUpRight, CheckCircle2, Upload } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ImportModal } from '../components/ImportModal'
import { JobList } from '../components/JobList'
import { ErrorBox, PageHeader, Spinner, cx } from '../components/ui'
import { VideoCard } from '../components/VideoCard'
import { VideoDetail } from '../components/VideoDetail'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes, formatDuration } from '../services/format'
import type { DashboardData } from '../types'

const FUNNEL_LABEL: Record<string, string> = {
  detected: 'Rilevate', rendered: 'Montate', approved: 'Approvate', exported: 'Esportate', published: 'Pubblicate',
}

interface Todo { n: number; label: string; detail: string; to: string; cta: string; tone: 'tally' | 'err' | 'bone' }

function todos(d: DashboardData): Todo[] {
  const out: Todo[] = []
  const noRights = d.recent_videos.filter((v) => !v.rights || v.rights.authorization_status !== 'authorized').length
  const toAnalyze = d.recent_videos.filter((v) => v.status === 'ready' && v.clip_count === 0).length
  const detected = d.clips.by_status.detected ?? 0
  if (d.clips.in_review) out.push({ n: d.clips.in_review, label: 'clip da approvare', detail: 'Montate e pronte: guarda, scrivi i testi, approva.', to: '/approval', cta: 'Approva', tone: 'tally' })
  if (d.jobs.failed) out.push({ n: d.jobs.failed, label: d.jobs.failed === 1 ? 'elaborazione fallita' : 'elaborazioni fallite', detail: 'Controlla l\'errore e rilancia dalla coda.', to: '/render', cta: 'Apri coda', tone: 'err' })
  if (detected) out.push({ n: detected, label: 'clip rilevate da montare', detail: 'Scegli un preset: il planner decide zoom, sottotitoli e suoni.', to: '/editor', cta: 'Monta', tone: 'bone' })
  if (toAnalyze) out.push({ n: toAnalyze, label: toAnalyze === 1 ? 'video da analizzare' : 'video da analizzare', detail: 'Trascrizione e ricerca dei momenti migliori.', to: '/detection', cta: 'Analizza', tone: 'bone' })
  if (noRights) out.push({ n: noRights, label: 'video senza diritti confermati', detail: 'Senza autorizzazione l\'export resta bloccato.', to: '/library', cta: 'Imposta', tone: 'bone' })
  return out
}

function Metric({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3.5 sm:px-5">
      <div className="eyebrow">{label}</div>
      <div className="timecode mt-1.5 text-[1.6rem] font-medium leading-none text-bone-100">{value}</div>
      {sub && <div className="mt-1.5 truncate text-xs text-graphite-400">{sub}</div>}
    </div>
  )
}

function Funnel() {
  const { data } = useApi(() => fetch('/api/analytics?days=30').then((r) => r.json()) as Promise<{ funnel: { stage: string; count: number }[] }>, [], 30000)
  const f = data?.funnel ?? []
  const max = Math.max(1, ...f.map((s) => s.count))
  return (
    <section aria-labelledby="funnel-h">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 id="funnel-h" className="eyebrow text-bone-400">Pipeline</h2>
        <span className="font-mono text-2xs text-graphite-500">ultimi 30 giorni</span>
      </div>
      {!data && <Spinner />}
      <ol className="space-y-3">
        {f.map((s, i) => {
          const prev = i ? f[i - 1].count : 0
          const rate = i && prev ? Math.round((s.count / prev) * 100) : null
          return (
            <li key={s.stage} className="grid grid-cols-[88px_1fr_auto] items-center gap-3">
              <span className="text-sm text-bone-300">{FUNNEL_LABEL[s.stage] ?? s.stage}</span>
              <span className="relative h-5 overflow-hidden rounded-sm bg-graphite-850">
                <span className={cx('absolute inset-y-0 left-0 rounded-sm transition-[width] duration-700 ease-out', i === 0 ? 'bg-bone-400/70' : 'bg-tally-500')}
                  style={{ width: `${Math.max(s.count ? 2 : 0, (s.count / max) * 100)}%`, opacity: i === 0 ? 1 : 1 - i * 0.12 }} />
              </span>
              <span className="timecode w-16 text-right text-sm text-bone-100">
                {s.count}{rate !== null && <span className="ml-1.5 text-2xs text-graphite-400">{rate}%</span>}
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

export function Dashboard() {
  const { data, error, loading, reload } = useApi(() => api.dashboard(), [], 3000)
  const [importOpen, setImportOpen] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const list = data ? todos(data) : []

  return (
    <>
      <PageHeader title="Regia" subtitle="Cosa entra, cosa è in lavorazione, cosa aspetta te."
        actions={<>
          <Link to="/detection" className="btn-ghost">Clip Detection</Link>
          <button className="btn-primary" onClick={() => setImportOpen(true)}><Upload size={16} /> Importa video</button>
        </>} />

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Spinner />}

      {data && (
        <div className="space-y-10">
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] lg:gap-14">
            {/* what needs you */}
            <section aria-labelledby="todo-h">
              <h2 id="todo-h" className="eyebrow mb-4 text-bone-400">Da fare adesso</h2>
              {list.length === 0 ? (
                <div className="flex items-center gap-3 border-l-2 border-ok py-2 pl-4 text-sm text-bone-200">
                  <CheckCircle2 size={18} className="text-ok" /> Tutto in ordine: nessuna clip in attesa, nessun errore.
                </div>
              ) : (
                <ul className="divide-y divide-graphite-800 border-y border-graphite-800">
                  {list.map((t, i) => (
                    <li key={t.label}>
                      <Link to={t.to} className="group grid grid-cols-[3.5rem_1fr_auto] items-center gap-4 py-4 transition-colors hover:bg-graphite-900/60 sm:grid-cols-[4.5rem_1fr_auto]">
                        <span className={cx('timecode text-right text-3xl font-medium leading-none sm:text-[2.6rem]',
                          t.tone === 'tally' ? 'text-tally-500' : t.tone === 'err' ? 'text-err' : 'text-bone-100',
                          i > 0 && 'sm:text-3xl')}>{t.n}</span>
                        <span className="min-w-0">
                          <span className="block text-[15px] font-medium text-bone-100">{t.label}</span>
                          <span className="block text-sm text-graphite-400">{t.detail}</span>
                        </span>
                        <span className="flex items-center gap-1 pr-1 text-sm text-bone-300 transition-colors group-hover:text-tally-400">
                          <span className="hidden sm:inline">{t.cta}</span><ArrowUpRight size={16} className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <Funnel />
          </div>

          {/* one dense strip instead of eight cards */}
          <section aria-label="Metriche" className="grid grid-cols-2 gap-px border-y border-graphite-800 bg-graphite-800 sm:grid-cols-3 lg:grid-cols-6 [&>*]:bg-graphite-950">
            <Metric label="Girato" value={formatDuration(data.videos.total_duration)} sub={`${data.videos.total} video · ${data.videos.ready} pronti`} />
            <Metric label="Clip" value={data.clips.total} sub={`${data.clips.in_review} in revisione`} />
            <Metric label="Approvate" value={data.clips.approved} sub="pronte per l'export" />
            <Metric label="Render" value={data.jobs.renders_completed} sub={data.jobs.active ? `${data.jobs.active} in corso` : 'nessuno in corso'} />
            <Metric label="Errori" value={<span className={data.jobs.failed + data.videos.errors ? 'text-err' : ''}>{data.jobs.failed + data.videos.errors}</span>}
              sub={`${data.jobs.failed} job · ${data.videos.errors} video`} />
            <Metric label="Spazio dati" value={formatBytes(data.storage.data_bytes)} sub={`${formatBytes(data.storage.disk_free)} liberi sul disco`} />
          </section>

          <div className="grid gap-10 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] lg:gap-14">
            <section aria-labelledby="videos-h">
              <div className="mb-4 flex items-baseline justify-between">
                <h2 id="videos-h" className="eyebrow text-bone-400">Ultimi video</h2>
                <Link to="/library" className="link text-sm">Libreria</Link>
              </div>
              {data.recent_videos.length ? (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {data.recent_videos.map((v) => <VideoCard key={v.id} video={v} onOpen={() => setOpenId(v.id)} />)}
                </div>
              ) : (
                <p className="text-sm text-graphite-400">
                  Nessun video. <button className="link" onClick={() => setImportOpen(true)}>Importa il primo</button>.
                </p>
              )}
            </section>
            <section aria-labelledby="act-h">
              <div className="mb-1 flex items-baseline justify-between">
                <h2 id="act-h" className="eyebrow text-bone-400">Attività</h2>
                <Link to="/render" className="link text-sm">Coda</Link>
              </div>
              <JobList jobs={data.recent_jobs} onChange={reload} compact />
            </section>
          </div>
        </div>
      )}

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onImported={reload} />
      <VideoDetail videoId={openId} onClose={() => setOpenId(null)} onChanged={reload} />
    </>
  )
}
