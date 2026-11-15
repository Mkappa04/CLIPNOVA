import { Archive, Bot, CheckCircle2, Clapperboard, Download, FileText, Package, RefreshCw, RotateCcw, Save, ShieldCheck, ShieldX, Wand2, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CategoryBadge } from '../components/TimelineChart'
import { Badge, EmptyState, Field, PageHeader, Spinner, StatusBadge, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { PLATFORM_LABELS, formatBytes, formatDate } from '../services/format'
import { toast } from '../stores/toastStore'
import type { ClipContent, ExportItem, Platform, RightsDecision, ReviewItem } from '../types'

const TABS = [
  ['review', 'In revisione'], ['approved', 'Approvate'], ['exported', 'Esportate'], ['rejected', 'Rifiutate'], ['archived', 'Archiviate'],
] as const

function Decision({ label, d }: { label: string; d: RightsDecision }) {
  return (
    <div className={cx('rounded-lg p-2.5 text-xs ring-1', d.allowed ? 'bg-emerald-500/5 ring-emerald-500/30' : 'bg-red-500/5 ring-red-500/30')}>
      <div className="mb-1 flex items-center gap-1.5 font-semibold text-white">
        {d.allowed ? <ShieldCheck size={14} className="text-emerald-400" /> : <ShieldX size={14} className="text-red-400" />}
        {label}: <span className={d.allowed ? 'text-emerald-300' : 'text-red-300'}>{d.allowed ? 'consentito' : 'bloccato'}</span>
      </div>
      {d.blockers.map((b) => <div key={b} className="text-red-200">• {b}</div>)}
      {d.warnings.map((w) => <div key={w} className="text-amber-200">⚠ {w}</div>)}
    </div>
  )
}

function Counter({ value, max }: { value: string; max: number }) {
  return <span className={cx('text-[10px]', value.length > max ? 'text-red-400' : 'text-zinc-500')}>{value.length}/{max}</span>
}

function ContentEditor({ item, onSaved }: { item: ReviewItem; onSaved: (i: ReviewItem) => void }) {
  const [c, setC] = useState<ClipContent | null>(item.content)
  const [tags, setTags] = useState((item.content?.hashtags ?? []).map((t) => `#${t}`).join(' '))
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const { data: llm } = useApi(() => api.llmStatus())

  useEffect(() => { setC(item.content); setTags((item.content?.hashtags ?? []).map((t) => `#${t}`).join(' ')); setWarnings([]) }, [item.clip.id, item.content])

  const gen = async (useLlm: boolean) => {
    setBusy(useLlm ? 'llm' : 'tpl')
    try {
      const r = await api.generateContent(item.clip.id, useLlm, c?.language)
      setC(r.content); setTags(r.content.hashtags.map((t) => `#${t}`).join(' ')); setWarnings(r.warnings)
      toast.info(useLlm ? 'Bozza LLM pronta: rivedila e salva' : 'Bozza pronta: rivedila e salva')
    } catch (e) { toast.error(e) } finally { setBusy(null) }
  }
  const save = async () => {
    if (!c) return
    setBusy('save')
    try {
      const hashtags = tags.split(/[\s,]+/).map((t) => t.replace(/^#/, '')).filter(Boolean)
      const r = await api.saveContent(item.clip.id, { ...c, hashtags })
      if (r.approval_revoked) toast.info('Testi modificati: la clip torna in revisione e va riapprovata')
      else toast.success('Testi salvati')
      onSaved(r)
    } catch (e) { toast.error(e) } finally { setBusy(null) }
  }

  if (!c) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-zinc-400">Nessun testo ancora.</span>
        <button className="btn-cyan" onClick={() => gen(false)} disabled={!!busy}><Wand2 size={15} /> Genera testi</button>
      </div>
    )
  }
  const set = <K extends keyof ClipContent>(k: K, v: ClipContent[K]) => setC({ ...c, [k]: v })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select className="input w-auto py-1 text-xs" value={c.language} onChange={(e) => set('language', e.target.value as 'it' | 'en')}>
          <option value="it">Italiano</option><option value="en">English</option>
        </select>
        <button className="btn-ghost px-2.5 py-1 text-xs" onClick={() => gen(false)} disabled={!!busy}><Wand2 size={13} /> Rigenera (template)</button>
        <button className="btn-ghost px-2.5 py-1 text-xs" onClick={() => gen(true)} disabled={!!busy || !llm?.available}
                title={llm?.available ? `LLM locale: ${llm.model}` : llm?.reason ?? 'LLM locale disabilitato (CLIPNOVA_LLM_PROVIDER=none)'}>
          {busy === 'llm' ? <Spinner /> : <Bot size={13} />} LLM locale{llm?.available ? ` (${llm.model})` : ' (off)'}
        </button>
        {c.generated_by && <Badge tone="zinc">{c.generated_by}</Badge>}
      </div>
      {warnings.length > 0 && (
        <ul className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-200 ring-1 ring-amber-500/30">
          {warnings.map((w) => <li key={w}>⚠ {w}</li>)}
        </ul>
      )}
      <Field label="Titolo" hint={<Counter value={c.title} max={100} />}><input className="input" value={c.title} onChange={(e) => set('title', e.target.value)} /></Field>
      <Field label="Hook iniziale"><input className="input" value={c.hook} onChange={(e) => set('hook', e.target.value)} /></Field>
      <Field label="Caption (TikTok / Instagram)" hint={<Counter value={c.caption} max={2200} />}>
        <textarea className="input min-h-[70px]" value={c.caption} onChange={(e) => set('caption', e.target.value)} />
      </Field>
      <Field label="Descrizione (YouTube)"><textarea className="input min-h-[90px]" value={c.description} onChange={(e) => set('description', e.target.value)} /></Field>
      <Field label="Hashtag" hint="Separati da spazio. #Shorts viene aggiunto automaticamente per YouTube.">
        <input className="input font-mono text-xs" value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
      <Field label="Call to action"><input className="input" value={c.cta} onChange={(e) => set('cta', e.target.value)} /></Field>
      {item.attribution && <p className="text-xs text-zinc-400">Attribuzione obbligatoria, aggiunta automaticamente all'export: <b className="text-zinc-200">{item.attribution}</b></p>}
      <button className="btn-primary" onClick={save} disabled={!!busy}><Save size={15} /> Salva testi</button>
    </div>
  )
}

function ExportPanel({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const [platforms, setPlatforms] = useState<Platform[]>(['tiktok', 'instagram', 'youtube'])
  const [purpose, setPurpose] = useState<'commercial' | 'non_commercial'>('commercial')
  const [result, setResult] = useState<ExportItem | null>(null)
  const [blockers, setBlockers] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const decision = item.rights[purpose]

  const run = async () => {
    setBusy(true); setBlockers([])
    try { const e = await api.createExport(item.clip.id, platforms, purpose); setResult(e); toast.success('Pacchetto di export pronto'); onDone() }
    catch (e) {
      const details = (e as { details?: { blockers?: string[] } }).details
      if (details?.blockers) setBlockers(details.blockers)
      toast.error(e)
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        {(['tiktok', 'instagram', 'youtube'] as Platform[]).map((p) => (
          <label key={p} className="flex items-center gap-2 text-sm text-zinc-200">
            <input type="checkbox" className="accent-nova-500" checked={platforms.includes(p)}
                   onChange={(e) => setPlatforms(e.target.checked ? [...platforms, p] : platforms.filter((x) => x !== p))} />
            {PLATFORM_LABELS[p]}
          </label>
        ))}
      </div>
      <div className="flex flex-wrap gap-3 text-sm">
        {(['commercial', 'non_commercial'] as const).map((p) => (
          <label key={p} className="flex items-center gap-2 text-zinc-200">
            <input type="radio" name="purpose" className="accent-nova-500" checked={purpose === p} onChange={() => setPurpose(p)} />
            {p === 'commercial' ? 'Uso commerciale (canale monetizzato)' : 'Uso non commerciale'}
          </label>
        ))}
      </div>
      <Decision label="Verifica diritti" d={decision} />
      {blockers.length > 0 && <div className="text-xs text-red-200">{blockers.map((b) => <div key={b}>• {b}</div>)}</div>}
      <button className="btn-primary" onClick={run} disabled={busy || !platforms.length || !decision.allowed}>
        {busy ? <Spinner /> : <Package size={15} />} Crea pacchetto export
      </button>
      {!decision.allowed && <p className="text-xs text-zinc-500">Correggi i diritti del video nella <Link to="/library" className="text-pulse-400 hover:underline">Libreria</Link> (scheda del video → Diritti).</p>}
      {result && <ExportFiles e={result} />}
    </div>
  )
}

export function ExportFiles({ e }: { e: ExportItem }) {
  return (
    <div className="space-y-2 rounded-lg bg-ink-850 p-3 text-xs ring-1 ring-ink-700">
      <div className="flex flex-wrap gap-2">
        <a className="btn-cyan px-2.5 py-1 text-xs" href={api.exportFileUrl(e.id, 'package.zip')}><Download size={13} /> Scarica pacchetto .zip</a>
        {e.files.filter((f) => f.endsWith('.mp4')).map((f) => <a key={f} className="btn-ghost px-2.5 py-1 text-xs" href={api.exportFileUrl(e.id, f)}><Download size={13} /> MP4</a>)}
        {e.files.filter((f) => f.endsWith('.txt')).map((f) => (
          <a key={f} className="btn-ghost px-2.5 py-1 text-xs" href={api.exportFileUrl(e.id, f)} target="_blank" rel="noreferrer"><FileText size={13} /> {f}</a>
        ))}
      </div>
      <div className="break-all font-mono text-zinc-500">{e.path}</div>
      {e.copied_to && <div className="break-all text-emerald-300">Copiato anche in: <span className="font-mono">{e.copied_to}</span></div>}
    </div>
  )
}

export function ApprovalCenter() {
  const [tab, setTab] = useState<string>('review')
  const { data: counts, reload: reloadCounts } = useApi(() => api.approvalCounts(), [], 5000)
  const { data: items, reload } = useApi(() => api.approvalQueue(tab), [tab], 5000)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [item, setItem] = useState<ReviewItem | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => { if (items && !items.some((i) => i.clip.id === selectedId)) setSelectedId(items[0]?.clip.id ?? null) }, [items])
  useEffect(() => { setItem(items?.find((i) => i.clip.id === selectedId) ?? null); setNote('') }, [selectedId])
  useEffect(() => { if (selectedId) api.review(selectedId).then(setItem).catch(() => {}) }, [selectedId])

  const refresh = () => { reload(); reloadCounts(); if (selectedId) api.review(selectedId).then(setItem).catch(() => {}) }
  const act = async (action: 'approve' | 'reject' | 'archive' | 'reopen') => {
    if (!item) return
    try {
      const r = await api.reviewAction(item.clip.id, action, note)
      setItem(r); toast.success({ approve: 'Clip approvata', reject: 'Clip rifiutata', archive: 'Clip archiviata', reopen: 'Clip riaperta' }[action])
      setNote(''); reload(); reloadCounts()
    } catch (e) { toast.error(e) }
  }
  const regenerate = async () => {
    if (!item) return
    try { await api.regenerate(item.clip.id); toast.info('Nuovo render in coda: la clip tornerà in revisione') } catch (e) { toast.error(e) }
  }
  const status = item?.clip.status
  const canExport = status === 'approved' || status === 'exported'
  const list = useMemo(() => items ?? [], [items])

  return (
    <>
      <PageHeader title="Approval Center" subtitle="Niente viene esportato o pubblicato senza la tua approvazione esplicita" />
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={cx('rounded-full px-3 py-1 text-sm ring-1 transition', tab === k ? 'bg-nova-600 text-white ring-nova-500' : 'text-zinc-400 ring-ink-600 hover:text-white')}>
            {l} <span className="ml-1 text-xs opacity-70">{counts?.[k] ?? 0}</span>
          </button>
        ))}
      </div>

      {!items && <Spinner />}
      {items && list.length === 0 && (
        <EmptyState icon={<CheckCircle2 size={28} />} title="Nessuna clip in questa sezione"
          text={tab === 'review' ? 'Le clip arrivano qui dopo il render nel Clip Editor.' : undefined}
          action={tab === 'review' ? <Link to="/editor" className="btn-primary">Apri il Clip Editor</Link> : undefined} />
      )}

      {list.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
          <ul className="space-y-2">
            {list.map((i) => (
              <li key={i.clip.id}>
                <button onClick={() => setSelectedId(i.clip.id)}
                  className={cx('card flex w-full gap-3 p-2 text-left transition hover:border-nova-500/60', i.clip.id === selectedId && 'border-nova-500 shadow-glow')}>
                  <div className="h-20 w-[45px] shrink-0 overflow-hidden rounded bg-ink-850">
                    {i.render?.has_thumbnail && <img src={api.renderThumbUrl(i.render.id)} alt="" className="h-full w-full object-cover" />}
                  </div>
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="line-clamp-2 text-sm text-zinc-100">{i.content?.title || i.clip.suggested_title}</div>
                    <div className="flex flex-wrap gap-1"><CategoryBadge category={i.clip.category} /></div>
                    <div className="truncate text-[11px] text-zinc-500">{i.clip.video_title}</div>
                  </div>
                </button>
              </li>
            ))}
          </ul>

          {item && (
            <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
              <div className="space-y-3">
                {item.render ? (
                  <video key={item.render.id} controls src={api.renderFileUrl(item.render.id)}
                         poster={item.render.has_thumbnail ? api.renderThumbUrl(item.render.id) : undefined}
                         className="aspect-[9/16] w-full rounded-xl bg-black ring-1 ring-ink-600" />
                ) : <div className="grid aspect-[9/16] place-items-center rounded-xl bg-ink-850 text-sm text-zinc-500">Nessun render</div>}
                {item.render && (
                  <div className="text-xs text-zinc-500">
                    {item.render.duration?.toFixed(1)}s · {formatBytes(item.render.file_size ?? 0)} · {item.render.config.layout} · {formatDate(item.render.finished_at)}
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <Link to={`/editor?clip=${item.clip.id}`} className="btn-ghost px-2.5 py-1.5 text-xs"><Clapperboard size={13} /> Modifica</Link>
                  <Link to={`/subtitles?clip=${item.clip.id}`} className="btn-ghost px-2.5 py-1.5 text-xs">Sottotitoli</Link>
                  <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={regenerate}><RefreshCw size={13} /> Rigenera</button>
                </div>
                <div className="space-y-2">
                  <Decision label="Non commerciale" d={item.rights.non_commercial} />
                  <Decision label="Commerciale" d={item.rights.commercial} />
                </div>
              </div>

              <div className="space-y-5">
                <section className="card p-4">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <StatusBadge status={item.clip.status} />
                    {item.approved_at && <span className="text-xs text-emerald-300">approvata {formatDate(item.approved_at)}</span>}
                    {item.review_note && <span className="text-xs text-zinc-400">nota: {item.review_note}</span>}
                  </div>
                  <textarea className="input mb-3 min-h-[44px] text-sm" placeholder="Nota di revisione (facoltativa)" value={note} onChange={(e) => setNote(e.target.value)} />
                  <div className="flex flex-wrap gap-2">
                    <button className="btn-primary" onClick={() => act('approve')} disabled={status !== 'review' || !item.render}
                            title={!item.render ? 'Serve un render completato' : undefined}><CheckCircle2 size={15} /> Approva</button>
                    <button className="btn-danger" onClick={() => act('reject')} disabled={status === 'rejected'}><XCircle size={15} /> Rifiuta</button>
                    <button className="btn-ghost" onClick={() => act('archive')} disabled={status === 'archived'}><Archive size={15} /> Archivia</button>
                    {['rejected', 'archived', 'approved', 'exported'].includes(status ?? '') &&
                      <button className="btn-ghost" onClick={() => act('reopen')}><RotateCcw size={15} /> Riapri</button>}
                  </div>
                </section>

                <section className="card p-4">
                  <h3 className="mb-3 font-display font-semibold text-white">Titolo, caption e hashtag</h3>
                  <ContentEditor item={item} onSaved={(r) => { setItem(r); refresh() }} />
                </section>

                <section className={cx('card p-4', !canExport && 'opacity-60')}>
                  <h3 className="mb-1 font-display font-semibold text-white">Export</h3>
                  <p className="mb-3 text-xs text-zinc-400">
                    {canExport ? 'Pacchetto pronto da caricare a mano: video, testi per piattaforma, sottotitoli e checklist.' : 'Disponibile dopo l\'approvazione.'}
                  </p>
                  {canExport && <ExportPanel item={item} onDone={refresh} />}
                </section>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
