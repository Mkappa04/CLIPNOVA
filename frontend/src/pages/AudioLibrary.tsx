import { FileAudio, Music2, Trash2, Upload } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Section, Segmented, Slider, Toggle } from '../components/EditorControls'
import { MOOD_LABEL } from '../components/EditingPanels'
import { Badge, EmptyState, Field, PageHeader, Spinner, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes } from '../services/format'
import { toast } from '../stores/toastStore'
import type { AudioAsset } from '../types'

const EMPTY = { kind: 'music', category: 'dynamic', title: '', license: '', attribution: '', source_url: '', notes: '', rights_confirmed: false }

function AssetRow({ a, onChanged }: { a: AudioAsset; onChanged: () => void }) {
  const [gain, setGain] = useState(a.gain_db)
  const [confirm, setConfirm] = useState(false)
  const patch = async (body: Parameters<typeof api.patchAudio>[1]) => {
    try { await api.patchAudio(a.id, body); onChanged() } catch (e) { toast.error(e) }
  }
  const del = async () => {
    try { await api.deleteAudio(a.id); toast.success('File eliminato'); onChanged() } catch (e) { toast.error(e) }
  }
  return (
    <li className={cx('grid gap-3 py-3 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(180px,0.8fr)] md:items-center', !a.enabled && 'opacity-55')}>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm text-bone-100">
          {a.title}
          <Badge tone={a.origin === 'user' ? 'violet' : 'zinc'}>{a.origin === 'user' ? 'tuo' : 'di serie'}</Badge>
          <span className="font-mono text-[10px] uppercase tracking-wider text-graphite-400">{a.kind === 'music' ? MOOD_LABEL[a.category] ?? a.category : a.category.replace('_', ' ')}</span>
        </p>
        <p className="timecode mt-0.5 text-[11px] text-graphite-400">
          {a.duration.toFixed(1)}s{a.bpm ? ` · ${Math.round(a.bpm)} BPM` : ''}{a.drop_time != null ? ` · drop ${a.drop_time.toFixed(1)}s` : ''}
          {a.loudness_db != null ? ` · ${a.loudness_db} dB` : ''}{a.file_size ? ` · ${formatBytes(a.file_size)}` : ''}
        </p>
        <p className="mt-0.5 text-[11px] text-graphite-500">{a.license_label}{a.attribution ? ` · ${a.attribution}` : ''}{a.source_url ? ` · ${a.source_url}` : ''}</p>
      </div>
      <audio controls preload="none" src={a.url} className="h-8 w-full" aria-label={`Ascolta ${a.title}`} />
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <Slider label="Volume" value={gain} min={-18} max={12} step={1} onChange={setGain} fmt={(v) => `${v > 0 ? '+' : ''}${v} dB`} />
          {gain !== a.gain_db && <button className="link text-xs" onClick={() => patch({ gain_db: gain })}>salva volume</button>}
        </div>
        <input type="checkbox" className="h-4 w-4 accent-[#ff5a1f]" checked={a.enabled} onChange={(e) => patch({ enabled: e.target.checked })}
          aria-label={a.enabled ? 'Disattiva' : 'Attiva'} title={a.enabled ? 'Usabile dal regista' : 'Disattivato'} />
        {a.origin === 'user' && (!confirm
          ? <button className="rounded-sm p-1 text-graphite-400 hover:text-err" onClick={() => setConfirm(true)} aria-label="Elimina"><Trash2 size={14} /></button>
          : <button className="btn-danger px-2 py-1 text-xs" onClick={del}>Conferma</button>)}
      </div>
    </li>
  )
}

