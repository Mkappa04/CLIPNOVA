import { ExternalLink, RefreshCw, Search, ShieldCheck, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Segmented, Toggle } from '../components/EditorControls'
import { Badge, EmptyState, Field, PageHeader, Spinner } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatDuration, timeAgo } from '../services/format'
import { toast } from '../stores/toastStore'
import type { DiscoveryCreator, DiscoveryItem, DiscoveryResult } from '../types'

const fmtN = (n: number) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n)

async function addToCrm(c: { name: string; platform: string; channel_id: string | null; url: string | null; languages?: string[]; score?: number; total_views?: number; items?: number }) {
  try {
    await api.addCreator({ name: c.name, source: 'discovery', language: c.languages?.[0] ?? '', score: c.score ?? 0,
      channels: [{ platform: c.platform, channel_id: c.channel_id, url: c.url }],
      metrics: { total_views: c.total_views, items_in_search: c.items } })
    toast.success(`${c.name} aggiunto ai Creator`)
  } catch (e) { toast.error(e) }
}

function ItemCard({ it }: { it: DiscoveryItem }) {
  return (
    <li className="card flex gap-3 overflow-hidden p-2">
      {it.thumbnail ? <img src={it.thumbnail} alt="" loading="lazy" className="h-20 w-36 shrink-0 rounded object-cover" referrerPolicy="no-referrer" />
        : <div className="h-20 w-36 shrink-0 rounded bg-ink-850" />}
      <div className="min-w-0 flex-1 space-y-1 text-sm">
        <div className="flex items-start gap-2">
          <a href={it.url} target="_blank" rel="noreferrer" className="line-clamp-2 flex-1 font-medium text-zinc-100 hover:text-pulse-300">{it.title}</a>
          <span className="font-display text-lg font-bold text-white">{it.score.toFixed(0)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-zinc-400">
          <span>{it.creator}</span>
          <Badge tone={it.platform === 'youtube' ? 'red' : 'violet'}>{it.platform === 'youtube' ? (it.is_short ? 'Short' : 'YouTube') : `Twitch ${it.kind ?? ''}`}</Badge>
          {it.license === 'creativeCommon' && <Badge tone="green"><ShieldCheck size={11} /> CC BY</Badge>}
          {it.language && <Badge>{it.language}</Badge>}
          <span>{fmtN(it.views)} views{it.likes != null ? ` · ${fmtN(it.likes)} like` : ''}</span>
          {it.duration_s > 0 && <span>{formatDuration(it.duration_s)}</span>}
          {it.published_at && <span>{timeAgo(it.published_at)}</span>}
        </div>
        <div className="text-[11px] text-zinc-500">{it.score_reason}</div>
        {it.attribution_hint && <div className="text-[11px] text-emerald-300">{it.attribution_hint}</div>}
        <div className="flex gap-2 pt-0.5">
          <a className="btn-ghost px-2 py-0.5 text-xs" href={it.url} target="_blank" rel="noreferrer"><ExternalLink size={11} /> Apri</a>
          <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => addToCrm({ name: it.creator, platform: it.platform, channel_id: it.channel_id, url: it.channel_url, languages: it.language ? [it.language.slice(0, 2)] : [] })}>
            <UserPlus size={11} /> Creator
          </button>
        </div>
      </div>
    </li>
  )
}

