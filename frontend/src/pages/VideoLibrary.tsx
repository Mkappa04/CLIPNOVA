import { Film, Search, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ImportModal } from '../components/ImportModal'
import { EmptyState, ErrorBox, PageHeader, Spinner } from '../components/ui'
import { VideoCard } from '../components/VideoCard'
import { VideoDetail } from '../components/VideoDetail'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes, formatDuration } from '../services/format'

export function VideoLibrary() {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [game, setGame] = useState('')
  const [status, setStatus] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t) }, [q])

  const { data: videos, error, loading, reload } = useApi(
    () => api.videos({ q: debounced, game, status }), [debounced, game, status], 3000)
  const { data: games } = useApi(() => api.games(), [videos?.length])

  const totalSize = videos?.reduce((s, v) => s + v.file_size, 0) ?? 0
  const totalDur = videos?.reduce((s, v) => s + (v.duration ?? 0), 0) ?? 0

  return (
    <>
      <PageHeader title="Video Library"
        subtitle={videos ? `${videos.length} video · ${formatDuration(totalDur)} · ${formatBytes(totalSize)}` : 'Libreria dei video importati'}
        actions={<button className="btn-primary" onClick={() => setImportOpen(true)}><Upload size={16} /> Importa video</button>} />

      <div className="mb-5 flex flex-wrap gap-3">
        <div className="relative min-w-[220px] flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input className="input pl-9" placeholder="Cerca per titolo, creator, file…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input w-auto" value={game} onChange={(e) => setGame(e.target.value)}>
          <option value="">Tutti i giochi</option>
          {games?.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Tutti gli stati</option>
          {['ready', 'pending', 'copying', 'probing', 'error'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !videos && <Spinner />}
      {videos && videos.length === 0 && (
        <EmptyState icon={<Film size={28} />} title={q || game || status ? 'Nessun risultato' : 'La libreria è vuota'}
          text="Importa registrazioni di gameplay di cui possiedi i diritti o per cui hai un'autorizzazione esplicita."
          action={<button className="btn-primary" onClick={() => setImportOpen(true)}><Upload size={16} /> Importa video</button>} />
      )}
      {videos && videos.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {videos.map((v) => <VideoCard key={v.id} video={v} onOpen={() => setOpenId(v.id)} />)}
        </div>
      )}

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onImported={reload} />
      <VideoDetail videoId={openId} onClose={() => setOpenId(null)} onChanged={reload} />
    </>
  )
}
