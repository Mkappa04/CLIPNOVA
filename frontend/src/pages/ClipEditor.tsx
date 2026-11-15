import { Captions, Clapperboard, Download, Film, RefreshCw, Save, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { LayoutPicker, PresetPicker, Section, Segmented, Slider, Toggle, WebcamSelector } from '../components/EditorControls'
import { JobList } from '../components/JobList'
import { CategoryBadge } from '../components/TimelineChart'
import { EmptyState, Field, PageHeader, Spinner, StatusBadge } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { formatBytes, formatTime } from '../services/format'
import { toast } from '../stores/toastStore'
import type { EditConfig, Region, RenderItem } from '../types'

export function RenderCard({ r, onDeleted }: { r: RenderItem; onDeleted?: () => void }) {
  const [confirm, setConfirm] = useState(false)
  const del = async () => {
    try { await api.deleteRender(r.id); toast.success('Render eliminato'); onDeleted?.() } catch (e) { toast.error(e) }
  }
  return (
    <div className="card overflow-hidden">
      {r.status === 'completed' ? (
        <video controls preload="none" poster={r.has_thumbnail ? api.renderThumbUrl(r.id) : undefined}
               src={api.renderFileUrl(r.id)} className="aspect-[9/16] w-full bg-black object-contain" />
      ) : (
        <div className="grid aspect-[9/16] w-full place-items-center bg-ink-850 p-3 text-center text-xs text-zinc-400">
          <div><StatusBadge status={r.status} /><p className="mt-2">{r.error ?? ''}</p></div>
        </div>
      )}
      <div className="space-y-1.5 p-2.5 text-xs">
        <div className="truncate font-medium text-zinc-100" title={r.clip_title}>{r.clip_title || r.video_title}</div>
        <div className="flex flex-wrap gap-x-2 text-zinc-500">
          <span>{r.config.layout}</span>
          {r.duration && <span>{r.duration.toFixed(1)}s</span>}
          {r.file_size && <span>{formatBytes(r.file_size)}</span>}
          {r.stats.speed_x && <span>{r.encoder.replace('h264_', '')} {r.stats.speed_x}x</span>}
        </div>
        {!!r.stats.warnings?.length && <p className="text-amber-300">⚠ {r.stats.warnings.join(' · ')}</p>}
        <div className="flex flex-wrap gap-1.5 pt-1">
          {r.status === 'completed' && <>
            <a className="btn-cyan px-2 py-1 text-xs" href={api.renderFileUrl(r.id, true)}><Download size={12} /> MP4</a>
            <a className="btn-ghost px-2 py-1 text-xs" href={api.renderSubsUrl(r.id, 'srt')}>SRT</a>
          </>}
          {!confirm ? <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirm(true)} aria-label="Elimina render"><Trash2 size={12} /></button>
            : <button className="btn-danger px-2 py-1 text-xs" onClick={del}>Conferma eliminazione</button>}
        </div>
      </div>
    </div>
  )
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
  const { data: presets } = useApi(() => api.subtitlePresets())
  const { data: jobs, reload: reloadJobs } = useApi(
    () => (clip ? api.jobs({ video_id: clip.video_id, limit: 20 }) : Promise.resolve([])), [clip?.video_id], 1500)
  const renderJob = jobs?.find((j) => j.type === 'render.clip' && j.payload.clip_id === clipId && ['queued', 'running'].includes(j.status))
  const { data: renders, reload: reloadRenders } = useApi(
    () => (clipId ? api.renders({ clip_id: clipId, limit: 12 }) : Promise.resolve([])), [clipId, !!renderJob], renderJob ? 3000 : undefined)
  const abortRef = useRef<AbortController | null>(null)

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

  if (clips && usable.length === 0) {
    return (
      <>
        <PageHeader title="Clip Editor" subtitle="Montaggio verticale automatico 1080×1920" />
        <EmptyState icon={<Clapperboard size={28} />} title="Nessuna clip da montare"
          text="Analizza un video in Clip Detection per ottenere le clip candidate." action={<Link to="/detection" className="btn-primary">Vai a Clip Detection</Link>} />
      </>
    )
  }

  const set = <K extends keyof EditConfig>(k: K, v: EditConfig[K]) => cfg && setCfg({ ...cfg, [k]: v })
  const dirty = cfg ? JSON.stringify(cfg) !== savedCfg : false

  const save = async () => {
    if (!cfg || !clipId) return
    try { const s = await api.saveEdit(clipId, cfg); setSavedCfg(JSON.stringify(s.config)); toast.success('Impostazioni salvate') } catch (e) { toast.error(e) }
  }
  const startRender = async () => {
    if (!cfg || !clipId) return
    try { await api.render(clipId, cfg); setSavedCfg(JSON.stringify(cfg)); toast.info('Render in coda'); reloadJobs() } catch (e) { toast.error(e) }
  }

  return (
    <>
      <PageHeader title="Clip Editor" subtitle="Montaggio verticale 1080×1920 · H.264/AAC · layout, smart crop, zoom, sottotitoli, audio"
        actions={
          <select className="input w-auto max-w-sm" value={clipId ?? ''} onChange={(e) => setParams({ clip: e.target.value })}>
            {usable.map((c) => <option key={c.id} value={c.id}>{c.suggested_title.slice(0, 50)} · {c.video_title.slice(0, 24)}</option>)}
          </select>
        } />

      {(!clip || !cfg) && <Spinner />}
      {clip && cfg && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="card space-y-4 p-4">
            <div className="flex flex-wrap items-center gap-2 border-b border-ink-700 pb-3">
              <CategoryBadge category={clip.category} />
              <StatusBadge status={clip.status} />
              <span className="text-sm text-zinc-300">{clip.video_title}</span>
              <span className="ml-auto font-mono text-xs text-zinc-500">{formatTime(clip.start)} → {formatTime(clip.end)} · {clip.duration.toFixed(1)}s</span>
            </div>

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

            <Section title="Webcam">
              <WebcamSelector videoId={clip.video_id} t={clip.start + t} region={webcam} onSaved={setWebcam} />
            </Section>

            <Section title="Inquadratura e movimento">
              <Segmented value={cfg.crop_mode} onChange={(v) => set('crop_mode', v)}
                options={[{ value: 'smart', label: 'Smart crop (segue l\'azione)' }, { value: 'center', label: 'Centrale' }, { value: 'fit', label: 'Intero + sfondo sfocato' }]} />
              <div className="grid gap-2 sm:grid-cols-2">
                <Toggle label="Zoom dinamici sui picchi" checked={cfg.zoom} onChange={(v) => set('zoom', v)} />
                <Toggle label="Transizioni (fade, crossfade sui tagli)" checked={cfg.transitions} onChange={(v) => set('transitions', v)} />
                {cfg.layout !== 'full' && <Toggle label="Escludi la webcam dal gameplay" checked={cfg.hide_webcam_in_gameplay} onChange={(v) => set('hide_webcam_in_gameplay', v)} />}
              </div>
              {cfg.zoom && <Slider label="Intensità zoom" value={cfg.zoom_strength} min={1} max={1.6} step={0.01} onChange={(v) => set('zoom_strength', v)} fmt={(v) => `${v.toFixed(2)}x`} />}
            </Section>

            <Section title="Sottotitoli" right={<Link to={`/subtitles?clip=${clip.id}`} className="text-xs text-pulse-400 hover:underline"><Captions size={12} className="mr-1 inline" />Modifica testo</Link>}>
              <Toggle label="Sottotitoli automatici" checked={cfg.subtitles} onChange={(v) => set('subtitles', v)} />
              {cfg.subtitles && presets && <>
                <PresetPicker presets={presets} value={cfg.subtitle_preset} onChange={(v) => set('subtitle_preset', v)} />
                <div className="flex flex-wrap items-center gap-3">
                  <Segmented value={cfg.subtitle_position} onChange={(v) => set('subtitle_position', v)}
                    options={[{ value: 'auto', label: 'Auto' }, { value: 'top', label: 'Alto' }, { value: 'middle', label: 'Centro' }, { value: 'bottom', label: 'Basso' }]} />
                  <Toggle label="Evidenzia parola" checked={cfg.highlight_words} onChange={(v) => set('highlight_words', v)} />
                </div>
                <Slider label="Dimensione testo" value={cfg.subtitle_scale} min={0.6} max={1.6} step={0.05} onChange={(v) => set('subtitle_scale', v)} fmt={(v) => `${Math.round(v * 100)}%`} />
              </>}
            </Section>

            <Section title="Audio">
              <div className="grid gap-2 sm:grid-cols-2">
                <Toggle label={`Normalizza loudness (${cfg.target_lufs} LUFS)`} checked={cfg.normalize_audio} onChange={(v) => set('normalize_audio', v)} hint="Standard social: −14 LUFS" />
                <Toggle label="Riduzione rumore (FFT)" checked={cfg.denoise} onChange={(v) => set('denoise', v)} />
                <Toggle label="Taglia i silenzi" checked={cfg.remove_silences} onChange={(v) => set('remove_silences', v)} hint="Usa i timestamp della trascrizione" />
              </div>
              {cfg.remove_silences && <>
                <Segmented value={cfg.silence_strategy} onChange={(v) => set('silence_strategy', v)}
                  options={[{ value: 'quiet', label: 'Solo pause silenziose' }, { value: 'no_speech', label: 'Ogni pausa nel parlato' }]} />
                <Slider label="Pausa minima" value={cfg.min_silence_s} min={0.3} max={3} step={0.1} onChange={(v) => set('min_silence_s', v)} fmt={(v) => `${v.toFixed(1)}s`} />
              </>}
            </Section>

            <Section title="Intro e outro">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Toggle label="Intro con titolo" checked={cfg.intro} onChange={(v) => set('intro', v)} />
                  {cfg.intro && <input className="input" placeholder={clip.suggested_title} value={cfg.intro_text} maxLength={120} onChange={(e) => set('intro_text', e.target.value)} />}
                </div>
                <div className="space-y-2">
                  <Toggle label="Outro con call to action" checked={cfg.outro} onChange={(v) => set('outro', v)} />
                  {cfg.outro && <input className="input" value={cfg.outro_text} maxLength={120} onChange={(e) => set('outro_text', e.target.value)} />}
                </div>
              </div>
            </Section>

            <Section title="Output">
              <div className="flex flex-wrap gap-4">
                <Field label="FPS"><Segmented value={cfg.fps} onChange={(v) => set('fps', v)} options={[{ value: 30, label: '30' }, { value: 60, label: '60' }]} /></Field>
                <Field label="Qualità"><Segmented value={cfg.quality} onChange={(v) => set('quality', v)} options={[{ value: 'draft', label: 'Bozza' }, { value: 'standard', label: 'Standard' }, { value: 'high', label: 'Alta' }]} /></Field>
              </div>
            </Section>
          </div>

          {/* preview + render */}
          <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
            <div className="card p-4">
              <div className="relative mx-auto aspect-[9/16] w-full max-w-[320px] overflow-hidden rounded-xl bg-black ring-1 ring-ink-600">
                {preview && <img src={preview} alt="Anteprima 9:16" className="h-full w-full object-contain" />}
                {previewBusy && <div className="absolute right-2 top-2"><Spinner /></div>}
                {previewErr && <p className="absolute inset-x-2 bottom-2 rounded bg-red-500/80 p-1.5 text-xs text-white">{previewErr}</p>}
              </div>
              <div className="mx-auto mt-3 max-w-[320px]">
                <Slider label="Istante" value={t} min={0} max={Math.max(0.1, clip.duration - 0.1)} step={0.1} onChange={setT} fmt={(v) => `${v.toFixed(1)}s`} />
                <p className="mt-1 text-[11px] text-zinc-500">Anteprima di un singolo fotogramma con le impostazioni correnti (anche non salvate). Gli zoom dinamici si vedono nel render.</p>
              </div>
              <div className="mt-4 flex gap-2">
                <button className="btn-ghost flex-1" disabled={!dirty} onClick={save}><Save size={15} /> Salva</button>
                <button className="btn-primary flex-1" disabled={!!renderJob} onClick={startRender}><Film size={15} /> Render</button>
              </div>
            </div>

            {renderJob && <div className="card px-4"><JobList jobs={[renderJob]} onChange={reloadJobs} /></div>}

            <div className="card p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-display font-semibold text-white">Render di questa clip</h3>
                <button className="btn-ghost px-2 py-1 text-xs" onClick={reloadRenders} aria-label="Aggiorna"><RefreshCw size={13} /></button>
              </div>
              {renders && renders.length === 0 && <p className="text-sm text-zinc-500">Nessun render ancora.</p>}
              <div className="grid grid-cols-2 gap-3">
                {renders?.slice(0, 4).map((r) => <RenderCard key={r.id} r={r} onDeleted={reloadRenders} />)}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
