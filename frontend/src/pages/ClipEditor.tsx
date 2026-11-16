import {
  Captions, Clapperboard, Crop, Download, Film, Gauge, Music2, RefreshCw, Save, Settings2, Sparkles, Stamp, Trash2, Type, Wand2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { EditingPresetPicker, PlanPanel, PlanStrip, usePlanPreview } from '../components/EditingPanels'
import { LayoutPicker, PresetPicker, Section, Segmented, Slider, Toggle, WebcamSelector } from '../components/EditorControls'
import { JobList } from '../components/JobList'
import { CategoryBadge } from '../components/TimelineChart'
import { EmptyState, Field, PageHeader, Spinner, StatusBadge, cx } from '../components/ui'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes, formatTime } from '../services/format'
import { toast } from '../stores/toastStore'
import type { EditConfig, EditingPreset, Region, RenderItem } from '../types'

const EFFECT_SHORT: Record<string, string> = {
  subtle_zoom: 'zoom', progressive_zoom: 'zoom progr.', punch_zoom: 'zoom rapido', caption_emphasis: 'enfasi', flash: 'flash', shake: 'shake',
}
const PRESET_SHORT: Record<string, string> = {
  gaming_dynamic: 'Gaming', sports_highlights: 'Sports', podcast_clean: 'Podcast', custom: 'Manuale',
}
// platform UI zones on 1080x1920 (same values the subtitle engine respects)
const SAFE = { top: 220 / 1920, bottom: 480 / 1920, side: 90 / 1080 }

export function RenderCard({ r, onDeleted, onRegenerate }: { r: RenderItem; onDeleted?: () => void; onRegenerate?: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const del = async () => {
    try { await api.deleteRender(r.id); toast.success('Render eliminato'); onDeleted?.() } catch (e) { toast.error(e) }
  }
  return (
    <article className="group">
      <div className="relative overflow-hidden rounded-md bg-black ring-1 ring-inset ring-graphite-800">
        {r.status === 'completed' ? (
          <video controls preload="none" poster={r.has_thumbnail ? api.renderThumbUrl(r.id) : undefined}
                 src={api.renderFileUrl(r.id)} className="aspect-[9/16] w-full bg-black object-contain" />
        ) : (
          <div className="grid aspect-[9/16] w-full place-items-center bg-graphite-900 p-3 text-center text-xs text-graphite-400">
            <div><StatusBadge status={r.status} /><p className="mt-2 line-clamp-4">{r.error ?? ''}</p></div>
          </div>
        )}
        {r.config.quality === 'draft' && <span className="absolute left-1.5 top-1.5 rounded-sm bg-black/75 px-1 font-mono text-[9px] uppercase tracking-wider text-warn">bozza</span>}
      </div>
      <div className="space-y-1.5 pt-2 text-xs">
        <div className="flex flex-wrap items-baseline gap-x-2 font-mono text-[10px] uppercase tracking-wider text-graphite-400">
          {r.stats.preset && <span className="text-tally-400">{PRESET_SHORT[r.stats.preset] ?? r.stats.preset}</span>}
          {r.duration && <span className="timecode text-bone-300">{r.duration.toFixed(1)}s</span>}
          {r.file_size && <span>{formatBytes(r.file_size)}</span>}
          {r.stats.speed_x && <span>{r.encoder.replace('h264_', '')} {r.stats.speed_x}×</span>}
        </div>
        {r.stats.plan && (
          <p className="text-graphite-400">
            {r.stats.plan.source === 'llm' ? 'AI' : 'Regole'}:{' '}
            {Object.entries(r.stats.plan.effects).map(([k, v]) => `${v}× ${EFFECT_SHORT[k] ?? k}`).join(', ') || 'nessun effetto'}
            {!!r.stats.sfx?.length && ` · ${r.stats.sfx.length} SFX`}{r.stats.logo && ' · logo'}{r.stats.tracking === 'faces' && ' · segue il volto'}
          </p>
        )}
        {!!r.stats.warnings?.length && <p className="text-warn">⚠ {r.stats.warnings.join(' · ')}</p>}
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {r.status === 'completed' && <>
            <a className="btn-cyan px-2 py-1 text-xs" href={api.renderFileUrl(r.id, true)}><Download size={12} /> MP4</a>
            <a className="btn-ghost px-2 py-1 text-xs" href={api.renderSubsUrl(r.id, 'srt')}>SRT</a>
          </>}
          {onRegenerate && r.status !== 'rendering' && <button className="btn-ghost px-2 py-1 text-xs" onClick={onRegenerate} title="Rigenera con le impostazioni correnti"><RefreshCw size={12} /> Rigenera</button>}
          {!confirm ? <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirm(true)} aria-label="Elimina render"><Trash2 size={12} /></button>
            : <button className="btn-danger px-2 py-1 text-xs" onClick={del}>Conferma</button>}
        </div>
      </div>
    </article>
  )
}

