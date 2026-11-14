import { CheckCircle2, RefreshCw, Save, ShieldAlert, Trash2, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes, formatDate, formatDuration, resolution } from '../services/format'
import { toast } from '../stores/toastStore'
import { EMPTY_RIGHTS, type Purpose, type RightsDecision, type Video } from '../types'
import { JobList } from './JobList'
import { RightsForm } from './RightsForm'
import { Field, Modal, StatusBadge, cx } from './ui'

const PURPOSES: [Purpose, string][] = [['non_commercial', 'Export non commerciale'], ['commercial', 'Export commerciale']]

function DecisionCard({ label, d }: { label: string; d: RightsDecision | null }) {
  if (!d) return null
  return (
    <div className={cx('rounded-lg p-3 text-xs ring-1', d.allowed ? 'bg-emerald-500/5 ring-emerald-500/30' : 'bg-red-500/5 ring-red-500/30')}>
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
        {d.allowed ? <CheckCircle2 size={15} className="text-emerald-400" /> : <XCircle size={15} className="text-red-400" />}
        <span className="text-white">{label}</span>
        <span className={d.allowed ? 'text-emerald-300' : 'text-red-300'}>{d.allowed ? 'consentito' : 'bloccato'}</span>
      </div>
      <ul className="space-y-0.5">
        {d.blockers.map((b) => <li key={b} className="text-red-200">• {b}</li>)}
        {d.warnings.map((w) => <li key={w} className="text-amber-200">⚠ {w}</li>)}
      </ul>
    </div>
  )
}

