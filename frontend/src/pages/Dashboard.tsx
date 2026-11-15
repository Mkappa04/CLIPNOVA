import { AlertTriangle, CheckCircle2, Clock, Film, HardDrive, Layers, ScanSearch, Upload } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ImportModal } from '../components/ImportModal'
import { JobList } from '../components/JobList'
import { ErrorBox, PageHeader, ProgressBar, Spinner } from '../components/ui'
import { VideoCard } from '../components/VideoCard'
import { VideoDetail } from '../components/VideoDetail'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes, formatDuration } from '../services/format'

const PIPELINE = ['Import', 'Analysis', 'Detection', 'Editing', 'Rendering', 'Review', 'Approved', 'Export']

function Stat({ label, value, icon, accent = 'violet', sub }: {
  label: string; value: ReactNode; icon: ReactNode; accent?: 'violet' | 'cyan' | 'red' | 'green'; sub?: ReactNode
}) {
  const ring = { violet: 'text-nova-400 bg-nova-500/10 ring-nova-500/30', cyan: 'text-pulse-400 bg-pulse-500/10 ring-pulse-500/30',
    red: 'text-red-400 bg-red-500/10 ring-red-500/30', green: 'text-emerald-400 bg-emerald-500/10 ring-emerald-500/30' }[accent]
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-zinc-400">{label}</span>
        <span className={`rounded-lg p-1.5 ring-1 ${ring}`}>{icon}</span>
      </div>
      <div className="mt-2 font-display text-3xl font-bold text-white">{value}</div>
      {sub && <div className="mt-1 text-xs text-zinc-500">{sub}</div>}
    </div>
  )
}

export function Dashboard() {
  const { data, error, loading, reload } = useApi(() => api.dashboard(), [], 3000)
  const [importOpen, setImportOpen] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Panoramica della pipeline CLIPNOVA"
        actions={<button className="btn-primary" onClick={() => setImportOpen(true)}><Upload size={16} /> Importa video</button>} />

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Spinner />}

      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Video importati" value={data.videos.total} icon={<Film size={16} />}
              sub={`${formatDuration(data.videos.total_duration)} di girato · ${data.videos.ready} pronti`} />
            <Stat label="Clip generate" value={data.clips.total} icon={<ScanSearch size={16} />} accent="cyan" sub={<Link to="/detection" className="text-pulse-400 hover:underline">Apri Clip Detection →</Link>} />
            <Stat label="In revisione" value={data.clips.in_review} icon={<Clock size={16} />} accent="cyan" />
            <Stat label="Approvate" value={data.clips.approved} icon={<CheckCircle2 size={16} />} accent="green" />
            <Stat label="Render completati" value={data.jobs.renders_completed} icon={<Layers size={16} />} />
            <Stat label="Job attivi" value={data.jobs.active} icon={<Spinner className={data.jobs.active ? '' : 'hidden'} />} accent="cyan" />
            <Stat label="Errori" value={data.jobs.failed + data.videos.errors} icon={<AlertTriangle size={16} />} accent="red"
              sub={`${data.jobs.failed} job · ${data.videos.errors} video`} />
            <Stat label="Storage" value={formatBytes(data.storage.data_bytes)} icon={<HardDrive size={16} />}
              sub={<>
                <ProgressBar value={1 - data.storage.disk_free / data.storage.disk_total} className="mb-1 mt-1" />
                {formatBytes(data.storage.disk_free)} liberi
              </>} />
          </div>

          <div className="card overflow-x-auto p-4">
            <div className="flex min-w-[640px] items-center gap-1">
              {PIPELINE.map((step, i) => (
                <div key={step} className="flex flex-1 items-center gap-1">
                  <div className={`flex-1 rounded-lg px-2 py-2 text-center text-xs font-semibold uppercase tracking-wider ring-1 ${
                    i < 6 ? 'bg-nova-500/15 text-nova-200 ring-nova-500/40' : 'bg-ink-850 text-zinc-500 ring-ink-700'}`}>{step}</div>
                  {i < PIPELINE.length - 1 && <span className="text-zinc-600">›</span>}
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-zinc-500">Attivi: Import, Analysis, Clip Detection, Editing, Rendering e Review (Milestone 3). La pubblicazione è disabilitata e richiederà sempre approvazione esplicita.</p>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-display text-lg font-semibold text-white">Ultimi video</h2>
                <Link to="/library" className="text-sm text-pulse-400 hover:underline">Libreria →</Link>
              </div>
              {data.recent_videos.length ? (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {data.recent_videos.map((v) => <VideoCard key={v.id} video={v} onOpen={() => setOpenId(v.id)} />)}
                </div>
              ) : (
                <div className="card p-8 text-center text-sm text-zinc-400">
                  Nessun video. <button className="text-pulse-400 hover:underline" onClick={() => setImportOpen(true)}>Importa il primo</button>.
                </div>
              )}
            </section>
            <section>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-display text-lg font-semibold text-white">Attività</h2>
                <Link to="/render" className="text-sm text-pulse-400 hover:underline">Coda →</Link>
              </div>
              <div className="card px-4"><JobList jobs={data.recent_jobs} onChange={reload} compact /></div>
            </section>
          </div>
        </div>
      )}

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onImported={reload} />
      <VideoDetail videoId={openId} onClose={() => setOpenId(null)} onChanged={reload} />
    </>
  )
}