const TABS = [
  { id: 'preset', label: 'Preset', icon: Wand2 },
  { id: 'plan', label: 'Piano AI', icon: Sparkles },
  { id: 'frame', label: 'Inquadratura', icon: Crop },
  { id: 'subs', label: 'Sottotitoli', icon: Type },
  { id: 'audio', label: 'Audio', icon: Music2 },
  { id: 'brand', label: 'Logo e titoli', icon: Stamp },
  { id: 'output', label: 'Output', icon: Settings2 },
] as const

function typing(e: KeyboardEvent) {
  const el = e.target as HTMLElement
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

export function ClipEditor() {
  const [params, setParams] = useSearchParams()
  const { data: clips } = useApi(() => api.clips({ sort: 'score' }), [], 10000)
  const usable = useMemo(() => (clips ?? []).filter((c) => !['rejected', 'archived'].includes(c.status)), [clips])
  const clipId = params.get('clip') ?? usable[0]?.id ?? null
  const clip = clips?.find((c) => c.id === clipId) ?? null

  const [cfg, setCfg] = useState<EditConfig | null>(null)
  const [savedCfg, setSavedCfg] = useState<string>('')
  const [webcam, setWebcam] = useState<Region | null>(null)
  const [t, setT] = useState(0)
  const [preview, setPreview] = useState<string | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const [safeArea, setSafeArea] = useState(false)
  const [tab, setTab] = useState<string>('preset')
  const { data: presets } = useApi(() => api.subtitlePresets())
  const { data: editPresets } = useApi(() => api.editingPresets())
  const { data: brand } = useApi(() => api.brandKit())
  const { data: jobs, reload: reloadJobs } = useApi(
    () => (clip ? api.jobs({ video_id: clip.video_id, limit: 20 }) : Promise.resolve([])), [clip?.video_id], 1500)
  const renderJob = jobs?.find((j) => j.type === 'render.clip' && j.payload.clip_id === clipId && ['queued', 'running'].includes(j.status))
  const { data: renders, reload: reloadRenders } = useApi(
    () => (clipId ? api.renders({ clip_id: clipId, limit: 12 }) : Promise.resolve([])), [clipId, !!renderJob], renderJob ? 3000 : undefined)
  const abortRef = useRef<AbortController | null>(null)
  const { plan, stored, busy: planBusy, planJob } = usePlanPreview(clipId, cfg, jobs)

  useEffect(() => {
    if (!clipId) return
    setCfg(null); setPreview(null)
    api.editState(clipId).then((s) => { setCfg(s.config); setSavedCfg(JSON.stringify(s.config)); setWebcam(s.webcam_region) }).catch(toast.error)
  }, [clipId])
  useEffect(() => { if (clip) setT(Math.max(0, Math.min(clip.duration - 0.1, (clip.peak_time ?? clip.start + clip.duration / 2) - clip.start))) }, [clip?.id])

  // Debounced live preview of the composed 9:16 frame (unsaved config included)
  useEffect(() => {
    if (!cfg || !clipId) return
    const handle = setTimeout(async () => {
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac
      setPreviewBusy(true)
      try {
        const url = await api.previewFrame(clipId, t, cfg, ac.signal)
        setPreview((old) => { if (old) URL.revokeObjectURL(old); return url })
        setPreviewErr(null)
      } catch (e) {
        if ((e as Error).name !== 'AbortError') setPreviewErr((e as Error).message)
      } finally { if (!ac.signal.aborted) setPreviewBusy(false) }
    }, 350)
    return () => clearTimeout(handle)
  }, [cfg, t, clipId, webcam])

  const set = <K extends keyof EditConfig>(k: K, v: EditConfig[K]) => cfg && setCfg({ ...cfg, [k]: v })
  const dirty = cfg ? JSON.stringify(cfg) !== savedCfg : false
  const busyJob = !!renderJob || !!planJob

  const save = async () => {
    if (!cfg || !clipId) return
    try { const s = await api.saveEdit(clipId, cfg); setSavedCfg(JSON.stringify(s.config)); toast.success('Impostazioni salvate') } catch (e) { toast.error(e) }
  }
  const startRender = async (draft = false) => {
    if (!cfg || !clipId) return
    const conf = draft ? { ...cfg, quality: 'draft' as const } : cfg
    try {
      await api.render(clipId, conf)
      if (!draft) setSavedCfg(JSON.stringify(cfg))
      toast.info(draft ? 'Anteprima veloce in coda (qualità bozza)' : 'Render in coda')
      reloadJobs()
    } catch (e) { toast.error(e) }
  }
  const pickPreset = (p: EditingPreset) => cfg && setCfg({ ...cfg, ...p.config, preset: p.id })

  // keyboard: S save · P quick preview · R render · ←/→ scrub (Shift = 2 s)
  const keys = useRef({ save, startRender, dirty, busyJob, t, dur: clip?.duration ?? 0 })
  keys.current = { save, startRender, dirty, busyJob, t, dur: clip?.duration ?? 0 }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return
      const k = keys.current
      if (e.key === 's' && k.dirty) { e.preventDefault(); void k.save() }
      else if (e.key === 'p' && !k.busyJob) { e.preventDefault(); void k.startRender(true) }
      else if (e.key === 'r' && !k.busyJob) { e.preventDefault(); void k.startRender(false) }
      else if (e.key === 'ArrowLeft' && !(e.target as HTMLElement).closest('[role=slider]')) setT(Math.max(0, k.t - (e.shiftKey ? 2 : 0.5)))
      else if (e.key === 'ArrowRight' && !(e.target as HTMLElement).closest('[role=slider]')) setT(Math.min(k.dur - 0.1, k.t + (e.shiftKey ? 2 : 0.5)))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (clips && usable.length === 0) {
    return (
      <>
        <PageHeader title="Clip Editor" subtitle="Montaggio verticale automatico 1080×1920" />
        <EmptyState icon={<Clapperboard size={28} />} title="Nessuna clip da montare"
          text="Analizza un video in Clip Detection per ottenere le clip candidate." action={<Link to="/detection" className="btn-primary">Vai a Clip Detection</Link>} />
      </>
    )
  }

  const presetName = editPresets?.find((p) => p.id === cfg?.preset)?.name

  return (
    <>
      <PageHeader title="Clip Editor" subtitle="Scegli un preset: il planner decide il montaggio, tu rifinisci e controlli il risultato."
        actions={
          <select className="input w-full max-w-sm sm:w-auto" aria-label="Clip da montare" value={clipId ?? ''} onChange={(e) => setParams({ clip: e.target.value })}>
            {usable.map((c) => <option key={c.id} value={c.id}>{c.suggested_title.slice(0, 50)} · {c.video_title.slice(0, 24)}</option>)}
          </select>
        } />

      {(!clip || !cfg) && <Spinner />}
      {clip && cfg && (
        <div className="grid grid-cols-1 gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)] xl:gap-10">
          {/* ---------------------------------------------------------------- monitor (first on small screens) */}
          <div className="space-y-5 xl:sticky xl:top-20 xl:order-2 xl:self-start">
            <div className="flex flex-wrap items-center gap-2">
              <CategoryBadge category={clip.category} />
              <StatusBadge status={clip.status} />
              {presetName && <span className="font-mono text-[10px] uppercase tracking-wider text-tally-400">{presetName}</span>}
              {dirty && <span className="ml-auto font-mono text-[10px] uppercase tracking-wider text-warn">● non salvato</span>}
            </div>
            <div className="mx-auto w-full max-w-[340px]">
              <div className="relative aspect-[9/16] w-full overflow-hidden bg-black ring-1 ring-graphite-700">
                {preview && <img src={preview} alt={`Anteprima 9:16 a ${t.toFixed(1)} secondi`} className="h-full w-full object-contain" />}
                {safeArea && (
                  <div aria-hidden className="pointer-events-none absolute inset-0">
                    <div className="absolute inset-x-0 top-0 border-b border-dashed border-err/70 bg-err/10" style={{ height: `${SAFE.top * 100}%` }} />
                    <div className="absolute inset-x-0 bottom-0 border-t border-dashed border-err/70 bg-err/10" style={{ height: `${SAFE.bottom * 100}%` }} />
                    <div className="absolute right-0 border-l border-dashed border-err/60" style={{ top: `${SAFE.top * 100}%`, bottom: `${SAFE.bottom * 100}%`, width: `${SAFE.side * 100}%` }} />
                  </div>
                )}
                <div className="viewfinder pointer-events-none absolute inset-3" />
                <span className="timecode absolute left-3 top-3 rounded-sm bg-black/70 px-1.5 py-0.5 text-[11px] text-bone-100">
                  {formatTime(clip.start + t)}
                </span>
                {previewBusy && <span className="absolute right-3 top-3"><Spinner className="h-3.5 w-3.5" /></span>}
                {previewErr && <p className="absolute inset-x-3 bottom-3 rounded-sm bg-err-dim/95 p-1.5 text-xs text-bone-100">{previewErr}</p>}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between font-mono text-[11px] text-graphite-400">
                <span className="timecode text-bone-200">{t.toFixed(1)}s</span>
                <button className={cx('uppercase tracking-wider transition-colors', safeArea ? 'text-err' : 'hover:text-bone-200')} onClick={() => setSafeArea(!safeArea)} aria-pressed={safeArea}>
                  Safe area
                </button>
                <span className="timecode">{clip.duration.toFixed(1)}s</span>
              </div>
              <PlanStrip plan={plan} duration={clip.duration} t={t} onSeek={setT} />
              <p className="text-[11px] text-graphite-500">Trascina sulla timeline o usa <span className="kbd">←</span> <span className="kbd">→</span> per scorrere. Il fotogramma mostra le impostazioni correnti; zoom e suoni si vedono nel render.</p>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <button className="btn-ghost" disabled={!dirty} onClick={save} title="Salva (S)"><Save size={15} /> Salva</button>
              <button className="btn-cyan" disabled={busyJob} onClick={() => startRender(true)} title="Render veloce in bozza (P)"><Gauge size={15} /> Anteprima</button>
              <button className="btn-primary" disabled={busyJob} onClick={() => startRender(false)} title="Render finale (R)"><Film size={15} /> Render</button>
            </div>
            <p className="hidden gap-3 text-[11px] text-graphite-500 sm:flex">
              <span><span className="kbd">S</span> salva</span><span><span className="kbd">P</span> anteprima bozza</span><span><span className="kbd">R</span> render</span>
            </p>

            {(renderJob || planJob) && <div className="border-y border-graphite-800"><JobList jobs={[renderJob, planJob].filter((j): j is NonNullable<typeof j> => !!j)} onChange={reloadJobs} /></div>}

            <section aria-labelledby="bin-h">
              <div className="mb-3 flex items-center justify-between">
                <h2 id="bin-h" className="eyebrow text-bone-400">Render di questa clip</h2>
                <button className="rounded-sm p-1 text-graphite-400 transition-colors hover:text-bone-100" onClick={reloadRenders} aria-label="Aggiorna"><RefreshCw size={13} /></button>
              </div>
              {renders && renders.length === 0 && <p className="text-sm text-graphite-400">Nessun render: premi <b className="font-medium text-bone-200">Anteprima</b> per vedere il montaggio completo.</p>}
              <div className="grid grid-cols-2 gap-4">
                {renders?.slice(0, 4).map((r) => <RenderCard key={r.id} r={r} onDeleted={reloadRenders} onRegenerate={renderJob ? undefined : () => startRender(r.config.quality === 'draft')} />)}
              </div>
            </section>
          </div>

          {/* ---------------------------------------------------------------- settings */}
          <div className="min-w-0 xl:order-1">
            <div className="mb-5 border-l-2 border-graphite-700 pl-4">
              <h2 className="display text-xl leading-tight">{clip.suggested_title}</h2>
              <p className="timecode mt-1 text-xs text-graphite-400">
                {clip.video_title} · {formatTime(clip.start)} → {formatTime(clip.end)} · {clip.duration.toFixed(1)}s
              </p>
            </div>

            <Tabs value={tab} onValueChange={setTab} orientation="vertical" className="md:grid md:grid-cols-[168px_minmax(0,1fr)] md:gap-8">
              <TabsList aria-label="Impostazioni di montaggio"
                className="-mx-4 mb-5 overflow-x-auto px-4 data-[orientation=vertical]:flex-row md:mx-0 md:mb-0 md:px-0 md:data-[orientation=vertical]:flex-col md:self-start md:sticky md:top-20 max-md:border-b max-md:border-r-0">
                {TABS.map(({ id, label, icon: Icon }) => (
                  <TabsTrigger key={id} value={id} className="max-md:after:inset-x-3 max-md:after:inset-y-auto max-md:after:-bottom-px max-md:after:right-auto max-md:after:h-0.5 max-md:after:w-auto max-md:data-[state=active]:bg-transparent max-md:w-auto">
                    <Icon size={15} strokeWidth={1.75} />{label}
                    {id === 'plan' && plan && <span className="timecode ml-auto text-2xs text-graphite-500 max-md:hidden">{plan.segments.filter((s) => s.effect !== 'none').length}</span>}
                  </TabsTrigger>
                ))}
              </TabsList>

              <div className="min-w-0">
                <TabsContent value="preset" className="space-y-6">
                  <Section title="Preset di montaggio" right={<span className="text-xs text-graphite-500">modificabile dopo la scelta</span>}>
                    {editPresets ? <EditingPresetPicker presets={editPresets} value={cfg.preset} onPick={pickPreset} /> : <Spinner />}
                  </Section>
                  <Section title="Effetti">
                    <Slider label="Intensità" value={cfg.intensity} min={0} max={1} step={0.05} onChange={(v) => set('intensity', v)} fmt={(v) => `${Math.round(v * 100)}%`} />
                    <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                      <Toggle label="Zoom intelligenti" checked={cfg.zoom} onChange={(v) => set('zoom', v)} hint="Leggero, progressivo o rapido, momento per momento" />
                      <Toggle label="Effetti visivi (flash, shake)" checked={cfg.effects} onChange={(v) => set('effects', v)} hint="Solo sugli impatti più forti" />
                      <Toggle label="Evidenzia le parole chiave" checked={cfg.caption_emphasis} onChange={(v) => set('caption_emphasis', v)} />
                      <Toggle label="Effetti sonori contestuali" checked={cfg.sfx} onChange={(v) => set('sfx', v)} hint="Libreria inclusa (CC0) o tuoi file" />
                    </div>
                    {cfg.zoom && <Slider label="Zoom massimo" value={cfg.zoom_strength} min={1} max={1.6} step={0.01} onChange={(v) => set('zoom_strength', v)} fmt={(v) => `${v.toFixed(2)}×`} />}
                  </Section>
                </TabsContent>

                <TabsContent value="plan" className="space-y-6">
                  <Section title="AI Editing Planner" right={<span className="text-xs text-graphite-500">decide dove serve un effetto, e dove no</span>}>
                    <Segmented value={cfg.planner} onChange={(v) => set('planner', v)}
                      options={[{ value: 'auto', label: 'AI locale + regole' }, { value: 'rules', label: 'Solo regole (istantaneo)' }]} />
                    <PlanPanel clipId={clip.id} cfg={cfg} plan={plan} stored={stored} busy={planBusy} planJob={planJob} onJob={reloadJobs} />
                  </Section>
                </TabsContent>

                <TabsContent value="frame" className="space-y-6">
                  <Section title="Layout">
                    <LayoutPicker value={cfg.layout} hasWebcam={!!webcam} onChange={(l) => set('layout', l)} />
                    {cfg.layout === 'stack' && <Slider label="Altezza gameplay" value={cfg.stack_ratio} min={0.4} max={0.75} step={0.01} onChange={(v) => set('stack_ratio', v)} fmt={(v) => `${Math.round(v * 100)}%`} />}
                    {cfg.layout === 'pip' && (
                      <div className="flex flex-wrap items-center gap-3">
                        <Segmented value={cfg.pip_corner} onChange={(v) => set('pip_corner', v)}
                          options={[{ value: 'top-left', label: '↖' }, { value: 'top-right', label: '↗' }, { value: 'bottom-left', label: '↙' }, { value: 'bottom-right', label: '↘' }]} />
                        <div className="min-w-[220px] flex-1"><Slider label="Dimensione" value={cfg.pip_size} min={0.2} max={0.6} step={0.01} onChange={(v) => set('pip_size', v)} fmt={(v) => `${Math.round(v * 100)}%`} /></div>
                      </div>
                    )}
                  </Section>
                  <Section title="Inquadratura e movimento">
                    <Segmented value={cfg.crop_mode} onChange={(v) => set('crop_mode', v)}
                      options={[{ value: 'smart', label: 'Smart crop' }, { value: 'center', label: 'Centrale' }, { value: 'fit', label: 'Intero + sfondo sfocato' }]} />
                    {cfg.crop_mode === 'smart' && (
                      <div className="space-y-3">
                        <Segmented value={cfg.subject} onChange={(v) => set('subject', v)}
                          options={[{ value: 'action', label: 'Segue l\'azione' }, { value: 'faces', label: 'Segue lo speaker' }, { value: 'auto', label: 'Auto' }]} />
                        <Slider label="Velocità camera" value={cfg.follow_speed} min={0.5} max={2.5} step={0.1} onChange={(v) => set('follow_speed', v)} fmt={(v) => `${v.toFixed(1)}×`} />
                      </div>
                    )}
                    <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                      <Toggle label="Transizioni (fade, crossfade sui tagli)" checked={cfg.transitions} onChange={(v) => set('transitions', v)} />
                      {cfg.layout !== 'full' && <Toggle label="Escludi la webcam dal gameplay" checked={cfg.hide_webcam_in_gameplay} onChange={(v) => set('hide_webcam_in_gameplay', v)} />}
                    </div>
                  </Section>
                  <Section title="Webcam">
                    <WebcamSelector videoId={clip.video_id} t={clip.start + t} region={webcam} onSaved={setWebcam} />
                  </Section>
                </TabsContent>

                <TabsContent value="subs" className="space-y-6">
                  <Section title="Sottotitoli" right={<Link to={`/subtitles?clip=${clip.id}`} className="link text-xs"><Captions size={12} className="mr-1 inline" />Modifica testo</Link>}>
                    <Toggle label="Sottotitoli automatici" checked={cfg.subtitles} onChange={(v) => set('subtitles', v)} />
                    {cfg.subtitles && presets && <>
                      <PresetPicker presets={presets} value={cfg.subtitle_preset} onChange={(v) => set('subtitle_preset', v)} />
                      <Field label="Posizione">
                        <Segmented value={cfg.subtitle_position} onChange={(v) => set('subtitle_position', v)}
                          options={[{ value: 'auto', label: 'Auto' }, { value: 'top', label: 'Alto' }, { value: 'middle', label: 'Centro' }, { value: 'bottom', label: 'Basso' }]} />
                      </Field>
                      <Slider label="Dimensione" value={cfg.subtitle_scale} min={0.6} max={1.6} step={0.05} onChange={(v) => set('subtitle_scale', v)} fmt={(v) => `${Math.round(v * 100)}%`} />
                      <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                        <Toggle label="Evidenzia la parola pronunciata" checked={cfg.highlight_words} onChange={(v) => set('highlight_words', v)} />
                        <Toggle label="Evidenzia le parole chiave" checked={cfg.caption_emphasis} onChange={(v) => set('caption_emphasis', v)} hint="Scelte dal planner, colore dedicato" />
                      </div>
                    </>}
                  </Section>
                </TabsContent>

                <TabsContent value="audio" className="space-y-6">
                  <Section title="Audio">
                    <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                      <Toggle label={`Normalizza loudness (${cfg.target_lufs} LUFS)`} checked={cfg.normalize_audio} onChange={(v) => set('normalize_audio', v)} hint="Standard social: −14 LUFS" />
                      <Toggle label="Riduzione rumore (FFT)" checked={cfg.denoise} onChange={(v) => set('denoise', v)} />
                      <Toggle label="Taglia i silenzi" checked={cfg.remove_silences} onChange={(v) => set('remove_silences', v)} hint="Le pause drammatiche prima di una battuta restano" />
                    </div>
                    {cfg.remove_silences && <>
                      <Segmented value={cfg.silence_strategy} onChange={(v) => set('silence_strategy', v)}
                        options={[{ value: 'quiet', label: 'Solo pause silenziose' }, { value: 'no_speech', label: 'Ogni pausa nel parlato' }]} />
                      <Slider label="Pausa minima" value={cfg.min_silence_s} min={0.3} max={3} step={0.1} onChange={(v) => set('min_silence_s', v)} fmt={(v) => `${v.toFixed(1)}s`} />
                    </>}
                  </Section>
                  <Section title="Effetti sonori">
                    <Toggle label="Effetti sonori contestuali" checked={cfg.sfx} onChange={(v) => set('sfx', v)} hint="Solo dove il planner li ritiene utili; cartella data/sfx/ per i tuoi file" />
                    {cfg.sfx && <Slider label="Volume SFX" value={cfg.sfx_volume} min={0} max={1} step={0.05} onChange={(v) => set('sfx_volume', v)} fmt={(v) => `${Math.round(v * 100)}%`} />}
                  </Section>
                </TabsContent>

                <TabsContent value="brand" className="space-y-6">
                  <Section title="Logo (Brand Kit)" right={<Link to="/brand-kit" className="link text-xs">Gestisci logo</Link>}>
                    {brand?.logo ? (
                      <div className="flex items-center gap-4">
                        <img src={brand.logo.url} alt="Logo" className="h-12 w-auto rounded-sm bg-[repeating-conic-gradient(#2c2a27_0_25%,#1d1c1a_0_50%)] bg-[length:12px_12px] p-1.5" />
                        <div className="flex-1">
                          <Toggle label="Applica il logo a questa clip" checked={cfg.logo} onChange={(v) => set('logo', v)}
                            hint={brand.settings.enabled ? `${brand.settings.position} · opacità ${Math.round(brand.settings.opacity * 100)}%` : 'Logo disattivato nel Brand Kit'} />
                        </div>
                      </div>
                    ) : <p className="text-sm text-graphite-400">Nessun logo: caricalo nel <Link to="/brand-kit" className="link">Brand Kit</Link>.</p>}
                  </Section>
                  <Section title="Intro e outro">
                    <div className="grid gap-6 sm:grid-cols-2">
                      <div className="space-y-2.5">
                        <Toggle label="Intro con titolo" checked={cfg.intro} onChange={(v) => set('intro', v)} />
                        {cfg.intro && <input className="input" aria-label="Testo intro" placeholder={clip.suggested_title} value={cfg.intro_text} maxLength={120} onChange={(e) => set('intro_text', e.target.value)} />}
                      </div>
                      <div className="space-y-2.5">
                        <Toggle label="Outro con call to action" checked={cfg.outro} onChange={(v) => set('outro', v)} />
                        {cfg.outro && <input className="input" aria-label="Testo outro" value={cfg.outro_text} maxLength={120} onChange={(e) => set('outro_text', e.target.value)} />}
                      </div>
                    </div>
                  </Section>
                </TabsContent>

                <TabsContent value="output" className="space-y-6">
                  <Section title="Output · 1080×1920 · H.264 / AAC">
                    <Field label="Frame rate">
                      <Segmented value={cfg.fps} onChange={(v) => set('fps', v)}
                        options={[{ value: 'auto', label: 'Come la sorgente' }, { value: 24, label: '24' }, { value: 25, label: '25' }, { value: 30, label: '30' }, { value: 50, label: '50' }, { value: 60, label: '60' }]} />
                    </Field>
                    <Field label="Qualità">
                      <Segmented value={cfg.quality} onChange={(v) => set('quality', v)} options={[{ value: 'draft', label: 'Bozza' }, { value: 'standard', label: 'Standard' }, { value: 'high', label: 'Alta' }]} />
                    </Field>
                  </Section>
                </TabsContent>
              </div>
            </Tabs>
          </div>
        </div>
      )}
    </>
  )
}
