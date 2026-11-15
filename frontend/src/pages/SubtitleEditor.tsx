import { Captions, Download, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Badge, EmptyState, PageHeader, Spinner, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { toast } from '../stores/toastStore'
import type { Cue, EditConfig } from '../types'

export function SubtitleEditor() {
  const [params, setParams] = useSearchParams()
  const { data: clips } = useApi(() => api.clips({ sort: 'score' }), [])
  const usable = useMemo(() => (clips ?? []).filter((c) => !['rejected', 'archived'].includes(c.status)), [clips])
  const clipId = params.get('clip') ?? usable[0]?.id ?? null
  const clip = clips?.find((c) => c.id === clipId) ?? null

  const [cues, setCues] = useState<Cue[] | null>(null)
  const [orig, setOrig] = useState('')
  const [edited, setEdited] = useState(false)
  const [cfg, setCfg] = useState<EditConfig | null>(null)
  const [selected, setSelected] = useState(0)
  const [preview, setPreview] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)

  const load = async (id: string) => {
    const [s, e] = await Promise.all([api.subtitles(id), api.editState(id)])
    setCues(s.cues); setOrig(JSON.stringify(s.cues)); setEdited(s.edited); setCfg(e.config); setSelected(0)
  }
  useEffect(() => { if (clipId) load(clipId).catch(toast.error) }, [clipId])

  // Preview of the selected cue (uses the saved subtitles)
  useEffect(() => {
    if (!clipId || !cfg || !cues?.length) return
    const c = cues[Math.min(selected, cues.length - 1)]
    const tm = (c.start + c.end) / 2
    const h = setTimeout(() => {
      api.previewFrame(clipId, tm, cfg).then((u) => setPreview((old) => { if (old) URL.revokeObjectURL(old); return u })).catch(() => {})
    }, 300)
    return () => clearTimeout(h)
  }, [clipId, cfg, selected, orig])

  if (clips && usable.length === 0) {
    return (<><PageHeader title="Subtitle Editor" />
      <EmptyState icon={<Captions size={28} />} title="Nessuna clip" text="Le clip rilevate compaiono qui con i sottotitoli generati dalla trascrizione." /></>)
  }

  const dirty = cues ? JSON.stringify(cues) !== orig : false
  const update = (i: number, patch: Partial<Cue>) => cues && setCues(cues.map((c, k) => (k === i ? { ...c, ...patch } : c)))
  const remove = (i: number) => cues && setCues(cues.filter((_, k) => k !== i))
  const addAfter = (i: number) => {
    if (!cues || !clip) return
    const prev = cues[i]
    const start = prev ? prev.end : 0
    const next = cues[i + 1]
    const end = Math.min(next ? next.start : clip.duration, start + 1.5)
    if (end - start < 0.2) return toast.error('Non c\'è spazio tra queste due righe')
    const c: Cue = { start: +start.toFixed(2), end: +end.toFixed(2), text: 'Nuovo testo', words: [] }
    setCues([...cues.slice(0, i + 1), c, ...cues.slice(i + 1)]); setSelected(i + 1)
  }
  const save = async () => {
    if (!clipId || !cues) return
    try { const s = await api.saveSubtitles(clipId, cues); setCues(s.cues); setOrig(JSON.stringify(s.cues)); setEdited(true); toast.success('Sottotitoli salvati') }
    catch (e) { toast.error(e) }
  }
  const reset = async () => {
    if (!clipId) return
    try { const s = await api.resetSubtitles(clipId); setCues(s.cues); setOrig(JSON.stringify(s.cues)); setEdited(false); setConfirmReset(false); toast.success('Ripristinati dalla trascrizione') }
    catch (e) { toast.error(e) }
  }

  return (
    <>
      <PageHeader title="Subtitle Editor" subtitle="Correggi testo e tempi: la sincronizzazione parola per parola viene mantenuta o ridistribuita automaticamente"
        actions={
          <select className="input w-auto max-w-sm" value={clipId ?? ''} onChange={(e) => setParams({ clip: e.target.value })}>
            {usable.map((c) => <option key={c.id} value={c.id}>{c.suggested_title.slice(0, 50)} · {c.video_title.slice(0, 24)}</option>)}
          </select>
        } />
      {!cues && <Spinner />}
      {clip && cues && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="card p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Badge tone={edited ? 'amber' : 'zinc'}>{edited ? 'modificati a mano' : 'automatici (Whisper)'}</Badge>
              {cfg && <Badge tone="violet">preset {cfg.subtitle_preset}</Badge>}
              <span className="text-xs text-zinc-500">{cues.length} righe · tempi relativi all'inizio della clip</span>
              <span className="ml-auto flex gap-2">
                <a className="btn-ghost px-2 py-1 text-xs" href={api.subtitleExportUrl(clip.id, 'srt')}><Download size={13} /> SRT</a>
                <a className="btn-ghost px-2 py-1 text-xs" href={api.subtitleExportUrl(clip.id, 'ass')}><Download size={13} /> ASS</a>
              </span>
            </div>
            {cues.length === 0 && (
              <div className="py-8 text-center text-sm text-zinc-400">
                Nessun parlato trascritto in questa clip. <button className="text-pulse-400 hover:underline" onClick={() => addAfter(-1)}>Aggiungi una riga</button>
              </div>
            )}
            <ul className="space-y-1.5">
              {cues.map((c, i) => (
                <li key={i} onClick={() => setSelected(i)}
                    className={cx('grid grid-cols-[72px_72px_1fr_auto] items-center gap-2 rounded-lg p-1.5 ring-1',
                      i === selected ? 'bg-nova-500/10 ring-nova-500/60' : 'ring-transparent hover:bg-ink-850')}>
                  <input type="number" step={0.05} min={0} aria-label="inizio" className="input px-2 py-1 font-mono text-xs" value={c.start}
                         onChange={(e) => update(i, { start: Number(e.target.value) })} />
                  <input type="number" step={0.05} min={0} aria-label="fine" className="input px-2 py-1 font-mono text-xs" value={c.end}
                         onChange={(e) => update(i, { end: Number(e.target.value) })} />
                  <input className="input py-1" value={c.text} maxLength={300} onChange={(e) => update(i, { text: e.target.value })} />
                  <span className="flex gap-1">
                    <button className="btn-ghost px-1.5 py-1" onClick={() => addAfter(i)} aria-label="Aggiungi riga dopo"><Plus size={13} /></button>
                    <button className="btn-ghost px-1.5 py-1" onClick={() => remove(i)} aria-label="Elimina riga"><Trash2 size={13} /></button>
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap gap-2 border-t border-ink-700 pt-3">
              <button className="btn-primary" disabled={!dirty} onClick={save}><Save size={15} /> Salva sottotitoli</button>
              {dirty && <button className="btn-ghost" onClick={() => setCues(JSON.parse(orig))}><RotateCcw size={15} /> Annulla modifiche</button>}
              {edited && (!confirmReset
                ? <button className="btn-ghost" onClick={() => setConfirmReset(true)}>Ripristina da trascrizione</button>
                : <span className="flex items-center gap-2 text-sm text-red-200">Perdere le modifiche? <button className="btn-danger" onClick={reset}>Conferma</button>
                    <button className="btn-ghost" onClick={() => setConfirmReset(false)}>No</button></span>)}
              <Link to={`/editor?clip=${clip.id}`} className="btn-cyan ml-auto">Vai al Clip Editor</Link>
            </div>
          </div>
          <div className="card p-4 lg:sticky lg:top-6 lg:self-start">
            <div className="mx-auto aspect-[9/16] w-full max-w-[280px] overflow-hidden rounded-xl bg-black ring-1 ring-ink-600">
              {preview && <img src={preview} alt="Anteprima sottotitolo" className="h-full w-full object-contain" />}
            </div>
            <p className="mt-2 text-center text-xs text-zinc-500">{dirty ? 'Salva per vedere le modifiche nell\'anteprima' : 'Anteprima della riga selezionata'}</p>
          </div>
        </div>
      )}
    </>
  )
}
