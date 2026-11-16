import { Check, ChevronDown, Copy, Eye, Hash, RefreshCw, Save, Sparkles, Type, X } from 'lucide-react'
import { useEffect, useState, type KeyboardEvent } from 'react'
import { api } from '../services/api'
import { toast } from '../stores/toastStore'
import type { ClipContent, MetadataPart, ReviewItem, SocialMetadata } from '../types'
import { Badge, Field, Spinner, cx } from './ui'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs'

const PLATFORM_TABS = [
  { id: 'instagram', label: 'Instagram Reels', max: 2200 },
  { id: 'tiktok', label: 'TikTok', max: 2200 },
  { id: 'youtube_shorts', label: 'YouTube Shorts', max: 5000 },
] as const

const TONE_LABEL: Record<string, string> = {
  divertente: 'divertente', teso: 'teso', drammatico: 'drammatico', epico: 'epico', arrabbiato: 'arrabbiato',
  informativo: 'informativo', emozionante: 'emozionante', rilassato: 'rilassato', sorpreso: 'sorpreso', neutro: 'neutro',
}

/** Content saved before 1.3 (one caption for everything) → the per-platform structure. */
function fromLegacy(c: ClipContent): SocialMetadata {
  return {
    version: 2, language: c.language, generated_by: c.generated_by ?? 'manual', visual_used: false,
    content_analysis: { category: c.category ?? '', subject: '', event: '', context: '', key_moment: '', why_interesting: '',
      speaker: 'non identificabile', tone: 'neutro', emotion: '', evidence: [], confidence: 0.5, insufficient_context: false, source: 'rules' },
    titles: { options: [c.title || 'Senza titolo'], selected: c.title || 'Senza titolo' },
    platforms: {
      instagram: { caption: c.caption, hashtags: c.hashtags }, tiktok: { caption: c.caption, hashtags: c.hashtags },
      youtube_shorts: { title: c.title, description: c.description, hashtags: c.hashtags },
    },
  }
}

function copy(text: string, what: string) {
  navigator.clipboard?.writeText(text).then(() => toast.success(`${what} copiato`)).catch(() => toast.error('Copia non riuscita'))
}

function CopyBtn({ text, what }: { text: string; what: string }) {
  return (
    <button type="button" onClick={() => copy(text, what)} aria-label={`Copia ${what.toLowerCase()}`} title={`Copia ${what.toLowerCase()}`}
      className="rounded-sm p-1 text-graphite-400 transition-colors hover:bg-graphite-800 hover:text-bone-100"><Copy size={13} /></button>
  )
}

function Count({ value, max }: { value: string; max: number }) {
  return <span className={cx('timecode text-[10px]', value.length > max ? 'text-err' : 'text-graphite-500')}>{value.length}/{max}</span>
}

/** Hashtags as removable chips; type + Enter/space/comma to add. */
function TagEditor({ tags, onChange, limit }: { tags: string[]; onChange: (t: string[]) => void; limit?: [number, number] }) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const t = draft.replace(/^#+/, '').replace(/[^\p{L}\p{N}_]/gu, '')
    if (t && !tags.some((x) => x.toLowerCase() === t.toLowerCase())) onChange([...tags, t])
    setDraft('')
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (['Enter', ' ', ','].includes(e.key)) { e.preventDefault(); add() }
    if (e.key === 'Backspace' && !draft && tags.length) onChange(tags.slice(0, -1))
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-graphite-600 bg-graphite-850 px-2 py-1.5 focus-within:border-tally-500">
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-sm bg-graphite-750 py-0.5 pl-1.5 pr-0.5 font-mono text-xs text-bone-200">
          #{t}
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))} aria-label={`Rimuovi #${t}`}
            className="rounded-sm p-0.5 text-graphite-400 hover:text-err"><X size={11} /></button>
        </span>
      ))}
      <input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} onBlur={add} aria-label="Aggiungi hashtag"
        placeholder={tags.length ? '' : 'aggiungi hashtag…'} className="min-w-[90px] flex-1 bg-transparent py-0.5 font-mono text-xs text-bone-100 outline-none placeholder:text-graphite-500" />
      {limit && <span className={cx('timecode ml-auto text-[10px]', tags.length > limit[1] ? 'text-warn' : 'text-graphite-500')}>{tags.length} · consigliati {limit[0]}–{limit[1]}</span>}
    </div>
  )
}