export function VideoDetail({ videoId, onClose, onChanged }: { videoId: string | null; onClose: () => void; onChanged: () => void }) {
  const { data: video, reload } = useApi(() => (videoId ? api.video(videoId) : Promise.resolve(null)), [videoId], 2500)
  const { data: jobs, reload: reloadJobs } = useApi(
    () => (videoId ? api.jobs({ video_id: videoId, limit: 10 }) : Promise.resolve([])), [videoId], 2500)
  const [form, setForm] = useState<Pick<Video, 'title' | 'game' | 'creator' | 'source' | 'notes'> | null>(null)
  const [rights, setRights] = useState(EMPTY_RIGHTS)
  const [decisions, setDecisions] = useState<Record<string, RightsDecision>>({})
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteFile, setDeleteFile] = useState(false)

  const loadDecisions = async (id: string) => {
    const entries = await Promise.all(PURPOSES.map(async ([p]) => [p, await api.checkRights(id, p)] as const))
    setDecisions(Object.fromEntries(entries))
  }

  // Initialise editable state once per opened video
  useEffect(() => { setForm(null); setConfirmDelete(false); setDeleteFile(false); setDecisions({}) }, [videoId])
  useEffect(() => {
    if (video && !form) {
      setForm({ title: video.title, game: video.game, creator: video.creator, source: video.source, notes: video.notes })
      setRights(video.rights ? { ...EMPTY_RIGHTS, ...video.rights } : EMPTY_RIGHTS)
      void loadDecisions(video.id)
    }
  }, [video, form])

  if (!videoId) return null

  const save = async () => {
    if (!video || !form) return
    try {
      await api.updateVideo(video.id, form)
      await api.putRights(video.id, rights)
      await loadDecisions(video.id)
      toast.success('Salvato')
      reload(); onChanged()
    } catch (e) { toast.error(e) }
  }

  const doDelete = async () => {
    if (!video) return
    try {
      const r = await api.deleteVideo(video.id, deleteFile)
      toast.success(r.removed_files.length ? 'Video e file eliminati' : 'Video rimosso dalla libreria (file mantenuto)')
      onChanged(); onClose()
    } catch (e) { toast.error(e) }
  }

  const reprobe = async () => {
    if (!video) return
    try { await api.reprobe(video.id); toast.info('Rianalisi avviata'); reloadJobs() } catch (e) { toast.error(e) }
  }

  return (
    <Modal open onClose={onClose} title={video?.title ?? 'Video'} wide>
      {!video || !form ? <p className="text-sm text-zinc-400">Caricamento…</p> : (
        <div className="space-y-6">
          <div className="grid gap-5 lg:grid-cols-5">
            <div className="lg:col-span-3">
              <video key={video.id} controls preload="metadata" className="aspect-video w-full rounded-xl bg-black"
                     src={api.streamUrl(video.id)} poster={video.has_thumbnail ? api.thumbnailUrl(video) : undefined} />
              {['mkv', 'avi', 'flv', 'wmv', 'ts', 'mts'].some((e) => video.original_filename.toLowerCase().endsWith(e)) && (
                <p className="mt-1 text-xs text-zinc-500">Alcuni formati (MKV/AVI/…) potrebbero non essere riproducibili nel browser: l'elaborazione FFmpeg funziona comunque.</p>
              )}
            </div>
            <dl className="grid grid-cols-2 content-start gap-x-4 gap-y-2 text-sm lg:col-span-2">
              {[
                ['Stato', <StatusBadge key="s" status={video.status} />],
                ['Durata', formatDuration(video.duration)],
                ['Risoluzione', resolution(video.width, video.height)],
                ['FPS', video.fps ?? '—'],
                ['Codec', `${video.video_codec ?? '—'} / ${video.audio_codec ?? 'no audio'}`],
                ['Dimensione', formatBytes(video.file_size)],
                ['Bitrate', video.bitrate ? `${(video.bitrate / 1e6).toFixed(1)} Mbps` : '—'],
                ['Archiviazione', video.storage_mode],
                ['Importato', formatDate(video.created_at)],
              ].map(([k, v]) => (
                <div key={String(k)}><dt className="text-xs uppercase tracking-wider text-zinc-500">{k}</dt><dd className="text-zinc-200">{v}</dd></div>
              ))}
              <div className="col-span-2"><dt className="text-xs uppercase tracking-wider text-zinc-500">File</dt>
                <dd className="break-all font-mono text-xs text-zinc-400">{video.file_path}</dd></div>
              {video.error && <div className="col-span-2 rounded bg-red-500/10 p-2 text-xs text-red-300">{video.error}</div>}
            </dl>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Titolo"><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            <Field label="Gioco"><input className="input" value={form.game} onChange={(e) => setForm({ ...form, game: e.target.value })} /></Field>
            <Field label="Creator"><input className="input" value={form.creator} onChange={(e) => setForm({ ...form, creator: e.target.value })} /></Field>
            <Field label="Fonte"><input className="input" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></Field>
          </div>

          <section>
            <h3 className="mb-3 flex items-center gap-2 font-display text-sm font-semibold uppercase tracking-wider text-pulse-300">
              <ShieldAlert size={15} /> Diritti
            </h3>
            <RightsForm value={rights} onChange={setRights} />
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {PURPOSES.map(([p, l]) => <DecisionCard key={p} label={l} d={decisions[p] ?? null} />)}
            </div>
            <p className="mt-2 text-xs text-zinc-500">La verifica si aggiorna dopo il salvataggio. L'analisi locale è sempre consentita; i blocchi valgono per export e pubblicazione.</p>
          </section>

          <section>
            <h3 className="mb-1 font-display text-sm font-semibold uppercase tracking-wider text-pulse-300">Job</h3>
            <JobList jobs={jobs ?? []} onChange={reloadJobs} compact />
          </section>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-700 pt-4">
            {!confirmDelete ? (
              <div className="flex gap-2">
                <button className="btn-danger" onClick={() => setConfirmDelete(true)}><Trash2 size={15} /> Elimina</button>
                <button className="btn-ghost" onClick={reprobe}><RefreshCw size={15} /> Rianalizza metadati</button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3 rounded-lg bg-red-500/10 p-3 text-sm ring-1 ring-red-500/40">
                <span className="text-red-200">Confermi l'eliminazione dalla libreria?</span>
                {video.storage_mode !== 'referenced' && (
                  <label className="flex items-center gap-2 text-xs text-red-200">
                    <input type="checkbox" checked={deleteFile} onChange={(e) => setDeleteFile(e.target.checked)} />
                    Elimina anche il file in data/videos
                  </label>
                )}
                <button className="btn-danger" onClick={doDelete}>Conferma</button>
                <button className="btn-ghost" onClick={() => setConfirmDelete(false)}>Annulla</button>
              </div>
            )}
            <button className="btn-primary" onClick={save}><Save size={15} /> Salva modifiche</button>
          </div>
        </div>
      )}
    </Modal>
  )
}
