import { ChevronDown, Cpu, Download, Heart, Plus, ScanSearch, Sparkles, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ClipInspector } from '../components/ClipInspector'
import { JobList } from '../components/JobList'
import { ScoringPanel } from '../components/ScoringPanel'
import { CategoryBadge, CategoryLegend, TimelineChart } from '../components/TimelineChart'
import { Badge, EmptyState, ErrorBox, Field, PageHeader, Spinner, cx } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { CATEGORIES, formatDuration, formatTime } from '../services/format'
import { toast } from '../stores/toastStore'
import type { AnalysisResponse, Clip, ClipCategory, ScoringConfig } from '../types'

const STEP_LABELS: Record<string, string> = {
  prepare: 'Proxy+audio', audio: 'Audio', scenes: 'Scene', motion: 'Movimento', transcription: 'Trascrizione', semantic: 'AI locale',
}

export function ClipDetection() {
  const [params, setParams] = useSearchParams()
  const { data: videos } = useApi(() => api.videos(), [], 5000)
  const candidates = useMemo(() => (videos ?? []).filter((v) => ['ready', 'analyzed', 'analyzing'].includes(v.status)), [videos])
  const videoId = params.get('video') ?? candidates.find((v) => v.status === 'analyzed')?.id ?? candidates[0]?.id ?? null
  const video = candidates.find((v) => v.id === videoId) ?? videos?.find((v) => v.id === videoId)

  const { data: jobs, reload: reloadJobs } = useApi(
    () => (videoId ? api.jobs({ video_id: videoId, limit: 5 }) : Promise.resolve([])), [videoId], 1500)
  const activeJob = jobs?.find((j) => j.type === 'video.analyze' && (j.status === 'queued' || j.status === 'running'))
  const lastJob = jobs?.find((j) => j.type === 'video.analyze')

  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [loadError, setLoadError] = useState<Error | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sort, setSort] = useState<'score' | 'start'>('score')
  const [catFilter, setCatFilter] = useState<string>('')
  const [hideRejected, setHideRejected] = useState(true)
  const [language, setLanguage] = useState<'auto' | 'it' | 'en'>('auto')
  const [transcribe, setTranscribe] = useState(true)
  const [force, setForce] = useState(false)
  const [rescoring, setRescoring] = useState(false)
  const [showScoring, setShowScoring] = useState(false)
  const [manual, setManual] = useState({ start: 0, end: 20, category: 'gameplay_highlight' as ClipCategory })
  const lastJobState = useRef<string | undefined>(undefined)
  const { data: prefs, reload: reloadPrefs } = useApi(() => api.preferences(), [])
  const [reranking, setReranking] = useState(false)

  const rerank = async () => {
    if (!videoId) return
    setReranking(true)
    try {
      const c = await api.rerank(videoId)
      setClips(c); setAnalysis(await api.analysis(videoId)); reloadPrefs()
      toast.success('Clip riordinate secondo le tue scelte')
    } catch (e) { toast.error(e) } finally { setReranking(false) }
  }

  const loadAll = async (id: string) => {
    try {
      const [a, c] = await Promise.all([api.analysis(id), api.clips({ video_id: id, sort: 'start' })])
      setAnalysis(a); setClips(c); setLoadError(null)
    } catch (e) { setLoadError(e as Error) }
  }

  useEffect(() => { setSelectedId(null); setAnalysis(null); setClips([]); if (videoId) void loadAll(videoId) }, [videoId])

  // Reload results when an analysis job finishes
  useEffect(() => {
    const state = lastJob ? `${lastJob.id}:${lastJob.status}` : undefined
    if (lastJobState.current && state !== lastJobState.current && lastJob && !['queued', 'running'].includes(lastJob.status) && videoId) {
      void loadAll(videoId)
      if (lastJob.status === 'completed') toast.success(lastJob.message || 'Analisi completata')
      if (lastJob.status === 'failed') toast.error(lastJob.error ?? 'Analisi fallita')
    }
    lastJobState.current = state
  }, [lastJob, videoId])

  const start = async () => {
    if (!videoId) return
    try {
      await api.analyze(videoId, { language, transcribe, force })
      toast.info('Analisi avviata')
      reloadJobs()
    } catch (e) { toast.error(e) }
  }

  const rescore = async (cfg: ScoringConfig) => {
    if (!videoId) return
    setRescoring(true)
    try {
      const c = await api.rescore(videoId, cfg)
      setClips(c)
      setAnalysis(await api.analysis(videoId))
      toast.success(`${c.length} clip`)
    } catch (e) { toast.error(e) } finally { setRescoring(false) }
  }

  const addManual = async () => {
    if (!videoId) return
    try {
      const c = await api.createClip(videoId, manual)
      setClips((cs) => [...cs, c]); setSelectedId(c.id); toast.success('Clip manuale creata')
    } catch (e) { toast.error(e) }
  }

  const shown = useMemo(() => {
    const list = clips.filter((c) => (!catFilter || c.category === catFilter) && (!hideRejected || !['rejected', 'archived'].includes(c.status)))
    return [...list].sort((a, b) => sort === 'score' ? b.score - a.score : a.start - b.start)
  }, [clips, catFilter, hideRejected, sort])
  const selected = clips.find((c) => c.id === selectedId) ?? null
  const a = analysis?.analysis
  const presentCats = CATEGORIES.map((c) => c.id).filter((id) => clips.some((c) => c.category === id))

  if (videos && candidates.length === 0) {
    return (
      <>
        <PageHeader title="Clip Detection" subtitle="Analisi AI locale e individuazione automatica dei momenti migliori" />
        <EmptyState icon={<ScanSearch size={28} />} title="Nessun video pronto"
          text="Importa un video nella libreria: quando i metadati sono pronti potrai analizzarlo qui."
          action={<Link to="/library" className="btn-primary">Vai alla libreria</Link>} />
      </>
    )
  }

  return (
    <>
      <PageHeader title="Clip Detection" subtitle="Analisi locale: scene, audio, movimento e trascrizione (faster-whisper) → clip candidate con score spiegabile"
        actions={
          <select className="input w-auto max-w-xs" value={videoId ?? ''} onChange={(e) => setParams({ video: e.target.value })}>
            {candidates.map((v) => <option key={v.id} value={v.id}>{v.title} · {formatDuration(v.duration)}{v.status === 'analyzed' ? ' ✓' : ''}</option>)}
          </select>
        } />

      {!videos && <Spinner />}
      {loadError && <ErrorBox error={loadError} onRetry={() => videoId && loadAll(videoId)} />}

      {video && (
        <div className="space-y-5">
          {/* analysis control */}
          <div className="card flex flex-wrap items-end gap-4 p-4">
            <div className="min-w-[200px] flex-1">
              <div className="font-display text-lg font-semibold text-white">{video.title}</div>
              <div className="text-xs text-zinc-400">{video.game} · {formatDuration(video.duration)} · {video.width}×{video.height}{video.has_audio ? '' : ' · senza audio'}</div>
            </div>
            <Field label="Lingua parlato">
              <select className="input w-36" value={language} onChange={(e) => setLanguage(e.target.value as typeof language)}>
                <option value="auto">Auto-detect</option><option value="it">Italiano</option><option value="en">English</option>
              </select>
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm text-zinc-300">
              <input type="checkbox" className="accent-nova-500" checked={transcribe} onChange={(e) => setTranscribe(e.target.checked)} /> Trascrizione
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm text-zinc-300" title="Ignora la cache (proxy, audio, trascrizione)">
              <input type="checkbox" className="accent-nova-500" checked={force} onChange={(e) => setForce(e.target.checked)} /> Rianalizza da zero
            </label>
            <button className="btn-primary" onClick={start} disabled={!!activeJob || video.status === 'analyzing'}>
              <Sparkles size={16} /> {a ? 'Rianalizza' : 'Analizza video'}
            </button>
          </div>

          {(activeJob || (lastJob && lastJob.status === 'failed')) && (
            <div className="card px-4"><JobList jobs={[activeJob ?? lastJob!]} onChange={reloadJobs} /></div>
          )}

          {a?.status === 'failed' && !activeJob && <ErrorBox error={new Error(`Analisi fallita: ${a.error}`)} />}

          {a?.status === 'completed' && (
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone="violet"><Cpu size={11} /> Whisper {a.whisper_model || '—'} · {a.transcription_device || 'off'}</Badge>
              {a.language && <Badge tone="cyan">lingua {a.language}{a.stats.transcript ? ` (${Math.round(a.stats.transcript.language_probability * 100)}%)` : ''}</Badge>}
              <Badge>{a.stats.scenes ?? a.scenes.length} cambi scena</Badge>
              <Badge>{a.stats.audio?.peaks ?? 0} picchi audio</Badge>
              {a.stats.transcript && <Badge>{a.stats.transcript.words} parole</Badge>}
              {!!a.stats.transcript?.filtered_hallucinations && <Badge tone="amber">{a.stats.transcript.filtered_hallucinations} allucinazioni filtrate</Badge>}
              <Badge>decoder {a.stats.decoder}</Badge>
              {a.stats.timings && <Badge>⏱ {Object.entries(a.stats.timings).map(([k, v]) => `${STEP_LABELS[k] ?? k} ${v}s`).join(' · ')}</Badge>}
              {prefs && (
                <span className="flex items-center gap-2">
                  <Badge tone={prefs.active ? 'green' : 'zinc'}><Heart size={11} /> {prefs.active
                    ? `I tuoi gusti: ${prefs.positive} scelte, ${prefs.negative} scartate`
                    : `I tuoi gusti: servono almeno ${prefs.min_positive} clip approvate/esportate`}</Badge>
                  {prefs.active && <button className="btn-cyan px-2 py-1 text-xs" disabled={reranking} onClick={rerank}
                    title="L'LLM locale riconfronta i candidati usando le tue clip approvate e rifiutate come esempi (~30-60 s)">
                    {reranking ? <Spinner /> : <Heart size={12} />} Riordina con i miei gusti</button>}
                </span>
              )}
              {a.language && (
                <span className="ml-auto flex gap-2">
                  <a className="btn-ghost px-2 py-1 text-xs" href={api.transcriptUrl(video.id, 'srt')}><Download size={13} /> SRT</a>
                  <a className="btn-ghost px-2 py-1 text-xs" href={api.transcriptUrl(video.id, 'txt')} target="_blank" rel="noreferrer"><Download size={13} /> Testo</a>
                </span>
              )}
            </div>
          )}

          {analysis?.timeline && video.duration && (
            <div className="card space-y-3 p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-display font-semibold text-white">Interesse stimato nel tempo</h2>
                <span className="text-xs text-zinc-500">Combinazione euristica dei segnali, non comprensione semantica. Clicca una clip per aprirla.</span>
              </div>
              <TimelineChart timeline={analysis.timeline} duration={video.duration} clips={clips.filter((c) => c.status !== 'rejected')}
                             selectedId={selectedId} onSelect={setSelectedId} />
              <CategoryLegend categories={presentCats} />
            </div>
          )}

          {!a && !activeJob && (
            <EmptyState icon={<Wand2 size={28} />} title="Video non ancora analizzato"
              text="L'analisi gira in locale: NVDEC + OpenCV + PySceneDetect per il video, faster-whisper su GPU per il parlato. La prima volta scarica il modello Whisper (~1,6 GB, una sola volta)." />
          )}

          {a?.status === 'completed' && (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
              <section className="lg:col-span-5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <h2 className="mr-auto font-display text-lg font-semibold text-white">Clip ({shown.length})</h2>
                  <select className="input w-auto py-1 text-xs" value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
                    <option value="">Tutte le categorie</option>
                    {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                  </select>
                  <select className="input w-auto py-1 text-xs" value={sort} onChange={(e) => setSort(e.target.value as 'score' | 'start')}>
                    <option value="score">Per score</option><option value="start">Per tempo</option>
                  </select>
                  <label className="flex items-center gap-1 text-xs text-zinc-400">
                    <input type="checkbox" className="accent-nova-500" checked={hideRejected} onChange={(e) => setHideRejected(e.target.checked)} /> nascondi scartate
                  </label>
                </div>
                {shown.length === 0 && <p className="card p-6 text-center text-sm text-zinc-400">Nessuna clip. Prova ad abbassare lo score minimo nelle impostazioni di scoring.</p>}
                <ul className="space-y-2">
                  {shown.map((c) => (
                    <li key={c.id}>
                      <button onClick={() => setSelectedId(c.id)}
                        className={cx('card w-full p-3 text-left transition hover:border-nova-500/60',
                          c.id === selectedId && 'border-nova-500 shadow-glow', ['rejected', 'archived'].includes(c.status) && 'opacity-50')}>
                        <div className="flex items-center gap-2">
                          <CategoryBadge category={c.category} />
                          {c.status !== 'detected' && <Badge tone={c.status === 'review' ? 'amber' : 'zinc'}>{c.status}</Badge>}
                          <span className="ml-auto font-display text-lg font-bold text-white">{c.score.toFixed(0)}</span>
                        </div>
                        <div className="mt-1.5 truncate text-sm text-zinc-100">{c.suggested_title}</div>
                        <div className="mt-1 flex justify-between font-mono text-xs text-zinc-500">
                          <span>{formatTime(c.start)} → {formatTime(c.end)}</span>
                          <span>{c.duration.toFixed(0)}s · conf {Math.round(c.confidence * 100)}%</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>

                <div className="card mt-4 p-4">
                  <h3 className="label">Aggiungi clip manuale</h3>
                  <div className="grid grid-cols-3 gap-2">
                    <input type="number" className="input" aria-label="inizio" value={manual.start} min={0} onChange={(e) => setManual({ ...manual, start: Number(e.target.value) })} />
                    <input type="number" className="input" aria-label="fine" value={manual.end} min={1} onChange={(e) => setManual({ ...manual, end: Number(e.target.value) })} />
                    <select className="input" value={manual.category} onChange={(e) => setManual({ ...manual, category: e.target.value as ClipCategory })}>
                      {CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                    </select>
                  </div>
                  <button className="btn-ghost mt-2" onClick={addManual}><Plus size={15} /> Aggiungi</button>
                </div>
              </section>

              <section className="lg:col-span-7">
                <div className="card p-4">
                  {selected ? (
                    <ClipInspector clip={selected}
                      onChanged={(c) => setClips((cs) => cs.map((x) => (x.id === c.id ? c : x)))}
                      onDeleted={() => { setClips((cs) => cs.filter((x) => x.id !== selected.id)); setSelectedId(null) }} />
                  ) : (
                    <p className="py-16 text-center text-sm text-zinc-400">Seleziona una clip dall'elenco o dalla timeline per vederne anteprima, motivazione e segnali.</p>
                  )}
                </div>

                <div className="card mt-4">
                  <button className="flex w-full items-center justify-between p-4 text-left" onClick={() => setShowScoring(!showScoring)}>
                    <span className="font-display font-semibold text-white">Scoring configurabile</span>
                    <ChevronDown size={18} className={cx('text-zinc-400 transition', showScoring && 'rotate-180')} />
                  </button>
                  {showScoring && <div className="border-t border-ink-700 p-4"><ScoringPanel initial={a.config} busy={rescoring} onApply={rescore} /></div>}
                </div>
              </section>
            </div>
          )}
        </div>
      )}
    </>
  )
}