export function SocialMetadataEditor({ item, onSaved }: { item: ReviewItem; onSaved: (i: ReviewItem) => void }) {
  const initial = item.content ? (item.content.metadata ?? fromLegacy(item.content)) : null
  const [m, setM] = useState<SocialMetadata | null>(initial)
  const [lang, setLang] = useState<'it' | 'en'>(item.content?.language ?? 'it')
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState<MetadataPart | 'all' | 'save' | null>(null)
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setM(item.content ? (item.content.metadata ?? fromLegacy(item.content)) : null)
    setLang(item.content?.language ?? 'it'); setWarnings([]); setDirty(false)
  }, [item.clip.id, item.content])

  const edit = (fn: (x: SocialMetadata) => SocialMetadata) => { if (m) { setM(fn(structuredClone(m))); setDirty(true) } }

  const gen = async (parts?: MetadataPart[]) => {
    setBusy(parts?.length === 1 ? parts[0] : 'all')
    try {
      const r = await api.generateContent(item.clip.id, true, lang, parts, parts ? m : null)
      setM(r.content.metadata ?? fromLegacy(r.content)); setWarnings(r.warnings); setDirty(true)
      toast.info(parts ? 'Parte rigenerata: rivedi e salva' : 'Nuova bozza pronta: rivedila e salva')
    } catch (e) { toast.error(e) } finally { setBusy(null) }
  }
  const save = async () => {
    if (!m) return
    setBusy('save')
    try {
      const yt = m.platforms.youtube_shorts
      const body: ClipContent = {
        language: lang, title: m.titles.selected, hook: m.platforms.tiktok.caption.slice(0, 150),
        caption: m.platforms.instagram.caption, description: yt.description, hashtags: m.platforms.instagram.hashtags,
        cta: '', metadata: { ...m, language: lang },
      }
      const r = await api.saveContent(item.clip.id, body)
      if (r.approval_revoked) toast.info('Testi modificati: la clip torna in revisione e va riapprovata')
      else toast.success('Testi salvati')
      setDirty(false); onSaved(r)
    } catch (e) { toast.error(e) } finally { setBusy(null) }
  }

  const working = busy && busy !== 'save' && (
    <p className="flex items-center gap-2 text-xs text-graphite-400" role="status">
      <Spinner className="h-3.5 w-3.5" />
      {busy === 'all' ? 'L\'AI locale guarda la clip, capisce cosa succede e scrive i testi (fino a ~1 min)…'
        : 'Rigenero solo questa parte (~20 s)…'}
    </p>
  )

  if (!m) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-graphite-400">Nessun testo ancora. L'AI analizza parlato, contesto e fotogrammi e propone titoli, caption e hashtag per ogni piattaforma.</p>
        <button className="btn-primary" onClick={() => gen()} disabled={!!busy}><Sparkles size={15} /> Genera titoli, caption e hashtag</button>
        {working}
      </div>
    )
  }

  const a = m.content_analysis
  const s = m.titles
  return (
    <div className="space-y-5">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <select className="input w-auto py-1 text-xs" aria-label="Lingua dei testi" value={lang} onChange={(e) => setLang(e.target.value as 'it' | 'en')}>
          <option value="it">Italiano</option><option value="en">English</option>
        </select>
        <button className="btn-cyan px-2.5 py-1.5 text-xs" onClick={() => gen()} disabled={!!busy}><RefreshCw size={13} /> Rigenera tutto</button>
        <Badge tone={m.generated_by.startsWith('ollama') ? 'violet' : 'zinc'}>{m.generated_by.startsWith('ollama') ? 'AI locale' : m.generated_by.includes('edited') ? 'modificato' : 'prudente (senza AI)'}</Badge>
        {m.visual_used && <Badge tone="zinc"><Eye size={10} /> fotogrammi</Badge>}
        {dirty && <span className="ml-auto font-mono text-[10px] uppercase tracking-wider text-warn">● non salvato</span>}
      </div>
      {working}
      {warnings.length > 0 && (
        <ul className="space-y-1 border-l-2 border-warn bg-warn-dim/30 py-2 pl-3 pr-2 text-xs text-bone-300">
          {warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}

      {/* what the AI understood */}
      <section className="border-y border-graphite-800">
        <button className="flex w-full items-center gap-2 py-2.5 text-left" onClick={() => setShowAnalysis(!showAnalysis)} aria-expanded={showAnalysis}>
          <span className="eyebrow text-bone-400">Cosa ha capito l'AI</span>
          {a.insufficient_context && <Badge tone="amber">contesto insufficiente</Badge>}
          <span className="ml-auto flex items-center gap-2">
            <span className="relative h-1 w-16 overflow-hidden rounded-full bg-graphite-700" title={`Affidabilità ${Math.round(a.confidence * 100)}%`}>
              <span className={cx('absolute inset-y-0 left-0', a.confidence >= 0.6 ? 'bg-ok' : a.confidence >= 0.4 ? 'bg-warn' : 'bg-err')} style={{ width: `${a.confidence * 100}%` }} />
            </span>
            <span className="timecode text-[10px] text-graphite-400">{Math.round(a.confidence * 100)}%</span>
            <ChevronDown size={14} className={cx('text-graphite-400 transition-transform', showAnalysis && 'rotate-180')} />
          </span>
        </button>
        <p className="-mt-1 pb-2.5 text-sm text-bone-200">{a.event || 'Nessuna analisi: testi costruiti dai dati disponibili.'}</p>
        {showAnalysis && (
          <dl className="grid gap-x-6 gap-y-2 pb-3 text-xs sm:grid-cols-2">
            {[['Contesto', a.context], ['Momento chiave', a.key_moment], ['Perché interessa', a.why_interesting], ['Chi parla', a.speaker],
              ['Tono', TONE_LABEL[a.tone] ?? a.tone], ['Emozione', a.emotion]].filter(([, v]) => v).map(([k, v]) => (
              <div key={k}><dt className="eyebrow">{k}</dt><dd className="mt-0.5 text-bone-300">{v}</dd></div>
            ))}
            {a.evidence.length > 0 && (
              <div className="sm:col-span-2"><dt className="eyebrow">Prove (frasi dette nella clip)</dt>
                <dd className="mt-0.5 space-y-0.5 text-bone-300">{a.evidence.map((e) => <div key={e}>“{e}”</div>)}</dd></div>
            )}
          </dl>
        )}
      </section>

      {/* titles */}
      <section aria-labelledby="titles-h" className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 id="titles-h" className="eyebrow flex items-center gap-1.5 text-bone-400"><Type size={12} /> Titolo · {s.options.length} alternative</h4>
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => gen(['titles'])} disabled={!!busy}>
            {busy === 'titles' ? <Spinner className="h-3 w-3" /> : <RefreshCw size={12} />} Rigenera titoli
          </button>
        </div>
        <ul className="space-y-1.5" role="radiogroup" aria-label="Titolo scelto">
          {s.options.map((t, i) => {
            const sel = t === s.selected
            return (
              <li key={i} className={cx('flex items-center gap-2 rounded-md border px-2 py-1.5 transition-colors', sel ? 'border-tally-500/70 bg-graphite-850' : 'border-graphite-700')}>
                <button type="button" role="radio" aria-checked={sel} aria-label={`Usa il titolo ${i + 1}`}
                  onClick={() => edit((x) => { x.titles.selected = x.titles.options[i]; return x })}
                  className={cx('grid h-4 w-4 shrink-0 place-items-center rounded-full border', sel ? 'border-tally-500 bg-tally-500 text-[#160800]' : 'border-graphite-500')}>
                  {sel && <Check size={10} strokeWidth={3} />}
                </button>
                <input className="min-w-0 flex-1 bg-transparent text-sm text-bone-100 outline-none" value={t} maxLength={100} aria-label={`Titolo ${i + 1}`}
                  onChange={(e) => edit((x) => { const was = x.titles.options[i] === x.titles.selected; x.titles.options[i] = e.target.value; if (was) x.titles.selected = e.target.value; return x })} />
                <Count value={t} max={100} />
                <CopyBtn text={t} what="Titolo" />
              </li>
            )
          })}
        </ul>
      </section>

      {/* per platform */}
      <section aria-label="Testi per piattaforma">
        <div className="mb-2 flex flex-wrap items-center justify-end gap-2">
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => gen(['captions'])} disabled={!!busy}>
            {busy === 'captions' ? <Spinner className="h-3 w-3" /> : <RefreshCw size={12} />} Rigenera caption
          </button>
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => gen(['hashtags'])} disabled={!!busy}>
            {busy === 'hashtags' ? <Spinner className="h-3 w-3" /> : <Hash size={12} />} Rigenera hashtag
          </button>
        </div>
        <Tabs defaultValue="instagram">
          <TabsList aria-label="Piattaforma" className="mb-4 overflow-x-auto">
            {PLATFORM_TABS.map((p) => <TabsTrigger key={p.id} value={p.id}>{p.label}</TabsTrigger>)}
          </TabsList>
          {(['instagram', 'tiktok'] as const).map((pid) => {
            const post = m.platforms[pid]
            const full = `${post.caption}\n\n${post.hashtags.map((t) => `#${t}`).join(' ')}`.trim()
            return (
              <TabsContent key={pid} value={pid} className="space-y-3">
                <Field label={pid === 'tiktok' ? 'Caption TikTok · diretta, hook iniziale' : 'Caption Instagram · contesto e momento chiave'}
                  hint={<span className="flex items-center justify-between"><Count value={post.caption} max={2200} />
                    <span className="flex gap-1"><button type="button" className="link text-[11px]" onClick={() => copy(post.caption, 'Testo')}>copia testo</button>
                      <span className="text-graphite-600">·</span>
                      <button type="button" className="link text-[11px]" onClick={() => copy(full, 'Testo con hashtag')}>copia con hashtag</button></span></span>}>
                  <textarea className="input min-h-[96px]" value={post.caption} onChange={(e) => edit((x) => { x.platforms[pid].caption = e.target.value; return x })} />
                </Field>
                <Field label="Hashtag"><TagEditor tags={post.hashtags} limit={[3, 5]} onChange={(t) => edit((x) => { x.platforms[pid].hashtags = t; return x })} /></Field>
              </TabsContent>
            )
          })}
          <TabsContent value="youtube_shorts" className="space-y-3">
            <Field label="Titolo YouTube" hint={<span className="flex items-center justify-between"><Count value={m.platforms.youtube_shorts.title} max={100} /><CopyBtn text={m.platforms.youtube_shorts.title} what="Titolo YouTube" /></span>}>
              <input className="input" maxLength={100} value={m.platforms.youtube_shorts.title} onChange={(e) => edit((x) => { x.platforms.youtube_shorts.title = e.target.value; return x })} />
            </Field>
            <Field label="Descrizione" hint={<span className="flex items-center justify-between"><Count value={m.platforms.youtube_shorts.description} max={5000} /><CopyBtn text={m.platforms.youtube_shorts.description} what="Descrizione" /></span>}>
              <textarea className="input min-h-[80px]" value={m.platforms.youtube_shorts.description} onChange={(e) => edit((x) => { x.platforms.youtube_shorts.description = e.target.value; return x })} />
            </Field>
            <Field label="Hashtag" hint="#Shorts viene aggiunto automaticamente all'export.">
              <TagEditor tags={m.platforms.youtube_shorts.hashtags} limit={[2, 4]} onChange={(t) => edit((x) => { x.platforms.youtube_shorts.hashtags = t; return x })} />
            </Field>
          </TabsContent>
        </Tabs>
      </section>

      {item.attribution && <p className="text-xs text-graphite-400">Attribuzione obbligatoria, aggiunta automaticamente all'export: <b className="text-bone-200">{item.attribution}</b></p>}
      <button className="btn-primary" onClick={save} disabled={!!busy || !dirty}><Save size={15} /> Salva testi</button>
    </div>
  )
}