export function Discovery() {
  const { data: status, reload } = useApi(() => api.discoveryStatus())
  const [platform, setPlatform] = useState<'youtube' | 'twitch'>('youtube')
  const [query, setQuery] = useState('GTA 6')
  const [language, setLanguage] = useState<'' | 'it' | 'en'>('it')
  const [days, setDays] = useState(7)
  const [shorts, setShorts] = useState(true)
  const [cc, setCc] = useState(false)
  const [kind, setKind] = useState<'clips' | 'vods'>('clips')
  const [res, setRes] = useState<DiscoveryResult | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async (refresh = false) => {
    setBusy(true)
    try {
      const r = await api.discover({ platform, query, language: language || null, days, shorts_only: shorts, cc_only: cc, twitch_kind: kind, refresh })
      setRes(r); reload()
      if (!r.enabled) toast.info(r.message ?? 'API non configurata')
    } catch (e) { toast.error(e) } finally { setBusy(false) }
  }
  const configured = status ? (platform === 'youtube' ? status.youtube.configured : status.twitch.configured) : false

  return (
    <>
      <PageHeader title="Discovery" subtitle="Cosa funziona su GTA 6: ricerca tramite API ufficiali gratuite (YouTube, Twitch)" />
      {status && <p className="card mb-5 p-3 text-xs text-zinc-400"><ShieldCheck size={13} className="mr-1 inline text-emerald-400" />{status.policy}</p>}
      <div className="card mb-5 space-y-3 p-4">
        <div className="flex flex-wrap items-start gap-3">
          <Field label="Piattaforma"><Segmented value={platform} onChange={setPlatform} options={[{ value: 'youtube', label: 'YouTube' }, { value: 'twitch', label: 'Twitch' }]} /></Field>
          {platform === 'youtube' ? <Field label="Ricerca"><input className="input w-56 py-1.5" value={query} onChange={(e) => setQuery(e.target.value)} /></Field>
            : <Field label="Contenuti"><Segmented value={kind} onChange={setKind} options={[{ value: 'clips', label: 'Clip più viste' }, { value: 'vods', label: 'VOD' }]} /></Field>}
          <Field label="Lingua"><Segmented value={language} onChange={setLanguage} options={[{ value: 'it', label: 'IT' }, { value: 'en', label: 'EN' }, { value: '', label: 'Tutte' }]} /></Field>
          <Field label="Periodo"><Segmented value={days} onChange={setDays} options={[{ value: 1, label: '24h' }, { value: 7, label: '7g' }, { value: 30, label: '30g' }, { value: 90, label: '90g' }]} /></Field>
        </div>
        {platform === 'youtube' && <div className="flex flex-wrap gap-4"><Toggle label="Solo video brevi (Shorts)" checked={shorts} onChange={setShorts} /><Toggle label="Solo licenza Creative Commons (CC BY)" checked={cc} onChange={setCc} /></div>}
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-primary" onClick={() => run(false)} disabled={busy || !configured}>{busy ? <Spinner /> : <Search size={15} />} Cerca</button>
          {res?.cached && <button className="btn-ghost" onClick={() => run(true)} disabled={busy}><RefreshCw size={14} /> Aggiorna (usa quota)</button>}
          {status && platform === 'youtube' && <span className="text-xs text-zinc-500">Quota YouTube oggi: {status.youtube.quota.units}/{status.youtube.quota.limit} unità (una ricerca ≈ 101)</span>}
          {res?.cached && <Badge tone="zinc">dalla cache locale</Badge>}
        </div>
        {status && !configured && <p className="text-sm text-amber-300">API non configurata: inserisci le chiavi gratuite in <Link to="/settings" className="underline">Settings → Scoperta contenuti</Link>.</p>}
      </div>

      {res?.enabled && res.results.length === 0 && <EmptyState icon={<Search size={26} />} title="Nessun risultato" />}
      {res?.enabled && res.results.length > 0 && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <ul className="space-y-2">{res.results.map((it) => <ItemCard key={`${it.platform}-${it.id}`} it={it} />)}</ul>
          <section className="card h-fit p-4">
            <h2 className="mb-3 font-display font-semibold text-white">Creator più adatti</h2>
            <ol className="space-y-2">
              {res.creators.slice(0, 15).map((c: DiscoveryCreator, i) => (
                <li key={`${c.platform}-${c.channel_id ?? c.name}`} className="flex items-center gap-2 text-sm">
                  <span className="w-5 text-right font-mono text-xs text-zinc-500">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <a href={c.url ?? '#'} target="_blank" rel="noreferrer" className="truncate text-zinc-100 hover:text-pulse-300">{c.name}</a>
                    <div className="text-[11px] text-zinc-500">{c.score_reason}{c.languages.length ? ` · ${c.languages.join('/')}` : ''}{c.cc_by ? ` · ${c.cc_by} CC BY` : ''}</div>
                  </div>
                  <button className="btn-ghost px-1.5 py-1" onClick={() => addToCrm(c)} aria-label={`Aggiungi ${c.name}`}><UserPlus size={13} /></button>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </>
  )
}
