import { useState } from 'react'
import { BarList, ColumnChart } from '../components/Charts'
import { ErrorBox, PageHeader, Spinner } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { CATEGORY_BY_ID, formatBytes } from '../services/format'
import { Segmented } from '../components/EditorControls'

interface AnalyticsData {
  days: number
  daily: { day: string; videos: number; renders: number; approved: number }[]
  funnel: { stage: string; count: number }[]
  rejected: number
  categories: { category: string; count: number; avg_score: number; approved: number }[]
  score_hist: { bucket: string; count: number }[]
  performance: {
    analysis_s_per_video_min: number | null; analysis_stages_s_per_min: Record<string, number>; analyses: number
    transcription_devices: Record<string, number>; render_speed_x: number | null; renders: number; encoders: Record<string, number>
  }
  automation: { by_status: Record<string, number>; avg_minutes_to_review: number | null }
  library: { videos: number; minutes: number; by_game: Record<string, number> }
  storage: { area: string; bytes: number }[]
  kpi: { clips: number; approval_rate: number | null; renders_in_period: number; videos_in_period: number }
}

const STAGES: Record<string, string> = { detected: 'Rilevate', rendered: 'Renderizzate', approved: 'Approvate', exported: 'Esportate', published: 'Pubblicate' }
const ANALYSIS_STAGES: Record<string, string> = { prepare: 'Proxy + audio', audio: 'Audio', scenes: 'Scene', motion: 'Movimento', transcription: 'Trascrizione' }
const AREAS: Record<string, string> = { videos: 'Video (copiati/caricati)', cache: 'Cache analisi', renders: 'Render', exports: 'Export', previews: 'Anteprime', models: 'Modelli AI', logs: 'Log', database: 'Database' }

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-zinc-400">{label}</div>
      <div className="mt-1 font-display text-3xl font-bold text-white">{value}</div>
      {sub && <div className="mt-1 text-xs text-zinc-500">{sub}</div>}
    </div>
  )
}

function Panel({ title, children, note }: { title: string; children: React.ReactNode; note?: string }) {
  return (
    <section className="card p-4">
      <h2 className="font-display font-semibold text-white">{title}</h2>
      {note && <p className="mb-3 text-xs text-zinc-500">{note}</p>}
      <div className={note ? '' : 'mt-3'}>{children}</div>
    </section>
  )
}

export function Analytics() {
  const [days, setDays] = useState(30)
  const { data, error, reload } = useApi(() => fetch(`/api/analytics?days=${days}`).then((r) => r.json()) as Promise<AnalyticsData>, [days], 30000)
  const p = data?.performance
  return (
    <>
      <PageHeader title="Analytics" subtitle="Produzione, qualità delle clip e prestazioni del sistema (dati locali)"
        actions={<Segmented value={days} onChange={setDays} options={[{ value: 7, label: '7 giorni' }, { value: 30, label: '30 giorni' }, { value: 90, label: '90 giorni' }]} />} />
      {error && <ErrorBox error={error} onRetry={reload} />}
      {!data && !error && <Spinner />}
      {data && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Video nel periodo" value={String(data.kpi.videos_in_period)} sub={`${data.library.videos} in libreria · ${Math.round(data.library.minutes)} min`} />
            <Tile label="Render nel periodo" value={String(data.kpi.renders_in_period)} sub={p?.render_speed_x ? `velocità media ${p.render_speed_x}× tempo reale` : undefined} />
            <Tile label="Clip rilevate" value={String(data.kpi.clips)} sub={`${data.rejected} rifiutate`} />
            <Tile label="Tasso di approvazione" value={data.kpi.approval_rate == null ? '—' : `${Math.round(data.kpi.approval_rate * 100)}%`} sub="approvate / renderizzate" />
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Render completati al giorno">
              <ColumnChart label="Render" data={data.daily.map((d) => ({ key: d.day, label: d.day.slice(5).split('-').reverse().join('/'), value: d.renders }))} />
            </Panel>
            <Panel title="Video importati al giorno">
              <ColumnChart label="Video" color="#22d3ee" data={data.daily.map((d) => ({ key: d.day, label: d.day.slice(5).split('-').reverse().join('/'), value: d.videos }))} />
            </Panel>
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel title="Workflow" note="Quante clip arrivano a ogni fase (da sempre)">
              <BarList max={data.funnel[0]?.count} rows={data.funnel.map((f) => ({ key: f.stage, label: STAGES[f.stage] ?? f.stage, value: f.count }))} />
            </Panel>
            <Panel title="Categorie" note="Numero di clip e score medio (euristica)">
              <BarList rows={data.categories.map((c) => ({ key: c.category, label: CATEGORY_BY_ID[c.category]?.label ?? c.category,
                value: c.count, color: CATEGORY_BY_ID[c.category]?.color, detail: `score ${c.avg_score}` }))} />
              {!data.categories.length && <p className="text-sm text-zinc-500">Nessuna clip ancora.</p>}
            </Panel>
            <Panel title="Distribuzione degli score" note="Clip rilevate automaticamente">
              <ColumnChart label="Clip" height={150} data={data.score_hist.map((h) => ({ key: h.bucket, label: h.bucket.split('-')[0], value: h.count }))} />
            </Panel>
          </div>

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel title="Prestazioni analisi" note={p?.analysis_s_per_video_min != null ? `${p.analysis_s_per_video_min} s di elaborazione per minuto di video (${p.analyses} analisi)` : 'Nessuna analisi completata'}>
              <BarList format={(v) => `${v.toFixed(2)} s/min`} rows={Object.entries(p?.analysis_stages_s_per_min ?? {}).map(([k, v]) => ({ key: k, label: ANALYSIS_STAGES[k] ?? k, value: v }))} />
              {p && Object.keys(p.transcription_devices).length > 0 && (
                <p className="mt-3 text-xs text-zinc-400">Trascrizione: {Object.entries(p.transcription_devices).map(([d, n]) => `${d.toUpperCase()} ${n}`).join(' · ')}
                  {p.transcription_devices.cpu ? ' — su CPU è circa 100 volte più lenta: vedi Settings per lo stato della GPU.' : ''}</p>
              )}
            </Panel>
            <Panel title="Spazio su disco" note="Cartella data/ (link e hard link contati una volta)">
              <BarList format={(v) => formatBytes(v)} rows={data.storage.filter((s) => s.bytes > 0).map((s) => ({ key: s.area, label: AREAS[s.area] ?? s.area, value: s.bytes, color: '#22d3ee' }))} />
            </Panel>
            <Panel title="Import automatico" note={data.automation.avg_minutes_to_review != null ? `In media ${data.automation.avg_minutes_to_review} min dal file al render in revisione` : 'Nessun file elaborato'}>
              <BarList rows={Object.entries(data.automation.by_status).map(([k, v]) => ({ key: k, label: k, value: v }))} />
              {!Object.keys(data.automation.by_status).length && <p className="text-sm text-zinc-500">Nessuna cartella monitorata attiva.</p>}
            </Panel>
          </div>
        </div>
      )}
    </>
  )
}
