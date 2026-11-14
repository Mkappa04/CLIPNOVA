import { FolderInput, UploadCloud } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { formatBytes } from '../services/format'
import { toast } from '../stores/toastStore'
import { EMPTY_RIGHTS, type Rights } from '../types'
import { RightsForm } from './RightsForm'
import { Field, Modal, ProgressBar, cx } from './ui'

const ACCEPT = '.mp4,.mkv,.mov,.avi,.webm,.flv,.m4v,.ts,.mts,.wmv'

export function ImportModal({ open, onClose, onImported }: { open: boolean; onClose: () => void; onImported: () => void }) {
  const [tab, setTab] = useState<'upload' | 'path'>('upload')
  const [files, setFiles] = useState<File[]>([])
  const [path, setPath] = useState('')
  const [mode, setMode] = useState<'reference' | 'copy'>('reference')
  const [game, setGame] = useState('GTA 6')
  const [games, setGames] = useState<string[]>(['GTA 6'])
  const [creator, setCreator] = useState('')
  const [source, setSource] = useState('')
  const [notes, setNotes] = useState('')
  const [rights, setRights] = useState<Rights>(EMPTY_RIGHTS)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => { if (open) api.games().then(setGames).catch(() => {}) }, [open])

  const reset = () => {
    setFiles([]); setPath(''); setProgress(0); setBusy(false); setNotes('')
  }

  const close = () => {
    abortRef.current?.abort()
    reset()
    onClose()
  }

  const submit = async () => {
    if (!game.trim()) return toast.error('Inserisci il nome del gioco')
    const meta = { game, creator, source, notes, rights }
    setBusy(true)
    try {
      if (tab === 'upload') {
        if (!files.length) return toast.error('Seleziona almeno un video')
        abortRef.current = new AbortController()
        const res = await api.upload(files, meta, setProgress, abortRef.current.signal)
        toast.success(`${res.videos.length} video importati, analisi in corso`)
      } else {
        if (!path.trim()) return toast.error('Inserisci un percorso')
        const res = await api.importPath({ ...meta, path, mode })
        res.warnings.forEach((w) => toast.info(w))
        toast.success(mode === 'copy' ? 'Copia avviata' : 'Video registrato, analisi in corso')
      }
      reset()
      onImported()
      onClose()
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }

  const totalSize = files.reduce((s, f) => s + f.size, 0)

  return (
    <Modal open={open} onClose={close} title="Importa video" wide>
      <div className="mb-5 inline-flex rounded-lg bg-ink-850 p-1 ring-1 ring-ink-700">
        {([['upload', 'Carica file', UploadCloud], ['path', 'Da percorso locale', FolderInput]] as const).map(([k, l, Icon]) => (
          <button key={k} onClick={() => setTab(k)}
            className={cx('flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition',
              tab === k ? 'bg-nova-600 text-white' : 'text-zinc-400 hover:text-white')}>
            <Icon size={15} /> {l}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          {tab === 'upload' ? (
            <label
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); setFiles([...files, ...Array.from(e.dataTransfer.files)]) }}
              className={cx('flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition',
                dragOver ? 'border-pulse-400 bg-pulse-500/10' : 'border-ink-600 hover:border-nova-500 hover:bg-nova-500/5')}>
              <UploadCloud className="mb-2 text-nova-400" size={30} />
              <span className="text-sm font-medium text-zinc-200">Trascina qui i video o clicca per sceglierli</span>
              <span className="mt-1 text-xs text-zinc-500">MP4, MKV, MOV, AVI, WEBM, FLV, M4V, TS, WMV</span>
              <input type="file" multiple accept={ACCEPT} className="hidden"
                onChange={(e) => setFiles([...files, ...Array.from(e.target.files ?? [])])} />
            </label>
          ) : (
            <>
              <Field label="Percorso del file" hint={<>Percorso Linux (es. <code>/home/flavio/recordings/gta.mp4</code>) o Windows (<code>C:\Video\gta.mp4</code>, letto via /mnt/c).</>}>
                <input className="input font-mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/home/flavio/videos/session.mkv" />
              </Field>
              <div className="grid grid-cols-2 gap-2 text-sm">
                {([['reference', 'Riferimento', 'Il file resta dov\'è. Mai cancellato da CLIPNOVA.'],
                   ['copy', 'Copia', 'Copiato in data/videos (filesystem Linux, più veloce).']] as const).map(([k, l, d]) => (
                  <button key={k} onClick={() => setMode(k)}
                    className={cx('rounded-lg p-3 text-left ring-1 transition', mode === k ? 'bg-nova-500/10 ring-nova-500' : 'ring-ink-600 hover:bg-ink-800')}>
                    <div className="font-semibold text-white">{l}</div>
                    <div className="mt-0.5 text-xs text-zinc-400">{d}</div>
                  </button>
                ))}
              </div>
            </>
          )}

          {files.length > 0 && tab === 'upload' && (
            <ul className="max-h-36 space-y-1 overflow-y-auto rounded-lg bg-ink-850 p-2 text-xs">
              {files.map((f, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span className="truncate text-zinc-300">{f.name}</span>
                  <span className="shrink-0 text-zinc-500">{formatBytes(f.size)}</span>
                </li>
              ))}
              <li className="flex justify-between border-t border-ink-700 pt-1 font-semibold text-zinc-300">
                <span>{files.length} file</span><span>{formatBytes(totalSize)}</span>
              </li>
            </ul>
          )}
          {tab === 'upload' && totalSize > 2 * 1024 ** 3 && (
            <p className="text-xs text-amber-300">File molto grandi: l'importazione da percorso locale (modalità Riferimento) è più rapida e non duplica lo spazio.</p>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Gioco">
              <input className="input" list="games" value={game} onChange={(e) => setGame(e.target.value)} />
              <datalist id="games">{games.map((g) => <option key={g} value={g} />)}</datalist>
            </Field>
            <Field label="Creator">
              <input className="input" value={creator} onChange={(e) => setCreator(e.target.value)} placeholder="es. il tuo nickname" />
            </Field>
          </div>
          <Field label="Fonte">
            <input className="input" value={source} onChange={(e) => setSource(e.target.value)} placeholder="es. Registrazione OBS, VOD autorizzato…" />
          </Field>
          <Field label="Note">
            <textarea className="input min-h-[60px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </div>

        <div>
          <h3 className="mb-3 font-display text-sm font-semibold uppercase tracking-wider text-pulse-300">Diritti e autorizzazione</h3>
          <RightsForm value={rights} onChange={setRights} />
        </div>
      </div>

      {busy && tab === 'upload' && (
        <div className="mt-5">
          <ProgressBar value={progress} />
          <p className="mt-1 text-xs text-zinc-400">Upload {Math.round(progress * 100)}%</p>
        </div>
      )}

      <div className="mt-6 flex justify-end gap-2 border-t border-ink-700 pt-4">
        <button className="btn-ghost" onClick={close}>{busy ? 'Annulla upload' : 'Chiudi'}</button>
        <button className="btn-primary" disabled={busy} onClick={submit}>
          {busy ? 'Importazione…' : 'Importa'}
        </button>
      </div>
    </Modal>
  )
}