export function AudioLibrary() {
  const { data: meta } = useApi(() => api.audioMeta())
  const { data: assets, reload } = useApi(() => api.audioLibrary())
  const [kind, setKind] = useState<'music' | 'sfx'>('music')
  const [form, setForm] = useState({ ...EMPTY })
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const list = useMemo(() => (assets ?? []).filter((a) => a.kind === kind), [assets, kind])
  const setF = (k: keyof typeof EMPTY, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }))
  const cats = form.kind === 'music' ? (meta?.moods ?? []).map((m) => ({ id: m.id, label: m.label })) : (meta?.sfx_categories ?? [])
  const needsAttribution = form.license === 'cc_by'
  const needsSource = ['cc_by', 'royalty_free', 'licensed'].includes(form.license)
  const ready = !!file && !!form.license && form.rights_confirmed && (!needsAttribution || form.attribution.trim().length >= 3) &&
    (!needsSource || (form.source_url || form.notes).trim().length >= 4)

  const submit = async () => {
    if (!file) return
    setBusy(true)
    try {
      const a = await api.importAudio(file, form)
      toast.success(`Importato: ${a.title}${a.bpm ? ` (${Math.round(a.bpm)} BPM)` : ''}`)
      setForm({ ...EMPTY, kind: form.kind, category: form.category }); setFile(null); reload()
    } catch (e) { toast.error(e) } finally { setBusy(false) }
  }

  return (
    <>
      <PageHeader title="Libreria audio" subtitle="Musiche ed effetti sonori che il regista può usare. Solo file con licenza dichiarata." />
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-w-0">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Segmented value={kind} onChange={setKind} options={[{ value: 'music', label: 'Musica' }, { value: 'sfx', label: 'Effetti sonori' }]} />
            <span className="text-xs text-graphite-500">{list.filter((a) => a.enabled).length} attivi su {list.length}</span>
          </div>
          {!assets && <Spinner />}
          {assets && list.length === 0 && <EmptyState icon={<Music2 size={26} />} title="Nessun file" />}
          <ul className="divide-y divide-graphite-800 border-y border-graphite-800">
            {list.map((a) => <AssetRow key={a.id} a={a} onChanged={reload} />)}
          </ul>
          <p className="mt-3 text-xs text-graphite-500">
            Le tracce di serie sono composte proceduralmente da CLIPNOVA (CC0): funzionano, ma non valgono una produzione professionale.
            Importa musica con licenza (es. libreria audio di YouTube, Pixabay Music, brani acquistati) e il regista la preferirà per lo stesso mood.
          </p>
        </section>

        <aside>
          <Section title="Importa un file">
            <input ref={input} type="file" accept={(meta?.formats ?? []).join(',')} className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button className="btn-ghost w-full justify-center" onClick={() => input.current?.click()}>
              {file ? <><FileAudio size={15} /> {file.name}</> : <><Upload size={15} /> Scegli un file audio</>}
            </button>
            <Segmented value={form.kind} onChange={(v) => setForm((f) => ({ ...f, kind: v, category: v === 'music' ? 'dynamic' : 'whoosh' }))}
              options={[{ value: 'music', label: 'Musica' }, { value: 'sfx', label: 'Effetto sonoro' }]} />
            <Field label={form.kind === 'music' ? 'Mood' : 'Categoria'}>
              <select className="input" value={form.category} onChange={(e) => setF('category', e.target.value)}>
                {cats.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </Field>
            <Field label="Titolo"><input className="input" maxLength={160} value={form.title} onChange={(e) => setF('title', e.target.value)} placeholder={file?.name ?? ''} /></Field>
            <Field label="Licenza (obbligatoria)">
              <select className="input" value={form.license} onChange={(e) => setF('license', e.target.value)}>
                <option value="">— scegli —</option>
                {meta?.licenses.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
              </select>
            </Field>
            {needsAttribution && <Field label="Attribuzione (autore, titolo)"><input className="input" value={form.attribution} onChange={(e) => setF('attribution', e.target.value)} /></Field>}
            {needsSource && <Field label="Fonte / URL della licenza"><input className="input" value={form.source_url} onChange={(e) => setF('source_url', e.target.value)} placeholder="https://…" /></Field>}
            <Field label="Note"><input className="input" value={form.notes} onChange={(e) => setF('notes', e.target.value)} /></Field>
            <Toggle label="Ho i diritti per usare questo file nei miei video" checked={form.rights_confirmed} onChange={(v) => setF('rights_confirmed', v)}
              hint="Niente musica commerciale senza licenza: i social silenziano o bloccano i video" />
            <button className="btn-primary w-full justify-center" disabled={!ready || busy} onClick={submit}>
              {busy ? <Spinner className="h-4 w-4" /> : <Upload size={15} />} Importa e analizza
            </button>
            {meta && <p className="text-[11px] text-graphite-500">{meta.formats.join(' ')} · max {meta.max_mb} MB. Durata, volume, BPM e drop vengono stimati in automatico.</p>}
          </Section>
        </aside>
      </div>
    </>
  )
}
