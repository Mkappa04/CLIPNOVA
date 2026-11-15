import { Archive, Check, Clapperboard, Minus, Plus, RotateCcw, Save, Trash2, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { CATEGORIES, SIGNAL_LABELS, formatTime } from '../services/format'
import { toast } from '../stores/toastStore'
import type { Clip, ClipCategory } from '../types'
import { CategoryBadge } from './TimelineChart'
import { Badge, Field, ProgressBar, cx } from './ui'

function Nudge({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-1">
        <button className="btn-ghost px-2 py-1.5" onClick={() => onChange(Math.max(0, +(value - 1).toFixed(2)))} aria-label={`${label} -1s`}><Minus size={13} /></button>
        <input type="number" step={0.1} min={0} className="input text-center font-mono" value={value}
               onChange={(e) => onChange(Number(e.target.value))} />
        <button className="btn-ghost px-2 py-1.5" onClick={() => onChange(+(value + 1).toFixed(2))} aria-label={`${label} +1s`}><Plus size={13} /></button>
      </div>
    </Field>
  )
}

export function ClipInspector({ clip, onChanged, onDeleted }: { clip: Clip; onChanged: (c: Clip) => void; onDeleted: () => void }) {
  const [start, setStart] = useState(clip.start)
  const [end, setEnd] = useState(clip.end)
  const [title, setTitle] = useState(clip.suggested_title)
  const [category, setCategory] = useState<ClipCategory>(clip.category)
  const [busy, setBusy] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)

  useEffect(() => {
    setStart(clip.start); setEnd(clip.end); setTitle(clip.suggested_title); setCategory(clip.category); setConfirmDel(false)
  }, [clip.id, clip.start, clip.end, clip.suggested_title, clip.category])

  const dirty = start !== clip.start || end !== clip.end || title !== clip.suggested_title || category !== clip.category

  const save = async (extra: Partial<Pick<Clip, 'status'>> = {}) => {
    setBusy(true)
    try {
      const body = { ...(dirty ? { start, end, suggested_title: title, category } : {}), ...extra }
      const updated = await api.updateClip(clip.id, body)
      onChanged(updated)
      toast.success(extra.status ? `Clip → ${extra.status}` : 'Clip aggiornata')
    } catch (e) { toast.error(e) } finally { setBusy(false) }
  }

  const remove = async () => {
    try { await api.deleteClip(clip.id); toast.success('Clip eliminata'); onDeleted() } catch (e) { toast.error(e) }
  }

  const ranked = Object.entries(clip.category_scores).sort((a, b) => b[1] - a[1]).slice(0, 4)

  return (
    <div className="space-y-4">
      <video key={`${clip.id}-${clip.start}-${clip.end}`} controls preload="metadata" className="aspect-video w-full rounded-xl bg-black"
             src={api.previewUrl(clip)} />
      <p className="-mt-2 text-[11px] text-zinc-500">Anteprima nel formato originale; il montaggio verticale 9:16 arriva con la Milestone 3. La prima apertura genera l'anteprima (NVENC).</p>

      <div className="flex flex-wrap items-center gap-2">
        <CategoryBadge category={clip.category} />
        <Badge tone={clip.status === 'review' ? 'amber' : clip.status === 'rejected' ? 'red' : 'zinc'}>{clip.status}</Badge>
        {clip.origin === 'manual' && <Badge tone="cyan">manuale</Badge>}
        <span className="ml-auto font-mono text-xs text-zinc-400">{formatTime(clip.start)} → {formatTime(clip.end)} · {clip.duration.toFixed(1)}s</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-ink-850 p-3 ring-1 ring-ink-700">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">Score</div>
          <div className="font-display text-2xl font-bold text-white">{clip.score.toFixed(0)}<span className="text-sm text-zinc-500">/100</span></div>
        </div>
        <div className="rounded-lg bg-ink-850 p-3 ring-1 ring-ink-700">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">Confidenza categoria</div>
          <div className="font-display text-2xl font-bold text-white">{Math.round(clip.confidence * 100)}<span className="text-sm text-zinc-500">%</span></div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Nudge label="Inizio (s)" value={start} onChange={setStart} />
        <Nudge label="Fine (s)" value={end} onChange={setEnd} />
      </div>
      <Field label="Categoria">
        <select className="input" value={category} onChange={(e) => setCategory(e.target.value as ClipCategory)}>
          {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.emoji} {c.label}</option>)}
        </select>
      </Field>
      <Field label="Titolo suggerito" hint="Basato su frasi realmente presenti nella trascrizione; i titoli definitivi arrivano in Milestone 4.">
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>

      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={!dirty || busy} onClick={() => save()}><Save size={15} /> Salva</button>
        {dirty && <button className="btn-ghost" onClick={() => { setStart(clip.start); setEnd(clip.end); setTitle(clip.suggested_title); setCategory(clip.category) }}><RotateCcw size={15} /> Annulla</button>}
        <Link to={`/editor?clip=${clip.id}`} className="btn-cyan"><Clapperboard size={15} /> Apri nell'editor</Link>
        <button className="btn-ghost" disabled={busy || clip.status === 'review'} onClick={() => save({ status: 'review' })}><Check size={15} /> In revisione</button>
        <button className="btn-ghost" disabled={busy || clip.status === 'rejected'} onClick={() => save({ status: 'rejected' })}><X size={15} /> Scarta</button>
        <button className="btn-ghost" disabled={busy || clip.status === 'archived'} onClick={() => save({ status: 'archived' })}><Archive size={15} /> Archivia</button>
        {clip.status !== 'detected' && <button className="btn-ghost" disabled={busy} onClick={() => save({ status: 'detected' })}><RotateCcw size={15} /> Ripristina</button>}
      </div>

      <section>
        <h4 className="label">Perché è stata selezionata</h4>
        <p className="whitespace-pre-line rounded-lg bg-ink-850 p-3 text-sm text-zinc-300 ring-1 ring-ink-700">{clip.reason}</p>
      </section>

      {Object.keys(clip.signals).length > 0 && (
        <section>
          <h4 className="label">Segnali attorno al picco (0–1)</h4>
          <div className="space-y-1.5">
            {Object.entries(clip.signals).map(([k, v]) => (
              <div key={k} className="grid grid-cols-[130px_1fr_36px] items-center gap-2 text-xs">
                <span className="text-zinc-400">{SIGNAL_LABELS[k] ?? k}</span>
                <ProgressBar value={v} />
                <span className="text-right font-mono text-zinc-300">{v.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {ranked.length > 0 && (
        <section>
          <h4 className="label">Categorie candidate</h4>
          <div className="flex flex-wrap gap-2 text-xs">
            {ranked.map(([k, v], i) => (
              <span key={k} className={cx('rounded-md px-2 py-1 ring-1', i === 0 ? 'bg-ink-800 text-zinc-100 ring-ink-600' : 'text-zinc-400 ring-ink-700')}>
                {CATEGORIES.find((c) => c.id === k)?.label ?? k} <span className="font-mono">{v.toFixed(2)}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <h4 className="label">Trascrizione della clip</h4>
        <p className="max-h-40 overflow-y-auto rounded-lg bg-ink-850 p-3 text-sm italic text-zinc-300 ring-1 ring-ink-700">
          {clip.transcript || <span className="not-italic text-zinc-500">Nessun parlato rilevato in questo intervallo.</span>}
        </p>
      </section>

      <div className="border-t border-ink-700 pt-3">
        {!confirmDel ? (
          <button className="btn-danger" onClick={() => setConfirmDel(true)}><Trash2 size={15} /> Elimina clip</button>
        ) : (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-red-200">Eliminare definitivamente questa clip?</span>
            <button className="btn-danger" onClick={remove}>Conferma</button>
            <button className="btn-ghost" onClick={() => setConfirmDel(false)}>Annulla</button>
          </div>
        )}
      </div>
    </div>
  )
}
